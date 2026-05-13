'use strict';

const { createCommitWatchdog } = require('../../src/farmos/commit-watchdog');

function makeCommitDb(initial) {
  const drafts = new Map(initial || []);
  const calls = [];
  return {
    _drafts: drafts,
    _calls: calls,
    async releaseStaleLocks(pool, staleMin) {
      calls.push({ fn: 'releaseStaleLocks', staleMin });
      return { ok: true, rowCount: 0, released_ids: [] };
    },
    async findConfirmedCandidates(pool, batchCap) {
      calls.push({ fn: 'findConfirmedCandidates', batchCap });
      return Array.from(drafts.values()).filter((r) => r.status === 'confirmed').slice(0, batchCap);
    },
    async getCachedResponse(pool, id) {
      const r = drafts.get(id);
      if (!r) return { ok: false };
      return { ok: true, status: r.status, farmos_response: r.farmos_response, commit_failed_reason: r.commit_failed_reason };
    },
    async acquireCommitLock(pool, id) {
      calls.push({ fn: 'acquireCommitLock', id });
      const r = drafts.get(id);
      if (!r || r.status !== 'confirmed') return { ok: true, rowCount: 0, row: null };
      r.status = 'committing';
      r.commit_attempt_count = (r.commit_attempt_count || 0) + 1;
      r.committed_at_attempt = new Date();
      return { ok: true, rowCount: 1, row: { ...r } };
    },
    async markCommitted(pool, id, resp) {
      calls.push({ fn: 'markCommitted', id, resp });
      const r = drafts.get(id);
      if (r) { r.status = 'committed'; r.farmos_response = resp; }
      return { ok: true, rowCount: 1 };
    },
    async markFailed(pool, id, reason) {
      calls.push({ fn: 'markFailed', id, reason });
      const r = drafts.get(id);
      if (r) { r.status = 'commit_failed'; r.commit_failed_reason = reason; }
      return { ok: true, rowCount: 1 };
    },
    async requeueForRetry(pool, id) {
      calls.push({ fn: 'requeueForRetry', id });
      const r = drafts.get(id);
      if (r) { r.status = 'confirmed'; r.committed_at_attempt = null; }
      return { ok: true, rowCount: 1 };
    },
  };
}

function makeAudit() {
  const events = [];
  return {
    _events: events,
    logCommit: jest.fn(async (event, draft, result) => { events.push({ event, draft_id: draft && draft.id, result }); }),
  };
}

function build({ routerImpl, drafts, releaseStaleImpl, configOverride } = {}) {
  const commitDb = makeCommitDb(drafts);
  if (releaseStaleImpl) commitDb.releaseStaleLocks = releaseStaleImpl;
  const auditLogger = makeAudit();
  const commitRouter = { commit: jest.fn(routerImpl || (async () => ({ ok: true, asset_ids: ['a1'], log_ids: ['l1'], file_ids: [], http_status: 201, latency_ms: 50 }))) };
  const config = Object.assign({
    commitWatchdogIntervalMs: 30000,
    commitWatchdogBatchCap: 10,
    commitRetryMax: 3,
    commitRetryBackoffMs: [1000, 4000, 16000],
    commitLockStaleMin: 5,
  }, configOverride || {});
  const wd = createCommitWatchdog({
    pool: {}, commitDb, farmosClient: {}, commitRouter, ctx: {}, config, auditLogger,
    logger: { info() {}, warn() {} },
    clock: { now: () => 100000 },
  });
  return { wd, commitDb, auditLogger, commitRouter };
}

describe('commit-watchdog (Phase 40 Plan 05)', () => {
  it('tickOnce with no rows is a no-op', async () => {
    const { wd, commitRouter } = build({ drafts: [] });
    await wd.tickOnce();
    expect(commitRouter.commit).not.toHaveBeenCalled();
  });

  it('one row: probe miss -> lock -> commit -> markCommitted', async () => {
    const { wd, commitDb, auditLogger, commitRouter } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding', commit_attempt_count: 0 }]],
    });
    await wd.tickOnce();
    expect(commitRouter.commit).toHaveBeenCalledTimes(1);
    expect(commitDb._drafts.get('d1').status).toBe('committed');
    const events = auditLogger._events.map((e) => e.event);
    expect(events).toEqual(['commit_attempt', 'commit_success']);
  });

  it('already-committed cache hit emits commit_idempotent_noop, no lock', async () => {
    const { wd, commitDb, auditLogger, commitRouter } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding' }]],
    });
    // Trick: set up cache so the probe sees status=committed
    commitDb.getCachedResponse = async () => ({ ok: true, status: 'committed', farmos_response: { asset_ids: ['cached'] } });
    await wd.tickOnce();
    expect(commitRouter.commit).not.toHaveBeenCalled();
    expect(auditLogger._events[0].event).toBe('commit_idempotent_noop');
  });

  it('race-lost lock (rowCount=0) silent skip', async () => {
    const { wd, commitDb, auditLogger, commitRouter } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding' }]],
    });
    commitDb.acquireCommitLock = async () => ({ ok: true, rowCount: 0, row: null });
    await wd.tickOnce();
    expect(commitRouter.commit).not.toHaveBeenCalled();
    expect(auditLogger._events.length).toBe(0);
  });

  it('success emits commit_attempt + commit_success in order', async () => {
    const { wd, auditLogger } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding' }]],
    });
    await wd.tickOnce();
    expect(auditLogger._events.map((e) => e.event)).toEqual(['commit_attempt', 'commit_success']);
  });

  it('transient failure with attempts=1: requeueForRetry, NOT markFailed', async () => {
    const { wd, commitDb, auditLogger } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding', commit_attempt_count: 0 }]],
      routerImpl: async () => ({ ok: false, http_status: 500, reason: 'http_500', asset_ids: [], log_ids: [], file_ids: [] }),
    });
    await wd.tickOnce();
    expect(commitDb._drafts.get('d1').status).toBe('confirmed'); // requeued
    expect(auditLogger._events.map((e) => e.event)).toContain('commit_attempt_retry');
    expect(auditLogger._events.map((e) => e.event)).not.toContain('commit_failed');
  });

  it('transient failure with attempts=retryMax: markFailed', async () => {
    const { wd, commitDb, auditLogger } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding', commit_attempt_count: 2 }]],
      routerImpl: async () => ({ ok: false, http_status: 500, reason: 'http_500', asset_ids: [], log_ids: [], file_ids: [] }),
    });
    await wd.tickOnce();
    // After lock acquire, commit_attempt_count goes to 3 (= retryMax). Treat as terminal.
    expect(commitDb._drafts.get('d1').status).toBe('commit_failed');
    expect(auditLogger._events.map((e) => e.event)).toContain('commit_failed');
  });

  it('terminal 4xx (422) marks failed immediately (not transient)', async () => {
    const { wd, commitDb, auditLogger } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding', commit_attempt_count: 0 }]],
      routerImpl: async () => ({ ok: false, http_status: 422, reason: 'http_422', asset_ids: [], log_ids: [], file_ids: [] }),
    });
    await wd.tickOnce();
    expect(commitDb._drafts.get('d1').status).toBe('commit_failed');
    expect(auditLogger._events.map((e) => e.event)).toContain('commit_failed');
  });

  it('backoff gate: attempts=2 + recent attempt -> requeue without commit', async () => {
    const { wd, commitDb, commitRouter } = build({
      drafts: [['d1', {
        id: 'd1', status: 'confirmed', log_type: 'seeding',
        commit_attempt_count: 1, // pre-lock; after lock becomes 2
        committed_at_attempt: new Date(100000 - 100), // very recent
      }]],
    });
    await wd.tickOnce();
    expect(commitRouter.commit).not.toHaveBeenCalled();
    expect(commitDb._drafts.get('d1').status).toBe('confirmed'); // requeued by gate
  });

  it('stale lock release emits commit_stale_released audit per id', async () => {
    const { wd, auditLogger } = build({
      drafts: [],
      releaseStaleImpl: async () => ({ ok: true, rowCount: 2, released_ids: ['s1', 's2'] }),
    });
    await wd.tickOnce();
    const releases = auditLogger._events.filter((e) => e.event === 'commit_stale_released');
    expect(releases.length).toBe(2);
  });

  it('releaseStaleLocks invoked with configured staleMin on every tick', async () => {
    const { wd, commitDb } = build({ drafts: [], configOverride: { commitLockStaleMin: 5 } });
    await wd.tickOnce();
    const releaseCalls = commitDb._calls.filter((c) => c.fn === 'releaseStaleLocks');
    expect(releaseCalls.length).toBe(1);
    expect(releaseCalls[0].staleMin).toBe(5);
  });

  it('start() awaits first tickOnce before setInterval (observable via commitDb call)', async () => {
    const { wd, commitDb } = build({ drafts: [] });
    const callsBefore = commitDb._calls.length;
    await wd.start();
    // First tick should have invoked releaseStaleLocks + findConfirmedCandidates synchronously before returning.
    const callsAfter = commitDb._calls.length;
    expect(callsAfter).toBeGreaterThan(callsBefore);
    wd.stop();
  });

  it('row exception isolated; second row still processes', async () => {
    const { wd, commitDb } = build({
      drafts: [
        ['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding' }],
        ['d2', { id: 'd2', status: 'confirmed', log_type: 'seeding' }],
      ],
    });
    // First call throws, second succeeds
    let n = 0;
    const origGet = commitDb.getCachedResponse;
    commitDb.getCachedResponse = async (...args) => {
      n++;
      if (n === 1) throw new Error('boom');
      return origGet.call(commitDb, ...args);
    };
    await wd.tickOnce();
    // d2 should still be processed
    expect(commitDb._drafts.get('d2').status).toBe('committed');
  });
});
