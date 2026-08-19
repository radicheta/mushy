"""EDIT re-extraction. Replaces the Phase 61 stub -- a farmer correction must land."""

from farm_agent.confirm.edit_handler import create_edit_handler


class FakeConfirmRepo:
    def __init__(self, bump_ok=True, edit_rowcount=1):
        self.bumped = []
        self.bump_ok = bump_ok
        self.events = []  # (draft_id, event, payload)
        self.edits = []  # (draft_id, fields)
        self.edit_rowcount = edit_rowcount

    async def bump_edit_turn(self, pool, draft_id):
        self.bumped.append(draft_id)
        return {"ok": self.bump_ok, "edit_turn_count": 1}

    async def update_draft_after_edit(self, pool, draft_id, fields):
        # Real SQL is WHERE id=%s AND status='awaiting_farmer'; rowcount 0 means
        # the draft left awaiting_farmer before the update landed.
        self.edits.append((draft_id, fields))
        return {"ok": True, "rowcount": self.edit_rowcount}

    async def append_event_via_pool(self, pool, draft_id, event, payload):
        self.events.append((draft_id, event, payload))
        return {"ok": True, "seq": 1}


class FakeExtractionDb:
    def __init__(self):
        self.updates = []

    async def update_draft_status(self, pool, draft_id, status, extras=None):
        self.updates.append((draft_id, status, extras or {}))
        return {"ok": True, "rowcount": 1}


CORRECTED = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 750,
             "source_block_refs": ["b1"], "event_timestamp": "t"}


def _extractor(result):
    calls = []

    async def extract(captures, in_flight_draft=None, corpus_context=None,
                      farmer_correction=None, capture_date_iso=None):
        calls.append(farmer_correction)
        return result

    return {"extract": extract}, calls


def _config():
    class C:
        extraction_confidence_threshold = 0.7
        max_edit_turns = 3
    return C()


ROW = {"id": "d1", "sender_e164": "+5989", "status": "awaiting_farmer",
       "source_capture_ids": ["cap1"], "draft_json": {"type": "harvest", "qty_g": 500},
       "edit_turn_count": 0, "reply_target_kind": "dm", "group_id": None}


async def test_edit_passes_the_correction_to_the_extractor():
    ex, calls = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                            "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=FakeConfirmRepo(),
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "no it was 750 grams")
    assert res["ok"] is True
    assert calls[0] == "no it was 750 grams"


async def test_edit_updates_draft_in_place_same_id():
    ex, _ = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                        "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    repo = FakeConfirmRepo()
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=repo,
                            extraction_db=FakeExtractionDb(), config=_config())
    await h["handle_edit"](ROW, "750 grams")
    draft_id, fields = repo.edits[-1]
    assert draft_id == "d1"
    assert fields["draft_json"]["qty_g"] == 750


async def test_edit_goes_through_the_status_guarded_repo_not_update_draft_status():
    """C-3: the write MUST carry Node's WHERE ... AND status='awaiting_farmer'
    guard. extraction_db.update_draft_status has no status predicate and SETS
    the status, so an EDIT racing a YES would resurrect a closed draft."""
    ex, _ = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                        "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    repo = FakeConfirmRepo()
    db = FakeExtractionDb()
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=repo,
                            extraction_db=db, config=_config())
    res = await h["handle_edit"](ROW, "750 grams")
    assert res["ok"] is True
    assert len(repo.edits) == 1
    assert db.updates == [], "unguarded update_draft_status must not be used for EDIT"


async def test_edit_on_a_draft_that_left_awaiting_farmer_is_a_noop():
    """C-3: guarded UPDATE matches no row (the draft was confirmed / committed /
    expired mid-EDIT). Node returns draft_no_longer_active; so must we."""
    ex, _ = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                        "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    repo = FakeConfirmRepo(edit_rowcount=0)
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=repo,
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "750 grams")
    assert res["ok"] is True
    assert res["side_effect"] == "noop"
    assert res["reason"] == "draft_no_longer_active"


async def test_edit_returns_preview_resend_with_new_preview():
    ex, _ = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                        "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=FakeConfirmRepo(),
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "750 grams")
    assert res["side_effect"] == "send_preview_resend"
    assert "750" in res["new_preview"]


async def test_edit_bumps_the_turn_counter():
    ex, _ = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                        "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    repo = FakeConfirmRepo()
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=repo,
                            extraction_db=FakeExtractionDb(), config=_config())
    await h["handle_edit"](ROW, "750 grams")
    assert repo.bumped == ["d1"]


async def test_edit_extractor_failure_returns_reason_not_silence():
    ex, _ = _extractor({"ok": False, "reason": "schema_invalid"})
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=FakeConfirmRepo(),
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "750 grams")
    assert res["ok"] is False
    assert res["reason"] == "schema_invalid"


async def test_edit_success_writes_audit_trail_event():
    """Fix round 2: edit-handler.js:141-145 -- a DB audit row (signal_draft_event),
    not log output, must record the edit-turn history."""
    ex, _ = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                        "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    repo = FakeConfirmRepo()
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=repo,
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "750 grams")
    assert res["ok"] is True
    assert len(repo.events) == 1
    draft_id, event, payload = repo.events[0]
    assert draft_id == "d1"
    assert event == "edit"
    assert payload["ok"] is True
    assert payload["edit_text"] == "750 grams"


async def test_edit_extractor_failure_writes_audit_trail_event():
    """Fix round 2: edit-handler.js:112-116 -- the failure path must also be
    recorded, not just logged."""
    ex, _ = _extractor({"ok": False, "reason": "schema_invalid"})
    repo = FakeConfirmRepo()
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=repo,
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "750 grams")
    assert res["ok"] is False
    assert len(repo.events) == 1
    draft_id, event, payload = repo.events[0]
    assert draft_id == "d1"
    assert event == "edit"
    assert payload["ok"] is False
    assert payload["reason"] == "schema_invalid"
    assert payload["edit_text"] == "750 grams"


async def test_edit_extractor_exception_writes_audit_trail_event():
    """Fix round 2: edit-handler.js:100-104 -- an extractor exception must also
    land an audit row, not just a log line."""
    async def boom(*a, **kw):
        raise RuntimeError("down")

    repo = FakeConfirmRepo()
    h = create_edit_handler(pool=None, extractor={"extract": boom}, confirm_repo=repo,
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "750 grams")
    assert res["ok"] is False
    assert len(repo.events) == 1
    draft_id, event, payload = repo.events[0]
    assert draft_id == "d1"
    assert event == "edit"
    assert payload["ok"] is False
    assert payload["reason"] == "down"


async def test_edit_no_draft_row():
    ex, _ = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {}})
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=FakeConfirmRepo(),
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](None, "text")
    assert res == {"ok": False, "reason": "no_draft_row"}


async def test_edit_never_raises():
    async def boom(**kw):
        raise RuntimeError("down")

    h = create_edit_handler(pool=None, extractor={"extract": boom},
                            confirm_repo=FakeConfirmRepo(),
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "text")
    assert res["ok"] is False


# ---------------------------------------------------------------------------
# Wiring: dispatch.route_confirm_reply actually reaches the real handler
# (this is the gap Task 8 closes -- Phase 61 left a stub here that dropped
# the farmer's correction on the floor).
# ---------------------------------------------------------------------------


async def test_dispatch_edit_reply_reaches_the_extractor_and_resends_preview():
    from farm_agent.confirm.dispatch import route_confirm_reply
    from tests.confirm.test_strain_ask_back import (
        FakeConfirmRepoForDispatch,
        FakeSignalClient,
        _make_config,
        _make_standard_draft_row,
    )

    ex, calls = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                            "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    fake_signal = FakeSignalClient()
    fake_repo = FakeConfirmRepoForDispatch()
    draft = _make_standard_draft_row()

    result = await route_confirm_reply(
        object(), fake_signal, _make_config(), draft, "EDIT no it was 750 grams",
        repo=fake_repo, extractor=ex, extraction_db=FakeExtractionDb(),
    )

    # The EDIT verb must not reach the extractor -- only the remainder is the
    # farmer's correction (parser.js:31-38 parity).
    assert calls[0] == "no it was 750 grams"
    assert result is not None
    assert result.get("action") == "edited"
    assert result.get("ok") is True
    assert fake_signal.sends, "farmer must hear the re-rendered preview after EDIT"
    assert "750" in fake_signal.sends[-1]["body"]


# ---------------------------------------------------------------------------
# _extract_edit_text: the EDIT verb must not reach the extractor
# (Fix round 1 -- ported from confirm/parser.js:31-38)
# ---------------------------------------------------------------------------


def test_extract_edit_text_strips_leading_edit_verb_preserves_casing():
    from farm_agent.confirm.dispatch import _extract_edit_text

    assert _extract_edit_text("EDIT no it was 750 Grams") == "no it was 750 Grams"


def test_extract_edit_text_bare_edit_with_nothing_after_is_empty():
    from farm_agent.confirm.dispatch import _extract_edit_text

    assert _extract_edit_text("EDIT") == ""
    assert _extract_edit_text("edit   ") == ""


def test_extract_edit_text_implicit_edit_is_full_trimmed_body():
    from farm_agent.confirm.dispatch import _extract_edit_text

    assert _extract_edit_text("  no it was 750 grams  ") == "no it was 750 grams"
    # A recognized dispatch-level EDIT synonym (change/redo/fix) is NOT the
    # literal 'edit' token Node strips -- it falls through to the implicit
    # case, matching parser.js (which does not recognize these at all).
    assert _extract_edit_text("change it to 750g") == "change it to 750g"


async def test_dispatch_bare_edit_reply_sends_empty_correction_not_the_verb():
    """Farmer sends bare 'EDIT' (no remainder): correction must be '', not 'EDIT'."""
    from farm_agent.confirm.dispatch import route_confirm_reply
    from tests.confirm.test_strain_ask_back import (
        FakeConfirmRepoForDispatch,
        FakeSignalClient,
        _make_config,
        _make_standard_draft_row,
    )

    ex, calls = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                            "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    draft = _make_standard_draft_row()

    await route_confirm_reply(
        object(), FakeSignalClient(), _make_config(), draft, "EDIT",
        repo=FakeConfirmRepoForDispatch(), extractor=ex, extraction_db=FakeExtractionDb(),
    )

    assert calls[0] == ""


# ---------------------------------------------------------------------------
# MUSHY-92: punctuation after the control verb must not hide the edit path.
# _parse_yes_no_edit matched the first WHITESPACE-delimited token, so the
# colon in "edit:" (the form the bot's own copy teaches) was part of the
# token and never equalled "edit". The reply fell through to the capture
# pipeline and re-extracted instead of taking the cheap targeted edit.
# ---------------------------------------------------------------------------


def test_parse_edit_verb_with_trailing_colon_and_space():
    from farm_agent.confirm.dispatch import _parse_yes_no_edit

    assert _parse_yes_no_edit("edit: it was 750 grams") == "edit"


def test_parse_edit_verb_with_colon_glued_to_the_correction():
    from farm_agent.confirm.dispatch import _parse_yes_no_edit

    assert _parse_yes_no_edit("EDIT:750 grams") == "edit"


def test_parse_yes_no_verbs_tolerate_trailing_punctuation():
    from farm_agent.confirm.dispatch import _parse_yes_no_edit

    assert _parse_yes_no_edit("yes.") == "yes"
    assert _parse_yes_no_edit("No!") == "no"
    assert _parse_yes_no_edit("ok,") == "yes"


def test_parse_does_not_match_a_longer_word_that_starts_with_a_verb():
    from farm_agent.confirm.dispatch import _parse_yes_no_edit

    # "fixed the fan in FC1" is a real log entry, not a control word.
    assert _parse_yes_no_edit("fixed the fan in FC1") is None
    assert _parse_yes_no_edit("yesterday we harvested 2kg") is None


def test_extract_edit_text_strips_the_colon_with_the_verb():
    from farm_agent.confirm.dispatch import _extract_edit_text

    assert _extract_edit_text("edit: it was 750 Grams") == "it was 750 Grams"
    assert _extract_edit_text("EDIT:750 grams") == "750 grams"


def test_extract_edit_text_bare_edit_with_punctuation_only_is_empty():
    from farm_agent.confirm.dispatch import _extract_edit_text

    assert _extract_edit_text("edit:") == ""
    assert _extract_edit_text("EDIT: ") == ""
