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

// Phase 54 Cycle-1 (finding B): ensureFungiTypeUuid mints an unknown strain's
// term when create=true (backfill = santi source-of-truth), but never on the
// live-capture default (typo-safe) or on infra errors.
describe('ensureFungiTypeUuid create-on-missing', () => {
  beforeEach(() => { cache._clear(); });

  function clientGP(getImpl, postImpl) {
    return { get: jest.fn(getImpl), post: jest.fn(postImpl) };
  }

  it('returns the existing term without POSTing when found', async () => {
    const client = clientGP(
      async () => ({ ok: true, status: 200, body: { data: [{ id: 'uuid-cas' }] } }),
      async () => { throw new Error('should not POST'); },
    );
    const r = await cache.ensureFungiTypeUuid(client, 'CAS', { create: true });
    expect(r).toEqual({ ok: true, uuid: 'uuid-cas' });
    expect(client.post).not.toHaveBeenCalled();
  });

  it('create=true mints the term on fungi_type_not_found', async () => {
    const client = clientGP(
      async () => ({ ok: true, status: 200, body: { data: [] } }),
      async () => ({ ok: true, status: 201, body: { data: { id: 'uuid-new-poy' } } }),
    );
    const r = await cache.ensureFungiTypeUuid(client, 'POY', { create: true });
    expect(r).toEqual({ ok: true, uuid: 'uuid-new-poy', created: true });
    expect(client.post).toHaveBeenCalledWith('/api/taxonomy_term/fungi_type', {
      data: { type: 'taxonomy_term--fungi_type', attributes: { name: 'POY' } },
    });
    // Minted uuid is cached for subsequent lookups.
    expect((await cache.ensureFungiTypeUuid(client, 'POY', { create: true })).uuid).toBe('uuid-new-poy');
  });

  it('create=false (live-capture default) does NOT mint', async () => {
    const client = clientGP(
      async () => ({ ok: true, status: 200, body: { data: [] } }),
      async () => { throw new Error('should not POST'); },
    );
    const r = await cache.ensureFungiTypeUuid(client, 'POY', { create: false });
    expect(r).toMatchObject({ ok: false, reason: 'fungi_type_not_found' });
    expect(client.post).not.toHaveBeenCalled();
  });

  it('does NOT mint on taxonomy-missing (infra problem, not a new strain)', async () => {
    const client = clientGP(
      async () => ({ ok: false, status: 404 }),
      async () => { throw new Error('should not POST'); },
    );
    const r = await cache.ensureFungiTypeUuid(client, 'POY', { create: true });
    expect(r).toMatchObject({ ok: false, reason: 'fungi_type_taxonomy_missing' });
    expect(client.post).not.toHaveBeenCalled();
  });

  it('surfaces a create HTTP failure', async () => {
    const client = clientGP(
      async () => ({ ok: true, status: 200, body: { data: [] } }),
      async () => ({ ok: false, status: 403 }),
    );
    const r = await cache.ensureFungiTypeUuid(client, 'POY', { create: true });
    expect(r).toMatchObject({ ok: false, reason: 'fungi_type_create_http_403' });
  });
});
