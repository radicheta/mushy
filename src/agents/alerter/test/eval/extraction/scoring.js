'use strict';

// Phase 38 Plan 07 Task 1: Scoring helpers for the D-07 ship-gate eval harness.
//
// Inputs everywhere are arrays of `{fixture, actual}` entries where:
//   - fixture.expected: {type, fields, ambiguous?, requiredFields?}
//   - actual: extractor result -- {ok, draft, per_field_confidence, ...} or {ok:false}
//
// Bar (per CONTEXT D-07): schemaConformance >= 0.90 AND requiredFieldOrAppropriateAskBack >= 0.75.

const { BLOCK_NAME_RE } = require('../../../src/extraction/schemas/seeding');

// 1. Schema conformance: fraction of results whose draft validates against Draft (via Submission wrapper applied at extract time).
function schemaConformance(results) {
  if (!results.length) return 0;
  let pass = 0;
  for (const r of results) {
    if (r.actual && r.actual.ok === true && r.actual.draft) pass += 1;
  }
  return pass / results.length;
}

// 2. Per-required-field exact-match.
// Per-fixture: count required fields, count matched. Aggregate = sum(matched) / sum(required).
function exactFieldMatch(results) {
  let totalReq = 0;
  let matched = 0;
  const perField = {}; // {fieldName: {match, total}}
  for (const r of results) {
    const exp = r.fixture && r.fixture.expected;
    if (!exp || !exp.fields) continue;
    const required = exp.requiredFields || Object.keys(exp.fields);
    const draft = (r.actual && r.actual.ok && r.actual.draft) || {};
    for (const f of required) {
      totalReq += 1;
      perField[f] = perField[f] || { match: 0, total: 0 };
      perField[f].total += 1;
      if (fieldEquals(draft[f], exp.fields[f])) {
        matched += 1;
        perField[f].match += 1;
      }
    }
  }
  return {
    aggregate: totalReq === 0 ? 0 : matched / totalReq,
    perField,
    totalReq,
    matched,
  };
}

function fieldEquals(a, b) {
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  if (typeof a === 'string' && typeof b === 'string') {
    return a.trim().toLowerCase() === b.trim().toLowerCase();
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    const sa = [...a].sort();
    const sb = [...b].sort();
    return sa.length === sb.length && sa.every((v, i) => v === sb[i]);
  }
  return a === b;
}

// 3. Appropriate ask-back:
//   - expected.ambiguous true  + actual produced ask-back signal => 1
//   - expected.ambiguous false + actual produced concrete draft (ok=true)  => 1
//   - otherwise => 0
// In Phase 38 the extractor itself doesn't ask-back -- the state machine does
// downstream. As a stand-in here we treat "ok:false with reason in (schema_invalid, low_confidence)"
// OR "per_field_confidence has any field < 0.7" as an ask-back signal.
function isAskBack(actual) {
  if (!actual) return false;
  if (actual.ok === false) return false; // hard failure, not an ask-back
  if (actual.ok === true && actual.per_field_confidence) {
    for (const v of Object.values(actual.per_field_confidence)) {
      if (typeof v === 'number' && v < 0.7) return true;
    }
  }
  return false;
}

function appropriateAskBack(results) {
  if (!results.length) return 0;
  let pass = 0;
  for (const r of results) {
    const ambiguous = !!(r.fixture && r.fixture.expected && r.fixture.expected.ambiguous);
    const askBack = isAskBack(r.actual);
    const concreteOk = r.actual && r.actual.ok === true && !askBack;
    if (ambiguous && askBack) pass += 1;
    else if (!ambiguous && concreteOk) pass += 1;
  }
  return pass / results.length;
}

// 4. Set-equality on harvest source_block_refs (multi-parent lineage).
function setEqualityArrays(actualRefs, expectedRefs) {
  if (!Array.isArray(actualRefs) || !Array.isArray(expectedRefs)) return 0;
  const a = [...actualRefs].map(String).sort();
  const b = [...expectedRefs].map(String).sort();
  if (a.length !== b.length) return 0;
  return a.every((v, i) => v === b[i]) ? 1 : 0;
}

function setEquality(results) {
  // Filter to harvest fixtures with expected.fields.source_block_refs.
  const relevant = results.filter((r) =>
    r.fixture && r.fixture.expected &&
    r.fixture.expected.type === 'harvest' &&
    Array.isArray(r.fixture.expected.fields && r.fixture.expected.fields.source_block_refs),
  );
  if (!relevant.length) return { aggregate: null, count: 0 };
  let pass = 0;
  for (const r of relevant) {
    const actualRefs = (r.actual && r.actual.ok && r.actual.draft && r.actual.draft.source_block_refs) || [];
    pass += setEqualityArrays(actualRefs, r.fixture.expected.fields.source_block_refs);
  }
  return { aggregate: pass / relevant.length, count: relevant.length };
}

// 5. B5 block_name precision/recall.
function b5PrecisionRecall(results) {
  // For each fixture with expected.fields.block_name:
  //   - if actual extracted a regex-valid block_name -> 'extracted'
  //   - if it matches expected -> 'correct'
  let extracted = 0;
  let expectedTotal = 0;
  let correct = 0;
  for (const r of results) {
    const expBlock = r.fixture && r.fixture.expected && r.fixture.expected.fields && r.fixture.expected.fields.block_name;
    const actBlock = r.actual && r.actual.ok && r.actual.draft && r.actual.draft.block_name;
    if (expBlock) expectedTotal += 1;
    if (actBlock && BLOCK_NAME_RE.test(actBlock)) {
      extracted += 1;
      if (expBlock && actBlock.toLowerCase() === String(expBlock).toLowerCase()) correct += 1;
    }
  }
  const precision = extracted === 0 ? 0 : correct / extracted;
  const recall = expectedTotal === 0 ? 0 : correct / expectedTotal;
  return { precision, recall, extracted, correct, expected: expectedTotal };
}

// 6. Brier score: mean( (confidence - correct)^2 ) across (confidence, correct?) pairs.
function brierScorePairs(pairs) {
  if (!pairs.length) return 0;
  let sum = 0;
  for (const [conf, correct] of pairs) {
    const c = correct ? 1 : 0;
    sum += (conf - c) ** 2;
  }
  return sum / pairs.length;
}

function pairsFromResults(results) {
  const pairs = [];
  for (const r of results) {
    if (!r.actual || !r.actual.ok || !r.actual.per_field_confidence) continue;
    const exp = r.fixture && r.fixture.expected && r.fixture.expected.fields;
    if (!exp) continue;
    const required = (r.fixture.expected.requiredFields) || Object.keys(exp);
    for (const f of required) {
      const conf = r.actual.per_field_confidence[f];
      if (typeof conf !== 'number') continue;
      const draftVal = r.actual.draft && r.actual.draft[f];
      const correct = fieldEquals(draftVal, exp[f]);
      pairs.push([conf, correct]);
    }
  }
  return pairs;
}

function brierScore(results) {
  return brierScorePairs(pairsFromResults(results));
}

// 7. Expected Calibration Error.
function ecePairs(pairs, bins = 10) {
  if (!pairs.length) return 0;
  const buckets = Array.from({ length: bins }, () => ({ n: 0, accSum: 0, confSum: 0 }));
  for (const [conf, correct] of pairs) {
    let idx = Math.floor(conf * bins);
    if (idx >= bins) idx = bins - 1;
    if (idx < 0) idx = 0;
    buckets[idx].n += 1;
    buckets[idx].accSum += correct ? 1 : 0;
    buckets[idx].confSum += conf;
  }
  let ece = 0;
  const N = pairs.length;
  for (const b of buckets) {
    if (b.n === 0) continue;
    const acc = b.accSum / b.n;
    const conf = b.confSum / b.n;
    ece += (b.n / N) * Math.abs(acc - conf);
  }
  return ece;
}

function ece(results, bins = 10) {
  return ecePairs(pairsFromResults(results), bins);
}

// 8. Combined: per-fixture, did we exact-match required fields OR appropriately ask-back?
function combinedFieldOrAskBack(results) {
  if (!results.length) return 0;
  let pass = 0;
  for (const r of results) {
    const exp = r.fixture && r.fixture.expected;
    if (!exp) continue;
    const ambiguous = !!exp.ambiguous;
    const askBack = isAskBack(r.actual);
    if (ambiguous && askBack) {
      pass += 1;
      continue;
    }
    if (!exp.fields) {
      // No expected fields and not ambiguous -- count schema-valid as pass.
      if (r.actual && r.actual.ok === true) pass += 1;
      continue;
    }
    const required = exp.requiredFields || Object.keys(exp.fields);
    if (!r.actual || !r.actual.ok || !r.actual.draft) continue;
    const draft = r.actual.draft;
    let allMatch = true;
    for (const f of required) {
      if (!fieldEquals(draft[f], exp.fields[f])) {
        allMatch = false;
        break;
      }
    }
    if (allMatch) pass += 1;
  }
  return pass / results.length;
}

module.exports = {
  schemaConformance,
  exactFieldMatch,
  appropriateAskBack,
  setEquality,
  setEqualityArrays,
  b5PrecisionRecall,
  brierScore,
  brierScorePairs,
  ece,
  ecePairs,
  combinedFieldOrAskBack,
  isAskBack,
  fieldEquals,
};
