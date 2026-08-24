"""farm_agent/extraction/multimodal.py -- image helpers for Anthropic content blocks.

Foray island: only stdlib + PIL imports, no other farm_agent package.

Port of src/agents/alerter/src/extraction/multimodal.js.

Responsibilities:
  - mime_from_path: extension -> MIME type
  - downscale_if_needed: enforce 5MB and the MAX_PIXELS ceiling; RGBA/LA/P -> RGB before JPEG save
  - read_image_to_base64: file -> base64 content block; fail-open on any error
  - build_content_blocks: assemble Anthropic content blocks (text, transcript, images)

Security notes (T-60-02-02, T-60-02-03):
  - read_image_to_base64 never raises; logs only the reason string (never image bytes)
  - downscale caps pixel count and file size before base64 encoding
"""

from __future__ import annotations

import base64
import io
import logging
import math
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024  # 5MB Anthropic image ceiling
# Pixel cap before downscale. The old 1.15MP cap was a cost guard sized for large
# phone photos, but it shredded faint-pencil paper logs: a 1600x900 (1.44MP)
# notebook scan got resized + re-JPEG'd at q85, destroying handwriting legibility
# (260530 inoc misread, 2026-05-30). Anthropic accepts well above this. Ported from
# Node df1bdb09, which never reached the Python stack (MUSHY-32).
# ponytail: module constant, not an env knob -- FND-02 forbids direct env reads outside the
# tenant loaders. Promote to a tenant knob if this ever needs per-farm tuning.
MAX_PIXELS = 4_000_000


def mime_from_path(p: str) -> str:
    """Return MIME type from file extension (case-insensitive)."""
    ext = Path(p).suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    return "application/octet-stream"


def downscale_if_needed(buf: bytes, media_type: str) -> tuple[bytes, str]:
    """Enforce 5MB and the MAX_PIXELS ceiling. Re-encodes to JPEG when downscaling.

    RGBA/LA/P images are converted to RGB before JPEG save (PIL cannot save
    RGBA/LA/P as JPEG — T-60-02-02).

    Returns (buf, media_type) unchanged when both thresholds are satisfied.
    Always returns (bytes, str); never raises. Mirrors Node downscaleIfNeeded
    which wraps the entire body in try/catch and returns the original on error.
    """
    try:
        img = Image.open(io.BytesIO(buf))
        w, h = img.size
        if len(buf) <= MAX_BYTES and w * h <= MAX_PIXELS:
            return buf, media_type

        scale = math.sqrt(MAX_PIXELS / (w * h))
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        # CRITICAL: JPEG save fails on RGBA, LA, P modes
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        # Pass through unchanged; outer read_image_to_base64 will log the caller context.
        return buf, media_type


async def read_image_to_base64(image_path: str, log=None) -> dict:
    """Read image file, downscale if needed, return base64 content dict.

    Returns:
        {ok: True, data: str, media_type: str}  on success
        {ok: False, reason: str}                on any error (fail-open)

    Never raises. Logs only the exception reason string, never image content
    (T-60-02-03).
    """
    _log = log or logger
    try:
        buf = Path(image_path).read_bytes()
        media_type = mime_from_path(image_path)
        if media_type in ("image/jpeg", "image/png"):
            buf, media_type = downscale_if_needed(buf, media_type)
        data = base64.b64encode(buf).decode("ascii")
        return {"ok": True, "data": data, "media_type": media_type}
    except Exception as e:  # noqa: BLE001
        _log.warning("[multimodal] read degraded: %s", e)
        return {"ok": False, "reason": str(e)}


def build_content_blocks(
    text: str | None = None,
    transcript: str | None = None,
    images: list[dict] | None = None,
) -> list[dict]:
    """Assemble Anthropic content blocks from text, transcript, and resolved images.

    Args:
        text: raw text content (optional)
        transcript: transcription text (optional; prefixed with "Transcript: ")
        images: list of already-resolved {data, media_type} dicts (optional)

    Returns list of Anthropic content block dicts.
    """
    blocks: list[dict] = []
    if text and str(text).strip():
        blocks.append({"type": "text", "text": str(text)})
    if transcript and str(transcript).strip():
        blocks.append({"type": "text", "text": f"Transcript: {transcript}"})
    for img in images or []:
        if not img or not img.get("data"):
            continue
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.get("media_type") or "image/jpeg",
                    "data": img["data"],
                },
            }
        )
    return blocks
