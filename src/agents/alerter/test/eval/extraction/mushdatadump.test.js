'use strict';

// Phase 38 Plan 07 Task 2: D-07 ship-gate driver.
//
// Loops every mushdatadump fixture, calls the real Anthropic extractor, scores,
// and writes 38-EVAL-REPORT.md. The jest test passes as long as the harness
// completes + writes the report. The HARD gate is the verdict line in the
// report, which Don Santiago (Task 3) reads + decides on.

const path = require('path');
const fs = require('fs');
const { createExtractor } = require('../../../src/extraction/extractor');
const { readImageToBase64 } = require('../../../src/extraction/multimodal');
const { loadFixtures } = require('./fixtures-loader');
const scoring = require('./scoring');
const { writeReport } = require('./report');

const FIXTURE_DIR = process.env.EXTRACTION_FIXTURE_DIR || '/mnt/mossrock/shared/mushdatadump';
const REPORT_PATH = process.env.EVAL_REPORT_PATH
  || path.resolve(__dirname, '../../../../../../.planning/phases/38-extraction-pipeline/38-EVAL-REPORT.md');
const PARTIAL_PATH = REPORT_PATH.replace(/\.md$/, '.partial.json');
const RESULTS_JSON_PATH = REPORT_PATH.replace(/\.md$/, '-results.json');
const RESULTS_JSONL_PATH = REPORT_PATH.replace(/\.md$/, '-results.jsonl');
const MODEL = 'claude-sonnet-4-6';
// Optional cap for smoke runs. Set EVAL_MAX_FIXTURES=2 to run on 2 images first.
const MAX_FIXTURES = process.env.EVAL_MAX_FIXTURES
  ? Math.max(1, parseInt(process.env.EVAL_MAX_FIXTURES, 10))
  : Infinity;
// Sonnet 4.6 pricing per MTok ($USD).
const PRICE = {
  input: 3.0,
  output: 15.0,
  cache_write: 3.75,
  cache_read: 0.30,
};

const ADAPTATION_NOTE = [
  'mushdatadump v1.6 does NOT ship a per-image ground-truth.csv. The 73 JPEGs',
  'are paper-log pages; mushroom_log.csv is page-grain (829 entries across 73',
  'pages, ~11 entries per page). Aligning each entry to a JPEG region requires',
  'OCR, which is out of scope for Plan 07.',
  '',
  'Adaptation: per-image expected reduced to `type=seeding` + `ambiguous=false`',
  'with no required fields. Scored dimensions:',
  '  - Schema conformance (binary: did extractor return a schema-valid draft?)',
  '  - B5 block_name precision: of drafts that produced a block_name, how many',
  '    pass the {YYMMDD}_{SPECIES3}_{SEQ} regex (no recall, no expected match)',
  '  - Confidence calibration: Brier + ECE on per_field_confidence vs schema',
  '    validity (proxy for correctness)',
  '  - combinedFieldOrAskBack: schema-valid OR per_field_confidence < 0.7 on any',
  '    required field (treated as appropriate ask-back since pages ARE ambiguous',
  '    for a single draft).',
  '',
  'Richer per-image ground truth is deferred to Plan 08 (production-log path),',
  'where farmer-curated single-event captures land 1:1 against extracted drafts.',
].join('\n');

const COST_NOTE = [
  '73 fixtures x ~1 turn x claude-sonnet-4-6 (~$3/MTok input cached, $15/MTok',
  'output) with image input. With prompt caching across the system+few-shot,',
  'expected spend $1-5 per full run. Re-runnable any time the extractor changes.',
].join(' ');

describe('mushdatadump eval (D-07 ship-gate)', () => {
  test('runs all fixtures and writes report', async () => {
    if (!process.env.ANTHROPIC_API_KEY) {
      throw new Error('ANTHROPIC_API_KEY must be set in env to run this eval.');
    }
    const allFixtures = loadFixtures(FIXTURE_DIR);
    const fixtures = Number.isFinite(MAX_FIXTURES) ? allFixtures.slice(0, MAX_FIXTURES) : allFixtures;
    console.info(`[eval] loaded ${fixtures.length}/${allFixtures.length} fixtures from ${FIXTURE_DIR}${Number.isFinite(MAX_FIXTURES) ? ` (capped at ${MAX_FIXTURES})` : ''}`);

    // Fresh JSONL — truncate so re-runs don't accumulate stale entries.
    try { fs.mkdirSync(path.dirname(RESULTS_JSONL_PATH), { recursive: true }); } catch (_) { /* noop */ }
    try { fs.writeFileSync(RESULTS_JSONL_PATH, ''); } catch (_) { /* noop */ }

    const extractor = createExtractor({
      apiKey: process.env.ANTHROPIC_API_KEY,
      logger: console,
      model: MODEL,
    });

    const results = [];
    let hardErrors = 0;
    let skipped = 0;
    const t0 = Date.now();
    for (let i = 0; i < fixtures.length; i += 1) {
      const fx = fixtures[i];
      const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
      console.info(`[eval] ${i + 1}/${fixtures.length} (${elapsed}s) ${fx.name}`);
      let imgBlock;
      try {
        imgBlock = await readImageToBase64(fx.imagePath, { logger: console });
      } catch (e) {
        console.warn(`[eval] image read failed: ${e.message}`);
        skipped += 1;
        continue;
      }
      if (!imgBlock || !imgBlock.ok) {
        console.warn(`[eval] image not loadable: ${imgBlock && imgBlock.reason}`);
        skipped += 1;
        continue;
      }
      let r;
      try {
        r = await extractor.extract({
          captures: [{
            text: '',
            transcript: '',
            images: [{ data: imgBlock.data, media_type: imgBlock.media_type }],
          }],
          inFlightDraft: null,
        });
      } catch (e) {
        console.warn(`[eval] extract threw (should not happen): ${e.message}`);
        hardErrors += 1;
        r = { ok: false, reason: `thrown: ${e.message}` };
      }
      if (r && r.ok === false && /rate|429|503|overload/i.test(String(r.reason || ''))) {
        hardErrors += 1;
        console.warn(`[eval] hard API error: ${r.reason}`);
      }
      results.push({ fixture: fx, actual: r });

      // Stream per-fixture JSONL append — never lose a paid-for draft again.
      try {
        const line = JSON.stringify({
          idx: i,
          fixture_name: fx.name,
          fixture_path: fx.imagePath,
          actual: r,
        });
        fs.appendFileSync(RESULTS_JSONL_PATH, line + '\n');
      } catch (e) {
        console.warn(`[eval] jsonl append failed: ${e.message}`);
      }

      // Coarse checkpoint every 10 cases for at-a-glance progress (kept for back-compat).
      if ((i + 1) % 10 === 0) {
        try {
          fs.writeFileSync(PARTIAL_PATH, JSON.stringify({ done: i + 1, total: fixtures.length, results }, null, 2));
        } catch (_) { /* best effort */ }
      }

      // Early-abort guard: if more than 15% of cases so far are hard errors AND
      // we've done at least 20, bail to a partial report rather than burn budget.
      if (i >= 20 && hardErrors / (i + 1) > 0.15) {
        console.warn(`[eval] early abort: hard error rate ${hardErrors}/${i + 1} > 15%`);
        break;
      }
    }
    const wallSec = ((Date.now() - t0) / 1000).toFixed(1);
    console.info(`[eval] completed ${results.length} fixtures in ${wallSec}s (${hardErrors} hard errors, ${skipped} skipped)`);

    // Aggregate Anthropic usage tokens across all calls + estimate spend.
    const usageTotals = { input_tokens: 0, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, calls_with_usage: 0 };
    for (const row of results) {
      const u = row.actual && row.actual.usage;
      if (!u) continue;
      usageTotals.calls_with_usage += 1;
      usageTotals.input_tokens += u.input_tokens || 0;
      usageTotals.output_tokens += u.output_tokens || 0;
      usageTotals.cache_creation_input_tokens += u.cache_creation_input_tokens || 0;
      usageTotals.cache_read_input_tokens += u.cache_read_input_tokens || 0;
    }
    const costUsd =
        (usageTotals.input_tokens / 1e6) * PRICE.input
      + (usageTotals.output_tokens / 1e6) * PRICE.output
      + (usageTotals.cache_creation_input_tokens / 1e6) * PRICE.cache_write
      + (usageTotals.cache_read_input_tokens / 1e6) * PRICE.cache_read;
    console.info(`[eval] tokens: in=${usageTotals.input_tokens} out=${usageTotals.output_tokens} cache_w=${usageTotals.cache_creation_input_tokens} cache_r=${usageTotals.cache_read_input_tokens} -> $${costUsd.toFixed(4)}`);

    // Final full-results dump (separate from per-fixture JSONL stream).
    try {
      fs.writeFileSync(RESULTS_JSON_PATH, JSON.stringify({
        meta: {
          model: MODEL,
          fixtureDir: FIXTURE_DIR,
          timestamp: new Date().toISOString(),
          wallSec: Number(wallSec),
          fixturesRun: results.length,
          fixturesTotalAvailable: allFixtures.length,
          skipped,
          hardErrors,
          usageTotals,
          estimatedCostUsd: costUsd,
        },
        results,
      }, null, 2));
    } catch (e) {
      console.warn(`[eval] final results.json write failed: ${e.message}`);
    }

    const scores = {
      schemaConformance: scoring.schemaConformance(results),
      requiredFieldMatch: scoring.exactFieldMatch(results),
      appropriateAskBack: scoring.appropriateAskBack(results),
      setEquality: scoring.setEquality(results),
      b5: scoring.b5PrecisionRecall(results),
      brier: scoring.brierScore(results),
      ece: scoring.ece(results),
      requiredFieldOrAppropriateAskBack: scoring.combinedFieldOrAskBack(results),
    };
    const verdict = (scores.schemaConformance >= 0.90 && scores.requiredFieldOrAppropriateAskBack >= 0.75)
      ? 'PASS' : 'FAIL';

    writeReport(REPORT_PATH, scores, results.length, verdict, {
      model: MODEL,
      fixtureDir: FIXTURE_DIR,
      timestamp: new Date().toISOString(),
      costNote: COST_NOTE,
      adaptations: ADAPTATION_NOTE,
      skipped,
      errors: hardErrors,
      usageTotals,
      costEstimateUsd: costUsd,
      notes: [
        `Wall time: ${wallSec}s.`,
        `Per-fixture drafts: ${RESULTS_JSONL_PATH}`,
        `Full results: ${RESULTS_JSON_PATH}`,
        Number.isFinite(MAX_FIXTURES) ? `Capped run: EVAL_MAX_FIXTURES=${MAX_FIXTURES} (of ${allFixtures.length} available).` : null,
      ].filter(Boolean).join(' '),
    });
    console.info(`[eval] wrote ${REPORT_PATH}`);
    console.info(`[eval] verdict: [${verdict}]`);

    // Soft assertion: harness ran. Hard gate is the verdict line.
    expect(scores.schemaConformance).toBeGreaterThanOrEqual(0);
    expect(results.length).toBeGreaterThan(0);
  }, 1800000); // 30 min jest timeout (per-call inside is governed by Anthropic SDK)
});
