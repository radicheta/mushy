"""farm_agent/farmos/commit_db.py -- Python commit-lifecycle DAO for signal_draft.

Faithful Python port of src/agents/alerter/src/farmos/commit-db.js
(Phase 40 D-02 / Phase 62-10).

ORIGIN GUARD (Phase 62 D-01 / T-62-27):
  The live Node watchdog SELECTs `WHERE status='confirmed' AND origin != 'python'`
  to avoid draining Python-owned rows. This Python side is the mirror:
    - find_confirmed_candidates: SELECT WHERE status='confirmed' AND origin='python'
    - acquire_commit_lock, mark_committed, requeue_for_retry: SET origin='python'
  Any Python-touched row stays Python-owned and the live Node watchdog ignores it.

Write helpers are never-throws (try/except Exception) returning
  {"ok": True, "rowcount": n} | {"ok": False, "reason": str(e)}
find_* queries return [] on error.

SQL port notes:
  - Node $1/$2 -> Python %s/%s (psycopg3 paramstyle)
  - staleMin String cast -> str(stale_min) with interval-as-string pattern
  - JSON serialized via json.dumps (None -> NULL)
  - No CHECK constraint reliance -- statuses validated in application code

No em-dashes in source artifacts.
"""
from __future__ import annotations

import json
import logging

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

# Phase 62 D-01: origin='python' guard in SELECT.
# The Node watchdog selects WHERE origin != 'python'; Python side selects WHERE origin='python'.
_FIND_CONFIRMED_SQL = """
SELECT * FROM signal_draft
 WHERE status='confirmed'
   AND origin='python'
 ORDER BY confirmed_at ASC NULLS LAST
 LIMIT %s
"""

_ACQUIRE_LOCK_SQL = """
UPDATE signal_draft
   SET status='committing',
       committed_at_attempt=NOW(),
       commit_attempt_count=commit_attempt_count + 1,
       origin='python'
 WHERE id=%s AND status='confirmed'
 RETURNING *
"""

_MARK_COMMITTED_SQL = """
UPDATE signal_draft
   SET status='committed',
       farmos_response=%s::jsonb,
       committed_at=NOW(),
       origin='python'
 WHERE id=%s AND status='committing'
"""

_MARK_FAILED_SQL = """
UPDATE signal_draft
   SET status='commit_failed',
       commit_failed_reason=%s,
       commit_failed_transport=%s,
       committed_at=NOW()
 WHERE id=%s AND status='committing'
"""

# NOTE: committed_at_attempt is PRESERVED across requeue so the watchdog
# backoff gate can compare now() - prev. releaseStaleLocks NULLs it back.
_REQUEUE_SQL = """
UPDATE signal_draft
   SET status='confirmed',
       origin='python'
 WHERE id=%s AND status='committing'
"""

_RELEASE_STALE_SQL = """
UPDATE signal_draft
   SET status='confirmed',
       committed_at_attempt=NULL
 WHERE status='committing'
   AND committed_at_attempt < NOW() - (%s || ' minutes')::interval
 RETURNING id
"""

# Phase 62 D-06: hold draft as fidelity_cross_check_unverified (T-62-30 / FWR-03).
# Transition from 'committing' (lock already acquired) to the hold status.
# origin='python' preserved so the Node watchdog does not pick it up.
_HOLD_FIDELITY_SQL = """
UPDATE signal_draft
   SET status='fidelity_cross_check_unverified',
       origin='python'
 WHERE id=%s AND status='committing'
"""


# ---------------------------------------------------------------------------
# Finder queries (return [] on error -- never raise)
# ---------------------------------------------------------------------------


async def find_confirmed_candidates(
    pool: AsyncConnectionPool, batch_cap: int = 10
) -> list[dict]:
    """SELECT confirmed rows owned by Python (origin='python').

    Returns [] on error (never raises).
    psycopg3: conn.execute() returns a cursor; cursor.description gives column names.
    """
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(_FIND_CONFIRMED_SQL, (batch_cap,))
            rows = await cur.fetchall()
        if not rows:
            return []
        col_names = [d.name for d in cur.description]
        return [dict(zip(col_names, row, strict=False)) for row in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("[commit_db] find_confirmed_candidates failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Write helpers (never raise; return {ok, rowcount} or {ok, reason})
# ---------------------------------------------------------------------------


async def acquire_commit_lock(pool: AsyncConnectionPool, draft_id: str) -> dict:
    """Atomic CAS: status='confirmed' -> 'committing', SET origin='python'.

    rowcount=1: lock acquired (caller should commit).
    rowcount=0: race lost or row not in 'confirmed' (no-op, safe to ignore).
    """
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_ACQUIRE_LOCK_SQL, (draft_id,))
        return {"ok": True, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[commit_db] acquire_commit_lock failed draft_id=%s: %s", draft_id, e)
        return {"ok": False, "reason": str(e)}


async def mark_committed(
    pool: AsyncConnectionPool, draft_id: str, farmos_response: dict | None
) -> dict:
    """CAS: status='committing' -> 'committed', store farmos_response, SET origin='python'.

    rowcount=0 if not currently 'committing' (idempotent no-op).
    """
    try:
        response_json = json.dumps(farmos_response) if farmos_response is not None else None
        async with pool.connection() as conn:
            result = await conn.execute(_MARK_COMMITTED_SQL, (response_json, draft_id))
        return {"ok": True, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[commit_db] mark_committed failed draft_id=%s: %s", draft_id, e)
        return {"ok": False, "reason": str(e)}


async def mark_failed(
    pool: AsyncConnectionPool, draft_id: str, reason: str | None, transport: bool = False
) -> dict:
    """CAS: status='committing' -> 'commit_failed', store commit_failed_reason.

    rowcount=0 if not currently 'committing' (idempotent no-op).

    MUSHY-75: `transport` records whether the failure was the server being
    unreachable rather than the entry being wrong. It cannot be recovered from
    the reason string later, and the recovery pass needs it.
    """
    try:
        reason_str = str(reason) if reason is not None else None
        async with pool.connection() as conn:
            result = await conn.execute(_MARK_FAILED_SQL, (reason_str, bool(transport), draft_id))
        return {"ok": True, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[commit_db] mark_failed failed draft_id=%s: %s", draft_id, e)
        return {"ok": False, "reason": str(e)}


async def requeue_for_retry(pool: AsyncConnectionPool, draft_id: str) -> dict:
    """CAS: status='committing' -> 'confirmed', SET origin='python'.

    committed_at_attempt is PRESERVED (watchdog backoff gate uses it).
    rowcount=0 if not currently 'committing' (no-op).
    """
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_REQUEUE_SQL, (draft_id,))
        return {"ok": True, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[commit_db] requeue_for_retry failed draft_id=%s: %s", draft_id, e)
        return {"ok": False, "reason": str(e)}


async def hold_for_fidelity(pool: AsyncConnectionPool, draft_id: str) -> dict:
    """CAS: status='committing' -> 'fidelity_cross_check_unverified', SET origin='python'.

    Called by commit_watchdog when the fidelity gate returns a strain_mismatch hold
    (D-06 / T-62-30). The draft is held for human review; the farmOS commit is NOT
    made. origin='python' prevents the Node watchdog from picking up this row.

    rowcount=0 if not currently 'committing' (idempotent no-op).
    """
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_HOLD_FIDELITY_SQL, (draft_id,))
        return {"ok": True, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[commit_db] hold_for_fidelity failed draft_id=%s: %s", draft_id, e)
        return {"ok": False, "reason": str(e)}


async def release_stale_locks(
    pool: AsyncConnectionPool, stale_min: int = 15
) -> dict:
    """Reclaim locks stuck in 'committing' older than stale_min minutes.

    Uses interval-as-string pattern per confirm_repo.py:
      (%s || ' minutes')::interval with str(stale_min)

    Returns {"ok": True, "rowcount": n, "released_ids": [id, ...]}
    on success; {"ok": False, "reason": str, "released_ids": []} on error.
    """
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_RELEASE_STALE_SQL, (str(stale_min),))
            rows = await result.fetchall()
        released_ids = [row[0] for row in (rows or [])]
        return {"ok": True, "rowcount": result.rowcount, "released_ids": released_ids}
    except Exception as e:  # noqa: BLE001
        logger.warning("[commit_db] release_stale_locks failed stale_min=%s: %s", stale_min, e)
        return {"ok": False, "reason": str(e), "released_ids": []}


# ---------------------------------------------------------------------------
# MUSHY-75 -- transport-parked recovery
# ---------------------------------------------------------------------------

_FIND_TRANSPORT_PARKED_SQL = """
SELECT id, log_type, draft_json, sender_e164, commit_attempt_count
  FROM signal_draft
 WHERE status='commit_failed'
   AND commit_failed_transport IS TRUE
   AND origin='python'
 ORDER BY confirmed_at
 LIMIT 20
"""

_REQUEUE_PARKED_SQL = """
UPDATE signal_draft
   SET status='confirmed',
       commit_attempt_count=0,
       commit_failed_reason=NULL,
       commit_failed_transport=NULL
 WHERE id=%s AND status='commit_failed' AND commit_failed_transport IS TRUE
"""


async def find_transport_parked(pool: AsyncConnectionPool) -> list[dict]:
    """Drafts stuck at the attempt cap because farmOS was unreachable.

    Bounded at 20: a recovery pass runs inside the watchdog tick and a farmOS
    outage could park many drafts at once. The rest come back next tick.
    """
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(_FIND_TRANSPORT_PARKED_SQL)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        logger.warning("[commit_db] find_transport_parked failed: %s", e)
        return []


async def requeue_parked(pool: AsyncConnectionPool, draft_id: str) -> dict:
    """CAS: 'commit_failed' (transport) -> 'confirmed', attempts reset to 0.

    The status+transport guard is what stops this resurrecting a validation
    failure, which really does need the farmer to fix it.
    """
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_REQUEUE_PARKED_SQL, (draft_id,))
        return {"ok": True, "rowcount": result.rowcount}
    except Exception as e:  # noqa: BLE001
        logger.warning("[commit_db] requeue_parked failed draft_id=%s: %s", draft_id, e)
        return {"ok": False, "reason": str(e)}
