"""Unit tests for farm_agent.extraction.multimodal.

Covers:
  - mime_from_path: jpg/jpeg/PNG/tiff extension detection
  - downscale_if_needed: real paper-log.jpg fixture (1.44MP) passes through untouched at the default cap
  - downscale_if_needed: a lowered MAX_PIXELS forces the downscale path
  - downscale_if_needed: in-memory RGBA PNG -> JPEG (RGBA convert, no exception)
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

def test_downscale_real_paper_log_untouched_at_default_cap():
    """900x1600 = 1.44MP is under the 4MP default cap -> paper log must NOT be re-encoded.

    Regression: the old 1.15MP cap shredded faint-pencil handwriting on notebook
    scans and caused the 260530 inoc misread. Ported from Node df1bdb09.
    """
    from farm_agent.extraction.multimodal import downscale_if_needed
    img_path = FIXTURE_DIR / "paper-log.jpg"
    original_buf = img_path.read_bytes()
    out_buf, out_mime = downscale_if_needed(original_buf, "image/jpeg")
    assert out_buf == original_buf
    assert out_mime == "image/jpeg"


def test_downscale_lowered_cap_forces_downscale(monkeypatch):
    """Lowering MAX_PIXELS re-enables the cap, proving the downscale path still works."""
    from farm_agent.extraction import multimodal
    from farm_agent.extraction.multimodal import downscale_if_needed
    monkeypatch.setattr(multimodal, "MAX_PIXELS", 1_150_000)
    img_path = FIXTURE_DIR / "paper-log.jpg"
    original_buf = img_path.read_bytes()
    out_buf, out_mime = downscale_if_needed(original_buf, "image/jpeg")
    assert out_mime == "image/jpeg"
    w, h = Image.open(io.BytesIO(out_buf)).size
    assert w * h <= 1_150_000
    assert w * h < 900 * 1600


def test_downscale_rgba_png_no_exception(monkeypatch):
    """A large RGBA PNG must be converted to RGB before the JPEG save."""
    from farm_agent.extraction import multimodal
    from farm_agent.extraction.multimodal import downscale_if_needed
    monkeypatch.setattr(multimodal, "MAX_PIXELS", 1_150_000)
    # 1200x1000 = 1.2MP > the overridden cap, so the downscale path runs.
    img = Image.new("RGBA", (1200, 1000), color=(128, 64, 32, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out_buf, out_mime = downscale_if_needed(buf.getvalue(), "image/png")
    assert out_mime == "image/jpeg"
    assert Image.open(io.BytesIO(out_buf)).mode == "RGB"


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
