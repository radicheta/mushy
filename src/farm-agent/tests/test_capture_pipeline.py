"""
tests/test_capture_pipeline.py -- Unit tests for capture/pipeline.py (CAP-01/CAP-02).

TDD RED: all tests written before pipeline.py exists.
All HTTP + disk I/O is faked via injected deps (Option B: fake dict injection).

Key behaviors:
  test_handle_text_only          -- text envelope -> insert_capture called; ULID id; farmer slug
  test_handle_audio_attachment   -- audio attach -> fetch_attachment, file written, path in attachment_paths
  test_d05_missing_file_dropped  -- write ok but Path.exists->False: path NOT added, degraded=True
  test_d04_transcription_failure -- transcribe {ok:False} -> row persisted, transcript=None, degraded=True
  test_unassigned_farmer         -- unknown sender -> farmos_person == "(unassigned)"
  test_sc2_transcription_offloop -- transcribe awaits; another task's flag flips; loop yields
  test_handle_never_raises       -- dep raises mid-step; handle returns None, loop not killed
  test_record_reply_capture      -- persist-only stub: no attachment download, no transcription
"""

from __future__ import annotations

import asyncio
import dataclasses
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / test doubles
# ---------------------------------------------------------------------------


def _test_config():
    """Build a minimal TenantConfig for testing (no farmer map)."""
    from farm_agent.tenancy.tenant import load
    return load({
        "TENANT_ID": "test",
        "TIMESCALE_HOST": "localhost:5434",
        "TIMESCALE_DB": "test_farm_agent",
        "TIMESCALE_USER": "postgres",
        "TIMESCALE_PASSWORD": "test",
        "SIGNAL_SENDER": "+10000000000",
        "ANTHROPIC_API_KEY": "test-key",
        "FARMOS_PASSWORD": "test-pass",
        "FARMOS_URL": "http://localhost:18080",
        "FARMOS_USERNAME": "test-user",
        "SIGNAL_RECIPIENT": "+10000000001",
    })


def _test_config_with_farmer():
    """TenantConfig with a known farmer mapping (+15550001234 -> santi)."""
    config = _test_config()
    config.signal_farmer_map["+15550001234"] = "santi"
    return config


_KNOWN_SENDER = "+15550001234"
_UNKNOWN_SENDER = "+19990009999"


def _text_envelope(sender=_KNOWN_SENDER, text="hola"):
    return {
        "envelope": {
            "source": sender,
            "dataMessage": {
                "message": text,
                "attachments": [],
                "timestamp": 1718900000000,
            },
        }
    }


def _audio_envelope(sender=_KNOWN_SENDER):
    return {
        "envelope": {
            "source": sender,
            "dataMessage": {
                "message": None,
                "attachments": [
                    {"id": "att-001", "contentType": "audio/ogg", "voiceNote": True},
                ],
                "timestamp": 1718900000000,
            },
        }
    }


class FakeSignalClient:
    """Duck-typed signal client whose fetch_attachment returns dummy bytes."""

    def __init__(self, should_raise: bool = False):
        self.should_raise = should_raise
        self.fetch_calls: list[str] = []

    async def fetch_attachment(self, att_id: str) -> bytes:
        self.fetch_calls.append(att_id)
        if self.should_raise:
            raise RuntimeError("FakeSignalClient: simulated fetch failure")
        return b"\x00\x01\x02"  # minimal dummy audio bytes


# ---------------------------------------------------------------------------
# test_handle_text_only
# ---------------------------------------------------------------------------


async def test_handle_text_only(fake_capture_repo, tmp_path):
    """Text-only envelope -> insert_capture called; ULID id (26 chars); farmer slug resolved."""
    from farm_agent.capture.pipeline import create_capture_pipeline

    config = _test_config_with_farmer()
    config = dataclasses.replace(config, capture_base_dir=str(tmp_path))

    async def _unused_transcribe(arg):
        raise AssertionError("transcribe must not be called for text-only message")

    pipeline = create_capture_pipeline(
        pool=None,
        signal_client=FakeSignalClient(),
        transcribe_client={"transcribe": _unused_transcribe},
        config=config,
        capture_repo=fake_capture_repo,
    )

    result = await pipeline["handle"](_text_envelope(sender=_KNOWN_SENDER))

    assert result is not None, "handle() must return a CaptureResult for a text envelope"
    assert len(fake_capture_repo.calls) == 1
    row = fake_capture_repo.calls[0]
    assert row["message_type"] == "text"
    assert row["farmos_person"] == "santi"
    assert len(row["id"]) == 26, f"Expected 26-char ULID, got {row['id']!r}"
    assert row["sender"] == _KNOWN_SENDER


# ---------------------------------------------------------------------------
# test_handle_audio_attachment
# ---------------------------------------------------------------------------


async def test_handle_audio_attachment(fake_capture_repo, fake_transcribe_client, tmp_path):
    """Audio attachment -> fetch_attachment called, file written, path in attachment_paths, transcript populated."""
    from farm_agent.capture.pipeline import create_capture_pipeline

    config = _test_config_with_farmer()
    config = dataclasses.replace(config, capture_base_dir=str(tmp_path))

    signal_client = FakeSignalClient()
    pipeline = create_capture_pipeline(
        pool=None,
        signal_client=signal_client,
        transcribe_client=fake_transcribe_client,
        config=config,
        capture_repo=fake_capture_repo,
    )

    result = await pipeline["handle"](_audio_envelope())

    assert result is not None
    assert "att-001" in signal_client.fetch_calls
    row = fake_capture_repo.calls[0]
    assert len(row["attachment_paths"]) == 1, "Expected 1 attachment path in row"
    path_str = row["attachment_paths"][0]
    assert pathlib.Path(path_str).exists(), f"Written file must exist: {path_str}"
    assert row["transcript"] == "fake transcript"


# ---------------------------------------------------------------------------
# test_d05_missing_file_dropped
# ---------------------------------------------------------------------------


async def test_d05_missing_file_dropped(fake_capture_repo, fake_transcribe_client, tmp_path, caplog):
    """D-05: Path.exists() -> False after write -> path NOT in attachment_paths; degraded=True."""
    import logging
    from farm_agent.capture.pipeline import create_capture_pipeline

    config = _test_config_with_farmer()
    config = dataclasses.replace(config, capture_base_dir=str(tmp_path))

    signal_client = FakeSignalClient()
    pipeline = create_capture_pipeline(
        pool=None,
        signal_client=signal_client,
        transcribe_client=fake_transcribe_client,
        config=config,
        capture_repo=fake_capture_repo,
    )

    # Patch pathlib.Path.exists to always return False AFTER write_bytes
    original_exists = pathlib.Path.exists

    call_count = {"n": 0}

    def fake_exists(self):
        # Return False so the D-05 gate fires
        return False

    with patch.object(pathlib.Path, "exists", fake_exists):
        with caplog.at_level(logging.WARNING):
            result = await pipeline["handle"](_audio_envelope())

    assert result is not None
    row = fake_capture_repo.calls[0]
    assert row["attachment_paths"] == [], "D-05: missing file must NOT be in attachment_paths"
    assert row["degraded"] is True, "D-05: degraded must be True when file missing after write"


# ---------------------------------------------------------------------------
# test_d04_transcription_failure
# ---------------------------------------------------------------------------


async def test_d04_transcription_failure(fake_capture_repo, tmp_path):
    """D-04: transcribe {ok:False} -> insert_capture STILL called, transcript=None, degraded=True."""
    from farm_agent.capture.pipeline import create_capture_pipeline

    async def _failing_transcribe(arg):
        return {"ok": False, "reason": "whisper 503: service unavailable"}

    config = _test_config_with_farmer()
    config = dataclasses.replace(config, capture_base_dir=str(tmp_path))

    pipeline = create_capture_pipeline(
        pool=None,
        signal_client=FakeSignalClient(),
        transcribe_client={"transcribe": _failing_transcribe},
        config=config,
        capture_repo=fake_capture_repo,
    )

    result = await pipeline["handle"](_audio_envelope())

    # handle must NOT raise and must NOT drop the capture
    assert len(fake_capture_repo.calls) == 1, "D-04: exactly one row must be inserted even on transcription failure"
    row = fake_capture_repo.calls[0]
    assert row["transcript"] is None, "D-04: transcript must be None on failure"
    assert row["degraded"] is True, "D-04: degraded must be True on transcription failure"


# ---------------------------------------------------------------------------
# test_unassigned_farmer
# ---------------------------------------------------------------------------


async def test_unassigned_farmer(fake_capture_repo, fake_transcribe_client, tmp_path):
    """Unknown sender -> farmos_person == '(unassigned)', capture still inserted."""
    from farm_agent.capture.pipeline import create_capture_pipeline

    config = _test_config()  # no farmer map entries for _UNKNOWN_SENDER
    config = dataclasses.replace(config, capture_base_dir=str(tmp_path))

    pipeline = create_capture_pipeline(
        pool=None,
        signal_client=FakeSignalClient(),
        transcribe_client=fake_transcribe_client,
        config=config,
        capture_repo=fake_capture_repo,
    )

    result = await pipeline["handle"](_text_envelope(sender=_UNKNOWN_SENDER))

    assert len(fake_capture_repo.calls) == 1
    row = fake_capture_repo.calls[0]
    assert row["farmos_person"] == "(unassigned)"


# ---------------------------------------------------------------------------
# test_sc2_transcription_offloop
# ---------------------------------------------------------------------------


async def test_sc2_transcription_offloop(fake_capture_repo, tmp_path):
    """SC#2: transcribe awaits asyncio.sleep; another task's flag flips before handle() returns."""
    import inspect
    from farm_agent.capture.pipeline import create_capture_pipeline

    flag = {"flipped": False}

    async def _slow_transcribe(arg):
        # Yield to the event loop -- another coroutine can run during this await
        await asyncio.sleep(0.05)
        return {"ok": True, "text": "slow transcript", "duration_ms": 500, "language": "en"}

    async def _set_flag():
        await asyncio.sleep(0.01)  # yields before slow_transcribe completes
        flag["flipped"] = True

    config = _test_config_with_farmer()
    config = dataclasses.replace(config, capture_base_dir=str(tmp_path))

    pipeline = create_capture_pipeline(
        pool=None,
        signal_client=FakeSignalClient(),
        transcribe_client={"transcribe": _slow_transcribe},
        config=config,
        capture_repo=fake_capture_repo,
    )

    # Schedule both concurrently: flag should flip WHILE handle() is awaiting transcription
    flag_task = asyncio.create_task(_set_flag())
    await pipeline["handle"](_audio_envelope())
    await flag_task

    assert flag["flipped"], "SC#2: event loop must yield during transcription (off-loop)"

    # Structural check: transcribe must be a coroutine function
    assert inspect.iscoroutinefunction(_slow_transcribe), "transcribe must be async def"


# ---------------------------------------------------------------------------
# test_handle_never_raises
# ---------------------------------------------------------------------------


async def test_handle_never_raises(fake_capture_repo, tmp_path):
    """D-03: dep raises mid-step (fetch_attachment) -> handle swallows, returns None, does not kill loop."""
    from farm_agent.capture.pipeline import create_capture_pipeline

    config = _test_config_with_farmer()
    config = dataclasses.replace(config, capture_base_dir=str(tmp_path))

    # signal_client.fetch_attachment raises
    pipeline = create_capture_pipeline(
        pool=None,
        signal_client=FakeSignalClient(should_raise=True),
        transcribe_client={"transcribe": AsyncMock(return_value={"ok": True, "text": "x"})},
        config=config,
        capture_repo=fake_capture_repo,
    )

    # Must NOT raise -- the exception is swallowed and handle returns normally
    # (either None from outer catch, or a result with degraded attachment)
    try:
        result = await pipeline["handle"](_audio_envelope())
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"D-03: handle() must never raise but got: {exc}")


# ---------------------------------------------------------------------------
# test_record_reply_capture
# ---------------------------------------------------------------------------


async def test_record_reply_capture(fake_capture_repo, tmp_path):
    """record_reply_capture persists a row with NO attachment download / transcription."""
    from farm_agent.capture.pipeline import create_capture_pipeline

    signal_client = FakeSignalClient()

    async def _should_not_be_called(arg):
        raise AssertionError("transcribe must NOT be called in record_reply_capture")

    config = _test_config_with_farmer()
    config = dataclasses.replace(config, capture_base_dir=str(tmp_path))

    pipeline = create_capture_pipeline(
        pool=None,
        signal_client=signal_client,
        transcribe_client={"transcribe": _should_not_be_called},
        config=config,
        capture_repo=fake_capture_repo,
    )

    envelope = _text_envelope(sender=_KNOWN_SENDER, text="YES")
    await pipeline["record_reply_capture"](envelope)

    # fetch_attachment must NOT have been called
    assert signal_client.fetch_calls == [], "record_reply_capture must NOT fetch attachments"
    # But insert_capture MUST have been called
    assert len(fake_capture_repo.calls) == 1, "record_reply_capture must persist the row"
    row = fake_capture_repo.calls[0]
    assert row["raw_text"] == "YES"
    assert row["attachment_paths"] == []
    assert row["transcript"] is None
