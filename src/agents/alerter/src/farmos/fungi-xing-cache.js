'use strict';

// Phase 40 (Option A hybrid, 2026-05-14): fungi_xing is a required term
// reference on asset--fungi carrying the structural classifier
// (block | fruit; lives in taxonomy_term--fungi_xing). Per-process LRU
// cache mirroring fungi-type-cache shape.
//
// 'batch' is intentionally NOT a fungi_xing value -- pre-inoc substrates
// live in the material bundle or as pasteurization logs, not as fungi
// assets. See .planning/notes/2026-05-14-reply-from-farmos-fungi-schema.md.

const CACHE = new Map();
const CACHE_MAX = 4;

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

async function getFungiXingUuid(client, xingName) {
  const cached = _get(xingName);
  if (cached) return { ok: true, uuid: cached, cached: true };
  const enc = encodeURIComponent(xingName);
  const r = await client.get(`/api/taxonomy_term/fungi_xing?filter[name][value]=${enc}`);
  if (!r.ok) {
    if (r.status === 404) return { ok: false, reason: 'fungi_xing_taxonomy_missing' };
    return { ok: false, reason: 'http_' + (r.status || 'network') };
  }
  const arr = r.body && r.body.data;
  if (!Array.isArray(arr) || arr.length === 0) {
    return { ok: false, reason: 'fungi_xing_not_found', xingName };
  }
  const uuid = arr[0].id;
  _set(xingName, uuid);
  return { ok: true, uuid };
}

module.exports = { getFungiXingUuid, _clear };
