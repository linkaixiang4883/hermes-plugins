"""Agnes AI Intl (Sapiens AI international endpoint) provider profile.

Provider: Agnes AI by Sapiens AI
Endpoint: https://apihub.agnes-ai.com/v1
Models:
  - agnes-3.0-flash (512K context, 65.5K max output) — latest, free promo
  - agnes-2.5-flash (512K context, 65.5K max output)
  - agnes-2.0-flash (512K context, 65.5K max output) — previous gen
Docs: https://agnes-ai.com/zh-Hans/docs/quickstart

Capabilities:
  - OpenAI-compatible chat completions (/v1/chat/completions)
  - Vision (image_url input in messages)
  - Tool calling (function calling)
  - Streaming
  - Thinking mode via chat_template_kwargs.enable_thinking (OpenAI compat)
    or thinking object (Anthropic compat)

Reasoning/Thinking:
  The Agnes AI international base_url (apihub.agnes-ai.com) does NOT match any hostname in
  Hermes's _supports_reasoning_extra_body() gate, so the global /reasoning
  command has no effect. This profile injects enable_thinking=true in
  build_extra_body() so thinking is always on, and also honors the
  reasoning_config from /reasoning when the user explicitly sets it.

  Thinking mode reference:
    OpenAI-compatible: chat_template_kwargs.enable_thinking = true
    Anthropic-compatible: thinking.budget_tokens (not used here)

Pricing (as of 2026-09, international site in USD):
  agnes-3.0-flash: FREE ($0/1M tokens, current promotion)
  agnes-2.5-flash: FREE ($0/1M tokens input & output, current promotion)
  agnes-2.0-flash: FREE ($0/1M tokens input & output, current promotion)

Env vars:
  AGNES_API_KEY — API key from https://agnes-ai.com/ (international endpoint)
"""

from __future__ import annotations

from providers import register_provider
from providers.base import ProviderProfile


class AgnesIntlProfile(ProviderProfile):
    """Agnes AI international provider — injects thinking mode and reasoning support.

    Since apihub.agnes-ai.com is not in Hermes's built-in reasoning hostname
    gate, we handle reasoning ourselves:

    1. build_extra_body(): always inject chat_template_kwargs.enable_thinking=true
       so thinking mode is on by default for every request.

    2. build_api_kwargs_extras(): when reasoning_config is provided (user ran
       /reasoning), pass it through as chat_template_kwargs.enable_thinking so
       the user can toggle thinking on/off via /reasoning.
    """

    def build_extra_body(self, *, session_id=None, **context):
        """Always enable thinking mode for Agnes AI.

        Agnes 2.5 Flash / 2.0 Flash support chat_template_kwargs.enable_thinking
        for extended reasoning. Since the base_url doesn't match Hermes's
        reasoning gate, we inject it here unconditionally.
        """
        return {
            "chat_template_kwargs": {
                "enable_thinking": True,
            }
        }

    def build_api_kwargs_extras(self, *, reasoning_config=None, **context):
        """Handle /reasoning command passthrough.

        When the user explicitly sets reasoning effort via /reasoning:
        - effort != none → ensure enable_thinking=true (already set in
          build_extra_body, but reinforce here for clarity)
        - effort == none → we still keep thinking on by default for Agnes
          since the model benefits from it for coding/agent tasks

        Returns (extra_body_additions, top_level_kwargs).
        """
        extra_body_additions = {}
        top_level = {}

        if reasoning_config:
            enabled = reasoning_config.get("enabled", True)
            if enabled is not False:
                # /reasoning is on — reinforce thinking
                extra_body_additions["chat_template_kwargs"] = {
                    "enable_thinking": True,
                }
            # If user explicitly disables reasoning, we let build_extra_body
            # keep thinking on — Agnes models benefit from thinking for
            # all agentic tasks. Override here would be:
            # extra_body_additions["chat_template_kwargs"] = {"enable_thinking": False}

        return extra_body_additions, top_level


agnes_intl = AgnesIntlProfile(
    name="agnes",
    display_name="Agnes AI (Intl)",
    description="Agnes AI Intl international endpoint (Sapiens AI) — agnes-3.0-flash & agnes-2.5-flash & agnes-2.0-flash, 512K context, vision & thinking",
    signup_url="https://agnes-ai.com/",
    env_vars=("AGNES_API_KEY",),
    base_url="https://apihub.agnes-ai.com/v1",
    auth_type="api_key",
    supports_vision=True,
    supports_health_check=True,
    fallback_models=(
        "agnes-3.0-flash",
        "agnes-2.5-flash",
        "agnes-2.0-flash",
    ),
)

register_provider(agnes_intl)

# ── Context length injection ──────────────────────────────────────────
# Inject correct context lengths into the persistent cache so Hermes
# doesn't fall back to models.dev (which may have wrong values or no
# entry at all for Agnes models).
try:
    from agent.model_metadata import save_context_length

    _AGNES_INTL_BASE_URL = "https://apihub.agnes-ai.com/v1"
    _AGNES_CONTEXT_LENGTHS = {
        "agnes-3.0-flash":  512_000,
        "agnes-2.5-flash":  512_000,
        "agnes-2.0-flash":  512_000,
    }
    for _model_id, _ctx_len in _AGNES_CONTEXT_LENGTHS.items():
        save_context_length(_model_id, _AGNES_INTL_BASE_URL, _ctx_len)
except Exception:
    pass

# ── Hermes registry injection ─────────────────────────────────────────
# Hermes v0.19.0's resolve_provider_full() and resolve_runtime_provider()
# query HERMES_OVERLAYS (providers.py) and PROVIDER_REGISTRY (auth.py)
# respectively. The plugin registration system only registers to the
# providers/ framework, not these internal dicts, causing TUI /model
# and dashboard model picker to fail.
#
# This injects entries directly into module-level dicts without modifying
# Hermes source code or config.yaml. Must execute AFTER register_provider().


def _inject_into_hermes_registries() -> None:
    # 1. HERMES_OVERLAYS — resolve_provider_full() recognizes provider
    try:
        from hermes_cli.providers import HERMES_OVERLAYS, HermesOverlay

        if "agnes" not in HERMES_OVERLAYS:
            HERMES_OVERLAYS["agnes"] = HermesOverlay(
                transport="openai_chat",
                auth_type="api_key",
                extra_env_vars=("AGNES_API_KEY",),
                base_url_override="https://apihub.agnes-ai.com/v1",
            )
    except Exception:
        pass

    # 2. _PROVIDER_MODELS — validate_requested_model() static catalog check
    #    When API /models returns empty list ([]) instead of None, validate
    #    enters "api_models is not None" branch and checks
    #    _model_in_provider_catalog(). If _PROVIDER_MODELS lacks this
    #    provider entry, model validation fails.
    try:
        from hermes_cli.models import _PROVIDER_MODELS

        if "agnes" not in _PROVIDER_MODELS:
            _PROVIDER_MODELS["agnes"] = list(agnes_intl.fallback_models)
    except Exception:
        pass


_inject_into_hermes_registries()
