"""
extraction/extraction_db.py -- never-throws signal_draft DAO.

Port of src/agents/alerter/src/extraction/extraction-db.js (initDb excluded --
persistence/migrations.py:157 already owns the DDL and the D-02c partial
unique index).

MUSHY-76 deviation from Node: insert_draft stamps origin='python'. Node relies
on the column default 'node'. The Node commit watchdog selects
`WHERE status='confirmed' AND origin != 'python'`, so a Python-created draft
left at the default is committed to PRODUCTION farmOS by the Node agent.
"""

from __future__ import annotations

import hashlib
import logging

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

IN_FLIGHT_STATUSES: tuple[str, ...] = ("pending", "awaiting_farmer")

# Whitelisted so a caller-supplied key can never reach the SET clause.
# Verbatim from extraction-db.js UPDATE_EXTRAS_WHITELIST (8 keys).
_UPDATE_EXTRAS_WHITELIST = frozenset({
    "needs_review_reason",
    "farmer_facing_preview",
    "draft_json",
    "per_field_confidence",
    "log_type",
    "farmos_person",
    "reply_target_kind",
    "group_id",
})

_INSERT_SQL = """
INSERT INTO signal_draft
  (id, sender_e164, farmos_person, source_capture_ids, status, log_type,
   draft_json, per_field_confidence, askback_turns, farmer_facing_preview,
   needs_review_reason, reply_target_kind, group_id, origin)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_SELECT_IN_FLIGHT_SQL = """
SELECT * FROM signal_draft
 WHERE sender_e164 = %s
   AND status IN ('pending','awaiting_farmer')
 LIMIT 1
"""

_ADVANCE_ASKBACK_SQL = """
UPDATE signal_draft
   SET askback_turns = askback_turns + 1,
       updated_at    = now()
 WHERE id = %s
 RETURNING askback_turns
"""

_EXPIRE_IDLE_SQL = """
UPDATE signal_draft
   SET status = 'expired',
       updated_at = now()
 WHERE status IN ('pending','awaiting_farmer')
   AND updated_at < now() - (%s || ' minutes')::interval
"""

_SELECT_FOR_CAPTURE_SQL = """
SELECT * FROM signal_draft
 WHERE source_capture_ids @> ARRAY[%s]::text[]
 ORDER BY created_at ASC
"""

_SELECT_BY_ID_SQL = """
SELECT * FROM signal_draft WHERE id = %s LIMIT 1
"""


def compute_draft_id(capture_ids: list[str], draft_index: int | None = None) -> str:
    """Deterministic, replay-safe draft id (D-02a).

    SHA-256 over sorted capture ids joined by '|'. Index 0 and None are NOT
    suffixed, so single-draft ids stay byte-identical to every pre-Plan-08 row
    already in the shared database. Port of extraction-db.js:18-24.
    """
    sorted_ids = "|".join(sorted(capture_ids))
    keyed = sorted_ids if draft_index in (None, 0) else f"{sorted_ids}#{draft_index}"
    return hashlib.sha256(keyed.encode()).hexdigest()


async def insert_draft(pool: AsyncConnectionPool, row: dict) -> dict:
    """Insert a new draft row. Never raises.

    Returns:
        {"ok": True, "id": ...}                          on success
        {"ok": False, "reason": "in_flight_conflict"}     on D-02c 23505
        {"ok": False, "reason": str(e)}                   on any other error
    """
    params = (
        row["id"],
        row["sender_e164"],
        row.get("farmos_person"),
        row.get("source_capture_ids", []),  # text[] -- pass the list directly
        row["status"],
        row.get("log_type"),
        Jsonb(row["draft_json"]) if row.get("draft_json") is not None else None,
        Jsonb(row["per_field_confidence"])
        if row.get("per_field_confidence") is not None
        else None,
        row.get("askback_turns", 0),
        row.get("farmer_facing_preview"),
        row.get("needs_review_reason"),
        row.get("reply_target_kind"),
        row.get("group_id"),
        "python",  # MUSHY-76: origin guard
    )
    try:
        async with pool.connection() as conn:
            await conn.execute(_INSERT_SQL, params)
        return {"ok": True, "id": row["id"]}
    except Exception as e:  # noqa: BLE001 -- never-throw DAO
        if getattr(e, "sqlstate", None) == "23505":
            return {"ok": False, "reason": "in_flight_conflict"}
        logger.warning("[extraction_db] insert_draft failed: %s", e)
        return {"ok": False, "reason": str(e)}


async def get_in_flight_for_sender(pool: AsyncConnectionPool, sender_e164: str) -> dict | None:
    """Return the single in-flight draft (pending|awaiting_farmer) for a sender, or None.

    D-02c guarantees at most one exists. Returns None on error (never-throw).
    """
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(_SELECT_IN_FLIGHT_SQL, (sender_e164,))
            row = await cur.fetchone()
            if row is None:
                return None
            col_names = [desc[0] for desc in cur.description] if cur.description else []
            return dict(zip(col_names, row))
    except Exception as e:  # noqa: BLE001
        logger.warning("[extraction_db] get_in_flight_for_sender failed: %s", e)
        return None


async def update_draft_status(
    pool: AsyncConnectionPool, draft_id: str, new_status: str, extras: dict | None = None
) -> dict:
    """Update status + updated_at; optional extras write whitelisted columns only.

    Returns {"ok": True, "rowcount": N} or {"ok": False, "reason": str}. Never raises.
    """
    set_parts = ["status = %s", "updated_at = now()"]
    params: list = [new_status]
    for k, v in (extras or {}).items():
        if k not in _UPDATE_EXTRAS_WHITELIST:
            continue
        set_parts.append(f"{k} = %s")
        params.append(
            Jsonb(v) if k in ("draft_json", "per_field_confidence") and v is not None else v
        )
    params.append(draft_id)
    sql = f"UPDATE signal_draft SET {', '.join(set_parts)} WHERE id = %s"
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(sql, tuple(params))
            return {"ok": True, "rowcount": cur.rowcount or 0}
    except Exception as e:  # noqa: BLE001
        logger.warning("[extraction_db] update_draft_status failed: %s", e)
        return {"ok": False, "reason": str(e)}


async def advance_askback_turn(pool: AsyncConnectionPool, draft_id: str) -> dict:
    """Atomically increment askback_turns. Never raises.

    Returns {"ok": True, "askback_turns": N} or {"ok": False, "reason": str}.
    """
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(_ADVANCE_ASKBACK_SQL, (draft_id,))
            row = await cur.fetchone()
            if row is None:
                return {"ok": True, "askback_turns": None}
            col_names = [desc[0] for desc in cur.description] if cur.description else []
            turns = dict(zip(col_names, row)).get("askback_turns")
        return {"ok": True, "askback_turns": turns}
    except Exception as e:  # noqa: BLE001
        logger.warning("[extraction_db] advance_askback_turn failed: %s", e)
        return {"ok": False, "reason": str(e)}


async def expire_idle(pool: AsyncConnectionPool, gap_minutes: int) -> dict:
    """Expire in-flight drafts whose updated_at is older than gap_minutes (D-01a).

    Returns {"ok": True, "rowcount": N} or {"ok": False, "reason": str}. Never raises.
    """
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(_EXPIRE_IDLE_SQL, (str(gap_minutes),))
            return {"ok": True, "rowcount": cur.rowcount or 0}
    except Exception as e:  # noqa: BLE001
        logger.warning("[extraction_db] expire_idle failed: %s", e)
        return {"ok": False, "reason": str(e)}


async def get_drafts_for_capture(pool: AsyncConnectionPool, capture_id: str) -> list[dict]:
    """Read all drafts whose source_capture_ids array contains capture_id.

    Ordered by created_at ASC. Returns [] on error (never-throw).
    """
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(_SELECT_FOR_CAPTURE_SQL, (capture_id,))
            rows = await cur.fetchall()
            col_names = [desc[0] for desc in cur.description] if cur.description else []
            return [dict(zip(col_names, row)) for row in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("[extraction_db] get_drafts_for_capture failed: %s", e)
        return []


async def get_draft_by_id(pool: AsyncConnectionPool, draft_id: str) -> dict | None:
    """Fetch a single draft row by primary-key id. Returns the row or None (never-throw)."""
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(_SELECT_BY_ID_SQL, (draft_id,))
            row = await cur.fetchone()
            if row is None:
                return None
            col_names = [desc[0] for desc in cur.description] if cur.description else []
            return dict(zip(col_names, row))
    except Exception as e:  # noqa: BLE001
        logger.warning("[extraction_db] get_draft_by_id failed: %s", e)
        return None
