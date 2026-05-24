'use strict';

// Phase 48 Plan 05 Task 1: HERMETIC SHIP-GATE for the orphan-cleanup branch.
//
// Drives the FULL producer-to-consumer chain with a stubbed 422 on the 4th
// seeding-log POST. Expected behavior (per 48-02 SUMMARY Test E):
//   - 1 session + 4 source blocks + 4 child blocks are created BEFORE failure
//     = 9 assets total
//   - on log #4 422, the handler reverse-DELETEs all 9 in reverse-creation
//     order (last child first, session asset last)
//   - signal_draft row -> status='commit_failed' with reason='partial_commit_failed'
//   - outboundConfirm.dispatch called exactly once with
//     ('send_commit_outcome_ack', row, { outcome: 'failed', reason: 'partial_commit_failed' })
//   - auditLogger logs commit_failed but NOT orphan_cleanup_failed (DELETEs ok)
//
// The 422 on log #4 is the canonical Plan 02 Test E scenario; this integration
// test re-exercises it through the watchdog -> router chain (the bit unit
// tests cannot reach).

const { buildHarness } = require('./_session-commit-harness');

describe('seeding-session commit pipeline -- partial-fail orphan cleanup (Phase 48 Plan 05 Task 1)', () => {
  it('log #4 returns 422: reverse-order DELETE for 9 orphans; row -> commit_failed; failed-ack dispatched once', async () => {
    const { watchdog, commitDb, farmosClient, auditLogger, outboundConfirm, row } = buildHarness({
      failLogIndex: 4,
    });

    await watchdog.tickOnce();

    // ----- 9 DELETEs in reverse order (Phase 52: 8 fungi + 1 session group) -----
    expect(farmosClient._deletes.length).toBe(9);
    const sessionGroupId = farmosClient._created.groups[0].id;
    // Session group DELETE is LAST (created first, deleted last).
    expect(farmosClient._deletes[farmosClient._deletes.length - 1]).toBe('/api/asset/group/' + sessionGroupId);
    // 2nd-to-last fungi DELETE is the first source block (created first among fungi).
    const firstCreatedId = farmosClient._created.assets[0].id;
    expect(farmosClient._deletes[farmosClient._deletes.length - 2]).toBe('/api/asset/fungi/' + firstCreatedId);

    // First DELETE must be the most-recently-created fungi asset (the 4th child block).
    const child4Asset = farmosClient._created.assets[farmosClient._created.assets.length - 1];
    expect(child4Asset.name).toMatch(/^260522_KOY_/);
    expect(farmosClient._deletes[0]).toBe('/api/asset/fungi/' + child4Asset.id);

    // ----- pipeline state: signal_draft row -> commit_failed -----
    const finalRow = commitDb._drafts.get(row.id);
    expect(finalRow.status).toBe('commit_failed');
    expect(finalRow.commit_failed_reason).toBe('partial_commit_failed');

    // ----- audit: commit_failed present, orphan_cleanup_failed absent -----
    const events = auditLogger._events.map((e) => e.event);
    expect(events).toContain('commit_attempt');
    expect(events).toContain('commit_failed');
    expect(events).not.toContain('commit_success');
    expect(events).not.toContain('orphan_cleanup_failed');

    // ----- outcome ack: exactly once, outcome='failed', reason='partial_commit_failed' -----
    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);
    const [verb, ackRow, extras] = outboundConfirm.dispatch.mock.calls[0];
    expect(verb).toBe('send_commit_outcome_ack');
    expect(ackRow.id).toBe(row.id);
    expect(ackRow.log_type).toBe('seeding_session');
    expect(extras.outcome).toBe('failed');
    expect(extras.reason).toBe('partial_commit_failed');
  });

  it('log #4 fails AND DELETEs themselves fail (500): orphan_cleanup_failed audit lines emitted; ack still dispatched', async () => {
    const { watchdog, farmosClient, auditLogger, outboundConfirm } = buildHarness({
      failLogIndex: 4,
      deleteResponse: () => ({ ok: false, status: 500, body: null }),
    });

    await watchdog.tickOnce();

    expect(farmosClient._deletes.length).toBe(9);

    // 9 orphan_cleanup_failed audit lines, one per failed DELETE (8 fungi + 1 group).
    const orphanFailures = auditLogger._events.filter((e) => e.event === 'orphan_cleanup_failed');
    expect(orphanFailures.length).toBe(9);
    for (const f of orphanFailures) {
      expect(f.result.asset_ids.length).toBe(1);
    }

    // Failed-ack still dispatched (no silent failure invariant per Phase 45).
    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);
    const [, , extras] = outboundConfirm.dispatch.mock.calls[0];
    expect(extras.outcome).toBe('failed');
    expect(extras.reason).toBe('partial_commit_failed');
  });
});
