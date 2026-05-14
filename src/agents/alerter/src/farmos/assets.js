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

const NAME_CACHE = new Map(); // name -> assetId; capped at 32
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

async function createFungiAsset(client, opts) {
  const {
    name,
    parentIds = [],
    fungiTypeName = null,
    fungiXingName = null,
    draftId,
    qrCodes = [],
    notes = null,
  } = opts;
  if (!fungiTypeName) return { ok: false, reason: 'missing_fungi_type_name' };
  if (!fungiXingName) return { ok: false, reason: 'missing_fungi_xing_name' };
  const ft = await fungiTypeCache.getFungiTypeUuid(client, fungiTypeName);
  if (!ft.ok) return { ok: false, reason: ft.reason, fungiTypeName };
  const fx = await fungiXingCache.getFungiXingUuid(client, fungiXingName);
  if (!fx.ok) return { ok: false, reason: fx.reason, fungiXingName };
  const noteTrailer = (notes ? notes + '\n' : '') + 'mushy:draft:' + draftId;
  const payload = {
    data: {
      type: 'asset--fungi',
      attributes: {
        name,
        status: 'active',
        notes: { value: noteTrailer, format: 'plain_text' },
      },
    },
  };
  const relationships = {
    fungi_type: { data: [{ type: 'taxonomy_term--fungi_type', id: ft.uuid }] },
    fungi_xing: { data: [{ type: 'taxonomy_term--fungi_xing', id: fx.uuid }] },
  };
  if (parentIds.length > 0) {
    relationships.parent = { data: parentIds.map((id) => ({ type: 'asset--fungi', id })) };
  }
  payload.data.relationships = relationships;
  if (qrCodes.length > 0) {
    qr.bindQrOnCreate(payload, qrCodes);
  }
  const r = await client.post('/api/asset/fungi', payload);
  if (!r.ok) {
    return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
  }
  const assetId = r.body && r.body.data && r.body.data.id;
  if (!assetId) {
    return { ok: false, reason: 'no_asset_id_in_response' };
  }
  _cacheSet(name, assetId);
  return { ok: true, assetId, qrBindings: [], http_status: r.status };
}

async function resolveOrCreateAsset(client, opts) {
  const lookup = await findAssetByName(client, opts.name);
  if (lookup.found) return { ok: true, assetId: lookup.assetId, reused: true };
  return createFungiAsset(client, opts);
}

module.exports = { findAssetByName, createFungiAsset, resolveOrCreateAsset, _clearCache };
