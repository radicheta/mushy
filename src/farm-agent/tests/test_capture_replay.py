"""
tests/test_capture_replay.py -- Unit tests for capture/replay.py (MUSHY-87).

TDD RED: written before the module exists.

Behaviors covered:
  build_capture_ctx anchors extraction to the ORIGINAL captured_at, not replay time
  build_capture_ctx carries transcript / attachments / reply target through
  replay_scoped_db mints a replay-scoped draft id that cannot collide with the live one
  ... deterministic per marker, distinct across markers, index-suffix semantics kept
  ... every other extraction_db attribute is delegated untouched
  replay_captures drives captures in captured_at order
  replay_captures dry-runs by default -- nothing is enqueued without apply=True
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# build_capture_ctx
# ---------------------------------------------------------------------------


def _row(**over) -> dict:
    row = {
        "id": "01J0CAP0000000000000000001",
        "captured_at": datetime(2026, 8, 16, 14, 30, 0, tzinfo=timezone.utc),
        "sender": "+59891111111",
        "raw_text": "4 bags WIN",
        "transcript": None,
        "attachment_paths": [],
        "farmos_person": "farmer1",
        "reply_target_kind": "dm",
        "group_id": None,
    }
    row.update(over)
    return row


def test_build_capture_ctx_anchors_to_the_original_capture_time():
    """The extraction date anchor is when the farmer sent it, not when we replayed."""
    from farm_agent.capture.replay import build_capture_ctx

    ctx = build_capture_ctx(_row())

    expected_ms = int(
        datetime(2026, 8, 16, 14, 30, 0, tzinfo=timezone.utc).timestamp() * 1000
    )
    assert ctx["captured_at_ms"] == expected_ms


def test_build_capture_ctx_carries_the_stored_capture_through():
    """Text, transcript, attachments and reply target come from the stored row."""
    from farm_agent.capture.replay import build_capture_ctx

    ctx = build_capture_ctx(
        _row(
            transcript="four bags of winter oyster",
            attachment_paths=["/data/captures/a.jpg"],
            reply_target_kind="group",
            group_id="grp-1",
        )
    )

    assert ctx["capture_id"] == "01J0CAP0000000000000000001"
    assert ctx["sender"] == "+59891111111"
    assert ctx["farmos_person"] == "farmer1"
    assert ctx["text"] == "4 bags WIN"
    assert ctx["transcripts"] == ["four bags of winter oyster"]
    assert ctx["attachment_paths"] == ["/data/captures/a.jpg"]
    assert ctx["reply_target_kind"] == "group"
    assert ctx["group_id"] == "grp-1"
    assert ctx["corpus_context"] is None


def test_build_capture_ctx_omits_a_missing_transcript():
    """No transcript means no transcripts entry, not a [None] the extractor would join."""
    from farm_agent.capture.replay import build_capture_ctx

    assert build_capture_ctx(_row(transcript=None))["transcripts"] == []


# ---------------------------------------------------------------------------
# replay_scoped_db
# ---------------------------------------------------------------------------


def test_replay_draft_id_cannot_collide_with_the_live_draft():
    """insert_draft has no upsert, so a replay must not reuse the original id."""
    from farm_agent.capture.replay import replay_scoped_db
    from farm_agent.extraction import extraction_db

    proxy = replay_scoped_db(extraction_db, "2026-08-20T12:00:00Z")

    ids = ["cap-b", "cap-a"]
    assert proxy.compute_draft_id(ids) != extraction_db.compute_draft_id(ids)


def test_replay_draft_id_is_stable_within_one_replay_run():
    """Same marker, same captures -- same id, whatever order they arrive in."""
    from farm_agent.capture.replay import replay_scoped_db
    from farm_agent.extraction import extraction_db

    proxy = replay_scoped_db(extraction_db, "run-1")

    assert proxy.compute_draft_id(["cap-b", "cap-a"]) == proxy.compute_draft_id(
        ["cap-a", "cap-b"]
    )


def test_replay_draft_id_differs_between_replay_runs():
    """Replaying twice must not collide with the first replay either."""
    from farm_agent.capture.replay import replay_scoped_db
    from farm_agent.extraction import extraction_db

    first = replay_scoped_db(extraction_db, "run-1")
    second = replay_scoped_db(extraction_db, "run-2")

    assert first.compute_draft_id(["cap-a"]) != second.compute_draft_id(["cap-a"])


def test_replay_draft_id_keeps_the_multi_draft_index_distinction():
    """Batch mode mints one id per draft index; the replay ids must stay distinct."""
    from farm_agent.capture.replay import replay_scoped_db
    from farm_agent.extraction import extraction_db

    proxy = replay_scoped_db(extraction_db, "run-1")

    assert proxy.compute_draft_id(["cap-a"], 0) == proxy.compute_draft_id(["cap-a"], None)
    assert proxy.compute_draft_id(["cap-a"], 2) != proxy.compute_draft_id(["cap-a"], 1)


def test_replay_scoped_db_delegates_everything_else():
    """Only the id changes -- the DAO the pipeline writes through is the real one."""
    from farm_agent.capture.replay import replay_scoped_db
    from farm_agent.extraction import extraction_db

    proxy = replay_scoped_db(extraction_db, "run-1")

    assert proxy.insert_draft is extraction_db.insert_draft
    assert proxy.update_draft_status is extraction_db.update_draft_status


# ---------------------------------------------------------------------------
# replay_captures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_captures_drives_captures_in_captured_at_order():
    """Continuity and multimodal fusion depend on the original arrival order."""
    from farm_agent.capture.replay import replay_captures

    seen = []

    async def enqueue(ctx):
        seen.append(ctx["capture_id"])
        return {"ok": True}

    rows = [
        _row(id="cap-late", captured_at=datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)),
        _row(id="cap-early", captured_at=datetime(2026, 8, 16, 14, 0, tzinfo=timezone.utc)),
    ]

    await replay_captures(rows=rows, enqueue=enqueue, apply=True)

    assert seen == ["cap-early", "cap-late"]


@pytest.mark.asyncio
async def test_replay_captures_dry_runs_by_default():
    """Without apply, a replay reports the plan and touches nothing."""
    from farm_agent.capture.replay import replay_captures

    async def enqueue(ctx):
        raise AssertionError("dry run must not enqueue")

    results = await replay_captures(rows=[_row(id="cap-a")], enqueue=enqueue, apply=False)

    assert [r["capture_id"] for r in results] == ["cap-a"]
    assert all(r["applied"] is False for r in results)


# ---------------------------------------------------------------------------
# replay_scoped_db -- in-flight isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_does_not_append_to_the_farmers_live_draft():
    """A replay within the idle gap must not extend the draft it is superseding."""
    from farm_agent.capture.replay import replay_scoped_db

    class _Base:
        async def get_in_flight_for_sender(self, pool, sender):
            return {"id": "live-draft", "sender_e164": sender}

    proxy = replay_scoped_db(_Base(), "run-1")

    assert await proxy.get_in_flight_for_sender(None, "+59891111111") is None


@pytest.mark.asyncio
async def test_replay_keeps_continuity_across_its_own_captures():
    """The second capture of a replayed session still appends to the first's draft."""
    from farm_agent.capture.replay import replay_scoped_db

    minted = {}

    class _Base:
        async def get_in_flight_for_sender(self, pool, sender):
            return {"id": minted["id"], "sender_e164": sender}

    proxy = replay_scoped_db(_Base(), "run-1")
    minted["id"] = proxy.compute_draft_id(["cap-a"])

    in_flight = await proxy.get_in_flight_for_sender(None, "+59891111111")
    assert in_flight is not None and in_flight["id"] == minted["id"]
