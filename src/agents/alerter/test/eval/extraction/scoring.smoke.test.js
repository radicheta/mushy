'use strict';

// Phase 38 Plan 07 Task 1: Smoke tests for the scoring lib.
// Synthetic inputs only -- no Anthropic calls.

const scoring = require('./scoring');

describe('scoring smoke -- brier', () => {
  test('classic Brier on [(0.8,1),(0.5,0)] = (0.04 + 0.25) / 2 = 0.145', () => {
    const v = scoring.brierScorePairs([[0.8, 1], [0.5, 0]]);
    expect(v).toBeCloseTo(0.145, 6);
  });

  test('perfect confidence = 0', () => {
    expect(scoring.brierScorePairs([[1, 1], [0, 0]])).toBe(0);
  });

  test('empty pairs = 0', () => {
    expect(scoring.brierScorePairs([])).toBe(0);
  });
});

describe('scoring smoke -- ece', () => {
  test('uniformly-correct predictions at conf 0.9 give ECE ~ 0.1', () => {
    const pairs = Array.from({ length: 100 }, () => [0.9, 1]);
    expect(scoring.ecePairs(pairs, 10)).toBeCloseTo(0.1, 4);
  });

  test('perfect calibration ECE = 0', () => {
    const pairs = [[1, 1], [1, 1], [0, 0], [0, 0]];
    expect(scoring.ecePairs(pairs, 10)).toBe(0);
  });
});

describe('scoring smoke -- setEquality', () => {
  test('permutation invariant', () => {
    expect(scoring.setEqualityArrays(['a', 'b', 'c'], ['c', 'a', 'b'])).toBe(1);
  });
  test('different lengths fail', () => {
    expect(scoring.setEqualityArrays(['a', 'b'], ['a', 'b', 'c'])).toBe(0);
  });
  test('mismatch fails', () => {
    expect(scoring.setEqualityArrays(['a', 'b'], ['a', 'c'])).toBe(0);
  });
});

describe('scoring smoke -- b5PrecisionRecall', () => {
  test('all extracted match expected = precision 1, recall 1', () => {
    const results = [
      { fixture: { expected: { fields: { block_name: '250201_CAS_1' } } }, actual: { ok: true, draft: { block_name: '250201_CAS_1' } } },
      { fixture: { expected: { fields: { block_name: '250201_LIM_3' } } }, actual: { ok: true, draft: { block_name: '250201_LIM_3' } } },
    ];
    const v = scoring.b5PrecisionRecall(results);
    expect(v.precision).toBe(1);
    expect(v.recall).toBe(1);
  });
  test('regex-invalid extractions don\'t count as extracted', () => {
    const results = [
      { fixture: { expected: { fields: { block_name: '250201_CAS_1' } } }, actual: { ok: true, draft: { block_name: 'gibberish' } } },
    ];
    const v = scoring.b5PrecisionRecall(results);
    expect(v.extracted).toBe(0);
    expect(v.precision).toBe(0);
    expect(v.recall).toBe(0);
  });
});

describe('scoring smoke -- fieldEquals', () => {
  test('case-insensitive string match', () => {
    expect(scoring.fieldEquals('CAS', 'cas')).toBe(true);
  });
  test('array set-equality', () => {
    expect(scoring.fieldEquals(['a', 'b'], ['b', 'a'])).toBe(true);
  });
});

describe('scoring smoke -- combinedFieldOrAskBack', () => {
  test('ambiguous + askback = pass', () => {
    const results = [{
      fixture: { expected: { ambiguous: true, fields: { species: 'CAS' }, requiredFields: ['species'] } },
      actual: { ok: true, draft: { species: 'OTHER' }, per_field_confidence: { species: 0.3 } },
    }];
    expect(scoring.combinedFieldOrAskBack(results)).toBe(1);
  });
  test('non-ambiguous + exact-match = pass', () => {
    const results = [{
      fixture: { expected: { ambiguous: false, fields: { species: 'CAS' }, requiredFields: ['species'] } },
      actual: { ok: true, draft: { species: 'CAS' }, per_field_confidence: { species: 0.9 } },
    }];
    expect(scoring.combinedFieldOrAskBack(results)).toBe(1);
  });
  test('non-ambiguous + miss = fail', () => {
    const results = [{
      fixture: { expected: { ambiguous: false, fields: { species: 'CAS' }, requiredFields: ['species'] } },
      actual: { ok: true, draft: { species: 'WRONG' }, per_field_confidence: { species: 0.9 } },
    }];
    expect(scoring.combinedFieldOrAskBack(results)).toBe(0);
  });
});
