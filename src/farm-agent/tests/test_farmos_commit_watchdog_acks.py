"""MUSHY-38 -- the commit watchdog must never leave a post-YES outcome silent.

The farmer says YES, dispatch replies "Got it! Your entry was recorded.", and the
actual farmOS write happens LATER in this watchdog. Before this fix the watchdog
had no signal_client at all, so all three of its terminal outcomes were silent:

  - commit success      -> mark_committed, farmer never told it landed
  - terminal commit_failed -> mark_failed, farmer still believes it was recorded
  - fidelity strain hold   -> ask_back_msg rendered, then only LOGGED

The Node original dispatches send_commit_outcome_ack on both T4 (success) and
T6 (terminal failure) -- see src/agents/alerter/src/farmos/commit-watchdog.js:134,152.

See memory feedback_no_silent_failure_after_farmer_confirm.
"""

import logging

import pytest

from tests.test_farmos_commit_watchdog import FakeCommitDb, FakeConfig, FakeRouter


class FakeSignalClient:
    """Records send() calls. Never raises."""

    def __init__(self) -> None:
        self.sends: list[dict] = []

    async def send(self, body: str, *, to=None, related_draft_id=None, intent=None, **kwargs) -> dict:
        self.sends.append({"body": body, "to": to, "related_draft_id": related_draft_id, "intent": intent})
        return {"ok": True, "timestamp": 1}


class ExplodingSignalClient:
    """send() always raises -- the ack must never unwind the commit (best-effort)."""

    async def send(self, *a, **kw):
        raise RuntimeError("signal-cli down")


def _row(draft_id: str = "draft-1", **over) -> dict:
    row = {
        "id": draft_id,
        "block_name": "BlockA",
        "draft_json": {"species_code": "KOY"},
        "commit_attempt_count": 0,
        "status": "confirmed",
        "origin": "python",
        "sender_e164": "+59899000001",
        "reply_target_kind": "dm",
        "group_id": None,
    }
    row.update(over)
    return row


@pytest.mark.asyncio
async def test_terminal_failure_tells_the_farmer():
    """CRIT: a terminal commit_failed must reach the farmer, who was told 'recorded'."""
    from farm_agent.farmos.commit_watchdog import tick_once

    db = FakeCommitDb(candidates=[_row(commit_attempt_count=99)])
    router = FakeRouter(result={"ok": False, "http_status": 422, "reason": "validation failed"})
    signal = FakeSignalClient()

    await tick_once(None, {}, FakeConfig(), db=db, router=router, csv_rows=[], signal_client=signal)

    assert [c for c in db.calls if c["fn"] == "mark_failed"], "precondition: expected terminal failure"
    assert signal.sends, "MUSHY-38: terminal commit_failed was silent to the farmer"
    ack = signal.sends[0]
    assert ack["intent"] == "commit_outcome_ack"
    assert ack["related_draft_id"] == "draft-1"
    body = ack["body"].lower()
    assert "validation failed" in body, f"failure reason must be surfaced, got: {ack['body']!r}"
    assert "—" not in ack["body"], "no em-dashes in farmer-facing copy"


@pytest.mark.asyncio
async def test_commit_success_tells_the_farmer():
    """Parity with Node T4: success dispatches an outcome ack."""
    from farm_agent.farmos.commit_watchdog import tick_once

    db = FakeCommitDb(candidates=[_row()])
    signal = FakeSignalClient()

    await tick_once(None, {}, FakeConfig(), db=db, router=FakeRouter(), csv_rows=[], signal_client=signal)

    assert [c for c in db.calls if c["fn"] == "mark_committed"], "precondition: expected success"
    assert signal.sends, "MUSHY-38: successful commit was silent"
    assert signal.sends[0]["intent"] == "commit_outcome_ack"
    assert "—" not in signal.sends[0]["body"], "no em-dashes in farmer-facing copy"


@pytest.mark.asyncio
async def test_transient_retry_stays_silent():
    """A transient failure is retried, not terminal -- must NOT pester the farmer."""
    from farm_agent.farmos.commit_watchdog import tick_once

    db = FakeCommitDb(candidates=[_row(commit_attempt_count=0)])
    router = FakeRouter(result={"ok": False, "http_status": None, "reason": "timeout"})
    signal = FakeSignalClient()

    await tick_once(None, {}, FakeConfig(), db=db, router=router, csv_rows=[], signal_client=signal)

    assert [c for c in db.calls if c["fn"] == "requeue_for_retry"], "precondition: expected requeue"
    assert signal.sends == [], (
        f"transient retry must stay silent until it goes terminal, sent: {signal.sends}"
    )


@pytest.mark.asyncio
async def test_fidelity_hold_actually_sends_the_ask_back():
    """The ask-back was rendered and then only logged -- it must reach the farmer."""
    from farm_agent.farmos.commit_watchdog import tick_once

    db = FakeCommitDb(candidates=[_row()])
    router = FakeRouter()
    signal = FakeSignalClient()
    csv_rows = [{"block_name": "BlockA", "strain_code": "POY"}]

    await tick_once(None, {}, FakeConfig(), db=db, router=router, csv_rows=csv_rows, signal_client=signal)

    assert router.calls == [], "precondition: fidelity hold must not commit"
    assert signal.sends, "MUSHY-38: fidelity ask-back was logged but never sent"
    body = signal.sends[0]["body"]
    assert "KOY" in body and "POY" in body, f"ask-back must name both strains, got: {body!r}"
    assert signal.sends[0]["intent"] == "fidelity_ask_back"


@pytest.mark.asyncio
async def test_ack_failure_never_unwinds_the_commit(caplog):
    """Best-effort: a dead signal-cli must not turn a committed draft into an exception."""
    from farm_agent.farmos.commit_watchdog import tick_once

    db = FakeCommitDb(candidates=[_row()])

    with caplog.at_level(logging.WARNING, logger="farm_agent"):
        await tick_once(
            None, {}, FakeConfig(), db=db, router=FakeRouter(), csv_rows=[],
            signal_client=ExplodingSignalClient(),
        )

    assert [c for c in db.calls if c["fn"] == "mark_committed"], (
        "commit must still be marked when the ack send blows up"
    )
    assert any("ack" in r.getMessage().lower() for r in caplog.records), (
        "a failed ack must at least be logged"
    )


@pytest.mark.asyncio
async def test_no_signal_client_still_works():
    """Back-compat: existing callers pass no signal_client; watchdog must not crash."""
    from farm_agent.farmos.commit_watchdog import tick_once

    db = FakeCommitDb(candidates=[_row()])
    await tick_once(None, {}, FakeConfig(), db=db, router=FakeRouter(), csv_rows=[])
    assert [c for c in db.calls if c["fn"] == "mark_committed"]


def test_boot_wires_signal_client_into_commit_watchdog():
    """boot.py must hand the watchdog a signal_client, or every ack above is dead code."""
    import inspect

    from farm_agent import boot

    src = inspect.getsource(boot)
    idx = src.find("commit_watchdog_loop(")
    assert idx != -1, "commit_watchdog_loop call not found in boot.py"
    call = src[idx:idx + 260]
    assert "signal_client" in call, (
        f"MUSHY-38: boot.py starts the commit watchdog without a signal_client: {call!r}"
    )
