'use strict';

// Phase 41 Plan 07 Task 3: compare-runs CLI unit tests.

const fs = require('fs');
const path = require('path');
const os = require('os');
const { compare } = require('./compare-runs');

function tmpJsonl(rows) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cmp-'));
  const p = path.join(dir, 'r.jsonl');
  fs.writeFileSync(p, rows.map((r) => JSON.stringify(r)).join('\n') + '\n');
  return p;
}

const silent = { info: () => {}, warn: () => {}, error: () => {} };

describe('compare-runs', () => {
  test('no regressions -> regressions=0', () => {
    const older = tmpJsonl([
      { fixture_id: 'a', actual: { ok: true } },
      { fixture_id: 'b', actual: { ok: true } },
    ]);
    const newer = tmpJsonl([
      { fixture_id: 'a', actual: { ok: true } },
      { fixture_id: 'b', actual: { ok: true } },
    ]);
    const { regressions } = compare(older, newer, { logger: silent });
    expect(regressions).toBe(0);
  });

  test('PASS->FAIL transition -> regressions=1', () => {
    const older = tmpJsonl([{ fixture_id: 'a', actual: { ok: true } }]);
    const newer = tmpJsonl([{ fixture_id: 'a', actual: { ok: false } }]);
    const { regressions, rows } = compare(older, newer, { logger: silent });
    expect(regressions).toBe(1);
    expect(rows[0].status).toBe('REGRESSION');
  });

  test('new fixture in newer is informational, not a regression', () => {
    const older = tmpJsonl([{ fixture_id: 'a', actual: { ok: true } }]);
    const newer = tmpJsonl([
      { fixture_id: 'a', actual: { ok: true } },
      { fixture_id: 'b', actual: { ok: true } },
    ]);
    const { regressions, rows } = compare(older, newer, { logger: silent });
    expect(regressions).toBe(0);
    expect(rows.find((r) => r.fixture_id === 'b').status).toBe('NEW');
  });

  test('removed fixture is informational, not a regression', () => {
    const older = tmpJsonl([
      { fixture_id: 'a', actual: { ok: true } },
      { fixture_id: 'b', actual: { ok: true } },
    ]);
    const newer = tmpJsonl([{ fixture_id: 'a', actual: { ok: true } }]);
    const { regressions, rows } = compare(older, newer, { logger: silent });
    expect(regressions).toBe(0);
    expect(rows.find((r) => r.fixture_id === 'b').status).toBe('REMOVED');
  });

  test('bad JSONL throws (caller maps to exit 2)', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cmp-bad-'));
    const p = path.join(dir, 'bad.jsonl');
    fs.writeFileSync(p, 'not-json\n');
    const ok = tmpJsonl([{ fixture_id: 'a', actual: { ok: true } }]);
    expect(() => compare(p, ok, { logger: silent })).toThrow(/bad JSON/);
  });
});
