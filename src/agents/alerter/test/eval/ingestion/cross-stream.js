'use strict';

// Phase 41 Plan 06 Task 1: cross-stream consistency scorer.
//
// Cites CONTEXT D-05 (paired fixtures grouped by session_id), D-05a (>=2
// paired sessions), D-05b (ship-gate >= 1/2 paired sessions PASS). Phase 38
// scoring.js is INTENTIONALLY untouched (CONTEXT D-01b reuse rule); cross-
// stream is a new dimension that lives here, not in extraction/scoring.js.
//
// deepEqualModWhitespace normalizes string fields via trim + whitespace
// collapse + lowercase, and ignores: id, source_capture_ids,
// per_field_confidence, ts. crossStreamConsistency groups by session_id and
// pair-wise compares within each session.

const IGNORE_KEYS = new Set(['id', 'source_capture_ids', 'per_field_confidence', 'ts']);

function normalizeString(s) {
  return String(s).trim().replace(/\s+/g, ' ').toLowerCase();
}

function deepEqualModWhitespace(a, b) {
  if (a === b) return true;
  if (a == null || b == null) return a == b;
  if (typeof a !== typeof b) {
    // tolerate number-string parity for fields like qty
    if ((typeof a === 'number' && typeof b === 'string') || (typeof a === 'string' && typeof b === 'number')) {
      return String(a) === String(b);
    }
    return false;
  }
  if (typeof a === 'string') return normalizeString(a) === normalizeString(b);
  if (typeof a === 'number' || typeof a === 'boolean') return a === b;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i += 1) {
      if (!deepEqualModWhitespace(a[i], b[i])) return false;
    }
    return true;
  }
  if (typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a).filter((k) => !IGNORE_KEYS.has(k)).sort();
    const kb = Object.keys(b).filter((k) => !IGNORE_KEYS.has(k)).sort();
    if (ka.length !== kb.length) return false;
    for (let i = 0; i < ka.length; i += 1) {
      if (ka[i] !== kb[i]) return false;
    }
    return ka.every((k) => deepEqualModWhitespace(a[k], b[k]));
  }
  return false;
}

function describeDifference(a, b, pathPrefix = '') {
  // Walks objects until first disagreement; returns [{path, a, b}] (one entry
  // per top-level differing field, recursive into objects).
  const out = [];
  if (deepEqualModWhitespace(a, b)) return out;
  if (a == null || b == null || typeof a !== typeof b
      || typeof a !== 'object' || Array.isArray(a) !== Array.isArray(b)) {
    out.push({ path: pathPrefix || '<root>', a, b });
    return out;
  }
  if (Array.isArray(a)) {
    if (a.length !== b.length) {
      out.push({ path: pathPrefix || '<root>', a: `len=${a.length}`, b: `len=${b.length}` });
      return out;
    }
    for (let i = 0; i < a.length; i += 1) {
      const sub = describeDifference(a[i], b[i], `${pathPrefix}[${i}]`);
      for (const s of sub) out.push(s);
    }
    return out;
  }
  const allKeys = new Set([
    ...Object.keys(a).filter((k) => !IGNORE_KEYS.has(k)),
    ...Object.keys(b).filter((k) => !IGNORE_KEYS.has(k)),
  ]);
  for (const k of allKeys) {
    const p = pathPrefix ? `${pathPrefix}.${k}` : k;
    if (!(k in a) || !(k in b)) {
      out.push({ path: p, a: a[k], b: b[k] });
    } else if (!deepEqualModWhitespace(a[k], b[k])) {
      const sub = describeDifference(a[k], b[k], p);
      for (const s of sub) out.push(s);
    }
  }
  return out;
}

function crossStreamConsistency(results) {
  const groups = new Map();
  for (const r of results || []) {
    const sid = r && ((r.expected && r.expected.session_id) || r.session_id);
    if (!sid) continue;
    if (!groups.has(sid)) groups.set(sid, []);
    groups.get(sid).push(r);
  }
  let totalPairs = 0;
  let identicalPairs = 0;
  const divergences = [];
  for (const [sid, group] of groups) {
    if (group.length < 2) continue;
    for (let i = 0; i < group.length; i += 1) {
      for (let j = i + 1; j < group.length; j += 1) {
        totalPairs += 1;
        const a = group[i].actual && group[i].actual.draft;
        const b = group[j].actual && group[j].actual.draft;
        if (deepEqualModWhitespace(a, b)) {
          identicalPairs += 1;
        } else {
          divergences.push({
            session_id: sid,
            kind_a: group[i].kind,
            kind_b: group[j].kind,
            fixture_a: group[i].fixture_id,
            fixture_b: group[j].fixture_id,
            diff: describeDifference(a, b),
          });
        }
      }
    }
  }
  return {
    aggregate: totalPairs === 0 ? 0 : identicalPairs / totalPairs,
    totalPairs,
    identicalPairs,
    divergences,
  };
}

module.exports = {
  crossStreamConsistency,
  deepEqualModWhitespace,
  normalizeString,
  describeDifference,
};
