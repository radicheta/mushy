'use strict';

const cache = require('../../src/farmos/species-cache');

function mockClient(getImpl) {
  return { get: jest.fn(getImpl) };
}

describe('species-cache (Phase 40 ship-gate fix 2026-05-13: 404 classification)', () => {
  beforeEach(() => { cache._clear(); });

  it('happy path: returns uuid and caches', async () => {
    const client = mockClient(async () => ({ ok: true, status: 200, body: { data: [{ id: 'uuid-shi' }] } }));
    const r1 = await cache.getSpeciesUuid(client, 'SHI');
    expect(r1.ok).toBe(true);
    expect(r1.uuid).toBe('uuid-shi');
    const r2 = await cache.getSpeciesUuid(client, 'SHI');
    expect(r2.cached).toBe(true);
    expect(client.get).toHaveBeenCalledTimes(1);
  });

  it('reason=species_taxonomy_missing on 404 (bundle absent, dev-farmOS state pre-seeding)', async () => {
    const client = mockClient(async () => ({ ok: false, status: 404, body: { errors: [{}] } }));
    const r = await cache.getSpeciesUuid(client, 'SHI');
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('species_taxonomy_missing');
  });

  it('reason=species_not_found on 200 + empty (bundle exists, term not present)', async () => {
    const client = mockClient(async () => ({ ok: true, status: 200, body: { data: [] } }));
    const r = await cache.getSpeciesUuid(client, 'XYZ');
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('species_not_found');
    expect(r.shortCode).toBe('XYZ');
  });

  it('reason=http_<n> on transient (500, network)', async () => {
    const c1 = mockClient(async () => ({ ok: false, status: 500, body: {} }));
    expect((await cache.getSpeciesUuid(c1, 'SHI')).reason).toBe('http_500');
  });
});
