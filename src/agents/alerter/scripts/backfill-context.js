'use strict';

// Phase 54 Cycle-1 wiring: createBackfillContext() lifts the canonical
// pool + extraction-pipeline bootstrap out of src/index.js so the backfill
// harness (backfill-notebook.js) can run REAL extraction against dev farmOS.
//
// The harness's main() already accepts injected poolFactory / pipelineFactory
// and constructs the responses.jsonl onLlmCall observer itself, handing it to
// pipelineFactory. This module supplies those two factories.
//
// What it deliberately does NOT wire (vs the full createAlerter): signal client,
// bridge, heartbeat, receive loop, watchdogs. Backfill never sends Signal and
// never talks to the bridge. The outbound dispatcher is a no-op so batch-mode's
// summary ping is swallowed (we flip drafts straight to 'confirmed' and commit
// via the harness's commit-router instead).
//
// DB address: prefers DATABASE_URL (the Cycle RUNBOOK env + the harness's own
// required-env gate). Falls back to the canonical TIMESCALE_* fields from
// config.load() when DATABASE_URL is unset, matching src/index.js's Pool.

const { Pool } = require('pg');
const { load } = require('../src/config');
const captureDb = require('../src/capture-db');
const extractionDb = require('../src/extraction/extraction-db');
const stateMachine = require('../src/extraction/state-machine');
const previewBuilder = require('../src/extraction/preview-builder');
const { createExtractor } = require('../src/extraction/extractor');
const { createExtractionPipeline } = require('../src/extraction');
const confirm = require('../src/confirm');
const farmos = require('../src/farmos');

// Best-effort schema init, mirroring src/index.js order. Each is wrapped so a
// single unreachable-at-boot table doesn't abort the whole backfill; the
// columns flipDraftToConfirmed (needs_review_reason) and the commit-router
// (commit_* columns) depend on extraction/confirm/commit schemas, so we run
// the same set the live alerter does.
async function initSchemas(pool, logger) {
  const steps = [
    ['signal_capture', () => captureDb.initDb(pool)],
    ['signal_draft', () => extractionDb.initDb(pool)],
    ['confirm columns + signal_draft_event', () => confirm.confirmDb.initDb(pool)],
    ['commit columns', () => farmos.commitDb.initDb(pool)],
  ];
  for (const [label, fn] of steps) {
    try {
      await fn();
      logger.log && logger.log(`[backfill-ctx] ${label} schema initialized`);
    } catch (e) {
      logger.warn && logger.warn(`[backfill-ctx] ${label} initDb failed (will degrade): ${e.message}`);
    }
  }
}

function buildPool(env, deps) {
  const PoolCtor = deps.Pool || Pool;
  if (env.DATABASE_URL) {
    return new PoolCtor({ connectionString: env.DATABASE_URL });
  }
  // Canonical fallback: same fields src/index.js feeds its Pool.
  const config = deps.config;
  return new PoolCtor({
    host: config.timescaleHost,
    database: config.timescaleDb,
    user: config.timescaleUser,
    password: config.timescalePassword,
    port: 5432,
  });
}

// createBackfillContext({ env, logger, deps }) -> { poolFactory, pipelineFactory }
//
// deps is a test seam (defaults to the real modules). Tests inject fakes to
// prove the wiring without a real Postgres / Anthropic connection.
function createBackfillContext({ env = process.env, logger = console, deps = {} } = {}) {
  const loadConfig = deps.load || load;
  const makeExtractor = deps.createExtractor || createExtractor;
  const makePipeline = deps.createExtractionPipeline || createExtractionPipeline;
  const initFn = deps.initSchemas || initSchemas;

  // config.load() resolves the canonical pipeline knobs (extractionConfidenceThreshold,
  // draftIdleGapMin, maxAskbackTurns) + anthropicApiKey, so backfill extraction
  // behaves identically to the live capture path. Resolved once, shared by both
  // factories.
  const config = loadConfig(env);

  async function poolFactory() {
    const pool = buildPool(env, { ...deps, config });
    await initFn(pool, logger);
    return pool;
  }

  async function pipelineFactory({ pool, onLlmCall = null, replayResponses = null } = {}) {
    if (!pool) throw new Error('createBackfillContext: pipelineFactory requires pool');
    // Replay seam: when given an ordered array of cached Anthropic responses
    // (e.g. from a prior run's responses.jsonl), inject a fake client that hands
    // them back sequentially instead of calling the paid API. Lets us re-validate
    // the extraction->persist path on real captured data for $0.
    let injectedClient = null;
    if (Array.isArray(replayResponses)) {
      let i = 0;
      injectedClient = {
        messages: {
          create: async () => {
            const r = replayResponses[i];
            i += 1;
            if (!r) throw new Error(`replay: ran out of cached responses at call ${i}`);
            return r;
          },
        },
      };
    }
    const extractor = makeExtractor({
      apiKey: config.anthropicApiKey,
      logger,
      onLlmCall,
      client: injectedClient,
    });
    return makePipeline({
      pool,
      extractor,
      extractionDb: deps.extractionDb || extractionDb,
      stateMachine: deps.stateMachine || stateMachine,
      previewBuilder: deps.previewBuilder || previewBuilder,
      config,
      logger,
      // No-op: backfill must not send Signal. Batch-mode's summary ping is
      // swallowed; drafts are flipped to 'confirmed' + committed by the harness.
      outboundDispatcher: { dispatch: () => {} },
    });
  }

  return { poolFactory, pipelineFactory, _config: config };
}

module.exports = { createBackfillContext, initSchemas, buildPool };
