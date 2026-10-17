"""opencode-go-usage 离线单测（注册表版）。

运行（用 Hermes 自带 venv）：
    "C:/Users/<you>/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe" tests/test_plugin_api.py

覆盖：
  ① 路由与取数（真实端点，会发一次网络请求）
  ② 错误映射（401 / 403 / 网络）
  ③ 无 key
  ④ 冷却选择逻辑（跳过冷却 / 全冷却取最早解冻 / 到期回归 / TTL 对齐 Hermes）
  ⑤ 提供商注册表接缝（未知 provider、balance 型 provider 整链路）
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

PLUGIN = Path(__file__).resolve().parent.parent / "dashboard" / "plugin_api.py"
assert PLUGIN.is_file(), f"plugin_api.py not found at {PLUGIN}"

spec = importlib.util.spec_from_file_location("ocgo_usage", PLUGIN)
m = importlib.util.module_from_spec(spec)
sys.modules["ocgo_usage"] = m
spec.loader.exec_module(m)

client = TestClient(FastAPI())
client.app.include_router(m.router)

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        failures.append(name)


print("== 环境 ==")
print("  hermes credential_pool 常量复用:", m._hermes_pool is not None)
print("  PROVIDERS:", sorted(m.PROVIDERS), "| default:", m.DEFAULT_PROVIDER)

print("\n== ① 路由与取数（真实端点） ==")
r = client.get("/usage?force=1").json()
print("  ", json.dumps({k: r.get(k) for k in ("ok", "fetchedAt", "poolSize", "availableCount")}, ensure_ascii=False))
if r.get("ok"):
    print("   provider:", r.get("provider"))
    print("   key:", {k: r["key"].get(k) for k in ("id", "label", "poolStatus", "requestCount", "fallback")})
    print("   windows:", json.dumps(r.get("windows"), ensure_ascii=False))
    check("① ok=true", r.get("ok") is True)
    check("① provider.kind=windows", r["provider"]["kind"] == "windows")
    wins = r.get("windows") or []
    check("① 三个窗口 id 正确", [w["id"] for w in wins] == ["rolling", "weekly", "monthly"])
    check("① 窗口字段齐全", all(set(("id", "label", "percent", "status", "resetsAt")) <= set(w) for w in wins))
    print("   百分比:", [w["percent"] for w in wins], "（对照 console 网页，允许 ±1 取整差）")
else:
    check("① ok=true", False, str(r))

print("\n== ①b Command Code GOAT（真实端点） ==")
rc = client.get("/usage?provider=commandcode-goat&force=1").json()
print("  ", json.dumps({k: rc.get(k) for k in ("ok", "fetchedAt", "poolSize", "availableCount")}, ensure_ascii=False))
if rc.get("ok"):
    print("   provider:", rc.get("provider"))
    print("   key:", {k: rc["key"].get(k) for k in ("id", "label", "poolStatus", "fallback")})
    print("   windows:", json.dumps(rc.get("windows"), ensure_ascii=False))
    wins = rc.get("windows") or []
    check("①b ok=true", rc.get("ok") is True)
    check("①b provider.kind=windows / short=GOAT",
          rc["provider"]["kind"] == "windows" and rc["provider"]["short"] == "GOAT", str(rc.get("provider")))
    check("①b 前两个窗口 rolling/weekly", [w["id"] for w in wins][:2] == ["rolling", "weekly"], str([w["id"] for w in wins]))
    check("①b 百分比 0..100", bool(wins) and all(0 <= w["percent"] <= 100 for w in wins), str([w["percent"] for w in wins]))
    check("①b resetAt 为 ISO（毫秒已换算）",
          all((w.get("resetsAt") or "").endswith("Z") and "T" in (w.get("resetsAt") or "") for w in wins),
          str([w.get("resetsAt") for w in wins]))
else:
    check("①b ok=true", False, str(rc))

print("\n== ④ 冷却选择逻辑（合成池） ==")
now = 1_000_000.0
cooling = {
    "id": "a", "label": "A", "secret": "sk-a", "last_status": "exhausted",
    "last_status_at": now - 100, "last_error_code": 429, "last_error_reset_at": None,
    "failure_reason": None, "request_count": 0,
}
healthy = {
    "id": "b", "label": "B", "secret": "sk-b", "last_status": "ok",
    "last_status_at": None, "last_error_code": None, "last_error_reset_at": None,
    "failure_reason": None, "request_count": 1,
}
active, all_cooling, avail = m._select_active([cooling, healthy], now)
check("④ 跳过冷却中的 key", active["id"] == "b" and not all_cooling and avail == 1, f"active={active['id']}")
cool_a = {**cooling, "id": "a", "last_status_at": now - 5, "request_count": 0}
cool_b = {**cooling, "id": "b", "last_status_at": now - 10, "request_count": 0}
active2, all_cooling2, avail2 = m._select_active([cool_a, cool_b], now)
check("④ 全冷却取最早解冻", active2["id"] == "b" and all_cooling2 and avail2 == 0, f"active={active2['id']}")
active3, _, _ = m._select_active([cooling, healthy], now + 60 * 60 + 1)
check("④ 冷却到期后回到优先位", active3["id"] == "a", f"active={active3['id']}")
check("④ TTL 常量对齐(429→3600s)", m._ttl_seconds(429, None, False) == 3600)
check("④ TTL 常量对齐(401→300s)", m._ttl_seconds(401, None, False) == 300)
check("④ TTL 单 key 兜底(60s)", m._ttl_seconds(429, None, True) == 60)

print("\n== ② 错误映射（monkeypatch 401 / 403 / 网络） ==")
m.CACHE.clear()
orig_http = m._http_json

def fake_401(url, secret, ua):
    return None, {"kind": "unauthorized", "message": "HTTP 401"}

m._http_json = fake_401
r2 = client.get("/usage?force=1").json()
check("② 401→unauthorized", r2["key"]["error"]["kind"] == "unauthorized", str(r2["key"]["error"]))
check("② 失败时 windows=null", r2.get("windows") is None)

def fake_403(url, secret, ua):
    return None, {"kind": "entitlement", "message": "HTTP 403"}

m._http_json = fake_403
r3 = client.get("/usage?force=1").json()
check("② 403→entitlement", r3["key"]["error"]["kind"] == "entitlement")

def fake_net(url, secret, ua):
    return None, {"kind": "network", "message": "URLError"}

m._http_json = fake_net
r4 = client.get("/usage?force=1").json()
check("② 网络错→network", r4["key"]["error"]["kind"] == "network")
check("② 失败也有 key 信息", r4["key"]["label"] != "" and r4["key"]["fallback"] is False)

m._http_json = orig_http

print("\n== ③ 无 key ==")
orig_pool, orig_env = m._pool_entries, m._env_entry_for
m._pool_entries = lambda auth, spec: []
m._env_entry_for = lambda spec: None
r5 = client.get("/usage?force=1").json()
check("③ ok=false / no_key", r5.get("ok") is False and r5["error"]["kind"] == "no_key", str(r5))
m._pool_entries, m._env_entry_for = orig_pool, orig_env

print("\n== ⑤ 提供商注册表接缝 ==")
r6 = client.get("/usage?provider=nope&force=1").json()
check("⑤ 未知 provider 报错", r6.get("ok") is False and r6["error"]["kind"] == "unknown_provider", str(r6.get("error")))

os.environ["FAKE_BAL_KEY"] = "sk-fake-bal"

def fake_balance(secret):
    return {"balance": {"value": 12.34, "unit": "USD"}}, None

m.PROVIDERS["fake-balance"] = m.ProviderSpec(
    id="fake-balance", display="Fake Balance", short="FB", kind="balance",
    key_envs=("FAKE_BAL_KEY",), pool_provider=None, fetch=fake_balance,
)
r7 = client.get("/usage?provider=fake-balance&force=1").json()
check("⑤ balance 型 provider 链路", r7.get("ok") is True and r7["provider"]["kind"] == "balance"
      and r7["balance"] == {"value": 12.34, "unit": "USD"} and r7.get("windows") is None, str(r7.get("balance")))
del m.PROVIDERS["fake-balance"]
os.environ.pop("FAKE_BAL_KEY", None)

print("\n== ⑥ 模型门控 /gate ==")
orig_sess, orig_conf = m._session_provider, m._config_provider

# (a) 前缀就是受支持套餐的 provider → 立即命中（契约示例形态）
g1 = client.get("/gate?model=opencode-go/deepseek-v4.1-flash").json()
check("⑥ 前缀 opencode-go → matched", g1["matched"] is True and g1["provider"] == "opencode-go"
      and g1["resolvedFrom"] == "prefix", str(g1))
g2 = client.get("/gate?model=commandcode-goat/deepseek-v4.1-flash").json()
check("⑥ 前缀 commandcode-goat → matched", g2["matched"] is True and g2["provider"] == "commandcode-goat", str(g2))

# (b) 关键回归：Command Code 目录的 slug 是「厂商/模型」（deepseek/deepseek-v4.1-flash），
#     首段是模型厂商名而不是 provider 名 —— 不能被它骗到 'deepseek' 上而藏掉 GOAT 芯片
m._session_provider = lambda sid: "commandcode" if sid else None
m._config_provider = lambda: "ollama-local"
g3 = client.get("/gate?model=deepseek/deepseek-v4.1-flash&session=abc123").json()
check("⑥ 厂商前缀不被当 provider（会话 commandcode）", g3["matched"] is True
      and g3["provider"] == "commandcode-goat" and g3["resolvedFrom"] == "session", str(g3))

# (c) 同一 slug 但会话在 zen → 不显示（前缀≠provider 的判读要保持一致）
m._session_provider = lambda sid: "opencode-zen"
g4 = client.get("/gate?model=deepseek/deepseek-v4.1-flash&session=abc123").json()
check("⑥ 厂商前缀 + 会话 zen → 不显示", g4["matched"] is False
      and g4["resolvedProvider"] == "opencode-zen", str(g4))

# (d) 无会话（草稿态）→ 配置兜底
m._session_provider = lambda sid: None
m._config_provider = lambda: "commandcode"
g5 = client.get("/gate?model=deepseek/deepseek-v4.1-flash").json()
check("⑥ 配置兜底(commandcode) → matched", g5["matched"] is True and g5["resolvedFrom"] == "config", str(g5))

m._config_provider = lambda: "ollama-local"
g6 = client.get("/gate?model=qwen3-vl:latest").json()
check("⑥ 配置兜底(其他家) → 不显示", g6["matched"] is False, str(g6))

# (e) 非受支持前缀 + 会话/配置都不是受支持套餐 → 不显示
m._session_provider = lambda sid: "anthropic"
g7 = client.get("/gate?model=opencode-zen/some-model&session=abc123").json()
check("⑥ zen 前缀/会话 → 不显示", g7["matched"] is False, str(g7))

# (f) 受支持前缀优先（会话/配置都说别家时也认前缀 —— 只有注册表内的 provider 才有这待遇）
m._session_provider = lambda sid: "opencode-zen"
m._config_provider = lambda: "ollama-local"
g8 = client.get("/gate?model=opencode-go/deepseek-flash&session=abc123").json()
check("⑥ 受支持前缀优先于会话/配置", g8["matched"] is True and g8["provider"] == "opencode-go"
      and g8["resolvedFrom"] == "prefix", str(g8))

# (g) 裸模型名（opencode-go 的 slug 形态）+ 会话 provider
m._session_provider = lambda sid: "opencode-go" if sid else None
m._config_provider = lambda: "ollama-local"
g9 = client.get("/gate?model=deepseek-flash&session=abc123").json()
check("⑥ 裸模型名 → 会话解析", g9["matched"] is True and g9["resolvedFrom"] == "session", str(g9))
m._session_provider = lambda sid: "opencode-zen" if sid else None
g10 = client.get("/gate?model=deepseek-flash&session=abc123").json()
check("⑥ 裸模型名 + 会话 zen → 不显示", g10["matched"] is False
      and g10["resolvedProvider"] == "opencode-zen", str(g10))

m._session_provider, m._config_provider = orig_sess, orig_conf

print("\n== ⑦ 失效 key 的顺延行为 ==")


def _mk_entry(eid, secret, status="ok"):
    return {
        "id": eid, "label": eid, "source": "manual", "last_status": status,
        "last_status_at": None, "last_error_code": None, "last_error_reset_at": None,
        "failure_reason": None, "request_count": 0, "secret": secret,
    }


orig_pool7 = m._pool_entries
m.CACHE.clear()

# (a) 主力 401、备用可用 → 顺延到备用并标 fallback
m._pool_entries = lambda auth, spec: [_mk_entry("A", "sk-a"), _mk_entry("B", "sk-b")]
m._http_json = lambda url, secret, ua: (
    (None, {"kind": "unauthorized", "message": "HTTP 401"}) if secret == "sk-a"
    else ({"usage": {"rolling": {"percent": 1, "status": "ok", "resetsAt": ""},
                     "weekly": {"percent": 2, "status": "ok", "resetsAt": ""},
                     "monthly": {"percent": 3, "status": "ok", "resetsAt": ""}}}, None)
)
r8 = client.get("/usage?force=1").json()
check("⑦ 主力 401 → 顺延备用(fallback)", r8["ok"] is True and r8["key"]["id"] == "B"
      and r8["key"]["fallback"] is True and r8["key"]["error"] is None, str(r8["key"]))

# (b) 备用已 dead → 不再探它，直接报主力的 401
m._pool_entries = lambda auth, spec: [_mk_entry("A", "sk-a"), _mk_entry("B", "sk-b", status="dead")]
r9 = client.get("/usage?force=1").json()
check("⑦ dead 备用不被探（报 401 而非误顺延）", r9["ok"] is True and r9["key"]["id"] == "A"
      and r9["key"]["error"] and r9["key"]["error"]["kind"] == "unauthorized", str(r9["key"]))

m._pool_entries, m._http_json = orig_pool7, orig_http
m.CACHE.clear()

print("\n== ⑧ Command Code GOAT 取数与换算（合成响应） ==")
spec_cc = m.PROVIDERS.get("commandcode-goat")
check("⑧ 注册表含 commandcode-goat（windows/GOAT/池 commandcode）",
      spec_cc is not None and spec_cc.kind == "windows" and spec_cc.short == "GOAT"
      and spec_cc.pool_provider == "commandcode" and "commandcode" in spec_cc.model_providers
      and {"COMMANDCODE_API_KEY", "COMMAND_CODE_API_KEY"} <= set(spec_cc.key_envs), str(spec_cc))

CC_CREDITS = {
    "credits": {"monthlyCredits": 63.0, "purchasedCredits": 0, "freeCredits": 0, "belowThreshold": False},
    "windowLimits": {
        "limited": True,
        "exceeded": None,
        "fiveHour": {"used": 7.0, "cap": 14, "exceeded": False, "resetAt": 1790575611720},
        "weekly": {"used": 8.0, "cap": 35, "exceeded": True, "resetAt": 1791162411720},
    },
    "sandboxAccess": False,
    "sandboxMinutes": None,
}
CC_SUB = {
    "success": True,
    "data": {"planId": "individual-goat", "status": "active",
             "currentPeriodStart": "2026-09-28T00:49:19.000Z",
             "currentPeriodEnd": "2026-10-28T00:49:19.000Z"},
}

def fake_cc(url, secret, ua):
    if url.endswith("/alpha/billing/credits"):
        return CC_CREDITS, None
    if url.endswith("/alpha/billing/subscriptions"):
        return CC_SUB, None
    return None, {"kind": "http_404", "message": url}

orig8_pool, orig8_http = m._pool_entries, m._http_json
m._pool_entries = lambda auth, spec: [_mk_entry("CC", "user_fake-cc")]
m._http_json = fake_cc
m.CACHE.clear()
r8 = client.get("/usage?provider=commandcode-goat&force=1").json()
wins8 = r8.get("windows") or []
by_id = {w["id"]: w for w in wins8}
check("⑧ 三窗口 rolling/weekly/monthly", [w["id"] for w in wins8] == ["rolling", "weekly", "monthly"],
      str([w["id"] for w in wins8]))
check("⑧ 百分比 50 / 22 / 10（向下取整）",
      [by_id[k]["percent"] for k in ("rolling", "weekly", "monthly")] == [50, 22, 10],
      str({k: by_id[k]["percent"] for k in by_id}))
check("⑧ 毫秒 resetAt → ISO",
      "T" in by_id["rolling"]["resetsAt"] and by_id["rolling"]["resetsAt"].endswith("Z"),
      str(by_id["rolling"]["resetsAt"]))
check("⑧ 月窗重置=账单周期末", by_id["monthly"]["resetsAt"] == "2026-10-28T00:49:19.000Z",
      str(by_id["monthly"]["resetsAt"]))
check("⑧ exceeded → rate-limited",
      by_id["weekly"]["status"] == "rate-limited" and by_id["rolling"]["status"] == "ok",
      str([w["status"] for w in wins8]))
check("⑧ 池内 key 取数（顺延无关）",
      r8["key"]["label"] == "CC" and r8["key"]["error"] is None and r8["ok"] is True, str(r8["key"]))

# 已购/赠送计入月池：剩余 60+5+5=70，池 = max(70,60)+5+5 = 80 → 已用 10 → 12%
m._http_json = lambda url, secret, ua: (
    ({"credits": {"monthlyCredits": 60.0, "purchasedCredits": 5.0, "freeCredits": 5.0},
      "windowLimits": {"fiveHour": {"used": 0, "cap": 14, "resetAt": 0},
                       "weekly": {"used": 0, "cap": 35, "resetAt": 0}}}, None)
    if url.endswith("/credits") else (CC_SUB, None))
frag, err = m._fetch_commandcode_windows("user_fake")
monthly_win = next((w for w in (frag or {}).get("windows", []) if w["id"] == "monthly"), None)
check("⑧ 已购/赠送计入月池（12%）", err is None and monthly_win is not None and monthly_win["percent"] == 12,
      str(monthly_win))

# subscriptions 失败不致命 → 仍给 5h/周
m._http_json = lambda url, secret, ua: (
    (CC_CREDITS, None) if url.endswith("/credits") else (None, {"kind": "network", "message": "URLError"}))
frag2, err2 = m._fetch_commandcode_windows("user_fake")
check("⑧ 订阅失败仍回 5h/周", err2 is None and [w["id"] for w in frag2["windows"]] == ["rolling", "weekly"],
      str(err2 or frag2))

# 未知 planId → 不编数，省略月窗
m._http_json = lambda url, secret, ua: (
    ({"credits": {"monthlyCredits": 5.0},
      "windowLimits": {"fiveHour": {"used": 0, "cap": 14}, "weekly": {"used": 0, "cap": 35}}}, None)
    if url.endswith("/credits") else ({"success": True, "data": {"planId": "individual-enterprise"}}, None))
frag3, err3 = m._fetch_commandcode_windows("user_fake")
check("⑧ 未知套餐 → 省略月窗", err3 is None and [w["id"] for w in frag3["windows"]] == ["rolling", "weekly"],
      str(frag3))

# 错误映射
m._http_json = lambda url, secret, ua: (None, {"kind": "unauthorized", "message": "HTTP 401"})
r9 = client.get("/usage?provider=commandcode-goat&force=1").json()
check("⑧ 401 → unauthorized 且 windows=null",
      r9["key"]["error"]["kind"] == "unauthorized" and r9.get("windows") is None, str(r9["key"]))

m._http_json = lambda url, secret, ua: ({"nope": 1}, None)
r10 = client.get("/usage?provider=commandcode-goat&force=1").json()
check("⑧ 结构异常 → malformed", r10["key"]["error"]["kind"] == "malformed", str(r10["key"]))

m._pool_entries, m._http_json = orig8_pool, orig8_http
m.CACHE.clear()

# 真实数据冒烟：拿库里最新会话（含其真实 model slug）跑一次（环境依赖，仅打印不断言）
try:
    import sqlite3
    db = sqlite3.connect(f"file:///{(m._hermes_home() / 'state.db').as_posix().lstrip('/')}?mode=ro", uri=True)
    cols = {r[1] for r in db.execute("PRAGMA table_info(sessions)")}
    idc = next((c for c in ("session_id", "id", "sid") if c in cols), None)
    row = db.execute(f"SELECT {idc}, model, billing_provider FROM sessions ORDER BY rowid DESC LIMIT 1").fetchone() if idc else None
    db.close()
    if row:
        live = client.get(f"/gate?model={row[1]}&session={row[0]}").json()
        print("   真实会话冒烟:", row[0][:24], "| model=", row[1], "| billing=", row[2], "→", json.dumps(live, ensure_ascii=False))
except Exception as exc:
    print("   真实会话冒烟跳过:", type(exc).__name__)

print("\n== ⑨ 压缩轮转（compression lineage）会话解析 ==")
import sqlite3 as _sq
import tempfile as _tf

_orig_home = m._hermes_home
_tmp_home = Path(_tf.mkdtemp(prefix="ocgo-lineage-"))
_con = _sq.connect(str(_tmp_home / "state.db"))
_con.execute(
    "CREATE TABLE sessions (id TEXT PRIMARY KEY, model_config TEXT, billing_provider TEXT, parent_session_id TEXT)"
)
# 压缩轮转实测形态：continuation 的 model_config 只有初始化片段（无 provider），billing 未回账（NULL）
_con.execute("INSERT INTO sessions VALUES ('child', ?, NULL, 'mid')",
             (json.dumps({"max_iterations": 200, "reasoning_config": {"enabled": True}}),))
# 中间层也无声明 → 继续上溯
_con.execute("INSERT INTO sessions VALUES ('mid', ?, NULL, 'root')", (json.dumps({"reasoning_config": {}}),))
# 根：model_config 带 provider，billing NULL（provider 解析路径）
_con.execute("INSERT INTO sessions VALUES ('root', ?, NULL, NULL)",
             (json.dumps({"model": "deepseek/deepseek-v4.1-flash", "provider": "commandcode"}),))
# 另一条链：中间层靠 billing_provider 解析
_con.execute("INSERT INTO sessions VALUES ('childB', ?, NULL, 'midB')", ("{}",))
_con.execute("INSERT INTO sessions VALUES ('midB', ?, 'commandcode', 'root')", ("{}",))
# 本行自证优先：自己带 provider 时不看父链
_con.execute("INSERT INTO sessions VALUES ('own', ?, NULL, 'root')",
             (json.dumps({"provider": "opencode-go"}),))
# 成环：两行互指、都无声明
_con.execute("INSERT INTO sessions VALUES ('loop-a', '{}', NULL, 'loop-b')")
_con.execute("INSERT INTO sessions VALUES ('loop-b', '{}', NULL, 'loop-a')")
_con.commit()
_con.close()

m._hermes_home = lambda: _tmp_home
_r_child = m._session_provider("child")
check("⑨ 轮转子行无声明 → 沿父链(3跳)解析 commandcode", _r_child == "commandcode", str(_r_child))
_r_b = m._session_provider("childB")
check("⑨ 中间层 billing_provider 参与解析", _r_b == "commandcode", str(_r_b))
_r_own = m._session_provider("own")
check("⑨ 本行有 provider 时优先本行", _r_own == "opencode-go", str(_r_own))
check("⑨ 行不存在 → None", m._session_provider("ghost") is None)
_r_loop = m._session_provider("loop-a")
check("⑨ 成环不挂（回 None）", _r_loop is None, str(_r_loop))
check("⑨ 空 id → None", m._session_provider("") is None)
m._hermes_home = _orig_home

print("\n== 缓存行为 ==")
m.CACHE.clear()
a = client.get("/usage").json()
b = client.get("/usage").json()
c = client.get("/usage?force=1").json()
check("缓存命中返回同一 payload", a is not None and b.get("fetchedAt") == a.get("fetchedAt"))
check("force=1 绕缓存", c.get("ok") is True)

print("\n== 结果 ==")
print("FAILURES:", failures if failures else "无 —— 全部通过")
sys.exit(1 if failures else 0)
