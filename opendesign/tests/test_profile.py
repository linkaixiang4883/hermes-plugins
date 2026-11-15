#!/usr/bin/env python3
"""Offline tests for the opendesign provider plugin.

Run with the Hermes venv python:
    <HERMES_HOME>/hermes-agent/venv/Scripts/python.exe tests/test_profile.py

No API key, no network. Every assertion prints ``FAILED: <case>`` and exits 1 on failure.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
INIT = PLUGIN_DIR / "__init__.py"


def hermes_agent_dir() -> Path:
    env = os.environ.get("HERMES_AGENT_DIR", "").strip()
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "hermes" / "hermes-agent"
    return Path.home() / ".hermes" / "hermes-agent"


def load_plugin():
    root = hermes_agent_dir()
    if not (root / "hermes_bootstrap.py").is_file():
        raise SystemExit(f"SKIP: Hermes install not found at {root}")
    sys.path.insert(0, str(root))
    import hermes_bootstrap  # noqa: F401  (must be first)

    spec = importlib.util.spec_from_file_location("_opendesign_plugin_tests", INIT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    from providers import get_provider_profile

    # 用本文件定义的实例做行为断言：$HERMES_HOME 里可能还挂着一份旧的安装副本，
    # last-writer-wins 会让 get_provider_profile() 返回那一个（测试会测到旧代码）。
    profile = getattr(mod, "opendesign", None)
    if profile is None or get_provider_profile("opendesign") is None:
        raise SystemExit("FAILED: registration")
    return mod, profile


MOD, PROFILE = load_plugin()

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def registration_identity():
    assert PROFILE.name == "opendesign"
    assert PROFILE.base_url == "https://amr-link.open-design.ai/v1"
    assert PROFILE.env_vars == ("OPENDESIGN_API_KEY", "OPENDESIGN_BASE_URL")
    assert PROFILE.auth_type == "api_key"
    assert PROFILE.api_mode == "chat_completions"
    assert PROFILE.display_name == "OpenDesign Cloud"
    from providers import get_provider_profile

    alias_profile = get_provider_profile("open-design")
    assert alias_profile is not None and alias_profile.name == "opendesign"
    assert get_provider_profile("open_design") is not None


@case
def fallback_and_aux():
    assert PROFILE.fallback_models == ("deepseek-v4.1-flash",)
    assert PROFILE.default_aux_model == "deepseek-v4.1-flash"
    assert PROFILE.default_max_tokens is None


@case
def capabilities_table():
    caps = PROFILE.model_capabilities
    assert len(caps) == 14, len(caps)
    assert set(MOD.MODELS) == set(caps)
    for model_id, entry in caps.items():
        ctx = entry["context_window"]
        assert isinstance(ctx, int) and 8_000 <= ctx <= 2_000_000, (model_id, ctx)
        assert entry["supports_tools"] is True
        assert entry["supports_reasoning"] is True
        assert isinstance(entry["supports_vision"], bool)
    assert caps["kimi-k2.7-code"]["context_window"] == 262_000 - 65_536
    assert caps["deepseek-v4.1-flash"]["context_window"] == 1_048_000
    assert caps["gpt-6-luna"]["context_window"] == 1_050_000
    assert caps["deepseek-v4-pro"]["supports_vision"] is False
    assert caps["hy4-preview"]["supports_vision"] is False
    assert caps["deepseek-v4.1-flash-eco"]["supports_vision"] is False
    assert caps["deepseek-v4-flash"]["supports_vision"] is False
    for fallback_id in PROFILE.fallback_models:
        assert fallback_id in caps


@case
def max_tokens_not_sent():
    """不发送 max_tokens（get_max_tokens 未覆盖 → 基类返回 default_max_tokens=None）。"""
    MOD._CATALOG_CACHE.clear()
    for model in ("deepseek-v4.1-flash", "glm-5.3-flash", "kimi-k2.7-code", "hy4-preview",
                  "minimax-m3.1-flash", "not-in-catalog"):
        assert PROFILE.get_max_tokens(model) is None, model
    assert PROFILE.default_max_tokens is None
    assert PROFILE.max_tokens_param(base_url=PROFILE.base_url, model="gpt-6-luna") == "max_tokens"


@case
def effort_vocabularies():
    full = PROFILE.supported_reasoning_efforts("deepseek-v4.1-flash")
    glm = PROFILE.supported_reasoning_efforts("glm-5.3-flash")
    glm_x = PROFILE.supported_reasoning_efforts("glm-5.3-flashx")
    mini = PROFILE.supported_reasoning_efforts("minimax-m3.1-flash")
    eco = PROFILE.supported_reasoning_efforts("deepseek-v4.1-flash-eco")
    unknown = PROFILE.supported_reasoning_efforts("unknown-model")
    for value in (full, glm, glm_x, mini, eco):
        assert value is not None
    assert full == MOD.EFFORT_FULL8
    assert glm == ("low", "high", "max") and glm_x == ("low", "high", "max")
    assert mini is not None and "none" not in mini
    assert eco is not None and "ultra" not in eco
    # 0.3.x：未登记的模型给 ()（= 一个字段都不发）；None 是「未声明、传输层保留默认词表」，不对
    assert unknown == ()
    setup = PROFILE.setup_reasoning_efforts
    assert setup is not None and setup("glm-5.3-flash") == ("low", "high", "max")


@case
def reasoning_extras_table():
    def extras(model, cfg):
        return PROFILE.build_api_kwargs_extras(reasoning_config=cfg, model=model)

    assert extras("deepseek-v4.1-flash", None) == ({}, {})
    assert extras("deepseek-v4.1-flash", {"effort": "high"}) == ({}, {"reasoning_effort": "high"})
    assert extras("deepseek-v4.1-flash", {"effort": "ultra"}) == ({}, {"reasoning_effort": "ultra"})
    assert extras("deepseek-v4.1-flash", {"enabled": False}) == ({}, {"reasoning_effort": "none"})
    assert extras("minimax-m3.1-flash", {"enabled": False}) == ({}, {})
    assert extras("minimax-m3.1-flash", {"effort": "none"}) == ({}, {})
    assert extras("glm-5.3-flash", {"effort": "medium"}) == ({}, {"reasoning_effort": "high"})
    assert extras("glm-5.3-flash", {"effort": "minimal"}) == ({}, {"reasoning_effort": "low"})
    assert extras("glm-5.3-flash", {"effort": "xhigh"}) == ({}, {"reasoning_effort": "max"})
    assert extras("glm-5.3-flash", {"enabled": False}) == ({}, {})
    assert extras("deepseek-v4.1-flash-eco", {"effort": "ultra"}) == ({}, {"reasoning_effort": "max"})


@case
def provider_context_bound():
    """get_model_context_length 是 step 0d：必须在 custom-endpoint 探测之前给出元数据窗口。"""
    MOD._CATALOG_CACHE.clear()
    saved = MOD._PREFERRED_CATALOG
    setattr(MOD, "_PREFERRED_CATALOG", {})
    try:
        assert PROFILE.get_model_context_length("deepseek-v4.1-flash") == 1_048_000
        assert PROFILE.get_model_context_length("kimi-k2.7-code") == 262_000 - 65_536
        assert PROFILE.get_model_context_length("not-in-catalog") is None
        # 目录优先（0.3.0 起只认 _PREFERRED_CATALOG）
        setattr(MOD, "_PREFERRED_CATALOG",
                {"deepseek-v4.1-flash": {"context": 900_000, "output": 128_000,
                                         "vision": True, "enabled": True, "default": True}})
        assert PROFILE.get_model_context_length("deepseek-v4.1-flash") == 900_000
        # 缓存里有值但没有「最近一次抓取」记录 → 不采用（防跨凭据串味）
        setattr(MOD, "_PREFERRED_CATALOG", {})
        MOD._CATALOG_CACHE[("x", "y")] = (0.0, {"deepseek-v4.1-flash": {"context": 777_000}})
        assert PROFILE.get_model_context_length("deepseek-v4.1-flash") == 1_048_000
        # 纯函数纪律：fetch / cached_catalog 抛异常也不影响声明值（这条路径不允许有 I/O）
        original_fetch = MOD.fetch_catalog
        original_cached = MOD.cached_catalog
        def _boom(*args, **kwargs):
            raise RuntimeError("no network in get_model_context_length")
        setattr(MOD, "fetch_catalog", _boom)
        setattr(MOD, "cached_catalog", _boom)
        try:
            assert PROFILE.get_model_context_length("deepseek-v4.1-flash") == 1_048_000
        finally:
            setattr(MOD, "fetch_catalog", original_fetch)
            setattr(MOD, "cached_catalog", original_cached)
        # 极小窗不能上报成 1 token（<65,536 时按 75%）
        assert MOD._reported_context(32_000) == 24_000
        assert MOD._reported_context(262_000) == 262_000 - 65_536
    finally:
        MOD._CATALOG_CACHE.clear()
        setattr(MOD, "_PREFERRED_CATALOG", saved)


@case
def fetch_models_filters_media():
    catalog = {
        "deepseek-v4.1-flash": {"context": 1_048_000, "output": 128_000, "vision": True, "enabled": True, "default": True},
        "glm-5.3-flash": {"context": 1_048_000, "output": 32_000, "vision": True, "enabled": True, "default": False},
        "gpt-image-2": {"context": None, "output": None, "vision": False, "enabled": True, "default": False},
        "seedream-5.0": {"context": None, "output": None, "vision": False, "enabled": True, "default": False},
        "disabled-chat": {"context": 1000, "output": None, "vision": False, "enabled": False, "default": False},
    }
    original = MOD.cached_catalog
    setattr(MOD, "cached_catalog", lambda api_key="", base_url=None, **kwargs: catalog)
    try:
        ids = PROFILE.fetch_models(api_key="x")
        assert ids == ["deepseek-v4.1-flash", "glm-5.3-flash"], ids
        assert PROFILE.live_context_length("kimi-k2.7-code", api_key="x") is None
        assert PROFILE.live_context_length("glm-5.3-flash", api_key="x") == 1_048_000
        setattr(MOD, "cached_catalog", lambda api_key="", base_url=None, **kwargs: None)
        from providers.base import ProviderProfile

        base_original = ProviderProfile.fetch_models
        ProviderProfile.fetch_models = lambda self, **kwargs: None
        try:
            assert PROFILE.fetch_models(api_key="x") is None
        finally:
            ProviderProfile.fetch_models = base_original
    finally:
        setattr(MOD, "cached_catalog", original)


@case
def zero_private_imports():
    source = INIT.read_text(encoding="utf-8")
    banned = (
        "agent.reasoning_effort",
        "agent.models_dev",
        "agent.model_metadata",
        "hermes_cli.urllib_security",
        "hermes_cli.providers",
        "hermes_cli.models",
    )
    for token in banned:
        assert token not in source, token


@case
def catalog_refresh_adds_unknown_model():
    """目录出现静态表没有的模型 → 补进 model_capabilities（视觉判定按精确 id 查这张表）。"""
    payload = {"data": [{"id": "new-model-x", "metadata": {"context_limit": 600000},
                         "architecture": {"input_modalities": ["text", "image"]}}]}
    try:
        MOD._refresh_capabilities(MOD.parse_catalog(payload))
        caps = PROFILE.model_capabilities["new-model-x"]
        assert caps["context_window"] == 600_000, caps
        assert caps["supports_vision"] is True, caps
        assert caps["supports_tools"] is True and caps["supports_reasoning"] is True, caps
        # 自定义网点不补：注册单例是进程级，写进去会污染别的 profile
        MOD._refresh_capabilities(MOD.parse_catalog(
            {"data": [{"id": "new-model-y", "metadata": {"context_limit": 600000}}]}),
            base_url="https://gw-other.test/v1")
        assert "new-model-y" not in PROFILE.model_capabilities
    finally:
        PROFILE.model_capabilities.pop("new-model-x", None)
        PROFILE.model_capabilities.pop("new-model-y", None)
        MOD._REFRESHED_IDS.discard("new-model-x")
        MOD._REFRESHED_IDS.discard("new-model-y")


@case
def catalog_refresh_never_overwrites_static():
    """静态表是人工校准过的（小窗预留、模态修正），目录只允许填空位。"""
    saved = dict(PROFILE.model_capabilities["deepseek-v4.1-flash"])
    try:
        MOD._refresh_capabilities(MOD.parse_catalog(
            {"data": [{"id": "deepseek-v4.1-flash", "metadata": {"context_limit": 1234},
                       "architecture": {"input_modalities": ["text"]}}]}))
        caps = PROFILE.model_capabilities["deepseek-v4.1-flash"]
        assert caps["context_window"] == 1_048_000, caps
        assert caps["supports_vision"] is True, caps
    finally:
        PROFILE.model_capabilities["deepseek-v4.1-flash"] = saved


@case
def context_length_uses_preferred_catalog_only():
    """step 0d 拿不到凭据 → 只认最近一次成功目录，不跨凭据串味。"""
    payloads = iter([
        {"data": [{"id": "m", "metadata": {"context_limit": 900000}}]},
        {"data": [{"id": "m", "metadata": {"context_limit": 600000}}]},
    ])
    original_fetch = MOD.fetch_catalog
    saved_preferred = MOD._PREFERRED_CATALOG
    try:
        setattr(MOD, "fetch_catalog", lambda api_key="", base_url=None, timeout=8.0: MOD.parse_catalog(next(payloads)))
        MOD._CATALOG_CACHE.clear()
        MOD.cached_catalog("key-a", "https://gw-a.test/v1")
        MOD.cached_catalog("key-b", "https://gw-b.test/v1")
        assert PROFILE.get_model_context_length("m") == 600_000, PROFILE.get_model_context_length("m")
    finally:
        setattr(MOD, "fetch_catalog", original_fetch)
        MOD._CATALOG_CACHE.clear()
        setattr(MOD, "_PREFERRED_CATALOG", saved_preferred)
        PROFILE.model_capabilities.pop("m", None)


@case
def unknown_model_emits_no_effort():
    """未登记的模型不猜档位：发错值会 400，不发只是没有 thinking。"""
    assert PROFILE.build_api_kwargs_extras(reasoning_config={"enabled": True, "effort": "high"},
                                           model="brand-new-1") == ({}, {})
    assert PROFILE.build_api_kwargs_extras(reasoning_config={"effort": "none"},
                                           model="brand-new-1") == ({}, {})
    assert PROFILE.build_api_kwargs_extras(reasoning_config={"effort": "ultra"},
                                           model=None) == ({}, {})


@case
def unknown_model_declares_no_efforts():
    assert PROFILE.supported_reasoning_efforts("brand-new-1") == ()
    assert PROFILE.setup_reasoning_efforts("brand-new-1") == ()
    # 已知模型不受影响
    assert PROFILE.supported_reasoning_efforts("glm-5.3-flash") == ("low", "high", "max")
    assert PROFILE.setup_reasoning_efforts("glm-5.3-flash") == ("low", "high", "max")


@case
def declares_hostnames_and_models_url():
    """让 host→provider 反查认 amr-link，并让 doctor 探活用真实 /models 地址。"""
    assert PROFILE.hostnames == ("amr-link.open-design.ai",), PROFILE.hostnames
    assert PROFILE.models_url == MOD.BASE_URL + "/models", PROFILE.models_url
    assert PROFILE.supports_health_check is True
    # 故意不覆盖错误分类：429/额度交回 Hermes 内置（rate_limit → 重试 → 轮换 → fallback）
    assert PROFILE.classify_api_error is None


@case
def catalog_refresh_is_wired_through_cached_catalog():
    """G1 的**生产接线**：cached_catalog 成功抓取后必须自动补能力（把调用删掉就该红）。"""
    original_fetch = MOD.fetch_catalog
    original_cache = MOD._CATALOG_CACHE
    try:
        setattr(MOD, "_CATALOG_CACHE", {})
        setattr(MOD, "fetch_catalog", lambda api_key="", base_url=None, timeout=8.0: MOD.parse_catalog(
            {"data": [{"id": "wired-model", "metadata": {"context_limit": 600000},
                       "architecture": {"input_modalities": ["text", "image"]}}]}))
        MOD.cached_catalog("k-wired")
        caps = PROFILE.model_capabilities.get("wired-model")
        assert caps is not None, "cached_catalog 没有触发 _refresh_capabilities"
        assert caps["context_window"] == 600_000 and caps["supports_vision"] is True, caps
        # 自定义网点不走补全（注册单例，写进去会污染别的 profile）
        setattr(MOD, "fetch_catalog", lambda api_key="", base_url=None, timeout=8.0: MOD.parse_catalog(
            {"data": [{"id": "wired-proxy", "metadata": {"context_limit": 600000}}]}))
        MOD.cached_catalog("k2", "https://proxy.test/v1")
        assert "wired-proxy" not in PROFILE.model_capabilities
    finally:
        setattr(MOD, "fetch_catalog", original_fetch)
        setattr(MOD, "_CATALOG_CACHE", original_cache)
        MOD._CATALOG_CACHE.clear()
        for mid in ("wired-model", "wired-proxy"):
            PROFILE.model_capabilities.pop(mid, None)
            MOD._REFRESHED_IDS.discard(mid)


def main() -> int:
    failed = []
    for fn in CASES:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed.append(fn.__name__)
            print(f"FAILED: {fn.__name__} -> {type(exc).__name__}: {exc}")
    if failed:
        print(f"FAILED: {len(failed)} case(s): {', '.join(failed)}")
        return 1
    print(f"OK: {len(CASES)} cases, FAILED: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
