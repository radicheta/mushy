"""Unit tests for farm_agent.extraction.multimodal.

Covers:
  - mime_from_path: jpg/jpeg/PNG/tiff extension detection
  - downscale_if_needed: real paper-log.jpg fixture (1.44MP > 1.15MP -> JPEG, smaller buffer)
  - downscale_if_needed: in-memory 100x100 RGBA PNG -> JPEG (RGBA convert, no exception)
  - downscale_if_needed: small under-threshold JPEG -> unchanged buffer + media_type
  - read_image_to_base64: nonexistent path -> {ok: False}, no exception raised
  - build_content_blocks: text-only, transcript-only, images, combined
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "extraction" / "seeding-session-may22"


# ---------------------------------------------------------------------------
# mime_from_path
# ---------------------------------------------------------------------------

def test_mime_from_path_jpg():
    from farm_agent.extraction.multimodal import mime_from_path
    assert mime_from_path("photo.jpg") == "image/jpeg"


def test_mime_from_path_jpeg_upper():
    from farm_agent.extraction.multimodal import mime_from_path
    assert mime_from_path("x.JPEG") == "image/jpeg"


def test_mime_from_path_png_upper():
    from farm_agent.extraction.multimodal import mime_from_path
    assert mime_from_path("y.PNG") == "image/png"


def test_mime_from_path_unknown():
    from farm_agent.extraction.multimodal import mime_from_path
    assert mime_from_path("z.tiff") == "application/octet-stream"


# ---------------------------------------------------------------------------
# downscale_if_needed
# ---------------------------------------------------------------------------

def test_downscale_real_paper_log():
    """900x1600 = 1.44MP > 1.15MP -> must downscale, return image/jpeg, pixel count within cap."""
    from farm_agent.extraction.multimodal import downscale_if_needed, MAX_PIXELS
    img_path = FIXTURE_DIR / "paper-log.jpg"
    original_buf = img_path.read_bytes()
    out_buf, out_mime = downscale_if_needed(original_buf, "image/jpeg")
    assert out_mime == "image/jpeg"
    # Verify it's a valid JPEG within the pixel cap (the fixture is highly compressed
    # so the re-encoded output may be larger in bytes, but pixels must be reduced)
    out_img = Image.open(io.BytesIO(out_buf))
    w, h = out_img.size
    assert w * h <= MAX_PIXELS
    # Original was 900x1600=1.44MP, output must have fewer pixels
    assert w * h < 900 * 1600


def test_downscale_rgba_png_no_exception():
    """100x100 RGBA PNG is small but RGBA mode must be converted before JPEG save."""
    from farm_agent.extraction.multimodal import downscale_if_needed, MAX_BYTES, MAX_PIXELS
    # Create a 100x100 RGBA PNG that exceeds MAX_PIXELS if we set it tiny for testing.
    # Since 100x100=10000 < 1.15MP and likely < 5MB, it won't downscale normally.
    # We need to force the RGBA path: create a large RGBA image (> 1.15MP).
    # 1200x1000 = 1.2MP > 1.15MP
    img = Image.new("RGBA", (1200, 1000), color=(128, 64, 32, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    rgba_buf = buf.getvalue()
    out_buf, out_mime = downscale_if_needed(rgba_buf, "image/png")
    # Must succeed (no exception) and return JPEG
    assert out_mime == "image/jpeg"
    # Verify the output is a valid JPEG (no RGBA save error)
    out_img = Image.open(io.BytesIO(out_buf))
    assert out_img.mode == "RGB"


def test_downscale_small_jpeg_unchanged():
    """A small JPEG under both thresholds is returned unchanged."""
    from farm_agent.extraction.multimodal import downscale_if_needed
    # 100x100 JPEG
    img = Image.new("RGB", (100, 100), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    small_buf = buf.getvalue()
    out_buf, out_mime = downscale_if_needed(small_buf, "image/jpeg")
    assert out_buf == small_buf
    assert out_mime == "image/jpeg"


# ---------------------------------------------------------------------------
# read_image_to_base64
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_image_to_base64_missing_path():
    """Nonexistent path -> {ok: False}, no exception raised."""
    from farm_agent.extraction.multimodal import read_image_to_base64
    result = await read_image_to_base64("/nonexistent/path/image.jpg")
    assert result["ok"] is False
    assert "reason" in result


@pytest.mark.asyncio
async def test_read_image_to_base64_valid_image():
    """Valid paper-log.jpg -> {ok: True, data: <base64>, media_type: image/jpeg}."""
    from farm_agent.extraction.multimodal import read_image_to_base64
    img_path = str(FIXTURE_DIR / "paper-log.jpg")
    result = await read_image_to_base64(img_path)
    assert result["ok"] is True
    assert result["media_type"] == "image/jpeg"
    # Verify data is valid base64
    decoded = base64.b64decode(result["data"])
    assert len(decoded) > 0


# ---------------------------------------------------------------------------
# build_content_blocks
# ---------------------------------------------------------------------------

def test_build_content_blocks_text_only():
    from farm_agent.extraction.multimodal import build_content_blocks
    blocks = build_content_blocks(text="hello", transcript=None, images=[])
    assert len(blocks) == 1
    assert blocks[0]["type"] == "text"
    assert blocks[0]["text"] == "hello"


def test_build_content_blocks_transcript_only():
    from farm_agent.extraction.multimodal import build_content_blocks
    blocks = build_content_blocks(text=None, transcript="words", images=[])
    assert len(blocks) == 1
    assert blocks[0]["type"] == "text"
    assert blocks[0]["text"] == "Transcript: words"


def test_build_content_blocks_image_only():
    from farm_agent.extraction.multimodal import build_content_blocks
    blocks = build_content_blocks(
        text=None,
        transcript=None,
        images=[{"data": "abc", "media_type": "image/jpeg"}],
    )
    assert len(blocks) == 1
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["type"] == "base64"
    assert blocks[0]["source"]["media_type"] == "image/jpeg"
    assert blocks[0]["source"]["data"] == "abc"


def test_build_content_blocks_no_data_image_skipped():
    from farm_agent.extraction.multimodal import build_content_blocks
    # Image with no data must be skipped
    blocks = build_content_blocks(
        text="hi",
        transcript=None,
        images=[{"data": None, "media_type": "image/jpeg"}],
    )
    assert len(blocks) == 1
    assert blocks[0]["text"] == "hi"


def test_build_content_blocks_empty():
    from farm_agent.extraction.multimodal import build_content_blocks
    blocks = build_content_blocks(text=None, transcript=None, images=None)
    assert blocks == []
