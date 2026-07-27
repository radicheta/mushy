"""
persistence/migrations.py -- idempotent additive-only migrations (FND-03).

Ports the live Node alerter DDL verbatim from:
  - src/agents/alerter/src/capture-db.js       (signal_capture)
  - src/agents/alerter/src/extraction/extraction-db.js  (signal_draft base)
  - src/agents/alerter/src/confirm/confirm-db.js        (signal_draft confirm columns)
  - src/agents/alerter/src/farmos/commit-db.js          (signal_draft commit columns + index)
  - src/agents/alerter/src/outbound-db.js       (signal_outbound + pgcrypto)

ADDITIVE-ONLY CONSTRAINT (T-56-05-01):
  This runner issues only constructive DDL (CREATE ... IF NOT EXISTS, ADD COLUMN IF NOT EXISTS,
  the two whitelisted text->text no-op ALTER COLUMN TYPE statements on signal_outbound).
  Violation would break the live Node alerter reading the shared TimescaleDB.
  The test_migrations_additive_only source-grep guard in test_persistence.py
  enforces this by scanning for forbidden keywords in SQL strings.
"""

import logging

from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)


async def run_migrations(pool: AsyncConnectionPool) -> None:
    """Run all migrations in a single connection.

    Idempotent: safe to call on every boot. All DDL uses IF NOT EXISTS or
    IF EXISTS guards so re-running against an already-migrated DB is a no-op.
    """
    async with pool.connection() as conn:
        await _run_capture_migrations(conn)
        await _run_draft_migrations(conn)
        await _run_confirm_event_migrations(conn)
        await _run_outbound_migrations(conn)
        await _run_commit_migrations(conn)
    log.info("migrations complete")


# ---------------------------------------------------------------------------
# signal_capture (capture-db.js)
# ---------------------------------------------------------------------------

async def _run_capture_migrations(conn) -> None:
    """Port of capture-db.js initDb().

    Base table from Phase 25, plus all additive columns through Phase 53.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_capture (
          id                  text PRIMARY KEY,
          captured_at         timestamptz NOT NULL DEFAULT now(),
          sender              text NOT NULL,
          message_type        text NOT NULL,
          raw_text            text,
          attachment_paths    text[] NOT NULL DEFAULT ARRAY[]::text[],
          transcript          text,
          llm_session_tag     text,
          llm_reply           text,
          degraded            boolean NOT NULL DEFAULT false,
          expired             boolean NOT NULL DEFAULT false
        )
    """)

    # Indexes
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_capture_sender_time "
        "ON signal_capture (sender, captured_at DESC)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_capture_expired "
        "ON signal_capture (expired) WHERE expired = false"
    )

    # Phase 37 D-14/D-15: nullable columns added idempotently.
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS group_id text"
    )
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS farmos_person text"
    )
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS reply_target_kind text"
    )

    # Backlog 999.53: Anthropic token usage for cost visibility.
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS input_tokens int"
    )
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS output_tokens int"
    )
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS cache_creation_input_tokens int"
    )
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS cache_read_input_tokens int"
    )
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS model text"
    )

    # Phase 44 Plan-04 D-04: event-gate audit column. VARCHAR(32) per D-04 lock.
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS extraction_gate VARCHAR(32)"
    )

    # Phase 50 Plan-01 D-02: Signal-native quote threading columns.
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS signal_msg_ts bigint"
    )
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS quote_msg_ts bigint"
    )
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS quote_author_e164 text"
    )

    # Phase 53 BACK-01: year-context shim for the backfill harness.
    await conn.execute(
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS corpus_context jsonb"
    )

    # v_llm_cost_daily view (CREATE OR REPLACE -- idempotent).
    await conn.execute("""
        CREATE OR REPLACE VIEW v_llm_cost_daily AS
        SELECT
          date_trunc('day', captured_at) AS day,
          count(*) AS n_calls,
          sum(input_tokens) AS input_tokens,
          sum(output_tokens) AS output_tokens,
          sum(cache_creation_input_tokens) AS cache_creation_input_tokens,
          sum(cache_read_input_tokens) AS cache_read_input_tokens,
          (coalesce(sum(input_tokens), 0) * 3
            + coalesce(sum(output_tokens), 0) * 15
            + coalesce(sum(cache_creation_input_tokens), 0) * 3.75
            + coalesce(sum(cache_read_input_tokens), 0) * 0.30) / 1000000.0 AS approx_usd
        FROM signal_capture
        WHERE input_tokens IS NOT NULL
        GROUP BY day
        ORDER BY day DESC
    """)


# ---------------------------------------------------------------------------
# signal_draft (extraction-db.js + confirm-db.js)
# ---------------------------------------------------------------------------

async def _run_draft_migrations(conn) -> None:
    """Port of extraction-db.js initDb() base table + confirm-db.js ADD COLUMN blocks.

    signal_draft.id is a hex SHA-256 (text PK).
    Includes Phase 38 base, Phase 39 confirm columns, Phase 49 discard columns.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_draft (
          id                    text PRIMARY KEY,
          created_at            timestamptz NOT NULL DEFAULT now(),
          updated_at            timestamptz NOT NULL DEFAULT now(),
          sender_e164           text NOT NULL,
          farmos_person         text,
          source_capture_ids    text[] NOT NULL DEFAULT ARRAY[]::text[],
          status                text NOT NULL,
          log_type              text,
          draft_json            jsonb,
          per_field_confidence  jsonb,
          askback_turns         integer NOT NULL DEFAULT 0,
          farmer_facing_preview text,
          needs_review_reason   text,
          reply_target_kind     text,
          group_id              text
        )
    """)

    # Phase 38 indexes
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_draft_sender_status "
        "ON signal_draft (sender_e164, status)"
    )
    # D-02c: partial unique index -- at-most-one in-flight draft per sender.
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_draft_in_flight_per_sender "
        "ON signal_draft (sender_e164) WHERE status IN ('pending','awaiting_farmer')"
    )

    # Future-extensibility no-op (extraction-db.js line 56-58): needs_review_reason
    # already exists in the base CREATE TABLE above; ADD COLUMN IF NOT EXISTS is a no-op.
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS needs_review_reason text"
    )

    # Phase 49 Plan 01: discard columns.
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS discarded_reason text"
    )
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS discarded_at timestamptz"
    )

    # Phase 39 D-07 (confirm-db.js): confirm-loop columns.
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS edit_turn_count integer NOT NULL DEFAULT 0"
    )
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS nudge_sent_at timestamptz NULL"
    )
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS confirmed_at timestamptz NULL"
    )
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS expired_at timestamptz NULL"
    )
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS terminal_reason text NULL"
    )



# ---------------------------------------------------------------------------
# signal_draft_event (confirm-db.js)
# ---------------------------------------------------------------------------

async def _run_confirm_event_migrations(conn) -> None:
    """Port of confirm-db.js initDb() signal_draft_event table + indexes.

    signal_draft_event is the append-only audit log for draft confirm-loop
    transitions (preview_sent, nudge_sent, yes, no, edit, expired, etc.).
    PK is (draft_id, seq) with seq being a per-draft monotonic counter
    assigned at insert time via MAX(seq)+1.

    This table is created by the Node confirm-db.js initDb() on every Node
    alerter boot. If alerter-py boots first (fresh DB), this migration creates
    the table so the Node alerter's appendEvent() calls don't fail with
    "relation signal_draft_event does not exist".
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_draft_event (
          draft_id   text NOT NULL,
          seq        integer NOT NULL,
          event      text NOT NULL,
          payload    jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (draft_id, seq)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_draft_event_created_at "
        "ON signal_draft_event (created_at)"
    )
    # Nudge/expire watchdog index on signal_draft (not signal_draft_event).
    # Ported verbatim from confirm-db.js -- targets rows awaiting farmer reply.
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_draft_event_nudge_expire "
        "ON signal_draft (status, updated_at) WHERE status = 'awaiting_farmer'"
    )


# ---------------------------------------------------------------------------
# signal_outbound (outbound-db.js) -- pgcrypto FIRST
# ---------------------------------------------------------------------------

async def _run_outbound_migrations(conn) -> None:
    """Port of outbound-db.js initDb().

    MUST start with the pgcrypto extension statement (needed for
    gen_random_uuid() used in signal_outbound.id default).

    signal_outbound.id is a uuid PK (gen_random_uuid()).
    related_capture_id / related_draft_id are text (NOT uuid) -- hotfix from
    outbound-db.js 2026-05-23: original uuid columns broke on ULID/SHA inserts.
    The two TYPE text statements below are idempotent no-ops on a text column
    (text->text cast in Postgres) and are included for compat with hosts that
    ran the original uuid schema (RESEARCH FND-03 Pitfall 3).
    """
    # pgcrypto required for gen_random_uuid() PK default.
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_outbound (
          id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id           text NOT NULL,
          sent_at             timestamptz NOT NULL DEFAULT now(),
          recipient_e164      text NOT NULL,
          intent              text NOT NULL,
          body                text NOT NULL,
          attachments         jsonb,
          source_module       text NOT NULL,
          source_line         integer,
          related_capture_id  text,
          related_draft_id    text
        )
    """)

    # 2026-05-23 hotfix: idempotent text->text no-op ALTER for hosts that ran
    # the original uuid version of these columns.  text->text cast is a no-op
    # in Postgres (no data conversion, negligible lock on low-volume table --
    # T-56-05-04 accepted disposition per threat model).
    await conn.execute(
        "ALTER TABLE signal_outbound ALTER COLUMN related_capture_id TYPE text"
    )
    await conn.execute(
        "ALTER TABLE signal_outbound ALTER COLUMN related_draft_id TYPE text"
    )

    # Indexes
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_outbound_tenant_sent "
        "ON signal_outbound (tenant_id, sent_at DESC)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_outbound_recipient_sent "
        "ON signal_outbound (recipient_e164, sent_at DESC)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_outbound_intent "
        "ON signal_outbound (intent)"
    )

    # Phase 50 Plan-01 D-02: Signal-native ms-since-epoch for outbound acks.
    await conn.execute(
        "ALTER TABLE signal_outbound ADD COLUMN IF NOT EXISTS signal_msg_ts bigint"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_outbound_msg_ts "
        "ON signal_outbound (signal_msg_ts) WHERE signal_msg_ts IS NOT NULL"
    )


# ---------------------------------------------------------------------------
# signal_draft commit columns (commit-db.js / Phase 40 + Phase 45 + Phase 62)
# ---------------------------------------------------------------------------

async def _run_commit_migrations(conn) -> None:
    """Port of commit-db.js initDb() -- farmOS commit lifecycle columns on signal_draft.

    All ADD COLUMN IF NOT EXISTS so safe to run after _run_draft_migrations
    on a DB that already has these columns.

    Allowed signal_draft.status values after all migrations (validated in
    application code, NOT via pg CHECK constraint -- mirrors Phase 38/39
    precedent):
      pending | awaiting_farmer | confirmed | discarded | expired |
      needs_review | committing | committed | commit_failed |
      fidelity_cross_check_unverified

    fidelity_cross_check_unverified (Phase 62 D-06): Python commit_db holds a
    draft here when the CSV fidelity cross-check cannot verify the extraction;
    the Node commit-watchdog never drains this status (it only polls
    status='confirmed' AND origin != 'python').
    """
    # Phase 62 D-01: origin guard column. Default 'node' so all legacy rows
    # and Node-written rows are drained by the Node commit-watchdog unchanged.
    # Python commit_db writes origin='python'; findConfirmedCandidates in the
    # Node watchdog filters AND origin != 'python' so Python-owned drafts
    # cannot leak to prod farmOS via the 30s drain loop.
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'node'"
    )

    # Phase 40 D-02 / D-07: farmOS write columns.
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS farmos_response jsonb"
    )
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS committed_at timestamptz"
    )
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS commit_failed_reason text"
    )
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS commit_attempt_count int NOT NULL DEFAULT 0"
    )
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS committed_at_attempt timestamptz"
    )

    # Phase 45 D-01 (ACK-04): mark-then-send idempotency claim column.
    await conn.execute(
        "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS outcome_ack_sent_at timestamptz"
    )

    # Commit-watchdog index: status IN ('confirmed','committing') ordered by confirmed_at.
    # confirmed_at is added in _run_draft_migrations (confirm-db.js Phase 39).
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_draft_status_confirmed "
        "ON signal_draft (status, confirmed_at) WHERE status IN ('confirmed','committing')"
    )
