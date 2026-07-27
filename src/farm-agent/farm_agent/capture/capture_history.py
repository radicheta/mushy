"""
capture/capture_history.py -- Fail-open SELECT queries for signal_capture + signal_outbound.

Port of src/agents/alerter/src/capture-history.js createCaptureHistory().

Provides:
  select_recent_by_sender(pool, sender, since_ms) -> list[dict]
  select_recent_outbound_by_recipient(pool, recipient, since_ms) -> list[dict]

Both functions:
  - Convert since_ms (epoch-ms int) to UTC datetime for the query.
  - Use async with pool.connection() + %s placeholders (psycopg3 pattern).
  - select_recent_by_sender: returns rows in DESC order (most-recent first).
  - select_recent_outbound_by_recipient: returns rows in ASC order (oldest-first).
  - Are fail-open: any exception returns [] with a WARNING (NEVER raises).

These are consumed by Phase 59+ event gate and extraction pipeline as context windows.

CAP-01/CAP-02 (Phase 59+ seam): recent-capture context for LLM prompt + gate.
T-58-03-02: no PII in log lines (pool errors logged without sender/recipient value).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

_SELECT_BY_SENDER_SQL = """
SELECT id, captured_at, sender, message_type, raw_text, transcript,
       attachment_paths, farmos_person, reply_target_kind,
       signal_msg_ts, quote_msg_ts, quote_author_e164, degraded
  FROM signal_capture
 WHERE sender = %s
   AND captured_at >= %s
 ORDER BY captured_at DESC
"""

_SELECT_OUTBOUND_BY_RECIPIENT_SQL = """
SELECT sent_at, body, intent, related_capture_id
  FROM signal_outbound
 WHERE recipient_e164 = %s
   AND sent_at >= %s
 ORDER BY sent_at ASC
"""


async def select_recent_by_sender(
    pool: AsyncConnectionPool,
    sender: str,
    since_ms: int,
) -> list[dict]:
    """Return signal_capture rows for sender since since_ms (epoch-ms). NEVER raises.

    Port of capture-history.js:selectRecentBySender.

    Args:
        pool:     Injected psycopg3 async pool.
        sender:   Sender e164 to filter by.
        since_ms: Epoch-milliseconds lower bound (rows >= this timestamp).

    Returns:
        list of dict rows, ordered captured_at DESC.
        Empty list on any error (fail-open).
    """
    since_dt = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc)
    try:
        async with pool.connection() as conn:
            cursor = await conn.execute(_SELECT_BY_SENDER_SQL, (sender, since_dt))
            rows = await cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description] if cursor.description else []
            return [dict(zip(col_names, row)) for row in rows]
    except Exception as e:  # noqa: BLE001 -- fail-open
        logger.warning("[capture_history] select_recent_by_sender failed: %s", e)
        return []


async def select_recent_outbound_by_recipient(
    pool: AsyncConnectionPool,
    recipient: str,
    since_ms: int,
) -> list[dict]:
    """Return signal_outbound rows for recipient since since_ms (epoch-ms). NEVER raises.

    Port of capture-history.js:selectRecentOutboundByRecipient (Phase 44 Plan-05 D-18).
    Returns {sent_at, body, intent, related_capture_id} rows -- the fields consumed
    by Phase 59+ gate/extractor fmtHistory merge.

    Args:
        pool:      Injected psycopg3 async pool.
        recipient: Recipient e164 to filter by.
        since_ms:  Epoch-milliseconds lower bound (rows >= this timestamp).

    Returns:
        list of dict rows, ordered sent_at ASC.
        Empty list on any error (fail-open).
    """
    since_dt = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc)
    try:
        async with pool.connection() as conn:
            cursor = await conn.execute(_SELECT_OUTBOUND_BY_RECIPIENT_SQL, (recipient, since_dt))
            rows = await cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description] if cursor.description else []
            return [dict(zip(col_names, row)) for row in rows]
    except Exception as e:  # noqa: BLE001 -- fail-open
        logger.warning("[capture_history] select_recent_outbound_by_recipient failed: %s", e)
        return []
