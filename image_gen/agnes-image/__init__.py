"""Agnes AI image generation backends — 国际站 + 国内站，一个插件两个 provider。

形态照 Hermes 内置 ``plugins/model-providers/opencode-zen``：一个文件注册两个 provider，
选择器里就是两个**并列条目**（Hermes 没有 variant / 子选择概念）。

    provider id        base_url                          env var
    -----------------  --------------------------------  --------------------
    ``agnes-image``    https://apihub.agnes-ai.com/v1     ``AGNES_API_KEY``
    ``agnes-cn-image`` https://api.agnes-ai.cn/v1         ``AGNES_CN_API_KEY``

两家逻辑体完全相同，只有 base_url / key / 名称 / 在售模型集不同（国际站另有 2.0-flash）。

Exposes ``agnes-image-2.5-flash`` (default) / ``2.1-flash``
via Agnes AI's OpenAI-compatible
``/v1/images/generations`` endpoint. Supports:

- **Text-to-image**: prompt only, returns generated image
- **Image-to-image**: pass source image URL(s) for editing/composition
- **Multi-image composition**: pass multiple reference images

API quirks:
  - ``response_format`` MUST be inside ``extra_body``, not at the top level
  - Image-to-image uses ``extra_body.image`` array (not a top-level ``image``)
  - No ``tags`` parameter needed for img2img

Output is saved to ``$HERMES_HOME/cache/images/``.
"""

from __future__ import annotations

import base64
import datetime
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    normalize_reference_images,
    resolve_aspect_ratio,
    save_b64_image,
    save_url_image,
    success_response,
)
from agent.secret_scope import get_secret

logger = logging.getLogger(__name__)

# Max local-file size accepted for data: URI conversion (base64 inflates ~37%).
_MAX_LOCAL_IMAGE_BYTES = 10 * 1024 * 1024


def _to_data_uri_or_url(value: str) -> str:
    """Pass through http(s) URLs and data: URIs; encode local files as data: URIs.

    Every entry path (agent chain, unified tool, direct calls) funnels image
    inputs through here, so callers may pass any of the three forms.
    """
    s = (value or "").strip()
    if not s:
        return s
    low = s.lower()
    if low.startswith(("http://", "https://", "data:")):
        return s
    path = Path(s)
    if not path.is_file():
        raise ValueError(
            f"Image is neither a public http(s) URL, a data: URI, nor a readable local file: {s}"
        )
    if path.stat().st_size > _MAX_LOCAL_IMAGE_BYTES:
        raise ValueError(
            f"Local image exceeds 10MB data: URI cap, host it at a public URL instead: {s}"
        )
    mime, _ = mimetypes.guess_type(str(path))
    if not (mime or "").startswith("image/"):
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")

_MODELS_INTL: Dict[str, Dict[str, Any]] = {
    "agnes-image-2.0-flash": {
        "display": "Agnes Image 2.0 Flash",
        "speed": "~5-15s",
        "strengths": "Text-to-image, image editing, multi-image composition",
        "price": "free (current promotion)",
    },
    "agnes-image-2.1-flash": {
        "display": "Agnes Image 2.1 Flash",
        "speed": "~5-15s",
        "strengths": "Newer image model — improved quality",
        "price": "free (current promotion)",
    },
    "agnes-image-2.5-flash": {
        "display": "Agnes Image 2.5 Flash",
        "speed": "~5-10s",
        "strengths": "Latest — comprehensively exceeds 2.1, high-density visuals, text/image/multi-image",
        "price": "free (current promotion)",
    },
}

DEFAULT_MODEL = "agnes-image-2.5-flash"

# 国内站（api.agnes-ai.cn）的 /v1/models 只列 2.1-flash 与 2.5-flash，**没有 2.0-flash**。
# 国际站保留 2.0-flash（其 /v1/models 仍返回，定价页在售）。
_MODELS_CN: Dict[str, Dict[str, Any]] = {
    "agnes-image-2.1-flash": {
        "display": "Agnes Image 2.1 Flash",
        "speed": "~5-15s",
        "strengths": "Newer image model — improved quality",
        "price": "free (current promotion)",
    },
    "agnes-image-2.5-flash": {
        "display": "Agnes Image 2.5 Flash",
        "speed": "~5-10s",
        "strengths": "Latest — comprehensively exceeds 2.1, high-density visuals, text/image/multi-image",
        "price": "free (current promotion)",
    },
}

_SIZES = {
    "landscape": "1024x768",
    "square": "1024x1024",
    "portrait": "768x1024",
}


class AgnesImageGenProvider(ImageGenProvider):
    """Agnes AI 图像生成后端基类 —— 区域差异全在下面这几个类常量里。

    子类只需覆盖：PROVIDER_NAME / DISPLAY_NAME / ENV_VAR / KEY_PROMPT /
    SIGNUP_URL / API_BASE / MODELS。其余逻辑（含 generate()）一份共享。
    """

    # ── 子类必须覆盖的区域参数 ──
    PROVIDER_NAME: str = ""
    DISPLAY_NAME: str = ""
    ENV_VAR: str = ""
    KEY_PROMPT: str = ""
    SIGNUP_URL: str = ""
    API_BASE: str = ""
    MODELS: Dict[str, Dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return self.PROVIDER_NAME

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    def is_available(self) -> bool:
        return bool(get_secret(self.ENV_VAR))

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": model_id,
                "display": meta["display"],
                "speed": meta["speed"],
                "strengths": meta["strengths"],
                "price": meta["price"],
            }
            for model_id, meta in self.MODELS.items()
        ]

    def default_model(self) -> Optional[str]:
        return DEFAULT_MODEL

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": self.DISPLAY_NAME,
            "badge": "free",
            "tag": "agnes-image-2.5-flash — text-to-image & image editing (free, latest)",
            "env_vars": [
                {
                    "key": self.ENV_VAR,
                    "prompt": self.KEY_PROMPT,
                    "url": self.SIGNUP_URL,
                },
            ],
        }

    def capabilities(self) -> Dict[str, Any]:
        return {"modalities": ["text", "image"], "max_reference_images": 10}

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt = (prompt or "").strip()
        aspect = resolve_aspect_ratio(aspect_ratio)

        if not prompt:
            return error_response(
                error="Prompt is required and must be a non-empty string",
                error_type="invalid_argument",
                provider=self.name,
                aspect_ratio=aspect,
            )

        api_key = get_secret(self.ENV_VAR)
        if not api_key:
            return error_response(
                error=f"{self.ENV_VAR} not set. Get your key at {self.SIGNUP_URL}",
                error_type="auth_required",
                provider=self.name,
                aspect_ratio=aspect,
            )

        size = _SIZES.get(aspect, _SIZES["square"])

        # Resolve which model to use (from kwargs or default)
        model_id = kwargs.get("model") or DEFAULT_MODEL
        if model_id not in self.MODELS:
            model_id = DEFAULT_MODEL

        # Collect source images for image-to-image / multi-image composition.
        # Local paths are encoded to data: URIs here so every entry path works.
        raw_sources: List[str] = []
        if isinstance(image_url, str) and image_url.strip():
            raw_sources.append(image_url.strip())
        for ref in normalize_reference_images(reference_image_urls) or []:
            raw_sources.append(ref)
        try:
            sources = [_to_data_uri_or_url(raw) for raw in raw_sources]
        except ValueError as exc:
            return error_response(
                error=str(exc),
                error_type="invalid_argument",
                provider=self.name,
                aspect_ratio=aspect,
            )

        is_edit = bool(sources)
        modality = "image" if is_edit else "text"

        # Build request body
        # IMPORTANT: response_format goes inside extra_body, NOT top level
        body: Dict[str, Any] = {
            "model": model_id,
            "prompt": prompt,
            "size": size,
            "extra_body": {
                "response_format": "url",
            },
        }

        # Image-to-image: pass images inside extra_body.image
        if is_edit:
            body["extra_body"]["image"] = sources

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                f"{self.API_BASE}/images/generations",
                headers=headers,
                json=body,
                timeout=120,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.debug("Agnes image generation failed", exc_info=True)
            detail = ""
            try:
                raw = exc.response.text if getattr(exc, "response", None) is not None else ""
                if raw:
                    detail = f" Server said: {raw[:500]}"
            except Exception:
                pass
            return error_response(
                error=f"Agnes AI API request failed: {exc}.{detail}",
                error_type="api_error",
                provider=self.name,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        data = resp.json()
        images = data.get("data") or []
        if not images:
            return error_response(
                error="Agnes AI returned no image data",
                error_type="empty_response",
                provider=self.name,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        first = images[0]
        url = first.get("url")
        b64 = first.get("b64_json")
        revised_prompt = first.get("revised_prompt")

        if b64:
            try:
                saved_path = save_b64_image(b64, prefix="agnes_image")
            except Exception as exc:
                return error_response(
                    error=f"Could not save image to cache: {exc}",
                    error_type="io_error",
                    provider=self.name,
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            image_ref = str(saved_path)
        elif url:
            try:
                saved_path = save_url_image(url, prefix="agnes_image")
            except Exception as exc:
                logger.warning(
                    "Agnes image URL %s could not be cached (%s); falling back to bare URL.",
                    url,
                    exc,
                )
                image_ref = url
            else:
                image_ref = str(saved_path)
        else:
            return error_response(
                error="Agnes AI response contained neither b64_json nor URL",
                error_type="empty_response",
                provider=self.name,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        extra: Dict[str, Any] = {"size": size}
        if revised_prompt:
            extra["revised_prompt"] = revised_prompt

        return success_response(
            image=image_ref,
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            provider=self.name,
            modality=modality,
            extra=extra,
        )


class AgnesIntlImageProvider(AgnesImageGenProvider):
    """国际站（apihub.agnes-ai.com）—— agnes-image-2.5-flash(默认) / 2.1-flash / 2.0-flash。"""

    PROVIDER_NAME = "agnes-image"
    DISPLAY_NAME = "Agnes AI (Intl)"
    ENV_VAR = "AGNES_API_KEY"
    KEY_PROMPT = "Agnes AI Intl API key"
    SIGNUP_URL = "https://agnes-ai.com/"
    API_BASE = "https://apihub.agnes-ai.com/v1"
    MODELS = _MODELS_INTL


class AgnesCNImageProvider(AgnesImageGenProvider):
    """国内站（api.agnes-ai.cn）—— agnes-image-2.5-flash(默认) / 2.1-flash（无 2.0-flash）。"""

    PROVIDER_NAME = "agnes-cn-image"
    DISPLAY_NAME = "Agnes AI (CN)"
    ENV_VAR = "AGNES_CN_API_KEY"
    KEY_PROMPT = "Agnes AI CN API key (domestic)"
    SIGNUP_URL = "https://platform.agnes-ai.cn/"
    API_BASE = "https://api.agnes-ai.cn/v1"
    MODELS = _MODELS_CN


def register(ctx) -> None:
    """Plugin entry point — 一次注册两个 provider（国际站 + 国内站）。"""
    ctx.register_image_gen_provider(AgnesIntlImageProvider())
    ctx.register_image_gen_provider(AgnesCNImageProvider())
