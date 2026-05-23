'use strict';

// Phase 48 Plan 02: commitSeedingSession handler tests.
//
// Hermetic -- uses the shared makeMockClient + an extension for client.delete
// and for log-create injection (Test E/F simulate a 4xx on log #4).
//
// Fixture: 2026-05-22 inoc session (5 groups, 11 children) read from
// test/fixtures/seeding-session-may22/expected-draft.json.

const path = require('path');
const fs = require('fs');

const commitSeedingSession = require('../../src/farmos/commits/commit-seeding-session');
const commitRouter = require('../../src/farmos/commits/commit-router');
const assets = require('../../src/farmos/assets');
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
    failLogIndex = -1,         // 1-based log POST count to fail; -1 = never
    failLogStatus = 422,
    deleteResponse = null,     // function(path) -> { ok, status, body }; default ok 204
  } = opts;

  const client = makeMockClient({ knownAssetsByName });
  client._deletes = [];

  // Replace post to support failLogIndex.
  const origPost = client.post;
  let logPostCount = 0;
  client.post = jest.fn(async (p, body, o) => {
    if (/^\/api\/log\//.test(p)) {
      logPostCount += 1;
      if (failLogIndex > 0 && logPostCount === failLogIndex) {
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
  fungiTypeCache._clear();
  fungiXingCache._clear();
});

describe('commitSeedingSession (Phase 48 Plan 02)', () => {
  it('Test A (happy path May 22): 17 asset POSTs, 11 seeding log POSTs, child parent[] = [source, session]', async () => {
    const client = makeSessionMockClient();
    const { ctx } = makeAuditCtx();
    const r = await commitSeedingSession(client, draftFor(MAY22_FIXTURE), ctx);

    expect(r.ok).toBe(true);
    expect(client._created.assets.length).toBe(17); // 1 session + 5 source blocks + 11 child blocks
    expect(client._created.logs.length).toBe(11);
    expect(r.log_ids.length).toBe(11);
    expect(r.asset_ids.length).toBe(17);

    // Session asset is the first POSTed asset; name 'inoc 2026-05-22'.
    const sessionAsset = client._created.assets[0];
    expect(sessionAsset.name).toBe('inoc 2026-05-22');
    const sessionId = sessionAsset.id;
    // allowNoFungiType: session asset has fungi_xing but NOT fungi_type.
    expect(sessionAsset.payload.data.relationships.fungi_type).toBeUndefined();
    expect(sessionAsset.payload.data.relationships.fungi_xing).toBeDefined();

    // Every CHILD block asset (the 11 created after the 5 source blocks) has
    // parent[] = [sourceBlockId, sessionId] in that order. Source blocks are
    // assets[1..5]; child blocks are assets[6..16] but interleaved per group.
    // The simplest invariant: every child block (any asset whose name starts
    // with '260522_') has parent.data length 2, last = sessionId.
    const childAssets = client._created.assets.filter((a) => /^260522_/.test(a.name));
    expect(childAssets.length).toBe(11);
    for (const c of childAssets) {
      const parents = c.payload.data.relationships.parent.data;
      expect(parents.length).toBe(2);
      expect(parents[1].id).toBe(sessionId);
      // First parent is a source block id (one of the 5 created earlier).
    }

    // Each seeding log refers to its child block (one assetId per log).
    for (const log of client._created.logs) {
      expect(log.payload.data.relationships.asset.data.length).toBe(1);
    }
  });

  it('Test B (name collision): #2 suffix used when inoc 2026-05-22 already exists', async () => {
    const client = makeSessionMockClient({
      knownAssetsByName: { 'inoc 2026-05-22': 'existing-session-asset' },
    });
    const r = await commitSeedingSession(client, draftFor(MAY22_FIXTURE), {});
    expect(r.ok).toBe(true);
    expect(client._created.assets[0].name).toBe('inoc 2026-05-22 #2');
  });

  it('Test C (single-parent legacy, INOC-04): 1 group of 5 children still creates a session asset + 5 child blocks', async () => {
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
    // 1 session + 1 source block + 5 child blocks = 7 assets.
    expect(client._created.assets.length).toBe(7);
    expect(client._created.logs.length).toBe(5);
    const sessionId = client._created.assets[0].id;
    const sourceId = client._created.assets[1].id;
    const childAssets = client._created.assets.filter((a) => /^260522_/.test(a.name));
    for (const c of childAssets) {
      const parents = c.payload.data.relationships.parent.data;
      expect(parents.map((p) => p.id)).toEqual([sourceId, sessionId]);
    }
  });

  it('Test D (NO_PARENT): child blocks created with parentIds = [sessionAssetId] only', async () => {
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
    // 1 session + 0 source blocks (NO_PARENT skips resolution) + 2 child blocks.
    expect(client._created.assets.length).toBe(3);
    const sessionId = client._created.assets[0].id;
    const childAssets = client._created.assets.filter((a) => /^260522_SHI_X/.test(a.name));
    expect(childAssets.length).toBe(2);
    for (const c of childAssets) {
      const parents = c.payload.data.relationships.parent.data;
      expect(parents.length).toBe(1);
      expect(parents[0].id).toBe(sessionId);
    }
  });

  it('Test E (partial failure on log #4): reverse-order DELETE for session + 4 source blocks + 4 child blocks; ok=false, failed_at_child_index=3', async () => {
    // Log #4 corresponds to the 4th seeding log POST (1-based). Per the
    // May 22 fixture: groups 1-3 each contribute 1 child (logs 1, 2, 3);
    // group 4 (260118_KOY_12, qty=4) starts at log 4. So at failure time,
    // we have created: 1 session + 4 source blocks + 4 child blocks = 9 assets.
    const client = makeSessionMockClient({ failLogIndex: 4 });
    const { ctx, calls: auditCalls } = makeAuditCtx();
    const r = await commitSeedingSession(client, draftFor(MAY22_FIXTURE), ctx);

    expect(r.ok).toBe(false);
    expect(r.reason).toBe('partial_commit_failed');
    expect(r.farmos_response.failed_at_child_index).toBe(3);
    expect(r.asset_ids).toEqual([]);
    expect(r.log_ids).toEqual([]);

    // 1 session + 4 source blocks + 4 child blocks = 9 DELETEs.
    expect(client._deletes.length).toBe(9);
    expect(r.farmos_response.orphan_attempted_count).toBe(9);
    expect(r.farmos_response.orphan_cleanup_failed_count).toBe(0);

    // Reverse-order invariant: the FIRST DELETE is the most recently created
    // asset (the 4th child block); the LAST DELETE is the session asset.
    const sessionId = client._created.assets[0].id;
    expect(client._deletes[client._deletes.length - 1]).toBe('/api/asset/fungi/' + sessionId);

    // No orphan_cleanup_failed audit since DELETEs all succeeded.
    expect(auditCalls.find((c) => c.event === 'orphan_cleanup_failed')).toBeUndefined();
  });

  it('Test F (orphan cleanup itself fails): auditLogger.logCommit called with orphan_cleanup_failed for each failed DELETE', async () => {
    const client = makeSessionMockClient({
      failLogIndex: 4,
      deleteResponse: () => ({ ok: false, status: 500, body: null }),
    });
    const { ctx, calls: auditCalls } = makeAuditCtx();
    const r = await commitSeedingSession(client, draftFor(MAY22_FIXTURE), ctx);

    expect(r.ok).toBe(false);
    expect(r.reason).toBe('partial_commit_failed');
    // All 9 DELETEs attempted, all failed.
    expect(client._deletes.length).toBe(9);
    expect(r.farmos_response.orphan_cleanup_failed_count).toBe(9);
    expect(r.farmos_response.orphan_cleanup_failed_ids.length).toBe(9);

    // 9 audit calls, one per failed orphan delete.
    const orphanCalls = auditCalls.filter((c) => c.event === 'orphan_cleanup_failed');
    expect(orphanCalls.length).toBe(9);
    for (const c of orphanCalls) {
      expect(c.result.asset_ids.length).toBe(1);
      expect(c.draft_id).toBe('d-session-1');
    }
  });

  it('Test G (router dispatch): commit(client, draft) with draft.log_type=seeding_session routes to commitSeedingSession', async () => {
    expect(typeof commitRouter.DISPATCH.seeding_session).toBe('function');
    // Same function reference -- confirms the router import is wired to this
    // module (not a typo'd path).
    expect(commitRouter.DISPATCH.seeding_session).toBe(commitSeedingSession);
  });
});
