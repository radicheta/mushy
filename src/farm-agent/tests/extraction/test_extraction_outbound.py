"""Extraction outbound dispatcher: routing, trinity-skip, unknown tags."""

import pytest

from farm_agent.extraction import preview_builder
from farm_agent.extraction.outbound import create_outbound_dispatcher


class FakeSignalClient:
    def __init__(self):
        self.sent = []

    async def send(self, body, **kwargs):
        self.sent.append((body, kwargs))
        return {"ok": True}


def _dispatcher(client, operator="+59890000000"):
    return create_outbound_dispatcher(
        signal_client=client, config=object(), preview_builder=preview_builder,
        operator_recipient=operator,
    )["dispatch"]


async def test_ask_back_sends_preview_to_dm():
    c = FakeSignalClient()
    await _dispatcher(c)("send_ask_back", {
        "id": "abc123", "sender_e164": "+59891111111",
        "farmer_facing_preview": "How many grams?",
        "reply_target_kind": "dm", "source_capture_ids": ["cap1"],
    })
    body, kw = c.sent[0]
    assert body == "How many grams?"
    assert kw["to"] == "+59891111111"
    assert kw["related_draft_id"] == "abc123"
    assert kw["related_capture_id"] == "cap1"


async def test_ask_back_routes_to_group_when_group_kind():
    c = FakeSignalClient()
    await _dispatcher(c)("send_ask_back", {
        "id": "abc123", "sender_e164": "+59891111111", "farmer_facing_preview": "q",
        "reply_target_kind": "group", "group_id": "g1", "source_capture_ids": [],
    })
    _, kw = c.sent[0]
    # SignalClient.send resolves a group target from {"groupId": ...} -- camelCase,
    # verified at farm_agent/signal_io/client.py:220. A snake_case key raises
    # ValueError("invalid send target").
    assert kw["to"] == {"groupId": "g1"}


async def test_ask_back_group_kind_without_group_id_has_no_target():
    c = FakeSignalClient()
    res = await _dispatcher(c)("send_ask_back", {
        "id": "abc", "sender_e164": "+5989", "farmer_facing_preview": "q",
        "reply_target_kind": "group", "group_id": None, "source_capture_ids": [],
    })
    assert res == {"ok": False, "reason": "no_target"}
    assert c.sent == []


async def test_needs_review_ping_skipped_when_operator_is_sender():
    c = FakeSignalClient()
    res = await _dispatcher(c, operator="+59891111111")("send_needs_review_ping", {
        "id": "abc", "sender_e164": "+59891111111", "needs_review_reason": "askback_cap",
    })
    assert res["ok"] is True
    assert res["skipped"] == "trinity"
    assert c.sent == []


async def test_needs_review_ping_no_target_when_operator_unset():
    c = FakeSignalClient()
    res = await _dispatcher(c, operator=None)("send_needs_review_ping", {"id": "a", "sender_e164": "+1"})
    assert res == {"ok": False, "reason": "no_target"}


async def test_batch_summary_counts_clean_and_needs_review():
    c = FakeSignalClient()
    await _dispatcher(c)("send_batch_review_summary", {
        "sender_e164": "+59891111111",
        "draftIds": [
            {"id": "a" * 20, "status": "needs_review"},
            {"id": "b" * 20, "status": "needs_review"},
            {"id": "c" * 20, "status": "awaiting_farmer"},
        ],
    })
    body, _ = c.sent[0]
    assert "3 drafts" in body
    assert "1 clean" in body
    assert "2 need review" in body
    assert "Don Santiago" in body


@pytest.mark.parametrize("tag", ["mark_expired", "noop"])
async def test_no_send_tags(tag):
    c = FakeSignalClient()
    res = await _dispatcher(c)(tag, {})
    assert res == {"ok": True, "noop": True}
    assert c.sent == []


async def test_confirm_prompt_is_sent_to_the_farmer():
    """D-1: the whole point. A clean draft must reach the farmer."""
    c = FakeSignalClient()
    await _dispatcher(c)("send_confirm_prompt", {
        "id": "abc123", "sender_e164": "+59891111111",
        "farmer_facing_preview": "harvest 500 g\n\nReply YES to commit, NO to discard, "
                                 "EDIT <text> to amend.",
        "reply_target_kind": "dm", "source_capture_ids": ["cap1"],
    })
    body, kw = c.sent[0]
    assert "Reply YES to commit" in body
    assert kw["to"] == "+59891111111"
    assert kw["related_draft_id"] == "abc123"


async def test_starting_seq_askback_is_sent_to_the_farmer():
    """MUSHY-76 Task 7: the SEQ ask-back must reach the farmer, DM route."""
    c = FakeSignalClient()
    await _dispatcher(c)("send_starting_seq_askback", {
        "id": "abc123", "sender_e164": "+59891111111",
        "farmer_facing_preview": "May 22 inoc, 5 blocks. What block number should I start at?",
        "reply_target_kind": "dm", "source_capture_ids": ["cap1"],
    })
    body, kw = c.sent[0]
    assert body == "May 22 inoc, 5 blocks. What block number should I start at?"
    assert kw["to"] == "+59891111111"
    assert kw["related_draft_id"] == "abc123"
    assert kw["related_capture_id"] == "cap1"


async def test_seeding_session_filled_preview_is_sent_to_the_farmer():
    """MUSHY-76 Task 7: the group-by-parent table after SEQ is resolved."""
    c = FakeSignalClient()
    await _dispatcher(c)("send_seeding_session_filled_preview", {
        "id": "abc123", "sender_e164": "+59891111111",
        "farmer_facing_preview": "260522_KOY_4, 260522_KOY_5\n\nReply YES to commit.",
        "reply_target_kind": "dm", "source_capture_ids": ["cap1"],
    })
    body, kw = c.sent[0]
    assert "260522_KOY_4" in body
    assert kw["to"] == "+59891111111"
    assert kw["related_draft_id"] == "abc123"


async def test_handoff_to_phase_39_is_now_unknown():
    c = FakeSignalClient()
    res = await _dispatcher(c)("handoff_to_phase_39", {})
    assert res == {"ok": False, "reason": "unknown_side_effect"}


async def test_unknown_tag():
    c = FakeSignalClient()
    res = await _dispatcher(c)("send_nukes", {})
    assert res == {"ok": False, "reason": "unknown_side_effect"}


async def test_dispatch_never_raises_when_send_throws():
    class Boom:
        async def send(self, body, **kw):
            raise RuntimeError("signal down")

    res = await _dispatcher(Boom())("send_ask_back", {
        "id": "a", "sender_e164": "+1", "farmer_facing_preview": "q",
        "reply_target_kind": "dm", "source_capture_ids": [],
    })
    assert res["ok"] is False
