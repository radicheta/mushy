'use strict';

// Phase 39 D-07 + D-07a: confirm-loop persistence.
//
// Adds the columns Phase 39's state-machine needs on top of Phase 38's
// signal_draft table (edit_turn_count, nudge_sent_at, confirmed/discarded/
// expired timestamps, terminal_reason) plus a new append-only audit table
// signal_draft_event with per-draft monotonic seq (composite PK).
//
// All transition helpers (confirmDraft / discardDraft / expireDraft) issue
// a single conditional UPDATE WHERE status='awaiting_farmer' so duplicate
// calls and watchdog/restart races are idempotent (rowCount=0 = no-op).
//
// Recognized event names (signal_draft_event.event):
//   preview_sent / nudge_sent / yes / no / edit / expired / edit_cap_exceeded / superseded
//
// Never-throw on writes (matches extraction-db.js conventions).

async function initDb(pool) {
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS edit_turn_count integer NOT NULL DEFAULT 0`
  );
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS nudge_sent_at timestamptz NULL`
  );
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS confirmed_at timestamptz NULL`
  );
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS discarded_at timestamptz NULL`
  );
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS expired_at timestamptz NULL`
  );
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS terminal_reason text NULL`
  );
  await pool.query(`
    CREATE TABLE IF NOT EXISTS signal_draft_event (
      draft_id   text NOT NULL,
      seq        integer NOT NULL,
      event      text NOT NULL,
      payload    jsonb,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (draft_id, seq)
    )
  `);
  await pool.query(
    `CREATE INDEX IF NOT EXISTS idx_signal_draft_event_created_at ON signal_draft_event (created_at)`
  );
  await pool.query(
    `CREATE INDEX IF NOT EXISTS idx_signal_draft_event_nudge_expire
       ON signal_draft (status, updated_at) WHERE status = 'awaiting_farmer'`
  );
}

// ----- Event log -----

// Insert one event row inside an open client transaction. RETURNING seq.
async function appendEvent(client, draftId, event, payload) {
  try {
    const r = await client.query(
      `INSERT INTO signal_draft_event (draft_id, seq, event, payload, created_at)
       VALUES ($1,
               (SELECT COALESCE(MAX(seq), 0) + 1 FROM signal_draft_event WHERE draft_id = $1),
               $2, $3::jsonb, NOW())
       RETURNING seq`,
      [draftId, event, payload == null ? null : JSON.stringify(payload)]
    );
    const seq = r.rows.length > 0 ? r.rows[0].seq : null;
    return { ok: true, seq };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

// Pool-level overload -- opens its own client briefly.
async function appendEventViaPool(pool, draftId, event, payload) {
  try {
    const r = await pool.query(
      `INSERT INTO signal_draft_event (draft_id, seq, event, payload, created_at)
       VALUES ($1,
               (SELECT COALESCE(MAX(seq), 0) + 1 FROM signal_draft_event WHERE draft_id = $1),
               $2, $3::jsonb, NOW())
       RETURNING seq`,
      [draftId, event, payload == null ? null : JSON.stringify(payload)]
    );
    const seq = r.rows.length > 0 ? r.rows[0].seq : null;
    return { ok: true, seq };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

// ----- Atomic transitions -----

async function _runTransition(pool, sql, params, eventName, eventPayload) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const r = await client.query(sql, params);
    if (r.rowCount === 1) {
      const draftId = params[0];
      await appendEvent(client, draftId, eventName, eventPayload || null);
    }
    await client.query('COMMIT');
    return { ok: true, rowCount: r.rowCount };
  } catch (e) {
    try { await client.query('ROLLBACK'); } catch (_) { /* ignore */ }
    return { ok: false, reason: e.message };
  } finally {
    client.release();
  }
}

async function confirmDraft(pool, draftId) {
  return _runTransition(
    pool,
    `UPDATE signal_draft
        SET status='confirmed',
            confirmed_at=NOW(),
            terminal_reason='farmer_yes',
            updated_at=NOW()
      WHERE id=$1 AND status='awaiting_farmer'
      RETURNING id`,
    [draftId],
    'yes',
    null
  );
}

async function discardDraft(pool, draftId) {
  return _runTransition(
    pool,
    `UPDATE signal_draft
        SET status='discarded',
            discarded_at=NOW(),
            terminal_reason='farmer_no',
            updated_at=NOW()
      WHERE id=$1 AND status='awaiting_farmer'
      RETURNING id`,
    [draftId],
    'no',
    null
  );
}

async function expireDraft(pool, draftId, reason) {
  let sql;
  let eventName;
  if (reason === 'edit_cap_exceeded') {
    // Cap-exceeded -> needs_review (not expired), expired_at stays NULL.
    sql = `UPDATE signal_draft
              SET status='needs_review',
                  terminal_reason=$2,
                  updated_at=NOW()
            WHERE id=$1 AND status='awaiting_farmer'
            RETURNING id`;
    eventName = 'edit_cap_exceeded';
  } else if (reason === 'superseded_by_newer_draft') {
    sql = `UPDATE signal_draft
              SET status='expired',
                  expired_at=NOW(),
                  terminal_reason=$2,
                  updated_at=NOW()
            WHERE id=$1 AND status='awaiting_farmer'
            RETURNING id`;
    eventName = 'superseded';
  } else {
    // 'timeout_expired' (or any other) -> expired.
    sql = `UPDATE signal_draft
              SET status='expired',
                  expired_at=NOW(),
                  terminal_reason=$2,
                  updated_at=NOW()
            WHERE id=$1 AND status='awaiting_farmer'
            RETURNING id`;
    eventName = 'expired';
  }
  return _runTransition(pool, sql, [draftId, reason], eventName, { reason });
}

// ----- Watchdog / sender / edit helpers -----

async function markNudgeSent(pool, draftId) {
  try {
    const r = await pool.query(
      `UPDATE signal_draft
          SET nudge_sent_at=NOW(),
              updated_at=NOW()
        WHERE id=$1 AND nudge_sent_at IS NULL
        RETURNING id`,
      [draftId]
    );
    return { ok: true, rowCount: r.rowCount };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

async function bumpEditTurn(pool, draftId) {
  try {
    const r = await pool.query(
      `UPDATE signal_draft
          SET edit_turn_count = edit_turn_count + 1,
              updated_at = NOW()
        WHERE id=$1 AND status='awaiting_farmer'
        RETURNING edit_turn_count`,
      [draftId]
    );
    const cnt = r.rows.length > 0 ? r.rows[0].edit_turn_count : null;
    return { ok: true, edit_turn_count: cnt, rowCount: r.rowCount };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

async function updateDraftAfterEdit(pool, draftId, fields) {
  const { draftJson, perFieldConfidence, farmerFacingPreview } = fields || {};
  try {
    const r = await pool.query(
      `UPDATE signal_draft
          SET draft_json=$2,
              per_field_confidence=$3,
              farmer_facing_preview=$4,
              updated_at=NOW()
        WHERE id=$1 AND status='awaiting_farmer'`,
      [draftId, draftJson ?? null, perFieldConfidence ?? null, farmerFacingPreview ?? null]
    );
    return { ok: true, rowCount: r.rowCount };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

async function findAwaitingForSender(pool, senderE164) {
  try {
    // Phase 45 Plan 04 follow-on (Plan 03 hand-off): include commit_failed in
    // the active-draft lookup so EDIT replies from a farmer on a failed commit
    // actually reach the edit-handler (which now accepts commit_failed per
    // Plan 03's Option X). Without this extension the EDIT-from-commit_failed
    // path is wired in code but unreachable at runtime from a real Signal reply.
    // Ordering: awaiting_farmer wins over commit_failed when both exist for the
    // same sender (most recent active confirm beats a leftover failed draft);
    // within the same status, most recent updated_at wins.
    const r = await pool.query(
      `SELECT * FROM signal_draft
        WHERE sender_e164=$1
          AND status IN ('awaiting_farmer','commit_failed')
        ORDER BY CASE status WHEN 'awaiting_farmer' THEN 0 ELSE 1 END ASC,
                 updated_at DESC
        LIMIT 1`,
      [senderE164]
    );
    return r.rows.length > 0 ? r.rows[0] : null;
  } catch (e) {
    // Defensive: bubble null so caller falls through; matches Phase 38 conventions.
    return null;
  }
}

async function findNudgeCandidates(pool, nudgeMin) {
  try {
    const r = await pool.query(
      `SELECT id, sender_e164, reply_target_kind, group_id, farmer_facing_preview, updated_at
         FROM signal_draft
        WHERE status='awaiting_farmer'
          AND nudge_sent_at IS NULL
          AND updated_at < NOW() - ($1 || ' minutes')::interval`,
      [nudgeMin]
    );
    return r.rows;
  } catch (e) {
    return [];
  }
}

async function findExpireCandidates(pool, timeoutMin) {
  try {
    const r = await pool.query(
      `SELECT id, sender_e164, reply_target_kind, group_id, farmer_facing_preview
         FROM signal_draft
        WHERE status='awaiting_farmer'
          AND updated_at < NOW() - ($1 || ' minutes')::interval`,
      [timeoutMin]
    );
    return r.rows;
  } catch (e) {
    return [];
  }
}

// ----- Plan 50-03: outbound quote-threading lookup -----

// getCaptureQuoteTarget(pool, captureId)
//   -> { signal_msg_ts, sender, raw_text } when the capture row exists AND
//      signal_msg_ts is non-null.
//   -> null in every other case (missing captureId, missing row, NULL ts,
//      ANY DB error). Never throws.
//
// This drives the outbound-confirm dispatcher's quote payload for
// send_commit_outcome_ack + send_confirm_ack. Per CONTEXT D-05 and memory
// [[feedback_no_silent_failure_after_farmer_confirm]] the dispatcher MUST
// degrade to an unquoted ack rather than block when this returns null --
// a vague ack beats no ack.
async function getCaptureQuoteTarget(pool, captureId) {
  if (!captureId) return null;
  if (!pool || typeof pool.query !== 'function') return null;
  try {
    const r = await pool.query(
      'SELECT signal_msg_ts, sender, raw_text FROM signal_capture WHERE id = $1 LIMIT 1',
      [captureId]
    );
    const row = r && r.rows && r.rows[0];
    if (!row || row.signal_msg_ts == null) return null;
    return {
      signal_msg_ts: row.signal_msg_ts,
      sender: row.sender,
      raw_text: row.raw_text == null ? '' : row.raw_text,
    };
  } catch (_e) {
    return null;
  }
}

module.exports = {
  initDb,
  confirmDraft,
  discardDraft,
  expireDraft,
  markNudgeSent,
  bumpEditTurn,
  updateDraftAfterEdit,
  appendEvent,
  appendEventViaPool,
  findAwaitingForSender,
  findNudgeCandidates,
  findExpireCandidates,
  getCaptureQuoteTarget,
};
