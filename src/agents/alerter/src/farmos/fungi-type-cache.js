'use strict';

// Phase 40 (Option A hybrid, re-locked 2026-05-14): fungi_type is a
// required relationship on asset--fungi carrying the STRAIN CODE
// (SHI, SH2, KOY, MAI, ...; lives in taxonomy_term--fungi_type). Matches
// upstream farm_fungi {bundle}_type convention. The structural
// classifier (block | fruit) lives in fungi_xing instead -- see
// fungi-xing-cache.js. Per-process LRU cache.
//
// Earlier shape (2026-05-13 dev-smoke ship-gate fix) treated fungi_type
// as the batch/block/bag classifier; superseded by the hybrid lock.

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
