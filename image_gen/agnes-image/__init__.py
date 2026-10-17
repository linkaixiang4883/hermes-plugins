"""Agnes AI Intl image generation backend (international endpoint apihub.agnes-ai.com).

Exposes the ``agnes-image-2.0-flash`` model via Agnes AI's OpenAI-compatible
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
import os
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

API_BASE = "https://apihub.agnes-ai.com/v1"

_MODELS: Dict[str, Dict[str, Any]] = {
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

_SIZES = {
    "landscape": "1024x768",
    "square": "1024x1024",
    "portrait": "768x1024",
}


class AgnesImageGenProvider(ImageGenProvider):
    """Agnes AI Intl image generation backend — agnes-image-2.0-flash (international)."""

    @property
    def name(self) -> str:
        return "agnes-image"

    @property
    def display_name(self) -> str:
        return "Agnes AI (Intl)"

    def is_available(self) -> bool:
        return bool(os.environ.get("AGNES_API_KEY"))

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": model_id,
                "display": meta["display"],
                "speed": meta["speed"],
                "strengths": meta["strengths"],
                "price": meta["price"],
            }
            for model_id, meta in _MODELS.items()
        ]

    def default_model(self) -> Optional[str]:
        return DEFAULT_MODEL

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Agnes AI (Intl)",
            "badge": "free",
            "tag": "agnes-image-2.5-flash — text-to-image & image editing (free, latest)",
            "env_vars": [
                {
                    "key": "AGNES_API_KEY",
                    "prompt": "Agnes AI Intl API key",
                    "url": "https://agnes-ai.com/",
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

        api_key = os.environ.get("AGNES_API_KEY")
        if not api_key:
            return error_response(
                error="AGNES_API_KEY not set. Get your key at https://agnes-ai.com/",
                error_type="auth_required",
                provider=self.name,
                aspect_ratio=aspect,
            )

        size = _SIZES.get(aspect, _SIZES["square"])

        # Resolve which model to use (from kwargs or default)
        model_id = kwargs.get("model") or DEFAULT_MODEL
        if model_id not in _MODELS:
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
                f"{API_BASE}/images/generations",
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


def register(ctx) -> None:
    """Plugin entry point — wire AgnesImageGenProvider into the registry."""
    ctx.register_image_gen_provider(AgnesImageGenProvider())
