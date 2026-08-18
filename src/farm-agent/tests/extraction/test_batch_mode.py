"""Batch mode and small-N fan-out. Guards the 2026-05-25 in-flight-slot regression."""

import pytest

from farm_agent.extraction.batch_mode import run_batch_mode, run_multi_confirm
from farm_agent.extraction import outbound, preview_builder, state_machine


class RealisticDb:
    """Mirrors the signal_draft schema as it actually is.

    MUSHY-53/80: the D-02c partial unique index that permitted one in-flight
    draft per sender has been dropped, so several drafts from the same capture
    can be awaiting_farmer at once. This fake used to enforce that uniqueness;
    leaving it in would make the fake disagree with the real table and hide the
    very behaviour these tests exist to check.

    The count is still bounded, just not by the database: _should_batch_review
    routes anything over 5 drafts to batch review, and batch review parks every
    draft in needs_review. So at most 5 in-flight drafts per sender.
    """

    def __init__(self):
        self.rows = {}

    def compute_draft_id(self, ids, index=None):
        return "d-" + "|".join(sorted(ids)) + ("" if index in (None, 0) else f"#{index}")

    async def insert_draft(self, pool, row):
        self.rows[row["id"]] = dict(row)
        return {"ok": True, "id": row["id"]}

    async def update_draft_status(self, pool, draft_id, status, extras=None):
        if draft_id not in self.rows:
            return {"ok": False, "reason": "not_found"}
        self.rows[draft_id]["status"] = status
        self.rows[draft_id].update(extras or {})
        return {"ok": True, "rowcount": 1}

    async def advance_askback_turn(self, pool, draft_id):
        return {"ok": True, "askback_turns": 1}


class FakeDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch(self, effect, row):
        self.calls.append((effect, row))
        return {"ok": True}


def _config():
    class C:
        extraction_confidence_threshold = 0.7
        draft_idle_gap_min = 30
        max_askback_turns = 3
    return C()


def _clean(i):
    return {"draft": {"type": "harvest", "harvest_batch_id": f"H{i}", "qty_g": 100,
                      "source_block_refs": [f"b{i}"], "event_timestamp": "t"},
            "per_field_confidence": {}}


CTX = {"farmos_person": "santi", "reply_target_kind": "dm", "group_id": None}


def _kwargs(db, dispatcher, drafts):
    # create_outbound_dispatcher (Task 4) returns {"dispatch": async fn} -- the
    # one shape batch_mode.py accepts. Wrap the fake the same way so this
    # double matches what production actually hands in.
    return dict(drafts_arr=drafts, capture_ctx=CTX, sender="+5989", capture_id="cap1",
                now_ms=0, in_flight=None, pool=None, extraction_db=db,
                state_machine=state_machine, preview_builder=preview_builder,
                outbound_dispatcher={"dispatch": dispatcher.dispatch}, config=_config(), log=None)


async def test_batch_mode_persists_every_draft_on_the_page():
    """The regression: all 7 entries must land, not just the first."""
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(i) for i in range(7)]
    res = await run_batch_mode(source_capture_ids_base=["cap1"],
                               **_kwargs(db, d, drafts))
    assert res["count"] == 7
    assert len(db.rows) == 7


async def test_batch_summary_payload_carries_every_draft_id_on_the_seam():
    """C-1: the producer key here and the consumer key in outbound.py must be the
    SAME key. They were draft_ids vs draftIds, so every page reported 0 drafts."""
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(i) for i in range(7)]
    await run_batch_mode(source_capture_ids_base=["cap1"], **_kwargs(db, d, drafts))

    summaries = [payload for effect, payload in d.calls if effect == "send_batch_review_summary"]
    assert len(summaries) == 1
    assert len(summaries[0]["draft_ids"]) == 7

    # And the real consumer must read that payload, not an empty list.
    sent = []

    class FakeSignal:
        async def send(self, body, **kw):
            sent.append(body)
            return {"ok": True}

    dispatcher = outbound.create_outbound_dispatcher(
        FakeSignal(), _config(), preview_builder, "+59891000000"
    )
    res = await dispatcher["dispatch"]("send_batch_review_summary", summaries[0])
    assert res.get("ok") is True
    assert "7 drafts" in sent[0]
    assert "IDs: ." not in sent[0]


async def test_batch_mode_continues_past_a_failed_draft_mid_page():
    """Deferred item: the per-draft fail-soft `continue`. One bad entry on a
    paper-log page must not take the rest of the page down with it."""
    db, d = RealisticDb(), FakeDispatcher()

    real_insert = db.insert_draft
    calls = {"n": 0}

    async def flaky_insert(pool, row):
        calls["n"] += 1
        if calls["n"] == 3:
            return {"ok": False, "reason": "boom"}
        return await real_insert(pool, row)

    db.insert_draft = flaky_insert

    real_update = db.update_draft_status

    async def flaky_update(pool, draft_id, status, extras=None):
        # Last entry on the page, so its row staying 'pending' cannot take the
        # in-flight slot from a later sibling.
        if draft_id.endswith("#6"):
            return {"ok": False, "reason": "boom"}
        return await real_update(pool, draft_id, status, extras)

    db.update_draft_status = flaky_update

    drafts = [_clean(i) for i in range(7)]
    res = await run_batch_mode(source_capture_ids_base=["cap1"], **_kwargs(db, d, drafts))

    # The failed insert drops exactly one draft; the failed status update does
    # not drop its draft (it is still reported), and neither aborts the page.
    assert res["count"] == 6
    assert len(db.rows) == 6
    summaries = [payload for effect, payload in d.calls if effect == "send_batch_review_summary"]
    assert len(summaries[0]["draft_ids"]) == 6


async def test_batch_mode_routes_clean_drafts_to_needs_review():
    db, d = RealisticDb(), FakeDispatcher()
    await run_batch_mode(source_capture_ids_base=["cap1"], **_kwargs(db, d, [_clean(0)]))
    row = next(iter(db.rows.values()))
    assert row["status"] == "needs_review"
    assert row["needs_review_reason"] == "batch_mode_clean"


async def test_batch_mode_flags_low_conf_drafts_distinctly():
    db, d = RealisticDb(), FakeDispatcher()
    dirty = {"draft": {"type": "harvest", "harvest_batch_id": "H", "event_timestamp": "t"},
             "per_field_confidence": {}}
    await run_batch_mode(source_capture_ids_base=["cap1"], **_kwargs(db, d, [dirty]))
    row = next(iter(db.rows.values()))
    assert row["status"] == "needs_review"
    assert row["needs_review_reason"] == "batch_mode_low_conf"


async def test_batch_mode_never_asks_the_farmer_back():
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(i) for i in range(3)]
    await run_batch_mode(source_capture_ids_base=["cap1"], **_kwargs(db, d, drafts))
    assert all(effect != "send_ask_back" for effect, _ in d.calls)


async def test_batch_mode_expires_prior_in_flight():
    db, d = RealisticDb(), FakeDispatcher()
    db.rows["old"] = {"id": "old", "sender_e164": "+5989", "status": "awaiting_farmer"}
    kw = _kwargs(db, d, [_clean(0)])
    kw["in_flight"] = {"id": "old"}
    await run_batch_mode(source_capture_ids_base=["cap1"], **kw)
    assert db.rows["old"]["status"] == "expired"


async def test_draft_ids_are_unique_per_index():
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(i) for i in range(3)]
    res = await run_batch_mode(source_capture_ids_base=["cap1"], **_kwargs(db, d, drafts))
    assert len(set(res["draft_ids"])) == 3


async def test_multi_confirm_gives_every_clean_draft_its_own_prompt():
    """MUSHY-53/80: this is what Phase 53 BACK-02 intended all along.

    "DT tubs 0519 1 and 2" is two entries, so the farmer gets two independent
    confirm prompts and can answer them separately. Previously the first draft
    took the only in-flight slot and the second was parked in needs_review
    (D-4), where the farmer never saw it -- better than Node, which dropped it
    outright, but still not the designed behaviour.
    """
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(0), _clean(1)]
    res = await run_multi_confirm(**_kwargs(db, d, drafts))
    assert res["mode"] == "multi_confirm"
    assert res["count"] == 2
    assert [e for e, _ in d.calls].count("send_confirm_prompt") == 2

    rows_by_id = {r["id"]: r for r in db.rows.values()}
    for draft_id in res["draft_ids"]:
        row = rows_by_id[draft_id]
        assert row["status"] == "awaiting_farmer", f"{draft_id} did not reach awaiting_farmer"
        assert row.get("needs_review_reason") is None


async def test_multi_confirm_persists_all_drafts():
    """No draft is ever dropped."""
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(0), _clean(1), _clean(2)]
    res = await run_multi_confirm(**_kwargs(db, d, drafts))
    assert res["count"] == 3
    assert len(db.rows) == 3
    assert [e for e, _ in d.calls].count("send_confirm_prompt") == 3


async def test_multi_confirm_stays_within_the_small_n_cap():
    """The cap is 5, enforced by _should_batch_review upstream, not by the DB.

    This pins the contract that lifting the unique index relies on: anything
    larger than 5 never reaches run_multi_confirm in the first place.
    """
    from farm_agent.extraction.pipeline import _should_batch_review

    # High confidence throughout, so only the count rule is under test.
    def _hc(i):
        d = _clean(i)
        d["per_field_confidence"] = {"qty_g": 0.95}
        return d

    assert _should_batch_review([_hc(i) for i in range(5)]) is False
    assert _should_batch_review([_hc(i) for i in range(6)]) is True
