"""EDIT re-extraction. Replaces the Phase 61 stub -- a farmer correction must land."""

from farm_agent.confirm.edit_handler import create_edit_handler


class FakeConfirmRepo:
    def __init__(self, bump_ok=True):
        self.bumped = []
        self.bump_ok = bump_ok

    async def bump_edit_turn(self, pool, draft_id):
        self.bumped.append(draft_id)
        return {"ok": self.bump_ok, "edit_turn_count": 1}


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
                      farmer_correction=None):
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
    db = FakeExtractionDb()
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=FakeConfirmRepo(),
                            extraction_db=db, config=_config())
    await h["handle_edit"](ROW, "750 grams")
    draft_id, status, extras = db.updates[-1]
    assert draft_id == "d1"
    assert extras["draft_json"]["qty_g"] == 750


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

    assert calls[0] == "EDIT no it was 750 grams"
    assert result is not None
    assert result.get("action") == "edited"
    assert result.get("ok") is True
    assert fake_signal.sends, "farmer must hear the re-rendered preview after EDIT"
    assert "750" in fake_signal.sends[-1]["body"]
