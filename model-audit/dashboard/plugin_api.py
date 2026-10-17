"""model-audit dashboard 后端：读端点（/rows 顺带只读取会话标题）+ 三个写端点（认可 / 设置 / 手动清理）。

注意：本文件被 web server 用 spec_from_file_location 单独装载 → **相对导入不可用**，
共享核心必须按路径加载（见 _load_core）。
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query

_ROOT = Path(__file__).resolve().parent.parent


def _load_core() -> Any:
    path = _ROOT / "model_audit_core.py"
    name = "model_audit_core"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


core = _load_core()
router = APIRouter()


def _db() -> Path:
    return core.db_path()


# 客户端语义（0.3.0）：后端半**不建库、不迁移**——schema 由服务端（agent 半的 register）负责。
# 客户端只探测 core.schema_ready()：没就绪 → 读接口 200 + 空结果 + initialized=false，写接口 503；
# 绝不 500，也绝不在别人的库上做 DDL（单写者 ⇒ 无跨半竞态）。
_EMPTY_TOTALS = {"calls": 0, "ok": 0, "approved": 0, "mismatch": 0, "new_route": 0,
                 "body_mismatch": 0, "body_only": 0, "no_signal": 0, "no_attestation": 0}
_NOT_READY_DETAIL = ("插件库尚未初始化：schema 由 agent 半（桌面端 / 网关 / CLI）启动时创建，后端半只读。"
                     "请先启动一次任一 agent 进程。")


def _db_if_ready() -> Optional[Path]:
    """就绪则返回库路径，否则 None（客户端探测，绝不建库）。"""
    db = _db()
    return db if core.schema_ready(db) else None


def _check_range(name: str, value: int, low: int, high: int) -> int:
    if not (low <= value <= high):
        raise HTTPException(status_code=400, detail=f"{name} out of range")
    return value


def _check_text(name: str, value: Optional[str], max_len: int = 300) -> Optional[str]:
    if value is not None and len(value) > max_len:
        raise HTTPException(status_code=400, detail=f"{name} too long")
    return value


# ---------------------------------------------------------------- read
@router.get("/health")
async def health() -> Dict[str, Any]:
    def _run() -> Dict[str, Any]:
        db = _db()
        state = core.state_db_path()
        out: Dict[str, Any] = {"db_path": str(db), "exists": db.exists(), "meta": core.get_meta(db),
                               "initialized": core.schema_ready(db),
                               "state_db": str(state), "state_db_exists": state.exists()}
        try:
            with core.connect(db, readonly=True) as conn:
                out["rows"] = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
                out["approvals"] = conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0]
                row = conn.execute("SELECT MAX(ts_start) FROM calls").fetchone()
                out["last_row_ts"] = row[0] if row else None
        except Exception as exc:
            out.update({"rows": 0, "approvals": 0, "last_row_ts": None,
                        "error": f"{type(exc).__name__}: {exc}"})
        return out

    return await asyncio.to_thread(_run)


@router.get("/rows")
async def rows(days: int = Query(7), limit: int = Query(200), offset: int = Query(0),
               only_anomaly: int = Query(0), include_no_signal: int = Query(0),
               alias: Optional[str] = Query(None),
               session_id: Optional[str] = Query(None),
               profile: Optional[str] = Query(None)) -> Dict[str, Any]:
    _check_range("days", days, 1, 3650)
    _check_range("limit", limit, 1, core.MAX_LIMIT)
    _check_range("offset", offset, 0, 10**9)
    _check_text("alias", alias)
    _check_text("session_id", session_id)
    profile = _check_text("profile", profile)

    db = _db_if_ready()
    if db is None:                                   # 客户端：库还没被服务端建出来 → 空结果，不是错
        return {"rows": [], "limit": limit, "offset": offset, "days": days, "total": 0, "initialized": False}

    def _run() -> Dict[str, Any]:
        out = core.query_rows(db, days=days, limit=limit, offset=offset,
                              only_anomaly=bool(only_anomaly),
                              include_no_signal=bool(include_no_signal),
                              alias=alias, session_id=session_id, profile=profile)
        core.attach_titles(out["rows"])          # 跨库只读，失败降级为空标题
        out["initialized"] = True
        return out

    return await asyncio.to_thread(_run)


@router.get("/summary")
async def summary(days: int = Query(7), profile: Optional[str] = Query(None),
                  group_by: str = Query("alias")) -> Dict[str, Any]:
    _check_range("days", days, 1, 3650)
    profile = _check_text("profile", profile)
    if group_by not in core.GROUP_BY_KEYS:
        raise HTTPException(status_code=400,
                            detail="group_by must be one of: " + ", ".join(core.GROUP_BY_KEYS))
    db = _db_if_ready()
    if db is None:
        return {"totals": dict(_EMPTY_TOTALS), "by_alias": [], "profiles": [], "groups": [],
                "group_by": group_by, "days": days,
                "retention_days": core.DEFAULT_RETENTION_DAYS, "initialized": False}
    out = await asyncio.to_thread(core.summarize, db, days=days, profile=profile, group_by=group_by)
    out["initialized"] = True
    return out


def _db_ready() -> Path:
    """写操作前确认库已就绪：客户端**不建库**——未初始化时 503 并提示先启动一次 agent 进程。"""
    db = _db_if_ready()
    if db is None:
        raise HTTPException(status_code=503, detail=_NOT_READY_DETAIL)
    return db


# ---------------------------------------------------------------- approvals
@router.get("/approvals")
async def approvals_list() -> Dict[str, Any]:
    db = _db_if_ready()
    if db is None:
        return {"approvals": [], "initialized": False}
    return {"approvals": await asyncio.to_thread(core.list_approvals, db), "initialized": True}


@router.get("/builtin")
async def builtin_rules() -> Dict[str, Any]:
    """内置标准（只读）：provider + alias → 期望的 model + 端点。命中即「一致」。"""
    return {"rules": [dict(r) for r in core.BUILTIN_RULES]}


@router.post("/approvals")
async def approvals_add(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """认可规则：alias 必填；provider / 上游 model / 端点留空 = 任意，但 model 与端点至少填一项。"""
    req = str(payload.get("requested_model") or "").strip()
    up = str(payload.get("upstream_model") or "").strip()
    prov = str(payload.get("provider") or "").strip()
    if not req:
        raise HTTPException(status_code=400, detail="requested_model is required")
    if not up and not str(payload.get("endpoint_id") or "").strip():
        raise HTTPException(
            status_code=400,
            detail="upstream_model 与 endpoint_id 至少填一项（两项都空会认可该 alias 的所有行）")
    if len(req) > 200 or len(up) > 200 or len(prov) > 200:
        raise HTTPException(status_code=400, detail="value too long")
    raw_note = payload.get("note")
    note = str(raw_note)[:500] if raw_note else None
    raw_ep = payload.get("endpoint_id")
    endpoint = str(raw_ep)[:200] if raw_ep else None
    ok = await asyncio.to_thread(core.add_approval, _db_ready(), req, up, endpoint, note, prov)
    if not ok:
        raise HTTPException(status_code=400, detail="rejected")
    return {"ok": True}


@router.delete("/approvals/{approval_id}")
async def approvals_delete(approval_id: int) -> Dict[str, Any]:
    _check_range("approval_id", approval_id, 1, 10**12)
    ok = await asyncio.to_thread(core.delete_approval, _db_ready(), approval_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True}


# ---------------------------------------------------------------- settings / maintenance
@router.get("/settings")
async def settings_get() -> Dict[str, Any]:
    db = _db_if_ready()
    if db is None:
        return {"retention_days": str(core.DEFAULT_RETENTION_DAYS), "initialized": False}
    return {"retention_days": str(core.retention_days(db)), "initialized": True}


@router.put("/settings")
async def settings_put(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    raw = payload.get("retention_days")
    try:
        days = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="retention_days must be an integer")
    _check_range("retention_days", days, 1, 3650)
    db = _db_ready()
    await asyncio.to_thread(core.set_setting, db, "retention_days", str(days))
    return {"ok": True, "retention_days": str(days)}


@router.post("/maintenance/prune")
async def maintenance_prune() -> Dict[str, Any]:
    db = _db_ready()
    deleted = await asyncio.to_thread(core.prune_calls, db)
    return {"ok": True, "deleted": deleted, "retention_days": str(core.retention_days(db))}
