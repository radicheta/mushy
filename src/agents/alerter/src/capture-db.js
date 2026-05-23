'use strict';
// Phase 25: signal_capture persistence (regular table; per-farmer volume too low for hypertable).
// Pure module — pool injected by caller (mirrors src/mission-control/timelapse/src/db.js).

async function initDb(pool) {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS signal_capture (
      id              text PRIMARY KEY,
      captured_at     timestamptz NOT NULL DEFAULT now(),
      sender          text NOT NULL,
      message_type    text NOT NULL,
      raw_text        text,
      attachment_paths text[] NOT NULL DEFAULT ARRAY[]::text[],
      transcript      text,
      llm_session_tag text,
      llm_reply       text,
      degraded        boolean NOT NULL DEFAULT false,
      expired         boolean NOT NULL DEFAULT false
    )
  `);
  await pool.query(`
    CREATE INDEX IF NOT EXISTS idx_signal_capture_sender_time
    ON signal_capture (sender, captured_at DESC)
  `);
  await pool.query(`
    CREATE INDEX IF NOT EXISTS idx_signal_capture_expired
    ON signal_capture (expired) WHERE expired = false
  `);
  // Phase 37 D-14/D-15: three nullable columns added idempotently.
  // Plain ADD COLUMN IF NOT EXISTS is sufficient on Postgres (no DO-block needed —
  // signal_capture is a regular table, not a hypertable).
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS group_id text`);
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS farmos_person text`);
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS reply_target_kind text`);
  // Backlog 999.53: persist Anthropic token usage for $/day cost visibility.
  // Pricing for sonnet-4-6 per MTok: input=$3, output=$15, cache_creation=$3.75, cache_read=$0.30.
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS input_tokens int`);
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS output_tokens int`);
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS cache_creation_input_tokens int`);
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS cache_read_input_tokens int`);
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS model text`);
  // Phase 44 Plan-04 D-04: event-gate audit column. VARCHAR(32) per locked D-04
  // decision (NOT downgraded to `text` — D-04 enum longest value 'skipped_rule_neg' is 16 chars).
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS extraction_gate VARCHAR(32)`);
  await pool.query(`
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
  `);
}

async function insertCapture(pool, row) {
  await pool.query(
    `INSERT INTO signal_capture
       (id, captured_at, sender, message_type, raw_text, attachment_paths, transcript, llm_session_tag, llm_reply, degraded, group_id, farmos_person, reply_target_kind)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)`,
    [
      row.id,
      row.captured_at,
      row.sender,
      row.message_type,
      row.raw_text ?? null,
      row.attachment_paths ?? [],
      row.transcript ?? null,
      row.llm_session_tag ?? null,
      row.llm_reply ?? null,
      row.degraded === true,
      row.group_id ?? null,
      row.farmos_person ?? null,
      row.reply_target_kind ?? null,
    ]
  );
}

async function markExpiredOlderThan(pool, ageMs) {
  const cutoff = new Date(Date.now() - ageMs);
  const r = await pool.query(
    `UPDATE signal_capture SET expired = true
     WHERE captured_at < $1 AND expired = false`,
    [cutoff]
  );
  return { rowCount: r.rowCount };
}

// Phase 40 Plan 06: photo attachment-path lookup for the commit pipeline.
// Returns a deduped flat array of paths across all matching capture rows.
// Never-throws shape: {ok, paths} | {ok:false, reason}.
async function getAttachmentPathsForIds(pool, captureIds) {
  if (!Array.isArray(captureIds) || captureIds.length === 0) {
    return { ok: true, paths: [] };
  }
  try {
    const r = await pool.query(
      `SELECT attachment_paths FROM signal_capture WHERE id = ANY($1::text[])`,
      [captureIds]
    );
    const set = new Set();
    for (const row of (r.rows || [])) {
      for (const p of (row.attachment_paths || [])) {
        if (p) set.add(p);
      }
    }
    return { ok: true, paths: Array.from(set) };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

module.exports = { initDb, insertCapture, markExpiredOlderThan, getAttachmentPathsForIds };
