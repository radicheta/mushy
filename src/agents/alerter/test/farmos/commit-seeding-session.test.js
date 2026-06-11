'use strict';

// Phase 52 Plan 04: commitSeedingSession handler tests at the new
// asset--group + log--activity shape.
//
// Hermetic -- uses shared makeMockClient (extended in Plan 04 to route
// /api/asset/group + /api/log/activity).
//
// Fixture: 2026-05-22 inoc session (5 groups, 11 children).
// Expected happy-path counts:
//   - 1 asset--group (session)
//   - 5 asset--fungi source blocks
//   - 11 asset--fungi child blocks
//   = 17 asset POSTs total
//   - 1 log--activity (membership, is_group_assignment=true)
//   - 11 log--seeding (one per child)
//   = 12 logs total

const path = require('path');
const fs = require('fs');

const commitSeedingSession = require('../../src/farmos/commits/commit-seeding-session');
const commitRouter = require('../../src/farmos/commits/commit-router');
const assets = require('../../src/farmos/assets');
const groupAssets = require('../../src/farmos/groupAssets');
const fungiTypeCache = require('../../src/farmos/fungi-type-cache');
const fungiXingCache = require('../../src/farmos/fungi-xing-cache');
const { makeMockClient } = require('./mock-client');

const MAY22_FIXTURE = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, '..', 'fixtures', 'seeding-session-may22', 'expected-draft.json'),
    'utf8',
  ),
);

function makeSessionMockClient(opts = {}) {
  const {
    knownAssetsByName = {},
    knownGroupsByName = {},
    failLogIndex = -1,         // 1-based seeding-log POST to fail; -1 = never
    failLogStatus = 422,
    failActivityLog = false,   // fail the /api/log/activity POST
    deleteResponse = null,
  } = opts;

  const client = makeMockClient({ knownAssetsByName, knownGroupsByName });
  client._deletes = [];

  // Replace post to support failLogIndex (seeding logs) and failActivityLog.
  const origPost = client.post;
  let seedingLogPostCount = 0;
  client.post = jest.fn(async (p, body, o) => {
    if (p === '/api/log/activity' && failActivityLog) {
      return { ok: false, status: failLogStatus, body: { errors: [{ detail: 'validation' }] } };
    }
    if (p === '/api/log/seeding') {
      seedingLogPostCount += 1;
      if (failLogIndex > 0 && seedingLogPostCount === failLogIndex) {
        return { ok: false, status: failLogStatus, body: { errors: [{ detail: 'validation' }] } };
      }
    }
    return origPost(p, body, o);
  });

  client.delete = jest.fn(async (p, o) => {
    client._deletes.push(p);
    if (typeof deleteResponse === 'function') return deleteResponse(p);
    return { ok: true, status: 204, body: null };
  });

  return client;
}

function makeAuditCtx() {
  const calls = [];
  return {
    ctx: {
      auditLogger: {
        logCommit: jest.fn(async (event, draft, result) => {
          calls.push({ event, draft_id: draft && draft.id, result });
        }),
      },
    },
    calls,
  };
}

function draftFor(json, id = 'd-session-1') {
  return {
    id,
    log_type: 'seeding_session',
    draft_json: json,
  };
}

beforeEach(() => {
  assets._clearCache();
  groupAssets._clearCache();
  fungiTypeCache._clear();
  fungiXingCache._clear();
});

describe('commitSeedingSession (Phase 52 Plan 03/04)', () => {

  it('Test A (happy path May 22): 17 asset POSTs (1 group + 5 source + 11 children), 12 logs (1 activity-with-flag + 11 seeding), child parent[] = [source] ONLY', async () => {
    const client = makeSessionMockClient();
    const { ctx } = makeAuditCtx();
    const r = await commitSeedingSession(client, draftFor(MAY22_FIXTURE), ctx);

    expect(r.ok).toBe(true);

    // 1 session group + 5 source + 11 children = 17 asset writes
    expect(client._created.groups.length).toBe(1);
    expect(client._created.assets.length).toBe(16); // 5 source + 11 children
    // 1 activity + 11 seeding = 12 logs
    expect(client._created.activityLogs.length).toBe(1);
    expect(client._created.logs.filter((l) => l.type === 'seeding').length).toBe(11);

    // Return shape: session group id at asset_ids[0]; membership log at log_ids[0]
    const sessionGroupId = client._created.groups[0].id;
    expect(r.asset_ids[0]).toBe(sessionGroupId);
    expect(r.asset_ids.length).toBe(17);
    expect(r.log_ids.length).toBe(12);
    const membershipLogId = client._created.activityLogs[0].id;
    expect(r.log_ids[0]).toBe(membershipLogId);

    // Activity POST body shape
    const activityBody = client._created.activityLogs[0].payload;
    expect(activityBody.data.type).toBe('log--activity');
    expect(activityBody.data.attributes.is_group_assignment).toBe(true);
    expect(activityBody.data.relationships.asset.data.length).toBe(11);
    for (const ref of activityBody.data.relationships.asset.data) {
      expect(ref.type).toBe('asset--fungi');
    }
    expect(activityBody.data.relationships.group.data).toEqual([
      { type: 'asset--group', id: sessionGroupId },
    ]);

    // Every CHILD block asset has parent[] = [sourceBlockId] only (length 1, NO sessionGroupId).
    const childAssets = client._created.assets.filter((a) => /^260522_/.test(a.name));
    expect(childAssets.length).toBe(11);
    for (const c of childAssets) {
      const parents = c.payload.data.relationships.parent.data;
      expect(parents.length).toBe(1);
      for (const p of parents) {
        expect(p.type).toBe('asset--fungi');
        expect(p.id).not.toBe(sessionGroupId);
      }
    }

    // Each seeding log refers to its child block (one assetId per log).
    const seedingLogs = client._created.logs.filter((l) => l.type === 'seeding');
    for (const log of seedingLogs) {
      expect(log.payload.data.relationships.asset.data.length).toBe(1);
    }

    // log_ids[1..] are the 11 seeding log ids in order.
    const seedingLogIds = client._created.logs.filter((l) => l.type === 'seeding').map((l) => l.id);
    expect(r.log_ids.slice(1)).toEqual(seedingLogIds);
  });

  it('Test C (single-parent legacy, INOC-04): 1 session group + 1 source + 5 children + 1 activity log + 5 seeding logs', async () => {
    const dj = {
      type: 'seeding_session',
      event_date: '2026-05-22',
      groups: [
        {
          parent: { value: '260118_KOY_12', confidence: 0.9, sources: ['audio'] },
          species: { value: 'KOY', confidence: 0.99, sources: ['audio'] },
          qty: { value: 5, confidence: 0.99, sources: ['audio'] },
          child_block_names: { value: ['260522_KOY_1','260522_KOY_2','260522_KOY_3','260522_KOY_4','260522_KOY_5'], confidence: 0.95, sources: ['audio'] },
        },
      ],
    };
    const client = makeSessionMockClient();
    const r = await commitSeedingSession(client, draftFor(dj, 'd-single-parent'), {});
    expect(r.ok).toBe(true);
    expect(client._created.groups.length).toBe(1);
    expect(client._created.assets.length).toBe(6); // 1 source + 5 children
    expect(client._created.activityLogs.length).toBe(1);
    expect(client._created.logs.filter((l) => l.type === 'seeding').length).toBe(5);
    const sourceId = client._created.assets[0].id;
    const childAssets = client._created.assets.filter((a) => /^260522_/.test(a.name));
    for (const c of childAssets) {
      const parents = c.payload.data.relationships.parent.data;
      expect(parents.map((p) => p.id)).toEqual([sourceId]);
    }
  });

  it('Test D (NO_PARENT): child blocks created with parentIds = []; session group + activity log still mint', async () => {
    const dj = {
      type: 'seeding_session',
      event_date: '2026-05-22',
      groups: [
        {
          parent: { value: 'NO_PARENT', confidence: 0.99, sources: ['audio'] },
          species: { value: 'SHI', confidence: 0.99, sources: ['audio'] },
          qty: { value: 2, confidence: 0.99, sources: ['audio'] },
          child_block_names: { value: ['260522_SHI_X1','260522_SHI_X2'], confidence: 0.99, sources: ['audio'] },
        },
      ],
    };
    const client = makeSessionMockClient();
    const r = await commitSeedingSession(client, draftFor(dj, 'd-no-parent'), {});
    expect(r.ok).toBe(true);
    expect(client._created.groups.length).toBe(1);
    expect(client._created.assets.length).toBe(2);
    expect(client._created.activityLogs.length).toBe(1);
    const childAssets = client._created.assets.filter((a) => /^260522_SHI_X/.test(a.name));
    for (const c of childAssets) {
      expect(c.payload.data.relationships.parent).toBeUndefined();
    }
  });

  it('Test E (partial failure on seeding log #4): reverse-order DELETE for fungi + session group; activity log NOT yet created', async () => {
    // At seeding log #4 failure (1-based), we have created:
    //   1 session group + 4 source blocks + 4 child blocks = 9 entities to roll back.
    // Membership activity log has NOT been posted yet (it comes after the loop).
    const client = makeSessionMockClient({ failLogIndex: 4 });
    const { ctx, calls: auditCalls } = makeAuditCtx();
    const r = await commitSeedingSession(client, draftFor(MAY22_FIXTURE), ctx);

    expect(r.ok).toBe(false);
    expect(r.reason).toBe('partial_commit_failed');
    expect(r.farmos_response.failed_at_child_index).toBe(3);
    expect(r.asset_ids).toEqual([]);
    expect(r.log_ids).toEqual([]);

    // Mock-tracked counts: 1 group POST + 8 asset POSTs + 0 activity-log POSTs.
    expect(client._created.groups.length).toBe(1);
    expect(client._created.activityLogs.length).toBe(0);

    // DELETEs: 8 fungi assets (reverse order) + 1 session group = 9 total.
    expect(client._deletes.length).toBe(9);
    expect(r.farmos_response.orphan_attempted_count).toBe(9);
    expect(r.farmos_response.orphan_cleanup_failed_count).toBe(0);

    // Session group DELETE is LAST in the sequence.
    const sessionGroupId = client._created.groups[0].id;
    expect(client._deletes[client._deletes.length - 1]).toBe('/api/asset/group/' + sessionGroupId);

    // First fungi DELETE is the LAST-created fungi (reverse order).
    const lastCreatedFungiId = client._created.assets[client._created.assets.length - 1].id;
    expect(client._deletes[0]).toBe('/api/asset/fungi/' + lastCreatedFungiId);

    expect(auditCalls.find((c) => c.event === 'orphan_cleanup_failed')).toBeUndefined();
  });

  it('Test F (orphan cleanup itself fails): auditLogger.logCommit called with orphan_cleanup_failed for EACH failed DELETE', async () => {
    const client = makeSessionMockClient({
      failLogIndex: 4,
      deleteResponse: () => ({ ok: false, status: 500, body: null }),
    });
    const { ctx, calls: auditCalls } = makeAuditCtx();
    const r = await commitSeedingSession(client, draftFor(MAY22_FIXTURE), ctx);

    expect(r.ok).toBe(false);
    expect(r.reason).toBe('partial_commit_failed');
    // 8 fungi + 1 session group = 9 DELETE attempts.
    expect(client._deletes.length).toBe(9);
    expect(r.farmos_response.orphan_cleanup_failed_count).toBe(9);
    expect(r.farmos_response.orphan_cleanup_failed_ids.length).toBe(9);

    const orphanCalls = auditCalls.filter((c) => c.event === 'orphan_cleanup_failed');
    expect(orphanCalls.length).toBe(9);
    for (const c of orphanCalls) {
      expect(c.result.asset_ids.length).toBe(1);
      expect(c.draft_id).toBe('d-session-1');
    }
  });

  it('Test E2 (membership log POST fails): all children + seeding logs succeed; rollback covers session group + ALL 11 children', async () => {
    const client = makeSessionMockClient({ failActivityLog: true });
    const { ctx } = makeAuditCtx();
    const r = await commitSeedingSession(client, draftFor(MAY22_FIXTURE), ctx);

    expect(r.ok).toBe(false);
    expect(r.reason).toBe('partial_commit_failed');
    expect(r.farmos_response.original_reason).toBe('membership_log_create_failed');
    expect(r.asset_ids).toEqual([]);
    expect(r.log_ids).toEqual([]);

    // All children + source blocks + session group exist by the time activity-log fails.
    expect(client._created.groups.length).toBe(1);
    expect(client._created.assets.length).toBe(16); // 5 source + 11 children
    expect(client._created.logs.filter((l) => l.type === 'seeding').length).toBe(11);   // seeding logs all succeeded
    expect(client._created.activityLogs.length).toBe(0); // activity post failed -> not registered

    const sessionGroupId = client._created.groups[0].id;
    const childAssetIds = client._created.assets
      .filter((a) => /^260522_/.test(a.name))
      .map((a) => a.id);

    // Rollback: 16 fungi DELETEs + 1 session group DELETE = 17 total. No activity-log DELETE
    // because the activity-log POST never returned a logId.
    expect(client._deletes.length).toBe(17);

    // Session group id appears in DELETE list AND is LAST.
    expect(client._deletes).toContain('/api/asset/group/' + sessionGroupId);
    expect(client._deletes[client._deletes.length - 1]).toBe('/api/asset/group/' + sessionGroupId);

    // All 11 child fungi ids appear in DELETE list.
    for (const cid of childAssetIds) {
      expect(client._deletes).toContain('/api/asset/fungi/' + cid);
    }

    // Reverse-order invariant: session group DELETE comes after all fungi DELETEs.
    const groupDeleteIdx = client._deletes.indexOf('/api/asset/group/' + sessionGroupId);
    const firstChildDeleteIdx = client._deletes.indexOf('/api/asset/fungi/' + childAssetIds[0]);
    expect(groupDeleteIdx).toBeGreaterThan(firstChildDeleteIdx);
  });

  it('Test F2 (same-day collision): existing group with foreign draft id -> handler advances to "#2"', async () => {
    // Pre-seed an asset--group named 'inoc 2026-05-22' whose notes trailer
    // belongs to a DIFFERENT draft. Handler must skip and create '#2'.
    const client = makeSessionMockClient({
      knownGroupsByName: {
        'inoc 2026-05-22': {
          id: 'group-foreign',
          attributes: {
            name: 'inoc 2026-05-22',
            notes: { value: 'mushy:draft:OTHER_DRAFT', format: 'plain_text' },
          },
        },
      },
    });
    const r = await commitSeedingSession(client, draftFor(MAY22_FIXTURE, 'd-collision'), {});
    expect(r.ok).toBe(true);

    // Exactly one NEW group POST (the foreign one was pre-seeded, not POSTed).
    expect(client._created.groups.length).toBe(1);
    expect(client._created.groups[0].name).toBe('inoc 2026-05-22 #2');
    expect(client._created.groups[0].payload.data.attributes.name).toBe('inoc 2026-05-22 #2');

    // asset_ids[0] is the NEW session group id (not the foreign one).
    expect(r.asset_ids[0]).toBe(client._created.groups[0].id);
    expect(r.asset_ids[0]).not.toBe('group-foreign');
  });

  it('Test H (Phase 51 idempotency under new shape): replaying same draft reuses session group + assets + seeding logs; activity log POSTED again (creation-only)', async () => {
    const client = makeSessionMockClient();
    const r1 = await commitSeedingSession(client, draftFor(MAY22_FIXTURE), {});
    expect(r1.ok).toBe(true);
    const groupsAfterFirst = client._created.groups.length;     // 1
    const assetsAfterFirst = client._created.assets.length;     // 16
    const seedingLogsAfterFirst = client._created.logs.filter((l) => l.type === 'seeding').length;  // 11
    const activityLogsAfterFirst = client._created.activityLogs.length; // 1

    const r2 = await commitSeedingSession(client, draftFor(MAY22_FIXTURE), {});
    expect(r2.ok).toBe(true);

    // No new group POST -- reused via draft-id trailer match.
    expect(client._created.groups.length).toBe(groupsAfterFirst);
    // No new fungi POSTs -- upsertFungiAsset returns reused/noop.
    expect(client._created.assets.length).toBe(assetsAfterFirst);
    // No new seeding log POSTs -- upsertLog returns patched/noop.
    expect(client._created.logs.filter((l) => l.type === 'seeding').length).toBe(seedingLogsAfterFirst);
    // BUT: activity log is creation-only per 52-CONTEXT.md -- one new POST.
    expect(client._created.activityLogs.length).toBe(activityLogsAfterFirst + 1);

    // r2.asset_ids does NOT include the session group (outcome=reused).
    // createdAssetIds is also empty on replay.
    expect(r2.asset_ids).toEqual([]);
    // log_ids[0] is the new (second) membership log; rest are the 11 reused seeding log ids.
    expect(r2.log_ids.length).toBe(12);
  });

  it('Test G (router dispatch): commit(client, draft) with draft.log_type=seeding_session routes to commitSeedingSession', async () => {
    expect(typeof commitRouter.DISPATCH.seeding_session).toBe('function');
    expect(commitRouter.DISPATCH.seeding_session).toBe(commitSeedingSession);
  });
});

// ============================================================================
// Phase 55B Plan 01 Task 1: patchGroupAssetFiles payload-shape tests
// ============================================================================

const { patchGroupAssetFiles } = require('../../src/farmos/groupAssets');

describe('patch_files (patchGroupAssetFiles JSON:API PATCH shape)', () => {
  function makePatchClient(opts = {}) {
    const { patchStatus = 200, patchOk = true } = opts;
    return {
      patch: jest.fn().mockResolvedValue({ ok: patchOk, status: patchStatus }),
    };
  }

  it('calls client.patch with correct path and relationships.file.data entries', async () => {
    const client = makePatchClient();
    const result = await patchGroupAssetFiles(client, 'group-uuid-1', ['file-uuid-a']);

    expect(client.patch).toHaveBeenCalledTimes(1);
    const [path, body] = client.patch.mock.calls[0];
    expect(path).toBe('/api/asset/group/group-uuid-1');
    expect(body.data.type).toBe('asset--group');
    expect(body.data.id).toBe('group-uuid-1');
    expect(body.data.relationships.file.data).toEqual([
      { type: 'file--file', id: 'file-uuid-a' },
    ]);
    expect(result.ok).toBe(true);
    expect(result.http_status).toBe(200);
  });

  it('maps multiple fileIds to relationships.file.data array', async () => {
    const client = makePatchClient();
    await patchGroupAssetFiles(client, 'group-uuid-2', ['file-1', 'file-2', 'file-3']);

    const [, body] = client.patch.mock.calls[0];
    expect(body.data.relationships.file.data).toEqual([
      { type: 'file--file', id: 'file-1' },
      { type: 'file--file', id: 'file-2' },
      { type: 'file--file', id: 'file-3' },
    ]);
  });

  it('returns { ok: true, skipped: true } and does NOT call client.patch when fileIds is empty', async () => {
    const client = makePatchClient();
    const result = await patchGroupAssetFiles(client, 'group-uuid-3', []);

    expect(client.patch).not.toHaveBeenCalled();
    expect(result).toEqual({ ok: true, skipped: true });
  });

  it('returns { ok: true, skipped: true } and does NOT call client.patch when fileIds is null', async () => {
    const client = makePatchClient();
    const result = await patchGroupAssetFiles(client, 'group-uuid-4', null);

    expect(client.patch).not.toHaveBeenCalled();
    expect(result).toEqual({ ok: true, skipped: true });
  });

  it('returns canonical error shape on non-ok HTTP response', async () => {
    const client = makePatchClient({ patchOk: false, patchStatus: 422 });
    const result = await patchGroupAssetFiles(client, 'group-uuid-5', ['file-uuid-b']);

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('http_422');
    expect(result.http_status).toBe(422);
  });
});
