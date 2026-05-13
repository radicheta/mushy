'use strict';

// Phase 40 D-03 / D-03a / D-03b: fungi asset creation primitives (B1..B4).
// Single createFungiAsset shape; lazy QR-bind dispatch via probeAssetLinkModule.
// Module-level LRU cache for BATCH-* name resolution (resolveOrCreateAsset).

const qr = require('./qr');

const NAME_CACHE = new Map(); // name -> assetId; capped at 32
const NAME_CACHE_MAX = 32;

function _cacheGet(name) {
  if (!NAME_CACHE.has(name)) return undefined;
  const v = NAME_CACHE.get(name);
  // touch (LRU)
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
  const { name, parentIds = [], speciesUuid = null, draftId, qrCodes = [], notes = null } = opts;
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
  const relationships = {};
  if (parentIds.length > 0) {
    relationships.parent = { data: parentIds.map((id) => ({ type: 'asset--fungi', id })) };
  }
  if (speciesUuid) {
    relationships.species = { data: [{ type: 'taxonomy_term--species', id: speciesUuid }] };
  }
  if (Object.keys(relationships).length > 0) {
    payload.data.relationships = relationships;
  }
  const present = await client.probeAssetLinkModule();
  if (!present && qrCodes.length > 0) {
    qr.bindQrOnCreate(payload, qrCodes, { fallback: true });
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
  let qrBindings = [];
  if (present && qrCodes.length > 0) {
    const br = await qr.bindQrPostCreate(client, assetId, qrCodes);
    qrBindings = br.bindings;
  }
  return { ok: true, assetId, qrBindings, http_status: r.status };
}

async function resolveOrCreateAsset(client, opts) {
  const lookup = await findAssetByName(client, opts.name);
  if (lookup.found) return { ok: true, assetId: lookup.assetId, reused: true };
  return createFungiAsset(client, opts);
}

module.exports = { findAssetByName, createFungiAsset, resolveOrCreateAsset, _clearCache };
