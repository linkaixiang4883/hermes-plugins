"""model-audit —— agent 半：逐次记录每次主对话 API 调用的上游真实 model。

机制：
  · 官方 hook `post_api_request` 给出 session/model/provider/时间/用量，但**不含响应头**；
  · 上游真相在响应头（opencode-go: x-opencode-upstream-model-id）→ 借核心自己的 httpx 响应钩子：
    对 `agent.served_model.install_served_model_capture` 做一层 fail-open 包装，响应到达时把白名单头
    按 **session_id** 存进本模块的槽位（`_LAST_BY_SESSION`），hook 触发时按 payload 的 session_id 取回
    （**一次性消费 + 时间窗校验**，防止陈旧值错配）；
  · **关键：不在闭包里固定 agent 对象**。压缩（父会话 end_reason='compression'）会新建子会话与新 agent，
    而 httpx 客户端可能被复用 → 闭包里的旧 agent 会一直往旧对象写，新会话的 hook 什么都读不到
    （实测症状：压缩后整片「无信号」，偶发几条 ✅ 是客户端重建那一刻）。所以响应时**懒解析**当前 agent：
    `_CLIENT_AGENT[httpx 客户端] → agent`（每次 install 都刷新），再从它读 `session_id` 定槽。
  · **只写原始事实**（不写认可状态、不做自动清理）；
  · 任何一步失败都只降级为「无信号」，绝不影响 agent 主循环；
  · 诊断：响应/落库各写一行 JSONL 到 `data/capture-debug.jsonl`（超限自动截断），排「无信号」时先看它。
"""
from __future__ import annotations

import json
import os
import time
import weakref
from typing import Any, Dict, Optional, Tuple

from . import model_audit_core as core

_AGENTS: "weakref.WeakValueDictionary[str, Any]" = weakref.WeakValueDictionary()
_CLIENT_AGENT: "weakref.WeakKeyDictionary[Any, Any]" = weakref.WeakKeyDictionary()
_LAST_BY_SESSION: Dict[str, Tuple[float, Dict[str, str]]] = {}
_PATCHED_FLAG = "_model_audit_patched"
_MAX_SLOTS = 64
_DEBUG_MAX_BYTES = 512 * 1024
_DEBUG_KEEP_LINES = 300


# ---------------------------------------------------------------- debug（排「无信号」用）
def _debug_path():
    """诊断文件跟 DB 同目录（这样 MODEL_AUDIT_DB 覆盖时测试不会写到真实插件目录）。"""
    try:
        return core.db_path().parent / "capture-debug.jsonl"
    except Exception:
        return None


def _debug(kind: str, **fields: Any) -> None:
    """写一行诊断；任何失败静默。文件超限时只保留最近若干行。"""
    try:
        p = _debug_path()
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": round(time.time(), 3), "kind": kind, **fields},
                                ensure_ascii=False, default=str) + "\n")
        if p.stat().st_size > _DEBUG_MAX_BYTES:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-_DEBUG_KEEP_LINES:]
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- capture
def _keep_headers(raw: Any) -> Dict[str, str]:
    if raw is None:
        return {}
    try:
        return {str(k).lower(): str(v) for k, v in raw.items()
                if str(k).lower() in core.HEADER_ALLOWLIST}
    except Exception:
        return {}


def _remember(sid: str, headers: Dict[str, str]) -> None:
    if not sid:
        return
    _LAST_BY_SESSION[sid] = (time.time(), headers)
    while len(_LAST_BY_SESSION) > _MAX_SLOTS:                 # 只留最近若干条
        _LAST_BY_SESSION.pop(next(iter(_LAST_BY_SESSION)), None)


def _on_response_factory(http_client: Any, fallback_agent: Any):
    def _on_response(response: Any) -> None:
        try:
            if not (200 <= int(getattr(response, "status_code", 0)) < 300):
                return
            # 懒解析：客户端可能已被新 agent 复用（压缩后），闭包里的 agent 可能是旧的。
            agent = _CLIENT_AGENT.get(http_client) or fallback_agent
            sid = str(getattr(agent, "session_id", "") or "")
            keep = _keep_headers(getattr(response, "headers", None))
            _remember(sid, keep)
            if sid and agent is not None:
                _AGENTS[sid] = agent
            _debug("resp", sid=sid, n=len(keep), keys=sorted(keep), client=id(http_client),
                   agent=id(agent) if agent is not None else None)
        except Exception:
            pass
    _on_response._model_audit_hook = True
    return _on_response


def _wrap_install_served_model_capture(agent: Any, client: Any) -> None:
    """给同一个 client 追加我们的响应钩子（核心的钩子仍由原函数装）。

    每次 install 都刷新「httpx 客户端 → agent」映射：客户端可能被新 agent 复用，
    而钩子闭包是**首次安装**时建的（不会再建）→ 不刷新就只能读到旧 agent 的 session。
    """
    try:
        http_client = getattr(client, "_client", None)
        if http_client is None:
            return
        try:
            _CLIENT_AGENT[http_client] = agent
        except TypeError:                                    # 不可弱引用 → 退回闭包里的 agent
            pass
        sid = getattr(agent, "session_id", None)
        if sid:
            _AGENTS[str(sid)] = agent
        hooks = getattr(http_client, "event_hooks", None)
        if isinstance(hooks, dict):
            existing = list(hooks.get("response", ()))
            if not any(getattr(h, "_model_audit_hook", False) for h in existing):
                http_client.event_hooks = {**hooks,
                                           "response": [*existing, _on_response_factory(http_client, agent)]}
    except Exception:
        pass


def _try_patch_served_model(namespace: Dict[str, Any]) -> bool:
    """把 namespace['install_served_model_capture'] 换成包装。缺失 → False（fail-open）。"""
    orig = namespace.get("install_served_model_capture")
    if not callable(orig):
        return False
    if namespace.get(_PATCHED_FLAG):
        return True

    def _patched(agent: Any, client: Any) -> Any:
        _wrap_install_served_model_capture(agent, client)
        return orig(agent, client)

    namespace["install_served_model_capture"] = _patched
    namespace[_PATCHED_FLAG] = True
    return True


def install_capture() -> bool:
    """装包装 + 建库 + 写 meta（**不做自动清理**）。返回是否装上（False = 降级为 no_signal）。"""
    patched = False
    try:
        from agent import served_model as sm
        patched = _try_patch_served_model(vars(sm))
    except Exception:
        patched = False
    try:
        db = core.db_path()
        core.ensure_db(db)
        if core.get_setting(db, "retention_days") is None:
            core.set_setting(db, "retention_days", str(core.DEFAULT_RETENTION_DAYS))
        core.set_meta(db, "capture_installed", str(time.time()))
        core.set_meta(db, "patch_ok", "1" if patched else "0")
        try:
            import hermes_cli
            core.set_meta(db, "hermes_version", str(getattr(hermes_cli, "__version__", "unknown")))
        except Exception:
            pass
    except Exception:
        pass
    return patched


# ---------------------------------------------------------------- hook
def _consume(sid: str, payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], Optional[float]]:
    """取本次调用的头：一次性消费 + 时间窗校验；不匹配/为空 → (None, None)（记无信号）。"""
    got = _LAST_BY_SESSION.pop(sid, None) if sid else None
    if not got:
        return None, None
    header_ts, headers = got
    if not headers:                                          # 本次响应确实没带白名单头
        return None, None
    started = float(payload.get("started_at") or 0)
    ended = float(payload.get("ended_at") or (started + float(payload.get("api_duration") or 0)))
    if started and not (started - 5 <= header_ts <= ended + 5):
        return None, None                                    # 陈旧值 → 宁可无信号也不错配
    return headers, header_ts


def _profile_context(agent: Any) -> Tuple[str, str]:
    """(profile_home, profile_name)。

    多 profile 网关（`gateway.multiplex_profiles` 默认 true）里一个进程服务所有 profile，
    **不能**读进程级 `os.environ["HERMES_HOME"]`——那是启动时的 home。按轮次绑定的是
    上下文局部 home（`hermes_constants` 的 contextvar，经 copy_context 传到 agent 线程），
    所以优先 `get_hermes_home()`；profile 名优先取 agent 身份，退回按 home 反推。
    """
    home = ""
    try:
        from hermes_constants import get_hermes_home
        home = str(get_hermes_home())
    except Exception:
        home = ""
    if not home:
        home = os.environ.get("HERMES_HOME", "")
    name = ""
    try:
        name = str(getattr(agent, "agent_identity", "") or "")
    except Exception:
        name = ""
    if not name:
        try:
            from hermes_cli.profiles import get_active_profile_name
            name = str(get_active_profile_name() or "")
        except Exception:
            name = ""
    return home, name


def on_post_api_request(**payload: Any) -> None:
    """官方 hook：每次主对话 API 调用一次。只写原始事实；绝不抛异常。"""
    try:
        sid = str(payload.get("session_id") or "")
        headers, header_ts = _consume(sid, payload)
        agent = _AGENTS.get(sid) if sid else None
        profile_home, profile_name = _profile_context(agent)
        row = core.build_row(payload, headers, header_ts,
                             profile_home=profile_home, profile_name=profile_name)
        core.insert_call(core.db_path(), row)
        _debug("hook", sid=sid, idx=payload.get("api_call_count"), status=row.get("status"),
               up=row.get("upstream_model"), ep=row.get("endpoint_id"))
    except Exception:
        pass


# ---------------------------------------------------------------- entry
def register(ctx: Any) -> None:
    install_capture()
    ctx.register_hook("post_api_request", on_post_api_request)
