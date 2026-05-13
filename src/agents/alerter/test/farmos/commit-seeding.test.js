'use strict';

const commitSeeding = require('../../src/farmos/commits/commit-seeding');
const speciesCache = require('../../src/farmos/species-cache');
const assets = require('../../src/farmos/assets');
const { makeMockClient } = require('./mock-client');

function draft(extra) {
  return Object.assign({
    id: 'd-seed-1',
    log_type: 'seeding',
    draft_json: {
      batch_name: 'BATCH-2026-05-13-001',
      block_name: '260513_DT_001',
      species_code: 'DT',
      qr_codes: ['QR-A'],
      timestamp: 1700000000,
      notes: 'inoc test',
    },
  }, extra || {});
}

describe('commit-seeding (Phase 40 Plan 04)', () => {
  beforeEach(() => { speciesCache._clear(); assets._clearCache(); });

  it('happy path: new BATCH + new block + seeding log -> 3 POSTs', async () => {
    const client = makeMockClient({ speciesUuids: { DT: 'species-dt-uuid' } });
    const r = await commitSeeding(client, draft(), {});
    expect(r.ok).toBe(true);
    expect(client._created.assets.length).toBe(2);
    expect(client._created.logs.length).toBe(1);
    expect(r.asset_ids.length).toBe(2);
    expect(r.log_ids.length).toBe(1);
  });

  it('existing BATCH path: 1 asset POST (block only) + seeding log', async () => {
    const client = makeMockClient({
      speciesUuids: { DT: 'species-dt-uuid' },
      knownAssetsByName: { 'BATCH-2026-05-13-001': 'batch-existing' },
    });
    const r = await commitSeeding(client, draft(), {});
    expect(r.ok).toBe(true);
    expect(client._created.assets.length).toBe(1); // only block
    expect(client._created.logs.length).toBe(1);
    expect(r.asset_ids.length).toBe(1); // only newly-created block
  });

  it('Path B (QR resolves to existing block): zero block POST, seeding log only', async () => {
    const client = makeMockClient({
      knownAssetsByName: { 'BATCH-2026-05-13-001': 'batch-existing' },
      knownAssetsByQr: { 'QR-A': 'block-existing' },
    });
    const r = await commitSeeding(client, draft(), {});
    expect(r.ok).toBe(true);
    expect(client._created.assets.length).toBe(0);
    expect(client._created.logs.length).toBe(1);
    expect(client._created.logs[0].payload.data.relationships.asset.data.map((a) => a.id))
      .toEqual(['batch-existing', 'block-existing']);
  });

  it('species_not_found short-circuits BEFORE block creation', async () => {
    const client = makeMockClient({ /* no DT */ });
    const r = await commitSeeding(client, draft(), {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('species_not_found');
    expect(client._created.assets.length).toBe(1); // batch was created; block was not
    expect(client._created.logs.length).toBe(0);
  });

  it('ambiguous_qr_seeding when 2 QRs resolve to existing blocks', async () => {
    const client = makeMockClient({
      knownAssetsByName: { 'BATCH-2026-05-13-001': 'batch-existing' },
      knownAssetsByQr: { 'QR-A': 'block-1', 'QR-B': 'block-2' },
    });
    const d = draft();
    d.draft_json.qr_codes = ['QR-A', 'QR-B'];
    const r = await commitSeeding(client, d, {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('ambiguous_qr_seeding');
  });

  it('result envelope shape correctness (Path A)', async () => {
    const client = makeMockClient({ speciesUuids: { DT: 'sp' } });
    const r = await commitSeeding(client, draft(), {});
    expect(r).toEqual(expect.objectContaining({
      ok: true,
      asset_ids: expect.any(Array),
      log_ids: expect.any(Array),
      file_ids: [],
      http_status: 201,
    }));
  });
});
