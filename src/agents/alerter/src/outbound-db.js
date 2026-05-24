'use strict';
// Phase 44 Plan-02 (D-12 / D-14): signal_outbound persistence.
// Regular Postgres table (no hypertable — per-farmer volume too low,
// same posture as signal_capture).
//
// Schema is D-12 verbatim:
//   uuid PK via gen_random_uuid() (requires pgcrypto — emitted idempotently
//   below; operator should sanity-check the extension is enabled on the
//   elder-plops Timescale `mushy` database per RESEARCH A2 / Task 2.1).
//
// `insertOutbound` is never-throw per Pattern S1: returns {ok, reason}.
// The signal.js single-hook persistence call (D-14) depends on this for
// fail-open per D-03 — outbound insert failures must not back-pressure send().

async function initDb(pool) {
  // pgcrypto for gen_random_uuid(). Idempotent; needs superuser only on the
  // very first run. If superuser is unavailable this single statement errors
  // but `CREATE EXTENSION IF NOT EXISTS` is a no-op when already present.
  await pool.query(`CREATE EXTENSION IF NOT EXISTS pgcrypto`);
  await pool.query(`
    CREATE TABLE IF NOT EXISTS signal_outbound (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id       text NOT NULL,
      sent_at         timestamptz NOT NULL DEFAULT now(),
      recipient_e164  text NOT NULL,
      intent          text NOT NULL,
      body            text NOT NULL,
      attachments     jsonb,
      source_module   text NOT NULL,
      source_line     integer,
      related_capture_id text,
      related_draft_id   text
    )
  `);
  // 2026-05-23 hotfix: Plan-02 D-12 originally declared related_*_id as uuid,
  // but signal_capture.id is a ULID (text, e.g. "01KS9HSSJZYC6QHNKFT8Y3RF1H")
  // and signal_draft.id is a hex sha (text, e.g. "f87eb1e0..."). Postgres
  // rejected every insert with `invalid input syntax for type uuid`; the
  // insertOutbound fail-open mask hid the breakage until a live capture went
  // through post-cutover. ALTER the existing columns idempotently for hosts
  // already running the uuid version of the schema.
  await pool.query(`ALTER TABLE signal_outbound ALTER COLUMN related_capture_id TYPE text`);
  await pool.query(`ALTER TABLE signal_outbound ALTER COLUMN related_draft_id TYPE text`);
  await pool.query(`CREATE INDEX IF NOT EXISTS idx_signal_outbound_tenant_sent ON signal_outbound(tenant_id, sent_at DESC)`);
  await pool.query(`CREATE INDEX IF NOT EXISTS idx_signal_outbound_recipient_sent ON signal_outbound(recipient_e164, sent_at DESC)`);
  await pool.query(`CREATE INDEX IF NOT EXISTS idx_signal_outbound_intent ON signal_outbound(intent)`);
  // Phase 50 Plan-01 D-02: persist Signal-native ms-since-epoch returned by /v2/send
  // so future inbound quotes can resolve quote.timestamp -> related_draft_id.
  // Plan 02 owns the insertOutbound write path; this plan only lands the column + index.
  await pool.query(`ALTER TABLE signal_outbound ADD COLUMN IF NOT EXISTS signal_msg_ts bigint`);
  await pool.query(`CREATE INDEX IF NOT EXISTS idx_signal_outbound_msg_ts ON signal_outbound (signal_msg_ts) WHERE signal_msg_ts IS NOT NULL`);
}

async function insertOutbound(pool, row) {
  try {
    await pool.query(
      `INSERT INTO signal_outbound
         (tenant_id, sent_at, recipient_e164, intent, body, attachments,
          source_module, source_line, related_capture_id, related_draft_id, signal_msg_ts)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11)`,
      [
        row.tenant_id,
        row.sent_at,
        row.recipient_e164,
        row.intent,
        row.body,
        row.attachments != null ? JSON.stringify(row.attachments) : null,
        row.source_module,
        row.source_line ?? null,
        row.related_capture_id ?? null,
        row.related_draft_id ?? null,
        // Phase 50 Plan-02: Signal-native ms-ts from /v2/send. Row builder in
        // signal.js Number()-coerces before passing; insertOutbound does NOT
        // coerce. Omitted/null -> stored NULL (back-compat for ~14 callers).
        row.signal_msg_ts ?? null,
      ]
    );
    return { ok: true };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

async function selectRecentByRecipient(pool, recipient, sinceMs) {
  const since = new Date(sinceMs);
  const r = await pool.query(
    `SELECT sent_at, body, intent
     FROM signal_outbound
     WHERE recipient_e164 = $1 AND sent_at > $2
     ORDER BY sent_at ASC`,
    [recipient, since]
  );
  return r.rows;
}

module.exports = { initDb, insertOutbound, selectRecentByRecipient };
