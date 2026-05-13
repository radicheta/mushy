'use strict';

// Phase 40 in-memory pg pool fake for commit-db tests. Recognizes the SQL
// shapes commit-db.js issues plus the inserts/seeds the test harness needs.
// Records every query call in pool.queries[] (sql + params) so tests can
// assert call counts / shapes.
//
// Time math uses pool._now() so tests can advance the clock.

function makeFakePool() {
  const drafts = new Map(); // id -> row
  const queries = []; // {sql, params}
  let nowMs = Date.now();
  let throwNext = null; // {match: regex|null, error: Error}

  function _now() { return new Date(nowMs); }
  function setNow(ms) { nowMs = ms; }

  function seedDraft(row) {
    const full = Object.assign(
      {
        id: row.id,
        sender_e164: row.sender_e164 || '+15550001234',
        farmos_person: row.farmos_person || null,
        source_capture_ids: row.source_capture_ids || [],
        status: row.status || 'confirmed',
        log_type: row.log_type || 'seeding',
        draft_json: row.draft_json || null,
        per_field_confidence: row.per_field_confidence || null,
        farmer_facing_preview: row.farmer_facing_preview || null,
        confirmed_at: row.confirmed_at || _now(),
        farmos_response: row.farmos_response || null,
        committed_at: row.committed_at || null,
        commit_failed_reason: row.commit_failed_reason || null,
        commit_attempt_count: row.commit_attempt_count || 0,
        committed_at_attempt: row.committed_at_attempt || null,
        created_at: row.created_at || _now(),
        updated_at: row.updated_at || _now(),
      },
      row
    );
    drafts.set(full.id, full);
    return full;
  }

  function getDraft(id) { return drafts.get(id); }

  function setThrowNext(err, match) { throwNext = { error: err, match: match || null }; }

  async function query(sql, params) {
    params = params || [];
    const s = String(sql);
    queries.push({ sql: s, params });

    if (throwNext && (throwNext.match == null || throwNext.match.test(s))) {
      const err = throwNext.error;
      throwNext = null;
      throw err;
    }

    if (/^\s*ALTER TABLE/i.test(s)) return { rows: [], rowCount: 0 };
    if (/^\s*CREATE INDEX/i.test(s)) return { rows: [], rowCount: 0 };
    if (/^\s*BEGIN|^\s*COMMIT|^\s*ROLLBACK/i.test(s)) return { rows: [], rowCount: 0 };

    // findConfirmedCandidates
    if (/SELECT \* FROM signal_draft\s+WHERE status='confirmed'/i.test(s)) {
      const limit = params[0];
      const rows = Array.from(drafts.values())
        .filter((r) => r.status === 'confirmed')
        .sort((a, b) => new Date(a.confirmed_at || 0) - new Date(b.confirmed_at || 0))
        .slice(0, limit);
      return { rows, rowCount: rows.length };
    }

    // getCachedResponse
    if (/SELECT status, farmos_response, commit_failed_reason/i.test(s)) {
      const id = params[0];
      const r = drafts.get(id);
      if (!r) return { rows: [], rowCount: 0 };
      return { rows: [{ status: r.status, farmos_response: r.farmos_response, commit_failed_reason: r.commit_failed_reason }], rowCount: 1 };
    }

    // getAttemptCount
    if (/SELECT commit_attempt_count FROM signal_draft/i.test(s)) {
      const id = params[0];
      const r = drafts.get(id);
      if (!r) return { rows: [], rowCount: 0 };
      return { rows: [{ commit_attempt_count: r.commit_attempt_count }], rowCount: 1 };
    }

    // acquireCommitLock
    if (/UPDATE signal_draft[\s\S]+status='committing'[\s\S]+WHERE id=\$1 AND status='confirmed'/i.test(s)) {
      const id = params[0];
      const r = drafts.get(id);
      if (!r || r.status !== 'confirmed') return { rows: [], rowCount: 0 };
      r.status = 'committing';
      r.committed_at_attempt = _now();
      r.commit_attempt_count = (r.commit_attempt_count || 0) + 1;
      return { rows: [{ ...r }], rowCount: 1 };
    }

    // markCommitted
    if (/UPDATE signal_draft[\s\S]+status='committed'[\s\S]+WHERE id=\$1 AND status='committing'/i.test(s)) {
      const id = params[0];
      const r = drafts.get(id);
      if (!r || r.status !== 'committing') return { rows: [], rowCount: 0 };
      r.status = 'committed';
      let resp = params[1];
      if (typeof resp === 'string') {
        try { resp = JSON.parse(resp); } catch (_) { /* keep string */ }
      }
      r.farmos_response = resp;
      r.committed_at = _now();
      return { rows: [], rowCount: 1 };
    }

    // markFailed
    if (/UPDATE signal_draft[\s\S]+status='commit_failed'[\s\S]+WHERE id=\$1 AND status='committing'/i.test(s)) {
      const id = params[0];
      const r = drafts.get(id);
      if (!r || r.status !== 'committing') return { rows: [], rowCount: 0 };
      r.status = 'commit_failed';
      r.commit_failed_reason = params[1];
      r.committed_at = _now();
      return { rows: [], rowCount: 1 };
    }

    // requeueForRetry
    if (/UPDATE signal_draft[\s\S]+status='confirmed'[\s\S]+committed_at_attempt = NULL[\s\S]+WHERE id=\$1 AND status='committing'/i.test(s)) {
      const id = params[0];
      const r = drafts.get(id);
      if (!r || r.status !== 'committing') return { rows: [], rowCount: 0 };
      r.status = 'confirmed';
      r.committed_at_attempt = null;
      return { rows: [], rowCount: 1 };
    }

    // releaseStaleLocks
    if (/UPDATE signal_draft[\s\S]+WHERE status='committing'[\s\S]+committed_at_attempt < now/i.test(s)) {
      const staleMin = parseInt(params[0], 10);
      const cutoff = nowMs - staleMin * 60 * 1000;
      const released = [];
      for (const r of drafts.values()) {
        if (r.status === 'committing' && r.committed_at_attempt && new Date(r.committed_at_attempt).getTime() < cutoff) {
          r.status = 'confirmed';
          r.committed_at_attempt = null;
          released.push({ id: r.id });
        }
      }
      return { rows: released, rowCount: released.length };
    }

    return { rows: [], rowCount: 0 };
  }

  async function connect() {
    return { query, release() {} };
  }

  return { query, connect, _now, setNow, seedDraft, getDraft, queries, setThrowNext, _drafts: drafts };
}

module.exports = { makeFakePool };
