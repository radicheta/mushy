'use strict';

const qr = require('../../src/farmos/qr');

function mockClient({ present = true, getImpl, postImpl } = {}) {
  return {
    probeAssetLinkModule: jest.fn(async () => present),
    get: jest.fn(getImpl || (async () => ({ ok: true, status: 200, body: { data: [] } }))),
    post: jest.fn(postImpl || (async () => ({ ok: true, status: 201, body: { data: { id: 'link-1' } } }))),
  };
}

describe('qr.js (Phase 40 Plan 03)', () => {
  it('resolveQr module-present returns assetId from asset_link path', async () => {
    const client = mockClient({
      present: true,
      getImpl: async () => ({ ok: true, status: 200, body: { data: [{
        type: 'asset_link--farmos_asset_link',
        attributes: { qr_code: 'Q1' },
        relationships: { asset: { data: { type: 'asset--fungi', id: 'asset-42' } } },
      }] } }),
    });
    const r = await qr.resolveQr(client, 'Q1');
    expect(r.found).toBe(true);
    expect(r.assetId).toBe('asset-42');
    expect(r.path).toBe('asset_link');
  });

  it('resolveQr fallback queries fungi filter when module absent', async () => {
    const client = mockClient({
      present: false,
      getImpl: async () => ({ ok: true, status: 200, body: { data: [{ id: 'asset-9' }] } }),
    });
    const r = await qr.resolveQr(client, 'QX');
    expect(r.assetId).toBe('asset-9');
    expect(r.path).toBe('farm_id_tag');
    expect(client.get.mock.calls[0][0]).toMatch(/filter\[farm_id_tag\.qr_code\]\[value\]=QX/);
  });

  it('bindQrOnCreate {fallback:true} mutates attributes.farm_id_tag', () => {
    const p = { data: { type: 'asset--fungi', attributes: { name: 'x' } } };
    qr.bindQrOnCreate(p, ['Q1', 'Q2'], { fallback: true });
    expect(p.data.attributes.farm_id_tag).toEqual([{ qr_code: 'Q1' }, { qr_code: 'Q2' }]);
  });

  it('bindQrOnCreate without fallback leaves payload untouched', () => {
    const p = { data: { type: 'asset--fungi', attributes: { name: 'x' } } };
    qr.bindQrOnCreate(p, ['Q1']);
    expect(p.data.attributes.farm_id_tag).toBeUndefined();
  });

  it('bindQrPostCreate posts once per qrCode', async () => {
    const client = mockClient();
    const r = await qr.bindQrPostCreate(client, 'asset-1', ['Q1', 'Q2', 'Q3']);
    expect(client.post).toHaveBeenCalledTimes(3);
    expect(r.bindings.length).toBe(3);
    expect(r.ok).toBe(true);
  });

  it('bindQrPostCreate continues past one failed binding', async () => {
    let n = 0;
    const client = mockClient({
      postImpl: async () => {
        n++;
        if (n === 2) return { ok: false, status: 500, body: {} };
        return { ok: true, status: 201, body: { data: { id: 'link-' + n } } };
      },
    });
    const r = await qr.bindQrPostCreate(client, 'asset-1', ['Q1', 'Q2', 'Q3']);
    expect(client.post).toHaveBeenCalledTimes(3);
    expect(r.ok).toBe(false);
    expect(r.bindings.filter((b) => b.ok).length).toBe(2);
  });
});
