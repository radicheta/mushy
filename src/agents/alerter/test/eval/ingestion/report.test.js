'use strict';

// Phase 41 Plan 07 Task 3: report writer unit tests.

const fs = require('fs');
const path = require('path');
const os = require('os');
const { writeIngestReport, shipGateVerdict } = require('./report');

function makeSummary({ synthOk = 25, synthTotal = 25, paper = null, audio = null, crossStream = null } = {}) {
  const results = (n, ok) => {
    const out = [];
    for (let i = 0; i < n; i += 1) {
      out.push({ fixture_id: `f${i}`, kind: 'synthetic', expected: { type: 'seeding' }, actual: { ok: i < ok, draft: {} } });
    }
    return out;
  };
  const summary = {
    byCorpus: {
      synthetic: { fixtureCount: synthTotal, results: results(synthTotal, synthOk), costUsd: 0, errors: 0, skipped: 0 },
    },
    crossStream: crossStream || null,
    totalCostUsd: 0,
    runId: 'test',
    mode: 'mock',
    smoke: false,
  };
  if (paper) summary.byCorpus['paper-log'] = paper;
  if (audio) summary.byCorpus.audio = audio;
  return summary;
}

describe('writeIngestReport', () => {
  test('synthetic-only PASS writes Verdict [PASS]', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rep-'));
    const p = path.join(dir, 'r.md');
    const v = writeIngestReport(p, makeSummary({ synthOk: 25, synthTotal: 25 }));
    expect(v).toBe('PASS');
    const text = fs.readFileSync(p, 'utf8');
    expect(text).toMatch(/^## Verdict: \[PASS\]$/m);
  });

  test('synthetic < 90% writes Verdict [FAIL]', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rep-'));
    const p = path.join(dir, 'r.md');
    const v = writeIngestReport(p, makeSummary({ synthOk: 10, synthTotal: 25 }));
    expect(v).toBe('FAIL');
    const text = fs.readFileSync(p, 'utf8');
    expect(text).toMatch(/^## Verdict: \[FAIL\]$/m);
  });

  test('audio section prints human_needed when corpus empty', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rep-'));
    const p = path.join(dir, 'r.md');
    writeIngestReport(p, makeSummary({ audio: { fixtureCount: 0, results: [] } }));
    const text = fs.readFileSync(p, 'utf8');
    expect(text).toMatch(/human_needed.*section 4/);
  });

  test('cross-stream section prints human_needed when totalPairs == 0', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rep-'));
    const p = path.join(dir, 'r.md');
    writeIngestReport(p, makeSummary({ crossStream: { aggregate: 0, totalPairs: 0, identicalPairs: 0, divergences: [] } }));
    const text = fs.readFileSync(p, 'utf8');
    expect(text).toMatch(/human_needed.*section 5/);
  });

  test('per-run unique paths (two consecutive calls produce two files)', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rep-'));
    const p1 = path.join(dir, 'a.md');
    const p2 = path.join(dir, 'b.md');
    writeIngestReport(p1, makeSummary());
    writeIngestReport(p2, makeSummary());
    expect(fs.existsSync(p1)).toBe(true);
    expect(fs.existsSync(p2)).toBe(true);
  });
});

describe('shipGateVerdict', () => {
  test('synthetic missing -> FAIL', () => {
    const r = shipGateVerdict({ byCorpus: {} });
    expect(r.verdict).toBe('FAIL');
  });

  test('synthetic + paper-log both >= 90 -> PASS', () => {
    const r = shipGateVerdict({
      byCorpus: {
        synthetic: { fixtureCount: 10, results: Array.from({ length: 10 }, (_, i) => ({ actual: { ok: true } })) },
        'paper-log': { fixtureCount: 10, results: Array.from({ length: 10 }, (_, i) => ({ actual: { ok: i < 9 } })) },
      },
    });
    expect(r.verdict).toBe('PASS');
  });
});
