"""D-3: a farmer's answer to the SEQ ask-back must reach handle_starting_seq_reply."""

from __future__ import annotations

import pytest


def _seq_draft():
    return {
        "id": "d1", "sender_e164": "+59891111111", "status": "awaiting_farmer",
        "reply_target_kind": "dm", "group_id": None, "source_capture_ids": ["cap1"],
        "needs_review_reason": None,
        "edit_turn_count": 0,
        "nudge_sent_at": None,
        "draft_json": {
            "type": "seeding_session", "event_date": "20260522",
            "needs_input": "starting_seq",
            "groups": [{"parent": {"value": "P1"}, "species": {"value": "KOY"},
                        "qty": {"value": 2}, "child_block_names": {"value": []}}],
        },
    }


def _plain_draft():
    return {
        "id": "d2", "sender_e164": "+59891111111", "status": "awaiting_farmer",
        "reply_target_kind": "dm", "group_id": None, "source_capture_ids": ["cap1"],
        "needs_review_reason": None,
        "edit_turn_count": 0,
        "nudge_sent_at": None,
        "draft_json": {"type": "harvest", "qty_g": 500},
    }


class FakeSignalClient:
    """Records send() calls for assertion. Never raises."""

    def __init__(self) -> None:
        self.sends: list[dict] = []

    async def send(self, body, *, to=None, related_draft_id=None, intent=None, **kwargs):
        self.sends.append({"body": body, "to": to, "related_draft_id": related_draft_id, "intent": intent})
        return {"ok": True, "timestamp": 1234567890}


class FakeConfirmRepo:
    """Minimal confirm_repo double for the standard YES/NO/EDIT path."""

    def __init__(self) -> None:
        self.confirm_calls: list[str] = []

    async def confirm_draft(self, pool, draft_id: str) -> dict:
        self.confirm_calls.append(draft_id)
        return {"ok": True, "rowcount": 1}

    async def discard_draft(self, pool, draft_id: str) -> dict:
        return {"ok": True, "rowcount": 1}

    async def expire_draft(self, pool, draft_id: str, reason: str) -> dict:
        return {"ok": True, "rowcount": 1}

    async def mark_nudge_sent(self, pool, draft_id: str) -> dict:
        return {"ok": True, "rowcount": 1}

    async def bump_edit_turn(self, pool, draft_id: str) -> dict:
        return {"ok": True, "edit_turn_count": 1, "rowcount": 1}

    async def update_draft_after_edit(self, pool, draft_id: str, fields: dict) -> dict:
        return {"ok": True, "rowcount": 1}

    async def append_event_via_pool(self, pool, draft_id: str, event: str, payload) -> dict:
        return {"ok": True, "seq": 1}


def _make_config():
    from types import SimpleNamespace  # noqa: PLC0415
    return SimpleNamespace(max_edit_turns=3, STRAIN_CODES=None)


@pytest.mark.asyncio
async def test_numeric_reply_on_seq_draft_routes_to_seq_handler(monkeypatch):
    from farm_agent.confirm.dispatch import route_confirm_reply  # noqa: PLC0415

    called = {}

    async def fake_handler(**kwargs):
        called.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        "farm_agent.confirm.dispatch.handle_starting_seq_reply", fake_handler
    )

    fake_signal = FakeSignalClient()
    fake_repo = FakeConfirmRepo()
    config = _make_config()
    pool = object()
    outbound_dispatcher = {"dispatch": None}

    result = await route_confirm_reply(
        pool, fake_signal, config, _seq_draft(), "4",
        repo=fake_repo, outbound_dispatcher=outbound_dispatcher,
    )

    assert result == {"ok": True}
    assert called["reply_text"] == "4"
    assert called["draft_id"] == "d1"
    assert called["pool"] is pool
    assert called["outbound_dispatcher"] is outbound_dispatcher
    # Must NOT have fallen into the standard YES/NO/EDIT confirm path.
    assert not fake_repo.confirm_calls, "SEQ reply must not be treated as a confirmation"
    assert not fake_signal.sends, "route_confirm_reply must not send directly for a SEQ reply"


@pytest.mark.asyncio
async def test_yes_on_seq_draft_routes_to_seq_handler_not_confirm(monkeypatch):
    """YES here means 'use the default SEQ', not 'commit this draft'."""
    from farm_agent.confirm.dispatch import route_confirm_reply  # noqa: PLC0415

    called = {}

    async def fake_handler(**kwargs):
        called.update(kwargs)
        return {"ok": True, "start_seq": 4}

    monkeypatch.setattr(
        "farm_agent.confirm.dispatch.handle_starting_seq_reply", fake_handler
    )

    fake_signal = FakeSignalClient()
    fake_repo = FakeConfirmRepo()
    config = _make_config()
    pool = object()

    result = await route_confirm_reply(
        pool, fake_signal, config, _seq_draft(), "YES",
        repo=fake_repo, outbound_dispatcher={"dispatch": None},
    )

    assert result == {"ok": True, "start_seq": 4}
    assert called["reply_text"] == "YES"
    # The SEQ handler ran, not confirm_draft.
    assert not fake_repo.confirm_calls, "YES on a SEQ draft must not confirm_draft"
    assert not fake_signal.sends, "route_confirm_reply must not send an ack directly for a SEQ reply"


@pytest.mark.asyncio
async def test_yes_on_a_plain_draft_still_confirms():
    """Regression guard: the intercept must not swallow ordinary confirmations."""
    from farm_agent.confirm.dispatch import route_confirm_reply  # noqa: PLC0415

    fake_signal = FakeSignalClient()
    fake_repo = FakeConfirmRepo()
    config = _make_config()
    pool = object()

    result = await route_confirm_reply(
        pool, fake_signal, config, _plain_draft(), "yes",
        repo=fake_repo, outbound_dispatcher={"dispatch": None},
    )

    assert fake_repo.confirm_calls == ["d2"]
    assert result is not None
    assert result.get("action") == "confirmed"
    assert fake_signal.sends, "confirm ack must be sent for an ordinary YES"


@pytest.mark.asyncio
async def test_seq_draft_whose_needs_input_is_cleared_falls_through_to_confirm():
    """After the SEQ is filled, the draft is an ordinary awaiting_farmer draft."""
    from farm_agent.confirm.dispatch import route_confirm_reply  # noqa: PLC0415

    filled_draft = _seq_draft()
    filled_draft["draft_json"] = {
        **filled_draft["draft_json"],
    }
    filled_draft["draft_json"].pop("needs_input", None)

    fake_signal = FakeSignalClient()
    fake_repo = FakeConfirmRepo()
    config = _make_config()
    pool = object()

    result = await route_confirm_reply(
        pool, fake_signal, config, filled_draft, "yes",
        repo=fake_repo, outbound_dispatcher={"dispatch": None},
    )

    assert fake_repo.confirm_calls == ["d1"]
    assert result is not None
    assert result.get("action") == "confirmed"
