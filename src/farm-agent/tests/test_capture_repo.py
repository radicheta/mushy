"""
tests/test_capture_repo.py -- Unit tests for capture/capture_repo.py.

Covers:
  DB-independent (always run):
    - insert_capture fail-open: pool.connection() raises -> {ok:False, reason} never propagates
    - mark_expired_older_than fail-open: returns 0 on error, never raises
    - _INSERT_SQL column list includes extraction_gate (CR-01 regression guard)

  DB-gated (@requires_db):
    - attachment_paths=["a.mp3","b.jpg"] round-trips as text[] == ["a.mp3","b.jpg"]  (NOT JSON)
    - transcript=None stores NULL
    - degraded=True/False round-trips bool
    - corpus_context is NULL in the written row (hard-coded None in INSERT)
    - extraction_gate value round-trips (CR-01: was silently dropped before fix)
    - mark_expired_older_than sets expired=true only on rows older than age, returns count
"""

import datetime
import os
import socket
import uuid

import pytest


# ---------------------------------------------------------------------------
# DB reachability gate (mirrors test_signal_persist.py pattern)
# ---------------------------------------------------------------------------


def _db_reachable() -> bool:
    host = os.environ.get("TEST_TIMESCALE_HOST", "localhost")
    port_str = os.environ.get("TEST_TIMESCALE_PORT", "5434")
    try:
        with socket.create_connection((host, int(port_str)), timeout=2):
            return True
    except OSError:
        return False


_NO_DB_REASON = "no test DB reachable -- start postgres:14 on :5434"
_requires_db = pytest.mark.skipif(not _db_reachable(), reason=_NO_DB_REASON)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeRaisingPool:
    """Fake pool whose .connection() raises on execute (simulates DB error)."""

    class _FakeConn:
        async def execute(self, *_a, **_kw):
            raise RuntimeError("simulated DB error")

        async def fetchone(self):
            raise RuntimeError("simulated DB error")

    class _AsyncCtx:
        async def __aenter__(self):
            return FakeRaisingPool._FakeConn()

        async def __aexit__(self, *_a):
            pass

    def connection(self):
        return self._AsyncCtx()


def _capture_row(**overrides) -> dict:
    """Build a minimal valid signal_capture row for testing."""
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    base = {
        "id": str(uuid.uuid4()),
        "captured_at": now,
        "sender": "+10000000001",
        "message_type": "text",
        "raw_text": "hello from test",
        "attachment_paths": [],
        "transcript": None,
        "degraded": False,
        "group_id": None,
        "farmos_person": "(unassigned)",
        "reply_target_kind": "dm",
        "signal_msg_ts": None,
        "quote_msg_ts": None,
        "quote_author_e164": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Part 1: DB-independent -- fail-open
# ---------------------------------------------------------------------------


async def test_insert_capture_fail_open_never_raises():
    """Fail-open: pool error is swallowed, returns {ok:False, reason}, never raises."""
    from farm_agent.capture.capture_repo import insert_capture  # noqa: PLC0415

    result = await insert_capture(FakeRaisingPool(), _capture_row())
    assert result["ok"] is False
    assert "reason" in result
    assert isinstance(result["reason"], str)
    assert len(result["reason"]) > 0


async def test_insert_capture_always_returns_dict():
    """insert_capture never propagates exceptions -- always returns a dict."""
    from farm_agent.capture.capture_repo import insert_capture  # noqa: PLC0415

    result = await insert_capture(FakeRaisingPool(), _capture_row())
    assert isinstance(result, dict)


async def test_mark_expired_fail_open_returns_zero():
    """mark_expired_older_than fail-open: returns 0 on DB error, never raises."""
    from farm_agent.capture.capture_repo import mark_expired_older_than  # noqa: PLC0415

    count = await mark_expired_older_than(FakeRaisingPool(), age_seconds=86400)
    assert count == 0


def test_insert_sql_includes_extraction_gate():
    """CR-01 regression guard: _INSERT_SQL column list must include extraction_gate."""
    from farm_agent.capture.capture_repo import _INSERT_SQL  # noqa: PLC0415

    assert "extraction_gate" in _INSERT_SQL, (
        "extraction_gate is missing from _INSERT_SQL -- CR-01: gate decisions would be silently dropped"
    )


# ---------------------------------------------------------------------------
# Part 2: DB-gated -- round-trip tests
# ---------------------------------------------------------------------------


@_requires_db
async def test_attachment_paths_roundtrip_as_text_array(pool):
    """attachment_paths=["a.mp3","b.jpg"] round-trips as text[] (NOT a JSON string)."""
    from farm_agent.capture.capture_repo import insert_capture  # noqa: PLC0415

    sentinel_id = str(uuid.uuid4())
    row = _capture_row(id=sentinel_id, attachment_paths=["a.mp3", "b.jpg"])

    result = await insert_capture(pool, row)
    assert result == {"ok": True}, f"insert_capture failed: {result}"

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT attachment_paths FROM signal_capture WHERE id = %s",
            (sentinel_id,),
        )
        fetched = await cur.fetchone()

    assert fetched is not None
    stored = fetched[0]
    # Must be a Python list (text[] stored as array), NOT a JSON string
    assert isinstance(stored, list), (
        f"Expected list (text[]), got {type(stored)}: {stored!r}"
    )
    assert stored == ["a.mp3", "b.jpg"]


@_requires_db
async def test_transcript_none_stores_null(pool):
    """transcript=None stores NULL in the DB (not the string 'None')."""
    from farm_agent.capture.capture_repo import insert_capture  # noqa: PLC0415

    sentinel_id = str(uuid.uuid4())
    row = _capture_row(id=sentinel_id, transcript=None)

    await insert_capture(pool, row)

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT transcript FROM signal_capture WHERE id = %s",
            (sentinel_id,),
        )
        fetched = await cur.fetchone()

    assert fetched is not None
    assert fetched[0] is None


@_requires_db
async def test_degraded_roundtrips_bool(pool):
    """degraded=True round-trips as bool True (not 1 or 't')."""
    from farm_agent.capture.capture_repo import insert_capture  # noqa: PLC0415

    sentinel_id = str(uuid.uuid4())
    row = _capture_row(id=sentinel_id, degraded=True)

    await insert_capture(pool, row)

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT degraded FROM signal_capture WHERE id = %s",
            (sentinel_id,),
        )
        fetched = await cur.fetchone()

    assert fetched is not None
    assert fetched[0] is True


@_requires_db
async def test_corpus_context_is_null(pool):
    """corpus_context is always NULL for live captures (hard-coded None in INSERT)."""
    from farm_agent.capture.capture_repo import insert_capture  # noqa: PLC0415

    sentinel_id = str(uuid.uuid4())
    row = _capture_row(id=sentinel_id)

    await insert_capture(pool, row)

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT corpus_context FROM signal_capture WHERE id = %s",
            (sentinel_id,),
        )
        fetched = await cur.fetchone()

    assert fetched is not None
    assert fetched[0] is None, (
        f"corpus_context must be NULL for live captures, got: {fetched[0]!r}"
    )


@_requires_db
async def test_extraction_gate_roundtrips(pool):
    """extraction_gate value round-trips (CR-01: was silently dropped before fix)."""
    from farm_agent.capture.capture_repo import insert_capture  # noqa: PLC0415

    sentinel_id = str(uuid.uuid4())
    row = _capture_row(id=sentinel_id, extraction_gate="haiku_pass")

    result = await insert_capture(pool, row)
    assert result == {"ok": True}, f"insert_capture failed: {result}"

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT extraction_gate FROM signal_capture WHERE id = %s",
            (sentinel_id,),
        )
        fetched = await cur.fetchone()

    assert fetched is not None
    assert fetched[0] == "haiku_pass", (
        f"extraction_gate must persist gate value, got: {fetched[0]!r}"
    )


@_requires_db
async def test_mark_expired_soft_expires_old_rows(pool):
    """mark_expired_older_than sets expired=true only on rows older than age; returns count."""
    from farm_agent.capture.capture_repo import insert_capture, mark_expired_older_than  # noqa: PLC0415

    # Insert a row backdated by 2 days (should be expired by 1-day age)
    sentinel_id = str(uuid.uuid4())
    old_time = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(days=2)
    row = _capture_row(id=sentinel_id, captured_at=old_time, sender="+10000000099")
    result = await insert_capture(pool, row)
    assert result == {"ok": True}, f"insert_capture failed: {result}"

    # Run expiry for rows older than 1 day (86400 seconds)
    count = await mark_expired_older_than(pool, age_seconds=86400)
    assert count >= 1, f"Expected at least 1 row expired, got {count}"

    # Verify the row is now expired
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT expired FROM signal_capture WHERE id = %s",
            (sentinel_id,),
        )
        fetched = await cur.fetchone()

    assert fetched is not None
    assert fetched[0] is True
