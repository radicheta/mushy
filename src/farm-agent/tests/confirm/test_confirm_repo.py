"""
tests/confirm/test_confirm_repo.py -- DB-gated integration tests for confirm_repo.py.

Covers:
  DB-gated (@_requires_db):
    - test_dup_yes_idempotency (SC-2): confirm_draft twice; first rowcount==1, second==0;
      exactly one signal_draft_event with event='confirmed' for the draft_id.
    - test_concurrent_nudge_race (SC-3): asyncio.gather two mark_nudge_sent calls directly
      (bypassing any Lock); sorted rowcounts == [0, 1] proving the SQL guard wins the race.
    - test_update_draft_after_edit_status_guard (CR-01): update_draft_after_edit on an
      already-confirmed draft must return rowcount==0 (status guard prevents overwrite).
    - test_expire_draft_event_names (CR-02): expire_draft emits correct event name for
      each reason: 'edit_cap_exceeded' -> 'edit_cap_exceeded', 'superseded_by_newer_draft'
      -> 'superseded', 'timeout_expired' -> 'expired'.
    - test_find_awaiting_includes_commit_failed (CR-03): find_awaiting_for_sender returns
      a commit_failed draft when no awaiting_farmer draft exists for that sender.

DB-independent tests (always run): None in this file; see test_confirm_state_machine.py.

Skip pattern mirrors test_capture_repo.py -- requires postgres:14 on :5434.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import socket
import uuid

import pytest

import farm_agent.confirm.confirm_repo as confirm_repo


# ---------------------------------------------------------------------------
# DB reachability gate (mirrors test_capture_repo.py pattern)
# ---------------------------------------------------------------------------


def _db_reachable() -> bool:
    host = os.environ.get("TEST_TIMESCALE_HOST", "localhost")
    port_str = os.environ.get("TEST_TIMESCALE_PORT", "5434")
    try:
        with socket.create_connection((host, int(port_str)), timeout=2):
            return True
    except OSError:
        return False


_NO_DB_REASON = "no test DB reachable -- start postgres:14 on :5434"
_requires_db = pytest.mark.skipif(not _db_reachable(), reason=_NO_DB_REASON)


# ---------------------------------------------------------------------------
# Helper: insert a minimal awaiting_farmer signal_draft row
# ---------------------------------------------------------------------------

_INSERT_DRAFT_SQL = """
INSERT INTO signal_draft
  (id, status, sender_e164, edit_turn_count,
   nudge_sent_at, draft_json, per_field_confidence,
   farmer_facing_preview, reply_target_kind, created_at, updated_at)
VALUES (%s, 'awaiting_farmer', %s, 0, NULL,
        %s::jsonb, %s::jsonb, %s, 'dm',
        NOW(), NOW())
"""


async def _insert_draft(pool, *, sender_e164: str = "+10000000001") -> str:
    """Insert a minimal awaiting_farmer draft and return its id (hex string)."""
    draft_id = uuid.uuid4().hex
    async with pool.connection() as conn:
        await conn.execute(
            _INSERT_DRAFT_SQL,
            (
                draft_id,
                sender_e164,
                json.dumps({"species_code": "SHI", "substrate": "straw"}),
                json.dumps({"species_code": 0.95}),
                "SHI on straw -- confirm?",
            ),
        )
    return draft_id


# ---------------------------------------------------------------------------
# SC-2: dup-YES idempotency
# ---------------------------------------------------------------------------


@_requires_db
async def test_dup_yes_idempotency(pool):
    """Sending YES twice produces exactly one confirmed transition.

    SC-2 (CNF-01): first confirm_draft rowcount==1, second==0;
    exactly one signal_draft_event with event='confirmed' for this draft_id.
    """
    draft_id = await _insert_draft(pool)

    # First YES: must transition
    r1 = await confirm_repo.confirm_draft(pool, draft_id)
    assert r1["ok"] is True, f"first confirm_draft failed: {r1}"
    assert r1["rowcount"] == 1, f"expected rowcount=1, got {r1['rowcount']}"

    # Second YES: must be idempotent (race lost)
    r2 = await confirm_repo.confirm_draft(pool, draft_id)
    assert r2["ok"] is True, f"second confirm_draft failed: {r2}"
    assert r2["rowcount"] == 0, f"expected rowcount=0, got {r2['rowcount']}"

    # Exactly one 'confirmed' event must exist in signal_draft_event
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT COUNT(*) FROM signal_draft_event WHERE draft_id=%s AND event='confirmed'",
            (draft_id,),
        )
        row = await result.fetchone()
    event_count = row[0]
    assert event_count == 1, (
        f"expected exactly 1 'confirmed' event, got {event_count} "
        f"(SC-2: no double commit-trigger)"
    )


# ---------------------------------------------------------------------------
# SC-3: concurrent nudge race
# ---------------------------------------------------------------------------


@_requires_db
async def test_concurrent_nudge_race(pool):
    """Two concurrent mark_nudge_sent calls produce exactly one rowcount==1.

    SC-3 (CNF-02): calls the DAO function directly (bypassing any asyncio.Lock)
    via asyncio.gather, proving the SQL WHERE nudge_sent_at IS NULL guard is
    the correctness mechanism.

    sorted([r1['rowcount'], r2['rowcount']]) == [0, 1]
    """
    draft_id = await _insert_draft(pool)

    # Concurrent mark_nudge_sent -- bypasses any Lock, tests the SQL guard directly
    r1, r2 = await asyncio.gather(
        confirm_repo.mark_nudge_sent(pool, draft_id),
        confirm_repo.mark_nudge_sent(pool, draft_id),
    )

    assert r1["ok"] is True, f"r1 failed: {r1}"
    assert r2["ok"] is True, f"r2 failed: {r2}"

    rowcounts = sorted([r1["rowcount"], r2["rowcount"]])
    assert rowcounts == [0, 1], (
        f"expected [0, 1] rowcounts (one winner, one loser), got {rowcounts} "
        f"(SC-3: SQL nudge-race guard)"
    )


# ---------------------------------------------------------------------------
# Helper: insert a draft with a specific status (for CR-01/CR-02/CR-03)
# ---------------------------------------------------------------------------

_INSERT_DRAFT_STATUS_SQL = """
INSERT INTO signal_draft
  (id, status, sender_e164, edit_turn_count,
   nudge_sent_at, draft_json, per_field_confidence,
   farmer_facing_preview, reply_target_kind, created_at, updated_at)
VALUES (%s, %s, %s, 0, NULL,
        %s::jsonb, %s::jsonb, %s, 'dm',
        NOW(), NOW())
"""


async def _insert_draft_with_status(pool, status: str, *, sender_e164: str = "+10000000099") -> str:
    """Insert a draft with a specific status and return its id."""
    draft_id = uuid.uuid4().hex
    async with pool.connection() as conn:
        await conn.execute(
            _INSERT_DRAFT_STATUS_SQL,
            (
                draft_id,
                status,
                sender_e164,
                json.dumps({"species_code": "SHI", "substrate": "straw"}),
                json.dumps({"species_code": 0.95}),
                "SHI on straw -- confirm?",
            ),
        )
    return draft_id


# ---------------------------------------------------------------------------
# CR-01: update_draft_after_edit status guard
# ---------------------------------------------------------------------------


@_requires_db
async def test_update_draft_after_edit_status_guard(pool):
    """update_draft_after_edit on a confirmed draft returns rowcount==0 (status guard).

    CR-01: the WHERE id=%s AND status='awaiting_farmer' clause must prevent
    overwriting draft_json on a draft that has already been confirmed.
    Matches Node confirm-db.js:222-230 idempotency contract.
    """
    draft_id = await _insert_draft(pool)

    # Confirm the draft first
    r_confirm = await confirm_repo.confirm_draft(pool, draft_id)
    assert r_confirm["rowcount"] == 1, "setup: confirm_draft should succeed"

    # Now attempt an edit update -- must NOT touch the confirmed row
    r_edit = await confirm_repo.update_draft_after_edit(
        pool,
        draft_id,
        {"farmer_facing_preview": "OVERWRITTEN -- should not appear"},
    )
    assert r_edit["ok"] is True, f"update_draft_after_edit raised unexpectedly: {r_edit}"
    assert r_edit["rowcount"] == 0, (
        f"CR-01: expected rowcount=0 on confirmed draft, got {r_edit['rowcount']}. "
        "Status guard AND status='awaiting_farmer' is missing or broken."
    )

    # Verify the preview was NOT overwritten
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT farmer_facing_preview FROM signal_draft WHERE id=%s",
            (draft_id,),
        )
        row = await result.fetchone()
    assert row is not None, "draft row missing"
    assert row[0] == "SHI on straw -- confirm?", (
        f"CR-01: farmer_facing_preview was overwritten on a confirmed draft: {row[0]!r}"
    )


# ---------------------------------------------------------------------------
# CR-02: expire_draft event name mapping
# ---------------------------------------------------------------------------


@_requires_db
async def test_expire_draft_event_names(pool):
    """expire_draft emits the correct event name for each reason (CR-02).

    Node confirm-db.js:148-180 mapping:
      'edit_cap_exceeded'         -> event 'edit_cap_exceeded'
      'superseded_by_newer_draft' -> event 'superseded'
      'timeout_expired'           -> event 'expired'
    """
    # edit_cap_exceeded -> event 'edit_cap_exceeded'
    d1 = await _insert_draft(pool)
    r1 = await confirm_repo.expire_draft(pool, d1, "edit_cap_exceeded")
    assert r1["rowcount"] == 1, "setup: expire_draft edit_cap_exceeded should transition"
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT event FROM signal_draft_event WHERE draft_id=%s ORDER BY seq",
            (d1,),
        )
        events1 = [row[0] for row in await result.fetchall()]
    assert "edit_cap_exceeded" in events1, (
        f"CR-02: expected event 'edit_cap_exceeded' for reason='edit_cap_exceeded', got {events1}"
    )
    assert "expired" not in events1, (
        f"CR-02: event 'expired' must NOT be emitted for edit_cap_exceeded, got {events1}"
    )

    # superseded_by_newer_draft -> event 'superseded'
    d2 = await _insert_draft(pool)
    r2 = await confirm_repo.expire_draft(pool, d2, "superseded_by_newer_draft")
    assert r2["rowcount"] == 1, "setup: expire_draft superseded should transition"
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT event FROM signal_draft_event WHERE draft_id=%s ORDER BY seq",
            (d2,),
        )
        events2 = [row[0] for row in await result.fetchall()]
    assert "superseded" in events2, (
        f"CR-02: expected event 'superseded' for reason='superseded_by_newer_draft', got {events2}"
    )
    assert "expired" not in events2, (
        f"CR-02: event 'expired' must NOT be emitted for superseded_by_newer_draft, got {events2}"
    )

    # timeout_expired -> event 'expired'
    d3 = await _insert_draft(pool)
    r3 = await confirm_repo.expire_draft(pool, d3, "timeout_expired")
    assert r3["rowcount"] == 1, "setup: expire_draft timeout_expired should transition"
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT event FROM signal_draft_event WHERE draft_id=%s ORDER BY seq",
            (d3,),
        )
        events3 = [row[0] for row in await result.fetchall()]
    assert "expired" in events3, (
        f"CR-02: expected event 'expired' for reason='timeout_expired', got {events3}"
    )


# ---------------------------------------------------------------------------
# CR-03: find_awaiting_for_sender includes commit_failed
# ---------------------------------------------------------------------------


@_requires_db
async def test_find_awaiting_includes_commit_failed(pool):
    """find_awaiting_for_sender returns a commit_failed draft when no awaiting_farmer exists (CR-03).

    Port of Node findAwaitingForSender Phase 45 Plan 04 follow-on: without
    commit_failed in the status filter, an EDIT reply on a failed commit falls
    through to the capture pipeline instead of reaching the edit-handler.
    """
    sender = f"+1999{uuid.uuid4().hex[:7]}"  # unique sender per test run

    # Insert only a commit_failed draft (no awaiting_farmer for this sender)
    draft_id = await _insert_draft_with_status(pool, "commit_failed", sender_e164=sender)

    row = await confirm_repo.find_awaiting_for_sender(pool, sender)

    assert row is not None, (
        f"CR-03: find_awaiting_for_sender returned None for a commit_failed draft. "
        "commit_failed must be included in the status filter."
    )
    assert row["id"] == draft_id, (
        f"CR-03: expected draft_id={draft_id}, got {row['id']!r}"
    )
    assert row["status"] == "commit_failed", (
        f"CR-03: expected status='commit_failed', got {row['status']!r}"
    )


@_requires_db
async def test_find_awaiting_prefers_awaiting_farmer_over_commit_failed(pool):
    """find_awaiting_for_sender prefers awaiting_farmer over commit_failed (CR-03 ordering).

    When both statuses exist for the same sender, awaiting_farmer wins.
    """
    sender = f"+1888{uuid.uuid4().hex[:7]}"

    # Insert commit_failed first, then awaiting_farmer
    _cf_id = await _insert_draft_with_status(pool, "commit_failed", sender_e164=sender)
    af_id = await _insert_draft_with_status(pool, "awaiting_farmer", sender_e164=sender)

    row = await confirm_repo.find_awaiting_for_sender(pool, sender)

    assert row is not None, "find_awaiting_for_sender returned None unexpectedly"
    assert row["id"] == af_id, (
        f"CR-03 ordering: awaiting_farmer must win over commit_failed, "
        f"expected {af_id}, got {row['id']!r}"
    )


# ---------------------------------------------------------------------------
# Task 8c: find_active_drafts_for_sender (MUSHY-76 confirm-reply router)
# ---------------------------------------------------------------------------


async def _insert_draft_with_updated_at(
    pool, status: str, updated_at_expr: str, *, sender_e164: str
) -> str:
    """Insert a draft with a specific status and an explicit updated_at offset.

    updated_at_expr is a raw SQL expression (e.g. "NOW() - interval '7 hours'")
    -- safe here because it is a fixed literal supplied by the test, never
    farmer input.
    """
    draft_id = uuid.uuid4().hex
    async with pool.connection() as conn:
        await conn.execute(
            f"""
            INSERT INTO signal_draft
              (id, status, sender_e164, edit_turn_count, nudge_sent_at,
               draft_json, per_field_confidence, farmer_facing_preview,
               reply_target_kind, created_at, updated_at)
            VALUES (%s, %s, %s, 0, NULL, %s::jsonb, %s::jsonb, %s, 'dm',
                    NOW(), {updated_at_expr})
            """,  # noqa: S608 -- updated_at_expr is a fixed test literal, not farmer input
            (
                draft_id,
                status,
                sender_e164,
                json.dumps({"species_code": "SHI"}),
                json.dumps({"species_code": 0.95}),
                "SHI on straw -- confirm?",
            ),
        )
    return draft_id


@_requires_db
async def test_find_active_drafts_includes_awaiting_and_recent_commit_failed(pool):
    """find_active_drafts_for_sender returns both an awaiting_farmer AND a recent
    commit_failed draft for the same sender, awaiting_farmer first (CONTEXT D-06).
    """
    sender = f"+1777{uuid.uuid4().hex[:7]}"
    cf_id = await _insert_draft_with_status(pool, "commit_failed", sender_e164=sender)
    af_id = await _insert_draft_with_status(pool, "awaiting_farmer", sender_e164=sender)

    rows = await confirm_repo.find_active_drafts_for_sender(pool, sender)

    ids = [r["id"] for r in rows]
    assert ids == [af_id, cf_id], (
        f"expected [awaiting_farmer, commit_failed] order, got {ids}"
    )


@_requires_db
async def test_find_active_drafts_ages_out_stale_commit_failed(pool):
    """2026-05-23 staleness filter: commit_failed older than 6h is excluded.

    Without this filter, a ten-day-old ack-debt draft would trap every fresh
    capture in the numbered ask-back forever.
    """
    sender = f"+1666{uuid.uuid4().hex[:7]}"
    await _insert_draft_with_updated_at(
        pool, "commit_failed", "NOW() - interval '10 days'", sender_e164=sender
    )

    rows = await confirm_repo.find_active_drafts_for_sender(pool, sender)

    assert rows == [], (
        "a commit_failed draft older than 6h must be excluded from the active-draft "
        "lookup -- otherwise it traps every fresh capture in numbered ask-back"
    )


@_requires_db
async def test_find_active_drafts_returns_empty_for_no_active(pool):
    sender = f"+1555{uuid.uuid4().hex[:7]}"
    rows = await confirm_repo.find_active_drafts_for_sender(pool, sender)
    assert rows == []


# ---------------------------------------------------------------------------
# Task 8c: find_draft_by_quoted_msg_ts (MUSHY-76 confirm-reply router)
# ---------------------------------------------------------------------------


async def _insert_outbound(pool, *, related_draft_id: str, signal_msg_ts: int, recipient_e164: str) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO signal_outbound
              (tenant_id, sent_at, recipient_e164, intent, body, source_module,
               related_draft_id, signal_msg_ts)
            VALUES ('test', NOW(), %s, 'confirm_prompt', 'body', 'test', %s, %s)
            """,
            (recipient_e164, related_draft_id, signal_msg_ts),
        )


@_requires_db
async def test_find_draft_by_quoted_msg_ts_resolves_via_outbound_join(pool):
    sender = f"+1444{uuid.uuid4().hex[:7]}"
    draft_id = await _insert_draft(pool, sender_e164=sender)
    quote_ts = 1_700_000_000_000
    await _insert_outbound(pool, related_draft_id=draft_id, signal_msg_ts=quote_ts, recipient_e164=sender)

    row = await confirm_repo.find_draft_by_quoted_msg_ts(pool, quote_ts)

    assert row is not None
    assert row["id"] == draft_id
    assert row["sender_e164"] == sender


@_requires_db
async def test_find_draft_by_quoted_msg_ts_returns_none_when_unmatched(pool):
    row = await confirm_repo.find_draft_by_quoted_msg_ts(pool, 9_999_999_999_999)
    assert row is None


async def test_find_draft_by_quoted_msg_ts_returns_none_for_none_ts():
    """No DB required -- the None guard short-circuits before any query."""
    row = await confirm_repo.find_draft_by_quoted_msg_ts(object(), None)
    assert row is None
