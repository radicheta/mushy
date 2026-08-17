"""enqueue orchestration: continuity, idle guard, image loading, fail-soft."""

from datetime import datetime, timedelta, timezone

from farm_agent.extraction.pipeline import create_extraction_pipeline

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _dt_from_ms(ms: int) -> datetime:
    """Build a tz-aware datetime from an arbitrary ms offset from epoch.

    Avoids datetime.fromtimestamp() on negative offsets, which is a
    platform-dependent minefield -- this fixture's clock is a small test
    integer (1_000_000), not a real epoch-ms value, so offsets can go
    negative.
    """
    return _EPOCH + timedelta(milliseconds=ms)


class FakeDb:
    def __init__(self, in_flight=None):
        self.in_flight = in_flight
        self.inserted = []
        self.updates = []
        self.bumps = []

    def compute_draft_id(self, ids, index=None):
        return "draft-" + "|".join(sorted(ids)) + ("" if index in (None, 0) else f"#{index}")

    async def get_in_flight_for_sender(self, pool, sender):
        return self.in_flight

    async def insert_draft(self, pool, row):
        self.inserted.append(row)
        return {"ok": True, "id": row["id"]}

    async def update_draft_status(self, pool, draft_id, status, extras=None):
        self.updates.append((draft_id, status, extras or {}))
        return {"ok": True, "rowcount": 1}

    async def advance_askback_turn(self, pool, draft_id):
        self.bumps.append(draft_id)
        return {"ok": True, "askback_turns": 1}


class FakeDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch(self, effect, row):
        self.calls.append((effect, row))
        return {"ok": True}


CLEAN = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
         "source_block_refs": ["b1"], "event_timestamp": "2026-05-22T10:00:00Z"}


def _extractor(result):
    async def extract(captures, in_flight_draft=None, corpus_context=None,
                      farmer_correction=None):
        return result
    return {"extract": extract}


def _config(**over):
    class C:
        extraction_confidence_threshold = 0.7
        draft_idle_gap_min = 30
        max_askback_turns = 3
    c = C()
    for k, v in over.items():
        setattr(c, k, v)
    return c


def _pipeline(db, extractor, dispatcher=None, config=None):
    # create_outbound_dispatcher (Task 4) returns {"dispatch": async fn} -- the
    # one shape the pipeline accepts. Wrap the fake the same way so this double
    # matches what production actually hands in.
    d = dispatcher or FakeDispatcher()
    return create_extraction_pipeline(
        pool=None, extractor=extractor, config=config or _config(),
        extraction_db=db, outbound_dispatcher={"dispatch": d.dispatch},
        clock=lambda: 1_000_000,
    )


CTX = {"capture_id": "cap1", "sender": "+59891111111", "farmos_person": "santi",
       "text": "harvested 500g", "transcripts": [], "attachment_paths": [],
       "reply_target_kind": "dm", "group_id": None, "captured_at_ms": 1_000_000}


async def test_missing_sender_returns_reason():
    p = _pipeline(FakeDb(), _extractor({"ok": True}))
    res = await p["enqueue"]({"capture_id": "c"})
    assert res == {"ok": False, "reason": "missing_sender_or_capture_id"}


async def test_clean_draft_inserts_and_lands_awaiting_farmer():
    db = FakeDb()
    d = FakeDispatcher()
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }), d)
    res = await p["enqueue"](CTX)
    assert res["ok"] is True
    assert res["status"] == "awaiting_farmer"
    assert res["continuity"] == "start_new"
    assert db.inserted[0]["status"] == "pending"
    assert db.inserted[0]["source_capture_ids"] == ["cap1"]
    # D-1: the farmer is actually asked to confirm, with a preview to confirm against.
    assert d.calls[0][0] == "send_confirm_prompt"
    _, _, extras = db.updates[-1]
    assert "Reply YES to commit" in extras["farmer_facing_preview"]


async def test_extractor_failure_returns_reason_and_writes_nothing():
    db = FakeDb()
    p = _pipeline(db, _extractor({"ok": False, "reason": "schema_invalid"}))
    res = await p["enqueue"](CTX)
    assert res == {"ok": False, "reason": "schema_invalid"}
    assert db.inserted == []


async def test_extractor_raising_is_caught():
    db = FakeDb()

    async def boom(**kw):
        raise RuntimeError("anthropic down")

    p = _pipeline(db, {"extract": boom})
    res = await p["enqueue"](CTX)
    assert res["ok"] is False
    assert db.inserted == []


async def test_append_continuity_updates_existing_draft():
    db = FakeDb(in_flight={"id": "existing", "source_capture_ids": ["cap0"],
                           "askback_turns": 1, "updated_at": None})
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "append",
        "usage": None,
    }))
    res = await p["enqueue"](CTX)
    assert res["draft_id"] == "existing"
    assert res["continuity"] == "append"
    assert db.inserted == []


async def test_idle_gap_forces_start_new_over_llm_append():
    # in-flight last updated 31 minutes before now -> LLM 'append' is overridden.
    #
    # Brief defect fix (MUSHY-76 task-5-brief.md decision 1): the brief's fixture
    # seeded 'updated_at_ms' directly, but the real in-flight row column (and the
    # pipeline's normalization step) is 'updated_at' -- a datetime/ISO-string/None,
    # never a raw *_ms integer. Seed a tz-aware datetime instead so this test
    # exercises the actual normalization path.
    now = 1_000_000
    db = FakeDb(in_flight={"id": "old", "source_capture_ids": ["cap0"],
                           "askback_turns": 0,
                           "updated_at": _dt_from_ms(now - 31 * 60 * 1000)})
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "append",
        "usage": None,
    }))
    res = await p["enqueue"](CTX)
    assert res["continuity"] == "start_new"
    assert db.inserted != []
    assert ("old", "expired", {}) in [(a, b, c) for a, b, c in db.updates]


async def test_ask_back_path_builds_preview_and_bumps_turn():
    db = FakeDb()
    d = FakeDispatcher()
    dirty = dict(CLEAN)
    del dirty["qty_g"]
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": dirty, "per_field_confidence": {}}],
        "draft": dirty, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }), d)
    res = await p["enqueue"](CTX)
    assert res["side_effects"] == ["send_ask_back"]
    _, _, extras = db.updates[-1]
    assert extras["farmer_facing_preview"]
    assert db.bumps == [res["draft_id"]]
    assert d.calls[0][0] == "send_ask_back"


async def test_insert_conflict_returns_reason():
    db = FakeDb()

    async def conflict(pool, row):
        return {"ok": False, "reason": "in_flight_conflict"}

    db.insert_draft = conflict
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }))
    res = await p["enqueue"](CTX)
    assert res == {"ok": False, "reason": "in_flight_conflict"}


async def test_multi_draft_routes_to_unimplemented_stub_without_crashing():
    # Task 6 owns multi-draft routing; here it must stay a stub that enqueue's
    # outer try/except converts into a clean ok:False, never an unhandled raise.
    # Also proves the single-draft tests above exercise a genuinely different
    # branch (drafts.length == 1 never reaches this stub).
    db = FakeDb()
    p = _pipeline(db, _extractor({
        "ok": True,
        "drafts": [
            {"draft": CLEAN, "per_field_confidence": {}},
            {"draft": CLEAN, "per_field_confidence": {}},
        ],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }))
    res = await p["enqueue"](CTX)
    assert res["ok"] is False
    assert db.inserted == []


async def test_dispatch_failure_does_not_fail_enqueue():
    class BadDispatcher:
        async def dispatch(self, effect, row):
            raise RuntimeError("signal down")

    db = FakeDb()
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }), BadDispatcher())
    res = await p["enqueue"](CTX)
    assert res["ok"] is True
