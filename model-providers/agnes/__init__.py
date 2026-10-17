"""Agnes AI (Sapiens AI) provider profiles — 国际站 + 国内站，一个插件两个 provider。

形态照 Hermes 内置的 ``plugins/model-providers/opencode-zen``：一个文件 ``register_provider()``
两次，选择器里就是两个**并列条目**（Hermes 没有 variant / sub-provider 概念）。

    provider      base_url                          env var
    ------------  --------------------------------  -------------------
    ``agnes``     https://apihub.agnes-ai.com/v1     ``AGNES_API_KEY``
    ``agnes-cn``  https://api.agnes-ai.cn/v1         ``AGNES_CN_API_KEY``

两家除 base_url / key / 名称与别名外**完全一致**（同一套模型、同样的能力与参数），故共享一个基类。

Models（两家一致，2026-10-17 抓官方文档 + /v1/models 实测）:
  - ``agnes-3.0-flash``      512K ctx / 65,536 out — 免费促销中
  - ``agnes-2.5-flash``      512K ctx / 65.5K  out — 免费促销中
  - ``agnes-2.5-pro``          1M ctx / 65,536 out — reasoning，付费
  - ``agnes-2.5-pro-beta``   ctx 官方未文档化 — 付费预览
  - ``agnes-3.0-pro``        ctx 官方未文档化 — 即将上线
  - ``agnes-2.0-flash``      **已废弃**，文档明确「请勿继续作为兼容回退」

Capabilities:
  - OpenAI-compatible chat completions (/v1/chat/completions)
  - Vision（messages 里的 image_url 输入）、Tool calling、Streaming
  - Thinking 模式：``chat_template_kwargs.enable_thinking``（OpenAI 兼容）
    或 ``thinking.budget_tokens``（Anthropic 兼容）

Reasoning/Thinking 为什么要自己处理：
  两家的 base_url 都不在 Hermes 的 ``_supports_reasoning_extra_body()`` 主机名白名单里，
  所以全局 ``/reasoning`` 对它们本来无效。本 profile 在 ``build_extra_body()`` 里无条件注入
  ``enable_thinking=true``（Agnes 在编码/Agent 任务上默认开思考更稳），并在
  ``build_api_kwargs_extras()`` 里把 ``/reasoning`` 的开关也映射过去。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from providers import register_provider
from providers.base import ProviderProfile

# ── 两家共享的数据（一处维护，两个 provider 都用）─────────────────────
FALLBACK_MODELS: Tuple[str, ...] = (
    "agnes-3.0-flash",
    "agnes-2.5-flash",
    "agnes-2.5-pro",
    "agnes-2.5-pro-beta",
    "agnes-3.0-pro",
)

# 上下文窗口 → 同时喂给 model_capabilities（正式声明面）与 save_context_length（老缓存）
CONTEXT_LENGTHS: Dict[str, int] = {
    "agnes-3.0-flash": 512_000,
    "agnes-2.5-flash": 512_000,
    "agnes-2.5-pro": 1_000_000,
}


def _model_capabilities() -> Dict[str, Dict[str, Any]]:
    """每个 provider 各拿一份**独立的** dict（避免两个 profile 共享可变对象）。"""
    return {
        "agnes-3.0-flash": {"context_window": 512_000, "supports_vision": True, "supports_tools": True},
        "agnes-2.5-flash": {"context_window": 512_000, "supports_vision": True, "supports_tools": True},
        "agnes-2.5-pro": {
            "context_window": 1_000_000, "supports_vision": True, "supports_tools": True,
            "supports_reasoning": True,
        },
        # 以下两个上下文窗口官方未文档化 → 只声明能力，context 留空（= 未知，不猜）
        "agnes-2.5-pro-beta": {"supports_vision": True, "supports_tools": True, "supports_reasoning": True},
        "agnes-3.0-pro": {"supports_vision": True, "supports_tools": True, "supports_reasoning": True},
    }


class AgnesProfile(ProviderProfile):
    """Agnes AI（国际站 / 国内站共用）—— 注入 thinking 模式并接管 reasoning 开关。"""

    def build_extra_body(self, *, session_id=None, **context):
        """无条件开启 thinking：Agnes 的 base_url 不在 Hermes reasoning 白名单里。"""
        return {"chat_template_kwargs": {"enable_thinking": True}}

    def build_api_kwargs_extras(self, *, reasoning_config=None, **context):
        """把 ``/reasoning`` 的开关映射到 ``chat_template_kwargs.enable_thinking``。

        用户关掉 reasoning 时**仍然保留 thinking**（Agnes 在编码/Agent 任务上受益），
        这是刻意的：真要强制关闭，就把下面分支改成 enable_thinking=False。
        """
        extra_body_additions: Dict[str, Any] = {}
        top_level: Dict[str, Any] = {}
        if reasoning_config and reasoning_config.get("enabled", True) is not False:
            extra_body_additions["chat_template_kwargs"] = {"enable_thinking": True}
        return extra_body_additions, top_level


# ── 两个 provider 的差异全部集中在这两处 ───────────────────────────────
agnes_intl = AgnesProfile(
    name="agnes",
    display_name="Agnes AI (Intl)",
    description="Agnes AI Intl international endpoint (Sapiens AI) — agnes-3.0-flash / agnes-2.5-flash (512K ctx, 免费) + agnes-2.5-pro (1M ctx, reasoning)；vision & tools",
    signup_url="https://agnes-ai.com/",
    env_vars=("AGNES_API_KEY",),
    base_url="https://apihub.agnes-ai.com/v1",
    auth_type="api_key",
    supports_vision=True,
    supports_health_check=True,
    fallback_models=FALLBACK_MODELS,
    model_capabilities=_model_capabilities(),
)

agnes_cn = AgnesProfile(
    name="agnes-cn",
    # 历史别名：这个 provider 早先是独立插件 ``agnes-ai``，改名后保留别名以兼容旧配置
    aliases=("agnes-ai", "agnes_ai", "sapiens"),
    display_name="Agnes AI (CN)",
    description="Agnes AI CN domestic endpoint (Sapiens AI) — agnes-3.0-flash / agnes-2.5-flash (512K ctx, 免费) + agnes-2.5-pro (1M ctx, reasoning)；vision & tools",
    signup_url="https://platform.agnes-ai.cn/",
    env_vars=("AGNES_CN_API_KEY",),
    base_url="https://api.agnes-ai.cn/v1",
    auth_type="api_key",
    supports_vision=True,
    supports_health_check=True,
    fallback_models=FALLBACK_MODELS,
    model_capabilities=_model_capabilities(),
)

register_provider(agnes_intl)
register_provider(agnes_cn)

_PROFILES = (agnes_intl, agnes_cn)


# ── 老缓存注入（保底；正式声明面是上面的 model_capabilities）───────────
# 写进 model_metadata 的持久缓存，按 (model, base_url) 记；两家 base_url 不同，各写一遍。
try:
    from agent.model_metadata import save_context_length

    for _profile in _PROFILES:
        for _model_id, _ctx_len in CONTEXT_LENGTHS.items():
            save_context_length(_model_id, _profile.base_url, _ctx_len)
except Exception:
    pass


# ── 核心注册表补丁（技术债，待上游提供正式面后移除）────────────────────
# 背景：Hermes v0.19 的 resolve_provider_full() / validate_requested_model() 曾只读
# HERMES_OVERLAYS 与 _PROVIDER_MODELS 两个模块级 dict，plugin 注册系统不碰它们。
# 官方文档称 register_provider(ProviderProfile) 已自动接好这些集成点，但
# _PROVIDER_MODELS 仍被静态目录逻辑（hermes_cli/models.py）使用，故暂时两边都注入。
def _inject_into_hermes_registries() -> None:
    for profile in _PROFILES:
        # 1. HERMES_OVERLAYS — resolve_provider_full() 认得这个 provider
        try:
            from hermes_cli.providers import HERMES_OVERLAYS, HermesOverlay

            if profile.name not in HERMES_OVERLAYS:
                HERMES_OVERLAYS[profile.name] = HermesOverlay(
                    transport="openai_chat",
                    auth_type="api_key",
                    extra_env_vars=tuple(profile.env_vars),
                    base_url_override=profile.base_url,
                )
        except Exception:
            pass

        # 2. _PROVIDER_MODELS — 静态目录校验的兜底清单
        try:
            from hermes_cli.models import _PROVIDER_MODELS

            if profile.name not in _PROVIDER_MODELS:
                _PROVIDER_MODELS[profile.name] = list(profile.fallback_models)
        except Exception:
            pass


_inject_into_hermes_registries()
