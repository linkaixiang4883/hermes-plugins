#!/usr/bin/env python3
"""Metadata tests: the static fallback table must equal the real /v1/models snapshot.

Run: <venv python> tests/test_metadata.py   (offline; fixture = 2026-11-15 real capture)
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
INIT = PLUGIN_DIR / "__init__.py"
FIXTURE = PLUGIN_DIR / "tests" / "fixtures" / "models.json"


def hermes_agent_dir() -> Path:
    if os.environ.get("HERMES_AGENT_DIR", "").strip():
        return Path(os.environ["HERMES_AGENT_DIR"].strip())
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "hermes" / "hermes-agent"
    return Path.home() / ".hermes" / "hermes-agent"


def load():
    root = hermes_agent_dir()
    if not (root / "hermes_bootstrap.py").is_file():
        raise SystemExit(f"SKIP: Hermes install not found at {root}")
    sys.path.insert(0, str(root))
    import hermes_bootstrap  # noqa: F401

    spec = importlib.util.spec_from_file_location("_opendesign_metadata_tests", INIT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


MOD = load()
PAYLOAD = json.loads(FIXTURE.read_text(encoding="utf-8"))
CATALOG = MOD.parse_catalog(PAYLOAD)

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def fixture_shape():
    assert len(PAYLOAD["data"]) == 14
    first = PAYLOAD["data"][0]
    assert {"id", "architecture", "metadata"} <= set(first)


@case
def parse_catalog_keys():
    assert len(CATALOG) == 14
    assert set(CATALOG["deepseek-v4.1-flash"]) == {"context", "output", "vision", "enabled", "default"}
    assert CATALOG["deepseek-v4.1-flash"] == {
        "context": 1_048_000,
        "output": 128_000,
        "vision": True,
        "enabled": True,
        "default": True,
    }


@case
def static_table_equals_fixture():
    """离线兜底表不得与真目录漂移：ctx / output / vision 三项逐模型对齐。"""
    for model_id, entry in CATALOG.items():
        assert model_id in MOD.MODELS, f"missing static entry: {model_id}"
        window, output, vision, _family, _name = MOD.MODELS[model_id]
        assert window == entry["context"], (model_id, window, entry["context"])
        assert output == entry["output"], (model_id, output, entry["output"])
        assert vision == entry["vision"], (model_id, vision, entry["vision"])
    assert set(MOD.MODELS) == set(CATALOG), set(MOD.MODELS) ^ set(CATALOG)


@case
def reported_context_rule():
    assert MOD._reported_context(1_048_000) == 1_048_000
    assert MOD._reported_context(512_000) == 512_000
    assert MOD._reported_context(262_000) == 262_000 - MOD.SMALL_WINDOW_RESERVE
    assert MOD._reported_context(None) is None


@case
def vision_flags_are_metadata_driven():
    text_only = {"deepseek-v4-pro", "hy4-preview", "deepseek-v4-flash", "deepseek-v4.1-flash-eco"}
    for model_id in text_only:
        assert CATALOG[model_id]["vision"] is False, model_id
    assert CATALOG["deepseek-v4.1-flash"]["vision"] is True
    assert CATALOG["deepseek-v4-flash-vision-exp"]["vision"] is True


@case
def output_budget_is_observed_not_sent():
    """output_budget 只解析出来观察/对账，不作为请求的 max_tokens（不发 = 交给服务端）。"""
    assert CATALOG["glm-5.3-flash"]["output"] == 32_000
    assert CATALOG["deepseek-v4.1-flash"]["output"] == 128_000
    assert CATALOG["minimax-m3.1-flash"]["output"] is None
    for model in ("glm-5.3-flash", "deepseek-v4.1-flash", "minimax-m3.1-flash"):
        assert MOD.opendesign.get_max_tokens(model) is None, model


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
