"""
tests/test_capture_durability.py -- MUSHY-78: inbound capture must be durable
before the event gate runs.

The bug: pipeline.handle() ran the event gate (a DB read + a Haiku call) BEFORE
insert_capture(). Anything that killed the process inside that window -- a hung
LLM call, a restart -- lost the farmer's message with no record it ever arrived.
Node does the opposite and says why at capture.js:117-118 ("persist row BEFORE
LLM call so capture is durable even if LLM hangs").

These tests use a REAL postgres and the REAL capture_repo, and observe the actual
signal_capture row. A fake gate that returns instantly cannot prove durability --
the gate here genuinely hangs until the surrounding task is cancelled.
"""

from __future__ import annotations

import asyncio
import os
import socket

import pytest


def _db_reachable() -> bool:
    host = os.environ.get("TEST_TIMESCALE_HOST", "localhost")
    port_str = os.environ.get("TEST_TIMESCALE_PORT", "5434")
    try:
        with socket.create_connection((host, int(port_str)), timeout=2):
            return True
    except OSError:
        return False


_requires_db = pytest.mark.skipif(
    not _db_reachable(), reason="no test DB reachable -- start postgres:14 on :5434"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_with_farmer(sender: str):
    from farm_agent.tenancy.tenant import load
    from tests.conftest import TEST_ENV

    config = load(dict(TEST_ENV))
    config.signal_farmer_map[sender] = "santi"
    return config


def _text_envelope(sender: str, text: str):
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


class _NeverClient:
    """Signal client that must never be touched (text-only envelopes)."""

    async def fetch_attachment(self, att_id: str) -> bytes:  # pragma: no cover
        raise AssertionError("fetch_attachment must not be called for text-only")


_NEVER_TRANSCRIBE = {
    "transcribe": lambda *_a, **_kw: (_ for _ in ()).throw(
        AssertionError("transcribe must not be called for text-only")
    )
}


async def _reset_sender(pool, sender: str) -> None:
    """Drop any rows left by a previous run -- the test DB outlives the suite."""
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM signal_capture WHERE sender = %s", (sender,))


async def _rows_for_sender(pool, sender: str) -> list[tuple]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, raw_text, extraction_gate FROM signal_capture WHERE sender = %s",
            (sender,),
        )
        return await cur.fetchall()


# ---------------------------------------------------------------------------
# CAP-78-01 -- durability: the row survives a gate that hangs past a restart
# ---------------------------------------------------------------------------


@_requires_db
async def test_capture_row_persists_when_gate_hangs_and_task_is_cancelled(pool):
    """A gate that never returns must not cost us the farmer's message.

    Reproduces the loss window: handle() is cancelled while awaiting the gate
    (what a restart looks like to an in-flight coroutine). The signal_capture
    row must already be on disk.
    """
    from farm_agent.capture.pipeline import create_capture_pipeline

    sender = "+15550780001"
    await _reset_sender(pool, sender)
    gate_entered = asyncio.Event()

    async def _hanging_classify(_env_ctx, _last_bot, _now_ms):
        gate_entered.set()
        await asyncio.Event().wait()  # never returns
        raise AssertionError("unreachable")

    pipeline = create_capture_pipeline(
        pool=pool,
        signal_client=_NeverClient(),
        transcribe_client=_NEVER_TRANSCRIBE,
        config=_config_with_farmer(sender),
        gate={"classify": _hanging_classify},
    )

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            pipeline["handle"](_text_envelope(sender, "cosecha koy 3 bolsas")),
            timeout=2.0,
        )

    assert gate_entered.is_set(), "gate never ran -- test did not exercise the window"

    rows = await _rows_for_sender(pool, sender)
    assert len(rows) == 1, "inbound message was lost: no signal_capture row"
    assert rows[0][1] == "cosecha koy 3 bolsas"
    assert rows[0][2] is None, "extraction_gate must be NULL when the gate never answered"


# ---------------------------------------------------------------------------
# CAP-78-02 -- the gate outcome still lands on the row (follow-up UPDATE)
# ---------------------------------------------------------------------------


@_requires_db
async def test_gate_outcome_lands_on_the_persisted_row(pool):
    """Persist-first must not lose the extraction_gate audit column."""
    from farm_agent.capture.pipeline import create_capture_pipeline

    sender = "+15550780002"
    await _reset_sender(pool, sender)

    async def _classify(_env_ctx, _last_bot, _now_ms):
        return {"gate": "event", "allow_extract": True}

    pipeline = create_capture_pipeline(
        pool=pool,
        signal_client=_NeverClient(),
        transcribe_client=_NEVER_TRANSCRIBE,
        config=_config_with_farmer(sender),
        gate={"classify": _classify},
    )

    result = await pipeline["handle"](_text_envelope(sender, "inocule 4 bolsas mali"))
    assert result is not None

    rows = await _rows_for_sender(pool, sender)
    assert len(rows) == 1
    assert rows[0][2] == "event"


# ---------------------------------------------------------------------------
# CAP-78-03 -- a failing gate leaves the row persisted, gate column NULL
# ---------------------------------------------------------------------------


@_requires_db
async def test_gate_error_still_persists_row_with_null_gate(pool):
    """Gate raising is fail-open: capture persists, extraction_gate stays NULL."""
    from farm_agent.capture.pipeline import create_capture_pipeline

    sender = "+15550780003"
    await _reset_sender(pool, sender)

    async def _classify(_env_ctx, _last_bot, _now_ms):
        raise RuntimeError("simulated Haiku outage")

    pipeline = create_capture_pipeline(
        pool=pool,
        signal_client=_NeverClient(),
        transcribe_client=_NEVER_TRANSCRIBE,
        config=_config_with_farmer(sender),
        gate={"classify": _classify},
    )

    result = await pipeline["handle"](_text_envelope(sender, "todo bien"))
    assert result is not None

    rows = await _rows_for_sender(pool, sender)
    assert len(rows) == 1
    assert rows[0][2] is None


# ---------------------------------------------------------------------------
# CAP-78-04 -- the audit UPDATE is itself fail-open (no DB needed)
# ---------------------------------------------------------------------------


async def test_update_extraction_gate_fail_open_never_raises():
    """update_extraction_gate must never throw -- same contract as insert_capture."""
    from farm_agent.capture import capture_repo

    class _RaisingPool:
        class _Conn:
            async def execute(self, *_a, **_kw):
                raise RuntimeError("simulated DB error")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

        def connection(self):
            return self._Conn()

    out = await capture_repo.update_extraction_gate(_RaisingPool(), "01ABC", "event")
    assert out["ok"] is False
    assert "simulated DB error" in out["reason"]
