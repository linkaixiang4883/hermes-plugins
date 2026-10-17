"""model-audit agent 半单测（不需要真 agent）。
    "$VENV" tests/test_agent_half.py
"""
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 测试必须隔离 DB：否则 install_capture()/on_post_api_request() 会写进**真实**插件库。
os.environ["MODEL_AUDIT_DB"] = str(Path(tempfile.mkdtemp(prefix="ma-agent-db-")) / "t.db")
# 以 package 形式加载（与 Hermes 真实加载器一致：submodule_search_locations 指向插件目录），
# 这样 __init__.py 里的 `from . import model_audit_core` 才能解析。
PKG = "model_audit_pkg"
spec = importlib.util.spec_from_file_location(PKG, ROOT / "__init__.py",
                                              submodule_search_locations=[str(ROOT)])
mod = importlib.util.module_from_spec(spec)
sys.modules[PKG] = mod
spec.loader.exec_module(mod)

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        failures.append(name)


class FakeHTTP:
    def __init__(self): self.event_hooks = {"response": []}


class FakeClient:
    def __init__(self): self._client = FakeHTTP()


class FakeAgent:
    session_id = "s1"


class FakeResp:
    status_code = 200
    headers = {"x-opencode-upstream-model-id": "deepseek/deepseek-v4.1-flash",
               "Authorization": "Bearer SECRET", "cf-ray": "abc-LAX"}


ok = mod.install_capture()
check("install_capture 返回 bool", isinstance(ok, bool), repr(ok))
try:
    from agent import served_model as _sm  # noqa: F401
    check("真实核心可打补丁 → True", ok is True, repr(ok))
except Exception:
    print("SKIP  真实核心不可导入（非 Hermes venv 环境），跳过 True 断言")

agent, client = FakeAgent(), FakeClient()
mod._wrap_install_served_model_capture(agent, client)
hooks = client._client.event_hooks["response"]
check("钩子被追加", len(hooks) == 1, str(len(hooks)))
hooks[0](FakeResp())
hdrs = mod._LAST_BY_SESSION.get("s1", (0, {}))[1]
check("抓到上游 model", hdrs.get("x-opencode-upstream-model-id") == "deepseek/deepseek-v4.1-flash")
check("白名单外不落（Authorization）", "authorization" not in {k.lower() for k in hdrs})
check("cf-ray 在白名单内", "cf-ray" in hdrs)
check("agent 注册表命中", mod._AGENTS.get("s1") is agent)
check("客户端→agent 映射命中", mod._CLIENT_AGENT.get(client._client) is agent)
check("缺失目标 → False 不抛", mod._try_patch_served_model({"install_served_model_capture": None}) is False)
try:
    mod.on_post_api_request(session_id="s1", model="m", provider="p", usage={}, started_at=time.time())
    check("hook 回调不抛", True)
except Exception as exc:
    check("hook 回调不抛", False, repr(exc))


# --- 压缩回归（2026-09-24 实测）：客户端被**新 agent** 复用 ---
# 压缩会新建子会话/新 agent，而 httpx 客户端可能复用；旧实现闭包固定首次安装的 agent，
# 会一直往旧对象写 → 新会话整片「无信号」。现在必须按**当前** agent 的 session_id 定槽。
class FakeAgent2:
    session_id = "s2"


agent2 = FakeAgent2()
mod._wrap_install_served_model_capture(agent2, client)          # 同一个 client，换 agent
check("复用客户端：不重复追加钩子", len(client._client.event_hooks["response"]) == 1,
      str(len(client._client.event_hooks["response"])))
client._client.event_hooks["response"][0](FakeResp())
check("复用客户端：新头归当前 agent 的 session",
      mod._LAST_BY_SESSION.get("s2", (0, {}))[1].get("x-opencode-upstream-model-id")
      == "deepseek/deepseek-v4.1-flash", str(sorted(mod._LAST_BY_SESSION)))
check("复用客户端：映射已刷新", mod._CLIENT_AGENT.get(client._client) is agent2)

# --- 一次性消费 + 时间窗校验 ---
now = time.time()
mod._LAST_BY_SESSION["s3"] = (now, {"x-opencode-upstream-model-id": "m/served"})
h1, t1 = mod._consume("s3", {"started_at": now - 1, "ended_at": now + 1})
check("消费：窗口内取到", h1 is not None and t1 is not None, str(h1))
h2, _ = mod._consume("s3", {"started_at": now - 1, "ended_at": now + 1})
check("消费：一次性（第二次为空）", h2 is None)
mod._LAST_BY_SESSION["s4"] = (now - 600, {"x-opencode-upstream-model-id": "m/old"})
h3, _ = mod._consume("s4", {"started_at": now, "ended_at": now + 1})
check("消费：窗口外拒绝（防陈旧错配）", h3 is None)
mod._LAST_BY_SESSION["s5"] = (now, {})
h4, _ = mod._consume("s5", {"started_at": now - 1, "ended_at": now + 1})
check("消费：空头 → 无信号", h4 is None)
mod._LAST_BY_SESSION["s6"] = (now, {"x-opencode-upstream-model-id": "m/x"})
h5, _ = mod._consume("", {"started_at": now - 1, "ended_at": now + 1})
check("消费：无 session_id → 不消费任何槽", h5 is None and "s6" in mod._LAST_BY_SESSION)

# 多 profile：hook 必须用"上下文局部 home"（多 profile 网关按轮次绑定），不是进程 env
import hermes_constants  # noqa: E402
import sqlite3  # noqa: E402

tmp_home = Path(tempfile.mkdtemp(prefix="ma-prof-"))
_token = hermes_constants.set_hermes_home_override(str(tmp_home))
try:
    mod.on_post_api_request(session_id="s1", model="m2", provider="p2", usage={},
                            started_at=time.time(), api_duration=0.1)
finally:
    hermes_constants.reset_hermes_home_override(_token)
with sqlite3.connect(os.environ["MODEL_AUDIT_DB"]) as _c:
    _row = _c.execute("select profile_home, profile_name from calls order by id desc limit 1").fetchone()
check("多 profile：profile_home 用上下文局部 home", bool(_row) and str(tmp_home) in str(_row[0]), str(_row))
check("多 profile：profile_name 非空", bool(_row) and bool(_row[1]), str(_row))
check("agent 半不做自动清理（无 prune 调用）",
      "prune" not in (ROOT / "__init__.py").read_text(encoding="utf-8"))

print()
print("FAILED:", failures if failures else "none")
sys.exit(1 if failures else 0)
