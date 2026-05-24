'use strict';

const commitSeeding = require('../../src/farmos/commits/commit-seeding');
const assets = require('../../src/farmos/assets');
const fungiTypeCache = require('../../src/farmos/fungi-type-cache');
const fungiXingCache = require('../../src/farmos/fungi-xing-cache');
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

describe('commit-seeding (Option A hybrid)', () => {
  beforeEach(() => { assets._clearCache(); fungiTypeCache._clear(); fungiXingCache._clear(); });

  it('happy path: 1 block asset + 1 seeding log (no batch asset)', async () => {
    const client = makeMockClient();
    const r = await commitSeeding(client, draft(), {});
    expect(r.ok).toBe(true);
    expect(client._created.assets.length).toBe(1); // only block
    expect(client._created.logs.length).toBe(1);
    expect(r.asset_ids.length).toBe(1);
    const blockPayload = client._created.assets[0].payload;
    expect(blockPayload.data.relationships.fungi_type.data[0].id).toBe('ft-dt');
    expect(blockPayload.data.relationships.fungi_xing.data[0].id).toBe('fx-block');
  });

  it('seeding log notes carry sterilization_batch lineage', async () => {
    const client = makeMockClient();
    await commitSeeding(client, draft(), {});
    const logPayload = client._created.logs[0].payload;
    expect(logPayload.data.attributes.notes.value).toMatch(/sterilization_batch: BATCH-2026-05-13-001/);
  });

  it('Path B (QR resolves to existing block): zero asset POST, seeding log only', async () => {
    const client = makeMockClient({
      knownAssetsByQr: { 'QR-A': 'block-existing' },
    });
    const r = await commitSeeding(client, draft(), {});
    expect(r.ok).toBe(true);
    expect(client._created.assets.length).toBe(0);
    expect(client._created.logs.length).toBe(1);
    expect(client._created.logs[0].payload.data.relationships.asset.data.map((a) => a.id))
      .toEqual(['block-existing']);
  });

  it('missing strain short-circuits BEFORE block creation', async () => {
    const client = makeMockClient();
    const d = draft();
    delete d.draft_json.species_code;
    const r = await commitSeeding(client, d, {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('missing_strain');
    expect(client._created.assets.length).toBe(0);
  });

  it('unknown strain (no taxonomy term) -> fungi_type_not_found', async () => {
    const client = makeMockClient({ fungiTypeUuids: {} }); // empty -- no strain resolves
    const r = await commitSeeding(client, draft(), {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('fungi_type_not_found');
  });

  it('ambiguous_qr_seeding when 2 QRs resolve to existing blocks', async () => {
    const client = makeMockClient({
      knownAssetsByQr: { 'QR-A': 'block-1', 'QR-B': 'block-2' },
    });
    const d = draft();
    d.draft_json.qr_codes = ['QR-A', 'QR-B'];
    const r = await commitSeeding(client, d, {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('ambiguous_qr_seeding');
  });

  it('Phase 51 idempotency: replaying the same seeding draft twice produces no duplicate asset/log', async () => {
    const client = makeMockClient();
    const r1 = await commitSeeding(client, draft(), {});
    expect(r1.ok).toBe(true);
    const a1 = client._created.assets.length; // 1
    const l1 = client._created.logs.length;   // 1
    const r2 = await commitSeeding(client, draft(), {});
    expect(r2.ok).toBe(true);
    // Second run: name lookup hits the existing asset; stable-key lookup hits
    // the existing seeding log — no new POSTs.
    expect(client._created.assets.length).toBe(a1);
    expect(client._created.logs.length).toBe(l1);
    // First run created 1 asset; second run upsert noop/patch so asset_ids empty.
    expect(r2.asset_ids).toEqual([]);
    expect(r2.log_ids.length).toBe(1);
  });

  it('result envelope shape correctness (Path A)', async () => {
    const client = makeMockClient();
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
