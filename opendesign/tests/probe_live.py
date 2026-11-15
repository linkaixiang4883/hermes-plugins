#!/usr/bin/env python3
"""Live probes for the OpenDesign gateway (needs a runtime key).

Usage:
    <venv python> tests/probe_live.py [--case models|chat|reasoning|max_tokens|wires|errors|images|tool_image|all]

Key resolution: $OPENDESIGN_API_KEY, else ``$HERMES_HOME/.env`` (``OPENDESIGN_API_KEY=``).
No key -> prints ``SKIP(no key)`` and exits 0 (so CI/offline runs never fail).

Never prints the key: only ``key present: yes (len=N)``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://amr-link.open-design.ai/v1"
TIMEOUT = 30.0
# 账户约定：只允许用 DeepSeek V4.1 Flash（或 eco）做推理测试，其它模型一律不打。
ALLOWED_MODELS = ("deepseek-v4.1-flash", "deepseek-v4.1-flash-eco")
DEFAULT_MODEL = ALLOWED_MODELS[0]


def _read_dotenv_key() -> str:
    home = os.environ.get("HERMES_HOME", "").strip()
    if not home:
        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            home = str(Path(base) / "hermes")
        else:
            home = str(Path.home() / ".hermes")
    env_file = Path(home) / ".env"
    if not env_file.is_file():
        return ""
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("OPENDESIGN_API_KEY=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def api_key() -> str:
    return os.environ.get("OPENDESIGN_API_KEY", "").strip() or _read_dotenv_key()


def call(path: str, key: str, body: dict | None = None, *, headers: dict | None = None) -> tuple[int, dict | str]:
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except ValueError:
                return resp.status, raw[:2000]
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw[:2000]


def _chat_body(model: str, **extra) -> dict:
    body = {"model": model, "messages": [{"role": "user", "content": "Reply with: ok"}], "stream": False}
    body.update(extra)
    return body


def case_models(key: str) -> None:
    status, payload = call("/models", key)
    ids = [m.get("id") for m in payload.get("data", [])] if isinstance(payload, dict) else []
    fields = sorted({k for m in payload.get("data", []) if isinstance(m, dict) for k in m}) if isinstance(payload, dict) else []
    print(f"models: status={status} count={len(ids)} fields={fields}")
    print("ids:", ", ".join(str(i) for i in ids))
    for m in (payload.get("data", []) if isinstance(payload, dict) else []):
        meta = m.get("metadata") if isinstance(m, dict) else None
        if isinstance(meta, dict) and ("context_limit" in meta or "output_budget" in meta):
            print("meta:", json.dumps({"id": m.get("id"),
                                       "context_limit": meta.get("context_limit"),
                                       "output_budget": meta.get("output_budget")}, ensure_ascii=False))


def case_chat(key: str, model: str = DEFAULT_MODEL) -> None:
    status, payload = call("/chat/completions", key, _chat_body(model))
    if isinstance(payload, dict):
        choice = (payload.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        print(f"chat: status={status} model={payload.get('model')} finish={choice.get('finish_reason')} "
              f"usage={payload.get('usage')} reasoning_chars={len(str(msg.get('reasoning_content') or ''))}")
    else:
        print(f"chat: status={status} body={str(payload)[:200]}")


def case_reasoning(key: str) -> None:
    """只打允许的两个 DeepSeek 模型（账户约定）。"""
    for model in ALLOWED_MODELS:
        for label, extra in (
            ("none", {"reasoning_effort": "none"}),
            ("low", {"reasoning_effort": "low"}),
            ("high", {"reasoning_effort": "high"}),
            ("thinking-disabled", {"thinking": {"type": "disabled"}}),
        ):
            status, payload = call("/chat/completions", key, _chat_body(model, max_tokens=32, **extra))
            rt = ""
            if isinstance(payload, dict):
                usage = ((payload.get("choices") or [{}])[0].get("message") or {}).get("usage") or payload.get("usage") or {}
                rt = str(usage.get("reasoning_tokens", ""))
            print(f"reasoning: {model} {label} -> {status} reasoning_tokens={rt}")


def case_max_tokens(key: str) -> None:
    """验证「输入 + max_tokens ≤ 窗口」与 output_budget 不是硬上限（只用允许的模型）。"""
    for model, window in (("deepseek-v4.1-flash", 1_048_000), ("deepseek-v4.1-flash-eco", 1_048_000)):
        for cap in (4096, 65_536, 131_072):
            status, payload = call("/chat/completions", key, _chat_body(model, max_tokens=cap))
            err = payload.get("error", {}).get("code") if isinstance(payload, dict) else ""
            print(f"max_tokens: {model} cap={cap} window={window} -> {status} err={err}")


def case_wires(key: str) -> None:
    status, payload = call("/responses", key, {"model": "deepseek-v4.1-flash", "input": "Reply with: ok", "store": False})
    print(f"responses: status={status} keys={sorted(payload) if isinstance(payload, dict) else type(payload).__name__}")
    status, payload = call("/messages", key, {"model": "deepseek-v4.1-flash", "max_tokens": 16,
                                              "messages": [{"role": "user", "content": "Reply with: ok"}]},
                           headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    content = payload.get("content") if isinstance(payload, dict) else None
    print(f"messages: status={status} content_blocks={len(content) if isinstance(content, list) else 'n/a'} "
          f"empty={not content if isinstance(content, list) else 'n/a'}")
    status, payload = call("/messages", key, {"model": "deepseek-v4.1-flash", "max_tokens": 16,
                                              "messages": [{"role": "user", "content": "hi"}]},
                           headers={"x-api-key": key})  # deliberately missing anthropic-version
    print(f"messages(no version): status={status} err={(payload.get('error') or {}).get('type') if isinstance(payload, dict) else ''}")


def case_errors(key: str) -> None:
    status, payload = call("/chat/completions", key, _chat_body("no-such-model-xyz"))
    print(f"errors: bogus model -> {status} err={payload.get('error') if isinstance(payload, dict) else ''}")
    status, payload = call("/models", key + "-bad")
    print(f"errors: bad key -> {status} err={(payload.get('error') or {}).get('code') if isinstance(payload, dict) else ''}")


def case_images(key: str) -> None:
    """生图 id 不允许用于测试（账户约定）；只保留占位，不发送请求。"""
    print("images: SKIP(account allows chat tests on deepseek-v4.1-flash / eco only)")


def case_tool_image(key: str, model: str = DEFAULT_MODEL) -> None:
    """G6/F13：tool 消息里放 list 型 content（text + image_url）能否被接受。

    判定用作 ``supports_vision_tool_messages`` 的依据：
      200                       → 接受 list 型 tool content（保持默认 True）
      400/422 且 body 提到 tool/string/text is not set → 拒绝（应设 False）
     """
    assert model in ALLOWED_MODELS, f"account allows only {ALLOWED_MODELS}"
    png = ("data:image/png;base64,"
           "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")
    body = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Call the tool with the attached image."},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "look", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1",
             "content": [{"type": "text", "text": "image"},
                         {"type": "image_url", "image_url": {"url": png}}]},
        ],
        "tools": [{"type": "function", "function": {"name": "look", "parameters": {"type": "object", "properties": {}}}}],
        "stream": False,
    }
    status, payload = call("/chat/completions", key, body)
    text = json.dumps(payload, ensure_ascii=False)[:400] if isinstance(payload, (dict, list)) else str(payload)[:400]
    print(f"tool_image: status={status} accepts_list_tool_content={status == 200}")
    print(f"tool_image body: {text}")


CASES = {
    "models": case_models,
    "chat": case_chat,
    "reasoning": case_reasoning,
    "max_tokens": case_max_tokens,
    "wires": case_wires,
    "errors": case_errors,
    "images": case_images,
    "tool_image": case_tool_image,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="all", choices=[*CASES, "all"])
    args = ap.parse_args()
    key = api_key()
    print(f"key present: {'yes' if key else 'no'}" + (f" (len={len(key)})" if key else ""))
    if not key:
        print("SKIP(no key)")
        return 0
    selected = CASES if args.case == "all" else {args.case: CASES[args.case]}
    for name, fn in selected.items():
        print(f"--- {name} ---")
        try:
            fn(key)
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: ERROR {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
