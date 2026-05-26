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
    // Phase 45 Plan 01 / Plan 04: idempotent CAS claim for terminal-state ack.
    // Tracks which draft ids have been claimed in an in-memory Set so concurrent
    // ticks converge to exactly one ok=true return.
    _ackClaimed: new Set(),
    async tryMarkOutcomeAckSent(pool, id) {
      calls.push({ fn: 'tryMarkOutcomeAckSent', id });
      if (!drafts.has(id)) return { ok: false, reason: 'not_found' };
      if (this._ackClaimed.has(id)) return { ok: false, reason: 'already_claimed' };
      this._ackClaimed.add(id);
      return { ok: true, id, claimed_at: new Date() };
    },
  };
}

function makeOutboundConfirm() {
  return { dispatch: jest.fn().mockResolvedValue({ ok: true }) };
}

function makeAudit() {
  const events = [];
  return {
    _events: events,
    logCommit: jest.fn(async (event, draft, result) => { events.push({ event, draft_id: draft && draft.id, result }); }),
  };
}

function build({ routerImpl, drafts, releaseStaleImpl, configOverride, outboundConfirm } = {}) {
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
    outboundConfirm: outboundConfirm || null,
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

  // -----------------------------------------------------------------------
  // Phase 45 Plan 04: terminal-state ack dispatch (T4 + T6) + ACK-04 idempotency
  // -----------------------------------------------------------------------

  it('T4 commit_success: dispatches send_commit_outcome_ack once with outcome=success', async () => {
    const outboundConfirm = makeOutboundConfirm();
    const { wd, commitDb } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding', sender_e164: '+15550001234' }]],
      outboundConfirm,
    });
    await wd.tickOnce();
    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);
    const args = outboundConfirm.dispatch.mock.calls[0];
    expect(args[0]).toBe('send_commit_outcome_ack');
    expect(args[1].id).toBe('d1');
    expect(args[2]).toEqual({ outcome: 'success' });
    // tryMarkOutcomeAckSent called exactly once
    expect(commitDb._calls.filter((c) => c.fn === 'tryMarkOutcomeAckSent').length).toBe(1);
  });

  it('T4 commit_success: forwards attachmentsFailed count to the ack when uploads failed', async () => {
    const outboundConfirm = makeOutboundConfirm();
    const { wd } = build({
      routerImpl: async () => ({
        ok: true, asset_ids: [], log_ids: ['l1'], file_ids: [],
        attachments_failed: [{ reason: 'http_500' }, { reason: 'http_500' }],
        http_status: 201, latency_ms: 50,
      }),
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'observation', sender_e164: '+15550001234' }]],
      outboundConfirm,
    });
    await wd.tickOnce();
    const args = outboundConfirm.dispatch.mock.calls[0];
    expect(args[0]).toBe('send_commit_outcome_ack');
    expect(args[2]).toEqual({ outcome: 'success', attachmentsFailed: 2 });
  });

  it('T6 commit_failed (terminal 4xx): dispatches send_commit_outcome_ack once with outcome=failed + reason', async () => {
    const outboundConfirm = makeOutboundConfirm();
    const { wd, commitDb } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'observation', sender_e164: '+15550001234', commit_attempt_count: 0 }]],
      routerImpl: async () => ({ ok: false, http_status: 422, reason: 'observation_requires_target', asset_ids: [], log_ids: [], file_ids: [] }),
      outboundConfirm,
    });
    await wd.tickOnce();
    expect(commitDb._drafts.get('d1').status).toBe('commit_failed');
    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);
    const args = outboundConfirm.dispatch.mock.calls[0];
    expect(args[0]).toBe('send_commit_outcome_ack');
    expect(args[2]).toEqual({ outcome: 'failed', reason: 'observation_requires_target' });
    expect(commitDb._calls.filter((c) => c.fn === 'tryMarkOutcomeAckSent').length).toBe(1);
  });

  it('ACK-04 idempotency: two concurrent ticks on same draft -> exactly one ack dispatch', async () => {
    // Simulated by two sequential tickOnce calls; the second tick's claim returns
    // ok=false because the in-memory ack-claimed Set already contains the draft id.
    // We force the watchdog to "see" the row again on tick 2 by resetting status
    // back to 'confirmed' after tick 1 (mirroring a hypothetical race where a
    // duplicate detector mistakenly re-queues a committed row).
    const outboundConfirm = makeOutboundConfirm();
    const { wd, commitDb } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding', sender_e164: '+15550001234' }]],
      outboundConfirm,
    });
    await wd.tickOnce();
    // Reset draft status so tickOnce sees a fresh confirmed row again. The CAS
    // claim still remembers d1 has been claimed.
    const row = commitDb._drafts.get('d1');
    row.status = 'confirmed';
    row.commit_attempt_count = 0;
    row.committed_at_attempt = null;
    await wd.tickOnce();
    // Total ack dispatches across both ticks must be EXACTLY 1.
    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);
    // tryMarkOutcomeAckSent was attempted twice; second attempt returned ok=false.
    expect(commitDb._calls.filter((c) => c.fn === 'tryMarkOutcomeAckSent').length).toBe(2);
  });

  it('T5 commit_attempt_retry (transient): NO ack dispatch on retry path', async () => {
    const outboundConfirm = makeOutboundConfirm();
    const { wd, auditLogger } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding', sender_e164: '+15550001234', commit_attempt_count: 0 }]],
      routerImpl: async () => ({ ok: false, http_status: 500, reason: 'http_500', asset_ids: [], log_ids: [], file_ids: [] }),
      outboundConfirm,
    });
    await wd.tickOnce();
    expect(auditLogger._events.map((e) => e.event)).toContain('commit_attempt_retry');
    expect(outboundConfirm.dispatch).not.toHaveBeenCalled();
  });

  it('graceful degrade: outboundConfirm absent -> no crash, no dispatch, commit still succeeds', async () => {
    const { wd, commitDb } = build({
      drafts: [['d1', { id: 'd1', status: 'confirmed', log_type: 'seeding', sender_e164: '+15550001234' }]],
      // outboundConfirm intentionally omitted
    });
    await wd.tickOnce();
    expect(commitDb._drafts.get('d1').status).toBe('committed');
    // tryMarkOutcomeAckSent IS still called (claim won) -- accepted trade-off
    // per plan: "A crash between mark and send leaves the draft marked".
    expect(commitDb._calls.filter((c) => c.fn === 'tryMarkOutcomeAckSent').length).toBe(1);
  });

  // -----------------------------------------------------------------------
  // Phase 48 Plan 04: seeding_session rides the Phase 45 ack contract
  // -----------------------------------------------------------------------

  it('Phase 48: seeding_session success dispatches send_commit_outcome_ack with outcome=success', async () => {
    const outboundConfirm = makeOutboundConfirm();
    const { wd, commitDb } = build({
      drafts: [['sess1', {
        id: 'sess1',
        status: 'confirmed',
        log_type: 'seeding_session',
        sender_e164: '+59891000001',
        commit_attempt_count: 0,
        draft_json: { type: 'seeding_session', event_date: '2026-05-22', groups: [{ child_block_names: { value: ['a','b','c'] } }] },
      }]],
      routerImpl: async () => ({
        ok: true,
        asset_ids: ['s1','b1','c1','c2','c3'],
        log_ids: ['l1','l2','l3'],
        file_ids: [],
        http_status: 201,
        latency_ms: 42,
      }),
      outboundConfirm,
    });
    await wd.tickOnce();
    expect(commitDb._drafts.get('sess1').status).toBe('committed');
    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);
    const args = outboundConfirm.dispatch.mock.calls[0];
    expect(args[0]).toBe('send_commit_outcome_ack');
    expect(args[1].id).toBe('sess1');
    expect(args[1].log_type).toBe('seeding_session');
    expect(args[2]).toEqual({ outcome: 'success' });
  });

  it('Phase 48: seeding_session terminal failure dispatches send_commit_outcome_ack with outcome=failed + reason=partial_commit_failed', async () => {
    const outboundConfirm = makeOutboundConfirm();
    const { wd, commitDb } = build({
      drafts: [['sess1', {
        id: 'sess1',
        status: 'confirmed',
        log_type: 'seeding_session',
        sender_e164: '+59891000001',
        commit_attempt_count: 0,
      }]],
      // 422 is terminal (4xx, not transient) -> markFailed on first attempt
      routerImpl: async () => ({ ok: false, http_status: 422, reason: 'partial_commit_failed', asset_ids: [], log_ids: [], file_ids: [] }),
      outboundConfirm,
    });
    await wd.tickOnce();
    expect(commitDb._drafts.get('sess1').status).toBe('commit_failed');
    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);
    const args = outboundConfirm.dispatch.mock.calls[0];
    expect(args[0]).toBe('send_commit_outcome_ack');
    expect(args[1].log_type).toBe('seeding_session');
    expect(args[2]).toEqual({ outcome: 'failed', reason: 'partial_commit_failed' });
  });

  it('Phase 48: idempotent no-op for already-committed seeding_session (no ack dispatch)', async () => {
    const outboundConfirm = makeOutboundConfirm();
    const { wd, commitDb, auditLogger } = build({
      drafts: [['sess1', {
        id: 'sess1',
        status: 'confirmed',
        log_type: 'seeding_session',
        sender_e164: '+59891000001',
      }]],
      outboundConfirm,
    });
    // Probe sees status=committed already -> early return before any lock or ack dispatch.
    commitDb.getCachedResponse = async () => ({
      ok: true,
      status: 'committed',
      farmos_response: { asset_ids: ['s1','c1','c2','c3'], log_ids: ['l1','l2','l3'] },
    });
    await wd.tickOnce();
    expect(outboundConfirm.dispatch).not.toHaveBeenCalled();
    expect(auditLogger._events[0].event).toBe('commit_idempotent_noop');
    // CAS not even attempted (early return before _maybeDispatchOutcomeAck)
    expect(commitDb._calls.filter((c) => c.fn === 'tryMarkOutcomeAckSent').length).toBe(0);
  });

  it('Phase 48: commit_failed seeding_session is not re-fetched on subsequent ticks (no double ack)', async () => {
    // findConfirmedCandidates filters on status='confirmed'; commit_failed rows
    // never re-enter the loop, so a second tick is a no-op for ack purposes.
    const outboundConfirm = makeOutboundConfirm();
    const { wd, commitDb } = build({
      drafts: [['sess1', {
        id: 'sess1',
        status: 'confirmed',
        log_type: 'seeding_session',
        sender_e164: '+59891000001',
        commit_attempt_count: 0,
      }]],
      routerImpl: async () => ({ ok: false, http_status: 422, reason: 'session_fungi_type_term_missing', asset_ids: [], log_ids: [], file_ids: [] }),
      outboundConfirm,
    });
    await wd.tickOnce(); // marks failed + dispatches ack #1
    expect(commitDb._drafts.get('sess1').status).toBe('commit_failed');
    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);
    await wd.tickOnce(); // no candidates returned (status !== 'confirmed')
    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);
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

// =====================================================================
// Phase 54.1 Plan 03 Task 3: per-draft createMissingFungiType authorization
// =====================================================================

describe('Phase 54.1 Plan 03: per-draft mint authorization via strain_confirm_approved', () => {
  function buildWithCtx(draftRow, sharedCtx = {}) {
    const commitDb = makeCommitDb([[draftRow.id, draftRow]]);
    const auditLogger = makeAudit();
    const capturedCtxs = [];
    const commitRouter = {
      commit: jest.fn(async (client, row, ctx) => {
        capturedCtxs.push({ row_id: row.id, createMissingFungiType: ctx && ctx.createMissingFungiType });
        return { ok: true, asset_ids: ['a1'], log_ids: ['l1'], file_ids: [], http_status: 201, latency_ms: 10 };
      }),
    };
    const config = {
      commitWatchdogIntervalMs: 30000,
      commitWatchdogBatchCap: 10,
      commitRetryMax: 3,
      commitRetryBackoffMs: [1000],
      commitLockStaleMin: 5,
    };
    const wd = createCommitWatchdog({
      pool: {}, commitDb, farmosClient: {}, commitRouter,
      ctx: sharedCtx, config, auditLogger,
      logger: { info() {}, warn() {} },
      clock: { now: () => 100000 },
    });
    return { wd, capturedCtxs };
  }

  it('strain_confirm_approved draft -> commitRouter called with createMissingFungiType=true', async () => {
    const draftRow = {
      id: 'approved-draft',
      status: 'confirmed',
      needs_review_reason: 'strain_confirm_approved',
      log_type: 'seeding',
      commit_attempt_count: 0,
    };
    const { wd, capturedCtxs } = buildWithCtx(draftRow, { createMissingFungiType: false });
    await wd.tickOnce();
    expect(capturedCtxs.length).toBe(1);
    expect(capturedCtxs[0].createMissingFungiType).toBe(true);
  });

  it('normal draft (no strain marker) -> commitRouter called with createMissingFungiType=false', async () => {
    const draftRow = {
      id: 'normal-draft',
      status: 'confirmed',
      needs_review_reason: null,
      log_type: 'seeding',
      commit_attempt_count: 0,
    };
    const { wd, capturedCtxs } = buildWithCtx(draftRow, { createMissingFungiType: false });
    await wd.tickOnce();
    expect(capturedCtxs.length).toBe(1);
    expect(capturedCtxs[0].createMissingFungiType).toBe(false);
  });

  it('shared ctx createMissingFungiType=true passes through for any draft (backfill path)', async () => {
    const draftRow = {
      id: 'backfill-draft',
      status: 'confirmed',
      needs_review_reason: null,
      log_type: 'seeding',
      commit_attempt_count: 0,
    };
    const { wd, capturedCtxs } = buildWithCtx(draftRow, { createMissingFungiType: true });
    await wd.tickOnce();
    expect(capturedCtxs.length).toBe(1);
    expect(capturedCtxs[0].createMissingFungiType).toBe(true);
  });
});
