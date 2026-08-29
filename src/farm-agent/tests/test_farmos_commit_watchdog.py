"""
tests/test_farmos_commit_watchdog.py -- Tests for commit_watchdog.py (62-11, Task 1 TDD).

Port behavioral assertions from commit-watchdog.js (Phase 40 D-07/D-07a/D-07b).

Tests are DB-independent (no pool connection needed): all DB / router / fidelity
calls are replaced with fakes injected via tick_once's keyword-only parameters.

Coverage:
  - _is_transient classifier (all branches)
  - tick_once fidelity hold: strain_mismatch holds draft as fidelity_cross_check_unverified,
    commit_router.commit is NEVER called (T-62-30 / D-06)
  - tick_once happy path: clean fidelity + ok result -> mark_committed
  - tick_once transient failure: result ok=False, http_status None -> requeue_for_retry
  - tick_once terminal failure: attempts >= retry_max -> mark_failed
  - tick_once race lost (acquire rowcount=0): skip without calling router
  - tick_once per-row exception: WARNING logged, loop continues to next row
  - commit_watchdog_loop: ticks immediately on boot
  - commit_watchdog_loop: re-raises CancelledError (T-62-31)
  - commit_watchdog_loop: tick Exception logs WARNING + continues (T-62-31)
"""
from __future__ import annotations

import asyncio
import logging

import pytest


# ---------------------------------------------------------------------------
# Fake DB module (injectable via db= kwarg)
# ---------------------------------------------------------------------------

class FakeCommitDb:
    """Records calls to commit_db functions; returns controllable results."""

    def __init__(
        self,
        candidates: list | None = None,
        acquire_rowcount: int = 1,
        acquire_ok: bool = True,
    ) -> None:
        self.candidates = candidates or []
        self.acquire_rowcount = acquire_rowcount
        self.acquire_ok = acquire_ok
        self.calls: list[dict] = []

    def _rec(self, fn: str, **kw) -> None:
        self.calls.append({"fn": fn, **kw})

    async def release_stale_locks(self, pool, stale_min: int = 15) -> dict:
        self._rec("release_stale_locks")
        return {"ok": True, "rowcount": 0, "released_ids": []}

    async def find_confirmed_candidates(self, pool, batch_cap: int = 10) -> list:
        self._rec("find_confirmed_candidates", batch_cap=batch_cap)
        return list(self.candidates)

    async def acquire_commit_lock(self, pool, draft_id: str) -> dict:
        self._rec("acquire_commit_lock", draft_id=draft_id)
        return {"ok": self.acquire_ok, "rowcount": self.acquire_rowcount}

    async def mark_committed(self, pool, draft_id: str, farmos_response: dict | None) -> dict:
        self._rec("mark_committed", draft_id=draft_id)
        return {"ok": True, "rowcount": 1}

    async def mark_failed(
        self, pool, draft_id: str, reason: str | None, transport: bool = False
    ) -> dict:
        # MUSHY-75: transport is recorded so the recovery pass can tell a dead
        # server apart from a bad entry.
        self._rec("mark_failed", draft_id=draft_id, reason=reason, transport=transport)
        return {"ok": True, "rowcount": 1}

    async def find_transport_parked(self, pool) -> list:
        self._rec("find_transport_parked")
        return list(getattr(self, "parked", []))

    async def requeue_parked(self, pool, draft_id: str) -> dict:
        self._rec("requeue_parked", draft_id=draft_id)
        return {"ok": True, "rowcount": 1}

    async def requeue_for_retry(self, pool, draft_id: str) -> dict:
        self._rec("requeue_for_retry", draft_id=draft_id)
        return {"ok": True, "rowcount": 1}

    async def hold_for_fidelity(self, pool, draft_id: str) -> dict:
        self._rec("hold_for_fidelity", draft_id=draft_id)
        return {"ok": True, "rowcount": 1}


# ---------------------------------------------------------------------------
# Fake router module (injectable via router= kwarg)
# ---------------------------------------------------------------------------

class FakeRouter:
    """Records commit calls; returns a controllable result."""

    def __init__(self, result: dict | None = None) -> None:
        self.result = result or {"ok": True, "asset_ids": [], "log_ids": [], "file_ids": [],
                                  "attachments_failed": [], "latency_ms": 1, "reason": None}
        self.calls: list[dict] = []

    async def commit(self, client, draft, ctx=None) -> dict:
        self.calls.append({"draft": draft, "ctx": ctx})
        return self.result


# ---------------------------------------------------------------------------
# Fake config
# ---------------------------------------------------------------------------

class FakeConfig:
    commit_watchdog_interval_ms = 30000
    commit_watchdog_batch_cap = 10
    commit_retry_max = 3
    fidelity_csv_path = ""


# ---------------------------------------------------------------------------
# _is_transient classifier tests
# ---------------------------------------------------------------------------

def test_is_transient_none_result():
    from farm_agent.farmos.commit_watchdog import _is_transient
    assert _is_transient(None) is True


def test_is_transient_http_status_none_with_a_transport_reason():
    """MUSHY-126 rewrote this case. A missing status used to be transient on its
    own, which swept up every handler that failed its own pre-flight check and
    told the farmer their correct entry could not be reached. Now the reason has
    to say it is the transport."""
    from farm_agent.farmos.commit_watchdog import _is_transient
    assert _is_transient({"http_status": None, "reason": "http_network"}) is True


def test_is_transient_http_status_none_with_a_local_reason():
    from farm_agent.farmos.commit_watchdog import _is_transient
    assert _is_transient({"http_status": None, "reason": "no_target_asset_for_activity"}) is False


def test_is_transient_http_status_500():
    from farm_agent.farmos.commit_watchdog import _is_transient
    assert _is_transient({"http_status": 500, "reason": "internal_error"}) is True


def test_is_transient_http_status_400_non_matching_reason():
    from farm_agent.farmos.commit_watchdog import _is_transient
    assert _is_transient({"http_status": 400, "reason": "validation_error"}) is False


def test_is_transient_reason_timeout():
    from farm_agent.farmos.commit_watchdog import _is_transient
    assert _is_transient({"http_status": 400, "reason": "timeout"}) is True


def test_is_transient_reason_econnreset():
    from farm_agent.farmos.commit_watchdog import _is_transient
    assert _is_transient({"http_status": 400, "reason": "ECONNRESET"}) is True


def test_is_transient_reason_abort():
    from farm_agent.farmos.commit_watchdog import _is_transient
    assert _is_transient({"http_status": 400, "reason": "abort"}) is True


def test_is_transient_empty_dict():
    from farm_agent.farmos.commit_watchdog import _is_transient
    # No http_status key -> .get returns None -> transient
    assert _is_transient({}) is True


# ---------------------------------------------------------------------------
# tick_once: fidelity strain_mismatch hold (T-62-30 / D-06)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_fidelity_strain_mismatch_never_calls_router(caplog):
    """A draft failing fidelity is held; commit_router.commit NEVER called."""
    from farm_agent.farmos.commit_watchdog import tick_once

    row = {
        "id": "draft-1",
        "block_name": "BlockA",
        "draft_json": {"species_code": "KOY"},
        "commit_attempt_count": 0,
        "status": "confirmed",
        "origin": "python",
    }
    # CSV says BlockA = POY; draft says KOY -> mismatch
    csv_rows = [{"block_name": "BlockA", "strain_code": "POY"}]

    db = FakeCommitDb(candidates=[row])
    router = FakeRouter()
    config = FakeConfig()

    with caplog.at_level(logging.WARNING, logger="farm_agent"):
        await tick_once(None, {}, config, db=db, router=router, csv_rows=csv_rows)

    # router.commit must NOT be called
    assert router.calls == [], "commit_router.commit was called but should NOT have been"

    # hold_for_fidelity must be called
    holds = [c for c in db.calls if c["fn"] == "hold_for_fidelity"]
    assert len(holds) == 1, "hold_for_fidelity was not called"
    assert holds[0]["draft_id"] == "draft-1"

    # mark_committed / requeue / mark_failed must NOT be called
    terminal_calls = [c for c in db.calls if c["fn"] in ("mark_committed", "requeue_for_retry", "mark_failed")]
    assert terminal_calls == [], f"Unexpected DB call: {terminal_calls}"

    # Fidelity warning logged
    assert any("fidelity" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_tick_fidelity_pass_block_not_in_csv_commits():
    """Block absent from CSV -> pass-through (D-07); commit proceeds normally."""
    from farm_agent.farmos.commit_watchdog import tick_once

    row = {
        "id": "draft-2",
        "block_name": "UnknownBlock",
        "draft_json": {"species_code": "KOY"},
        "commit_attempt_count": 0,
    }
    csv_rows = [{"block_name": "BlockA", "strain_code": "KOY"}]  # no entry for UnknownBlock

    db = FakeCommitDb(candidates=[row])
    router = FakeRouter(result={"ok": True, "asset_ids": ["a1"], "log_ids": ["l1"],
                                 "file_ids": [], "attachments_failed": [], "latency_ms": 5, "reason": None})
    config = FakeConfig()

    await tick_once(None, {}, config, db=db, router=router, csv_rows=csv_rows)

    # router.commit called once
    assert len(router.calls) == 1

    # mark_committed called
    committed = [c for c in db.calls if c["fn"] == "mark_committed"]
    assert len(committed) == 1
    assert committed[0]["draft_id"] == "draft-2"


# ---------------------------------------------------------------------------
# tick_once: happy path (ok result -> mark_committed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_ok_result_mark_committed():
    """Clean row (fidelity pass) + ok router result -> mark_committed called once."""
    from farm_agent.farmos.commit_watchdog import tick_once

    row = {
        "id": "draft-3",
        "block_name": "",
        "draft_json": {},
        "commit_attempt_count": 0,
    }
    db = FakeCommitDb(candidates=[row])
    router = FakeRouter(result={"ok": True, "asset_ids": ["a1"], "log_ids": [], "file_ids": [],
                                 "attachments_failed": [], "latency_ms": 2, "reason": None})
    config = FakeConfig()

    await tick_once(None, {}, config, db=db, router=router, csv_rows=[])

    assert len(router.calls) == 1
    committed = [c for c in db.calls if c["fn"] == "mark_committed"]
    assert len(committed) == 1 and committed[0]["draft_id"] == "draft-3"

    # No requeue or mark_failed
    assert not [c for c in db.calls if c["fn"] in ("requeue_for_retry", "mark_failed")]


# ---------------------------------------------------------------------------
# tick_once: transient failure -> requeue_for_retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_transient_failure_requeues():
    """Transient failure (http_status None) + attempt < retry_max -> requeue_for_retry."""
    from farm_agent.farmos.commit_watchdog import tick_once

    row = {
        "id": "draft-4",
        "block_name": "",
        "draft_json": {},
        "commit_attempt_count": 0,  # first attempt (pre-lock value)
    }
    db = FakeCommitDb(candidates=[row])
    # result has no http_status (None) -> transient; attempt=0 < 3 -> requeue
    router = FakeRouter(result={"ok": False, "asset_ids": [], "log_ids": [], "file_ids": [],
                                 "attachments_failed": [], "latency_ms": 1, "reason": "network_error"})
    config = FakeConfig()  # retry_max=3

    await tick_once(None, {}, config, db=db, router=router, csv_rows=[])

    requeued = [c for c in db.calls if c["fn"] == "requeue_for_retry"]
    assert len(requeued) == 1 and requeued[0]["draft_id"] == "draft-4"
    assert not [c for c in db.calls if c["fn"] in ("mark_committed", "mark_failed")]


# ---------------------------------------------------------------------------
# tick_once: terminal failure (attempts >= retry_max) -> mark_failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_terminal_failure_marks_failed():
    """Non-transient failure OR attempts >= retry_max -> mark_failed."""
    from farm_agent.farmos.commit_watchdog import tick_once

    # attempt_count=3 >= retry_max=3, even with transient result -> mark_failed
    row = {
        "id": "draft-5",
        "block_name": "",
        "draft_json": {},
        "commit_attempt_count": 3,  # already at max
    }
    db = FakeCommitDb(candidates=[row])
    router = FakeRouter(result={"ok": False, "asset_ids": [], "log_ids": [], "file_ids": [],
                                 "attachments_failed": [], "latency_ms": 1, "reason": "network_error"})
    config = FakeConfig()  # retry_max=3

    await tick_once(None, {}, config, db=db, router=router, csv_rows=[])

    failed = [c for c in db.calls if c["fn"] == "mark_failed"]
    assert len(failed) == 1 and failed[0]["draft_id"] == "draft-5"
    assert not [c for c in db.calls if c["fn"] == "requeue_for_retry"]


@pytest.mark.asyncio
async def test_tick_terminal_failure_non_transient_marks_failed():
    """Non-transient result (http_status=400, non-matching reason) -> mark_failed on first attempt."""
    from farm_agent.farmos.commit_watchdog import tick_once

    row = {
        "id": "draft-6",
        "block_name": "",
        "draft_json": {},
        "commit_attempt_count": 0,
    }
    db = FakeCommitDb(candidates=[row])
    # http_status=400 and non-transient reason -> NOT transient -> mark_failed
    router = FakeRouter(result={"ok": False, "http_status": 400, "asset_ids": [], "log_ids": [],
                                 "file_ids": [], "attachments_failed": [], "latency_ms": 1,
                                 "reason": "validation_error"})
    config = FakeConfig()

    await tick_once(None, {}, config, db=db, router=router, csv_rows=[])

    failed = [c for c in db.calls if c["fn"] == "mark_failed"]
    assert len(failed) == 1 and failed[0]["draft_id"] == "draft-6"
    assert not [c for c in db.calls if c["fn"] == "requeue_for_retry"]


# ---------------------------------------------------------------------------
# tick_once: acquire lock race lost (rowcount=0) -> skip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_acquire_race_lost_skips():
    """rowcount=0 on acquire_commit_lock -> skip; no router call."""
    from farm_agent.farmos.commit_watchdog import tick_once

    row = {"id": "draft-7", "block_name": "", "draft_json": {}, "commit_attempt_count": 0}
    db = FakeCommitDb(candidates=[row], acquire_rowcount=0)
    router = FakeRouter()
    config = FakeConfig()

    await tick_once(None, {}, config, db=db, router=router, csv_rows=[])

    assert router.calls == []
    assert not [c for c in db.calls if c["fn"] in ("mark_committed", "requeue_for_retry", "mark_failed")]


# ---------------------------------------------------------------------------
# tick_once: per-row exception -> WARNING logged, loop continues
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_per_row_exception_logs_warning_continues(caplog):
    """A per-row exception logs WARNING + continues to next row (T-62-31 never-throws)."""
    from farm_agent.farmos.commit_watchdog import tick_once

    row1 = {"id": "draft-bad", "block_name": "", "draft_json": {}, "commit_attempt_count": 0}
    row2 = {"id": "draft-ok", "block_name": "", "draft_json": {}, "commit_attempt_count": 0}

    class BrokenRouter:
        calls: list = []

        async def commit(self, client, draft, ctx=None):
            if draft.get("id") == "draft-bad":
                raise RuntimeError("simulated per-row failure")
            self.calls.append(draft)
            return {"ok": True, "asset_ids": [], "log_ids": [], "file_ids": [],
                    "attachments_failed": [], "latency_ms": 1, "reason": None}

    db = FakeCommitDb(candidates=[row1, row2])
    router = BrokenRouter()
    config = FakeConfig()

    with caplog.at_level(logging.WARNING, logger="farm_agent"):
        await tick_once(None, {}, config, db=db, router=router, csv_rows=[])

    # WARNING was logged for the bad row
    assert any("draft-bad" in r.getMessage() for r in caplog.records)

    # The second row was still processed (mark_committed called)
    committed = [c for c in db.calls if c["fn"] == "mark_committed"]
    assert any(c["draft_id"] == "draft-ok" for c in committed), (
        "Second row was not committed after first row threw"
    )


# ---------------------------------------------------------------------------
# tick_once: find_confirmed_candidates is the source (origin='python' guard)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_uses_find_confirmed_candidates_as_source():
    """tick_once calls find_confirmed_candidates to get rows (origin='python' guard is in DB)."""
    from farm_agent.farmos.commit_watchdog import tick_once

    db = FakeCommitDb(candidates=[])  # empty
    router = FakeRouter()
    config = FakeConfig()

    await tick_once(None, {}, config, db=db, router=router, csv_rows=[])

    find_calls = [c for c in db.calls if c["fn"] == "find_confirmed_candidates"]
    assert len(find_calls) == 1, "find_confirmed_candidates was not called"
    assert router.calls == [], "router should not be called when no candidates"


# ---------------------------------------------------------------------------
# commit_watchdog_loop: ticks immediately on boot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_ticks_immediately():
    """commit_watchdog_loop performs an immediate tick before any sleep."""
    from farm_agent.farmos.commit_watchdog import commit_watchdog_loop

    tick_count = 0

    async def fake_tick_once(*args, **kwargs):
        nonlocal tick_count
        tick_count += 1
        # After first tick, cancel the loop
        raise asyncio.CancelledError("stop after first tick")

    import farm_agent.farmos.commit_watchdog as cwmod
    original = cwmod.tick_once

    cwmod.tick_once = fake_tick_once  # type: ignore[attr-defined]
    try:
        config = FakeConfig()
        task = asyncio.create_task(commit_watchdog_loop(None, {}, config))
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    finally:
        cwmod.tick_once = original  # type: ignore[attr-defined]

    assert tick_count >= 1, "Loop did not tick immediately on boot"


# ---------------------------------------------------------------------------
# commit_watchdog_loop: re-raises CancelledError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_reraises_cancelled_error():
    """CancelledError propagates out of commit_watchdog_loop cleanly."""
    from farm_agent.farmos.commit_watchdog import commit_watchdog_loop

    config = FakeConfig()
    config.commit_watchdog_interval_ms = 100  # type: ignore[attr-defined]

    db = FakeCommitDb(candidates=[])
    router = FakeRouter()

    import farm_agent.farmos.commit_watchdog as cwmod
    original = cwmod.tick_once

    async def noop_tick(*args, **kwargs):
        pass

    cwmod.tick_once = noop_tick  # type: ignore[attr-defined]
    try:
        task = asyncio.create_task(commit_watchdog_loop(None, {}, config))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        cwmod.tick_once = original  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# commit_watchdog_loop: tick Exception logs WARNING + continues (T-62-31)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_tick_exception_logs_warning_continues(caplog):
    """A tick Exception is caught, WARNING is logged, and the loop continues."""
    from farm_agent.farmos.commit_watchdog import commit_watchdog_loop

    call_count = 0

    async def failing_tick(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Initial tick: raise (simulates tick error on boot)
            raise RuntimeError("simulated initial tick failure")
        # Second call: cancel the loop
        raise asyncio.CancelledError("stop after second tick")

    import farm_agent.farmos.commit_watchdog as cwmod
    original = cwmod.tick_once

    cwmod.tick_once = failing_tick  # type: ignore[attr-defined]
    try:
        config = FakeConfig()
        config.commit_watchdog_interval_ms = 50  # type: ignore[attr-defined]

        with caplog.at_level(logging.WARNING, logger="farm_agent"):
            task = asyncio.create_task(commit_watchdog_loop(None, {}, config))
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
    finally:
        cwmod.tick_once = original  # type: ignore[attr-defined]

    # WARNING was logged for the failed initial tick
    assert any(
        "initial tick" in r.getMessage().lower() or "tick" in r.getMessage().lower()
        for r in caplog.records
        if r.levelno >= logging.WARNING
    ), f"Expected WARNING not found in: {[r.getMessage() for r in caplog.records]}"



# ---------------------------------------------------------------------------
# tick_once: the commit ctx (MUSHY-131)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_passes_a_ctx_with_capture_paths():
    """The watchdog called router.commit(client, row) with no ctx at all, so
    every handler's photo upload was gated on a capturePathsFor that nothing
    ever provided. No photo the farmer sent reached farmOS, and because "no
    paths" is not an error, nothing was ever logged about it.
    """
    from farm_agent.farmos.commit_watchdog import tick_once

    row = {"id": "draft-ctx", "block_name": "", "draft_json": {}, "commit_attempt_count": 0}
    db = FakeCommitDb(candidates=[row])
    router = FakeRouter()

    await tick_once(None, {}, FakeConfig(), db=db, router=router, csv_rows=[])

    assert len(router.calls) == 1
    ctx = router.calls[0]["ctx"]
    assert ctx is not None, "ctx=None is the bug; the upload can never run"
    assert callable(ctx.get("capturePathsFor")), (
        "handlers gate the upload on exactly this key being callable"
    )


@pytest.mark.asyncio
async def test_capture_path_lookup_failure_does_not_break_the_commit():
    """A dead capture DB must cost the photo, never the log."""
    from farm_agent.farmos.commit_watchdog import tick_once

    class ExplodingPool:
        def connection(self):
            raise RuntimeError("capture db down")

    row = {"id": "draft-ctx2", "block_name": "", "draft_json": {}, "commit_attempt_count": 0}
    db = FakeCommitDb(candidates=[row])
    router = FakeRouter()

    await tick_once(ExplodingPool(), {}, FakeConfig(), db=db, router=router, csv_rows=[])

    paths = await router.calls[0]["ctx"]["capturePathsFor"](["cap-1"])
    assert paths == [], "a failed lookup degrades to no photos, not an exception"
