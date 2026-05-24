'use strict';

const assets = require('../../src/farmos/assets');
const fungiTypeCache = require('../../src/farmos/fungi-type-cache');
const fungiXingCache = require('../../src/farmos/fungi-xing-cache');
const { makeMockClient } = require('./mock-client');

// Default `get` stub: returns a stub UUID for any fungi_type/fungi_xing
// lookup so the createFungiAsset path proceeds. Tests that need a
// different behavior pass getImpl explicitly.
function mockClient({ getImpl, postImpl } = {}) {
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

  it('QR codes embed in payload as id_tag {id, type:qr, location}', async () => {
    const client = mockClient();
    await assets.createFungiAsset(client, {
      name: '260513_DT_001',
      fungiTypeName: 'DT',
      fungiXingName: 'block',
      qrCodes: ['Q1', 'Q2'],
      draftId: 'd2',
    });
    const sent = client.post.mock.calls[0][1];
    expect(sent.data.relationships.fungi_type.data[0].id).toBe('fungitype-stub-uuid');
    expect(sent.data.relationships.fungi_xing.data[0].id).toBe('fungixing-stub-uuid');
    expect(sent.data.attributes.id_tag).toEqual([
      { id: 'Q1', type: 'other', location: '' },
      { id: 'Q2', type: 'other', location: '' },
    ]);
    expect(client.post).toHaveBeenCalledTimes(1); // no second asset_link POST
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

// ---------------------------------------------------------------------------
// Phase 51 UPSERT-05: isStubAsset
// ---------------------------------------------------------------------------

describe('isStubAsset (Phase 51 UPSERT-05)', () => {
  it('returns true when notes.value contains the STUB marker', () => {
    const asset = { attributes: { notes: { value: 'STUB - awaits 2025-paper-scan backfill\nmushy:draft:x' } } };
    expect(assets.isStubAsset(asset)).toBe(true);
  });

  it('returns true when STUB marker is one of several \\n---\\n-separated entries', () => {
    const asset = { attributes: { notes: { value: 'entry_A\n---\nSTUB - awaits 2025-paper-scan backfill\n---\nentry_C' } } };
    expect(assets.isStubAsset(asset)).toBe(true);
  });

  it('returns false for ordinary notes', () => {
    const asset = { attributes: { notes: { value: 'ordinary notes' } } };
    expect(assets.isStubAsset(asset)).toBe(false);
  });

  it('returns false when notes attribute is absent', () => {
    const asset = { attributes: {} };
    expect(assets.isStubAsset(asset)).toBe(false);
  });

  it('returns false for null/undefined asset', () => {
    expect(assets.isStubAsset(null)).toBe(false);
    expect(assets.isStubAsset(undefined)).toBe(false);
  });

  it('STUB_BACKFILL_MARKER constant is exported with the expected literal', () => {
    expect(assets.STUB_BACKFILL_MARKER).toBe('STUB - awaits 2025-paper-scan backfill');
  });
});

// ---------------------------------------------------------------------------
// Phase 51 UPSERT-01/04/05: upsertFungiAsset
// ---------------------------------------------------------------------------

describe('upsertFungiAsset (Phase 51 UPSERT-01/04/05)', () => {
  beforeEach(() => { assets._clearCache(); fungiTypeCache._clear(); fungiXingCache._clear(); });

  it('miss path: findAssetByName empty -> POST via createFungiAsset; outcome=created', async () => {
    const client = makeMockClient({});
    const r = await assets.upsertFungiAsset(client, {
      name: '260524_DT_010',
      fungiTypeName: 'DT',
      fungiXingName: 'block',
      draftId: 'd-miss',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('created');
    expect(r.assetId).toMatch(/^asset-/);
    expect(r.http_status).toBe(201);
    // POST was issued, PATCH was not
    expect(client.post.mock.calls.some((c) => c[0] === '/api/asset/fungi')).toBe(true);
    expect(client.patch).not.toHaveBeenCalled();
  });

  it('hit-mergeable path: existing asset + new parent[] -> PATCH with merged set-union; outcome=patched', async () => {
    const client = makeMockClient({
      knownAssetsByName: {
        '260524_DT_010': {
          id: 'a-1',
          attributes: { name: '260524_DT_010', status: 'active', notes: { value: 'pre' } },
          relationships: {
            fungi_type: { data: { type: 'taxonomy_term--fungi_type', id: 'ft-dt' } },
            fungi_xing: { data: { type: 'taxonomy_term--fungi_xing', id: 'fx-block' } },
            parent: { data: [{ type: 'asset--fungi', id: 'p1' }] },
          },
        },
      },
      revisionIds: { '260524_DT_010': 7 },
    });
    const r = await assets.upsertFungiAsset(client, {
      name: '260524_DT_010',
      parentIds: ['p2'],
      fungiTypeName: 'DT',
      fungiXingName: 'block',
      draftId: 'd-hit',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('patched');
    expect(r.assetId).toBe('a-1');
    expect(r.conflicts).toEqual([]);
    expect(r.etag_source).toBe('soft_compare');
    expect(r.http_status).toBe(200);
    // PATCH was issued with merged parents (p1 + p2)
    expect(client.patch).toHaveBeenCalledTimes(1);
    const patchBody = client.patch.mock.calls[0][1];
    const mergedParents = patchBody.data.relationships.parent.data.map((d) => d.id).sort();
    expect(mergedParents).toEqual(['p1', 'p2']);
  });

  it('hit-noop path: incoming fields already present -> no PATCH; outcome=noop', async () => {
    const client = makeMockClient({
      knownAssetsByName: {
        '260524_DT_011': {
          id: 'a-2',
          attributes: { name: '260524_DT_011', status: 'active', notes: { value: 'mushy:draft:d-noop' } },
          relationships: {
            fungi_type: { data: { type: 'taxonomy_term--fungi_type', id: 'ft-dt' } },
            fungi_xing: { data: { type: 'taxonomy_term--fungi_xing', id: 'fx-block' } },
            parent: { data: [{ type: 'asset--fungi', id: 'p1' }] },
          },
        },
      },
      revisionIds: { '260524_DT_011': 3 },
    });
    const r = await assets.upsertFungiAsset(client, {
      name: '260524_DT_011',
      parentIds: ['p1'], // same parent already there
      fungiTypeName: 'DT',
      fungiXingName: 'block',
      draftId: 'd-noop',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('noop');
    expect(r.assetId).toBe('a-2');
    expect(r.conflicts).toEqual([]);
    expect(client.patch).not.toHaveBeenCalled();
  });

  it('hit-with-conflicts path: fungi_type mismatch -> no PATCH; conflicts populated', async () => {
    const client = makeMockClient({
      knownAssetsByName: {
        '260524_CONFLICT_001': {
          id: 'a-conflict',
          attributes: { name: '260524_CONFLICT_001', status: 'active', notes: { value: '' } },
          relationships: {
            fungi_type: { data: { type: 'taxonomy_term--fungi_type', id: 'ft-shi' } },
            fungi_xing: { data: { type: 'taxonomy_term--fungi_xing', id: 'fx-block' } },
          },
        },
      },
    });
    const r = await assets.upsertFungiAsset(client, {
      name: '260524_CONFLICT_001',
      fungiTypeName: 'KOY', // resolves to ft-koy, conflicts with existing ft-shi
      fungiXingName: 'block',
      draftId: 'd-conflict',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('noop');
    expect(r.conflicts.length).toBe(1);
    expect(r.conflicts[0].field).toBe('fungi_type');
    expect(r.conflicts[0].existing).toBe('ft-shi');
    expect(r.conflicts[0].incoming).toBe('ft-koy');
    expect(client.patch).not.toHaveBeenCalled();
  });

  it('identity-mutation path: never throws; returns structured {ok:false, reason:identity_mutation}', async () => {
    // mergeAssetFields throws when incoming name differs from existing name.
    // We exercise this by directly invoking with a planted mismatch: the
    // lookup returns id 'a-ident', but the GET body has a different name
    // than the one we are upserting under. Since our incoming opts.name is
    // what we look up by, we must seed _byId with a divergent attributes.name.
    const client = makeMockClient({
      knownAssetsByName: {
        '260524_IDENT_001': {
          id: 'a-ident',
          attributes: { name: 'DIFFERENT_NAME_ON_DISK', status: 'active' },
          relationships: {},
        },
      },
    });
    const r = await assets.upsertFungiAsset(client, {
      name: '260524_IDENT_001',
      fungiTypeName: 'DT',
      fungiXingName: 'block',
      draftId: 'd-ident',
    });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('identity_mutation');
    expect(r.http_status).toBe(null);
    expect(client.patch).not.toHaveBeenCalled();
  });

  it('soft-compare retry: revision moves between merge and PATCH -> retries once, then concurrency_loss', async () => {
    // Build a client where every GET-by-id increments the revision_id, so
    // the pre-PATCH re-GET always observes a moved revision and the retry
    // observes one more bump -> concurrency_loss surfaces as noop.
    const client = makeMockClient({
      knownAssetsByName: {
        '260524_RACE_001': {
          id: 'a-race',
          attributes: { name: '260524_RACE_001', status: 'active', notes: { value: '' } },
          relationships: {
            fungi_type: { data: { type: 'taxonomy_term--fungi_type', id: 'ft-dt' } },
            fungi_xing: { data: { type: 'taxonomy_term--fungi_xing', id: 'fx-block' } },
            parent: { data: [{ type: 'asset--fungi', id: 'p-old' }] },
          },
        },
      },
      revisionIds: { '260524_RACE_001': 1 },
    });
    // Wrap client.get to bump revision_id on every asset-by-id GET.
    const origGet = client.get;
    let bumpCounter = 0;
    client.get = jest.fn(async (path, opts) => {
      const r = await origGet(path, opts);
      const m = /^\/api\/asset\/fungi\/([A-Za-z0-9-]+)$/.exec(path);
      if (m && r.ok && r.body && r.body.data && r.body.data.attributes) {
        bumpCounter += 1;
        // Mutate the stored body so subsequent GETs see the new revision.
        client._byId[m[1]].attributes.drupal_internal__revision_id = 1 + bumpCounter;
      }
      return r;
    });
    const r = await assets.upsertFungiAsset(client, {
      name: '260524_RACE_001',
      parentIds: ['p-new'],
      fungiTypeName: 'DT',
      fungiXingName: 'block',
      draftId: 'd-race',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('noop');
    expect(r.reason).toBe('concurrency_loss');
    expect(r.etag_source).toBe('soft_compare');
    // No PATCH should have been issued (re-GET kept showing moved revisions).
    expect(client.patch).not.toHaveBeenCalled();
    // Retry budget: the soft-compare re-GET fires at most twice (once + 1 retry).
    // Initial merge GET (1) + first re-GET (2) + retry merge GET (3) + retry re-GET (4).
    // Bumps observed: exactly 4.
    expect(bumpCounter).toBe(4);
  });

  it('stub enrichment: existing stub asset + real incoming data -> patched; STUB marker preserved', async () => {
    const stubNotes = 'STUB - awaits 2025-paper-scan backfill\n---\nmushy:draft:original';
    const client = makeMockClient({
      knownAssetsByName: {
        '250122_KOY_4': {
          id: 'a-stub',
          attributes: { name: '250122_KOY_4', status: 'active', notes: { value: stubNotes } },
          relationships: {
            // Stub has no fungi_type and no parents yet
            fungi_xing: { data: { type: 'taxonomy_term--fungi_xing', id: 'fx-block' } },
          },
        },
      },
      revisionIds: { '250122_KOY_4': 1 },
    });
    const r = await assets.upsertFungiAsset(client, {
      name: '250122_KOY_4',
      parentIds: ['p-koy-parent'],
      fungiTypeName: 'KOY',
      fungiXingName: 'block',
      draftId: 'd-enrich',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('patched');
    expect(r.conflicts).toEqual([]);
    // Merged notes preserves STUB marker
    const patchBody = client.patch.mock.calls[0][1];
    expect(patchBody.data.attributes.notes.value).toContain('STUB - awaits 2025-paper-scan backfill');
    // Merged parent[] contains incoming parent
    const parentIds = patchBody.data.relationships.parent.data.map((d) => d.id);
    expect(parentIds).toContain('p-koy-parent');
    // The stub still tests as stub after the merge (marker preserved)
    expect(assets.isStubAsset({ attributes: { notes: patchBody.data.attributes.notes } })).toBe(true);
  });

  it('missing revision_id degrades to etag_source=absent; PATCH still issued', async () => {
    const client = makeMockClient({
      knownAssetsByName: {
        '260524_NOREV_001': {
          id: 'a-norev',
          attributes: { name: '260524_NOREV_001', status: 'active', notes: { value: '' } },
          relationships: {
            fungi_type: { data: { type: 'taxonomy_term--fungi_type', id: 'ft-dt' } },
            fungi_xing: { data: { type: 'taxonomy_term--fungi_xing', id: 'fx-block' } },
          },
        },
      },
    });
    // Strip the revision_id from the stored body so GET returns no rev.
    delete client._byId['a-norev'].attributes.drupal_internal__revision_id;
    const r = await assets.upsertFungiAsset(client, {
      name: '260524_NOREV_001',
      parentIds: ['p-new'],
      fungiTypeName: 'DT',
      fungiXingName: 'block',
      draftId: 'd-norev',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('patched');
    expect(r.etag_source).toBe('absent');
    // PATCH issued without If-Match header
    expect(client.patch).toHaveBeenCalledTimes(1);
    const headers = (client.patch.mock.calls[0][2] && client.patch.mock.calls[0][2].headers) || {};
    expect(headers['If-Match']).toBeUndefined();
  });
});
