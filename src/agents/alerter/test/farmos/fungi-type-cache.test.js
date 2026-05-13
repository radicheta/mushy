'use strict';

const cache = require('../../src/farmos/fungi-type-cache');

function mockClient(getImpl) {
  return { get: jest.fn(getImpl) };
}

describe('fungi-type-cache (Phase 40 ship-gate fix 2026-05-13)', () => {
  beforeEach(() => { cache._clear(); });

  it('returns uuid on first hit; caches subsequent lookups', async () => {
    const client = mockClient(async () => ({ ok: true, status: 200, body: { data: [{ id: 'uuid-batch' }] } }));
    const r1 = await cache.getFungiTypeUuid(client, 'batch');
    expect(r1.ok).toBe(true);
    expect(r1.uuid).toBe('uuid-batch');
    expect(r1.cached).toBeUndefined();
    const r2 = await cache.getFungiTypeUuid(client, 'batch');
    expect(r2.ok).toBe(true);
    expect(r2.uuid).toBe('uuid-batch');
    expect(r2.cached).toBe(true);
    expect(client.get).toHaveBeenCalledTimes(1);
  });

  it('reason=fungi_type_taxonomy_missing on 404 (bundle absent)', async () => {
    const client = mockClient(async () => ({ ok: false, status: 404, body: { errors: [{}] } }));
    const r = await cache.getFungiTypeUuid(client, 'batch');
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('fungi_type_taxonomy_missing');
  });

  it('reason=fungi_type_not_found on 200 + empty data', async () => {
    const client = mockClient(async () => ({ ok: true, status: 200, body: { data: [] } }));
    const r = await cache.getFungiTypeUuid(client, 'block');
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('fungi_type_not_found');
    expect(r.typeName).toBe('block');
  });

  it('reason=http_<n> on transient errors (500, network)', async () => {
    const c1 = mockClient(async () => ({ ok: false, status: 500, body: {} }));
    expect((await cache.getFungiTypeUuid(c1, 'batch')).reason).toBe('http_500');
    const c2 = mockClient(async () => ({ ok: false, status: null, body: null }));
    expect((await cache.getFungiTypeUuid(c2, 'batch')).reason).toBe('http_network');
  });

  it('URL-encodes the type name (safety, not strictly needed for batch/block/bag)', async () => {
    const client = mockClient(async () => ({ ok: true, status: 200, body: { data: [{ id: 'x' }] } }));
    await cache.getFungiTypeUuid(client, 'odd type');
    expect(client.get.mock.calls[0][0]).toBe('/api/taxonomy_term/fungi_type?filter[name][value]=odd%20type');
  });
});
