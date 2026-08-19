"""
persistence/outbound_repo.py -- SIG-02: durable outbound persist (fail-open, D-02).

Port of src/agents/alerter/src/outbound-db.js insertOutbound().

insert_outbound():
  - Inserts a row into signal_outbound in the exact 11-column contract order
    (tenant_id, sent_at, recipient_e164, intent, body, attachments, source_module,
    source_line, related_capture_id, related_draft_id, signal_msg_ts)
  - attachments passed as jsonb via psycopg.types.json.Jsonb
  - source_module defaults to "signal_io" when omitted (column is NOT NULL)
  - signal_msg_ts stored as-is (caller already int()'d it); NULL when omitted
  - NEVER raises -- any exception is caught and returned as {ok: False, reason: str(e)}
  - Returns {ok: True} on success

T-57-01-01: fail-open — a DB outage degrades to warn, send return unaffected (D-02).
"""

from __future__ import annotations

import logging

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

_INSERT_SQL = """
INSERT INTO signal_outbound
  (tenant_id, sent_at, recipient_e164, intent, body, attachments,
   source_module, source_line, related_capture_id, related_draft_id, signal_msg_ts)
VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
"""


async def insert_outbound(pool: AsyncConnectionPool, row: dict) -> dict:
    """Insert one row into signal_outbound.

    Column contract (exact order, matching outbound-db.js insertOutbound):
        tenant_id, sent_at, recipient_e164, intent, body, attachments,
        source_module, source_line, related_capture_id, related_draft_id, signal_msg_ts

    Row dict keys (all optional except tenant_id, sent_at, recipient_e164, intent, body):
        tenant_id          str
        sent_at            datetime (timestamptz)
        recipient_e164     str  -- e164 or 'group:<base64>'
        intent             str
        body               str
        attachments        dict | None  -- stored as jsonb
        source_module      str  -- defaults to 'signal_io' when absent (NOT NULL column)
        source_line        int | None
        related_capture_id str | None
        related_draft_id   str | None
        signal_msg_ts      int | None  -- ms-since-epoch bigint; caller must int()-coerce

    Returns:
        {"ok": True}                        on success
        {"ok": False, "reason": str(e)}     on any exception (fail-open, T-57-01-01)

    NEVER raises.
    """
    attachments_raw = row.get("attachments")
    attachments = Jsonb(attachments_raw) if attachments_raw is not None else None

    params = (
        row["tenant_id"],
        row["sent_at"],
        row["recipient_e164"],
        row["intent"],
        row["body"],
        attachments,
        row.get("source_module", "signal_io"),
        row.get("source_line"),
        row.get("related_capture_id"),
        row.get("related_draft_id"),
        row.get("signal_msg_ts"),
    )

    try:
        async with pool.connection() as conn:
            await conn.execute(_INSERT_SQL, params)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001 -- fail-open per D-02 / T-57-01-01
        logger.warning("[outbound_repo] insert_outbound failed: %s", e)
        return {"ok": False, "reason": str(e)}


async def last_body_for_draft(pool: AsyncConnectionPool, draft_id: str) -> str | None:
    """Return the body of the most recent send for a draft, or None (MUSHY-91).

    Fail-open like insert_outbound: any error returns None, which the caller
    reads as "no evidence of a duplicate" and sends. A lookup outage must never
    withhold a farmer message.
    """
    if not draft_id:
        return None
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT body FROM signal_outbound
                 WHERE related_draft_id = %s
                 ORDER BY sent_at DESC
                 LIMIT 1
                """,
                (draft_id,),
            )
            row = await cur.fetchone()
        return row[0] if row else None
    except Exception as e:  # noqa: BLE001 -- fail-open
        logger.warning("[outbound_repo] last_body_for_draft failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# MUSHY-98 -- one heartbeat per local day, across restarts
# ---------------------------------------------------------------------------

_LAST_HEARTBEAT_DAY_SQL = """
SELECT to_char(sent_at AT TIME ZONE %s, 'YYYY-MM-DD')
  FROM signal_outbound
 WHERE intent = 'heartbeat' OR body LIKE '[HEARTBEAT]%%'
 ORDER BY sent_at DESC
 LIMIT 1
"""


async def last_heartbeat_day(pool: AsyncConnectionPool, tz_name: str) -> str | None:
    """Local day of the most recent heartbeat sent, or None.

    Matches on the body as well as the intent because heartbeats sent before
    MUSHY-98 carry intent 'unknown' or 'attestation_kickoff' -- so the guard
    works on the history that already exists, not only on rows written from now
    on.

    Returns None on any failure. A DB that cannot answer must not silence the
    heartbeat: a missing heartbeat is the failure this path exists to prevent.
    """
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(_LAST_HEARTBEAT_DAY_SQL, (tz_name,))
            row = await cur.fetchone()
        return row[0] if row and row[0] else None
    except Exception as e:  # noqa: BLE001
        logger.warning("[outbound_repo] last_heartbeat_day failed: %s", e)
        return None
