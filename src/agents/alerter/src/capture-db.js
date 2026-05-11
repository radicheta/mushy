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

module.exports = { initDb, insertCapture, markExpiredOlderThan };
