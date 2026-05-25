'use strict';

// Phase 54 Cycle-1 validation: replay a prior backfill run's CACHED Anthropic
// responses (responses.jsonl) through the extraction->persist path for $0.
//
// Use this to re-validate a code fix (e.g. the batch-mode in_flight_conflict fix)
// on the REAL captured data without paying for extraction again.
//
//   node scripts/replay-backfill-responses.js --source-run=<runId> [backfill flags]
//
// Reads .planning/backfill/2025-notebook/<source-run>/responses.jsonl, pulls each
// line's raw_response in order, and injects them into the pipeline via
// createBackfillContext's replay seam. All other flags pass through to the
// backfill harness main().
//
// Recommended validation invocation (NO commit, NO prod risk -- drafts land in
// needs_review which the prod commit-watchdog ignores):
//
//   node scripts/replay-backfill-responses.js --source-run=<id> --cycle=1 --limit=5
//
// (Omit --bulk-backfill so processDraftsForCapture skips the confirm+commit step.)
//
// Env: same as the backfill harness (FARMOS_URL dev, DATABASE_URL, ...). No
// ANTHROPIC_API_KEY call is made, but config.load still requires it to be set.

const fs = require('fs');
const path = require('path');
const { main } = require('./backfill-notebook');
const { createBackfillContext } = require('./backfill-context');

const RUN_DIR_ROOT = '.planning/backfill/2025-notebook';

function loadCachedResponses(sourceRunId) {
  const p = path.join(RUN_DIR_ROOT, sourceRunId, 'responses.jsonl');
  const lines = fs.readFileSync(p, 'utf8').trim().split('\n').filter(Boolean);
  const responses = lines.map((l) => JSON.parse(l).raw_response);
  if (responses.some((r) => !r)) {
    throw new Error(`replay: some lines in ${p} have null raw_response`);
  }
  return responses;
}

if (require.main === module) {
  const argv = process.argv.slice(2);
  const srcArg = argv.find((a) => a.startsWith('--source-run='));
  if (!srcArg) {
    console.error('MISSING --source-run=<runId>');
    process.exit(2);
  }
  const sourceRunId = srcArg.split('=')[1];
  const passThrough = argv.filter((a) => !a.startsWith('--source-run='));

  const replayResponses = loadCachedResponses(sourceRunId);
  console.log(`[replay] loaded ${replayResponses.length} cached responses from run ${sourceRunId}`);

  const ctx = createBackfillContext({ env: process.env, logger: console });
  main(passThrough, {
    poolFactory: () => ctx.poolFactory(),
    pipelineFactory: ({ pool, onLlmCall }) => ctx.pipelineFactory({ pool, onLlmCall, replayResponses }),
  }).then((r) => {
    process.exit(r && typeof r.code === 'number' ? r.code : 0);
  }).catch((e) => {
    console.error('FATAL', e && e.stack || e);
    process.exit(1);
  });
}

module.exports = { loadCachedResponses };
