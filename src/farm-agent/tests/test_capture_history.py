"""
tests/test_capture_history.py -- Unit tests for capture/capture_history.py + capture/retention.py.

TDD RED: all tests written before the modules exist.

Behaviors covered:
  test_select_recent_by_sender        (DB-gated): rows returned for sender since since_ms
  test_select_recent_outbound_by_recipient (DB-gated): outbound rows returned for recipient
  test_select_fail_open               (DB-independent): pool.connection() raises -> [] returned, no raise
  test_retention_runs_once_then_sleeps: mark_expired called immediately; sleep(86400) follows;
                                         mark_expired error is swallowed (WARNING, loop continues)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# DB-gated tests (skip when no test DB available -- same pattern as pool fixture)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_recent_by_sender(pool):
    """DB-gated: select_recent_by_sender returns list of dicts, ordered captured_at DESC."""
    from farm_agent.capture.capture_history import select_recent_by_sender

    # Since we don't seed data, we expect an empty list (no rows for the test sender)
    # The key assertion is: function returns a list (not raising), even with a real pool.
    sender = "+15550009999"
    since_ms = 0  # all time
    result = await select_recent_by_sender(pool, sender, since_ms)
    assert isinstance(result, list), "select_recent_by_sender must return a list"


@pytest.mark.asyncio
async def test_select_recent_outbound_by_recipient(pool):
    """DB-gated: select_recent_outbound_by_recipient returns list of dicts."""
    from farm_agent.capture.capture_history import select_recent_outbound_by_recipient

    recipient = "+15550009999"
    since_ms = 0
    result = await select_recent_outbound_by_recipient(pool, recipient, since_ms)
    assert isinstance(result, list), "select_recent_outbound_by_recipient must return a list"


# ---------------------------------------------------------------------------
# DB-independent fail-open test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_fail_open():
    """DB-independent: pool.connection() raises -> both select functions return [] without raising."""
    from farm_agent.capture.capture_history import (
        select_recent_by_sender,
        select_recent_outbound_by_recipient,
    )

    # Build a fake pool whose connection() raises immediately
    class _FailPool:
        def connection(self):
            raise RuntimeError("FakePool: simulated connection failure")

    fake_pool = _FailPool()

    result_sender = await select_recent_by_sender(fake_pool, "+1555", 0)
    assert result_sender == [], "select_recent_by_sender must return [] on pool error"

    result_outbound = await select_recent_outbound_by_recipient(fake_pool, "+1555", 0)
    assert result_outbound == [], "select_recent_outbound_by_recipient must return [] on pool error"


# ---------------------------------------------------------------------------
# Retention loop test (DB-independent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retention_runs_once_then_sleeps():
    """retention_loop calls mark_expired_older_than immediately (run-once), then awaits sleep(86400).

    Also verifies:
    - A mark_expired error is swallowed (WARNING logged, loop continues to sleep).
    - asyncio.sleep is called with 86400.
    """
    import dataclasses
    from farm_agent.tenancy.tenant import load
    from farm_agent.capture.retention import retention_loop

    # Build minimal config
    config = load({
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

    mark_expired_calls = []
    sleep_calls = []

    async def _fake_mark_expired(pool, age_seconds):
        mark_expired_calls.append(age_seconds)
        return 0

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)
        # Cancel the loop after the first sleep to avoid infinite loop in test
        raise asyncio.CancelledError()

    with (
        patch("farm_agent.capture.retention.mark_expired_older_than", _fake_mark_expired),
        patch("farm_agent.capture.retention.asyncio.sleep", _fake_sleep),
    ):
        try:
            await retention_loop(None, config)
        except asyncio.CancelledError:
            pass  # expected -- _fake_sleep raises CancelledError to break the loop

    # mark_expired must have been called once (run-once semantics)
    assert len(mark_expired_calls) == 1, (
        f"mark_expired_older_than must be called once immediately; got {len(mark_expired_calls)}"
    )
    expected_age_seconds = config.capture_retention_days * 86400
    assert mark_expired_calls[0] == expected_age_seconds, (
        f"mark_expired called with wrong age: {mark_expired_calls[0]}, expected {expected_age_seconds}"
    )

    # sleep must have been called with 86400
    assert len(sleep_calls) == 1, f"asyncio.sleep must be called once; got {len(sleep_calls)}"
    assert sleep_calls[0] == 86400, f"asyncio.sleep must receive 86400; got {sleep_calls[0]}"


@pytest.mark.asyncio
async def test_retention_swallows_mark_expired_error():
    """retention_loop swallows mark_expired_older_than errors (WARNING, loop continues to sleep)."""
    from farm_agent.tenancy.tenant import load
    from farm_agent.capture.retention import retention_loop

    config = load({
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

    sleep_calls = []

    async def _failing_mark_expired(pool, age_seconds):
        raise RuntimeError("retention: simulated DB failure")

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise asyncio.CancelledError()  # stop after first sleep

    with (
        patch("farm_agent.capture.retention.mark_expired_older_than", _failing_mark_expired),
        patch("farm_agent.capture.retention.asyncio.sleep", _fake_sleep),
    ):
        try:
            await retention_loop(None, config)
        except asyncio.CancelledError:
            pass

    # sleep must still have been called -- error was swallowed, loop continued
    assert len(sleep_calls) == 1, (
        "retention_loop must continue to sleep even when mark_expired raises"
    )
