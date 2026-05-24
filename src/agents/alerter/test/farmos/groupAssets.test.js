'use strict';

// Phase 52 Plan 01: groupAssets.js hermetic unit tests.
//
// Mirrors assets.test.js patterns. asset--group is the stock farm_group
// bundle enabled on dev + prod farmOS (commit 1857037). No taxonomy
// resolution, no QR, no parent edges -- pure session container.

const groupAssets = require('../../src/farmos/groupAssets');

function mockClient({ getImpl, postImpl, deleteImpl } = {}) {
  return {
    get: jest.fn(getImpl || (async () => ({ ok: true, status: 200, body: { data: [] } }))),
    post: jest.fn(postImpl || (async () => ({ ok: true, status: 201, body: { data: { id: 'group-new' } } }))),
    delete: jest.fn(deleteImpl || (async () => ({ ok: true, status: 204, body: null }))),
  };
}

describe('groupAssets.js (Phase 52 Plan 01)', () => {
  beforeEach(() => { groupAssets._clearCache(); });

  describe('findGroupAssetByName', () => {
    it('MISS returns {found:false}', async () => {
      const client = mockClient();
      const r = await groupAssets.findGroupAssetByName(client, 'inoc 2026-05-22');
      expect(r.found).toBe(false);
    });

    it('HIT returns {found:true, assetId}', async () => {
      const client = mockClient({
        getImpl: async () => ({ ok: true, status: 200, body: { data: [{ id: 'group-abc' }] } }),
      });
      const r = await groupAssets.findGroupAssetByName(client, 'inoc 2026-05-22');
      expect(r.found).toBe(true);
      expect(r.assetId).toBe('group-abc');
    });

    it('uses GET /api/asset/group?filter[name][value]=<encoded-name>', async () => {
      const client = mockClient();
      await groupAssets.findGroupAssetByName(client, 'inoc 2026-05-22 #2');
      const path = client.get.mock.calls[0][0];
      expect(path).toBe('/api/asset/group?filter[name][value]=' + encodeURIComponent('inoc 2026-05-22 #2'));
    });

    it('caches subsequent lookups (second call does NOT hit client.get)', async () => {
      const client = mockClient({
        getImpl: async () => ({ ok: true, status: 200, body: { data: [{ id: 'group-cached' }] } }),
      });
      const r1 = await groupAssets.findGroupAssetByName(client, 'inoc 2026-05-22');
      expect(r1.found).toBe(true);
      const r2 = await groupAssets.findGroupAssetByName(client, 'inoc 2026-05-22');
      expect(r2.found).toBe(true);
      expect(r2.cached).toBe(true);
      expect(client.get).toHaveBeenCalledTimes(1);
    });
  });

  describe('upsertGroupAsset', () => {
    it('MISS path -> POST /api/asset/group with correct payload; returns created', async () => {
      const client = mockClient();
      const r = await groupAssets.upsertGroupAsset(client, {
        name: 'inoc 2026-05-22',
        draftId: 'draft-xyz',
      });
      expect(r.ok).toBe(true);
      expect(r.outcome).toBe('created');
      expect(r.assetId).toBe('group-new');
      expect(r.http_status).toBe(201);
      expect(client.post).toHaveBeenCalledTimes(1);
      const [path, body] = client.post.mock.calls[0];
      expect(path).toBe('/api/asset/group');
      expect(body.data.type).toBe('asset--group');
      expect(body.data.attributes.name).toBe('inoc 2026-05-22');
      expect(body.data.attributes.status).toBe('active');
      expect(body.data.attributes.notes.value).toContain('mushy:draft:draft-xyz');
      expect(body.data.attributes.notes.format).toBe('plain_text');
      // No relationships field at all
      expect(body.data.relationships).toBeUndefined();
    });

    it('HIT path: findGroupAssetByName returns existing -> NO POST, outcome=reused', async () => {
      const client = mockClient({
        getImpl: async () => ({ ok: true, status: 200, body: { data: [{ id: 'group-existing' }] } }),
      });
      const r = await groupAssets.upsertGroupAsset(client, {
        name: 'inoc 2026-05-22',
        draftId: 'draft-replay',
      });
      expect(r.ok).toBe(true);
      expect(r.outcome).toBe('reused');
      expect(r.assetId).toBe('group-existing');
      expect(client.post).not.toHaveBeenCalled();
    });

    it('POST 4xx -> {ok:false, reason:http_<status>}', async () => {
      const client = mockClient({
        postImpl: async () => ({ ok: false, status: 422, body: { errors: [{}] } }),
      });
      const r = await groupAssets.upsertGroupAsset(client, {
        name: 'inoc 2026-05-22',
        draftId: 'd',
      });
      expect(r.ok).toBe(false);
      expect(r.reason).toBe('http_422');
      expect(r.http_status).toBe(422);
    });

    it('POST 5xx -> {ok:false, reason:http_<status>}', async () => {
      const client = mockClient({
        postImpl: async () => ({ ok: false, status: 500, body: null }),
      });
      const r = await groupAssets.upsertGroupAsset(client, {
        name: 'inoc 2026-05-22',
        draftId: 'd',
      });
      expect(r.ok).toBe(false);
      expect(r.reason).toBe('http_500');
      expect(r.http_status).toBe(500);
    });

    it('notes trailer: notes opt provided -> "<notes>\\nmushy:draft:<draftId>"', async () => {
      const client = mockClient();
      await groupAssets.upsertGroupAsset(client, {
        name: 'inoc 2026-05-22',
        draftId: 'd1',
        notes: 'session preflight',
      });
      const body = client.post.mock.calls[0][1];
      expect(body.data.attributes.notes.value).toBe('session preflight\nmushy:draft:d1');
    });

    it('notes trailer: notes opt absent -> just "mushy:draft:<draftId>"', async () => {
      const client = mockClient();
      await groupAssets.upsertGroupAsset(client, {
        name: 'inoc 2026-05-22',
        draftId: 'd2',
      });
      const body = client.post.mock.calls[0][1];
      expect(body.data.attributes.notes.value).toBe('mushy:draft:d2');
    });
  });

  describe('deleteGroupAsset', () => {
    it('DELETE /api/asset/group/<id> ok -> {ok:true, http_status}', async () => {
      const client = mockClient();
      const r = await groupAssets.deleteGroupAsset(client, 'group-123');
      expect(r.ok).toBe(true);
      expect(r.http_status).toBe(204);
      expect(client.delete).toHaveBeenCalledWith('/api/asset/group/group-123');
    });

    it('DELETE failure -> {ok:false, reason:http_<status>}', async () => {
      const client = mockClient({
        deleteImpl: async () => ({ ok: false, status: 404, body: { errors: [{}] } }),
      });
      const r = await groupAssets.deleteGroupAsset(client, 'group-gone');
      expect(r.ok).toBe(false);
      expect(r.reason).toBe('http_404');
      expect(r.http_status).toBe(404);
    });

    it('invalidates name cache (subsequent find does NOT return stale UUID)', async () => {
      // Seed cache
      const getImpl = jest.fn()
        .mockResolvedValueOnce({ ok: true, status: 200, body: { data: [{ id: 'group-zzz' }] } })
        .mockResolvedValueOnce({ ok: true, status: 200, body: { data: [] } });
      const client = {
        get: getImpl,
        post: jest.fn(),
        delete: jest.fn(async () => ({ ok: true, status: 204, body: null })),
      };
      const r1 = await groupAssets.findGroupAssetByName(client, 'inoc 2026-05-22');
      expect(r1.assetId).toBe('group-zzz');
      // Delete it
      await groupAssets.deleteGroupAsset(client, 'group-zzz');
      // Subsequent lookup must NOT return cached id -- must re-fetch
      const r2 = await groupAssets.findGroupAssetByName(client, 'inoc 2026-05-22');
      expect(r2.found).toBe(false);
      expect(client.get).toHaveBeenCalledTimes(2);
    });
  });
});
