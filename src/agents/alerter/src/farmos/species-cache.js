'use strict';

// Phase 40 RESEARCH 13: per-process LRU cache (cap 10) for species taxonomy
// term UUIDs. Phase 38 short codes (DT, PE, etc.) are a small fixed vocab.
// Process-local: every container restart probes fresh.

const CACHE = new Map();
const CACHE_MAX = 10;

function _get(code) {
  if (!CACHE.has(code)) return undefined;
  const v = CACHE.get(code);
  CACHE.delete(code);
  CACHE.set(code, v);
  return v;
}
function _set(code, id) {
  if (CACHE.has(code)) CACHE.delete(code);
  CACHE.set(code, id);
  while (CACHE.size > CACHE_MAX) {
    const k = CACHE.keys().next().value;
    CACHE.delete(k);
  }
}
function _clear() { CACHE.clear(); }

async function getSpeciesUuid(client, shortCode) {
  const cached = _get(shortCode);
  if (cached) return { ok: true, uuid: cached, cached: true };
  const enc = encodeURIComponent(shortCode);
  const r = await client.get(`/api/taxonomy_term/species?filter[name][value]=${enc}`);
  if (!r.ok) return { ok: false, reason: 'http_' + (r.status || 'network') };
  const arr = r.body && r.body.data;
  if (!Array.isArray(arr) || arr.length === 0) {
    return { ok: false, reason: 'species_not_found', shortCode };
  }
  const uuid = arr[0].id;
  _set(shortCode, uuid);
  return { ok: true, uuid };
}

module.exports = { getSpeciesUuid, _clear };
