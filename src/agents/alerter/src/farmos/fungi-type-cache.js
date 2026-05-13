'use strict';

// Phase 40 D-03 ship-gate fix (2026-05-13 dev-smoke): fungi_type is a
// required relationship on asset--fungi (discriminator: batch | block |
// bag | etc; lives in taxonomy_term--fungi_type). Per-process LRU cache
// mirroring species-cache shape.

const CACHE = new Map();
const CACHE_MAX = 16;

function _get(name) {
  if (!CACHE.has(name)) return undefined;
  const v = CACHE.get(name);
  CACHE.delete(name);
  CACHE.set(name, v);
  return v;
}

function _set(name, id) {
  if (CACHE.has(name)) CACHE.delete(name);
  CACHE.set(name, id);
  while (CACHE.size > CACHE_MAX) {
    const k = CACHE.keys().next().value;
    CACHE.delete(k);
  }
}

function _clear() { CACHE.clear(); }

async function getFungiTypeUuid(client, typeName) {
  const cached = _get(typeName);
  if (cached) return { ok: true, uuid: cached, cached: true };
  const enc = encodeURIComponent(typeName);
  const r = await client.get(`/api/taxonomy_term/fungi_type?filter[name][value]=${enc}`);
  if (!r.ok) {
    if (r.status === 404) return { ok: false, reason: 'fungi_type_taxonomy_missing' };
    return { ok: false, reason: 'http_' + (r.status || 'network') };
  }
  const arr = r.body && r.body.data;
  if (!Array.isArray(arr) || arr.length === 0) {
    return { ok: false, reason: 'fungi_type_not_found', typeName };
  }
  const uuid = arr[0].id;
  _set(typeName, uuid);
  return { ok: true, uuid };
}

module.exports = { getFungiTypeUuid, _clear };
