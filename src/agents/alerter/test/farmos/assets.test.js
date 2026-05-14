'use strict';

const assets = require('../../src/farmos/assets');
const fungiTypeCache = require('../../src/farmos/fungi-type-cache');
const fungiXingCache = require('../../src/farmos/fungi-xing-cache');

// Default `get` stub: returns a stub UUID for any fungi_type/fungi_xing
// lookup so the createFungiAsset path proceeds. Tests that need a
// different behavior pass getImpl explicitly.
function mockClient({ present = false, getImpl, postImpl } = {}) {
  const defaultGet = async (path) => {
    if (/\/api\/taxonomy_term\/fungi_type/.test(path)) {
      return { ok: true, status: 200, body: { data: [{ id: 'fungitype-stub-uuid' }] } };
    }
    if (/\/api\/taxonomy_term\/fungi_xing/.test(path)) {
      return { ok: true, status: 200, body: { data: [{ id: 'fungixing-stub-uuid' }] } };
    }
    return { ok: true, status: 200, body: { data: [] } };
  };
  return {
    probeAssetLinkModule: jest.fn(async () => present),
    get: jest.fn(getImpl || defaultGet),
    post: jest.fn(postImpl || (async () => ({ ok: true, status: 201, body: { data: { id: 'new-asset' } } }))),
  };
}

describe('assets.js (Phase 40 Option A hybrid)', () => {
  beforeEach(() => { assets._clearCache(); fungiTypeCache._clear(); fungiXingCache._clear(); });

  it('payload: fungi_type + fungi_xing relationships always present; no parents, no QR', async () => {
    const client = mockClient();
    await assets.createFungiAsset(client, { name: '260513_DT_001', fungiTypeName: 'DT', fungiXingName: 'block', draftId: 'd1' });
    const sent = client.post.mock.calls[0][1];
    expect(sent.data.attributes.name).toBe('260513_DT_001');
    expect(sent.data.relationships).toBeDefined();
    expect(sent.data.relationships.fungi_type.data[0]).toEqual({ type: 'taxonomy_term--fungi_type', id: 'fungitype-stub-uuid' });
    expect(sent.data.relationships.fungi_xing.data[0]).toEqual({ type: 'taxonomy_term--fungi_xing', id: 'fungixing-stub-uuid' });
    expect(sent.data.relationships.parent).toBeUndefined();
    expect(sent.data.relationships.species).toBeUndefined();
    expect(sent.data.attributes.notes.value).toMatch(/mushy:draft:d1/);
  });

  it('fails clean when fungiTypeName missing', async () => {
    const client = mockClient();
    const r = await assets.createFungiAsset(client, { name: 'X', fungiXingName: 'block', draftId: 'd0' });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('missing_fungi_type_name');
    expect(client.post).not.toHaveBeenCalled();
  });

  it('fails clean when fungiXingName missing', async () => {
    const client = mockClient();
    const r = await assets.createFungiAsset(client, { name: 'X', fungiTypeName: 'DT', draftId: 'd0' });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('missing_fungi_xing_name');
    expect(client.post).not.toHaveBeenCalled();
  });

  it('fails clean when fungi_type taxonomy returns 404 (bundle missing)', async () => {
    const client = mockClient({ getImpl: async () => ({ ok: false, status: 404, body: { errors: [{}] } }) });
    const r = await assets.createFungiAsset(client, { name: 'X', fungiTypeName: 'DT', fungiXingName: 'block', draftId: 'd0' });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('fungi_type_taxonomy_missing');
    expect(client.post).not.toHaveBeenCalled();
  });

  it('fails clean when fungi_xing taxonomy returns 404 (bundle missing)', async () => {
    const client = mockClient({
      getImpl: async (path) => {
        if (/fungi_type/.test(path)) return { ok: true, status: 200, body: { data: [{ id: 'ft' }] } };
        return { ok: false, status: 404, body: { errors: [{}] } };
      },
    });
    const r = await assets.createFungiAsset(client, { name: 'X', fungiTypeName: 'DT', fungiXingName: 'block', draftId: 'd0' });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('fungi_xing_taxonomy_missing');
    expect(client.post).not.toHaveBeenCalled();
  });

  it('fallback path (module-absent): farm_id_tag embedded in payload', async () => {
    const client = mockClient({ present: false });
    await assets.createFungiAsset(client, {
      name: '260513_DT_001',
      fungiTypeName: 'DT',
      fungiXingName: 'block',
      qrCodes: ['Q1'],
      draftId: 'd2',
    });
    const sent = client.post.mock.calls[0][1];
    expect(sent.data.relationships.fungi_type.data[0].id).toBe('fungitype-stub-uuid');
    expect(sent.data.relationships.fungi_xing.data[0].id).toBe('fungixing-stub-uuid');
    expect(sent.data.attributes.farm_id_tag).toEqual([{ qr_code: 'Q1' }]);
  });

  it('module-present path triggers bindQrPostCreate (second POST)', async () => {
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
      fungiTypeName: 'DT',
      fungiXingName: 'block',
      qrCodes: ['QA'],
      draftId: 'd3',
    });
    expect(r.ok).toBe(true);
    expect(client.post).toHaveBeenCalledTimes(2); // asset create + asset_link bind
    expect(client.post.mock.calls[1][0]).toMatch(/asset_link\/farmos_asset_link/);
  });

  it('multi-parent payload (harvest bag with N source blocks)', async () => {
    const client = mockClient();
    await assets.createFungiAsset(client, {
      name: 'HBATCH-2026-05-13-DT-001-bag-1',
      parentIds: ['p1', 'p2'],
      fungiTypeName: 'DT',
      fungiXingName: 'fruit',
      draftId: 'd4',
    });
    const sent = client.post.mock.calls[0][1];
    expect(sent.data.relationships.parent.data.length).toBe(2);
    expect(sent.data.relationships.parent.data.map((d) => d.id)).toEqual(['p1', 'p2']);
    expect(sent.data.relationships.fungi_xing.data[0].id).toBe('fungixing-stub-uuid');
  });

  it('findAssetByName caches: second call zero fetches', async () => {
    const client = mockClient({
      getImpl: async () => ({ ok: true, status: 200, body: { data: [{ id: 'asset-abc' }] } }),
    });
    const r1 = await assets.findAssetByName(client, '260513_DT_CACHE');
    expect(r1.found).toBe(true);
    expect(r1.assetId).toBe('asset-abc');
    const r2 = await assets.findAssetByName(client, '260513_DT_CACHE');
    expect(r2.cached).toBe(true);
    expect(client.get).toHaveBeenCalledTimes(1);
  });

  it('resolveOrCreateAsset returns cached id when found', async () => {
    const client = mockClient({
      getImpl: async () => ({ ok: true, status: 200, body: { data: [{ id: 'asset-old' }] } }),
    });
    const r = await assets.resolveOrCreateAsset(client, { name: '260513_DT_OLD', draftId: 'd5' });
    expect(r.ok).toBe(true);
    expect(r.assetId).toBe('asset-old');
    expect(r.reused).toBe(true);
    expect(client.post).not.toHaveBeenCalled();
  });
});
