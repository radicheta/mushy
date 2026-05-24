'use strict';

// Phase 48 Plan 05 Task 1: HERMETIC SHIP-GATE for the May 22 seeding_session
// happy path (INOC-04 single-parent legacy + INOC-06 session+per-bag fan-out).
//
// Drives the FULL producer-to-consumer chain:
//   commit-watchdog.tickOnce
//     -> commit-router.commit
//     -> commit-seeding-session.commitSeedingSession (REAL)
//     -> assets.createFungiAsset / logs.createLog (REAL) -> mock farmosClient
//     -> commitDb.markCommitted
//     -> outboundConfirm.dispatch('send_commit_outcome_ack', row, {outcome:'success'})
//     -> auditLogger.logCommit('commit_success', ...)
//
// Live-fire (operator-gated) is documented in 48-LIVE-FIRE.md. This file's
// hermetic tests run under `npm test` by default with no env gates.
//
// Cross-references:
//   .planning/phases/48-*/48-05-PLAN.md  (must-have truths)
//   test/fixtures/seeding-session-may22-commit/expected-farmos-payloads.json

const path = require('path');
const fs = require('fs');

const { buildHarness } = require('./_session-commit-harness');

const EXPECTED = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, '..', '..', 'fixtures', 'seeding-session-may22-commit', 'expected-farmos-payloads.json'),
    'utf8',
  ),
);

describe('seeding-session commit pipeline -- May 22 happy path (Phase 48 Plan 05 Task 1)', () => {
  it('5 groups / 11 children: 16 asset POSTs + 11 log POSTs; child parent[] = [source]; commitDb -> committed; outcome ack dispatched once', async () => {
    const { watchdog, commitDb, farmosClient, auditLogger, outboundConfirm, row } = buildHarness();

    await watchdog.tickOnce();

    // ----- asset / log counts -----
    // Phase 52: session entity restored as asset--group + membership
    // log--activity with is_group_assignment=true. 16 fungi + 1 group = 17
    // asset writes; 11 seeding + 1 activity = 12 log writes.
    expect(farmosClient._created.assets.length).toBe(EXPECTED.happy_path.asset_post_count); // 16 fungi
    expect(farmosClient._created.groups.length).toBe(EXPECTED.happy_path.group_post_count); // 1
    expect(farmosClient._created.logs.length).toBe(EXPECTED.happy_path.log_post_count);     // 12 (11 seeding + 1 activity)
    expect(farmosClient._created.activityLogs.length).toBe(EXPECTED.happy_path.log_breakdown.activity_with_flag); // 1
    expect(farmosClient._deletes.length).toBe(0);

    // ----- lineage: every child block's parent[] has length 1 (the source block) -----
    const childAssets = farmosClient._created.assets.filter((a) => /^260522_/.test(a.name));
    expect(childAssets.length).toBe(11);
    const sourceBlockNames = new Set(EXPECTED.happy_path.source_block_names);
    const sourceAssets = farmosClient._created.assets.filter((a) => sourceBlockNames.has(a.name));
    const sourceIds = new Set(sourceAssets.map((a) => a.id));
    expect(sourceIds.size).toBe(5);
    for (const c of childAssets) {
      const parents = c.payload.data.relationships.parent.data;
      expect(parents.length).toBe(1);
      expect(sourceIds.has(parents[0].id)).toBe(true);
    }

    // ----- pipeline state: signal_draft row marked committed -----
    // asset_ids = [sessionGroupId, ...16 fungi] = 17; log_ids = [membership, ...11 seeding] = 12
    const finalRow = commitDb._drafts.get(row.id);
    expect(finalRow.status).toBe('committed');
    expect(finalRow.farmos_response.asset_ids.length).toBe(17);
    expect(finalRow.farmos_response.log_ids.length).toBe(12);

    // ----- audit -----
    const events = auditLogger._events.map((e) => e.event);
    expect(events).toContain('commit_attempt');
    expect(events).toContain('commit_success');
    expect(events).not.toContain('commit_failed');
    expect(events).not.toContain('orphan_cleanup_failed');

    // ----- outcome ack dispatched EXACTLY ONCE with success outcome -----
    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);
    const [verb, ackRow, extras] = outboundConfirm.dispatch.mock.calls[0];
    expect(verb).toBe('send_commit_outcome_ack');
    expect(ackRow.id).toBe(row.id);
    expect(ackRow.log_type).toBe('seeding_session');
    expect(extras).toEqual({ outcome: 'success' });
  });

  it('single-parent legacy (INOC-04): 1 group of 5 children still creates session asset + 5 child logs', async () => {
    const singleParentDraft = {
      type: 'seeding_session',
      event_date: '2026-05-22',
      groups: [
        {
          parent: { value: '260118_KOY_12', confidence: 0.9, sources: ['audio'] },
          species: { value: 'KOY', confidence: 0.99, sources: ['audio'] },
          qty: { value: 5, confidence: 0.99, sources: ['audio'] },
          child_block_names: {
            value: ['260522_KOY_1', '260522_KOY_2', '260522_KOY_3', '260522_KOY_4', '260522_KOY_5'],
            confidence: 0.95,
            sources: ['audio'],
          },
        },
      ],
      notes: 'INOC-04 legacy single-parent fixture',
    };
    const { watchdog, commitDb, farmosClient, outboundConfirm } = buildHarness({
      draft: singleParentDraft,
      rowOverrides: { id: 'd-single-parent-inoc-04' },
    });

    await watchdog.tickOnce();

    expect(farmosClient._created.assets.length).toBe(EXPECTED.single_parent_legacy.asset_post_count); // 6 fungi
    expect(farmosClient._created.groups.length).toBe(EXPECTED.single_parent_legacy.group_post_count); // 1 session group
    expect(farmosClient._created.logs.length).toBe(EXPECTED.single_parent_legacy.log_post_count);     // 6 (5 seeding + 1 activity)

    // 1 source + 5 children
    const sourceAsset = farmosClient._created.assets[0];
    expect(sourceAsset.name).toBe('260118_KOY_12');

    const childAssets = farmosClient._created.assets.filter((a) => /^260522_KOY_[1-5]$/.test(a.name));
    expect(childAssets.length).toBe(5);
    for (const c of childAssets) {
      const parents = c.payload.data.relationships.parent.data;
      expect(parents.map((p) => p.id)).toEqual([sourceAsset.id]);
    }

    const finalRow = commitDb._drafts.get('d-single-parent-inoc-04');
    expect(finalRow.status).toBe('committed');

    expect(outboundConfirm.dispatch).toHaveBeenCalledTimes(1);
    expect(outboundConfirm.dispatch.mock.calls[0][2]).toEqual({ outcome: 'success' });
  });

  it('LIVE-FIRE branch (skipped unless EVAL_RUN_LIVE=1): documents the operator-gated path', () => {
    if (process.env.EVAL_RUN_LIVE !== '1') {
      // Hermetic CI path. Operators run this branch manually per 48-LIVE-FIRE.md.
      return;
    }
    // Operator-deferred. The actual live-fire harness lives in 48-LIVE-FIRE.md
    // as a curl + manual jest invocation runbook; no automated branch is wired
    // here yet (mirrors 47-05 which also operator-defers).
    throw new Error('EVAL_RUN_LIVE=1 set but live-fire harness is operator-deferred; see 48-LIVE-FIRE.md');
  });
});
