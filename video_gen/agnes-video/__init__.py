"""Agnes AI Intl video generation backend (international endpoint apihub.agnes-ai.com).

Exposes ``agnes-video-2.5`` / ``agnes-video-2.5-flash`` (default) via Agnes AI's async
task API (OpenAI Videos-compatible: ``POST /v1/videos`` + ``GET /agnesapi``).
Supports:

- **Text-to-video**: generate video from text prompt
- **Image-to-video**: animate a static image
- **Keyframe animation**: smooth transition between keyframe images

API flow (async):
  1. POST /v1/videos  → create task, get video_id
  2. GET  /agnesapi?video_id=<ID>&model_name=<MODEL>  → poll until status=completed
  3. Download video from returned URL → save to $HERMES_HOME/cache/videos/

Request contract (per model docs — height/width/num_frames are forbidden):
  - body: {model, prompt, mode, seconds(str 4-12), size "720P", aspect_ratio}
  - text: no image fields; reference: images[] (<=5 URLs, needs <Picture N> in prompt);
    keyframe: first_frame/last_frame
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from agent.video_gen_provider import (
    VideoGenProvider,
    error_response,
    save_bytes_video,
    success_response,
)

# Reuse the shared reference-image normalizer from the image_gen provider
# module (same logic — coerce None/str/list into a clean list of strings).
from agent.image_gen_provider import normalize_reference_images

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
API_MODEL = "agnes-video-2.5-flash"
API_MODELS = {
    "agnes-video-2.5": {"display": "Agnes Video 2.5", "price": "free"},
    "agnes-video-2.5-flash": {"display": "Agnes Video 2.5 Flash", "price": "free (latest)"},
}

# Polling configuration
POLL_INTERVAL = 2  # seconds between polls (docs: poll every 1-2s)
POLL_TIMEOUT = 300  # max wait: 5 minutes

# Aspect-ratio names accepted by generate() mapped to the API's aspect_ratio
# values (size is fixed to "720P"; see the size table in the model docs).
_ASPECT_MAP = {
    "landscape": "16:9",
    "square": "1:1",
    "portrait": "9:16",
}


class AgnesVideoGenProvider(VideoGenProvider):
    """Agnes AI Intl video generation backend — agnes-video-2.5 / 2.5-flash (international)."""

    @property
    def name(self) -> str:
        return "agnes-video"

    @property
    def display_name(self) -> str:
        return "Agnes AI (Intl)"

    def is_available(self) -> bool:
        return bool(os.environ.get("AGNES_API_KEY"))

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {"id": k, "display": v["display"], "speed": "~1-5min", "strengths": "Text-to-video, image-to-video, keyframe", "price": v["price"]}
            for k, v in API_MODELS.items()
        ]

    def default_model(self) -> Optional[str]:
        return API_MODEL

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Agnes AI (Intl)",
            "badge": "free",
            "tag": "agnes-video-2.5-flash — text-to-video & image-to-video (free, latest)",
            "env_vars": [
                {
                    "key": "AGNES_API_KEY",
                    "prompt": "Agnes AI Intl API key",
                    "url": "https://agnes-ai.com/",
                },
            ],
        }

    def capabilities(self) -> Dict[str, Any]:
        return {
            "modalities": ["text", "image"],
            "max_reference_images": 5,
            "durations": (4, 12),
        }

    def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        duration: Optional[int] = None,
        aspect_ratio: str = "landscape",
        resolution: str = "720p",
        negative_prompt: Optional[str] = None,
        audio: Optional[bool] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt = (prompt or "").strip()

        if not prompt:
            return error_response(
                error="Prompt is required and must be a non-empty string",
                error_type="invalid_argument",
                provider=self.name,
            )

        api_key = os.environ.get("AGNES_API_KEY")
        if not api_key:
            return error_response(
                error="AGNES_API_KEY not set. Get your key at https://agnes-ai.com/",
                error_type="auth_required",
                provider=self.name,
            )

        # Map our aspect-ratio names to the API's aspect_ratio values
        # (size is fixed to "720P"; see the size table in the model docs).
        api_aspect = _ASPECT_MAP.get(aspect_ratio, "16:9")

        # Duration: the API takes seconds as a string in "4".."12".
        try:
            seconds = str(min(12, max(4, int(duration if duration is not None else 5))))
        except (TypeError, ValueError):
            seconds = "5"

        # Resolve which model to use (explicit argument wins, else default).
        # Unknown ids fall back to the default instead of 400ing upstream.
        model_id = (model or "").strip() or API_MODEL
        if model_id not in API_MODELS:
            model_id = API_MODEL

        # Routing: keyframe (2+ images) vs reference (single image) vs text.
        # Local paths are encoded to data: URIs here so every entry path works.
        raw_refs = normalize_reference_images(reference_image_urls) or []
        if isinstance(image_url, str) and image_url.strip():
            raw_refs = [image_url.strip()] + raw_refs
        try:
            refs = [_to_data_uri_or_url(raw) for raw in raw_refs]
        except ValueError as exc:
            return error_response(
                error=str(exc),
                error_type="invalid_argument",
                provider=self.name,
            )
        is_keyframe = len(refs) >= 2
        is_reference = bool(refs) and not is_keyframe

        # Request body follows the documented contract:
        # {model, prompt, mode, seconds, size, aspect_ratio}.
        # height/width/num_frames/frame_rate are forbidden fields (HTTP 400),
        # as are negative_prompt and any other undeclared keys.
        body: Dict[str, Any] = {
            "model": model_id,
            "prompt": prompt,
            "mode": "keyframe" if is_keyframe else ("reference" if is_reference else "text"),
            "seconds": seconds,
            "size": "720P",
            "aspect_ratio": api_aspect,
        }

        if seed is not None:
            body["seed"] = seed
        if negative_prompt:
            logger.debug("Agnes video API has no negative_prompt field; ignoring.")

        if is_keyframe:
            body["first_frame"] = refs[0]
            body["last_frame"] = refs[-1]
        elif is_reference:
            body["images"] = refs[:5]
            if "<Picture" not in prompt:
                # Reference mode requires <Picture N> placeholders in the
                # prompt or the images may be ignored upstream.
                body["prompt"] = prompt + " Use <Picture 1> as the visual reference for the subject and style."

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Step 1: Create video task
        try:
            resp = requests.post(
                f"{API_BASE}/videos",
                headers=headers,
                json=body,
                timeout=60,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.debug("Agnes video task creation failed", exc_info=True)
            detail = ""
            try:
                raw = exc.response.text if getattr(exc, "response", None) is not None else ""
                if raw:
                    detail = f" Server said: {raw[:500]}"
            except Exception:
                pass
            return error_response(
                error=f"Agnes AI video task creation failed: {exc}.{detail}",
                error_type="api_error",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        task_data = resp.json()
        video_id = task_data.get("video_id") or task_data.get("task_id")
        if not video_id:
            return error_response(
                error=f"Agnes AI did not return a video_id. Response: {task_data}",
                error_type="empty_response",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        logger.info(
            "Agnes video task created: video_id=%s, status=%s",
            video_id,
            task_data.get("status"),
        )

        # Step 2: Poll for completion
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed > POLL_TIMEOUT:
                return error_response(
                    error=f"Video generation timed out after {POLL_TIMEOUT}s. video_id={video_id}",
                    error_type="timeout",
                    provider=self.name,
                    model=model_id,
                    prompt=prompt,
                )

            time.sleep(POLL_INTERVAL)

            try:
                poll_resp = requests.get(
                    f"https://apihub.agnes-ai.com/agnesapi",
                    params={"video_id": video_id, "model_name": model_id},
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=30,
                )
                poll_resp.raise_for_status()
            except requests.exceptions.RequestException as exc:
                logger.debug("Agnes video poll failed: %s", exc)
                continue

            result = poll_resp.json()
            status = result.get("status", "")
            progress = result.get("progress", 0)

            logger.info(
                "Agnes video poll: video_id=%s status=%s progress=%s",
                video_id,
                status,
                progress,
            )

            if status == "completed":
                video_url = result.get("url")
                if not video_url:
                    return error_response(
                        error=f"Video completed but no URL returned. Response: {result}",
                        error_type="empty_response",
                        provider=self.name,
                        model=model_id,
                        prompt=prompt,
                    )
                break
            elif status == "failed":
                error_msg = result.get("error") or "Video generation failed"
                return error_response(
                    error=f"Agnes AI video generation failed: {error_msg}",
                    error_type="api_error",
                    provider=self.name,
                    model=model_id,
                    prompt=prompt,
                )

        # Step 3: Download video and save to cache
        try:
            video_resp = requests.get(video_url, timeout=120)
            video_resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "Could not download video from %s: %s; returning bare URL.",
                video_url,
                exc,
            )
            video_ref = video_url
        else:
            saved_path = save_bytes_video(
                video_resp.content,
                prefix="agnes_video",
                extension="mp4",
            )
            video_ref = str(saved_path)

        modality = "image" if (is_keyframe or is_reference) else "text"

        extra: Dict[str, Any] = {
            "duration": f"{seconds}s",
            "resolution": f"720P {api_aspect}",
            "video_id": video_id,
        }

        return success_response(
            video=video_ref,
            model=model_id,
            prompt=prompt,
            provider=self.name,
            modality=modality,
            extra=extra,
        )


def register(ctx) -> None:
    """Plugin entry point — wire AgnesVideoGenProvider into the registry."""
    ctx.register_video_gen_provider(AgnesVideoGenProvider())
