"""
tests/confirm/test_watchdog.py -- Unit tests for watchdog.py confirm loop.

Covers:
  - tick_once: sends exactly one nudge per due row; with mark_nudge_sent rowcount=0 skips
  - confirm_watchdog_loop: re-raises asyncio.CancelledError (not swallowed)
  - confirm_watchdog_loop: immediate tick on first entry, then interval-sleep
  - confirm_watchdog_loop: tick Exception logs WARNING and loop continues (never-throws)
  - boot wiring: confirm_watchdog_loop present in boot.py (import check)

No DB required -- uses a stub confirm_repo + fake signal_client.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeSignalClientWatchdog:
    """Records send() calls. Never raises."""

    def __init__(self) -> None:
        self.sends: list[dict] = []

    async def send(self, body: str, *, to=None, related_draft_id=None, intent=None, **kwargs) -> dict:
        self.sends.append({"body": body, "to": to, "related_draft_id": related_draft_id})
        return {"ok": True, "timestamp": 1234567890}


class StubConfirmRepo:
    """Configurable stub for watchdog tick_once tests.

    nudge_candidates: list of rows returned by find_nudge_candidates
    expire_candidates: list of rows returned by find_expire_candidates
    nudge_rowcounts: iterator of rowcounts for successive mark_nudge_sent calls
    expire_rowcounts: iterator of rowcounts for successive expire_draft calls
    """

    def __init__(
        self,
        nudge_candidates: list[dict] | None = None,
        expire_candidates: list[dict] | None = None,
        nudge_rowcounts: list[int] | None = None,
        expire_rowcounts: list[int] | None = None,
    ) -> None:
        self.nudge_candidates = nudge_candidates or []
        self.expire_candidates = expire_candidates or []
        self._nudge_rowcounts = iter(nudge_rowcounts or [1])
        self._expire_rowcounts = iter(expire_rowcounts or [1])
        self.mark_nudge_calls: list[str] = []
        self.expire_calls: list[dict] = []
        self.append_event_calls: list[dict] = []

    async def find_nudge_candidates(self, pool, nudge_min: int) -> list:
        return self.nudge_candidates

    async def find_expire_candidates(self, pool, timeout_min: int) -> list:
        return self.expire_candidates

    async def mark_nudge_sent(self, pool, draft_id: str) -> dict:
        self.mark_nudge_calls.append(draft_id)
        rowcount = next(self._nudge_rowcounts, 0)
        return {"ok": True, "rowcount": rowcount}

    async def expire_draft(self, pool, draft_id: str, reason: str) -> dict:
        self.expire_calls.append({"draft_id": draft_id, "reason": reason})
        rowcount = next(self._expire_rowcounts, 0)
        return {"ok": True, "rowcount": rowcount}

    async def append_event_via_pool(self, pool, draft_id: str, event: str, payload) -> dict:
        self.append_event_calls.append({"draft_id": draft_id, "event": event})
        return {"ok": True, "seq": 1}


def _make_nudge_row(draft_id: str = "draft-001") -> dict:
    """Minimal nudge candidate row."""
    import datetime  # noqa: PLC0415
    return {
        "id": draft_id,
        "sender_e164": "+59899000001",
        "reply_target_kind": "dm",
        "group_id": None,
        "farmer_facing_preview": "5 bags inoculation",
        "updated_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30),
    }


def _make_expire_row(draft_id: str = "draft-exp-001") -> dict:
    import datetime  # noqa: PLC0415
    return {
        "id": draft_id,
        "sender_e164": "+59899000002",
        "reply_target_kind": "dm",
        "group_id": None,
        "farmer_facing_preview": "harvest",
        "updated_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=40),
    }


def _make_config(timeout_min: int = 30, interval_ms: int = 60000, nudge_fraction: float = 0.8) -> SimpleNamespace:
    return SimpleNamespace(
        draft_pending_timeout_min=timeout_min,
        draft_nudge_fraction=nudge_fraction,
        draft_watchdog_interval_ms=interval_ms,
        max_edit_turns=3,
    )


# ---------------------------------------------------------------------------
# tick_once: nudge path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_once_sends_one_nudge_for_due_row():
    """tick_once with one due row sends exactly one nudge (mark_nudge_sent rowcount=1)."""
    from farm_agent.confirm.watchdog import tick_once  # noqa: PLC0415

    fake_signal = FakeSignalClientWatchdog()
    stub_repo = StubConfirmRepo(
        nudge_candidates=[_make_nudge_row()],
        nudge_rowcounts=[1],
    )
    config = _make_config()
    lock = asyncio.Lock()

    await tick_once(object(), fake_signal, config, lock=lock, repo=stub_repo)

    assert len(fake_signal.sends) == 1, f"Expected 1 nudge send, got {len(fake_signal.sends)}"
    assert stub_repo.mark_nudge_calls == ["draft-001"]


@pytest.mark.asyncio
async def test_tick_once_skips_nudge_when_already_sent():
    """tick_once with mark_nudge_sent rowcount=0 skips the send (race lost)."""
    from farm_agent.confirm.watchdog import tick_once  # noqa: PLC0415

    fake_signal = FakeSignalClientWatchdog()
    stub_repo = StubConfirmRepo(
        nudge_candidates=[_make_nudge_row()],
        nudge_rowcounts=[0],  # race lost -- already nudged
    )
    config = _make_config()
    lock = asyncio.Lock()

    await tick_once(object(), fake_signal, config, lock=lock, repo=stub_repo)

    assert len(fake_signal.sends) == 0, "Should not send nudge when rowcount=0"


@pytest.mark.asyncio
async def test_tick_once_sends_expire_note_for_due_row():
    """tick_once with one expire-due row sends expired note (expire_draft rowcount=1)."""
    from farm_agent.confirm.watchdog import tick_once  # noqa: PLC0415

    fake_signal = FakeSignalClientWatchdog()
    stub_repo = StubConfirmRepo(
        expire_candidates=[_make_expire_row()],
        expire_rowcounts=[1],
    )
    config = _make_config()
    lock = asyncio.Lock()

    await tick_once(object(), fake_signal, config, lock=lock, repo=stub_repo)

    assert len(fake_signal.sends) == 1, "Expected 1 expire send"
    assert stub_repo.expire_calls[0]["draft_id"] == "draft-exp-001"
    assert stub_repo.expire_calls[0]["reason"] == "timeout_expired"


@pytest.mark.asyncio
async def test_tick_once_skips_expire_when_already_expired():
    """tick_once with expire_draft rowcount=0 skips the send."""
    from farm_agent.confirm.watchdog import tick_once  # noqa: PLC0415

    fake_signal = FakeSignalClientWatchdog()
    stub_repo = StubConfirmRepo(
        expire_candidates=[_make_expire_row()],
        expire_rowcounts=[0],
    )
    config = _make_config()
    lock = asyncio.Lock()

    await tick_once(object(), fake_signal, config, lock=lock, repo=stub_repo)

    assert len(fake_signal.sends) == 0, "Should not send expire note when rowcount=0"


@pytest.mark.asyncio
async def test_tick_once_nudge_body_contains_preview():
    """D-2: unlike Node (watchdog.js:31, minutesRemaining only), the nudge body
    must name which draft is nudging the farmer.
    """
    from farm_agent.confirm.watchdog import tick_once  # noqa: PLC0415

    fake_signal = FakeSignalClientWatchdog()
    stub_repo = StubConfirmRepo(
        nudge_candidates=[_make_nudge_row()],
        nudge_rowcounts=[1],
    )
    config = _make_config()
    lock = asyncio.Lock()

    await tick_once(object(), fake_signal, config, lock=lock, repo=stub_repo)

    assert len(fake_signal.sends) == 1
    assert "5 bags inoculation" in fake_signal.sends[0]["body"]


@pytest.mark.asyncio
async def test_tick_once_appends_event_on_nudge_send():
    """tick_once appends a nudge_sent event after a successful nudge send."""
    from farm_agent.confirm.watchdog import tick_once  # noqa: PLC0415

    fake_signal = FakeSignalClientWatchdog()
    stub_repo = StubConfirmRepo(
        nudge_candidates=[_make_nudge_row()],
        nudge_rowcounts=[1],
    )
    config = _make_config()
    lock = asyncio.Lock()

    await tick_once(object(), fake_signal, config, lock=lock, repo=stub_repo)

    nudge_events = [e for e in stub_repo.append_event_calls if e["event"] == "nudge_sent"]
    assert nudge_events, "Expected a nudge_sent event to be appended"


# ---------------------------------------------------------------------------
# confirm_watchdog_loop: CancelledError re-raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_watchdog_loop_reraises_cancelled_error():
    """confirm_watchdog_loop re-raises asyncio.CancelledError (not swallowed).

    Strategy: inject a tick_once that immediately raises CancelledError,
    assert the loop propagates it.
    """
    from farm_agent.confirm import watchdog as watchdog_module  # noqa: PLC0415

    cancelled_raised = []

    async def _tick_raise_cancelled(pool, signal_client, config, *, lock=None, repo=None):
        raise asyncio.CancelledError("test cancel")

    config = _make_config(interval_ms=1)  # minimal interval so loop doesn't hang
    fake_signal = FakeSignalClientWatchdog()

    # Patch tick_once temporarily
    original_tick = watchdog_module.tick_once
    watchdog_module.tick_once = _tick_raise_cancelled
    try:
        with pytest.raises(asyncio.CancelledError):
            await watchdog_module.confirm_watchdog_loop(object(), fake_signal, config)
        cancelled_raised.append(True)
    finally:
        watchdog_module.tick_once = original_tick

    assert cancelled_raised, "CancelledError should have propagated"


@pytest.mark.asyncio
async def test_confirm_watchdog_loop_continues_after_exception(caplog):
    """confirm_watchdog_loop logs WARNING on tick error and continues (never-throws)."""
    from farm_agent.confirm import watchdog as watchdog_module  # noqa: PLC0415

    call_count = 0

    async def _tick_raise_then_cancel(pool, signal_client, config, *, lock=None, repo=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated tick error")
        # After the first tick fails, cancel so we don't loop forever
        raise asyncio.CancelledError("stop loop")

    config = _make_config(interval_ms=1)
    fake_signal = FakeSignalClientWatchdog()

    original_tick = watchdog_module.tick_once
    watchdog_module.tick_once = _tick_raise_then_cancel
    try:
        with caplog.at_level(logging.WARNING, logger="farm_agent.confirm.watchdog"):
            with pytest.raises(asyncio.CancelledError):
                await watchdog_module.confirm_watchdog_loop(object(), fake_signal, config)
    finally:
        watchdog_module.tick_once = original_tick

    # First call (immediate tick) raised RuntimeError -> logged as WARNING
    # The loop continued and second call raised CancelledError -> re-raised
    assert call_count >= 2, f"Expected at least 2 tick calls, got {call_count}"
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("tick" in m.lower() or "watchdog" in m.lower() for m in warning_messages), (
        f"Expected a WARNING log for tick error, got: {warning_messages}"
    )


# ---------------------------------------------------------------------------
# boot wiring import check
# ---------------------------------------------------------------------------


def test_boot_imports_confirm_watchdog_loop():
    """boot.py must import confirm_watchdog_loop (boot wiring present)."""
    import importlib  # noqa: PLC0415
    import inspect  # noqa: PLC0415

    boot = importlib.import_module("farm_agent.boot")
    source = inspect.getsource(boot)
    assert "confirm_watchdog_loop" in source, (
        "confirm_watchdog_loop not found in boot.py source -- boot wiring missing"
    )
