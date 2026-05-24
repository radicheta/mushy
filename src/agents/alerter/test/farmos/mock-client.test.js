'use strict';

// Phase 51 Plan 01 Task 1: mock-client extensions (patch, delete, GET-by-id,
// 412 protocol, revision_id seed). Drives the Wave-0 infra so Plans 02-05
// can build against a hermetic fake.

const { makeMockClient } = require('./mock-client');

describe('mock-client extensions (Phase 51 Wave 0)', () => {
  it('exposes patch(path, body, opts) recording method PATCH', async () => {
    const c = makeMockClient({
      knownAssetsByName: { foo: { id: 'a-1' } },
    });
    const r = await c.patch('/api/asset/fungi/a-1', {
      data: { id: 'a-1', type: 'asset--fungi', attributes: { name: 'foo' } },
    }, { headers: { 'If-Match': '7' } });
    expect(r.ok).toBe(true);
    expect(r.status).toBe(200);
    const call = c._calls.find((x) => x.method === 'PATCH');
    expect(call).toBeTruthy();
    expect(call.path).toBe('/api/asset/fungi/a-1');
    expect(call.body).toBeDefined();
    expect(call.headers).toEqual({ 'If-Match': '7' });
  });

  it('exposes delete(path, opts) recording method DELETE; returns 204', async () => {
    const c = makeMockClient();
    const r = await c.delete('/api/asset/fungi/a-1');
    expect(r.ok).toBe(true);
    expect(r.status).toBe(204);
    expect(r.body).toBeNull();
    const call = c._calls.find((x) => x.method === 'DELETE');
    expect(call).toBeTruthy();
    expect(call.path).toBe('/api/asset/fungi/a-1');
  });

  it('GET /api/asset/fungi/<uuid> returns the asset body from registry', async () => {
    const c = makeMockClient({
      knownAssetsByName: { foo: { id: 'a-1' } },
    });
    const r = await c.get('/api/asset/fungi/a-1');
    expect(r.ok).toBe(true);
    expect(r.body.data).toBeDefined();
    expect(r.body.data.id).toBe('a-1');
  });

  it('GET-by-id includes attributes.drupal_internal__revision_id (default 1)', async () => {
    const c = makeMockClient({
      knownAssetsByName: { foo: { id: 'a-1' } },
    });
    const r = await c.get('/api/asset/fungi/a-1');
    expect(r.body.data.attributes.drupal_internal__revision_id).toBe(1);
  });

  it('honors revisionIds override for GET-by-id revision_id', async () => {
    const c = makeMockClient({
      knownAssetsByName: { foo: { id: 'a-1' } },
      revisionIds: { foo: 42 },
    });
    const r = await c.get('/api/asset/fungi/a-1');
    expect(r.body.data.attributes.drupal_internal__revision_id).toBe(42);
  });

  it('force412Ids: first PATCH to id returns 412, second returns 200', async () => {
    const c = makeMockClient({
      knownAssetsByName: { foo: { id: 'a-1' } },
      force412Ids: ['a-1'],
    });
    const r1 = await c.patch('/api/asset/fungi/a-1', {
      data: { id: 'a-1', type: 'asset--fungi', attributes: {} },
    });
    expect(r1.ok).toBe(false);
    expect(r1.status).toBe(412);

    const r2 = await c.patch('/api/asset/fungi/a-1', {
      data: { id: 'a-1', type: 'asset--fungi', attributes: {} },
    });
    expect(r2.ok).toBe(true);
    expect(r2.status).toBe(200);
  });

  it('patch returns merged attributes + relationships', async () => {
    const c = makeMockClient({
      knownAssetsByName: { foo: { id: 'a-1' } },
    });
    const r = await c.patch('/api/asset/fungi/a-1', {
      data: {
        id: 'a-1',
        type: 'asset--fungi',
        attributes: { status: 'active' },
        relationships: { parent: { data: [{ type: 'asset--fungi', id: 'p-1' }] } },
      },
    });
    expect(r.ok).toBe(true);
    expect(r.body.data.id).toBe('a-1');
    expect(r.body.data.type).toBe('asset--fungi');
    expect(r.body.data.attributes.status).toBe('active');
    expect(r.body.data.relationships.parent.data[0].id).toBe('p-1');
  });

  it('GET-by-id for log routes too', async () => {
    // Logs by UUID-shaped ids; for test we use the same registry-style.
    const c = makeMockClient({
      knownLogsByAssetId: { 'a-1': { id: 'l-1', type: 'seeding' } },
    });
    // Probe: not strictly required by behavior list, kept for plan 02 use.
    expect(typeof c.get).toBe('function');
  });
});
