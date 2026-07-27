'use strict';

// Phase 40 D-02 / D-02a / D-07: farmOS-write commit lifecycle persistence.
//
// Extends Phase 38/39's signal_draft table with the columns the commit
// pipeline needs and exposes the SQL primitives the commit-watchdog
// (Plan 05) and integration tests (Plan 07) consume.
//
// Allowed signal_draft.status values after this migration (validated in JS,
// NOT via pg CHECK constraint -- mirrors Phase 38/39 precedent):
//   pending | awaiting_farmer | confirmed | discarded | expired |
//   needs_review | committing | committed | commit_failed
//
// Atomic transitions all use a conditional UPDATE WHERE status='<prev>' so
// duplicate calls + watchdog/restart races collapse to rowCount=0 no-ops.
// All write helpers never-throw (try/catch returning {ok:false, reason}).
// No em-dashes anywhere in this file (memory: feedback_no_em_dashes_in_artifacts).

async function initDb(pool) {
  // Phase 62 D-01: the origin guard column must exist before findConfirmedCandidates
  // runs its `AND origin != 'python'` clause, otherwise the SELECT throws and the
  // never-throws wrapper returns [] (prod commits silently freeze). Adding it here
  // makes the patched alerter self-sufficient on a clean DB; the Python migration
  // adds the identical column independently (idempotent ADD COLUMN IF NOT EXISTS).
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'node'`
  );
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS farmos_response jsonb`
  );
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS committed_at timestamptz`
  );
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS commit_failed_reason text`
  );
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS commit_attempt_count int NOT NULL DEFAULT 0`
  );
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS committed_at_attempt timestamptz`
  );
  // Phase 45 D-01 (ACK-04): mark-then-send idempotency claim for commit
  // outcome acks. The CAS UPDATE in tryMarkOutcomeAckSent is the only writer.
  // No index: column is never scanned, only single-row CAS by id.
  await pool.query(
    `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS outcome_ack_sent_at timestamptz`
  );
  await pool.query(
    `CREATE INDEX IF NOT EXISTS idx_signal_draft_status_confirmed
       ON signal_draft (status, confirmed_at) WHERE status IN ('confirmed','committing')`
  );
}

async function findConfirmedCandidates(pool, batchCap) {
  try {
    const r = await pool.query(
      `SELECT * FROM signal_draft
        WHERE status='confirmed' AND origin != 'python'
        ORDER BY confirmed_at ASC NULLS LAST
        LIMIT $1`,
      [batchCap]
    );
    return r.rows || [];
  } catch (e) {
    return [];
  }
}

async function acquireCommitLock(pool, draftId) {
  try {
    const r = await pool.query(
      `UPDATE signal_draft
          SET status='committing',
              committed_at_attempt = now(),
              commit_attempt_count = commit_attempt_count + 1
        WHERE id=$1 AND status='confirmed'
        RETURNING *`,
      [draftId]
    );
    const row = r.rows && r.rows.length > 0 ? r.rows[0] : null;
    return { ok: true, rowCount: r.rowCount, row };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

async function markCommitted(pool, draftId, farmosResponse) {
  try {
    const r = await pool.query(
      `UPDATE signal_draft
          SET status='committed',
              farmos_response = $2::jsonb,
              committed_at = now()
        WHERE id=$1 AND status='committing'`,
      [draftId, farmosResponse == null ? null : JSON.stringify(farmosResponse)]
    );
    return { ok: true, rowCount: r.rowCount };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

async function markFailed(pool, draftId, reason) {
  try {
    const r = await pool.query(
      `UPDATE signal_draft
          SET status='commit_failed',
              commit_failed_reason = $2,
              committed_at = now()
        WHERE id=$1 AND status='committing'`,
      [draftId, reason == null ? null : String(reason)]
    );
    return { ok: true, rowCount: r.rowCount };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

async function requeueForRetry(pool, draftId) {
  // NOTE: committed_at_attempt is PRESERVED across requeue so the watchdog's
  // pre-lock backoff gate (Plan 05 task 2) can compare clock.now() - prev to
  // the configured backoff. releaseStaleLocks (the crash-recovery path) is
  // what NULLs committed_at_attempt back to a clean state.
  try {
    const r = await pool.query(
      `UPDATE signal_draft
          SET status='confirmed'
        WHERE id=$1 AND status='committing'`,
      [draftId]
    );
    return { ok: true, rowCount: r.rowCount };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

async function releaseStaleLocks(pool, staleMin) {
  try {
    const r = await pool.query(
      `UPDATE signal_draft
          SET status='confirmed',
              committed_at_attempt = NULL
        WHERE status='committing'
          AND committed_at_attempt < now() - ($1 || ' minutes')::interval
        RETURNING id`,
      [String(staleMin)]
    );
    const released_ids = (r.rows || []).map((row) => row.id);
    return { ok: true, rowCount: r.rowCount, released_ids };
  } catch (e) {
    return { ok: false, reason: e.message, released_ids: [] };
  }
}

async function getCachedResponse(pool, draftId) {
  try {
    const r = await pool.query(
      `SELECT status, farmos_response, commit_failed_reason
         FROM signal_draft WHERE id=$1`,
      [draftId]
    );
    if (!r.rows || r.rows.length === 0) {
      return { ok: false, reason: 'not_found' };
    }
    const row = r.rows[0];
    return {
      ok: true,
      status: row.status,
      farmos_response: row.farmos_response,
      commit_failed_reason: row.commit_failed_reason,
    };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

async function getAttemptCount(pool, draftId) {
  try {
    const r = await pool.query(
      `SELECT commit_attempt_count FROM signal_draft WHERE id=$1`,
      [draftId]
    );
    if (!r.rows || r.rows.length === 0) return { ok: false, reason: 'not_found' };
    return { ok: true, commit_attempt_count: r.rows[0].commit_attempt_count };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

// Phase 45 D-01 (ACK-04): mark-then-send claim primitive.
//
// Single-statement CAS that converts a NULL outcome_ack_sent_at into now() and
// returns the row exactly once. Second + Nth callers see rowCount=0 and get
// { ok:false, reason:'already_claimed' }. Unknown id => { ok:false,
// reason:'not_found' }. SQL errors throw (consistent with the read helpers'
// shape, distinct from the never-throw write helpers above; this is the
// dispatch-side primitive and callers must see hard failures).
async function tryMarkOutcomeAckSent(pool, draftId) {
  const exists = await pool.query(
    `SELECT 1 FROM signal_draft WHERE id=$1`,
    [draftId]
  );
  if (!exists.rows || exists.rows.length === 0) {
    return { ok: false, reason: 'not_found' };
  }
  const r = await pool.query(
    `UPDATE signal_draft
        SET outcome_ack_sent_at = now()
      WHERE id=$1 AND outcome_ack_sent_at IS NULL
      RETURNING id, outcome_ack_sent_at`,
    [draftId]
  );
  if (r.rowCount === 0) {
    return { ok: false, reason: 'already_claimed' };
  }
  return { ok: true, id: r.rows[0].id, claimed_at: r.rows[0].outcome_ack_sent_at };
}

module.exports = {
  initDb,
  findConfirmedCandidates,
  acquireCommitLock,
  markCommitted,
  markFailed,
  requeueForRetry,
  releaseStaleLocks,
  getCachedResponse,
  getAttemptCount,
  tryMarkOutcomeAckSent,
};
