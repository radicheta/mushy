"""
capture/capture_repo.py -- Never-throws psycopg3 INSERT + soft-expiry for signal_capture.

Port of src/agents/alerter/src/capture-db.js insertCapture() + markExpiredOlderThan().
Mirrors persistence/outbound_repo.py exactly (structure, psycopg3 pattern, fail-open).

Provides:
  insert_capture(pool, row) -> {ok:True} | {ok:False, reason}  -- NEVER raises
  mark_expired_older_than(pool, age_seconds) -> int             -- NEVER raises

Critical subtleties (from 58-PATTERNS.md):
  1. attachment_paths is text[] -- pass list[str] directly; psycopg3 auto-adapts.
     Do NOT wrap in Jsonb (that would cause a type error).
  2. corpus_context is ALWAYS None for live captures (hard-coded in params tuple).
     Only the Phase 53/54 backfill harness ever sets it.

CAP-01: Inbound envelopes captured to signal_capture (ULID id); fail-open (D-04 persist).
T-58-02-02: corpus_context hard-coded None -- live caller cannot inject it.
T-58-02-03: never-throw try/except -- DB outage degrades to WARNING, pipeline continues.
"""

from __future__ import annotations

import logging

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

# Column order must match signal_capture DDL exactly (18 columns).
# See 58-CONTEXT.md §interfaces and 58-PATTERNS.md §capture_repo.py.
_INSERT_SQL = """
INSERT INTO signal_capture
  (id, captured_at, sender, message_type, raw_text, attachment_paths,
   transcript, llm_session_tag, llm_reply, degraded,
   group_id, farmos_person, reply_target_kind,
   signal_msg_ts, quote_msg_ts, quote_author_e164, corpus_context,
   extraction_gate)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

# Soft-expire rows older than age_seconds that are not already expired.
# Uses interval cast from string because psycopg3 cannot bind a Python timedelta
# to an interval-arithmetic expression of the form NOW() - %s::interval directly.
_EXPIRE_SQL = """
UPDATE signal_capture
   SET expired = true
 WHERE captured_at < NOW() - (%s || ' seconds')::interval
   AND expired IS DISTINCT FROM true
"""


async def insert_capture(pool: AsyncConnectionPool, row: dict) -> dict:
    """Insert one row into signal_capture.

    Column contract (exact order, 18 columns):
        id, captured_at, sender, message_type, raw_text, attachment_paths,
        transcript, llm_session_tag (None), llm_reply (None), degraded,
        group_id, farmos_person, reply_target_kind,
        signal_msg_ts, quote_msg_ts, quote_author_e164, corpus_context (None),
        extraction_gate str | None -- Phase 59

    Row dict keys:
        id                 str  -- ULID string (required)
        captured_at        datetime (timezone.utc)  -- required
        sender             str  -- e164 (required)
        message_type       str  -- "text"|"audio"|"image"|"mixed" (required)
        raw_text           str | None
        attachment_paths   list[str]  -- text[] (NOT jsonb); pass list directly
        transcript         str | None
        degraded           bool
        group_id           str | None
        farmos_person      str | None
        reply_target_kind  str | None
        signal_msg_ts      int | None
        quote_msg_ts       int | None
        quote_author_e164  str | None
        extraction_gate    str | None  -- VARCHAR(32) gate outcome; Phase 59

    corpus_context is ALWAYS None (hard-coded) -- only backfill harness sets it.
    llm_session_tag and llm_reply are ALWAYS None (Phase 59+).

    Returns:
        {"ok": True}                        on success
        {"ok": False, "reason": str(e)}     on any exception (fail-open, D-04 / T-58-02-03)

    NEVER raises.
    """
    params = (
        row["id"],
        row["captured_at"],                       # datetime(timezone.utc) -- never naive
        row["sender"],
        row["message_type"],
        row.get("raw_text"),
        row.get("attachment_paths", []),           # list[str] -> text[] (psycopg3 auto-adapts)
        row.get("transcript"),                     # str | None; NULL = fail-open D-04
        None,                                      # llm_session_tag (Phase 59+)
        None,                                      # llm_reply (Phase 59+)
        row.get("degraded", False),
        row.get("group_id"),
        row.get("farmos_person"),
        row.get("reply_target_kind"),
        row.get("signal_msg_ts"),                  # bigint | None
        row.get("quote_msg_ts"),                   # bigint | None
        row.get("quote_author_e164"),
        None,                                      # corpus_context -- ALWAYS None (T-58-02-02)
        row.get("extraction_gate"),                # VARCHAR(32) | None -- Phase 59
    )

    try:
        async with pool.connection() as conn:
            await conn.execute(_INSERT_SQL, params)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001 -- fail-open per D-04 / T-58-02-03
        logger.warning("[capture_repo] insert_capture failed: %s", e)
        return {"ok": False, "reason": str(e)}


async def mark_expired_older_than(pool: AsyncConnectionPool, age_seconds: int) -> int:
    """Soft-expire signal_capture rows captured more than age_seconds ago.

    Sets expired=true on rows where:
      - captured_at < NOW() - age_seconds
      - expired IS DISTINCT FROM true  (idempotent; skips already-expired rows)

    Returns the number of rows affected (0 on error -- fail-open, never raises).
    Port of capture-db.js markExpiredOlderThan().
    """
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_EXPIRE_SQL, (str(age_seconds),))
            return result.rowcount or 0
    except Exception as e:  # noqa: BLE001 -- fail-open; retention failure is non-critical
        logger.warning("[capture_repo] mark_expired_older_than failed: %s", e)
        return 0
