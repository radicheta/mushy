'use strict';

const commitDb = require('../../src/farmos/commit-db');
const { makeFakePool } = require('./fake-pool');

describe('commit-db (Phase 40 D-02/D-07)', () => {
  it('initDb issues 6 ALTER TABLE statements + 1 CREATE INDEX', async () => {
    const pool = makeFakePool();
    await commitDb.initDb(pool);
    const sqls = pool.queries.map((q) => q.sql);
    const alters = sqls.filter((s) => /^\s*ALTER TABLE/i.test(s));
    const indexes = sqls.filter((s) => /^\s*CREATE INDEX/i.test(s));
    expect(alters.length).toBe(6);
    expect(indexes.length).toBe(1);
    // Phase 45 D-01: outcome_ack_sent_at column ships at boot, no new index.
    expect(sqls.some((s) => /outcome_ack_sent_at timestamptz/i.test(s))).toBe(true);
    expect(sqls.some((s) => /CREATE INDEX[\s\S]+outcome_ack_sent_at/i.test(s))).toBe(false);
  });

  it('findConfirmedCandidates passes batchCap as LIMIT', async () => {
    const pool = makeFakePool();
    pool.seedDraft({ id: 'a', status: 'confirmed' });
    pool.seedDraft({ id: 'b', status: 'confirmed' });
    pool.seedDraft({ id: 'c', status: 'pending' });
    const rows = await commitDb.findConfirmedCandidates(pool, 5);
    const select = pool.queries.find((q) => /SELECT \* FROM signal_draft/i.test(q.sql));
    expect(select.params[0]).toBe(5);
    expect(rows.map((r) => r.id).sort()).toEqual(['a', 'b']);
  });

  it('acquireCommitLock rowCount=1 returns row', async () => {
    const pool = makeFakePool();
    pool.seedDraft({ id: 'a', status: 'confirmed' });
    const r = await commitDb.acquireCommitLock(pool, 'a');
    expect(r.ok).toBe(true);
    expect(r.rowCount).toBe(1);
    expect(r.row.id).toBe('a');
    expect(pool.getDraft('a').status).toBe('committing');
    expect(pool.getDraft('a').commit_attempt_count).toBe(1);
  });

  it('acquireCommitLock rowCount=0 returns row=null (race lost)', async () => {
    const pool = makeFakePool();
    pool.seedDraft({ id: 'a', status: 'committing' });
    const r = await commitDb.acquireCommitLock(pool, 'a');
    expect(r.ok).toBe(true);
    expect(r.rowCount).toBe(0);
    expect(r.row).toBeNull();
  });

  it('markCommitted JSON-encodes farmosResponse', async () => {
    const pool = makeFakePool();
    pool.seedDraft({ id: 'a', status: 'committing' });
    const resp = { asset_ids: ['u1'], log_ids: ['u2'], file_ids: [], http_status: 201, latency_ms: 432 };
    const r = await commitDb.markCommitted(pool, 'a', resp);
    expect(r.ok).toBe(true);
    expect(r.rowCount).toBe(1);
    const stored = pool.getDraft('a').farmos_response;
    expect(stored).toEqual(resp);
    expect(pool.getDraft('a').status).toBe('committed');
    // assert the SQL has the WHERE status='committing' guard
    const upd = pool.queries.find((q) => /UPDATE signal_draft/i.test(q.sql) && /status='committed'/i.test(q.sql));
    expect(upd.sql).toMatch(/WHERE id=\$1 AND status='committing'/);
  });

  it('markFailed sets commit_failed status with reason', async () => {
    const pool = makeFakePool();
    pool.seedDraft({ id: 'a', status: 'committing' });
    const r = await commitDb.markFailed(pool, 'a', 'http_422');
    expect(r.rowCount).toBe(1);
    expect(pool.getDraft('a').status).toBe('commit_failed');
    expect(pool.getDraft('a').commit_failed_reason).toBe('http_422');
  });

  it('requeueForRetry resets to confirmed and PRESERVES committed_at_attempt for backoff gate', async () => {
    const pool = makeFakePool();
    const prev = new Date();
    pool.seedDraft({ id: 'a', status: 'committing', committed_at_attempt: prev });
    const r = await commitDb.requeueForRetry(pool, 'a');
    expect(r.rowCount).toBe(1);
    expect(pool.getDraft('a').status).toBe('confirmed');
    // committed_at_attempt is intentionally preserved so the watchdog backoff
    // gate (Plan 05) can compare clock.now() - prev_attempt to backoff window.
    expect(pool.getDraft('a').committed_at_attempt).toBe(prev);
  });

  it('releaseStaleLocks RETURNS released ids', async () => {
    const pool = makeFakePool();
    const old = new Date(pool._now().getTime() - 10 * 60 * 1000);
    pool.seedDraft({ id: 'stale', status: 'committing', committed_at_attempt: old });
    pool.seedDraft({ id: 'fresh', status: 'committing', committed_at_attempt: pool._now() });
    const r = await commitDb.releaseStaleLocks(pool, 5);
    expect(r.rowCount).toBe(1);
    expect(r.released_ids).toEqual(['stale']);
    expect(pool.getDraft('stale').status).toBe('confirmed');
    expect(pool.getDraft('fresh').status).toBe('committing');
  });

  it('getCachedResponse returns farmos_response for committed draft', async () => {
    const pool = makeFakePool();
    const resp = { asset_ids: ['u1'] };
    pool.seedDraft({ id: 'a', status: 'committed', farmos_response: resp });
    const r = await commitDb.getCachedResponse(pool, 'a');
    expect(r.ok).toBe(true);
    expect(r.status).toBe('committed');
    expect(r.farmos_response).toEqual(resp);
  });

  // Phase 48 Plan 01: multi-asset / multi-log farmos_response round-trip.
  // The existing signal_draft.farmos_response JSONB column is the idempotency
  // surface for the seeding_session composite (1 asset + N child seeding logs).
  // There is NO separate signal_commit table (CONTEXT.md uses that name but the
  // actual implementation lives in signal_draft; reconciled silently per the
  // friction policy: missing-data ask, mismatch silent).
  it('markCommitted + getCachedResponse round-trip multi-asset multi-log shape (Phase 48 Plan 01)', async () => {
    const pool = makeFakePool();
    pool.seedDraft({ id: 'sess1', status: 'committing' });
    const resp = {
      asset_ids: ['asset-uuid-a'],
      log_ids: ['log-uuid-1', 'log-uuid-2', 'log-uuid-3'],
      file_ids: [],
      http_status: 201,
      latency_ms: 42,
    };
    const w = await commitDb.markCommitted(pool, 'sess1', resp);
    expect(w.ok).toBe(true);
    expect(w.rowCount).toBe(1);
    const r = await commitDb.getCachedResponse(pool, 'sess1');
    expect(r.ok).toBe(true);
    expect(r.status).toBe('committed');
    expect(r.farmos_response.asset_ids.length).toBe(1);
    expect(r.farmos_response.log_ids.length).toBe(3);
    expect(r.farmos_response).toEqual(resp);
  });

  // Phase 48 Plan 01: idempotent re-commit returns cached response unchanged.
  // Once status='committed', acquireCommitLock CANNOT re-acquire (WHERE
  // status='confirmed' guard returns rowCount=0). The watchdog must short-
  // circuit on the cached farmos_response instead of re-dispatching.
  it('idempotent re-commit on committed draft yields rowCount=0 lock + intact cache (Phase 48 Plan 01)', async () => {
    const pool = makeFakePool();
    const cached = {
      asset_ids: ['asset-uuid-a'],
      log_ids: ['log-uuid-1', 'log-uuid-2', 'log-uuid-3'],
      file_ids: [],
      http_status: 201,
      latency_ms: 42,
    };
    pool.seedDraft({ id: 'sess2', status: 'committed', farmos_response: cached });
    const lock = await commitDb.acquireCommitLock(pool, 'sess2');
    expect(lock.ok).toBe(true);
    expect(lock.rowCount).toBe(0); // guard rejected -- already committed
    expect(lock.row).toBeNull();
    const r = await commitDb.getCachedResponse(pool, 'sess2');
    expect(r.status).toBe('committed');
    expect(r.farmos_response).toEqual(cached);
    expect(pool.getDraft('sess2').status).toBe('committed'); // unchanged
  });

  // Phase 45 D-01 (ACK-04): mark-then-send idempotency primitive.
  describe('tryMarkOutcomeAckSent (Phase 45 D-01 / ACK-04)', () => {
    it('first call returns ok with claimed_at', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd1', status: 'commit_failed' });
      const r = await commitDb.tryMarkOutcomeAckSent(pool, 'd1');
      expect(r.ok).toBe(true);
      expect(r.id).toBe('d1');
      expect(r.claimed_at).toBeInstanceOf(Date);
      expect(pool.getDraft('d1').outcome_ack_sent_at).toBeInstanceOf(Date);
      // SQL audit: single CAS UPDATE with WHERE outcome_ack_sent_at IS NULL + RETURNING id.
      const upd = pool.queries.find((q) =>
        /UPDATE signal_draft[\s\S]+SET outcome_ack_sent_at = now\(\)/i.test(q.sql)
      );
      expect(upd).toBeDefined();
      expect(upd.sql).toMatch(/WHERE id=\$1 AND outcome_ack_sent_at IS NULL/);
      expect(upd.sql).toMatch(/RETURNING id, outcome_ack_sent_at/);
    });

    it('second call on already-claimed draft returns ok=false, reason=already_claimed', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd2', status: 'committed' });
      const first = await commitDb.tryMarkOutcomeAckSent(pool, 'd2');
      expect(first.ok).toBe(true);
      const second = await commitDb.tryMarkOutcomeAckSent(pool, 'd2');
      expect(second.ok).toBe(false);
      expect(second.reason).toBe('already_claimed');
    });

    it('unknown draftId returns ok=false, reason=not_found', async () => {
      const pool = makeFakePool();
      const r = await commitDb.tryMarkOutcomeAckSent(pool, 'does-not-exist');
      expect(r.ok).toBe(false);
      expect(r.reason).toBe('not_found');
    });
  });

  it('write helpers wrap errors and return {ok:false}', async () => {
    const pool = makeFakePool();
    pool.seedDraft({ id: 'a', status: 'committing' });
    pool.setThrowNext(new Error('boom'), /status='committed'/);
    const r = await commitDb.markCommitted(pool, 'a', { asset_ids: [] });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('boom');
  });
});
