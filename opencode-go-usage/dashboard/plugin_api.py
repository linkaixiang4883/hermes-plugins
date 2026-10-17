"""OpenCode Go 用量查询 —— Hermes 桌面状态栏插件的后端半（提供商注册表版）。

挂载点：/api/plugins/opencode-go-usage/usage[?provider=<id>&force=1]
（由 Hermes web server 在进程启动时按 config.yaml 的 plugins.enabled 白名单导入
本模块的 ``router``；改动后需要重启承载它的后端进程才会生效。）

职责与边界：
  · 读 Hermes 凭证池（auth.json 的 credential_pool）→ 选出"当前主力" key
    —— 与 agent/credential_pool.py 的 fill_first 选择顺序、冷却 TTL 保持一致；
  · 用该 key 请求提供商用量端点（只读元数据，不消耗套餐配额）；
  · 归一化输出：百分比窗口（kind='windows'）或余额（kind='balance'）。
    key 只在本进程内存与请求头里出现，绝不出现在响应或日志里。

=====================================================================
提供商注册表 —— 新增一家套餐 = 加一条 ProviderSpec，其余代码不动
=====================================================================
ProviderSpec 字段：
  id / display / short   标识、展示名、芯片前缀（short，2-3 字符）
  kind                   'windows'（百分比窗口）| 'balance'（余额）
  key_envs               兜底环境变量（凭证池为空/无池时按序取）
  pool_provider          auth.json credential_pool 里的池键（None = 不走凭证池）
  pool_fallback_match    池键缺失时做包含匹配的兜底串（可 None）
  model_providers        **模型门控**：这些 Hermes 模型 provider 名（规范化小写）出现时，
                         才显示该套餐的芯片 —— 例："opencode-go"。不属于任何 model_providers
                         的模型（如 opencode-zen / 其他家）芯片隐藏，避免误导（见 /gate）
  fetch(secret)          返回 (片段, error)；片段 = {"windows":[...]} 或 {"balance":{...}}
                         window = {id, label, percent, status, resetsAt}

端点：
  GET /usage?provider=<id>&force=1   当前主力 key 的套餐用量（缓存 60s）
  GET /gate?model=<raw>[&session=<storedSessionId>]
       模型门控判定：按 ① model 串前缀（仅当它是注册表内受支持套餐的 provider）→
       ② 会话在 state.db 里的 provider（本行解析不出时沿 parent_session_id 回溯，
       覆盖自动压缩轮转窗口）→ ③ 配置默认 provider 三级解析，
       回 {matched, provider, resolvedProvider, resolvedFrom}

当前已实现：opencode-go、commandcode-goat。

  commandcode-goat —— Command Code GOAT（$10/月；5h 上限 $14、每周 $35、月额度 $70）。
  取数端点（免登录，API key 与调模型同一把；cli.mjs 实测契约）：
    GET https://api.commandcode.ai/alpha/billing/credits        → 两个滚动窗（used/cap/resetAt）+ 剩余 credits
    GET https://api.commandcode.ai/alpha/billing/subscriptions  → planId（→ 月池）+ 账单周期
  月窗口的百分比 = 已用 / 月池（池 = 套餐月额度 + 已购 + 赠送）。
  注意 `host.state.model` 给的 slug 可能是 `deepseek/deepseek-v4.1-flash` 这种
  「厂商/模型」形态 —— 首段不是 provider 名，所以 /gate 的前缀规则只认注册表内的
  已支持 provider，其余走会话行 → 配置默认（否则 GOAT 会话会被误判成 deepseek）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter

log = logging.getLogger(__name__)

router = APIRouter()

HTTP_TIMEOUT_SECONDS = 15
CACHE_TTL_SECONDS = 60
# 自述 UA：默认 urllib UA 会被 Cloudflare 以 1010 拦掉（见技能中的陷阱记录）
PLUGIN_USER_AGENT = "hermes-desktop-plugin/opencode-go-usage"

# 与 agent/credential_pool.py 的 EXHAUSTED_TTL_* 对齐；能 import 到 Hermes 自己
# 的常量就用它（避免将来漂移），否则退回同值兜底。
try:  # pragma: no cover - 取决于运行环境
    from agent import credential_pool as _hermes_pool  # type: ignore
except Exception:  # pragma: no cover
    _hermes_pool = None

CACHE: dict[str, tuple[float, dict]] = {}


def _ttl(attr: str, default: int) -> int:
    value = getattr(_hermes_pool, attr, None) if _hermes_pool else None
    try:
        return int(value)
    except Exception:
        return default


def _hermes_home() -> Path:
    try:
        from hermes_cli.config import get_hermes_home  # type: ignore

        return Path(get_hermes_home())
    except Exception:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "hermes"


def _read_json_retry(path: Path) -> Optional[Any]:
    """auth.json 会被别的进程并发写（旁边有 auth.lock）→ 失败重试一次。"""
    for attempt in range(2):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return None
        except Exception:
            if attempt == 0:
                time.sleep(0.2)
    return None


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")


def _env_file_value(name: str) -> Optional[str]:
    try:
        text = (_hermes_home() / ".env").read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    for line in text.splitlines():
        match = _ENV_LINE.match(line)
        if match and match.group(1) == name:
            return match.group(2).strip().strip('"').strip("'") or None
    return None


def _resolve_secret(entry: dict) -> Optional[str]:
    token = entry.get("access_token")
    if isinstance(token, str) and token.strip():
        return token.strip()
    source = str(entry.get("source") or "")
    if source.startswith("env:"):
        name = source[4:].strip()
        value = os.environ.get(name) or _env_file_value(name)
        if value:
            return value.strip()
    return None


def _pool_entries(auth: Any, spec: "ProviderSpec") -> list[dict[str, Any]]:
    pools = auth.get("credential_pool") if isinstance(auth, dict) else None
    if not isinstance(pools, dict) or not spec.pool_provider:
        return []
    raw = pools.get(spec.pool_provider)
    if not (isinstance(raw, list) and raw) and spec.pool_fallback_match:
        for key, value in pools.items():
            if spec.pool_fallback_match in str(key).lower() and isinstance(value, list) and value:
                raw = value
                break
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        entries.append(
            {
                "id": str(item.get("id") or f"entry-{index}"),
                "label": str(item.get("label") or item.get("source") or f"key {index + 1}"),
                "source": str(item.get("source") or ""),
                "last_status": item.get("last_status"),
                "last_status_at": item.get("last_status_at"),
                "last_error_code": item.get("last_error_code"),
                "last_error_reset_at": item.get("last_error_reset_at"),
                "failure_reason": item.get("failure_reason"),
                "request_count": int(item.get("request_count") or 0),
                "secret": _resolve_secret(item),
            }
        )
    return entries


def _env_entry_for(spec: "ProviderSpec") -> Optional[dict[str, Any]]:
    for name in spec.key_envs:
        value = os.environ.get(name) or _env_file_value(name)
        if value:
            return {
                "id": "env",
                "label": name,
                "source": f"env:{name}",
                "last_status": None,
                "last_status_at": None,
                "last_error_code": None,
                "last_error_reset_at": None,
                "failure_reason": None,
                "request_count": 0,
                "secret": value.strip(),
            }
    return None


def _parse_ts(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number <= 0:
            return None
        return number / 1000.0 if number > 1_000_000_000_000 else number
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        try:
            number = float(text)
            return number / 1000.0 if number > 1_000_000_000_000 else number
        except Exception:
            return None


def _ttl_seconds(code: Any, failure_reason: Any, sole: bool) -> int:
    """镜像 agent/credential_pool.py:_exhausted_ttl 的冷却时长（秒）。"""
    if code == 401:
        base = _ttl("EXHAUSTED_TTL_401_SECONDS", 5 * 60)
    elif code == 429:
        base = _ttl("EXHAUSTED_TTL_429_SECONDS", 60 * 60)
    else:
        base = _ttl("EXHAUSTED_TTL_DEFAULT_SECONDS", 60 * 60)
    is_billing = code == 402 or failure_reason == "billing"
    if is_billing:
        return base
    if sole:
        return min(base, _ttl("EXHAUSTED_TTL_SOLE_CREDENTIAL_SECONDS", 60))
    return base


def _cooldown_until(entry: dict, *, sole: bool) -> Optional[float]:
    if entry.get("last_status") != "exhausted":
        return None
    reset = _parse_ts(entry.get("last_error_reset_at"))
    if reset is not None:
        return reset
    updated = _parse_ts(entry.get("last_status_at"))
    if updated is None:
        return None
    return updated + _ttl_seconds(entry.get("last_error_code"), entry.get("failure_reason"), sole)


def _select_active(entries: list[dict], now: float) -> tuple[Optional[dict], bool, int]:
    """与 Hermes fill_first 同序：第一把非 dead 且冷却已过的 key。

    返回 (active, all_cooling, available_count)；池内全部冷却时取最早解冻的那把。
    """
    usable = [e for e in entries if e.get("secret") and e.get("last_status") != "dead"]
    sole = len(usable) == 1
    available: list[dict] = []
    cooling: list[tuple[float, dict]] = []
    for entry in usable:
        until = _cooldown_until(entry, sole=sole)
        if until is None or until <= now:
            available.append(entry)
        else:
            cooling.append((until, entry))
    if available:
        return available[0], False, len(available)
    if cooling:
        cooling.sort(key=lambda pair: pair[0])
        return cooling[0][1], True, 0
    return (usable[0] if usable else None), False, 0


class _SameHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """只跟随同一 https 主机内的重定向。

    urllib 默认会把 Authorization 头转发到重定向目标主机 —— 对携带 API key 的
    请求这是凭据泄露面；跨主机的 3xx 一律不跟随（抛回 3xx 归入错误处理）。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        try:
            old_host = urllib.parse.urlsplit(req.full_url).hostname
            new_host = urllib.parse.urlsplit(newurl).hostname
        except Exception:
            return None
        if newurl.lower().startswith("https://") and old_host and old_host == new_host:
            return super().redirect_request(req, fp, code, msg, headers, newurl)
        return None


_OPENER = urllib.request.build_opener(_SameHostRedirectHandler())


def _http_json(url: str, secret: str, user_agent: str) -> tuple[Optional[Any], Optional[dict]]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {secret}",
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
    )
    try:
        with _OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
        return json.loads(body), None
    except urllib.error.HTTPError as exc:
        kind = {401: "unauthorized", 403: "entitlement"}.get(exc.code, f"http_{exc.code}")
        return None, {"kind": kind, "message": f"HTTP {exc.code}"}
    except Exception as exc:  # URLError / timeout / JSON 解析等
        name = type(exc).__name__.lower()
        return None, {"kind": "timeout" if "timeout" in name else "network", "message": type(exc).__name__}


# ---------------------------------------------------------------------------
# 各提供商的 fetch 实现
# ---------------------------------------------------------------------------


def _normalize_window(raw: dict, window_id: str) -> dict:
    return {
        "id": window_id,
        "label": window_id,
        "percent": int(raw.get("percent") or 0),
        "status": str(raw.get("status") or "ok"),
        "resetsAt": raw.get("resetsAt"),
    }


def _fetch_opencode_windows(secret: str) -> tuple[Optional[dict], Optional[dict]]:
    """OpenCode Go：GET /zen/go/v1/usage → three percent windows."""
    data, error = _http_json(
        "https://opencode.ai/zen/go/v1/usage", secret, PLUGIN_USER_AGENT
    )
    if error:
        return None, error
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None, {"kind": "malformed", "message": "missing usage in response"}
    windows = [_normalize_window(usage.get(wid) or {}, wid) for wid in ("rolling", "weekly", "monthly")]
    return {"windows": windows}, None


# ---------------------------------------------------------------------------
# Command Code（GOAT / Pro / Max / Provider）—— 金额型窗口 → 换算成百分比
# ---------------------------------------------------------------------------

COMMANDCODE_API_BASE = "https://api.commandcode.ai"

# 套餐月额度（credits）：抄自 Command Code CLI 包 dist/cli.mjs 的 getPlanTotalCredits 表
# （`rr={"individual-go":10,"individual-goat":70,…}`）。月池 = 该值 + 已购 + 赠送。
# 只知道 planId、表里没有 → 不编数，月窗口整个省略。
COMMANDCODE_PLAN_CREDITS = {
    "individual-go": 10,
    "individual-goat": 70,
    "individual-pro": 30,
    "individual-pro-v1": 80,
    "individual-provider": 15,
    "individual-max": 150,
    "individual-ultra": 300,
    "teams-pro": 40,
}


def _num(value: Any) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return 0.0


def _iso_from_ms(value: Any) -> Optional[str]:
    """credits 的 resetAt 是**毫秒时间戳**（cli.mjs 里 `1e3*e.reset` / 直接比较 Date.now()）。"""
    ms = _num(value)
    if ms <= 0:
        return None
    return (
        datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _percent_of(used: float, cap: float) -> int:
    """百分比**向下取整**（与 opencode-go 的 percent 口径一致；上限 100）。"""
    if cap <= 0:
        return 0
    return max(0, min(100, int(used / cap * 100)))


def _cc_window(
    window_id: str, label: str, used: float, cap: float, resets_at: Optional[str], exceeded: bool
) -> dict:
    return {
        "id": window_id,
        "label": label,
        "percent": _percent_of(used, cap),
        "status": "rate-limited" if exceeded else "ok",
        "resetsAt": resets_at,
    }


def _cc_monthly_window(credits: dict, secret: str) -> Optional[dict]:
    """月窗口：池 = 套餐月额度 + 已购 + 赠送；已用 = 池 − 剩余。

    planId 只在 subscriptions 响应里（credits 里通常没有）；套餐表里查不到就返回 None。
    """
    sub, _ = _http_json(f"{COMMANDCODE_API_BASE}/alpha/billing/subscriptions", secret, PLUGIN_USER_AGENT)
    sub_data = (sub or {}).get("data") or {} if isinstance(sub, dict) else {}
    plan_id = str(sub_data.get("planId") or credits.get("planId") or "").strip().lower()
    plan_total = COMMANDCODE_PLAN_CREDITS.get(plan_id)
    if plan_total is None:
        return None
    monthly = _num(credits.get("monthlyCredits"))
    purchased = _num(credits.get("purchasedCredits"))
    free = _num(credits.get("freeCredits"))
    pool = max(float(plan_total), monthly) + purchased + free
    used = max(0.0, pool - (monthly + purchased + free))
    period_end = str(sub_data.get("currentPeriodEnd") or "").strip() or None
    return _cc_window("monthly", "monthly", used, pool, period_end, False)


def _fetch_commandcode_windows(secret: str) -> tuple[Optional[dict], Optional[dict]]:
    """Command Code（GOAT 等）：滚动 5h + 周（credits）+ 月额度（subscriptions 补 planId）。

    两个 GET 都是免费元数据读（CLI 的 /usage 面板走同一对端点），不消耗套餐额度。
    subscriptions 失败不算致命：仍返回 5h/周两个窗口，只是没有月窗口。
    """
    data, error = _http_json(f"{COMMANDCODE_API_BASE}/alpha/billing/credits", secret, PLUGIN_USER_AGENT)
    if error:
        return None, error
    try:
        body = data if isinstance(data, dict) else {}
        credits = body.get("credits") if isinstance(body.get("credits"), dict) else {}
        limits = body.get("windowLimits") if isinstance(body.get("windowLimits"), dict) else {}
        if not credits and not limits:
            return None, {"kind": "malformed", "message": "missing credits/windowLimits in response"}
        five = limits.get("fiveHour") if isinstance(limits.get("fiveHour"), dict) else {}
        weekly = limits.get("weekly") if isinstance(limits.get("weekly"), dict) else {}
        windows = [
            _cc_window(
                "rolling",
                "5-hour",
                _num(five.get("used")),
                _num(five.get("cap")),
                _iso_from_ms(five.get("resetAt")),
                bool(five.get("exceeded")),
            ),
            _cc_window(
                "weekly",
                "weekly",
                _num(weekly.get("used")),
                _num(weekly.get("cap")),
                _iso_from_ms(weekly.get("resetAt")),
                bool(weekly.get("exceeded")),
            ),
        ]
        monthly = _cc_monthly_window(credits, secret)
        if monthly is not None:
            windows.append(monthly)
        return {"windows": windows}, None
    except Exception as exc:  # 结构意外 → malformed（别让 500 冒泡）
        return None, {"kind": "malformed", "message": f"{type(exc).__name__}: unexpected response shape"}


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    display: str
    short: str
    kind: str  # 'windows' | 'balance'
    key_envs: tuple[str, ...]
    pool_provider: Optional[str]
    fetch: Callable[[str], tuple[Optional[dict], Optional[dict]]]
    pool_fallback_match: Optional[str] = None
    model_providers: tuple[str, ...] = ()


PROVIDERS: dict[str, ProviderSpec] = {
    "opencode-go": ProviderSpec(
        id="opencode-go",
        display="OpenCode Go",
        short="Go",
        kind="windows",
        key_envs=("OPENCODE_GO_API_KEY", "OPENCODE_API_KEY"),
        pool_provider="opencode-go",
        pool_fallback_match="opencode",
        fetch=_fetch_opencode_windows,
        # 模型门控：只有当前模型跑在这些 provider 上时才显示芯片（Zen 不在此列 → 隐藏）
        model_providers=("opencode-go", "opencode_go", "opencode-go-sub"),
    ),
    "commandcode-goat": ProviderSpec(
        id="commandcode-goat",
        display="Command Code GOAT",
        short="GOAT",
        kind="windows",
        # Hermes 侧凭证名叫 COMMANDCODE_API_KEY；CLI 自己读的是 COMMAND_CODE_API_KEY
        # （cli.mjs 的 COMMAND_CODE_API_KEY_ENV_VAR）—— 两个都认。
        key_envs=("COMMANDCODE_API_KEY", "COMMAND_CODE_API_KEY"),
        pool_provider="commandcode",
        fetch=_fetch_commandcode_windows,
        model_providers=("commandcode", "command-code", "command_code", "commandcode-goat"),
    ),
}
DEFAULT_PROVIDER = "opencode-go"


# ---------------------------------------------------------------------------
# 组装响应
# ---------------------------------------------------------------------------


def _provider_block(spec: ProviderSpec) -> dict:
    return {"id": spec.id, "display": spec.display, "short": spec.short, "kind": spec.kind}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_payload(spec: ProviderSpec) -> dict:
    now = time.time()
    entries = _pool_entries(_read_json_retry(_hermes_home() / "auth.json"), spec)
    pool_size = len(entries)
    if not any(entry.get("secret") for entry in entries):
        fallback = _env_entry_for(spec)
        if fallback:
            entries = [fallback]
            pool_size = 1
    active, all_cooling, available_count = _select_active(entries, now)
    if active is None or not active.get("secret"):
        return {
            "ok": False,
            "provider": _provider_block(spec),
            "error": {"kind": "no_key", "message": "credential pool empty and no env key"},
            "poolSize": pool_size,
        }
    candidates = [active] + [entry for entry in entries if entry is not active]
    used, fragment, error = active, None, None
    for candidate in candidates:
        # 跳过无 secret 与已被 Hermes 标 dead 的 key（dead = 明确认证失败，探它只会再吃一个 401）
        if not candidate.get("secret") or candidate.get("last_status") == "dead":
            continue
        fragment, error = spec.fetch(candidate["secret"])
        used = candidate
        # 401/403 才顺延下一把；网络/超时类错误直接上报，避免连环重试。
        if error is None or error.get("kind") not in ("unauthorized", "entitlement"):
            break
    usable = [entry for entry in entries if entry.get("secret")]
    log.info(
        "opencode-go-usage: provider=%s key=%s pool=%d available=%d fetch=%s",
        spec.id,
        used["label"],
        pool_size,
        available_count,
        "ok" if error is None else error.get("kind"),
    )
    return {
        "ok": True,
        "fetchedAt": _iso_now(),
        "provider": _provider_block(spec),
        "key": {
            "id": used["id"],
            "label": used["label"],
            "poolStatus": "exhausted"
            if all_cooling
            else ("dead" if used.get("last_status") == "dead" else "ok"),
            "cooldownUntil": _cooldown_until(used, sole=len(usable) == 1),
            "requestCount": used.get("request_count", 0),
            "fallback": used is not active,
            "error": error,
        },
        "windows": (fragment or {}).get("windows"),
        "balance": (fragment or {}).get("balance"),
        "poolSize": pool_size,
        "availableCount": available_count,
    }


# ---------------------------------------------------------------------------
# 模型门控（/gate）—— 芯片"只在用本站套餐的模型时显示"，避免用别家模型时误导
# ---------------------------------------------------------------------------


def _norm_provider(value: Any) -> str:
    return re.sub(r"[^a-z0-9_.-]", "", str(value or "").strip().lower())


def _provider_from_model(model: str) -> str:
    """model 串形如 "provider/model" 时取前缀；裸模型名返回 ''。"""
    text = str(model or "").strip()
    slash = text.find("/")
    return _norm_provider(text[:slash]) if slash > 0 else ""


def _provider_from_session_row(data: dict) -> Optional[str]:
    """单行解析：优先 model_config.provider，回退 billing_provider。"""
    raw_cfg = data.get("model_config")
    if isinstance(raw_cfg, str) and raw_cfg.strip():
        try:
            cfg = json.loads(raw_cfg)
            if isinstance(cfg, dict) and cfg.get("provider"):
                return _norm_provider(cfg["provider"]) or None
        except Exception:
            pass
    return _norm_provider(data.get("billing_provider")) or None


# 压缩链回溯深度上限（防环、防异常长链）
_SESSION_LINEAGE_MAX_HOPS = 16


def _session_provider(stored_session_id: str) -> Optional[str]:
    """读 state.db 的 sessions 行解析 provider；本行解析不出时沿 parent_session_id 上溯。

    为什么必须上溯（2026-10-05 实测）：自动压缩会轮转出新 continuation 行——它的
    model_config 写的是会话初始化的片段（max_iterations 等，**不含 provider**），
    billing_provider 要等轮转后第一次用量回账才补上（实测 +11s ~ +244s）。空窗期内
    单读自己那行什么都解析不出，旧实现会掉进 config 默认兜底 → 「GOAT 会话刚压缩完，
    芯片跳回默认套餐（Go），直到用户切换会话才恢复」。continuation 与父行同属一场
    对话、provider 沿链一致，上溯取第一个能解析出声明的祖先即可（上限 16 跳）。
    """
    sid = str(stored_session_id or "").strip()
    if not sid:
        return None
    db_path = _hermes_home() / "state.db"
    if not db_path.exists():
        return None
    try:
        import sqlite3

        uri = "file:///" + db_path.as_posix().lstrip("/") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            cols = {row[1] for row in con.execute("PRAGMA table_info(sessions)")}
            id_col = next((c for c in ("session_id", "id", "sid") if c in cols), None)
            if id_col is None:
                return None
            wanted = [c for c in ("model_config", "billing_provider", "parent_session_id") if c in cols]
            if not wanted:
                return None
            seen: set[str] = set()
            current = sid
            for _ in range(_SESSION_LINEAGE_MAX_HOPS):
                if not current or current in seen:
                    break
                seen.add(current)
                row = con.execute(
                    f"SELECT {','.join(wanted)} FROM sessions WHERE {id_col} = ?", (current,)
                ).fetchone()
                if not row:
                    break
                data = dict(zip(wanted, row))
                provider = _provider_from_session_row(data)
                if provider:
                    return provider
                nxt = data.get("parent_session_id")
                current = str(nxt).strip() if nxt else ""
        finally:
            con.close()
    except Exception:
        return None
    return None


def _config_provider() -> str:
    """配置里的默认 provider（无会话 / 草稿态的兜底）。"""
    try:
        from hermes_cli.config import load_config  # type: ignore

        model_cfg = (load_config() or {}).get("model") or {}
        if isinstance(model_cfg, dict):
            return _norm_provider(model_cfg.get("provider"))
    except Exception:
        pass
    return ""


def _resolve_active_provider(session: str, model: str) -> tuple[str, str]:
    """三级解析：① model 前缀（仅当它确实是受支持套餐的 provider）→ ② 会话行 → ③ 配置默认。

    前缀为什么要加"受支持套餐"这道闸：桌面给的 slug 可能是 `deepseek/deepseek-v4.1-flash`
    这种「厂商/模型」形态（Command Code 目录就是这样），首段是模型厂商名而不是 provider 名。
    只认注册表里的 provider，其余 slug 交给会话行/配置判断 —— 否则 GOAT 会话会被
    误判成 deepseek 而把芯片藏掉。
    """
    prefix = _provider_from_model(model)
    if prefix and _match_usage_provider(prefix):
        return prefix, "prefix"
    session_provider = _session_provider(session)
    if session_provider:
        return session_provider, "session"
    config_provider = _config_provider()
    if config_provider:
        return config_provider, "config"
    if prefix:  # 未知 provider 前缀：上报原值（判定结果仍是不匹配 → 隐藏）
        return prefix, "prefix"
    return "", "unknown"


def _match_usage_provider(provider: str) -> Optional[ProviderSpec]:
    if not provider:
        return None
    for spec in PROVIDERS.values():
        if provider in spec.model_providers:
            return spec
    return None


@router.get("/gate")
async def gate(session: str = "", model: str = "") -> dict:
    """模型门控判定：当前模型是否属于某个已支持套餐（决定芯片显示/隐藏）。"""
    try:
        provider, source = _resolve_active_provider(session, model)
        spec = _match_usage_provider(provider)
        return {
            "ok": True,
            "matched": spec is not None,
            "provider": spec.id if spec else None,
            "resolvedProvider": provider,
            "resolvedFrom": source,
        }
    except Exception as exc:  # 兜底：拿不准时"不匹配"（隐藏），别误导
        log.warning("opencode-go-usage: gate error: %s", type(exc).__name__)
        return {"ok": False, "matched": False, "error": {"kind": "internal", "message": type(exc).__name__}}


@router.get("/usage")
async def usage(force: bool = False, provider: str = DEFAULT_PROVIDER) -> dict:
    """当前主力 key 的套餐用量（缓存 60s；force=1 绕缓存；provider 选注册表项）。"""
    try:
        spec = PROVIDERS.get(provider)
        if spec is None:
            return {
                "ok": False,
                "error": {"kind": "unknown_provider", "message": f"unknown provider '{provider}'"},
                "known": sorted(PROVIDERS),
            }
        cached = CACHE.get(spec.id)
        fresh = cached is not None and (time.time() - cached[0]) < CACHE_TTL_SECONDS
        if fresh and not force:
            return cached[1]
        payload = _build_payload(spec)
        CACHE[spec.id] = (time.time(), payload)
        return payload
    except Exception as exc:  # 兜底：绝不让 500 冒泡到前端
        log.warning("opencode-go-usage: internal error: %s", type(exc).__name__)
        return {"ok": False, "error": {"kind": "internal", "message": type(exc).__name__}}
