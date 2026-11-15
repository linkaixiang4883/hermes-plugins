"""OpenDesign Cloud（open-design.ai）模型 provider。

网关：``https://amr-link.open-design.ai/v1`` —— 同一 base 提供
``/chat/completions``、``/responses``、``/messages``、``/images/generations``、``/models``。
鉴权：``Authorization: Bearer <运行时 key>``（key 由 Hermes 框架按 ``env_vars`` 解析，插件不读 env）。

本期只接 **chat completions**（``api_mode="chat_completions"``）。其余两个面不接，理由：
- ``/responses``：思考内容只有被改写的 ``summary``；且 Hermes 的 ``gpt-5*`` 自动改判不会在本
  插件上触发（升级块被 ``api_mode is None`` 门控，宿主总是显式传 ``runtime["api_mode"]``）。
- ``/messages``：``reasoning_effort`` 在该面无效（只认 ``thinking``），且上游存在
  「200 + 空 content 仍计费」的已知缺陷；Anthropic transport 还会绕过 profile hooks。

**元数据优先**（2026-11-15 用真 key 实测）：``GET /v1/models`` 每个条目都带
``metadata.context_limit`` / ``metadata.output_budget`` / ``architecture.input_modalities`` /
``metadata.cost`` / ``metadata.capability`` / ``default`` / ``enabled``。本插件：

- ``live_context_length()`` 用 **``context_limit``**（不写死）；``fetch_models()`` 走同一份目录；
- 静态 ``MODELS`` 表只是**离线兜底**（值取自同一次 /models 快照，见 ``tests/fixtures/models.json``）；
- **不发送 ``max_tokens``**（不覆盖 ``get_max_tokens``，``default_max_tokens=None``）：交给服务端按模型自己定，
  与内置 ``opencode-zen`` / ``commandcode`` 的默认做法一致；Hermes 在截断时会自动加档重试
  （``turn_truncation``）、在「输入 + max_tokens 超窗」时会自动降档（``turn_overflow._clamp_output_cap``）。
  ``/models`` 的 ``output_budget`` 仍解析出来，只作观察/对账，不进请求（实测它不是模型输出上限：
  deepseek-v4.1-flash 发 128k~1,048,576 都 200；OD 客户端自己用 LiteLLM 表 + 覆写，也不读该字段）；
- ``architecture.input_modalities`` 决定每模型 ``supports_vision``（``deepseek-v4-pro`` /
  ``hy4-preview`` / ``deepseek-v4-flash`` / ``deepseek-v4.1-flash-eco`` 的目录声明都是纯文本）。

预算规则：网关按 ``输入 + max_tokens ≤ context_limit`` 判超长。Hermes 压缩器已按
``context_length − agent.max_tokens`` 扣预留，所以 ``context_window`` **报目录里的窗口**
（不报输入预算，避免双扣）；唯一例外是 <512K 的小窗（``kimi-k2.7-code``）：报
``context_limit − 65,536``，否则 75% 压缩地板 + 预留正好顶满。

思考：只发顶层 ``reasoning_effort``（``thinking`` 被网关静默忽略）。词表按模型族实测分组
（``/models`` 不提供 effort 信息，这部分只能靠探测）：GLM 只收 low/high/max、
``minimax-m3.1-flash`` 没有 none、eco 没有 ultra。``ultra`` 在进入 hook 前已被 Hermes 折成 ``max``。

错误分类**故意不覆盖**：429 / 额度等一律交回 Hermes 内置分类器（``rate_limit`` → 先原地重试、
再轮换凭据、再 fallback）。插件不改上游返回的语义，也没有「按 key 还是按 membership 限流」的实测依据。

零私有导入：只 import ``providers`` / ``providers.base``（官方公开插件 API 白名单内）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple

from providers import register_provider
from providers.base import ProviderProfile

logger = logging.getLogger(__name__)

BASE_URL = "https://amr-link.open-design.ai/v1"
USER_AGENT = "hermes-opendesign-plugin/0.3.2"

# ── reasoning_effort 词表：网关实测分组（不是 Hermes 核内厂商表）─────────────
EFFORT_FULL8: Tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "xhigh", "ultra", "max")
EFFORT_NO_ULTRA: Tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
EFFORT_NO_NONE: Tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh", "max")
EFFORT_GLM: Tuple[str, ...] = ("low", "high", "max")

FAMILY_FULL8 = "full8"
FAMILY_NO_ULTRA = "no_ultra"
FAMILY_NO_NONE = "no_none"
FAMILY_GLM = "glm"

_EFFORTS: Dict[str, Tuple[str, ...]] = {
    FAMILY_FULL8: EFFORT_FULL8,
    FAMILY_NO_ULTRA: EFFORT_NO_ULTRA,
    FAMILY_NO_NONE: EFFORT_NO_NONE,
    FAMILY_GLM: EFFORT_GLM,
}

# GLM 只有三档真实强度：把 Hermes 的八档按语义折到最近的一档（medium/high → high）。
_GLM_MAP: Dict[str, str | None] = {
    "none": None,
    "minimal": "low",
    "low": "low",
    "medium": "high",
    "high": "high",
    "xhigh": "max",
    "ultra": "max",
    "max": "max",
}

_CANONICAL_ORDER: Tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "xhigh", "ultra", "max")

# ── 离线兜底表：id -> (context_limit, output_budget, vision, effort 族, model_family) ──
# 值 = 2026-11-15 真 key 抓到的 /v1/models 快照（tests/fixtures/models.json）。
MODELS: Dict[str, Tuple[int, Optional[int], bool, str, str]] = {
    "deepseek-v4.1-flash": (1_048_000, 128_000, True, FAMILY_FULL8, "deepseek-flash"),
    "deepseek-v4.1-flash-eco": (1_048_000, 128_000, False, FAMILY_NO_ULTRA, "deepseek-flash"),
    "deepseek-v4-flash": (1_048_000, 32_000, False, FAMILY_FULL8, "deepseek-flash"),
    "deepseek-v4-flash-vision-exp": (1_048_000, 32_000, True, FAMILY_FULL8, "deepseek-flash"),
    "deepseek-v4-pro": (1_048_000, 128_000, False, FAMILY_FULL8, "deepseek"),
    "claude-haiku-5.5": (1_000_000, 128_000, True, FAMILY_NO_ULTRA, "claude-haiku"),
    "gpt-6-luna": (1_050_000, 128_000, True, FAMILY_FULL8, "gpt-luna"),
    "glm-5.3-flash": (1_048_000, 32_000, True, FAMILY_GLM, "glm-flash"),
    "glm-5.3-flashx": (1_000_000, 32_000, True, FAMILY_GLM, "glm-flash"),
    "kimi-k2.7-code": (262_000, 32_000, True, FAMILY_NO_ULTRA, "kimi-k2"),
    "mimo-v2.6-flash": (1_048_000, 32_000, True, FAMILY_NO_ULTRA, "mimo-flash"),
    "mimo-v2.6-pro": (1_048_000, 32_000, True, FAMILY_NO_ULTRA, "mimo"),
    "minimax-m3.1-flash": (1_000_000, None, True, FAMILY_NO_NONE, "minimax"),
    "hy4-preview": (1_048_000, 32_000, False, FAMILY_NO_ULTRA, "hunyuan"),
}

# 只放全套餐（含免费层）都可用的模型；其余交给实时 /v1/models。
FALLBACK_MODELS: Tuple[str, ...] = ("deepseek-v4.1-flash",)

# 目录里混着的生图/视频模型前缀（与 open-design 自己的聊天面过滤一致）。
MEDIA_PREFIXES: Tuple[str, ...] = (
    "gpt-image-",
    "nano-banana-",
    "seedream-",
    "seedance-",
    "doubao-seedance-",
    "veo-",
    "imagen-",
)

# 单次请求安全输出上限（网关：输入 + max_tokens ≤ 窗口）。
# 小窗预留：<512K 的窗口按「窗口 − 该值」上报（压缩地板 75% + 输出预留才能留出余量）。
SMALL_WINDOW_RESERVE = 65_536
SMALL_WINDOW = 512_000
_CATALOG_TTL = 600.0

# (base_url, key 指纹) -> (抓取时间, {id: {...}})；不存 key 本身。
_CATALOG_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Dict[str, Any]]]] = {}

# 最近一次**成功抓取**的目录（不按凭据区分）。``get_model_context_length()`` 只读它：
# step 0d 是纯函数、拿不到凭据，遍历所有缓存条目会跨凭据串味。
# ⚠️ 也不区分 base_url（该函数没有 base_url 形参）：同一进程里若先抓过自定义网点，这里就是网点的
# 目录。单网点（默认）无影响；多网点共用进程时以「最近一次抓取」为准，属已知限制（README 已记）。
_PREFERRED_CATALOG: Dict[str, Dict[str, Any]] = {}

# 由目录补进 model_capabilities 的模型 id（不含静态 14 条）。后续抓取允许**更新**这些条目，
# 静态表仍然只增不改 —— 网关补全 architecture 或修正 context_limit 时要能生效。
_REFRESHED_IDS: set[str] = set()

DESCRIPTION = (
    "OpenDesign Cloud（open-design.ai）套餐制模型网关 —— 单 provider：amr-link.open-design.ai/v1，"
    "OPENDESIGN_API_KEY（sk-amr 运行时 key）。chat completions 主路径；上下文/输出/图片模态取自"
    "/v1/models 的 metadata（离线用内置快照兜底）；生图模型自动过滤。"
)


# ── /v1/models 目录：抓取、解析、缓存 ────────────────────────────────────────
def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha1((api_key or "").encode("utf-8")).hexdigest()[:10]


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_catalog(payload: Any) -> Dict[str, Dict[str, Any]]:
    """把 /v1/models 响应解析成 ``{id: {context, output, vision, enabled, default}}``（纯函数）。"""
    items = payload.get("data") if isinstance(payload, dict) else payload
    catalog: Dict[str, Dict[str, Any]] = {}
    for item in items or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        meta_obj = item.get("metadata")
        meta: Dict[str, Any] = meta_obj if isinstance(meta_obj, dict) else {}
        arch_obj = item.get("architecture")
        arch: Dict[str, Any] = arch_obj if isinstance(arch_obj, dict) else {}
        mods_obj = arch.get("input_modalities")
        modalities: list[Any] = mods_obj if isinstance(mods_obj, list) else []
        catalog[str(item["id"])] = {
            "context": _positive_int(meta.get("context_limit")),
            "output": _positive_int(meta.get("output_budget")),
            "vision": "image" in modalities,
            "enabled": item.get("enabled") is not False,
            "default": item.get("default") is True,
        }
    return catalog


def fetch_catalog(api_key: str, base_url: str | None = None, timeout: float = 8.0) -> Optional[Dict[str, Dict[str, Any]]]:
    """带 Bearer 拉一次 /v1/models；失败返回 None（调用方回落静态表）。"""
    if not api_key:
        return None
    url = (base_url or BASE_URL).rstrip("/") + "/models"
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"Bearer {api_key}")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("opendesign: /models fetch failed: %s", exc)
        return None
    return parse_catalog(payload) or None


def cached_catalog(api_key: str, base_url: str | None = None, *, timeout: float = 8.0) -> Optional[Dict[str, Dict[str, Any]]]:
    """进程内 10 分钟缓存；key 只以指纹参与缓存键。

    成功抓取时顺带做两件事：① 记成 ``_PREFERRED_CATALOG``（step 0d 的唯一读源）；
    ② 用目录补 ``model_capabilities`` 里缺的模型（只增不改，见 ``_refresh_capabilities``）。
    """
    global _PREFERRED_CATALOG
    cache_key = ((base_url or BASE_URL).rstrip("/"), _key_fingerprint(api_key))
    now = time.time()
    hit = _CATALOG_CACHE.get(cache_key)
    if hit and now - hit[0] < _CATALOG_TTL:
        return hit[1]
    catalog = fetch_catalog(api_key, base_url, timeout=timeout)
    if catalog is not None:
        _CATALOG_CACHE[cache_key] = (now, catalog)
        _PREFERRED_CATALOG = catalog
        _refresh_capabilities(catalog, base_url=base_url)
    return catalog or (hit[1] if hit else None)


def _reported_context(window: Optional[int]) -> Optional[int]:
    """窗口 → 报给 Hermes 的 ctx：≥512K 原样；小窗减去输出预留。

    窗口比预留还小时（<65,536）不能硬减 —— 那会得出 1 token，step 0d 的 `> 0` 校验会放行，
    模型拿到 1 token 上下文。这类极小窗按 75%（与压缩地板同口径）报。
    """
    if not window:
        return None
    if window <= SMALL_WINDOW_RESERVE:
        return max(int(window * 0.75), 1024)
    if window < SMALL_WINDOW:
        return window - SMALL_WINDOW_RESERVE
    return window


def _refresh_capabilities(catalog: Dict[str, Dict[str, Any]], *, base_url: str | None = None) -> None:
    """用实时目录给 ``model_capabilities`` 补缺失条目（静态表**只增不改**）。

    为什么必须补：``agent/image_routing.py`` 做视觉判定时按**精确 model id** 查
    ``ProviderProfile.model_capabilities``，查不到就退回 models.dev 探测 —— OpenDesign 不在
    models.dev 里，结果恒为 unknown → 图片被静默降级成文字摘要。
    为什么只增不改：静态表是人工校准过的（含小窗预留、模态修正），目录里的值只允许填补空位；
    但**由目录补进来的条目**（``_REFRESHED_IDS``）允许在后续抓取时更新 —— 网关补全
    ``architecture`` 或修正 ``context_limit`` 时要能生效。

    只对**默认 base_url** 生效：``get_provider_profile()`` 返回注册单例，就地改 dict 是进程级效果，
    多 profile 共用进程时自定义网点的目录会永久污染别人的能力表。
    """
    if (base_url or BASE_URL).rstrip("/") != BASE_URL.rstrip("/"):
        return
    profile = globals().get("opendesign")
    caps = getattr(profile, "model_capabilities", None)
    if not isinstance(caps, dict):
        return
    for model_id, entry in catalog.items():
        if not isinstance(entry, dict):
            continue
        if model_id in caps and model_id not in _REFRESHED_IDS:
            # 静态表（人工校准）与别的来源一律不动；只有「我们自己补的」允许更新
            continue
        patch: Dict[str, Any] = {"supports_tools": True, "supports_reasoning": True}
        window = _reported_context(entry.get("context"))
        if window:
            patch["context_window"] = window
        patch["supports_vision"] = bool(entry.get("vision"))
        caps[model_id] = patch
        _REFRESHED_IDS.add(model_id)


def _clamp_effort(effort: str, family: str) -> str | None:
    """把 Hermes 的 effort 折到该族允许的取值；None = 不发该字段。"""
    supported = _EFFORTS.get(family, EFFORT_FULL8)
    if family == FAMILY_GLM:
        return _GLM_MAP.get(effort, "high" if effort not in _CANONICAL_ORDER else None)
    if effort in supported:
        return effort
    if effort == "none":
        # 该族没有 none（minimax）：不发，绝不 clamp 成 minimal。
        return None
    if effort == "ultra" and "max" in supported:
        return "max"
    # 就近向下取，再不行取族内最低的非 none 档。
    idx = _CANONICAL_ORDER.index(effort) if effort in _CANONICAL_ORDER else len(_CANONICAL_ORDER) - 1
    for level in reversed(_CANONICAL_ORDER[:idx]):
        if level in supported and level != "none":
            return level
    for level in supported:
        if level != "none":
            return level
    return None


def _capabilities() -> Dict[str, Dict[str, Any]]:
    caps: Dict[str, Dict[str, Any]] = {}
    for model_id, (window, _output, vision, _family, family_name) in MODELS.items():
        caps[model_id] = {
            "context_window": _reported_context(window),
            "supports_vision": vision,
            "supports_tools": True,
            "supports_reasoning": True,
            "model_family": family_name,
        }
    return caps


def _setup_efforts(model: str) -> Tuple[str, ...]:
    """``hermes model`` 设置页的档位与运行时词表保持一致（callable field）。

    未登记的模型返回 ``()``（= 无思考控制，见 ``ProviderProfile.setup_reasoning_efforts`` 契约）：
    运行时对未知模型不发 effort，UI 就不该给出网关可能 400 的档位。
    """
    entry = MODELS.get((model or "").strip().lower())
    return _EFFORTS.get(entry[3], EFFORT_FULL8) if entry else ()


class OpenDesignProfile(ProviderProfile):
    """OpenDesign Cloud —— chat completions 主路径，按模型声明预算与思考词表。"""

    def _family_for(self, model: str | None) -> str | None:
        """effort 族；未登记的模型返回 None（= 不猜档位）。"""
        entry = MODELS.get((model or "").strip().lower())
        return entry[3] if entry else None

    def fetch_models(
        self, *, api_key: str | None = None, base_url: str | None = None, timeout: float = 8.0
    ) -> list[str] | None:
        """实时目录（同一份也喂 ``live_context_length`` / ``get_max_tokens``），过滤生图/视频模型。"""
        catalog = cached_catalog(api_key or "", base_url, timeout=timeout)
        if catalog is None:
            ids = super().fetch_models(api_key=api_key, base_url=base_url, timeout=timeout)
            return None if ids is None else [i for i in ids if not str(i).strip().lower().startswith(MEDIA_PREFIXES)]
        ids = [
            model_id
            for model_id, entry in catalog.items()
            if entry.get("enabled", True) and not model_id.strip().lower().startswith(MEDIA_PREFIXES)
        ]
        defaults = [i for i in ids if catalog[i].get("default")]
        return defaults + [i for i in ids if i not in defaults]

    def live_context_length(self, model: str, *, api_key: str = "", base_url: str = "") -> Optional[int]:
        """``metadata.context_limit``（小窗减去输出预留）；目录不可用（无凭据/抓取失败）时返回 None，
        交给 Hermes 后续步骤（models.dev / 硬编码默认）兜底 —— 静态表只被 ``get_model_context_length()`` 使用。"""
        catalog = cached_catalog(api_key, base_url) or {}
        entry = catalog.get((model or "").strip()) or catalog.get((model or "").strip().lower())
        return _reported_context(entry["context"]) if entry else None

    def get_model_context_length(self, model: str | None) -> int | None:
        """Provider-qualified bound —— `model_metadata.get_model_context_length()` 的 **step 0d**：
        在持久缓存、custom-endpoint 探测、models.dev 之前生效（`agent/model_metadata.py:2258-2264`）。
        `hostnames` 已把 amr-link 登记为已知 provider，不会走 `_resolve_custom_endpoint_context_length`；
        而 step 5 的 `live_context_length` 依赖凭据与缓存（无 key 且未抓过目录时返回 None），持久缓存 /
        models.dev 也拿不到 `metadata.context_limit` —— step 0d 是唯一不依赖凭据与网络的来源。
        纯函数（只读进程缓存/静态表，无 I/O）。
        """
        model_id = (model or "").strip()
        # 只读「最近一次成功抓取」的目录：本函数拿不到凭据，遍历 _CATALOG_CACHE 会把别的 key /
        # 别的 base_url 的窗口值串过来。
        entry = _PREFERRED_CATALOG.get(model_id) or _PREFERRED_CATALOG.get(model_id.lower())
        if entry and entry.get("context"):
            return _reported_context(entry["context"])
        entry = MODELS.get(model_id.lower())
        return _reported_context(entry[0]) if entry else None

    def max_tokens_param(self, *, base_url: str, model: str = "") -> str | None:
        """``gpt-5*`` id 会被 Hermes 换成 max_completion_tokens；网关未探过该字段，钉死 max_tokens。"""
        return "max_tokens"

    def supported_reasoning_efforts(self, model: str | None) -> Tuple[str, ...] | None:
        """三态契约（`providers/base.py`）：tuple = 可 clamp 的词表；``()`` = 该模型完全不接受
        reasoning 字段；``None`` = 未声明、传输层保留默认词表。未知模型必须给 ``()``（运行时确实
        一个字段都不发），给 ``None`` 会让将来的 Responses 面把默认词表发出去。
        """
        family = self._family_for(model)
        return _EFFORTS.get(family) if family else ()

    def build_api_kwargs_extras(self, *, reasoning_config: dict | None = None, model: str | None = None, **context: Any):
        """顶层 ``reasoning_effort``（chat 面唯一生效的思考开关）。

        规则：无 config → 不发；**未登记的模型 → 不发**（不猜档位；发错值会 400，不发只是没有
        thinking，参照 opencode-go / commandcode 对未知模型 no-op）；``enabled is False`` 或
        ``effort == "none"`` → 该族有 ``none`` 就原样发、没有就不发（绝不 clamp 成更弱的档）；
        其余按族 clamp。
        """
        if not isinstance(reasoning_config, dict):
            return {}, {}
        family = self._family_for(model)
        supported = _EFFORTS.get(family) if family else None
        if not supported:
            return {}, {}
        effort = str(reasoning_config.get("effort") or "medium").strip().lower()
        if reasoning_config.get("enabled") is False or effort == "none":
            return {}, ({"reasoning_effort": "none"} if "none" in supported else {})
        clamped = _clamp_effort(effort, family or FAMILY_FULL8)
        return {}, ({"reasoning_effort": clamped} if clamped else {})


opendesign = OpenDesignProfile(
    name="opendesign",
    aliases=("open-design", "open_design"),
    display_name="OpenDesign Cloud",
    description=DESCRIPTION,
    signup_url="https://open-design.ai/cloud/api-keys",
    env_vars=("OPENDESIGN_API_KEY", "OPENDESIGN_BASE_URL"),
    base_url=BASE_URL,
    models_url=BASE_URL + "/models",
    hostnames=("amr-link.open-design.ai",),
    auth_type="api_key",
    api_mode="chat_completions",
    supports_vision=True,
    supports_health_check=True,
    fallback_models=FALLBACK_MODELS,
    default_aux_model="deepseek-v4.1-flash",
    default_max_tokens=None,
    model_capabilities=_capabilities(),
    setup_reasoning_efforts=_setup_efforts,
)

register_provider(opendesign)
