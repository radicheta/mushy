'use strict';

/**
 * Strain resolver: exact-match an extraction strain code against the curated
 * active set (config.strains -- the 14 codes from tenants/mossrock/strains.yaml).
 *
 * Resolution rules (CONTEXT decision 1):
 *  - Match is EXACT and case-normalized (uppercase + trim only; no truncation,
 *    no synonym expansion, no fuzzy auto-remap).
 *  - An unknown code is held for farmer review regardless of edit distance.
 *  - nearestKnown returns a single nearest-neighbor suggestion for DISPLAY ONLY.
 *
 * The resolver takes the curated set as an explicit argument and MUST NOT query
 * farmOS -- matching live farmOS terms would let dev-pollution terms (LIM,
 * SHIITAKE, OYS, CAR) silently pass exact-match (CONTEXT decision 1 rationale).
 */

/**
 * Compute Levenshtein edit distance between two strings.
 * @param {string} a
 * @param {string} b
 * @returns {number}
 */
function levenshtein(a, b) {
  const m = a.length;
  const n = b.length;
  const dp = [];
  for (let i = 0; i <= m; i++) {
    dp[i] = [i];
    for (let j = 1; j <= n; j++) {
      dp[i][j] = i === 0 ? j
        : j === 0 ? i
        : a[i - 1] === b[j - 1]
          ? dp[i - 1][j - 1]
          : 1 + Math.min(dp[i - 1][j - 1], dp[i - 1][j], dp[i][j - 1]);
    }
  }
  return dp[m][n];
}

/**
 * Return the single nearest curated code to the given input by Levenshtein.
 * Tie-break by curatedSet order (first element wins).
 *
 * @param {string} code  - already normalized (uppercase+trimmed) input
 * @param {string[]} curatedSet
 * @returns {string|null}
 */
function nearestKnown(code, curatedSet) {
  if (!curatedSet || curatedSet.length === 0) return null;
  const norm = typeof code === 'string' ? code.toUpperCase().trim() : '';
  let best = null;
  let bestDist = Infinity;
  for (const c of curatedSet) {
    const d = levenshtein(norm, c);
    if (d < bestDist) {
      bestDist = d;
      best = c;
    }
  }
  return best;
}

/**
 * Resolve a strain code against the curated set.
 *
 * @param {*}        code       - extraction output (may be non-string / null)
 * @param {string[]} curatedSet - the 14-code frozen list (e.g. config.strains)
 * @returns {{ known: boolean, code: string|null, nearest?: string }}
 */
function resolveStrain(code, curatedSet) {
  if (code === null || code === undefined || typeof code !== 'string') {
    return { known: false, code: null };
  }
  const norm = code.toUpperCase().trim();
  if (!norm) {
    return { known: false, code: null };
  }
  if (curatedSet && curatedSet.includes(norm)) {
    return { known: true, code: norm };
  }
  const result = { known: false, code: norm };
  if (curatedSet && curatedSet.length > 0) {
    result.nearest = nearestKnown(norm, curatedSet);
  }
  return result;
}

module.exports = { resolveStrain, nearestKnown };
