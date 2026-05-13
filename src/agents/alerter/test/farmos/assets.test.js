'use strict';

const assets = require('../../src/farmos/assets');

function mockClient({ present = false, getImpl, postImpl } = {}) {
  return {
    probeAssetLinkModule: jest.fn(async () => present),
    get: jest.fn(getImpl || (async () => ({ ok: true, status: 200, body: { data: [] } }))),
    post: jest.fn(postImpl || (async () => ({ ok: true, status: 201, body: { data: { id: 'new-asset' } } }))),
  };
}

describe('assets.js (Phase 40 Plan 03)', () => {
  beforeEach(() => { assets._clearCache(); });

  it('B1 payload: no parents, no species, no QR -> no relationships block', async () => {
    const client = mockClient();
    await assets.createFungiAsset(client, { name: 'BATCH-2026-05-13-001', draftId: 'd1' });
    const sent = client.post.mock.calls[0][1];
    expect(sent.data.attributes.name).toBe('BATCH-2026-05-13-001');
    expect(sent.data.relationships).toBeUndefined();
    expect(sent.data.attributes.notes.value).toMatch(/mushy:draft:d1/);
  });

  it('B2 fallback path (module-absent): farm_id_tag embedded in payload', async () => {
    const client = mockClient({ present: false });
    await assets.createFungiAsset(client, {
      name: '260513_DT_001',
      parentIds: ['batch-uuid'],
      speciesUuid: 'species-uuid',
      qrCodes: ['Q1'],
      draftId: 'd2',
    });
    const sent = client.post.mock.calls[0][1];
    expect(sent.data.relationships.parent.data[0].id).toBe('batch-uuid');
    expect(sent.data.relationships.species.data[0].id).toBe('species-uuid');
    expect(sent.data.attributes.farm_id_tag).toEqual([{ qr_code: 'Q1' }]);
  });

  it('B2 module-present path triggers bindQrPostCreate (second POST)', async () => {
    let postCalls = 0;
    const client = mockClient({
      present: true,
      postImpl: async () => {
        postCalls++;
        return { ok: true, status: 201, body: { data: { id: postCalls === 1 ? 'asset-x' : 'link-' + postCalls } } };
      },
    });
    const r = await assets.createFungiAsset(client, {
      name: '260513_DT_002',
      parentIds: ['b'],
      speciesUuid: 's',
      qrCodes: ['QA'],
      draftId: 'd3',
    });
    expect(r.ok).toBe(true);
    expect(client.post).toHaveBeenCalledTimes(2); // asset create + asset_link bind
    expect(client.post.mock.calls[1][0]).toMatch(/asset_link\/farmos_asset_link/);
  });

  it('B3 payload: multi-parent', async () => {
    const client = mockClient();
    await assets.createFungiAsset(client, {
      name: 'HBATCH-2026-05-13-DT-001',
      parentIds: ['p1', 'p2'],
      draftId: 'd4',
    });
    const sent = client.post.mock.calls[0][1];
    expect(sent.data.relationships.parent.data.length).toBe(2);
    expect(sent.data.relationships.parent.data.map((d) => d.id)).toEqual(['p1', 'p2']);
  });

  it('findAssetByName caches: second call zero fetches', async () => {
    const client = mockClient({
      getImpl: async () => ({ ok: true, status: 200, body: { data: [{ id: 'asset-abc' }] } }),
    });
    const r1 = await assets.findAssetByName(client, 'BATCH-CACHE-1');
    expect(r1.found).toBe(true);
    expect(r1.assetId).toBe('asset-abc');
    const r2 = await assets.findAssetByName(client, 'BATCH-CACHE-1');
    expect(r2.cached).toBe(true);
    expect(client.get).toHaveBeenCalledTimes(1);
  });

  it('resolveOrCreateAsset returns cached id when found', async () => {
    const client = mockClient({
      getImpl: async () => ({ ok: true, status: 200, body: { data: [{ id: 'asset-old' }] } }),
    });
    const r = await assets.resolveOrCreateAsset(client, { name: 'BATCH-OLD', draftId: 'd5' });
    expect(r.ok).toBe(true);
    expect(r.assetId).toBe('asset-old');
    expect(r.reused).toBe(true);
    expect(client.post).not.toHaveBeenCalled();
  });
});
