"""
tests/confirm/test_reply_router.py -- unit tests for confirm/reply_router.py.

MUSHY-76 (task 8c): route_confirm_reply had no caller anywhere in farm_agent,
so the daemon created a draft, prompted the farmer, and then ignored their
YES/NO/EDIT reply. These tests prove the routing layer that makes
route_confirm_reply reachable, wired between snooze and capture.

Every test uses a composed `_dispatch` wrapper mirroring boot.py's
`_handle_with_confirm` closure so "consumed" is proven by what did NOT reach
the capture handle, not merely by try_route's boolean return.

No DB required -- confirm_repo, signal_client, and capture_pipeline are all
fakes/doubles.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from farm_agent.confirm.reply_router import create_confirm_reply_router

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRepo:
    """Configurable confirm_repo double. Records every call for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.quoted_draft: dict | None = None
        self.active_drafts: list[dict] = []
        self.recent_terminal_draft: dict | None = None
        self.confirm_rowcount = 1
        self.discard_rowcount = 1
        self.needs_review_discard_rowcount = 1

    async def find_draft_by_quoted_msg_ts(self, pool, quote_msg_ts):
        self.calls.append(("find_draft_by_quoted_msg_ts", quote_msg_ts))
        return self.quoted_draft

    async def find_active_drafts_for_sender(self, pool, sender_e164):
        self.calls.append(("find_active_drafts_for_sender", sender_e164))
        return self.active_drafts

    async def find_recent_terminal_draft_for_sender(self, pool, sender_e164):
        self.calls.append(("find_recent_terminal_draft_for_sender", sender_e164))
        return self.recent_terminal_draft

    async def confirm_draft(self, pool, draft_id):
        self.calls.append(("confirm_draft", draft_id))
        return {"ok": True, "rowcount": self.confirm_rowcount}

    async def discard_draft(self, pool, draft_id):
        self.calls.append(("discard_draft", draft_id))
        return {"ok": True, "rowcount": self.discard_rowcount}

    async def discard_needs_review_draft(self, pool, draft_id):
        self.calls.append(("discard_needs_review_draft", draft_id))
        return {"ok": True, "rowcount": self.needs_review_discard_rowcount}

    async def append_event_via_pool(self, pool, draft_id, event, payload):
        self.calls.append(("append_event_via_pool", draft_id, event))
        return {"ok": True, "seq": 1}

    async def update_draft_after_edit(self, pool, draft_id, fields):
        self.calls.append(("update_draft_after_edit", draft_id))
        return {"ok": True, "rowcount": 1}

    def called(self, fn: str) -> bool:
        return any(c[0] == fn for c in self.calls)


class FakeSignalClient:
    """Records send() calls. Never raises."""

    def __init__(self) -> None:
        self.sends: list[dict] = []

    async def send(self, body, *, to=None, related_draft_id=None, intent=None, **kwargs) -> dict:
        self.sends.append({"body": body, "to": to, "related_draft_id": related_draft_id, "intent": intent})
        return {"ok": True, "timestamp": 1234567890}


class FakeCaptureDouble:
    """Records calls to BOTH record_reply_capture (the paper-trail write) AND
    handle (the full capture pipeline) so tests can assert on what was
    consumed versus what reached capture -- not merely try_route's boolean.
    """

    def __init__(self) -> None:
        self.record_calls: list[dict] = []
        self.handle_calls: list[dict] = []

    async def _record_reply_capture(self, envelope, ctx=None) -> None:
        self.record_calls.append(envelope)

    async def _handle(self, envelope) -> None:
        self.handle_calls.append(envelope)

    def as_pipeline(self) -> dict:
        return {"handle": self._handle, "record_reply_capture": self._record_reply_capture}


def _envelope(source: str, text: str | None, *, quote: dict | None = None, msg_ts: int = 1_700_000_000_000) -> dict:
    dm: dict = {"message": text, "timestamp": msg_ts}
    if quote is not None:
        dm["quote"] = quote
    return {"envelope": {"source": source, "dataMessage": dm}}


def _draft(
    *,
    draft_id: str = "draft-001",
    sender_e164: str = "+59891840001",
    status: str = "awaiting_farmer",
    needs_review_reason: str | None = None,
    farmer_facing_preview: str = "5 bags SHI inoculation",
) -> dict:
    return {
        "id": draft_id,
        "status": status,
        "sender_e164": sender_e164,
        "edit_turn_count": 0,
        "nudge_sent_at": None,
        "needs_review_reason": needs_review_reason,
        "draft_json": {"species_code": "SHI"},
        "reply_target_kind": "dm",
        "group_id": None,
        "farmer_facing_preview": farmer_facing_preview,
    }


def _make_router(repo: FakeRepo, signal_client: FakeSignalClient, capture: FakeCaptureDouble):
    config = SimpleNamespace(max_edit_turns=3)
    router = create_confirm_reply_router(
        pool=object(),
        signal_client=signal_client,
        config=config,
        capture_pipeline=capture.as_pipeline(),
        confirm_repo=repo,
    )

    async def _dispatch(env: dict) -> bool:
        """Mirrors boot.py's `_handle_with_confirm` composition exactly."""
        if await router["try_route"](env):
            return True
        await capture._handle(env)
        return False

    return router, _dispatch


# ---------------------------------------------------------------------------
# 1. The whole point: YES is consumed by confirm, never reaches capture
# ---------------------------------------------------------------------------


async def test_yes_routes_to_confirm_and_does_not_reach_capture():
    repo = FakeRepo()
    draft = _draft()
    repo.active_drafts = [draft]
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(_envelope(draft["sender_e164"], "YES"))

    assert consumed is True
    assert repo.called("confirm_draft"), "confirm_draft must have been called"
    assert capture.handle_calls == [], "a farmer's YES must NEVER reach the capture pipeline"
    assert len(capture.record_calls) == 1, "the reply must land in the signal_capture paper trail"
    assert any(s["intent"] == "confirm_ack" for s in signal.sends)


# ---------------------------------------------------------------------------
# 2. Quote resolution wins over the most-recent-active heuristic
# ---------------------------------------------------------------------------


async def test_quote_resolves_the_draft_in_preference_to_the_active_heuristic():
    repo = FakeRepo()
    sender = "+59891840001"
    quoted = _draft(draft_id="draft-QUOTED", sender_e164=sender)
    other_active = _draft(draft_id="draft-OTHER-ACTIVE", sender_e164=sender)
    repo.quoted_draft = quoted
    repo.active_drafts = [other_active]  # would be picked if quote resolution didn't win
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(_envelope(sender, "YES", quote={"id": 999}))

    assert consumed is True
    assert repo.calls[0] == ("find_draft_by_quoted_msg_ts", 999)
    confirm_calls = [c for c in repo.calls if c[0] == "confirm_draft"]
    assert confirm_calls == [("confirm_draft", "draft-QUOTED")], (
        "the quoted draft must win, not the most-recent-active draft"
    )
    assert not repo.called("find_active_drafts_for_sender"), (
        "a resolved quote must skip the active-draft fallback lookup entirely"
    )


# ---------------------------------------------------------------------------
# 3. Spoof guard: a quote pointing at another farmer's draft must not route
# ---------------------------------------------------------------------------


async def test_quote_from_a_different_sender_is_not_routed():
    repo = FakeRepo()
    farmer_a = "+59891840001"
    farmer_b = "+59891840002"
    # The quoted draft belongs to farmer A.
    repo.quoted_draft = _draft(draft_id="draft-A", sender_e164=farmer_a)
    # Farmer B has NO active draft of their own -- without the spoof guard, the
    # quoted draft (belonging to farmer A) would be adopted as draftRow and
    # farmer B's YES would confirm farmer A's draft.
    repo.active_drafts = []
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(_envelope(farmer_b, "YES", quote={"id": 999}))

    assert not repo.called("confirm_draft"), "farmer A's draft must not be confirmed by farmer B's reply"

    # MUSHY-84 changed what happens AFTER the guard fires, not the guard itself.
    # This used to fall through to capture; a bare YES would then be extracted
    # into a phantom draft for farmer B. It is now answered as a control word
    # with no live draft. The security property is unchanged and is what the
    # assertions below pin: farmer A's draft is neither mutated nor described.
    assert consumed is True
    assert capture.handle_calls == [], "a bare YES must not be extracted into a draft"
    assert len(signal.sends) == 1
    assert signal.sends[0]["related_draft_id"] is None, (
        "the reply must not name farmer A's draft"
    )
    assert "draft-A" not in signal.sends[0]["body"]
    assert repo.calls[-1] == ("find_recent_terminal_draft_for_sender", farmer_b), (
        "the closed-conversation lookup must be scoped to the replying farmer"
    )


# ---------------------------------------------------------------------------
# 4. Quote to a terminal draft: polite ack, no mutation, still consumed
# ---------------------------------------------------------------------------


async def test_quote_to_a_terminal_draft_acks_closed_and_consumes():
    repo = FakeRepo()
    sender = "+59891840001"
    repo.quoted_draft = _draft(draft_id="draft-DONE", sender_e164=sender, status="committed")
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(_envelope(sender, "YES", quote={"id": 999}))

    assert consumed is True
    assert not repo.called("confirm_draft"), "a terminal-status draft must never be mutated"
    assert not repo.called("discard_draft")
    assert any(s["intent"] == "quote_closed" for s in signal.sends)
    assert capture.handle_calls == []
    assert len(capture.record_calls) == 1


# ---------------------------------------------------------------------------
# 5. Two active drafts, no quote pin -> numbered disambiguation ask-back
# ---------------------------------------------------------------------------


async def test_two_active_drafts_without_a_quote_sends_the_numbered_ask_back():
    repo = FakeRepo()
    sender = "+59891840001"
    repo.active_drafts = [
        _draft(draft_id="draft-1", sender_e164=sender),
        _draft(draft_id="draft-2", sender_e164=sender, status="commit_failed"),
    ]
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(_envelope(sender, "YES"))

    assert consumed is True
    assert not repo.called("confirm_draft"), "ambiguous drafts must not be silently confirmed"
    ask_backs = [s for s in signal.sends if s["intent"] == "ask_back"]
    assert len(ask_backs) == 1
    assert "1." in ask_backs[0]["body"] and "2." in ask_backs[0]["body"]
    assert capture.handle_calls == []
    assert len(capture.record_calls) == 1


# ---------------------------------------------------------------------------
# 6. NOOP text falls through to capture unchanged
# ---------------------------------------------------------------------------


async def test_noop_text_falls_through_to_capture():
    repo = FakeRepo()
    sender = "+59891840001"
    repo.active_drafts = [_draft(sender_e164=sender)]
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    env = _envelope(sender, "just chatting about the weather")
    consumed = await dispatch(env)

    assert consumed is False
    assert not repo.called("confirm_draft")
    assert not repo.called("discard_draft")
    assert capture.record_calls == [], "NOOP must not double-persist -- handle() persists it once"
    assert capture.handle_calls == [env], "a non-reply message must reach the normal capture pipeline"


# ---------------------------------------------------------------------------
# 7. Every consumed path records the reply capture (2026-05-24 regression)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "setup_kind",
    ["yes_confirm", "no_discard", "terminal_quote_closed", "ambiguous_ask_back"],
)
async def test_every_consumed_path_records_the_reply_capture(setup_kind):
    repo = FakeRepo()
    sender = "+59891840001"
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()

    if setup_kind == "yes_confirm":
        repo.active_drafts = [_draft(sender_e164=sender)]
        text = "YES"
    elif setup_kind == "no_discard":
        repo.active_drafts = [_draft(sender_e164=sender)]
        text = "NO"
    elif setup_kind == "terminal_quote_closed":
        repo.quoted_draft = _draft(draft_id="draft-DONE", sender_e164=sender, status="expired")
        text = "anything"
    else:  # ambiguous_ask_back
        repo.active_drafts = [
            _draft(draft_id="draft-1", sender_e164=sender),
            _draft(draft_id="draft-2", sender_e164=sender, status="commit_failed"),
        ]
        text = "YES"

    quote = {"id": 999} if setup_kind == "terminal_quote_closed" else None
    _router, dispatch = _make_router(repo, signal, capture)
    consumed = await dispatch(_envelope(sender, text, quote=quote))

    assert consumed is True, f"{setup_kind} must be consumed"
    assert len(capture.record_calls) == 1, (
        f"{setup_kind}: every consumed confirm-branch path must persist the "
        "reply to signal_capture (2026-05-24 fix) or follow-up replies vanish "
        "from the farmer's paper trail"
    )
    assert capture.handle_calls == [], f"{setup_kind}: consumed paths must never reach the full capture pipeline"


# ---------------------------------------------------------------------------
# 8. No text at all falls through before any DB lookup
# ---------------------------------------------------------------------------


async def test_no_text_falls_through():
    repo = FakeRepo()
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    env = _envelope("+59891840001", None)
    consumed = await dispatch(env)

    assert consumed is False
    assert repo.calls == [], "no-text envelopes must short-circuit before touching the DB"
    assert capture.record_calls == []
    assert capture.handle_calls == [env]


# ---------------------------------------------------------------------------
# MUSHY-84: a control word must never reach the extractor.
#
# Verified present on Python, not just Node: find_active_drafts_for_sender
# matches only awaiting_farmer / recent commit_failed, so once a draft moves to
# needs_review the farmer's next message finds nothing to route to and falls
# through to extraction. Live on Node that turned a bare NO into a phantom
# observation draft (asset_ref <UNKNOWN>, every confidence 0) which then asked
# the farmer a question about itself, while the real draft stayed open and the
# farmer got told "Discarded" -- an acknowledgement of something that never
# happened.
#
# Scope is deliberately narrow: ONLY a message that is nothing but a control
# word is intercepted. Free text still reaches extraction, because the farmer
# writing new farm data must never be answered with "that conversation is
# closed" -- see the phrase-vs-token test below.
# ---------------------------------------------------------------------------


async def test_bare_no_after_draft_left_awaiting_never_reaches_capture():
    """The exact 2026-08-18 shape: draft has gone needs_review, farmer sends NO."""
    repo = FakeRepo()
    repo.active_drafts = []  # needs_review is not "active"
    repo.recent_terminal_draft = _draft(status="needs_review")
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(_envelope("+59891840001", "NO"))

    assert consumed is True
    assert capture.handle_calls == [], (
        "a bare NO reached the capture pipeline -- it will be extracted into a "
        "phantom draft and the farmer will be asked to double-check an asset_ref "
        "for a draft that should never have existed (MUSHY-84)"
    )
    assert len(signal.sends) == 1, "the farmer must get an honest answer, not silence"


async def test_closed_conversation_answer_is_honest_not_a_false_ack():
    """The farmer must not be told something was discarded when nothing was."""
    repo = FakeRepo()
    repo.active_drafts = []
    repo.recent_terminal_draft = _draft(status="needs_review")
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    await dispatch(_envelope("+59891840001", "NO"))

    body = signal.sends[0]["body"].lower()
    assert "discard" not in body, (
        f"replied {signal.sends[0]['body']!r} -- claiming a discard that did not "
        "happen is the false-acknowledgement half of MUSHY-84"
    )
    assert repo.called("discard_draft") is False, "nothing must actually be discarded"


async def test_free_text_still_reaches_capture():
    """A new capture must never be swallowed as a stale control word.

    'fix' is in _EDIT_TOKENS and _parse_yes_no_edit looks only at the first
    token, so a first-token match alone would eat real farm data.
    """
    repo = FakeRepo()
    repo.active_drafts = []
    repo.recent_terminal_draft = _draft(status="needs_review")
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(
        _envelope("+59891840001", "fixed the fan in FC1 and topped up the humidifier")
    )

    assert consumed is False
    assert len(capture.handle_calls) == 1, (
        "free text was swallowed as a control word -- the farmer's log entry is lost"
    )


async def test_bare_control_word_with_no_prior_draft_is_still_not_extracted():
    """'NO' out of nowhere is not farm data either, and must not become a draft."""
    repo = FakeRepo()
    repo.active_drafts = []
    repo.recent_terminal_draft = None
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(_envelope("+59891840001", "NO"))

    assert consumed is True
    assert capture.handle_calls == []
    assert len(signal.sends) == 1, "silence after a farmer message is its own bug"


async def test_explicit_edit_prefix_to_a_closed_draft_is_answered_not_extracted():
    """'EDIT: ...' is unambiguous intent to amend, even with nothing open."""
    repo = FakeRepo()
    repo.active_drafts = []
    repo.recent_terminal_draft = _draft(status="needs_review")
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(
        _envelope("+59891840001", "EDIT: 2 source is 250530_KOS_7, not 250530_KOY_7")
    )

    assert consumed is True
    assert capture.handle_calls == []


async def test_live_draft_still_wins_over_the_closed_path():
    """The interception must not shadow a draft that is genuinely open."""
    repo = FakeRepo()
    draft = _draft()
    repo.active_drafts = [draft]
    repo.recent_terminal_draft = _draft(draft_id="older", status="needs_review")
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    await dispatch(_envelope(draft["sender_e164"], "YES"))

    assert repo.called("confirm_draft"), "an open draft must still be confirmed normally"


# ---------------------------------------------------------------------------
# MUSHY-84 (remaining half): a farmer's NO closes a stranded needs_review draft.
#
# The earlier fix stopped the phantom draft and the false "Discarded" ack, but
# left the real draft sitting in the needs-review queue as a ghost the farmer
# believed they had closed. The farmer is the source of truth about their own
# capture, so declining it must actually close it.
#
# Scoped to NO on purpose. YES and EDIT stay blocked: a draft reaches
# needs_review by exhausting the ask-back cap, and reopening it there would
# restart the loop the cap exists to stop.
# ---------------------------------------------------------------------------


async def test_no_discards_a_stranded_needs_review_draft():
    repo = FakeRepo()
    sender = "+59891840001"
    repo.recent_terminal_draft = _draft(draft_id="draft-STRANDED", sender_e164=sender,
                                        status="needs_review")
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(_envelope(sender, "NO"))

    assert consumed is True
    assert capture.handle_calls == [], "a control word must never reach the extractor"
    assert ("discard_needs_review_draft", "draft-STRANDED") in repo.calls, (
        "the farmer's NO must actually close the stranded draft"
    )
    assert len(signal.sends) == 1
    assert signal.sends[0]["related_draft_id"] == "draft-STRANDED"


async def test_yes_does_not_reopen_a_needs_review_draft():
    repo = FakeRepo()
    sender = "+59891840001"
    repo.recent_terminal_draft = _draft(draft_id="draft-STRANDED", sender_e164=sender,
                                        status="needs_review")
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(_envelope(sender, "YES"))

    assert consumed is True
    assert not repo.called("discard_needs_review_draft")
    assert not repo.called("confirm_draft"), "YES must not commit a capped draft"
    assert capture.handle_calls == []


async def test_no_does_not_discard_an_already_committed_draft():
    repo = FakeRepo()
    sender = "+59891840001"
    repo.recent_terminal_draft = _draft(draft_id="draft-DONE", sender_e164=sender,
                                        status="committed")
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(_envelope(sender, "NO"))

    assert consumed is True
    assert not repo.called("discard_needs_review_draft"), (
        "a committed draft is real farm data; NO must never unwrite it"
    )
    assert "saved" in signal.sends[0]["body"]


async def test_no_with_nothing_open_still_answers_honestly():
    repo = FakeRepo()
    sender = "+59891840001"
    repo.recent_terminal_draft = None
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    consumed = await dispatch(_envelope(sender, "NO"))

    assert consumed is True
    assert not repo.called("discard_needs_review_draft")
    assert len(signal.sends) == 1


async def test_the_farmer_is_told_the_draft_was_closed_not_that_it_is_pending():
    """The whole point: the ack must describe what just happened, not the old status."""
    repo = FakeRepo()
    sender = "+59891840001"
    repo.recent_terminal_draft = _draft(draft_id="draft-STRANDED", sender_e164=sender,
                                        status="needs_review")
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    await dispatch(_envelope(sender, "NO"))

    body = signal.sends[0]["body"].lower()
    assert "pending review" not in body, (
        "telling the farmer it is still pending is the bug this closes"
    )
    assert "closed" in body or "discarded" in body


async def test_a_failed_discard_never_claims_the_draft_was_closed():
    """No silent failure after a farmer control word, and no false acknowledgement."""
    repo = FakeRepo()
    sender = "+59891840001"
    repo.recent_terminal_draft = _draft(draft_id="draft-STRANDED", sender_e164=sender,
                                        status="needs_review")
    repo.needs_review_discard_rowcount = 0  # lost a race; someone else moved it
    signal = FakeSignalClient()
    capture = FakeCaptureDouble()
    _router, dispatch = _make_router(repo, signal, capture)

    await dispatch(_envelope(sender, "NO"))

    assert len(signal.sends) == 1, "the farmer must still get an answer"
    body = signal.sends[0]["body"].lower()
    assert "closed" not in body, "claiming closure that did not happen is MUSHY-84's false ack"
