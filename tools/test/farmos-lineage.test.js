'use strict';

const { parseArgs, walk, sourceAssetIds } = require('../farmos-lineage');

// Mock farmOS client that returns fixed responses by path. The test wires up
// the four-hop pilot lineage bag -> harvest_batch -> block -> sterilization_batch.

function makeMockClient(responses) {
  return {
    get: async (path) => {
      for (const [pattern, body] of responses) {
        if (path.includes(pattern)) {
          return { ok: true, status: 200, body };
        }
      }
      return { ok: true, status: 200, body: { data: [] } };
    },
  };
}

function asset(uuid, bundle, name) {
  return { id: uuid, type: `asset--${bundle}`, attributes: { name } };
}
function harvestLog(id, refs, ts) {
  return {
    id,
    type: 'log--harvest',
    attributes: { name: 'bagging', timestamp: ts },
    relationships: { asset: { data: refs.map((u) => ({ id: u, type: 'asset' })) } },
  };
}
function seedingLog(id, refs, ts) {
  return {
    id,
    type: 'log--seeding',
    attributes: { name: 'inoculation', timestamp: ts },
    relationships: { asset: { data: refs.map((u) => ({ id: u, type: 'asset' })) } },
  };
}

describe('parseArgs', () => {
  test('help when no args', () => {
    expect(parseArgs(['node', 'x']).help).toBe(true);
  });
  test('uuid positional', () => {
    expect(parseArgs(['node', 'x', 'bag-1']).uuid).toBe('bag-1');
  });
});

describe('sourceAssetIds', () => {
  test('excludes the current asset', () => {
    const log = harvestLog('h1', ['block-1', 'bag-1'], '2026-07-01T10:00Z');
    expect(sourceAssetIds(log, 'bag-1')).toEqual(['block-1']);
  });
});

describe('walk: full pilot lineage', () => {
  test('bag -> harvest_batch -> block -> sterilization_batch', async () => {
    const responses = [
      // Asset GETs
      ['/api/asset/fungi/bag-1', { data: asset('bag-1', 'fungi', 'BAG-001') }],
      ['/api/asset/fungi/harvest-batch-1', { data: asset('harvest-batch-1', 'group', 'HARVEST-001') }],
      ['/api/asset/group/harvest-batch-1', { data: asset('harvest-batch-1', 'group', 'HARVEST-001') }],
      ['/api/asset/fungi/block-1', { data: asset('block-1', 'fungi', 'BLOCK-001') }],
      ['/api/asset/fungi/batch-1', { data: asset('batch-1', 'group', 'BATCH-001') }],
      ['/api/asset/group/batch-1', { data: asset('batch-1', 'group', 'BATCH-001') }],

      // Parent log lookups
      ['/api/log/harvest?filter[asset.id]=bag-1', { data: [harvestLog('h1', ['bag-1', 'harvest-batch-1'], '2026-07-01T10:00Z')] }],
      ['/api/log/harvest?filter[asset.id]=harvest-batch-1', { data: [harvestLog('h2', ['harvest-batch-1', 'block-1'], '2026-07-01T10:00Z')] }],
      ['/api/log/harvest?filter[asset.id]=block-1', { data: [] }],
      ['/api/log/seeding?filter[asset.id]=block-1', { data: [seedingLog('s1', ['block-1', 'batch-1'], '2026-05-13T10:00Z')] }],
      ['/api/log/harvest?filter[asset.id]=batch-1', { data: [] }],
      ['/api/log/seeding?filter[asset.id]=batch-1', { data: [] }],
    ];
    const client = makeMockClient(responses);
    const chain = await walk(client, 'bag-1');
    const uuids = chain.map((c) => c.uuid);
    expect(uuids).toEqual(['bag-1', 'harvest-batch-1', 'block-1', 'batch-1']);
  });

  test('leaf only: no parent log -> chain of length 1', async () => {
    const responses = [
      ['/api/asset/fungi/orphan-1', { data: asset('orphan-1', 'fungi', 'ORPHAN') }],
      // No parent logs -> default empty data
    ];
    const client = makeMockClient(responses);
    const chain = await walk(client, 'orphan-1');
    expect(chain).toHaveLength(1);
    expect(chain[0].uuid).toBe('orphan-1');
  });

  test('asset not found -> empty chain', async () => {
    const client = {
      get: async () => ({ ok: false, status: 404, body: null }),
    };
    const chain = await walk(client, 'missing');
    expect(chain).toEqual([]);
  });
});
