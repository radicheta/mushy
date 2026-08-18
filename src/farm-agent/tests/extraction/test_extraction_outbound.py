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
        # snake_case, matching the real producer (batch_mode.py). Hand-writing
        # Node's camelCase draftIds here is what hid C-1.
        "draft_ids": [
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


# ---------------------------------------------------------------------------
# MUSHY-91: the same ask-back is never sent to the farmer twice.
#
# askback_turns caps at 3 but only advances on a reply the confirm loop
# understands, so any path that re-runs extraction against an in-flight draft
# without a parseable reply re-sends the outstanding ask-back forever. On
# 2026-08-18 that put six identical messages on the farmer's phone at ~20s
# intervals. The bound belongs on the send, not on comprehension.
# ---------------------------------------------------------------------------

def _dedup_dispatcher(client, last_bodies, operator="+59890000000", pinged=None):
    """Dispatcher with the duplicate-send guard wired to an in-memory last-body map."""
    async def _get_last_sent_body(draft_id):
        return last_bodies.get(draft_id)

    return create_outbound_dispatcher(
        signal_client=client, config=object(), preview_builder=preview_builder,
        operator_recipient=operator, get_last_sent_body=_get_last_sent_body,
    )["dispatch"]


_DRAFT = {
    "id": "dup123", "sender_e164": "+59891111111",
    "farmer_facing_preview": "What seq did this session start at?",
    "reply_target_kind": "dm", "source_capture_ids": ["cap1"],
}


async def test_identical_ask_back_is_suppressed_on_resend():
    """The exact 2026-08-18 loop: same draft, same body, nothing changed."""
    c = FakeSignalClient()
    last: dict = {}
    d = _dedup_dispatcher(c, last)

    first = await d("send_ask_back", dict(_DRAFT))
    assert first["ok"] is True
    assert len(c.sent) == 1

    # Simulate the row SignalClient.send persists (MUSHY-90).
    last["dup123"] = _DRAFT["farmer_facing_preview"]

    second = await d("send_ask_back", dict(_DRAFT))
    assert second == {"ok": False, "reason": "duplicate_send"}
    farmer_sends = [s for s in c.sent if s[1]["to"] == "+59891111111"]
    assert len(farmer_sends) == 1, (
        f"the identical ask-back reached the farmer twice: {farmer_sends}"
    )


async def test_changed_preview_still_sends():
    """The guard is on sameness, not on count -- a real new question must go out."""
    c = FakeSignalClient()
    last = {"dup123": "What seq did this session start at?"}
    d = _dedup_dispatcher(c, last)

    changed = dict(_DRAFT, farmer_facing_preview="How many bags in total?")
    res = await d("send_ask_back", changed)
    assert res["ok"] is True
    assert c.sent[0][0] == "How many bags in total?"


async def test_suppression_pings_the_operator_once_per_draft():
    """A suppressed send means the farmer is waiting on something not arriving.

    Pinged once per draft, not once per suppression -- otherwise the flood just
    moves from the farmer's phone to the operator's.
    """
    c = FakeSignalClient()
    last = {"dup123": _DRAFT["farmer_facing_preview"]}
    d = _dedup_dispatcher(c, last)

    for _ in range(4):
        await d("send_ask_back", dict(_DRAFT))

    operator_sends = [s for s in c.sent if s[1]["to"] == "+59890000000"]
    assert len(operator_sends) == 1, (
        f"expected exactly one operator ping across 4 suppressions, got "
        f"{len(operator_sends)}"
    )
    assert "dup123" in operator_sends[0][0]


async def test_other_draft_is_unaffected_by_a_suppressed_one():
    c = FakeSignalClient()
    last = {"dup123": _DRAFT["farmer_facing_preview"]}
    d = _dedup_dispatcher(c, last)

    await d("send_ask_back", dict(_DRAFT))
    other = dict(_DRAFT, id="other456")
    res = await d("send_ask_back", other)

    assert res["ok"] is True, "a different draft must not inherit dup123's suppression"


async def test_guard_is_inert_when_not_wired():
    """No lookup hook (or a failing one) must never block a farmer message.

    Outbound persistence is fail-open, so the lookup can legitimately return
    nothing. Silence must degrade to sending, not to not-sending -- the failure
    this guard prevents is noisy, the failure it must not cause is silent.
    """
    c = FakeSignalClient()
    d = create_outbound_dispatcher(
        signal_client=c, config=object(), preview_builder=preview_builder,
        operator_recipient="+59890000000",
    )["dispatch"]

    assert (await d("send_ask_back", dict(_DRAFT)))["ok"] is True
    assert (await d("send_ask_back", dict(_DRAFT)))["ok"] is True
    assert len(c.sent) == 2


async def test_lookup_failure_falls_open_to_sending():
    c = FakeSignalClient()

    async def _boom(draft_id):
        raise RuntimeError("pool exhausted")

    d = create_outbound_dispatcher(
        signal_client=c, config=object(), preview_builder=preview_builder,
        operator_recipient="+59890000000", get_last_sent_body=_boom,
    )["dispatch"]

    res = await d("send_ask_back", dict(_DRAFT))
    assert res["ok"] is True
    assert len(c.sent) == 1
