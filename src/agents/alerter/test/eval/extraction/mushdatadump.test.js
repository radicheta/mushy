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
const MODEL = 'claude-sonnet-4-6';

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
    const fixtures = loadFixtures(FIXTURE_DIR);
    console.info(`[eval] loaded ${fixtures.length} fixtures from ${FIXTURE_DIR}`);

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

      // Checkpoint partial state every 10 cases so a mid-run crash doesn't lose work.
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
      notes: `Wall time: ${wallSec}s. Partial state checkpoint at ${PARTIAL_PATH}.`,
    });
    console.info(`[eval] wrote ${REPORT_PATH}`);
    console.info(`[eval] verdict: [${verdict}]`);

    // Soft assertion: harness ran. Hard gate is the verdict line.
    expect(scores.schemaConformance).toBeGreaterThanOrEqual(0);
    expect(results.length).toBeGreaterThan(0);
  }, 1800000); // 30 min jest timeout (per-call inside is governed by Anthropic SDK)
});
