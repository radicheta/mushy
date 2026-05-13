'use strict';

// Phase 41 Plan 06 Task 2: unit tests for cross-stream scorer.

const {
  crossStreamConsistency,
  deepEqualModWhitespace,
  normalizeString,
  describeDifference,
} = require('./cross-stream');

function makeResult(fixture_id, session_id, kind, draft) {
  return {
    fixture_id,
    kind,
    session_id,
    expected: { session_id, type: 'seeding', requiredFields: [], fields: {}, ambiguous: false },
    actual: { ok: true, draft, per_field_confidence: {} },
  };
}

describe('cross-stream consistency', () => {
  test('empty results -> aggregate 0, totalPairs 0', () => {
    const r = crossStreamConsistency([]);
    expect(r).toEqual({ aggregate: 0, totalPairs: 0, identicalPairs: 0, divergences: [] });
  });

  test('single fixture in a session is skipped (no pair)', () => {
    const r = crossStreamConsistency([makeResult('a', 's1', 'synthetic', { x: 1 })]);
    expect(r.totalPairs).toBe(0);
  });

  test('two fixtures with identical drafts mod whitespace -> aggregate 1.0', () => {
    const r = crossStreamConsistency([
      makeResult('a', 's1', 'synthetic', { name: ' Hello World ' }),
      makeResult('b', 's1', 'paper-log', { name: 'hello   world' }),
    ]);
    expect(r.identicalPairs).toBe(1);
    expect(r.totalPairs).toBe(1);
    expect(r.aggregate).toBe(1.0);
  });

  test('two fixtures differing block_name -> divergence captured', () => {
    const r = crossStreamConsistency([
      makeResult('a', 's2', 'synthetic', { block_name: '260513_SHI_4' }),
      makeResult('b', 's2', 'paper-log', { block_name: '260513_SHI_5' }),
    ]);
    expect(r.identicalPairs).toBe(0);
    expect(r.divergences.length).toBe(1);
    expect(r.divergences[0].session_id).toBe('s2');
    expect(r.divergences[0].diff[0].path).toBe('block_name');
  });

  test('ignore keys: id, source_capture_ids, per_field_confidence, ts', () => {
    const r = crossStreamConsistency([
      makeResult('a', 's3', 'synthetic', { name: 'x', id: 'A', source_capture_ids: [1], per_field_confidence: { x: 0.9 }, ts: 'old' }),
      makeResult('b', 's3', 'paper-log', { name: 'x', id: 'B', source_capture_ids: [2], per_field_confidence: { x: 0.5 }, ts: 'new' }),
    ]);
    expect(r.identicalPairs).toBe(1);
  });

  test('whitespace-only string difference is equal', () => {
    expect(deepEqualModWhitespace('a b', 'a   b')).toBe(true);
    expect(deepEqualModWhitespace('A', 'a ')).toBe(true);
  });

  test('three fixtures in same session -> 3 pairs evaluated', () => {
    const r = crossStreamConsistency([
      makeResult('a', 's4', 'synthetic', { x: 1 }),
      makeResult('b', 's4', 'paper-log', { x: 1 }),
      makeResult('c', 's4', 'audio', { x: 1 }),
    ]);
    expect(r.totalPairs).toBe(3);
    expect(r.identicalPairs).toBe(3);
  });

  test('normalizeString handles tabs, newlines, double-spaces, mixed case', () => {
    expect(normalizeString('  Hello\tWorld\n  ')).toBe('hello world');
    expect(normalizeString('A  B  C')).toBe('a b c');
  });

  test('describeDifference returns first differing path', () => {
    const diffs = describeDifference({ a: 1, b: 2 }, { a: 1, b: 3 });
    expect(diffs.length).toBe(1);
    expect(diffs[0].path).toBe('b');
  });
});
