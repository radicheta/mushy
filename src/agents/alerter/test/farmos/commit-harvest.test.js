'use strict';

const commitHarvest = require('../../src/farmos/commits/commit-harvest');
const assets = require('../../src/farmos/assets');
const { makeMockClient } = require('./mock-client');

function draft(extra) {
  return Object.assign({
    id: 'd-harv-1',
    log_type: 'harvest',
    draft_json: {
      source_qr_codes: ['SRC1', 'SRC2'],
      harvest_batch_name: 'HBATCH-2026-05-13-DT-001',
      bags: [
        { qr_code: 'BAG1', weight_grams: 250 },
        { qr_code: 'BAG2', weight_grams: 230 },
        { qr_code: 'BAG3', weight_grams: 260 },
      ],
      timestamp: 1700000000,
    },
  }, extra || {});
}

describe('commit-harvest (Phase 40 Plan 04)', () => {
  beforeEach(() => { assets._clearCache(); });

  it('missing source block aborts BEFORE any asset POST', async () => {
    const client = makeMockClient({ knownAssetsByQr: { SRC1: 'src-a' } }); // SRC2 missing
    const r = await commitHarvest(client, draft(), {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('missing_source_block');
    expect(client._created.assets.length).toBe(0);
    expect(client._created.logs.length).toBe(0);
  });

  it('N=2 sources + M=3 bags -> 1 batch + 3 bag assets + 1 log', async () => {
    const client = makeMockClient({ knownAssetsByQr: { SRC1: 'src-a', SRC2: 'src-b' } });
    const r = await commitHarvest(client, draft(), {});
    expect(r.ok).toBe(true);
    expect(client._created.assets.length).toBe(4); // 1 batch + 3 bags
    expect(client._created.logs.length).toBe(1);
  });

  it('log assetIds order: source blocks, batch, bags', async () => {
    const client = makeMockClient({ knownAssetsByQr: { SRC1: 'src-a', SRC2: 'src-b' } });
    await commitHarvest(client, draft(), {});
    const ids = client._created.logs[0].payload.data.relationships.asset.data.map((a) => a.id);
    // first 2 are source ids; remaining 4 are batch + 3 bags (all created with seq)
    expect(ids[0]).toBe('src-a');
    expect(ids[1]).toBe('src-b');
    expect(ids.length).toBe(6);
  });

  it('qr_already_bound_for_bag failure case', async () => {
    const client = makeMockClient({
      knownAssetsByQr: { SRC1: 'src-a', SRC2: 'src-b', BAG2: 'someone-else' },
    });
    const r = await commitHarvest(client, draft(), {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('qr_already_bound_for_bag');
    expect(client._created.assets.length).toBe(0);
  });

  it('result envelope shape', async () => {
    const client = makeMockClient({ knownAssetsByQr: { SRC1: 'a', SRC2: 'b' } });
    const r = await commitHarvest(client, draft(), {});
    expect(r).toEqual(expect.objectContaining({
      ok: true,
      asset_ids: expect.any(Array),
      log_ids: expect.any(Array),
      file_ids: [],
    }));
    expect(r.asset_ids.length).toBe(4); // batch + 3 bags
  });
});
