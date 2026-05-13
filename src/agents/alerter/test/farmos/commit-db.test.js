'use strict';

const commitDb = require('../../src/farmos/commit-db');
const { makeFakePool } = require('./fake-pool');

describe('commit-db (Phase 40 D-02/D-07)', () => {
  it('initDb issues 5 ALTER TABLE statements + 1 CREATE INDEX', async () => {
    const pool = makeFakePool();
    await commitDb.initDb(pool);
    const sqls = pool.queries.map((q) => q.sql);
    const alters = sqls.filter((s) => /^\s*ALTER TABLE/i.test(s));
    const indexes = sqls.filter((s) => /^\s*CREATE INDEX/i.test(s));
    expect(alters.length).toBe(5);
    expect(indexes.length).toBe(1);
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

  it('requeueForRetry resets to confirmed and nulls committed_at_attempt', async () => {
    const pool = makeFakePool();
    pool.seedDraft({ id: 'a', status: 'committing', committed_at_attempt: new Date() });
    const r = await commitDb.requeueForRetry(pool, 'a');
    expect(r.rowCount).toBe(1);
    expect(pool.getDraft('a').status).toBe('confirmed');
    expect(pool.getDraft('a').committed_at_attempt).toBeNull();
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

  it('write helpers wrap errors and return {ok:false}', async () => {
    const pool = makeFakePool();
    pool.seedDraft({ id: 'a', status: 'committing' });
    pool.setThrowNext(new Error('boom'), /status='committed'/);
    const r = await commitDb.markCommitted(pool, 'a', { asset_ids: [] });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('boom');
  });
});
