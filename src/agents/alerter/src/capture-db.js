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
}

async function insertCapture(pool, row) {
  await pool.query(
    `INSERT INTO signal_capture
       (id, captured_at, sender, message_type, raw_text, attachment_paths, transcript, llm_session_tag, llm_reply, degraded)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
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
