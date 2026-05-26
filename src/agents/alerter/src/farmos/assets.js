'use strict';

// Phase 40 fungi asset creation primitive. Option A hybrid shape
// (2026-05-14): asset--fungi requires fungi_type (strain code term, e.g.
// SHI/SH2/...) AND fungi_xing (structural classifier: block | fruit).
// Pre-inoc substrates are NOT fungi assets -- they live in the material
// bundle or as pasteurization logs. See
// .planning/notes/2026-05-14-reply-from-farmos-fungi-schema.md.
//
// Module-level LRU cache for asset name -> id resolution.

const qr = require('./qr');
const fungiTypeCache = require('./fungi-type-cache');
const fungiXingCache = require('./fungi-xing-cache');
const { mergeAssetFields, IdentityMutationError } = require('./merge');

// Phase 51 UPSERT-05: marker string in notes.value identifies hand-stubbed
// ancestors awaiting 2025-paper-scan backfill. See
// .planning/notes/2026-05-24-prod-write-receipt.md (4 stubs in prod farmOS).
const STUB_BACKFILL_MARKER = 'STUB - awaits 2025-paper-scan backfill';

const NAME_CACHE = new Map(); // name -> assetId; capped at 32
const NAME_CACHE_MAX = 32;

// NAME_CACHE survives PATCH without invalidation because UPSERT-03's
// IdentityMutationError on name change makes (name -> id) stable. If a future
// feature adds rename support, the cache MUST be invalidated in upsertFungiAsset.

function _cacheGet(name) {
  if (!NAME_CACHE.has(name)) return undefined;
  const v = NAME_CACHE.get(name);
  NAME_CACHE.delete(name);
  NAME_CACHE.set(name, v);
  return v;
}

function _cacheSet(name, id) {
  if (NAME_CACHE.has(name)) NAME_CACHE.delete(name);
  NAME_CACHE.set(name, id);
  while (NAME_CACHE.size > NAME_CACHE_MAX) {
    const k = NAME_CACHE.keys().next().value;
    NAME_CACHE.delete(k);
  }
}

function _clearCache() { NAME_CACHE.clear(); }

async function findAssetByName(client, name) {
  const cached = _cacheGet(name);
  if (cached) return { found: true, assetId: cached, cached: true };
  const enc = encodeURIComponent(name);
  const r = await client.get(`/api/asset/fungi?filter[name][value]=${enc}`);
  if (!r.ok) return { found: false, error: 'http_' + (r.status || 'network') };
  const arr = r.body && r.body.data;
  if (Array.isArray(arr) && arr.length > 0) {
    const id = arr[0].id;
    _cacheSet(name, id);
    return { found: true, assetId: id };
  }
  return { found: false };
}

// Internal payload builder shared by createFungiAsset and upsertFungiAsset.
// Returns either {ok:true, payload, attributes, relationships} where
// attributes/relationships are the canonical shape mergeAssetFields expects,
// or {ok:false, reason} on a taxonomy resolution failure.
async function _buildAssetBody(client, opts) {
  const {
    name,
    parentIds = [],
    fungiTypeName = null,
    fungiXingName = null,
    draftId,
    qrCodes = [],
    notes = null,
    allowNoFungiType = false,
    // Phase 54 Cycle-1: backfill (santi source-of-truth) opts in to minting an
    // unknown strain's fungi_type term instead of failing fungi_type_not_found.
    // Live capture leaves this false so extraction typos never pollute the taxonomy.
    createMissingFungiType = false,
  } = opts;
  if (!allowNoFungiType && !fungiTypeName) return { ok: false, reason: 'missing_fungi_type_name' };
  if (!fungiXingName) return { ok: false, reason: 'missing_fungi_xing_name' };
  let ft = null;
  if (fungiTypeName) {
    ft = await fungiTypeCache.ensureFungiTypeUuid(client, fungiTypeName, { create: createMissingFungiType });
    if (!ft.ok) return { ok: false, reason: ft.reason, fungiTypeName };
  }
  const fx = await fungiXingCache.getFungiXingUuid(client, fungiXingName);
  if (!fx.ok) return { ok: false, reason: fx.reason, fungiXingName };
  const noteTrailer = (notes ? notes + '\n' : '') + 'mushy:draft:' + draftId;
  const attributes = {
    name,
    status: 'active',
    notes: { value: noteTrailer, format: 'plain_text' },
  };
  const relationships = {
    fungi_xing: { data: [{ type: 'taxonomy_term--fungi_xing', id: fx.uuid }] },
  };
  if (ft && ft.uuid) {
    relationships.fungi_type = { data: [{ type: 'taxonomy_term--fungi_type', id: ft.uuid }] };
  }
  if (parentIds.length > 0) {
    relationships.parent = { data: parentIds.map((id) => ({ type: 'asset--fungi', id })) };
  }
  const payload = {
    data: {
      type: 'asset--fungi',
      attributes,
    },
  };
  payload.data.relationships = relationships;
  if (qrCodes.length > 0) {
    qr.bindQrOnCreate(payload, qrCodes);
    // Mirror the id_tag onto attributes so the merge layer treats it as part
    // of the canonical attributes view as well (payload.data.attributes is
    // the same object reference as `attributes`, so this is already done).
  }
  return { ok: true, payload, attributes, relationships };
}

async function createFungiAsset(client, opts) {
  const built = await _buildAssetBody(client, opts);
  if (!built.ok) return built;
  const r = await client.post('/api/asset/fungi', built.payload);
  if (!r.ok) {
    return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
  }
  const assetId = r.body && r.body.data && r.body.data.id;
  if (!assetId) {
    return { ok: false, reason: 'no_asset_id_in_response' };
  }
  _cacheSet(opts.name, assetId);
  return { ok: true, assetId, qrBindings: [], http_status: r.status };
}

async function resolveOrCreateAsset(client, opts) {
  const lookup = await findAssetByName(client, opts.name);
  if (lookup.found) return { ok: true, assetId: lookup.assetId, reused: true };
  return createFungiAsset(client, opts);
}

// Phase 51 UPSERT-05: stub-detection predicate. Pure.
function isStubAsset(asset) {
  if (!asset || !asset.attributes || !asset.attributes.notes) return false;
  const value = asset.attributes.notes.value;
  return typeof value === 'string' && value.includes(STUB_BACKFILL_MARKER);
}

// Helper: structural compare of merged vs existing on the dimensions we touch.
// JSON.stringify on the attributes+relationships subset is sufficient because
// mergeAssetFields produces canonical (set-union, dedup) outputs.
function _isMergeNoop(existing, merged) {
  // Compare attributes and relationships structurally, but normalize the
  // notes object to its value-only projection: createFungiAsset always
  // emits `{value, format:'plain_text'}` whereas farmOS GET responses may
  // omit `format` -- a missing-format difference is not a real change.
  function _normAttrs(a) {
    const out = Object.assign({}, a || {});
    if (out.notes && typeof out.notes === 'object') {
      out.notes = { value: out.notes.value };
    }
    // drupal_internal__revision_id is server-side metadata; never part of
    // anything we'd PATCH so exclude from compare.
    delete out.drupal_internal__revision_id;
    return out;
  }
  const ea = _normAttrs(existing && existing.attributes);
  const er = (existing && existing.relationships) || {};
  const ma = _normAttrs(merged && merged.attributes);
  const mr = (merged && merged.relationships) || {};
  return JSON.stringify(ea) === JSON.stringify(ma)
      && JSON.stringify(er) === JSON.stringify(mr);
}

// Phase 51 UPSERT-01/04/05: lookup-merge-or-create primitive.
//   - miss  -> delegate to createFungiAsset (outcome='created')
//   - hit, mergeable, non-empty diff -> PATCH with merged body (outcome='patched')
//   - hit, mergeable, zero diff      -> no PATCH (outcome='noop')
//   - hit, scalar conflict           -> no PATCH (outcome='noop', conflicts populated)
//   - hit, identity mutation         -> structured {ok:false, reason:'identity_mutation'}
//   - hit, soft revision_id moved    -> retry merge ONCE; if still moved,
//                                       outcome='noop', reason='concurrency_loss'
//
// Soft compare degrades to etag_source='absent' (and skips If-Match header)
// when the GET response has no drupal_internal__revision_id. See
// 51-RESEARCH.md §3 / Pitfall 2 — farmOS doesn't honor If-Match, the soft
// compare is a best-effort guard, not a true concurrency primitive.
async function upsertFungiAsset(client, opts) {
  const lookup = await findAssetByName(client, opts.name);

  // Miss path -> POST via createFungiAsset, wrap return.
  if (!lookup.found) {
    const r = await createFungiAsset(client, opts);
    if (!r.ok) {
      return { ok: false, reason: r.reason, http_status: r.http_status || null, conflicts: [], etag_source: null };
    }
    return {
      ok: true,
      assetId: r.assetId,
      outcome: 'created',
      conflicts: [],
      etag_source: null,
      http_status: r.http_status,
    };
  }

  // Hit path -> GET existing, build incoming, merge, decide PATCH-or-noop.
  const built = await _buildAssetBody(client, opts);
  if (!built.ok) {
    return { ok: false, reason: built.reason, http_status: null, conflicts: [], etag_source: null };
  }
  // Normalize incoming relationships to the singleton-`data` shape that
  // merge.js's SCALAR_REL_FIELDS expects. createFungiAsset POSTs
  // fungi_type/fungi_xing as `{data: [{...}]}` (array form) which is what
  // farmOS accepts on create; existing assets on GET come back as
  // `{data: {...}}` (singleton). For mergeAssetFields to compare like-with-
  // like, collapse the array form to singleton on the merge input.
  const incomingRelationships = Object.assign({}, built.relationships);
  for (const f of ['fungi_type', 'fungi_xing']) {
    const rel = incomingRelationships[f];
    if (rel && Array.isArray(rel.data)) {
      incomingRelationships[f] = { data: rel.data[0] || null };
    }
  }
  const incoming = { type: 'asset--fungi', attributes: built.attributes, relationships: incomingRelationships };

  async function _getExisting() {
    const r = await client.get('/api/asset/fungi/' + lookup.assetId);
    if (!r.ok) return null;
    return r.body && r.body.data;
  }

  // One attempt of merge cycle: GET -> merge -> (if non-noop, non-conflict)
  // -> re-GET to soft-compare revision_id -> PATCH if revision stable.
  // Returns one of: {kind:'patched', result}, {kind:'noop', result},
  // {kind:'conflict', result}, {kind:'identity', result}, {kind:'race'} (needs retry).
  async function _attempt() {
    const existing = await _getExisting();
    if (!existing) {
      return { kind: 'noop', result: { ok: false, reason: 'lookup_missing_after_find', http_status: null, conflicts: [], etag_source: null } };
    }
    const preMergeRevisionId = existing.attributes && existing.attributes.drupal_internal__revision_id != null
      ? existing.attributes.drupal_internal__revision_id
      : null;
    const etag_source = preMergeRevisionId != null ? 'soft_compare' : 'absent';

    let merged;
    let conflicts;
    try {
      const out = mergeAssetFields(existing, incoming);
      merged = out.merged;
      conflicts = out.conflicts;
    } catch (e) {
      if (e instanceof IdentityMutationError) {
        return { kind: 'identity', result: { ok: false, reason: 'identity_mutation', http_status: null, conflicts: [], etag_source: null } };
      }
      throw e;
    }

    if (conflicts.length > 0) {
      return { kind: 'conflict', result: { ok: true, assetId: lookup.assetId, outcome: 'noop', conflicts, etag_source, http_status: null } };
    }

    if (_isMergeNoop(existing, merged)) {
      return { kind: 'noop', result: { ok: true, assetId: lookup.assetId, outcome: 'noop', conflicts: [], etag_source, http_status: null } };
    }

    // Soft-compare guard: re-GET, compare revision_id with preMergeRevisionId.
    if (preMergeRevisionId != null) {
      const reGot = await _getExisting();
      const currentRevisionId = reGot && reGot.attributes && reGot.attributes.drupal_internal__revision_id != null
        ? reGot.attributes.drupal_internal__revision_id
        : null;
      if (currentRevisionId !== preMergeRevisionId) {
        return { kind: 'race' };
      }
    }

    // PATCH path.
    const headers = preMergeRevisionId != null ? { 'If-Match': String(preMergeRevisionId) } : undefined;
    const patchBody = {
      data: {
        type: 'asset--fungi',
        id: lookup.assetId,
        attributes: merged.attributes,
        relationships: merged.relationships,
      },
    };
    const pr = await client.patch('/api/asset/fungi/' + lookup.assetId, patchBody, headers ? { headers } : undefined);
    if (!pr.ok) {
      return { kind: 'patched', result: { ok: false, reason: 'http_' + (pr.status || 'network'), http_status: pr.status, conflicts: [], etag_source } };
    }
    return { kind: 'patched', result: { ok: true, assetId: lookup.assetId, outcome: 'patched', conflicts: [], etag_source, http_status: pr.status } };
  }

  const first = await _attempt();
  if (first.kind !== 'race') return first.result;
  // Retry budget = 1.
  const second = await _attempt();
  if (second.kind !== 'race') return second.result;
  // Still racing -> concurrency_loss.
  return {
    ok: true,
    assetId: lookup.assetId,
    outcome: 'noop',
    reason: 'concurrency_loss',
    conflicts: [],
    etag_source: 'soft_compare',
    http_status: null,
  };
}

// Phase 48 Plan 02: best-effort orphan cleanup after partial commit failure
// in commit-seeding-session. Caller treats non-ok as audit-log-and-continue;
// this primitive never throws.
async function deleteFungiAsset(client, assetId) {
  if (!assetId) return { ok: false, reason: 'missing_asset_id' };
  if (typeof client.delete !== 'function') {
    return { ok: false, reason: 'client_delete_unavailable' };
  }
  const r = await client.delete('/api/asset/fungi/' + assetId);
  if (!r.ok) return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
  // Invalidate the name cache for any entry that points at this id so a
  // subsequent re-commit attempt does not return a stale UUID for a deleted
  // asset. Linear scan is fine (cache is capped at 32).
  for (const [name, id] of NAME_CACHE.entries()) {
    if (id === assetId) NAME_CACHE.delete(name);
  }
  return { ok: true, http_status: r.status };
}

module.exports = {
  findAssetByName,
  createFungiAsset,
  resolveOrCreateAsset,
  deleteFungiAsset,
  _clearCache,
  upsertFungiAsset,
  isStubAsset,
  STUB_BACKFILL_MARKER,
  __test_isMergeNoop: _isMergeNoop,
};
