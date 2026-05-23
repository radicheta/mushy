'use strict';
// Phase 38: signal_draft persistence (D-02 / D-02a / D-02b / D-02c).
// Pool-injected; mirrors src/capture-db.js style. Never-throw on writes.

const crypto = require('crypto');

const IN_FLIGHT_STATUSES = ['pending', 'awaiting_farmer'];

/**
 * Deterministic draft id from a capture-id set (D-02a, replay-safe).
 * SHA-256 over sorted ids joined by '|'.
 *
 * Plan 08 batch mode: when one page yields multiple drafts (drafts[] from
 * multimodal paper-log extraction), each draft is keyed by (captureIds, index)
 * to avoid PK collisions. Index is appended after a '#' before hashing so
 * single-draft ids stay byte-identical to the pre-Plan-08 schema.
 */
function computeDraftId(captureIds, draftIndex) {
  const sorted = captureIds.slice().sort().join('|');
  const keyed = (draftIndex == null || draftIndex === 0)
    ? sorted
    : `${sorted}#${draftIndex}`;
  return crypto.createHash('sha256').update(keyed).digest('hex');
}

async function initDb(pool) {
  await pool.query(`
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
  `);
  await pool.query(`
    CREATE INDEX IF NOT EXISTS idx_signal_draft_sender_status
    ON signal_draft (sender_e164, status)
  `);
  // D-02c: partial unique index enforces at-most-one in-flight draft per sender.
  await pool.query(`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_draft_in_flight_per_sender
    ON signal_draft (sender_e164) WHERE status IN ('pending','awaiting_farmer')
  `);
  // Future-extensibility no-op: idempotent placeholder for the next column add.
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS needs_review_reason text`
  );
}

/**
 * Insert a new draft. Returns:
 *   { ok: true, id }                                on success
 *   { ok: false, reason: 'in_flight_conflict' }     on partial-unique-index 23505 (D-02c)
 *   { ok: false, reason: <pg error message> }       on any other error
 * Never throws.
 */
async function insertDraft(pool, row) {
  try {
    await pool.query(
      `INSERT INTO signal_draft
         (id, sender_e164, farmos_person, source_capture_ids, status, log_type,
          draft_json, per_field_confidence, askback_turns, farmer_facing_preview,
          needs_review_reason, reply_target_kind, group_id)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)`,
      [
        row.id,
        row.sender_e164,
        row.farmos_person ?? null,
        row.source_capture_ids ?? [],
        row.status,
        row.log_type ?? null,
        row.draft_json ?? null,
        row.per_field_confidence ?? null,
        row.askback_turns ?? 0,
        row.farmer_facing_preview ?? null,
        row.needs_review_reason ?? null,
        row.reply_target_kind ?? null,
        row.group_id ?? null,
      ]
    );
    return { ok: true, id: row.id };
  } catch (e) {
    if (e && e.code === '23505') {
      return { ok: false, reason: 'in_flight_conflict' };
    }
    return { ok: false, reason: e.message };
  }
}

/**
 * Returns the single in-flight draft (status in pending|awaiting_farmer) for a sender, or null.
 * D-02c guarantees at most one exists.
 */
async function getInFlightForSender(pool, senderE164) {
  const r = await pool.query(
    `SELECT * FROM signal_draft
     WHERE sender_e164 = $1
       AND status IN ('pending','awaiting_farmer')
     LIMIT 1`,
    [senderE164]
  );
  return r.rows.length > 0 ? r.rows[0] : null;
}

/**
 * Update status + updated_at; optional extras object writes named columns.
 * Allowed extras keys (whitelisted to avoid SQL-injection via key names):
 *   needs_review_reason, farmer_facing_preview, draft_json, per_field_confidence,
 *   log_type, farmos_person, reply_target_kind, group_id.
 * Returns { ok: true, rowCount } or { ok: false, reason }.
 */
const UPDATE_EXTRAS_WHITELIST = new Set([
  'needs_review_reason',
  'farmer_facing_preview',
  'draft_json',
  'per_field_confidence',
  'log_type',
  'farmos_person',
  'reply_target_kind',
  'group_id',
]);

async function updateDraftStatus(pool, id, newStatus, extras) {
  const setParts = ['status = $2', 'updated_at = now()'];
  const params = [id, newStatus];
  let nextIdx = 3;
  if (extras && typeof extras === 'object') {
    for (const k of Object.keys(extras)) {
      if (!UPDATE_EXTRAS_WHITELIST.has(k)) continue;
      setParts.push(`${k} = $${nextIdx}`);
      params.push(extras[k]);
      nextIdx += 1;
    }
  }
  try {
    const r = await pool.query(
      `UPDATE signal_draft SET ${setParts.join(', ')} WHERE id = $1`,
      params
    );
    return { ok: true, rowCount: r.rowCount };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

/**
 * Atomically increment askback_turns. Returns the new value via RETURNING.
 * { ok: true, askback_turns: N } or { ok: false, reason }.
 */
async function advanceAskbackTurn(pool, id) {
  try {
    const r = await pool.query(
      `UPDATE signal_draft
         SET askback_turns = askback_turns + 1,
             updated_at    = now()
       WHERE id = $1
       RETURNING askback_turns`,
      [id]
    );
    const turns = r.rows.length > 0 ? r.rows[0].askback_turns : null;
    return { ok: true, askback_turns: turns };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

/**
 * Expire in-flight drafts whose updated_at is older than gapMinutes.
 * D-01a: idle-gap closer. Returns { ok: true, rowCount } or { ok: false, reason }.
 */
async function expireIdle(pool, gapMinutes) {
  try {
    const r = await pool.query(
      `UPDATE signal_draft
         SET status = 'expired',
             updated_at = now()
       WHERE status IN ('pending','awaiting_farmer')
         AND updated_at < now() - ($1 || ' minutes')::interval`,
      [gapMinutes]
    );
    return { ok: true, rowCount: r.rowCount };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

/**
 * Fetch a single draft row by primary-key id. Returns the row or null.
 * Added for Phase 47 Plan 03 handleStartingSeqReply: ask-back reply needs
 * to re-load the draft, mutate child_block_names + needs_input, then
 * write back via updateDraftStatus({draft_json}).
 */
async function getDraftById(pool, id) {
  try {
    const r = await pool.query(
      `SELECT * FROM signal_draft WHERE id = $1 LIMIT 1`,
      [id],
    );
    return r.rows.length > 0 ? r.rows[0] : null;
  } catch (_e) {
    return null;
  }
}

module.exports = {
  initDb,
  insertDraft,
  getInFlightForSender,
  getDraftById,
  updateDraftStatus,
  advanceAskbackTurn,
  expireIdle,
  computeDraftId,
  IN_FLIGHT_STATUSES,
};
