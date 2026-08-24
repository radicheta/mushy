"""enqueue orchestration: continuity, idle guard, image loading, fail-soft."""

from datetime import datetime, timedelta, timezone

from farm_agent.extraction.pipeline import create_extraction_pipeline
from farm_agent.extraction.state_machine import DraftStatus

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


class FakePool:
    """Minimal async pool double: records executed raw SQL, never touches a DB.

    Adapted from tests/extraction/test_extraction_db.py's FakePool (Task 1) --
    same convention, reused rather than reinvented. The pipeline's two raw-SQL
    blocks (source_capture_ids extension, token-usage stamp) go through
    pool.connection() directly rather than the DAO, so a test that always
    passes pool=None never executes them -- AttributeError is swallowed by the
    surrounding fail-soft except, and a wrong column name or param order would
    pass the whole suite silently.
    """

    def __init__(self):
        self.calls = []

    def connection(self):
        return _FakeConnCtx(self)


class _FakeConnCtx:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        return _FakeConn(self.pool)

    async def __aexit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, pool):
        self.pool = pool

    async def execute(self, sql, params=None):
        self.pool.calls.append((sql, params))


CLEAN = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
         "source_block_refs": ["b1"], "event_timestamp": "2026-05-22T10:00:00Z"}


def _extractor(result):
    async def extract(captures, in_flight_draft=None, corpus_context=None,
                      farmer_correction=None, capture_date_iso=None):
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


def _pipeline(db, extractor, dispatcher=None, config=None, pool=None):
    # create_outbound_dispatcher (Task 4) returns {"dispatch": async fn} -- the
    # one shape the pipeline accepts. Wrap the fake the same way so this double
    # matches what production actually hands in.
    d = dispatcher or FakeDispatcher()
    return create_extraction_pipeline(
        pool=pool, extractor=extractor, config=config or _config(),
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

    async def boom(captures, **kw):
        raise RuntimeError("anthropic down")

    p = _pipeline(db, {"extract": boom})
    res = await p["enqueue"](CTX)
    assert res == {"ok": False, "reason": "anthropic down"}
    assert db.inserted == []


async def test_in_flight_lookup_exception_returns_reason():
    class BoomDb(FakeDb):
        async def get_in_flight_for_sender(self, pool, sender):
            raise RuntimeError("db down")

    p = _pipeline(BoomDb(), _extractor({"ok": True}))
    res = await p["enqueue"](CTX)
    assert res == {"ok": False, "reason": "db down"}


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
    # The append path must actually persist the new draft body via
    # update_draft_status, not just resolve continuity and stop.
    persist_updates = [u for u in db.updates if u[0] == "existing"]
    assert len(persist_updates) >= 1
    _, status, extras = persist_updates[0]
    assert status == "pending"
    assert extras["draft_json"] == CLEAN
    assert extras["per_field_confidence"] == {}
    assert extras["log_type"] == "harvest"


async def test_replace_continuity_reuses_the_draft_without_extending_captures():
    """I-5: the third continuity branch. `replace` supersedes the in-flight draft
    body on the SAME row, so it keeps the prior source_capture_ids rather than
    extending them the way `append` does."""
    pool = FakePool()
    db = FakeDb(in_flight={"id": "existing", "source_capture_ids": ["cap0"],
                           "askback_turns": 1, "updated_at": None})
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "replace",
        "usage": None,
    }), pool=pool)
    res = await p["enqueue"](CTX)
    assert res["ok"] is True
    assert res["draft_id"] == "existing"
    assert res["continuity"] == "replace"
    assert db.inserted == []

    # The new body lands on the existing row.
    persist_updates = [u for u in db.updates if u[0] == "existing"]
    assert persist_updates
    _, status, extras = persist_updates[0]
    assert status == "pending"
    assert extras["draft_json"] == CLEAN

    # ... and source_capture_ids is NOT extended: the raw-SQL write rewrites the
    # prior list unchanged, where `append` would have written ["cap0", "cap1"].
    assert len(pool.calls) == 1
    _sql, params = pool.calls[0]
    assert params == (["cap0"], "existing")


async def test_append_persists_source_capture_ids_via_raw_sql():
    # The append-path extras whitelist excludes arrays (extraction_db.py), so
    # source_capture_ids is extended via a separate raw pool.execute() call --
    # not through the DAO. Prove it actually fires with the right SQL/params,
    # using a pool double that records every execute() (test_extraction_db.py's
    # FakePool convention), not pool=None (which would swallow it silently).
    pool = FakePool()
    db = FakeDb(in_flight={"id": "existing", "source_capture_ids": ["cap0"],
                           "askback_turns": 1, "updated_at": None})
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "append",
        "usage": None,
    }), pool=pool)
    res = await p["enqueue"](CTX)
    assert res["ok"] is True
    assert len(pool.calls) == 1
    sql, params = pool.calls[0]
    assert "UPDATE signal_draft" in sql
    assert "source_capture_ids" in sql
    assert params == (["cap0", "cap1"], "existing")


async def test_usage_stamp_persists_token_counts_via_raw_sql():
    pool = FakePool()
    db = FakeDb()
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": {
            "input_tokens": 111, "output_tokens": 22,
            "cache_creation_input_tokens": 3, "cache_read_input_tokens": 4,
        },
    }), pool=pool)
    res = await p["enqueue"](CTX)
    assert res["ok"] is True
    assert len(pool.calls) == 1
    sql, params = pool.calls[0]
    assert "UPDATE signal_capture" in sql
    # Precise column-name checks -- "input_tokens" alone is a substring of
    # "cache_creation_input_tokens" / "cache_read_input_tokens" and would
    # still match even if the primary input_tokens column got renamed, so
    # anchor on "SET <col> =" / ", <col> =" to actually pin the column name.
    assert "SET input_tokens = %s" in sql
    assert "output_tokens = %s" in sql
    assert "cache_creation_input_tokens = %s" in sql
    assert "cache_read_input_tokens = %s" in sql
    assert "model = %s" in sql
    assert params == (111, 22, 3, 4, "claude-sonnet-4-6", "cap1")


async def test_usage_stamp_skipped_when_usage_falsy():
    pool = FakePool()
    db = FakeDb()
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }), pool=pool)
    res = await p["enqueue"](CTX)
    assert res["ok"] is True
    assert pool.calls == []


async def test_extractor_receives_loaded_image_blocks(tmp_path):
    # 2026-05-12 Node bug fix: attachment_paths are filesystem paths; the
    # extractor must receive decoded base64 {data, media_type} blocks, not
    # the raw path strings, or every image is silently dropped pre-fix.
    img_path = tmp_path / "block.jpg"
    img_path.write_bytes(b"not-a-real-jpeg-but-multimodal-fails-open-on-decode")

    received = {}

    async def extract(captures, in_flight_draft=None, corpus_context=None,
                      farmer_correction=None, capture_date_iso=None):
        received["captures"] = captures
        return {
            "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
            "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
            "usage": None,
        }

    db = FakeDb()
    ctx = dict(CTX, attachment_paths=[str(img_path)])
    p = _pipeline(db, {"extract": extract})
    res = await p["enqueue"](ctx)
    assert res["ok"] is True
    images = received["captures"][0]["images"]
    assert len(images) == 1
    assert images[0]["media_type"] == "image/jpeg"
    assert images[0]["data"]


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


async def test_multi_draft_routes_to_batch_mode():
    # Task 6: multi-draft routing is real. Two drafts with empty
    # per_field_confidence -> _min_leaf_confidence returns 0 (conservative,
    # no confidence signal) -> _should_batch_review is True -> run_batch_mode.
    # Also proves the single-draft tests above exercise a genuinely different
    # branch (drafts.length == 1 never reaches multi-draft routing).
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
    assert res["ok"] is True
    assert res["mode"] == "batch"
    assert res["count"] == 2
    assert len(db.inserted) == 2


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


# ---------------------------------------------------------------------------
# Seam: the pipeline must survive what the extractor ACTUALLY produces
# ---------------------------------------------------------------------------


def _real_extractor_result():
    """pack_result() over a REAL Submission -- the genuine extractor output.

    Every other test in this file hands the pipeline hand-written dicts, which
    is exactly why the live-fire crash ("'SeedingSession' object has no
    attribute 'get'") reached production-adjacent code. This one drives the
    real boundary function over the real pydantic schemas.
    """
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from farm_agent.extraction.extractor import pack_result  # noqa: PLC0415
    from farm_agent.extraction.schemas.submission import Submission  # noqa: PLC0415

    fixture = (
        Path(__file__).parent.parent
        / "fixtures" / "extraction" / "seeding-session-may22" / "expected-draft.json"
    )
    submission = Submission.model_validate({
        "drafts": [{
            "draft": json.loads(fixture.read_text()),
            "per_field_confidence": {"event_date": 0.98, "groups": 0.95},
        }],
        "continuity": "start_new",
        "continuity_reason": "New seeding session",
        "capture_kind": "voice_note",
    })
    return pack_result(submission, {"input_tokens": 10, "output_tokens": 20})


async def test_real_extractor_output_flows_through_to_an_inserted_draft_row():
    import json  # noqa: PLC0415

    db = FakeDb()
    p = _pipeline(db, _extractor(_real_extractor_result()))

    res = await p["enqueue"](CTX)

    assert res["ok"] is True, f"pipeline rejected real extractor output: {res}"
    assert len(db.inserted) == 1, "no draft row inserted from real extractor output"
    row = db.inserted[0]
    assert row["source_capture_ids"] == ["cap1"]
    # draft_json goes into a jsonb column via Jsonb(...) -- it must be plain data.
    persisted = row.get("draft_json") or db.updates[-1][2].get("draft_json")
    assert isinstance(persisted, dict)
    assert persisted["type"] == "seeding_session"
    json.dumps(persisted)


# MUSHY-83: the pipeline must hand the extractor the CAPTURE's received-at, not
# the wall clock. This is the seam the Node fix shipped without covering -- the
# extractor unit test proved the block renders, but nothing proved the pipeline
# passes the right instant, which is the half that decides whether a replayed
# capture reanchors to its original day.
#
# The harness clock is also 1_000_000, so a test using CTX's own captured_at_ms
# cannot tell the two sources apart. Use a distinct capture timestamp.
_ANCHOR_MS = 1_755_000_000_000  # 2025-08-12T ~14:40Z -- nowhere near the 1970 clock


async def _anchor_seen(ctx):
    """Run enqueue and return the capture_date_iso the extractor was handed."""
    received = {}

    async def extract(captures, in_flight_draft=None, corpus_context=None,
                      farmer_correction=None, capture_date_iso=None):
        received["anchor"] = capture_date_iso
        return {
            "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
            "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
            "usage": None,
        }

    p = _pipeline(FakeDb(), {"extract": extract})
    res = await p["enqueue"](ctx)
    assert res["ok"] is True
    return received["anchor"]


async def test_pipeline_anchors_extraction_to_the_capture_timestamp():
    anchor = await _anchor_seen(dict(CTX, captured_at_ms=_ANCHOR_MS))
    assert anchor.startswith("2025-08-12"), anchor
    assert not anchor.startswith("1970"), "used the clock instead of the capture"


async def test_pipeline_falls_back_to_the_clock_when_capture_timestamp_missing():
    ctx = dict(CTX)
    ctx.pop("captured_at_ms")
    anchor = await _anchor_seen(ctx)
    # Degrades to an anchor, never to no anchor: the clock is 1_000_000ms.
    assert anchor.startswith("1970-01-01"), anchor


async def test_pipeline_ignores_an_unusable_capture_timestamp():
    anchor = await _anchor_seen(dict(CTX, captured_at_ms="not-a-number"))
    assert anchor.startswith("1970-01-01"), anchor


# ---------------------------------------------------------------------------
# MUSHY-86: the ref check reaches the farmer through the real pipeline
# ---------------------------------------------------------------------------


async def test_confirm_prompt_flags_a_source_block_that_is_not_in_farmos():
    """Seam test: extraction -> check -> preview -> the body the farmer receives."""
    from farm_agent.farmos import assets

    assets._clear_cache()

    async def get(path):
        return {"ok": True, "body": {"data": []}}  # nothing resolves

    db = FakeDb()
    p = create_extraction_pipeline(
        pool=None, extractor=_extractor({
            "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
            "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
            "usage": None,
        }), config=_config(),
        extraction_db=db, outbound_dispatcher={"dispatch": FakeDispatcher().dispatch},
        clock=lambda: 1_000_000,
        farmos_client={"get": get},
    )

    await p["enqueue"](CTX)

    _, _, extras = db.updates[-1]
    assert "New in farmOS, will be created: b1" in extras["farmer_facing_preview"]
    assets._clear_cache()


async def test_an_unreachable_farmos_does_not_claim_the_block_is_new():
    """The outage case, end to end: 'could not check', never 'will be created'."""
    from farm_agent.farmos import assets

    assets._clear_cache()

    async def get(path):
        return {"ok": False, "status": 500}

    db = FakeDb()
    p = create_extraction_pipeline(
        pool=None, extractor=_extractor({
            "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
            "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
            "usage": None,
        }), config=_config(),
        extraction_db=db, outbound_dispatcher={"dispatch": FakeDispatcher().dispatch},
        clock=lambda: 1_000_000,
        farmos_client={"get": get},
    )

    await p["enqueue"](CTX)

    _, _, extras = db.updates[-1]
    body = extras["farmer_facing_preview"]
    assert "Could not check farmOS: b1" in body
    assert "will be created" not in body
    assets._clear_cache()


async def test_without_a_farmos_client_the_preview_is_unchanged():
    """The check is additive: no client wired means the old body, not a crash."""
    db = FakeDb()
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }))

    await p["enqueue"](CTX)

    _, _, extras = db.updates[-1]
    assert "farmOS" not in extras["farmer_facing_preview"]


# ---------------------------------------------------------------------------
# MUSHY-109: an unknown strain holds the draft and asks before it reaches farmOS
# ---------------------------------------------------------------------------

SEEDING = {"type": "SeedingLog", "species_code": "POY", "qty": 10,
           "event_timestamp": "2026-05-22T10:00:00Z"}

SESSION = {
    "type": "seeding_session",
    "event_timestamp": "2026-05-22T10:00:00Z",
    "groups": [
        {"species": {"value": "KOY"}, "qty": 4},
        {"species": {"value": "poy"}, "qty": 2},   # lowercase -> same code as below
        {"species": {"value": "POY"}, "qty": 1},   # duplicate: ONE ask, not two
    ],
}


def _strain_pipeline(db, draft, get, dispatcher=None, config=None):
    return create_extraction_pipeline(
        pool=None,
        extractor=_extractor({
            "ok": True, "drafts": [{"draft": draft, "per_field_confidence": {}}],
            "draft": draft, "per_field_confidence": {}, "continuity_decision": "start_new",
            "usage": None,
        }),
        config=config or _config(),
        extraction_db=db,
        outbound_dispatcher={"dispatch": (dispatcher or FakeDispatcher()).dispatch},
        clock=lambda: 1_000_000,
        farmos_client={"get": get},
    )


def _fungi_get(known_names):
    """farmOS double: resolves only the names in known_names, 404-empty otherwise."""
    async def get(path):
        if any(path.endswith("=" + n) for n in known_names):
            return {"ok": True, "body": {"data": [{"id": "uuid-1"}]}}
        return {"ok": True, "body": {"data": []}}  # -> fungi_type_not_found
    return get


async def test_an_unknown_strain_holds_the_draft_and_asks_the_farmer():
    from farm_agent.farmos import fungi_type_cache
    fungi_type_cache._clear()

    db, disp = FakeDb(), FakeDispatcher()
    p = _strain_pipeline(db, SEEDING, _fungi_get([]), disp)

    res = await p["enqueue"](CTX)

    assert res["ok"] and res["status"] == DraftStatus.AWAITING_FARMER
    _, status, extras = db.updates[-1]
    assert status == DraftStatus.AWAITING_FARMER
    # The join key confirm/dispatch.py routes the farmer's reply on.
    assert extras["needs_review_reason"] == "strain_unknown_pending_confirm"
    assert "POY" in extras["farmer_facing_preview"]
    assert [e for e, _ in disp.calls] == ["send_strain_ask_back"]
    fungi_type_cache._clear()


async def test_a_known_strain_is_never_held():
    from farm_agent.farmos import fungi_type_cache
    fungi_type_cache._clear()

    db, disp = FakeDb(), FakeDispatcher()
    p = _strain_pipeline(db, SEEDING, _fungi_get(["POY"]), disp)

    await p["enqueue"](CTX)

    _, _, extras = db.updates[-1]
    assert extras.get("needs_review_reason") != "strain_unknown_pending_confirm"
    assert "send_strain_ask_back" not in [e for e, _ in disp.calls]
    fungi_type_cache._clear()


async def test_a_farmos_outage_passes_through_instead_of_nagging():
    """taxonomy_missing / HTTP error is our problem, not the farmer's."""
    from farm_agent.farmos import fungi_type_cache
    fungi_type_cache._clear()

    async def get(path):
        return {"ok": False, "status": 500}

    db, disp = FakeDb(), FakeDispatcher()
    p = _strain_pipeline(db, SEEDING, get, disp)

    await p["enqueue"](CTX)

    _, _, extras = db.updates[-1]
    assert extras.get("needs_review_reason") != "strain_unknown_pending_confirm"
    assert "send_strain_ask_back" not in [e for e, _ in disp.calls]
    fungi_type_cache._clear()


async def test_a_seeding_session_asks_once_for_each_distinct_unknown_code():
    """Codes live per-group on this shape, and duplicates get ONE batched ask."""
    from farm_agent.farmos import fungi_type_cache
    fungi_type_cache._clear()

    db, disp = FakeDb(), FakeDispatcher()
    p = _strain_pipeline(db, SESSION, _fungi_get(["KOY"]), disp)

    res = await p["enqueue"](CTX)

    assert res["status"] == DraftStatus.AWAITING_FARMER
    _, _, extras = db.updates[-1]
    body = extras["farmer_facing_preview"]
    assert body.count("Saw strain 'POY'") == 1
    assert "Saw strain 'KOY'" not in body  # the known code is never asked about
    assert len(disp.calls) == 1
    fungi_type_cache._clear()


async def test_without_a_farmos_client_the_gate_is_skipped():
    """Additive: an unwired deployment degrades to the old behaviour, not a crash."""
    db, disp = FakeDb(), FakeDispatcher()
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": SEEDING, "per_field_confidence": {}}],
        "draft": SEEDING, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }), dispatcher=disp)

    await p["enqueue"](CTX)

    _, _, extras = db.updates[-1]
    assert extras.get("needs_review_reason") != "strain_unknown_pending_confirm"
