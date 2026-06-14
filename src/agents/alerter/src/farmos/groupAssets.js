'use strict';

// Phase 52 Plan 01: asset--group primitives for session-entity preflight.
//
// asset--group is the stock farmOS farm_group bundle enabled on dev + prod
// (farmos commit 1857037). It carries name + status + notes; NO taxonomy
// terms, NO parent edge, NO QR. Membership lives on log--activity with
// is_group_assignment=true (see activityLogs.js), NOT on this asset.
//
// upsertGroupAsset is lookup-or-create only. NO merge layer in v1.10.1 --
// same-name hit returns the existing UUID with outcome='reused' (per
// 52-CONTEXT.md decisions). Phase 51's PATCH-merge layer is intentionally
// out of scope for asset--group in this phase.

const NAME_CACHE = new Map(); // name -> assetId; capped at 32 (LRU)
const NAME_CACHE_MAX = 32;

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

async function findGroupAssetByName(client, name) {
  const cached = _cacheGet(name);
  if (cached) return { found: true, assetId: cached, cached: true };
  const enc = encodeURIComponent(name);
  const r = await client.get(`/api/asset/group?filter[name][value]=${enc}`);
  if (!r.ok) return { found: false, error: 'http_' + (r.status || 'network') };
  const arr = r.body && r.body.data;
  if (Array.isArray(arr) && arr.length > 0) {
    const id = arr[0].id;
    _cacheSet(name, id);
    return { found: true, assetId: id };
  }
  return { found: false };
}

async function upsertGroupAsset(client, opts) {
  const { name, draftId, notes } = opts || {};
  const lookup = await findGroupAssetByName(client, name);
  if (lookup.found) {
    return { ok: true, assetId: lookup.assetId, outcome: 'reused', http_status: null };
  }
  const noteTrailer = (notes ? notes + '\n' : '') + 'mushy:draft:' + draftId;
  const payload = {
    data: {
      type: 'asset--group',
      attributes: {
        name,
        status: 'active',
        notes: { value: noteTrailer, format: 'plain_text' },
      },
    },
  };
  const r = await client.post('/api/asset/group', payload);
  if (!r.ok) {
    return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
  }
  const assetId = r.body && r.body.data && r.body.data.id;
  if (!assetId) {
    return { ok: false, reason: 'no_asset_id_in_response', http_status: r.status };
  }
  _cacheSet(name, assetId);
  return { ok: true, assetId, outcome: 'created', http_status: r.status };
}

async function deleteGroupAsset(client, assetId) {
  if (!assetId) return { ok: false, reason: 'missing_asset_id' };
  if (typeof client.delete !== 'function') {
    return { ok: false, reason: 'client_delete_unavailable' };
  }
  const r = await client.delete('/api/asset/group/' + assetId);
  if (!r.ok) return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
  // Invalidate cache entries pointing at this id.
  for (const [name, id] of NAME_CACHE.entries()) {
    if (id === assetId) NAME_CACHE.delete(name);
  }
  return { ok: true, http_status: r.status };
}

// NOTE (Phase 55B, 2026-06-14): patchGroupAssetFiles (PATCH relationships.file) was
// REMOVED. The A1 design (upload file--file UUID, then PATCH it onto the group's `file`
// edge) was falsified live: this farmOS has no octet-stream route at /api/file/file, and
// the `file` field rejects images anyway. Page photos now use the field-scoped binary
// route on the `image` field (files.uploadFieldAttachments), which creates + links in one
// call. See memory project_farmos_image_upload_needs_field_scoped_route.

module.exports = {
  findGroupAssetByName,
  upsertGroupAsset,
  deleteGroupAsset,
  _clearCache,
};
