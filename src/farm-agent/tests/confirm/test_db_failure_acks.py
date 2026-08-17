"""MUSHY-40 -- DB failure during a farmer YES/NO must never send a false ack.

confirm_draft / discard_draft NEVER raise (T-61-05); on a DB error they return
{"ok": False, "reason": ...} with NO "rowcount" key. The dispatcher used to
branch on `res.get("rowcount") == 1` alone, so a DB failure fell into the
rowcount==0 arm:

  - YES -> "Already recorded."  (a FALSE ack; nothing was written)
  - NO  -> silence, then a confusing expiry message later

Both violate the project's hard rule: no silent failure after a farmer YES.
See memory feedback_no_silent_failure_after_farmer_confirm.
"""

import pytest

from tests.confirm.test_strain_ask_back import (
    FakeSignalClient,
    _make_config,
    _make_standard_draft_row,
)


class FakeConfirmRepoDbFailure:
    """Repo whose confirm/discard fail the way confirm_repo fails: ok=False, no rowcount."""

    def __init__(self) -> None:
        self.confirm_calls: list[str] = []
        self.discard_calls: list[str] = []
        self.events: list[str] = []

    async def confirm_draft(self, pool, draft_id: str) -> dict:
        self.confirm_calls.append(draft_id)
        return {"ok": False, "reason": "connection pool exhausted"}

    async def discard_draft(self, pool, draft_id: str) -> dict:
        self.discard_calls.append(draft_id)
        return {"ok": False, "reason": "connection pool exhausted"}

    async def expire_draft(self, pool, draft_id: str, reason: str) -> dict:
        return {"ok": True, "rowcount": 1}

    async def mark_nudge_sent(self, pool, draft_id: str) -> dict:
        return {"ok": True, "rowcount": 1}

    async def bump_edit_turn(self, pool, draft_id: str) -> dict:
        return {"ok": True, "edit_turn_count": 1, "rowcount": 1}

    async def update_draft_after_edit(self, pool, draft_id: str, fields: dict) -> dict:
        return {"ok": True, "rowcount": 1}

    async def append_event_via_pool(self, pool, draft_id: str, event: str, payload) -> dict:
        self.events.append(event)
        return {"ok": True, "seq": 1}


@pytest.mark.asyncio
async def test_yes_on_db_failure_never_claims_success():
    """YES + DB failure must NOT send 'Already recorded.' -- nothing was saved."""
    from farm_agent.confirm.dispatch import route_confirm_reply

    fake_signal = FakeSignalClient()
    fake_repo = FakeConfirmRepoDbFailure()

    result = await route_confirm_reply(
        object(), fake_signal, _make_config(), _make_standard_draft_row(), "yes", repo=fake_repo
    )

    bodies = " ".join(s["body"].lower() for s in fake_signal.sends)
    assert "already recorded" not in bodies, (
        f"MUSHY-40: DB failure must not claim the entry is saved. Sent: {bodies!r}"
    )
    assert "recorded." not in bodies, (
        f"MUSHY-40: no success-shaped ack on DB failure. Sent: {bodies!r}"
    )
    # no-silent-failure: the farmer MUST hear something
    assert fake_signal.sends, "MUSHY-40: farmer got total silence after YES on DB failure"
    assert result is not None
    assert result.get("action") == "confirm_failed"
    assert result.get("ok") is False


@pytest.mark.asyncio
async def test_yes_on_db_failure_emits_no_commit_trigger():
    """A failed confirm must not emit the commit-trigger marker (T-61-12)."""
    from farm_agent.confirm.dispatch import route_confirm_reply

    fake_repo = FakeConfirmRepoDbFailure()
    await route_confirm_reply(
        object(), FakeSignalClient(), _make_config(), _make_standard_draft_row(), "yes", repo=fake_repo
    )
    assert "commit_trigger" not in fake_repo.events, (
        "MUSHY-40: commit_trigger must only be emitted on a real rowcount==1 confirm"
    )


@pytest.mark.asyncio
async def test_no_on_db_failure_tells_the_farmer():
    """NO + DB failure must not be silent -- silence lets the draft expire confusingly."""
    from farm_agent.confirm.dispatch import route_confirm_reply

    fake_signal = FakeSignalClient()
    fake_repo = FakeConfirmRepoDbFailure()

    result = await route_confirm_reply(
        object(), fake_signal, _make_config(), _make_standard_draft_row(), "no", repo=fake_repo
    )

    assert fake_signal.sends, "MUSHY-40: farmer got total silence after NO on DB failure"
    bodies = " ".join(s["body"].lower() for s in fake_signal.sends)
    assert "discarded" not in bodies, (
        f"MUSHY-40: must not claim the draft was discarded when the write failed. Sent: {bodies!r}"
    )
    assert result is not None
    assert result.get("action") == "discard_failed"
    assert result.get("ok") is False


@pytest.mark.asyncio
async def test_rowcount_zero_still_sends_idempotent_ack():
    """Guard: the genuine race-lost case (ok=True, rowcount=0) keeps its idempotent ack."""
    from farm_agent.confirm.dispatch import route_confirm_reply

    class RaceLostRepo(FakeConfirmRepoDbFailure):
        async def confirm_draft(self, pool, draft_id: str) -> dict:
            self.confirm_calls.append(draft_id)
            return {"ok": True, "rowcount": 0}

    fake_signal = FakeSignalClient()
    result = await route_confirm_reply(
        object(), fake_signal, _make_config(), _make_standard_draft_row(), "yes", repo=RaceLostRepo()
    )

    acks = [s for s in fake_signal.sends if s.get("intent") == "confirm_ack_idempotent"]
    assert acks, "race-lost confirm must still send the idempotent ack"
    assert result.get("action") == "confirmed"
