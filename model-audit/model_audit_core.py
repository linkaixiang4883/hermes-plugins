"""model-audit 共享核心（只用 stdlib；agent 进程与 dashboard 进程都会加载）。

加载方式差异（重要）：
  · agent 半 __init__.py —— 插件目录以 package 形式导入 → `from . import model_audit_core`
  · dashboard 半 plugin_api.py —— web server 用 spec_from_file_location 单独装载 → 必须按路径加载

三条硬规则：
  1) calls 只增不改：status 只存**头部自证**的事实态（ok / mismatch / no_signal）；
  2) approved / new_route / body_mismatch / body_only / no_attestation 都是**查询期算**的展示态；
     后面三个是「体证层」——没有自证头时退到 body 的 model 判（容忍版本后缀，见 family_match），
     它对回声型中转（body==alias）没有鉴别力，所以与自证层分开标注；
     `no_attestation` 更进一步：该 provider **结构性不发自证**（实测矩阵见技能文档），
     同族回声等于没有证据——不是采集故障，掉包检测在这家做不到；
  2b) 判定顺序（用户定的标准）：① **内置标准**（BUILTIN_RULES：provider+alias → model+端点）命中 → 一致；
     ② **自定义认可**（approvals 表：provider/model/端点留空即任意）命中 → 已认可；
     ③ 都不命中才分类：**model 变了 → 不一致**，**只有端点变了 → 新路由**。
     内置标准缺失的 alias → 退回「该 profile+provider+alias 最常落到的组合」；
  3) 对 Hermes 的 state.db 只读（取会话标题），失败一律降级为空。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = 2
MAX_LIMIT = 500
DEFAULT_RETENTION_DAYS = 90
TITLE_TTL_SECONDS = 10.0

# 只保留这些响应头（小写精确匹配）。绝不落 Authorization / Cookie / Set-Cookie。
HEADER_ALLOWLIST = frozenset({
    "x-opencode-upstream-model-id", "x-opencode-endpoint-id", "x-opencode-log-id", "x-zen-model",
    "x-litellm-model-id", "x-litellm-model-api-base", "x-request-id", "x-served-by", "cf-ray",
    # Command Code：没有上游 model 头，但有每请求的追踪 id（投诉/排障时给厂商定位用）
    "x-trace-id",
})
UPSTREAM_MODEL_HEADERS = ("x-opencode-upstream-model-id", "x-litellm-model-id")
ENDPOINT_HEADERS = ("x-opencode-endpoint-id", "x-litellm-model-api-base")
# upstream_log_id 列的取值优先级：opencode 的 log id → Command Code 的 trace id
LOG_ID_HEADERS = ("x-opencode-log-id", "x-trace-id")

# 结构性无自证的 provider（实测，2026-09-28）：既没有自证头，body 的 model 也是请求别名回声
# → 体证层对它零鉴别力 → 展示态单列「◌ 无自证」，不冒充"仅体证"。
# 证据：Command Code 全量响应头 + 流式/非流式 body 逐 chunk 实读（见技能里的 provider 自证矩阵）。
NO_SELF_ATTESTATION_PROVIDERS = frozenset({"commandcode"})

_TITLE_CACHE: Dict[tuple, tuple] = {}          # (state_db_path, session_id) -> (title, ts)

# 行归属哪个 profile：优先 profile_name，退回 profile_home（旧行只有 home）。
_PROFILE_EXPR = "COALESCE(NULLIF(profile_name,''), profile_home, '')"

_DDL = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_start REAL NOT NULL, ts_end REAL, duration_s REAL, ttfb_s REAL,
    session_id TEXT, turn_id TEXT, task_id TEXT, api_call_index INTEGER,
    platform TEXT, provider TEXT, base_url TEXT, api_mode TEXT,
    requested_model TEXT, body_model TEXT, upstream_model TEXT,
    endpoint_id TEXT, zen_model TEXT, upstream_log_id TEXT, header_ts REAL,
    finish_reason TEXT, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER,
    profile_home TEXT, profile_name TEXT, status TEXT NOT NULL, headers_json TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_calls_ts ON calls(ts_start DESC);
CREATE INDEX IF NOT EXISTS idx_calls_alias ON calls(requested_model, ts_start DESC);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requested_model TEXT NOT NULL,
    upstream_model TEXT,                          -- 空 = 任意（以端点为准）
    endpoint_id TEXT,                             -- 空 = 任意（以 model 为准）
    note TEXT, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_approvals_alias ON approvals(requested_model);
-- 三项联合唯一（NULL 归一成 ''）：同一个 model 可以在不同端点各有一条认可
CREATE UNIQUE INDEX IF NOT EXISTS uq_approvals
    ON approvals(requested_model, COALESCE(upstream_model,''), COALESCE(endpoint_id,''));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT, updated_at REAL);
"""


# ---------------------------------------------------------------- paths
def plugin_root() -> Path:
    return Path(__file__).resolve().parent


PLUGIN_DATA_DIRNAME = "plugin-data"
PLUGIN_SLUG = "model-audit"


def shared_home() -> Path:
    """**进程级** Hermes home —— 不是 per-request 的 profile 覆盖。

    对账库的数据模型是「跨 profile 一个库 + 行级 profile_name 归属」（页面有 profile 列与过滤器、
    分组统计按 profile 分桶），所以取进程级 home：agent 半与仪表盘后端半按定义解析到同一处。

    为什么不直接用官方 ``plugin_data_dir()``：它每次调用解析 ``get_hermes_home()``，在多 profile
    多路复用下 agent 半（per-turn contextvar）与后端半可能解析到**不同目录 → 写读分裂**。
    ``get_process_hermes_home()`` 的官方 docstring 正是为这类需求写的：

        "Hermes home of the running process, ignoring task overrides. For process-level assets …
         that must stay visible while a request is scoped to another profile."
    """
    try:
        from hermes_constants import get_process_hermes_home        # 官方 API，语义最准
        return Path(get_process_hermes_home())
    except Exception:
        pass
    try:
        from hermes_constants import get_hermes_home                # 老版本退回（无覆盖时二者等价）
        return Path(get_hermes_home())
    except Exception:
        pass
    home = os.environ.get("HERMES_HOME", "").strip()
    return Path(home) if home else Path.home() / ".hermes"


def legacy_db_path(root: Optional[Path] = None) -> Path:
    """<=0.3.0 的位置：插件树内（install 目录 —— remove 会删、update 会 git pull）。

    *root* 仅测试注入用（默认真插件目录），生产路径不受影响。
    """
    return (Path(root) if root else plugin_root()) / "data" / "model_audit.db"


def db_path() -> Path:
    """对账库位置：env 覆盖 → 进程级 home 下的 ``plugin-data/<slug>/``（取舍见 shared_home）。"""
    override = os.environ.get("MODEL_AUDIT_DB")
    if override:
        return Path(override)
    return shared_home() / PLUGIN_DATA_DIRNAME / PLUGIN_SLUG / "model_audit.db"


def state_db_path(profile_home: Optional[str] = None) -> Path:
    """Hermes 的会话库（只读取标题）。按行的 profile_home 解析，测试可用 MODEL_AUDIT_STATE_DB 覆盖。"""
    override = os.environ.get("MODEL_AUDIT_STATE_DB")
    if override:
        return Path(override)
    home = profile_home or os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return Path(home) / "state.db"


class _ClosingConnection(sqlite3.Connection):
    """``with`` 上既提交**又关闭**。

    裸 ``sqlite3.Connection`` 的 ``with`` 只提交、不关闭，连接对象留在引用环里要等**循环 GC**
    才释放句柄 —— Windows 上表现为「文件被占用、改名/删除 WinError 32」。实测：insert_call 之后
    立刻 rename 必失败，``gc.collect()`` 之后就成功。库内所有 ``with connect(...)`` 依赖这条。
    """

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[override]
        try:
            return bool(super().__exit__(exc_type, exc, tb))
        finally:
            self.close()


def connect(path: Optional[Path] = None, *, readonly: bool = False) -> sqlite3.Connection:
    p = Path(path or db_path())
    if readonly:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=2.0, factory=_ClosingConnection)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p), timeout=2.0, factory=_ClosingConnection)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=2000")
    conn.row_factory = sqlite3.Row
    return conn


def schema_ready(path: Optional[Path] = None) -> bool:
    """只读探测：库在、三张表齐、且已是"迁移后"的形状（calls.profile_name / approvals 新唯一索引）。

    客户端（仪表盘后端半）**只用这一步**判断能不能读——不建库、不迁移。
    服务端（agent 半的 register）才允许改 schema（见 ensure_db）。任何异常 → False
    （宁可显示「未初始化」，也不在半成品库上读）。
    """
    p = Path(path or db_path())
    if not p.exists():
        return False
    try:
        conn = connect(p, readonly=True)
        try:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"calls", "approvals", "meta"} <= names:
                return False
            if "profile_name" not in {r[1] for r in conn.execute("PRAGMA table_info(calls)")}:
                return False
            row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='approvals'").fetchone()
            if row and "UNIQUE(requested_model, upstream_model)" in (row[0] or ""):
                return False
            return True
        finally:
            conn.close()          # `with` 只提交不关闭 → Windows 上句柄会吊着（删/改文件名会 WinError 32）
    except Exception:
        return False


def _create_schema(db: Path, *, attempts: int = 5) -> None:
    """DDL + 迁移（幂等）。多进程同时启动时用 busy/locked 重试兜底（SQLite 原生锁 + busy_timeout=2000ms）。"""
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            conn = connect(db)
            try:
                conn.executescript(_DDL)
                _migrate(conn)
                _migrate_approvals(conn)
                conn.commit()
            finally:
                conn.close()
            return
        except sqlite3.OperationalError as exc:
            if any(k in str(exc).lower() for k in ("locked", "busy")):
                last = exc
                time.sleep(0.1 * (i + 1))
                continue
            raise
    if last is not None:
        raise last


def adopt_legacy_db(target: Path, legacy_root: Optional[Path] = None) -> Optional[str]:
    """把插件树内的老库（<=0.3.0 的位置）整库搬到 *target*；返回老库路径（搬了）或 None。

    **仅服务端调用**（单写者）。用 ``sqlite3`` 的 ``backup()`` 而不是移动文件——backup 会带上 WAL
    里尚未 checkpoint 的行，而文件移动在 WAL 模式 / 文件被占用时会留下半成品。

    幂等且安静：*target* 已存在、老库不存在、或有 ``MODEL_AUDIT_DB`` 覆盖 → 什么都不做；
    任何失败都返回 None（下次启动再试），绝不挡主流程。*legacy_root* 仅测试注入用。

    **安全闸**：只有 *target* 就是本插件**默认**库位置（``db_path()``）时才动手。显式路径
    （单测、临时探针、任何 ``ensure_db(<自定义路径>)``）一律**永不**触碰插件树里的生产库——
    否则「拿一个临时路径调 ensure_db」会变成「把生产库搬进临时文件并改名」，测试一跑就毁数据。

    搬完把老库改名 ``*.migrated`` 退场（改不掉就留着）：**我们不再打开它，因此不再构成锁** ——
    doctor 拷不动插件树的根因正是「插件自己开着这个文件」。
    """
    if os.environ.get("MODEL_AUDIT_DB"):
        return None
    if legacy_root is None and Path(target) != db_path():
        return None
    if legacy_root is None:
        # **安全闸（关键，实测踩过）**：当前运行的这份插件必须**就是本 home 下安装的那份**。
        # 少了这条会中招的场景：`hermes plugins validate` / `doctor` 用**临时 HERMES_HOME**
        # 跑真实安装目录里的 `register()` —— 此时 db_path() 解析到临时 home（安全闸 1 因此通过），
        # 而 legacy_db_path() 仍指向**真实生产库** → 会把它「迁移」进一个随后就被丢弃的临时
        # home，并在离开时把真库改名成 .migrated。实测后果：页面突然变空库，9398 行躺在
        # .migrated 里（已在线合并恢复）。
        expected_root = (shared_home() / "plugins" / PLUGIN_SLUG)
        try:
            if Path(plugin_root()).resolve() != expected_root.resolve():
                return None
        except Exception:
            return None
    legacy = legacy_db_path(legacy_root)
    if target.exists() or not legacy.exists():
        return None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(f"file:{legacy}?mode=ro", uri=True, timeout=5.0)
        try:
            dst = sqlite3.connect(str(target), timeout=5.0)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except Exception:
        return None
    try:
        legacy.rename(legacy.with_name(legacy.name + ".migrated"))
        for suffix in ("-wal", "-shm"):
            side = legacy.with_name(legacy.name + suffix)
            if side.exists():
                side.rename(side.with_name(side.name + ".migrated"))
    except Exception:
        pass                                                  # 退场失败不影响正确性
    return str(legacy)


def ensure_db(path: Optional[Path] = None) -> None:
    """建库/迁移（幂等）——**服务端专用**：只由 agent 半（register）调用；客户端只读 schema_ready()。

    单写者 ⇒ 没有「后端半 vs agent 半」的跨半竞态；agent 半自身多进程并存时靠 SQLite 锁 + 重试兜底。
    快路径：schema 已就位直接返回（纯读，不拿写锁）；慢路径：先一次性接收老库（见 adopt_legacy_db），
    再 DDL + 迁移（带重试）。
    """
    db = Path(path or db_path())
    if schema_ready(db):
        return
    adopt_legacy_db(db)
    if schema_ready(db):
        return
    _create_schema(db)


def _migrate_approvals(conn: sqlite3.Connection) -> None:
    """老库的 approvals 带 `UNIQUE(requested_model, upstream_model)`：同一 model 想在不同端点各留一条
    认可会被挡，且无法表达「只认 model」。检测到旧结构就重建表（数据照搬），再补新唯一索引。"""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='approvals'").fetchone()
    if row and "UNIQUE(requested_model, upstream_model)" in (row[0] or ""):
        conn.executescript("""
            ALTER TABLE approvals RENAME TO approvals_old;
            CREATE TABLE approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requested_model TEXT NOT NULL, upstream_model TEXT, endpoint_id TEXT,
                note TEXT, created_at REAL NOT NULL);
            INSERT INTO approvals (id, requested_model, upstream_model, endpoint_id, note, created_at)
                SELECT id, requested_model, upstream_model, endpoint_id, note, created_at FROM approvals_old;
            DROP TABLE approvals_old;
            CREATE INDEX IF NOT EXISTS idx_approvals_alias ON approvals(requested_model);
        """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(approvals)")}
    if "provider" not in cols:                      # v2 → v3：加 provider 维度（同 alias 在不同 provider 下标准不同）
        conn.execute("ALTER TABLE approvals ADD COLUMN provider TEXT")
        conn.execute("DROP INDEX IF EXISTS uq_approvals")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_approvals "
                 "ON approvals(COALESCE(provider,''), requested_model, "
                 "COALESCE(upstream_model,''), COALESCE(endpoint_id,''))")


def _migrate(conn: sqlite3.Connection) -> None:
    """给旧库补列（CREATE TABLE IF NOT EXISTS 不会改已存在的表）。"""
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(calls)")}
        if "profile_name" not in cols:
            conn.execute("ALTER TABLE calls ADD COLUMN profile_name TEXT")
    except Exception:
        pass


def profile_key(profile_name: Any, profile_home: Any) -> str:
    """行归属的 profile 键：name 优先，退回 home 路径。"""
    return str(profile_name or "").strip() or str(profile_home or "").strip()


# ---------------------------------------------------------------- meta / settings
def set_meta(path: Optional[Path], key: str, value: str) -> None:
    with connect(path) as conn:
        conn.execute("INSERT INTO meta (key, value, updated_at) VALUES (?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                     (key, str(value), time.time()))
        conn.commit()


def get_meta(path: Optional[Path]) -> Dict[str, str]:
    try:
        with connect(path, readonly=True) as conn:
            return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    except Exception:
        return {}


def set_setting(path: Optional[Path], key: str, value: str) -> None:
    set_meta(path, key, value)


def get_setting(path: Optional[Path], key: str, default: Optional[str] = None) -> Optional[str]:
    return get_meta(path).get(key, default)


def retention_days(path: Optional[Path]) -> int:
    raw = get_setting(path, "retention_days", str(DEFAULT_RETENTION_DAYS)) or str(DEFAULT_RETENTION_DAYS)
    try:
        return max(1, min(3650, int(raw)))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS


# ---------------------------------------------------------------- judgment
def norm_model(value: Any) -> str:
    return str(value or "").strip().lower()


def model_match(requested: Any, upstream: Any) -> bool:
    """归一化后相等即视为同一模型（上游常带命名空间前缀，如 deepseek/xxx）。"""
    req, up = norm_model(requested), norm_model(upstream)
    if not req or not up:
        return False
    tail = up.rsplit("/", 1)[-1]
    return tail == req or up == req or tail.replace("_", "-") == req


# 体证层专用：比 model_match 宽——容忍版本/日期后缀（gpt-5-mini vs gpt-5-mini-2025-08-07 同族），
# 但 `x vs x-pro` 这种「多出来的部分是名字而不是版本」要判为不同族（否则会漏报）。
_VERSION_TAIL_RE = re.compile(r"^[-._](v?\d[\w.\-]*|latest|snapshot)$", re.IGNORECASE)


def family_match(requested: Any, upstream: Any) -> bool:
    """同族判定（只用于「无自证头 → 看 body」的体证层）：剥命名空间 + 容忍版本/日期后缀。"""
    req = norm_model(requested).rsplit("/", 1)[-1].replace("_", "-")
    up = norm_model(upstream).rsplit("/", 1)[-1].replace("_", "-")
    if not req or not up:
        return False
    if req == up:
        return True
    for longer, shorter in ((up, req), (req, up)):
        if longer.startswith(shorter) and _VERSION_TAIL_RE.match(longer[len(shorter):]):
            return True
    return False


def status_for(requested: Any, upstream: Any) -> str:
    """事实态（落库用）：只可能是 ok / mismatch / no_signal。"""
    if not norm_model(upstream):
        return "no_signal"
    return "ok" if model_match(requested, upstream) else "mismatch"


def route_key(upstream: Any, endpoint: Any) -> str:
    return f"{norm_model(upstream)}|{norm_model(endpoint)}"


# 分组统计可用的维度（UI 下拉 / API 校验共用）。
GROUP_BY_KEYS = ("upstream", "alias", "provider", "endpoint", "profile", "status")

# 展示态的集合：异常 = 真告警；未自证 = 覆盖缺口（不算异常，但可一起筛）。
ANOMALY_STATUSES = ("mismatch", "new_route", "body_mismatch")
UNVERIFIED_STATUSES = ("no_signal", "body_only", "no_attestation")

# ---------------------------------------------------------------- 内置标准（built-in）
# 「这个 provider 下，某个 alias 应该由哪个 model + 哪个端点来服务」——**这是判定标准**：
# 命中 → ✅一致；偏离 → 由「认可表」放行例外，否则按 model/端点偏离分类（不一致 / 新路由）。
# 只放"确定知道正确答案"的条目；alias 没条目时退回「该 provider+alias 最常落到的组合」。
# 目前只有 opencode-go 一条（用户 2026-09-24 提供）。要增改找 Hermes（代码级常量，UI 只读）。
BUILTIN_RULES: Tuple[Dict[str, str], ...] = (
    {"provider": "opencode-go", "alias": "deepseek-flash",
     "model": "deepseek-flash", "endpoint": "deepseek"},
    {"provider": "opencode-go", "alias": "deepseek-v4.1-flash",
     "model": "deepseek/deepseek-v4.1-flash", "endpoint": "deepseek"},
)


def builtin_expected(provider: Any, alias: Any) -> Optional[Tuple[str, str]]:
    """(norm_model, norm_endpoint) 内置标准；没有该 (provider, alias) 的条目 → None。"""
    p, a = norm_model(provider), str(alias or "")
    for r in BUILTIN_RULES:
        if norm_model(r.get("provider")) == p and str(r.get("alias") or "") == a:
            return norm_model(r.get("model")), norm_model(r.get("endpoint"))
    return None


def _group_value(row: Dict[str, Any], by: str, display_status: str) -> str:
    if by == "upstream":
        if row.get("upstream_model"):
            return str(row["upstream_model"])
        body = str(row.get("body_model") or "")
        if not body:
            return "(无信号)"
        return f"{body}（{'无自证' if display_status == 'no_attestation' else '仅体证'}）"
    if by == "alias":
        return str(row.get("requested_model") or "")
    if by == "provider":
        return str(row.get("provider") or "(未知)")
    if by == "endpoint":
        return str(row.get("endpoint_id") or "(无端点)")
    if by == "profile":
        return profile_key(row.get("profile_name"), row.get("profile_home")) or "(未知)"
    if by == "status":
        return display_status
    return ""


# ---------------------------------------------------------------- row
def _first(headers: Dict[str, str], names: Iterable[str]) -> Optional[str]:
    for n in names:
        v = headers.get(n)
        if v:
            return str(v)
    return None


def build_row(payload: Dict[str, Any], headers: Optional[Dict[str, str]],
              header_ts: Optional[float], *, profile_home: str,
              profile_name: Optional[str] = None) -> Dict[str, Any]:
    """hook payload + 响应头 → 一行记录。绝不取 prompt / 回复正文，也不写任何"认可"状态。"""
    hdrs = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    keep = {k: v for k, v in hdrs.items() if k in HEADER_ALLOWLIST}
    requested = payload.get("model")
    upstream = _first(keep, UPSTREAM_MODEL_HEADERS)
    started = payload.get("started_at")
    ended = payload.get("ended_at")
    first_chunk = payload.get("first_chunk_at")
    usage = payload.get("usage") or {}
    return {
        "ts_start": float(started or time.time()),
        "ts_end": float(ended) if ended else None,
        "duration_s": (float(payload.get("api_duration")) if payload.get("api_duration") else None),
        "ttfb_s": (float(first_chunk) - float(started)) if (first_chunk and started) else None,
        "session_id": payload.get("session_id"),
        "turn_id": payload.get("turn_id"),
        "task_id": payload.get("task_id"),
        "api_call_index": payload.get("api_call_count"),
        "platform": payload.get("platform"),
        "provider": payload.get("provider"),
        "base_url": payload.get("base_url"),
        "api_mode": payload.get("api_mode"),
        "requested_model": requested,
        "body_model": payload.get("response_model"),
        "upstream_model": upstream,
        "endpoint_id": _first(keep, ENDPOINT_HEADERS),
        "zen_model": keep.get("x-zen-model"),
        "upstream_log_id": _first(keep, LOG_ID_HEADERS),
        "header_ts": header_ts,
        "finish_reason": payload.get("finish_reason"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "profile_home": profile_home,
        "profile_name": profile_name,
        "status": status_for(requested, upstream),
        "headers_json": json.dumps(keep, ensure_ascii=False) if keep else None,
        "created_at": time.time(),
    }


_COLUMNS = ("ts_start", "ts_end", "duration_s", "ttfb_s", "session_id", "turn_id", "task_id",
            "api_call_index", "platform", "provider", "base_url", "api_mode", "requested_model",
            "body_model", "upstream_model", "endpoint_id", "zen_model", "upstream_log_id",
            "header_ts", "finish_reason", "input_tokens", "output_tokens", "total_tokens",
            "profile_home", "profile_name", "status", "headers_json", "created_at")


def insert_call(path: Optional[Path], row: Dict[str, Any]) -> None:
    sql = f"INSERT INTO calls ({','.join(_COLUMNS)}) VALUES ({','.join('?' * len(_COLUMNS))})"
    with connect(path) as conn:
        conn.execute(sql, tuple(row.get(c) for c in _COLUMNS))
        conn.commit()


# ---------------------------------------------------------------- approvals（视图层）
def add_approval(path: Optional[Path], requested_model: str,
                 upstream_model: Optional[str] = None, endpoint_id: Optional[str] = None,
                 note: Optional[str] = None, provider: Optional[str] = None) -> bool:
    """幂等新增认可（UNIQUE 冲突则忽略）。返回 True 表示调用被接受。

    匹配语义：`requested_model` 必填；`provider` / `upstream_model` / `endpoint_id` **留空 = 任意**
    （以其余项为准），但后两项不能都空（那等于认可该 alias 的所有行）。
    """
    req = str(requested_model or "").strip()
    prov = str(provider or "").strip() or None
    up = str(upstream_model or "").strip() or None
    ep = str(endpoint_id or "").strip() or None
    if not req or (not up and not ep):
        return False
    with connect(path) as conn:
        conn.execute("INSERT OR IGNORE INTO approvals "
                     "(provider, requested_model, upstream_model, endpoint_id, note, created_at) "
                     "VALUES (?,?,?,?,?,?)",
                     (prov, req, up, ep, note, time.time()))
        conn.commit()
    return True


def list_approvals(path: Optional[Path]) -> List[Dict[str, Any]]:
    with connect(path, readonly=True) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM approvals ORDER BY created_at DESC")]


def delete_approval(path: Optional[Path], approval_id: int) -> bool:
    with connect(path) as conn:
        cur = conn.execute("DELETE FROM approvals WHERE id = ?", (int(approval_id),))
        conn.commit()
        return cur.rowcount > 0


def approved_map(path: Optional[Path]) -> Dict[str, List[Tuple[Optional[str], Optional[str], Optional[str]]]]:
    """{requested_model: [(norm(provider) or None, norm(upstream_model) or None, norm(endpoint_id) or None), ...]}

    每项留空 = 该维度任意；命中判定见 `_approval_hit`。
    """
    out: Dict[str, List[Tuple[Optional[str], Optional[str], Optional[str]]]] = {}
    for r in list_approvals(path):
        prov = norm_model(r.get("provider")) or None
        up = norm_model(r.get("upstream_model")) or None
        ep = norm_model(r.get("endpoint_id")) or None
        out.setdefault(str(r["requested_model"]), []).append((prov, up, ep))
    return out


def _approval_hit(rules: Iterable[Tuple[Optional[str], Optional[str], Optional[str]]],
                  provider: str, served: str, endpoint: str) -> bool:
    """命中任一认可规则即算「已认可」：规则里留空的那项视为任意。"""
    for prov, up, ep in rules or ():
        if prov and prov != provider:
            continue
        if up and up != served:
            continue
        if ep and ep != endpoint:
            continue
        return True
    return False


# ---------------------------------------------------------------- titles（只读 state.db）
def session_titles_detail(session_ids: Iterable[str], *,
                          path: Optional[Path] = None) -> Dict[str, Tuple[str, str]]:
    """{session_id: (title, via)}；`via` 说明标题从哪来：

    - ``""``           直查命中（会话自己的标题）
    - ``"compression"`` 沿**子**会话链向下取的（压缩=分叉：旧会话 title 被清 NULL，标题归新子会话）
    - ``"parent"``     沿**父**会话链向上取的（子智能体 delegate_task 的会话不生成标题，取父会话的）

    任何失败 → {}（调用方降级为空标题）。
    """
    ids = sorted({str(s) for s in (session_ids or []) if s})
    if not ids:
        return {}
    db = Path(path or state_db_path())
    if not db.exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=1.0)
        try:
            marks = ",".join("?" * len(ids))
            rows = conn.execute(f"SELECT id, title FROM sessions WHERE id IN ({marks})", ids).fetchall()
            out: Dict[str, Tuple[str, str]] = {str(r[0]): (str(r[1] or ""), "") for r in rows}

            def _empty(sid: str) -> bool:
                return not (out.get(sid) or ("",))[0]

            missing = [s for s in ids if _empty(s)]
            if missing:
                for sid, title in _titles_from_descendants(conn, missing).items():
                    out[sid] = (title, "compression")
                still = [s for s in missing if _empty(s)]
                if still:
                    for sid, title in _titles_from_ancestors(conn, still).items():
                        out[sid] = (title, "parent")
            return out
        finally:
            conn.close()
    except Exception:
        return {}


def session_titles(session_ids: Iterable[str], *, path: Optional[Path] = None) -> Dict[str, str]:
    """只取标题（旧契约）；来源信息见 session_titles_detail。"""
    return {k: v[0] for k, v in session_titles_detail(session_ids, path=path).items()}


def _titles_from_ancestors(conn: sqlite3.Connection, session_ids: List[str]) -> Dict[str, str]:
    """沿 parent_session_id **向上**找最近的非空标题（子智能体会话取父会话标题）；找不到 → {}。

    `ORDER BY root, depth ASC` + setdefault = 取**最近的**祖先（父 > 祖父…）。
    """
    try:
        seed = ",".join("(?)" for _ in session_ids)
        sql = f"""
        WITH RECURSIVE seed(id) AS (VALUES {seed}),
        chain(root, id, parent, title, depth) AS (
            SELECT s.id, s.id, s.parent_session_id, s.title, 0
              FROM sessions s WHERE s.id IN (SELECT id FROM seed)
            UNION ALL
            SELECT c.root, p.id, p.parent_session_id, p.title, c.depth + 1
              FROM sessions p JOIN chain c ON p.id = c.parent
             WHERE c.depth < 4
        )
        SELECT root, title FROM chain
         WHERE title IS NOT NULL AND title <> ''
         ORDER BY root, depth ASC
        """
        found: Dict[str, str] = {}
        for root, title in conn.execute(sql, session_ids):
            found.setdefault(str(root), str(title))
        return found
    except Exception:
        return {}


def _titles_from_descendants(conn: sqlite3.Connection, session_ids: List[str]) -> Dict[str, str]:
    """沿 parent_session_id 向下（压缩产生的子会话）找链尾最近的非空标题；找不到 → {}。

    深链（同一对话反复压缩）取最深的一个：`ORDER BY root, depth DESC` + setdefault。
    """
    try:
        seed = ",".join("(?)" for _ in session_ids)
        sql = f"""
        WITH RECURSIVE seed(id) AS (VALUES {seed}),
        chain(root, id, title, depth) AS (
            SELECT s.id, s.id, s.title, 0 FROM sessions s WHERE s.id IN (SELECT id FROM seed)
            UNION ALL
            SELECT c.root, s.id, s.title, c.depth + 1
              FROM sessions s JOIN chain c ON s.parent_session_id = c.id
             WHERE c.depth < 10
        )
        SELECT root, title FROM chain
         WHERE title IS NOT NULL AND title <> ''
         ORDER BY root, depth DESC
        """
        found: Dict[str, str] = {}
        for root, title in conn.execute(sql, session_ids):
            found.setdefault(str(root), str(title))
        return found
    except Exception:
        return {}


def attach_titles(rows: List[Dict[str, Any]], *, path: Optional[Path] = None) -> None:
    """给行原地补 session_title / session_title_via：按每行的 profile_home 找对应 state.db；
    带 TTL 缓存；失败为空串。via 见 session_titles_detail（"" / "compression" / "parent"）。"""
    now = time.time()
    groups: Dict[str, set] = {}
    for r in rows:
        sid = str(r.get("session_id") or "")
        if not sid:
            continue
        dbp = str(path) if path else str(state_db_path(r.get("profile_home")))
        groups.setdefault(dbp, set()).add(sid)
    for dbp, ids in groups.items():
        missing = [s for s in ids
                   if (dbp, s) not in _TITLE_CACHE or now - _TITLE_CACHE[(dbp, s)][1] > TITLE_TTL_SECONDS]
        if missing:
            for sid, (title, via) in session_titles_detail(missing, path=Path(dbp)).items():
                _TITLE_CACHE[(dbp, sid)] = (title, now, via)
            for sid in missing:                     # 查不到的也缓存空值，避免每次重查
                _TITLE_CACHE.setdefault((dbp, sid), ("", now, ""))
    for r in rows:
        sid = str(r.get("session_id") or "")
        dbp = str(path) if path else str(state_db_path(r.get("profile_home")))
        cached = _TITLE_CACHE.get((dbp, sid), ("", 0, ""))
        r["session_title"] = cached[0]
        r["session_title_via"] = cached[2] if len(cached) > 2 else ""


# ---------------------------------------------------------------- retention（仅手动调用）
def prune_calls(path: Optional[Path], days: Optional[int] = None) -> int:
    """删除 ts_start 早于 now-days 的 calls 行，返回删除行数（approvals 不动）。只由用户点按钮触发。"""
    d = retention_days(path) if days is None else max(1, min(3650, int(days)))
    cutoff = time.time() - d * 86400
    with connect(path) as conn:
        cur = conn.execute("DELETE FROM calls WHERE ts_start < ?", (cutoff,))
        deleted = int(cur.rowcount or 0)
        conn.commit()
    try:
        set_meta(path, "last_prune_ts", str(time.time()))
        set_meta(path, "last_prune_deleted", str(deleted))
    except Exception:
        pass
    return deleted


# ---------------------------------------------------------------- queries
def _clamp_limit(limit: Any) -> int:
    return max(1, min(MAX_LIMIT, int(limit)))


def _dominant_pairs(conn: sqlite3.Connection, cutoff: float) -> Dict[tuple, Tuple[str, str]]:
    """每个 (profile, provider, alias) **最常落到的 (model, 端点) 组合** —— 没有内置标准的 alias 的基准。

    只在内置标准缺失时使用；一个组合"最常出现"不代表它正确，只是"目前的路由习惯"。
    """
    rows = conn.execute(
        f"""SELECT {_PROFILE_EXPR} AS prof, COALESCE(provider,'') AS prov, requested_model AS alias,
                  COALESCE(upstream_model,'') AS md, COALESCE(endpoint_id,'') AS ep,
                  COUNT(*) AS n, MAX(ts_start) AS last
           FROM calls WHERE ts_start >= ? AND upstream_model IS NOT NULL AND upstream_model != ''
           GROUP BY prof, prov, alias, md, ep ORDER BY prof, prov, alias, n DESC, last DESC""",
        (cutoff,)).fetchall()
    out: Dict[tuple, Tuple[str, str]] = {}
    for r in rows:
        out.setdefault((r["prof"], norm_model(r["prov"]), r["alias"]),
                       (norm_model(r["md"]), norm_model(r["ep"])))
    return out


def _display_status(row: Dict[str, Any], dominant: Dict[tuple, Tuple[str, str]],
                    approved: Dict[str, List[Tuple[Optional[str], Optional[str], Optional[str]]]]) -> str:
    """展示态（查询期算）。**判定顺序**（用户 2026-09-24 定的标准）：

    1) **内置标准**（`BUILTIN_RULES`：provider+alias → model+端点）命中 → ✅一致；
    2) **自定义认可**（认可表；provider/model/端点任一留空即任意）命中 → 🟢已认可（对内置标准的例外）；
    3) 都不命中才分类 —— **model 变了 → ❌不一致**，**只有端点变了 → ⚠️新路由**。
       期望值 = 内置标准；该 alias 没有内置条目 → 退回「该 profile+provider+alias 最常落到的组合」。

    体证层（没有自证头）单独处理：body 与请求同族 → ○仅体证；不同族 → ⚠️体证不同；
    同族但 provider 在 NO_SELF_ATTESTATION_PROVIDERS 里 → ◌ 无自证（回声，零鉴别力）。
    """
    req = str(row.get("requested_model") or "")
    provider = norm_model(row.get("provider"))
    endpoint = norm_model(row.get("endpoint_id"))
    up = norm_model(row.get("upstream_model"))
    rules = approved.get(req) or ()
    if not up:
        body = str(row.get("body_model") or "")
        nbody = norm_model(body)
        if not nbody:
            return "no_signal"
        # 体证层没有端点信息 → 只有「端点任意」的规则能命中
        if _approval_hit(rules, provider, nbody, endpoint):
            return "approved"
        if not family_match(req, body):
            return "body_mismatch"       # 不同族仍是真信号，哪怕该 provider 结构性无自证
        # 同族：结构性无自证的 provider 单列「无自证」（body==alias 的回声不算证据）
        return "no_attestation" if provider in NO_SELF_ATTESTATION_PROVIDERS else "body_only"
    # 1) 内置标准
    expected = builtin_expected(provider, req)
    if expected and (up, endpoint) == expected:
        return "ok"
    # 2) 自定义认可（内置标准的例外）
    if _approval_hit(rules, provider, up, endpoint):
        return "approved"
    # 3) 分类：不一致 / 新路由
    if not expected:
        pk = profile_key(row.get("profile_name"), row.get("profile_home"))
        expected = dominant.get((pk, provider, req))
    if expected:
        want_model, want_ep = expected
        if up != want_model or row.get("status") == "mismatch":
            return "mismatch"
        if want_ep and endpoint != want_ep:
            return "new_route"
        return "ok"
    return "mismatch" if row.get("status") == "mismatch" else "ok"


def query_rows(path: Optional[Path], *, days: int = 7, limit: int = 200, offset: int = 0,
               only_anomaly: bool = False, include_no_signal: bool = False,
               alias: Optional[str] = None, session_id: Optional[str] = None,
               profile: Optional[str] = None) -> Dict[str, Any]:
    limit = _clamp_limit(limit)
    offset = max(0, int(offset))
    days = max(1, int(days))
    cutoff = time.time() - days * 86400
    with connect(path, readonly=True) as conn:
        dominant = _dominant_pairs(conn, cutoff)
        approved = approved_map(path)
        where = ["ts_start >= ?"]
        params: list = [cutoff]
        if alias:
            where.append("requested_model = ?"); params.append(alias)
        if session_id:
            where.append("session_id = ?"); params.append(session_id)
        if profile:
            where.append(f"{_PROFILE_EXPR} = ?"); params.append(profile)
        sql = f"SELECT * FROM calls WHERE {' AND '.join(where)} ORDER BY ts_start DESC LIMIT ? OFFSET ?"
        rows = [dict(r) for r in conn.execute(sql, (*params, limit, offset))]
    for r in rows:
        r["status"] = _display_status(r, dominant, approved)
        r["profile_key"] = profile_key(r.get("profile_name"), r.get("profile_home"))
        r.pop("headers_json", None)
    if only_anomaly:
        keep = set(ANOMALY_STATUSES)
        if include_no_signal:                      # 「含未自证」= 无信号 + 仅体证
            keep |= set(UNVERIFIED_STATUSES)
        rows = [r for r in rows if r["status"] in keep]
    return {"rows": rows, "limit": limit, "offset": offset, "days": days, "total": len(rows)}


def summarize(path: Optional[Path], *, days: int = 7,
              profile: Optional[str] = None, group_by: str = "alias") -> Dict[str, Any]:
    days = max(1, int(days))
    cutoff = time.time() - days * 86400
    with connect(path, readonly=True) as conn:
        dominant = _dominant_pairs(conn, cutoff)
        approved = approved_map(path)
        where = "ts_start >= ?"
        params: list = [cutoff]
        if profile:
            where += f" AND {_PROFILE_EXPR} = ?"
            params.append(profile)
        rows = [dict(r) for r in conn.execute(
            f"SELECT requested_model, upstream_model, body_model, endpoint_id, provider, status, "
            f"profile_name, profile_home, duration_s, ts_start "
            f"FROM calls WHERE {where}", tuple(params))]
    counts = {"calls": 0, "ok": 0, "approved": 0, "mismatch": 0, "new_route": 0,
              "body_mismatch": 0, "body_only": 0, "no_signal": 0, "no_attestation": 0}
    by_alias: Dict[str, Dict[str, Any]] = {}
    by_profile: Dict[str, int] = {}
    groups: Dict[str, Dict[str, Any]] = {}
    use_group = group_by if group_by in GROUP_BY_KEYS else None
    for r in rows:
        st = _display_status(r, dominant, approved)
        counts["calls"] += 1
        counts[st] = counts.get(st, 0) + 1
        pk = profile_key(r.get("profile_name"), r.get("profile_home"))
        by_profile[pk] = by_profile.get(pk, 0) + 1
        a = by_alias.setdefault(str(r.get("requested_model")),
                                {"alias": r.get("requested_model"), "calls": 0, "anomalies": 0, "routes": {}})
        a["calls"] += 1
        if st in ANOMALY_STATUSES:
            a["anomalies"] += 1
        rk = route_key(r.get("upstream_model"), r.get("endpoint_id"))
        a["routes"][rk] = a["routes"].get(rk, 0) + 1
        if use_group:
            key = _group_value(r, use_group, st)
            g = groups.setdefault(key, {"key": key, "calls": 0, "anomalies": 0, "no_signal": 0,
                                        "unverified": 0, "approved": 0, "routes": set(),
                                        "mismatch": 0, "new_route": 0, "body_mismatch": 0,
                                        "_dur": [], "_aliases": {}, "_endpoints": {}, "last_ts": 0.0})
            g["calls"] += 1
            if st in ANOMALY_STATUSES:
                g["anomalies"] += 1
            if st in ("mismatch", "new_route", "body_mismatch"):
                g[st] += 1                      # 异常拆开：❌不一致 / ⚠️新路由 / ⚠️体证不同
            if st == "no_signal":
                g["no_signal"] += 1
            if st in UNVERIFIED_STATUSES:
                g["unverified"] += 1
            if st == "approved":
                g["approved"] += 1
            al = str(r.get("requested_model") or "(未知)")
            g["_aliases"][al] = g["_aliases"].get(al, 0) + 1
            ep = str(r.get("endpoint_id") or "(无端点)")
            g["_endpoints"][ep] = g["_endpoints"].get(ep, 0) + 1
            if r.get("duration_s"):
                g["_dur"].append(float(r["duration_s"]))
            g["last_ts"] = max(g["last_ts"], float(r.get("ts_start") or 0))
            if rk.strip("|"):
                g["routes"].add(rk)
    group_rows = []
    for g in groups.values():
        durs = g.pop("_dur")
        g["avg_duration_s"] = round(sum(durs) / len(durs), 1) if durs else None
        g["routes"] = len(g["routes"])
        # 组里到底混了哪些 alias / 端点（否则按上游 model 分组时看不出异常来自哪个 alias）
        g["aliases"] = sorted(([k, v] for k, v in g.pop("_aliases").items()), key=lambda x: -x[1])
        g["endpoints"] = sorted(([k, v] for k, v in g.pop("_endpoints").items()), key=lambda x: -x[1])
        group_rows.append(g)
    group_rows.sort(key=lambda g: (-g["anomalies"], -g["calls"]))
    aliases = sorted(by_alias.values(), key=lambda a: (-a["anomalies"], -a["calls"]))
    profiles = sorted(({"key": k, "calls": v} for k, v in by_profile.items()),
                      key=lambda p: -p["calls"])
    return {"totals": counts, "by_alias": aliases, "profiles": profiles,
            "groups": group_rows, "group_by": use_group or "alias",
            "days": days, "retention_days": retention_days(path)}
