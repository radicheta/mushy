"""
confirm/confirm_repo.py -- Never-throws psycopg3 DAO for signal_draft + signal_draft_event.

Port of src/agents/alerter/src/confirm/confirm-db.js.
Mirrors capture/capture_repo.py never-throws discriminated-result pattern.

Every public function wraps its body in try/except Exception (noqa BLE001) and returns
{"ok": False, "reason": str(e)} on failure; never raises.  find_* candidates return []
on error.  find_awaiting_for_sender returns None on error.

SQL guards (verbatim from Node, $1 -> %s):
  confirm_draft:     WHERE id=%s AND status='awaiting_farmer' RETURNING id
  mark_nudge_sent:   WHERE id=%s AND nudge_sent_at IS NULL RETURNING id
  expire/discard:    WHERE id=%s AND status='awaiting_farmer' RETURNING id

rowcount == 1 = transition happened; rowcount == 0 = race lost / already transitioned.
Interval predicates use (%s || ' minutes')::interval with str(n) -- per capture_repo.py pattern.

CNF-01: confirm_draft idempotency (dup-YES SQL guard).
CNF-02: mark_nudge_sent race guard (nudge-race SQL guard).
T-61-01/02/03/04/05 mitigations applied.
"""

from __future__ import annotations

import json
import logging

from psycopg_pool import AsyncConnectionPool

from farm_agent.tenancy.tenant import mask_number

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_CONFIRM_SQL = """
UPDATE signal_draft
   SET status='confirmed',
       confirmed_at=NOW(),
       terminal_reason='farmer_yes',
       updated_at=NOW()
 WHERE id=%s AND status='awaiting_farmer'
 RETURNING id
"""

_DISCARD_SQL = """
UPDATE signal_draft
   SET status='discarded',
       discarded_at=NOW(),
       terminal_reason='farmer_no',
       updated_at=NOW()
 WHERE id=%s AND status='awaiting_farmer'
 RETURNING id
"""

# expire_draft: two variants by reason
_EXPIRE_SQL_TERMINAL = """
UPDATE signal_draft
   SET status='expired',
       expired_at=NOW(),
       terminal_reason=%s,
       updated_at=NOW()
 WHERE id=%s AND status='awaiting_farmer'
 RETURNING id
"""

_EXPIRE_SQL_NEEDS_REVIEW = """
UPDATE signal_draft
   SET status='needs_review',
       terminal_reason=%s,
       updated_at=NOW()
 WHERE id=%s AND status='awaiting_farmer'
 RETURNING id
"""

_NUDGE_SQL = """
UPDATE signal_draft
   SET nudge_sent_at=NOW(),
       updated_at=NOW()
 WHERE id=%s AND nudge_sent_at IS NULL
 RETURNING id
"""

_BUMP_EDIT_SQL = """
UPDATE signal_draft
   SET edit_turn_count=edit_turn_count+1
 WHERE id=%s AND status='awaiting_farmer'
 RETURNING edit_turn_count
"""

_AWAITING_FOR_SENDER_SQL = """
SELECT id, status, sender_e164, edit_turn_count, nudge_sent_at,
       confirmed_at, discarded_at, expired_at, terminal_reason,
       needs_review_reason, draft_json, per_field_confidence,
       farmer_facing_preview, updated_at, reply_target_kind, group_id
  FROM signal_draft
 WHERE sender_e164=%s
   AND status IN ('awaiting_farmer', 'commit_failed')
 ORDER BY CASE status WHEN 'awaiting_farmer' THEN 0 ELSE 1 END ASC,
          updated_at DESC
 LIMIT 1
"""
# Phase 45 Plan 04 follow-on (ported from Node confirm-db.js:236-260):
# include commit_failed in the active-draft lookup so EDIT replies from a
# farmer on a failed commit actually reach the edit-handler instead of
# falling through to the capture pipeline and creating a new observation.
# Ordering: awaiting_farmer wins over commit_failed when both exist for the
# same sender; within the same status, most recent updated_at wins.

_NUDGE_CANDIDATES_SQL = """
SELECT id, sender_e164, reply_target_kind, group_id,
       farmer_facing_preview, updated_at
  FROM signal_draft
 WHERE status='awaiting_farmer'
   AND nudge_sent_at IS NULL
   AND updated_at < NOW() - (%s || ' minutes')::interval
"""

_EXPIRE_CANDIDATES_SQL = """
SELECT id, sender_e164, reply_target_kind, group_id,
       farmer_facing_preview, updated_at
  FROM signal_draft
 WHERE status='awaiting_farmer'
   AND updated_at < NOW() - (%s || ' minutes')::interval
"""

_APPEND_EVENT_SQL = """
INSERT INTO signal_draft_event (draft_id, seq, event, payload, created_at)
VALUES (
    %s,
    (SELECT COALESCE(MAX(seq), 0) + 1 FROM signal_draft_event WHERE draft_id=%s),
    %s,
    %s::jsonb,
    NOW()
)
RETURNING seq
"""


# ---------------------------------------------------------------------------
# Transition functions (transactional -- confirm, discard, expire)
# ---------------------------------------------------------------------------


async def confirm_draft(pool: AsyncConnectionPool, draft_id: str) -> dict:
    """Confirm a draft atomically.

    Returns {"ok": True, "rowcount": 1} if the transition happened (rowcount=1 means
    caller should emit commit-trigger).  Returns {"ok": True, "rowcount": 0} if the
    draft was already confirmed (race lost -- idempotent, no second trigger).

    NEVER raises (T-61-05).
    """
    try:
        async with pool.connection() as conn:
            async with conn.transaction():
                result = await conn.execute(_CONFIRM_SQL, (draft_id,))
                if result.rowcount == 1:
                    await append_event(conn, draft_id, "confirmed", {"terminal_reason": "farmer_yes"})
        return {"ok": True, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[confirm_repo] confirm_draft failed draft_id=%s: %s", draft_id, e)
        return {"ok": False, "reason": str(e)}


async def discard_draft(pool: AsyncConnectionPool, draft_id: str) -> dict:
    """Discard a draft atomically.

    Returns {"ok": True, "rowcount": 1|0}.  rowcount=0 means already discarded/transitioned.
    NEVER raises (T-61-05).
    """
    try:
        async with pool.connection() as conn:
            async with conn.transaction():
                result = await conn.execute(_DISCARD_SQL, (draft_id,))
                if result.rowcount == 1:
                    await append_event(conn, draft_id, "discarded", {"terminal_reason": "farmer_no"})
        return {"ok": True, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[confirm_repo] discard_draft failed draft_id=%s: %s", draft_id, e)
        return {"ok": False, "reason": str(e)}


async def expire_draft(pool: AsyncConnectionPool, draft_id: str, reason: str) -> dict:
    """Expire or needs_review a draft atomically.

    reason='timeout_expired' | 'superseded_by_newer_draft' -> status='expired' (expired_at set)
    reason='edit_cap_exceeded' -> status='needs_review' (NO expired_at)

    Returns {"ok": True, "rowcount": 1|0}.  rowcount=0 means already transitioned.
    NEVER raises (T-61-05).
    """
    try:
        if reason == "edit_cap_exceeded":
            sql = _EXPIRE_SQL_NEEDS_REVIEW
        else:
            sql = _EXPIRE_SQL_TERMINAL
        # Map reason to event name -- matching Node confirm-db.js:148-180 exactly:
        #   'edit_cap_exceeded'          -> 'edit_cap_exceeded'
        #   'superseded_by_newer_draft'  -> 'superseded'
        #   'timeout_expired' (or other) -> 'expired'
        _event_name_map = {
            "edit_cap_exceeded": "edit_cap_exceeded",
            "superseded_by_newer_draft": "superseded",
        }
        event_name = _event_name_map.get(reason, "expired")
        async with pool.connection() as conn:
            async with conn.transaction():
                result = await conn.execute(sql, (reason, draft_id))
                if result.rowcount == 1:
                    await append_event(conn, draft_id, event_name, {"terminal_reason": reason})
        return {"ok": True, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[confirm_repo] expire_draft failed draft_id=%s reason=%s: %s", draft_id, reason, e)
        return {"ok": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# Nudge (pool-level, no transaction -- per Node markNudgeSent behavior)
# ---------------------------------------------------------------------------


async def mark_nudge_sent(pool: AsyncConnectionPool, draft_id: str) -> dict:
    """Mark a draft as nudged (one-shot, race-safe via SQL guard).

    Uses pool.connection() directly (no explicit transaction) -- matching Node behavior
    where markNudgeSent is a plain pool query, not a _runTransition.

    Returns {"ok": True, "rowcount": 1} if we won the race; {"ok": True, "rowcount": 0}
    if another concurrent call already set nudge_sent_at (race lost -- no nudge to send).

    NEVER raises (T-61-05).
    """
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_NUDGE_SQL, (draft_id,))
        return {"ok": True, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[confirm_repo] mark_nudge_sent failed draft_id=%s: %s", draft_id, e)
        return {"ok": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# Edit helpers
# ---------------------------------------------------------------------------


async def bump_edit_turn(pool: AsyncConnectionPool, draft_id: str) -> dict:
    """Increment edit_turn_count for an awaiting_farmer draft.

    Returns {"ok": True, "edit_turn_count": int, "rowcount": 1|0}.
    rowcount=0 means the draft was not awaiting_farmer.
    NEVER raises (T-61-05).
    """
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_BUMP_EDIT_SQL, (draft_id,))
            if result.rowcount == 1:
                row = await result.fetchone()
                edit_turn_count = row[0] if row else None
            else:
                edit_turn_count = None
        return {"ok": True, "edit_turn_count": edit_turn_count, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[confirm_repo] bump_edit_turn failed draft_id=%s: %s", draft_id, e)
        return {"ok": False, "reason": str(e)}


async def update_draft_after_edit(
    pool: AsyncConnectionPool,
    draft_id: str,
    fields: dict,
) -> dict:
    """Update draft_json, per_field_confidence, farmer_facing_preview after edit reextraction.

    fields dict keys (all optional, only present keys are updated):
      draft_json            -- updated jsonb value
      per_field_confidence  -- updated jsonb value
      farmer_facing_preview -- updated text value

    Returns {"ok": True, "rowcount": int}.
    NEVER raises (T-61-05).
    """
    sets = []
    params: list = []

    if "draft_json" in fields:
        sets.append("draft_json=%s::jsonb")
        params.append(json.dumps(fields["draft_json"]) if fields["draft_json"] is not None else None)
    if "per_field_confidence" in fields:
        sets.append("per_field_confidence=%s::jsonb")
        params.append(
            json.dumps(fields["per_field_confidence"])
            if fields["per_field_confidence"] is not None
            else None
        )
    if "farmer_facing_preview" in fields:
        sets.append("farmer_facing_preview=%s")
        params.append(fields["farmer_facing_preview"])

    if not sets:
        return {"ok": True, "rowcount": 0}

    sets.append("updated_at=NOW()")
    # noqa: S608 -- safe: sets[] contains only literal column assignments; all values parameterized
    sql = f"UPDATE signal_draft SET {', '.join(sets)} WHERE id=%s AND status='awaiting_farmer'"  # noqa: S608
    params.append(draft_id)

    try:
        async with pool.connection() as conn:
            result = await conn.execute(sql, tuple(params))
        return {"ok": True, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[confirm_repo] update_draft_after_edit failed draft_id=%s: %s", draft_id, e)
        return {"ok": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# Finder queries (return [] / None on error -- never raise)
# ---------------------------------------------------------------------------


async def find_awaiting_for_sender(pool: AsyncConnectionPool, sender_e164: str) -> dict | None:
    """Return the most recent awaiting_farmer draft for sender_e164, or None.

    Scopes lookup by sender_e164 (T-61-03 spoofing mitigation).
    NEVER raises (T-61-05).
    """
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_AWAITING_FOR_SENDER_SQL, (sender_e164,))
            row = await result.fetchone()
        if row is None:
            return None
        cols = [
            "id", "status", "sender_e164", "edit_turn_count", "nudge_sent_at",
            "confirmed_at", "discarded_at", "expired_at", "terminal_reason",
            "needs_review_reason", "draft_json", "per_field_confidence",
            "farmer_facing_preview", "updated_at", "reply_target_kind", "group_id",
        ]
        return dict(zip(cols, row, strict=False))
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[confirm_repo] find_awaiting_for_sender failed sender=%s: %s",
            mask_number(sender_e164),
            e,
        )
        return None


async def find_nudge_candidates(pool: AsyncConnectionPool, nudge_min: int) -> list[dict]:
    """Return awaiting_farmer rows that are past the nudge threshold.

    WHERE status='awaiting_farmer' AND nudge_sent_at IS NULL
      AND updated_at < NOW() - nudge_min minutes

    Returns [] on error (T-61-05).
    """
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_NUDGE_CANDIDATES_SQL, (str(nudge_min),))
            rows = await result.fetchall()
        cols = ["id", "sender_e164", "reply_target_kind", "group_id", "farmer_facing_preview", "updated_at"]
        return [dict(zip(cols, row, strict=False)) for row in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("[confirm_repo] find_nudge_candidates failed nudge_min=%s: %s", nudge_min, e)
        return []


async def find_expire_candidates(pool: AsyncConnectionPool, timeout_min: int) -> list[dict]:
    """Return awaiting_farmer rows that are past the expiry threshold.

    WHERE status='awaiting_farmer'
      AND updated_at < NOW() - timeout_min minutes

    Returns [] on error (T-61-05).
    """
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_EXPIRE_CANDIDATES_SQL, (str(timeout_min),))
            rows = await result.fetchall()
        cols = ["id", "sender_e164", "reply_target_kind", "group_id", "farmer_facing_preview", "updated_at"]
        return [dict(zip(cols, row, strict=False)) for row in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("[confirm_repo] find_expire_candidates failed timeout_min=%s: %s", timeout_min, e)
        return []


# ---------------------------------------------------------------------------
# Event append helpers
# ---------------------------------------------------------------------------


async def append_event(
    conn: object,
    draft_id: str,
    event: str,
    payload: dict | None,
) -> dict:
    """Append a signal_draft_event row using an OPEN connection.

    Must be called INSIDE a caller-owned transaction (conn.transaction() context).
    Uses a subquery for the seq to ensure monotonic ordering per draft_id.

    payload is serialized via json.dumps; None -> passes NULL (::jsonb handles NULL).

    Returns {"ok": True, "seq": int} or {"ok": False, "reason": str}.
    NEVER raises (T-61-05) -- caller checks ok before proceeding.
    """
    payload_json = json.dumps(payload) if payload is not None else None
    try:
        result = await conn.execute(
            _APPEND_EVENT_SQL,
            (draft_id, draft_id, event, payload_json),
        )
        row = await result.fetchone()
        seq = row[0] if row else None
        return {"ok": True, "seq": seq}
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[confirm_repo] append_event failed draft_id=%s event=%s: %s",
            draft_id,
            event,
            e,
        )
        return {"ok": False, "reason": str(e)}


async def append_event_via_pool(
    pool: AsyncConnectionPool,
    draft_id: str,
    event: str,
    payload: dict | None,
) -> dict:
    """Pool-level overload of append_event: opens its own connection.

    Used by the watchdog for nudge_sent events, which have no outer transaction.
    Returns {"ok": True, "seq": int} or {"ok": False, "reason": str}.
    NEVER raises (T-61-05).
    """
    payload_json = json.dumps(payload) if payload is not None else None
    try:
        async with pool.connection() as conn:
            result = await conn.execute(
                _APPEND_EVENT_SQL,
                (draft_id, draft_id, event, payload_json),
            )
            row = await result.fetchone()
            seq = row[0] if row else None
        return {"ok": True, "seq": seq}
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[confirm_repo] append_event_via_pool failed draft_id=%s event=%s: %s",
            draft_id,
            event,
            e,
        )
        return {"ok": False, "reason": str(e)}
