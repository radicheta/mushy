'use strict';

// Phase 41 Plan 03 Task 4: synthetic corpus CI test.
//
// Drives the full harness on the synthetic corpus in MOCKED mode (no API key
// required). Asserts the ingestion harness wiring + scorer + mocked extractor
// all align with the fixture corpus.

const fs = require('fs');
const path = require('path');
const os = require('os');
const { runCorpus } = require('./run-harness');

describe('synthetic ingestion eval (CI; mocked LLM)', () => {
  test('runs all synthetic fixtures and produces a green JSONL', async () => {
    const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'synth-test-results-'));
    const summary = await runCorpus({ corpus: 'synthetic', smoke: false, live: false, capUsd: 0, noReport: true, baseDir });
    expect(summary.byCorpus.synthetic).toBeTruthy();
    const c = summary.byCorpus.synthetic;
    expect(c.fixtureCount).toBeGreaterThanOrEqual(15);
    expect(c.results).toBeTruthy();

    // Every fixture passed (mocked-mode is trivially-passing).
    const okCount = c.results.filter((r) => r.actual && r.actual.ok).length;
    expect(okCount).toBe(c.results.length);

    // Schema-conformance == 100% (every actual.ok was true).
    expect(okCount / c.results.length).toBe(1.0);

    // At least 5 distinct log_type values present.
    const logTypes = new Set(c.results.map((r) => r.expected && r.expected.type).filter(Boolean));
    expect(logTypes.size).toBeGreaterThanOrEqual(5);

    // JSONL file exists with N+1 lines (metadata + per-fixture).
    expect(fs.existsSync(c.jsonlPath)).toBe(true);
    const lines = fs.readFileSync(c.jsonlPath, 'utf8').trim().split('\n');
    expect(lines.length).toBe(c.fixtureCount + 1);
    for (const ln of lines) {
      expect(() => JSON.parse(ln)).not.toThrow();
    }

    // Two fixtures carry session_id (paired-shi-1 + paired-obs-1).
    const sessionIds = c.results.map((r) => r.session_id).filter(Boolean);
    expect(sessionIds.length).toBeGreaterThanOrEqual(2);
  }, 60000);
});
