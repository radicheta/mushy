'use strict';

// Phase 48 Plan 05 Task 1: HERMETIC SHIP-GATE for INOC-05 idempotency
// (double-YES is a no-op).
//
// The double-YES contract has two layers in production:
//
//   1. findConfirmedCandidates SQL filters on status='confirmed'. Once a row
//      is marked 'committed', subsequent ticks never re-fetch it. Tested by
//      "second tick after success is a no-op" below.
//
//   2. Defense in depth: if a row IS somehow re-presented to _processRow at
//      status='committed' (e.g. concurrent race, or a manual re-queue), the
//      idempotency probe at commit-watchdog.js line 77 short-circuits via
//      getCachedResponse + commit_idempotent_noop audit. No farmosClient.post,
//      no outboundConfirm.dispatch.
//
// Both layers asserted here.

const { buildHarness } = require('./_session-commit-harness');

describe('seeding-session commit pipeline -- INOC-05 idempotency (Phase 48 Plan 05 Task 1)', () => {
  it('double tickOnce: second tick is a no-op (zero new writes, zero new ack dispatches)', async () => {
    const { watchdog, commitDb, farmosClient, auditLogger, outboundConfirm, row } = buildHarness();

    // First tick: full happy-path commit.
    await watchdog.tickOnce();
    // Phase 52: 16 fungi + 1 session group; 11 seeding + 1 activity = 12 logs.
    expect(farmosClient._created.assets.length).toBe(16);
    expect(farmosClient._created.groups.length).toBe(1);
    expect(farmosClient._created.logs.length).toBe(12);
    expect(commitDb._drafts.get(row.id).status).toBe('committed');
    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);

    // Snapshot counts.
    const postCallsAfterFirst = farmosClient.post.mock.calls.length;
    const getCallsAfterFirst = farmosClient.get.mock.calls.length;
    const dispatchAfterFirst = outboundConfirm.dispatch.mock.calls.length;
    const auditAfterFirst = auditLogger._events.length;

    // Second tick: row is status='committed'; findConfirmedCandidates filters
    // it out. Zero new POSTs, zero new dispatches.
    await watchdog.tickOnce();

    expect(farmosClient.post.mock.calls.length).toBe(postCallsAfterFirst);
    expect(farmosClient.get.mock.calls.length).toBe(getCallsAfterFirst);
    expect(outboundConfirm.dispatch.mock.calls.length).toBe(dispatchAfterFirst);
    expect(auditLogger._events.length).toBe(auditAfterFirst);
  });

  it('defense in depth: if a committed row is re-presented to _processRow via the cache probe, no new writes / no double-ack', async () => {
    // Seed a row already in status='committed' with a cached farmos_response.
    // Force findConfirmedCandidates to surface it anyway by mutating status
    // back to 'confirmed' AFTER the cache probe would have run. But the cache
    // probe runs BEFORE the lock + commit, so we just need:
    //   row.status='confirmed' (so findConfirmedCandidates returns it)
    //   getCachedResponse returns {ok:true, status:'committed', farmos_response}
    //
    // The easiest way: pre-populate the in-memory drafts map with both
    // status='confirmed' AND farmos_response set. Then override
    // getCachedResponse to return status='committed' as if a previous
    // attempt had succeeded but the row was somehow requeued.
    const { watchdog, commitDb, farmosClient, auditLogger, outboundConfirm, row } = buildHarness();

    // Pretend a previous commit already wrote results.
    const cachedResponse = {
      asset_ids: ['cached-session', 'cached-source-1', 'cached-child-1'],
      log_ids: ['cached-log-1'],
      file_ids: [],
      http_status: 201,
    };
    const draftRow = commitDb._drafts.get(row.id);
    draftRow.farmos_response = cachedResponse;
    draftRow.status = 'confirmed'; // force re-presentation
    // Override getCachedResponse to mimic a 'committed' cache hit.
    const origGet = commitDb.getCachedResponse;
    commitDb.getCachedResponse = async (pool, id) => {
      if (id !== row.id) return origGet.call(commitDb, pool, id);
      return { ok: true, status: 'committed', farmos_response: cachedResponse };
    };

    await watchdog.tickOnce();

    // Zero writes (cache probe short-circuited).
    expect(farmosClient.post).not.toHaveBeenCalled();
    expect(farmosClient.get).not.toHaveBeenCalled();
    expect(farmosClient._deletes.length).toBe(0);

    // commit_idempotent_noop logged; commit_success NOT logged.
    const events = auditLogger._events.map((e) => e.event);
    expect(events).toContain('commit_idempotent_noop');
    expect(events).not.toContain('commit_success');
    expect(events).not.toContain('commit_attempt');

    // No double-ack: probe returns before _maybeDispatchOutcomeAck.
    expect(outboundConfirm.dispatch).not.toHaveBeenCalled();
  });
});
