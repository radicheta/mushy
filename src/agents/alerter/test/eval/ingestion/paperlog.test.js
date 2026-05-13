'use strict';

// Phase 41 Plan 04 Task 3: paper-log corpus eval (operator-run; live LLM).
//
// describe.skip by default; un-skips when EVAL_RUN_LIVE=1 + ANTHROPIC_API_KEY.
// Uses Phase 38 scorer for per-field scoring; no scorer modification.

const fs = require('fs');
const path = require('path');
const os = require('os');
const { runCorpus } = require('./run-harness');
const scoring = require('../extraction/scoring');

const liveMode = process.env.EVAL_RUN_LIVE === '1' && !!process.env.ANTHROPIC_API_KEY;
const describeMaybe = liveMode ? describe : describe.skip;

describeMaybe('paper-log ingestion eval (operator-run; live LLM)', () => {
  test('smoke run (5 fixtures)', async () => {
    const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pl-smoke-'));
    const summary = await runCorpus({ corpus: 'paper-log', smoke: true, live: true, capUsd: 5, noReport: true, baseDir });
    const c = summary.byCorpus['paper-log'];
    expect(c).toBeTruthy();
    expect(c.fixtureCount).toBeGreaterThan(0);

    // Schema conformance bar (Phase 38 v1.6 page-grain adaptation): >= 90%
    const okCount = (c.results || []).filter((r) => r.actual && r.actual.ok).length;
    const conformance = c.results.length ? (okCount / c.results.length) : 0;
    expect(conformance).toBeGreaterThanOrEqual(0.9);
  }, 600000);

  test('full run', async () => {
    const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pl-full-'));
    const summary = await runCorpus({ corpus: 'paper-log', smoke: false, live: true, capUsd: 20, noReport: true, baseDir });
    const c = summary.byCorpus['paper-log'];
    expect(c).toBeTruthy();
    expect(c.fixtureCount).toBeGreaterThan(0);

    const okCount = (c.results || []).filter((r) => r.actual && r.actual.ok).length;
    const conformance = c.results.length ? (okCount / c.results.length) : 0;
    expect(conformance).toBeGreaterThanOrEqual(0.9);

    // For prod fixtures with hand-labels: exactFieldMatch >= 0.80 (D-03c).
    const prodLabeled = (c.results || []).filter((r) => /^prod:/.test(r.fixture_id) && r.expected && r.expected.fields && Object.keys(r.expected.fields).length > 0);
    if (prodLabeled.length > 0) {
      const pairs = prodLabeled.map((r) => ({ fixture: { expected: r.expected }, actual: r.actual.draft }));
      const exact = scoring.exactFieldMatch(pairs);
      expect(exact).toBeGreaterThanOrEqual(0.8);
    }
  }, 1800000);
});
