'use strict';

const commitHarvest = require('../../src/farmos/commits/commit-harvest');
const assets = require('../../src/farmos/assets');
const fungiTypeCache = require('../../src/farmos/fungi-type-cache');
const fungiXingCache = require('../../src/farmos/fungi-xing-cache');
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

describe('commit-harvest (Option A hybrid)', () => {
  beforeEach(() => { assets._clearCache(); fungiTypeCache._clear(); fungiXingCache._clear(); });

  it('missing source block aborts BEFORE any asset POST', async () => {
    const client = makeMockClient({ knownAssetsByQr: { SRC1: 'src-a' } }); // SRC2 missing
    const r = await commitHarvest(client, draft(), {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('missing_source_block');
    expect(client._created.assets.length).toBe(0);
    expect(client._created.logs.length).toBe(0);
  });

  it('N=2 sources + M=3 bags -> 3 bag assets (no batch) + 1 log', async () => {
    const client = makeMockClient({ knownAssetsByQr: { SRC1: 'src-a', SRC2: 'src-b' } });
    const r = await commitHarvest(client, draft(), {});
    expect(r.ok).toBe(true);
    expect(client._created.assets.length).toBe(3); // bags only, no batch
    expect(client._created.logs.length).toBe(1);
    const bagPayload = client._created.assets[0].payload;
    expect(bagPayload.data.relationships.fungi_type.data[0].id).toBe('ft-dt');
    expect(bagPayload.data.relationships.fungi_xing.data[0].id).toBe('fx-fruit');
    expect(bagPayload.data.relationships.parent.data.map((p) => p.id)).toEqual(['src-a', 'src-b']);
  });

  it('strain resolves from harvest_batch_name when no explicit field', async () => {
    const client = makeMockClient({ knownAssetsByQr: { SRC1: 'src-a', SRC2: 'src-b' } });
    await commitHarvest(client, draft(), {});
    const bagPayload = client._created.assets[0].payload;
    expect(bagPayload.data.relationships.fungi_type.data[0].id).toBe('ft-dt');
  });

  it('missing strain (no batch_name parse, no explicit field) -> missing_strain', async () => {
    const client = makeMockClient({ knownAssetsByQr: { SRC1: 'src-a', SRC2: 'src-b' } });
    const d = draft();
    delete d.draft_json.harvest_batch_name;
    const r = await commitHarvest(client, d, {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('missing_strain');
    expect(client._created.assets.length).toBe(0);
  });

  it('log assetIds order: source blocks, bags', async () => {
    const client = makeMockClient({ knownAssetsByQr: { SRC1: 'src-a', SRC2: 'src-b' } });
    await commitHarvest(client, draft(), {});
    const ids = client._created.logs[0].payload.data.relationships.asset.data.map((a) => a.id);
    expect(ids[0]).toBe('src-a');
    expect(ids[1]).toBe('src-b');
    expect(ids.length).toBe(5); // 2 sources + 3 bags
  });

  it('harvest log notes carry harvest_batch lineage', async () => {
    const client = makeMockClient({ knownAssetsByQr: { SRC1: 'src-a', SRC2: 'src-b' } });
    await commitHarvest(client, draft(), {});
    const notes = client._created.logs[0].payload.data.attributes.notes.value;
    expect(notes).toMatch(/harvest_batch: HBATCH-2026-05-13-DT-001/);
    expect(notes).toMatch(/bag1: 250g/);
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
    expect(r.asset_ids.length).toBe(3); // 3 bags
  });
});
