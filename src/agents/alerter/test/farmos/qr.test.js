'use strict';

const qr = require('../../src/farmos/qr');

function mockClient({ getImpl } = {}) {
  return {
    get: jest.fn(getImpl || (async () => ({ ok: true, status: 200, body: { data: [] } }))),
  };
}

describe('qr.js (Phase 40 prod-cutover, id_tag)', () => {
  it('resolveQr filters by id_tag.id and returns assetId when found', async () => {
    const client = mockClient({
      getImpl: async () => ({ ok: true, status: 200, body: { data: [{ id: 'asset-9' }] } }),
    });
    const r = await qr.resolveQr(client, 'QX');
    expect(r.found).toBe(true);
    expect(r.assetId).toBe('asset-9');
    expect(r.path).toBe('id_tag');
    expect(client.get.mock.calls[0][0]).toMatch(/filter\[id_tag\.id\]\[value\]=QX/);
  });

  it('resolveQr returns found:false when no rows match (both-miss path=name)', async () => {
    const client = mockClient();
    const r = await qr.resolveQr(client, 'QY');
    expect(r.found).toBe(false);
    expect(r.path).toBe('name');
  });

  it('resolveQr falls back to name lookup when id_tag returns empty (name hit)', async () => {
    const getImpl = jest.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, body: { data: [] } })
      .mockResolvedValueOnce({ ok: true, status: 200, body: { data: [{ id: 'asset-named-7' }] } });
    const client = { get: getImpl };
    const r = await qr.resolveQr(client, '260512_DT_11');
    expect(r.found).toBe(true);
    expect(r.assetId).toBe('asset-named-7');
    expect(r.path).toBe('name');
    expect(getImpl).toHaveBeenCalledTimes(2);
    expect(getImpl.mock.calls[0][0]).toMatch(/filter\[id_tag\.id\]\[value\]=/);
    expect(getImpl.mock.calls[1][0]).toMatch(/filter\[name\]\[value\]=/);
  });

  it('resolveQr returns found:false when both id_tag and name return empty', async () => {
    const getImpl = jest.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, body: { data: [] } })
      .mockResolvedValueOnce({ ok: true, status: 200, body: { data: [] } });
    const client = { get: getImpl };
    const r = await qr.resolveQr(client, 'NOOP');
    expect(r.found).toBe(false);
    expect(r.path).toBe('name');
    expect(getImpl).toHaveBeenCalledTimes(2);
  });

  it('resolveQr does NOT fall back to name on id_tag http error', async () => {
    const getImpl = jest.fn()
      .mockResolvedValueOnce({ ok: false, status: 500, body: {} });
    const client = { get: getImpl };
    const r = await qr.resolveQr(client, 'QZ2');
    expect(r.found).toBe(false);
    expect(r.error).toBe('http_500');
    expect(r.path).toBe('id_tag');
    expect(getImpl).toHaveBeenCalledTimes(1);
  });

  it('resolveQr surfaces http error', async () => {
    const client = mockClient({
      getImpl: async () => ({ ok: false, status: 500, body: {} }),
    });
    const r = await qr.resolveQr(client, 'QZ');
    expect(r.found).toBe(false);
    expect(r.error).toBe('http_500');
    expect(r.path).toBe('id_tag');
  });

  it('bindQrOnCreate mutates attributes.id_tag with {id, type:qr, location}', () => {
    const p = { data: { type: 'asset--fungi', attributes: { name: 'x' } } };
    qr.bindQrOnCreate(p, ['Q1', 'Q2']);
    expect(p.data.attributes.id_tag).toEqual([
      { id: 'Q1', type: 'other', location: '' },
      { id: 'Q2', type: 'other', location: '' },
    ]);
  });

  it('bindQrOnCreate with empty list leaves payload untouched', () => {
    const p = { data: { type: 'asset--fungi', attributes: { name: 'x' } } };
    qr.bindQrOnCreate(p, []);
    expect(p.data.attributes.id_tag).toBeUndefined();
  });
});
