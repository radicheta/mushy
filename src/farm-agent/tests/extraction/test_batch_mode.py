"""Batch mode and small-N fan-out. Guards the 2026-05-25 in-flight-slot regression."""

import pytest

from farm_agent.extraction.batch_mode import run_batch_mode, run_multi_confirm
from farm_agent.extraction import preview_builder, state_machine


class RealisticDb:
    """Enforces the D-02c partial unique index: one in-flight draft per sender."""

    def __init__(self):
        self.rows = {}

    def compute_draft_id(self, ids, index=None):
        return "d-" + "|".join(sorted(ids)) + ("" if index in (None, 0) else f"#{index}")

    async def insert_draft(self, pool, row):
        # A Postgres partial unique index only constrains rows that satisfy
        # its own WHERE predicate -- a row being inserted with a status
        # outside ('pending','awaiting_farmer') never participates in the
        # index, so it cannot conflict with anything, regardless of what
        # other rows exist for the sender.
        if row["status"] in ("pending", "awaiting_farmer"):
            in_flight = [r for r in self.rows.values()
                         if r["sender_e164"] == row["sender_e164"]
                         and r["status"] in ("pending", "awaiting_farmer")]
            if in_flight:
                return {"ok": False, "reason": "in_flight_conflict"}
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


async def test_multi_confirm_first_draft_gets_the_slot():
    """D-4: only one draft per sender can hold the in-flight slot. The first
    clean draft claims it and gets its confirm prompt; the second is
    persisted as needs_review instead of being dropped (Node's behavior) or
    arbitrarily winning the slot by iteration order.
    """
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(0), _clean(1)]
    res = await run_multi_confirm(**_kwargs(db, d, drafts))
    assert res["mode"] == "multi_confirm"
    assert res["count"] == 2
    assert [e for e, _ in d.calls].count("send_confirm_prompt") == 1

    rows_by_id = {r["id"]: r for r in db.rows.values()}
    first_row = rows_by_id[res["draft_ids"][0]]
    second_row = rows_by_id[res["draft_ids"][1]]
    assert first_row["status"] == "awaiting_farmer"
    assert second_row["status"] == "needs_review"
    assert second_row["needs_review_reason"] == "multi_confirm_slot_taken"


async def test_multi_confirm_persists_all_drafts_despite_slot_conflict():
    """No draft is ever dropped, even though only one can hold the slot."""
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(0), _clean(1), _clean(2)]
    res = await run_multi_confirm(**_kwargs(db, d, drafts))
    assert res["count"] == 3
    assert len(db.rows) == 3
