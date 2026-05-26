'use strict';

// Phase 54 Plan 01: scripts/backfill-notebook.js — 2025-paper-log backfill harness.
//
// Iterates JPEGs from the corrected corpus (/mnt/slime-kingdom/shared/mushdatadump/jpeg/,
// IMG_3775..IMG_3861 range only — CSV ground truth available there), builds synthetic
// signal_capture rows with corpus_context={default_year:2025, source:'paper_log'}, and
// dispatches them through the live extraction pipeline.
//
// This plan ships the CLI surface + guards + dispatch loop. Auto-confirm short-circuit,
// paid-LLM persistence, and the receipt builder land in Plans 02/03/04.
//
// CLI:
//   node scripts/backfill-notebook.js [flags]
//
// Flags:
//   --help                  print usage and exit 0
//   --bulk-backfill         enable santi-only auto-confirm mode (gated to --farmer=santi)
//   --farmer=<name>         farmer identity; bulk-backfill REQUIRES 'santi' (T-54-02)
//   --cycle=<n>             cycle number (1 or 2); default 1
//   --limit=<n>             how many pages to process; default 5
//   --dry-run               skip DB + pipeline; just list selected pages
//   --resume-from=<base>    skip pages until basename matches (e.g. IMG_3778.jpg)
//   --run-id=<id>           override the auto-generated run id (ISO-8601 colon-free)
//   --corpus-dir=<path>     override corpus dir (default /mnt/slime-kingdom/shared/mushdatadump/jpeg)
//
// Env:
//   FARMOS_URL              required for non-dry-run; dev-only ('prod' or ':8082' -> exit 3)
//   FARMOS_USERNAME         required for non-dry-run
//   FARMOS_PASSWORD         required for non-dry-run
//   DATABASE_URL            required for non-dry-run (synthetic signal_capture insert)
//   ANTHROPIC_API_KEY       required for non-dry-run (extractor LLM calls)
//   BACKFILL_SENDER_E164    default '+59891840205' (bot number; santi's stand-in for backfill)
//
// Exit codes:
//   0   ok
//   1   unhandled exception
//   3   prod-guard tripped
//   4   farmer-gate tripped (bulk-backfill without --farmer=santi)
//   5   missing required env (FARMOS_URL/USERNAME/PASSWORD or DATABASE_URL when not --dry-run)

const fs = require('fs');
const path = require('path');

const RUN_DIR_ROOT = '.planning/backfill/2025-notebook';
// Phase 54 Plan 02: canonical confirmed-state constant used by confirm-state-machine
// CONFIRMED ('confirmed') + farmos/commit-db ("WHERE status='confirmed'"). The
// backfill harness short-circuits the live YES-prompt round-trip by flipping
// drafts straight to this status before invoking the commit-router.
const DRAFT_STATUS_CONFIRMED = 'confirmed';

const CORPUS_DEFAULT = '/mnt/slime-kingdom/shared/mushdatadump/jpeg';
const PAGE_REGEX = /^IMG_3(7[7-9][0-9]|8[0-5][0-9]|86[0-1])\.jpg$/;
const UN_TRANSCRIBED_REGEX = /^IMG_3(86[2-9]|87[0-9]|88[0-4])\.jpg$/;
const BACKFILL_SENDER_DEFAULT = '+59891840205';

const USAGE = `Usage: node scripts/backfill-notebook.js [flags]

Flags:
  --help                  Print this banner and exit.
  --bulk-backfill         Enable santi-only auto-confirm mode.
  --farmer=<name>         Farmer identity (santi required for --bulk-backfill).
  --cycle=<n>             Cycle number (1 or 2). Default 1.
  --limit=<n>             Max pages to process. Default 5.
  --dry-run               Skip DB + pipeline; list selected pages only.
  --resume-from=<base>    Skip until basename matches (e.g. IMG_3778.jpg).
  --run-id=<id>           Override the auto-generated run id.
  --corpus-dir=<path>     Override corpus dir. Default ${CORPUS_DEFAULT}.

Env (required for non --dry-run runs):
  FARMOS_URL, FARMOS_USERNAME, FARMOS_PASSWORD, DATABASE_URL, ANTHROPIC_API_KEY.
  BACKFILL_SENDER_E164 (optional; default ${BACKFILL_SENDER_DEFAULT}).

Exit codes: 0 ok | 1 fatal | 3 prod-guard | 4 farmer-gate | 5 missing-env.
`;

function parseArgs(argv) {
  const opts = {
    help: false,
    bulkBackfill: false,
    farmer: null,
    cycle: 1,
    limit: 5,
    dryRun: false,
    resumeFrom: null,
    runId: null,
    corpusDir: CORPUS_DEFAULT,
  };
  for (const arg of argv) {
    if (arg === '--help' || arg === '-h') { opts.help = true; continue; }
    if (arg === '--bulk-backfill') { opts.bulkBackfill = true; continue; }
    if (arg === '--dry-run') { opts.dryRun = true; continue; }
    const eq = arg.indexOf('=');
    if (eq < 0) continue;
    const k = arg.slice(0, eq);
    const v = arg.slice(eq + 1);
    if (k === '--farmer') opts.farmer = v;
    else if (k === '--cycle') opts.cycle = Number(v);
    else if (k === '--limit') opts.limit = Number(v);
    else if (k === '--resume-from') opts.resumeFrom = v;
    else if (k === '--run-id') opts.runId = v;
    else if (k === '--corpus-dir') opts.corpusDir = v;
  }
  return opts;
}

function assertProdGuard(farmosUrl) {
  // Mirror live-fire-52.js: refuse :8082 / ':8082/' / 'prod' substrings.
  const lower = String(farmosUrl || '').toLowerCase();
  if (!lower) {
    // Caller decides whether missing URL is allowed (dry-run path).
    return;
  }
  if (lower.endsWith(':8082') || lower.includes(':8082/') || lower.includes('prod')) {
    const err = new Error('prod-guard');
    err.code = 'PROD_GUARD';
    err.farmosUrl = farmosUrl;
    throw err;
  }
}

function assertFarmerGate(opts) {
  // T-54-02: bulk-backfill is santi-only; refuse any other farmer loudly.
  if (opts.bulkBackfill && opts.farmer !== 'santi') {
    const err = new Error('santi-only');
    err.code = 'FARMER_GATE';
    err.attemptedFarmer = opts.farmer;
    throw err;
  }
}

function listCorpusPages(corpusDir, { readdirSync, logger } = {}) {
  const reader = readdirSync || fs.readdirSync;
  const log = logger || console;
  let entries;
  try {
    entries = reader(corpusDir);
  } catch (e) {
    log.warn && log.warn(`[backfill] corpus dir unreadable: ${e.message}`);
    return [];
  }
  const pages = [];
  for (const name of entries) {
    if (PAGE_REGEX.test(name)) {
      pages.push(path.join(corpusDir, name));
    } else if (UN_TRANSCRIBED_REGEX.test(name)) {
      log.warn && log.warn(
        `[backfill] skipping ${name}: un-transcribed gap per HANDOFF.md (IMG_3862..IMG_3884)`
      );
    }
  }
  pages.sort();
  return pages;
}

function selectPages(allPages, { limit, resumeFrom } = {}) {
  let start = 0;
  if (resumeFrom) {
    const idx = allPages.findIndex((p) => path.basename(p) === resumeFrom);
    if (idx < 0) return [];
    start = idx;
  }
  const cap = Math.max(0, Number(limit) || 0);
  return allPages.slice(start, start + cap);
}

function computeRunId(now) {
  const d = now || new Date();
  return d.toISOString().replace(/[:.]/g, '-');
}

function buildSyntheticCapture({ page, runId, sender }) {
  const basename = path.basename(page, '.jpg');
  return {
    id: `backfill-${runId}-${basename}`,
    captured_at: new Date(),
    sender,
    // Phase 38 capture-db expects message_type — paper_log analogue of an attachment message.
    message_type: 'attachment',
    raw_text: null,
    attachment_paths: [page],
    transcript: null,
    corpus_context: { default_year: 2025, source: 'paper_log' },
  };
}

async function insertSyntheticCapture(pool, row) {
  // Direct require to avoid hard-coupling; capture-db already owns the INSERT shape
  // (id, captured_at, sender, message_type, raw_text, attachment_paths, transcript,
  // llm_session_tag, llm_reply, degraded, group_id, farmos_person, reply_target_kind,
  // signal_msg_ts, quote_msg_ts, quote_author_e164, corpus_context).
  const captureDb = require('../src/capture-db');
  await captureDb.insertCapture(pool, row);
}

async function dispatchPage({ pool, pipeline, page, runId, sender, corpusContext, dryRun }) {
  const captureId = `backfill-${runId}-${path.basename(page, '.jpg')}`;
  if (dryRun) {
    return { captureId, pagePath: page, ok: 'dry-run', draftIds: [], commits: [] };
  }
  const row = buildSyntheticCapture({ page, runId, sender });
  try {
    await insertSyntheticCapture(pool, row);
  } catch (e) {
    return { captureId, pagePath: page, ok: false, reason: `capture_insert_failed: ${e.message}`, draftIds: [], commits: [] };
  }
  let result;
  try {
    result = await pipeline.enqueue({
      sender,
      captureId,
      attachmentPaths: [page],
      corpusContext,
    });
  } catch (e) {
    // pipeline.enqueue is documented as never-throw; defense-in-depth.
    return { captureId, pagePath: page, ok: false, reason: `enqueue_threw: ${e.message}`, draftIds: [], commits: [] };
  }
  return {
    captureId,
    pagePath: page,
    ok: !!(result && result.ok),
    reason: result && result.reason,
    draftIds: [],
    commits: [],
  };
}

// ============================================================================
// Phase 54 Plan 02: auto-confirm short-circuit + commit-router dispatch +
// summaries.log writer. All santi-only; defense-in-depth in-loop assertion.
// ============================================================================

function assertSantiInLoop(opts) {
  // T-54-05: even if opts.farmer is mutated mid-loop, the per-iteration check
  // refuses to short-circuit for anyone other than santi.
  if (opts && opts.bulkBackfill && opts.farmer !== 'santi') {
    const err = new Error('santi-only');
    err.code = 'FARMER_GATE';
    err.attemptedFarmer = opts && opts.farmer;
    throw err;
  }
}

async function flipDraftToConfirmed(pool, draftId, { extractionDb } = {}) {
  // Phase 54 Plan 02: bulk-backfill short-circuit. Skips the live confirm
  // YES-round-trip by writing the canonical 'confirmed' status with an audit
  // marker in needs_review_reason.
  const db = extractionDb || require('../src/extraction/extraction-db');
  return db.updateDraftStatus(pool, draftId, DRAFT_STATUS_CONFIRMED, {
    needs_review_reason: 'bulk_backfill_santi',
  });
}

function buildSummaryLine({ ts, page, captureId, draftId, logType, ok, assetCount, logCount, reason }) {
  // ASCII-only; no em-dashes per [[feedback_no_em_dashes_in_artifacts]].
  const parts = [
    ts,
    `page=${page}`,
    `capture=${captureId}`,
    `draft=${draftId}`,
    `log_type=${logType || 'unknown'}`,
    `ok=${ok}`,
    `assets=${assetCount || 0}`,
    `logs=${logCount || 0}`,
  ];
  if (reason && ok !== true) {
    // Strip stray em-dashes from upstream reason strings; replace with '--'.
    const safe = String(reason).replace(/[–—]/g, '--');
    parts.push(`reason=${safe}`);
  }
  return parts.join(' ');
}

function openSummariesLog(runDir) {
  fs.mkdirSync(runDir, { recursive: true });
  return fs.openSync(path.join(runDir, 'summaries.log'), 'a');
}

function appendSummaryLine(fd, line) {
  fs.writeSync(fd, line + '\n');
}

async function processDraftsForCapture({
  pool, client, captureId, pagePath, opts, summariesFd, extractionDb, commitRouter, dryRun,
}) {
  // Hard re-assertion per T-54-05.
  assertSantiInLoop(opts);

  const db = extractionDb || require('../src/extraction/extraction-db');
  const router = commitRouter || require('../src/farmos/commits/commit-router');
  const drafts = await db.getDraftsForCapture(pool, captureId);
  const commits = [];

  for (const draft of drafts) {
    const ts = new Date().toISOString();
    const draftId = draft.id;
    const logType = draft.log_type;
    let entry;

    if (dryRun) {
      entry = { draftId, log_type: logType, ok: 'dry-run', asset_ids: [], log_ids: [] };
      commits.push(entry);
      if (summariesFd != null) {
        appendSummaryLine(summariesFd, buildSummaryLine({
          ts, page: path.basename(pagePath), captureId, draftId, logType,
          ok: 'dry-run', assetCount: 0, logCount: 0,
        }));
      }
      continue;
    }

    if (!opts.bulkBackfill) {
      // No short-circuit; leave draft in its pending/awaiting_farmer state.
      entry = { draftId, log_type: logType, ok: 'skipped', asset_ids: [], log_ids: [], reason: 'no_bulk_backfill' };
      commits.push(entry);
      if (summariesFd != null) {
        appendSummaryLine(summariesFd, buildSummaryLine({
          ts, page: path.basename(pagePath), captureId, draftId, logType,
          ok: false, assetCount: 0, logCount: 0, reason: 'no_bulk_backfill',
        }));
      }
      continue;
    }

    // 1. Flip draft to 'confirmed' (bulk_backfill_santi audit marker).
    const flip = await flipDraftToConfirmed(pool, draftId, { extractionDb: db });
    if (!flip || flip.ok !== true) {
      entry = {
        draftId, log_type: logType, ok: false, asset_ids: [], log_ids: [],
        reason: `draft_flip_failed: ${(flip && flip.reason) || 'unknown'}`,
      };
      commits.push(entry);
      if (summariesFd != null) {
        appendSummaryLine(summariesFd, buildSummaryLine({
          ts, page: path.basename(pagePath), captureId, draftId, logType,
          ok: false, assetCount: 0, logCount: 0, reason: entry.reason,
        }));
      }
      continue;
    }

    // 2. Dispatch via commit-router.
    // createMissingFungiType is intentionally OFF: blind-minting unknown strains
    // pollutes the shared taxonomy with extraction variants (Cycle-1 validation
    // 2026-05-25 minted LIM/SHITAKE/OYS for LIMA/SHI/POY). Per Santi, an unknown
    // strain must get a batched farmer double-check ("new strain XYZ?") before its
    // fungi_type term is minted. Until that confirm flow lands, unknown strains
    // fail fungi_type_not_found rather than auto-minting. The ensureFungiTypeUuid
    // mechanism stays in place for the confirm flow to call once a strain is
    // farmer-confirmed. See .planning/todos -> strain-confirm-before-mint.
    let commitResult;
    try {
      commitResult = await router.commit(client, draft, {
        auditLogger: { logCommit: async () => {} },
        createMissingFungiType: false,
      });
    } catch (e) {
      // commit-router is documented never-throw; defense-in-depth.
      commitResult = { ok: false, reason: `commit_threw: ${e.message}`, asset_ids: [], log_ids: [] };
    }

    // strain_codes + block_name carried onto the commit entry so the receipt's
    // CSV diff + upsert-stability check can match against ground truth (Cycle-1
    // finding A 2026-05-25). The strain lives in draft_json; the receipt reads
    // c.strain_codes / c.block_name off each commit entry.
    const dj = (draft && draft.draft_json) || {};
    const strain = dj.species_code || dj.species || dj.strain || dj.fungi_type || null;
    entry = {
      draftId, log_type: logType,
      ok: !!commitResult.ok,
      asset_ids: commitResult.asset_ids || [],
      log_ids: commitResult.log_ids || [],
      reason: commitResult.reason,
      strain_codes: strain ? [String(strain).toUpperCase()] : [],
      block_name: dj.block_name || null,
    };
    commits.push(entry);

    if (summariesFd != null) {
      appendSummaryLine(summariesFd, buildSummaryLine({
        ts, page: path.basename(pagePath), captureId, draftId, logType,
        ok: entry.ok, assetCount: entry.asset_ids.length, logCount: entry.log_ids.length,
        reason: entry.reason,
      }));
    }
  }

  return { drafts, commits };
}

function computeRunDir(runId) {
  return path.join(RUN_DIR_ROOT, runId);
}

// ============================================================================
// Phase 54 Plan 03: paid-LLM responses.jsonl writer + onLlmCall observer +
// run-id collision guard. Honors [[feedback_persist_paid_results_default]]
// and [[feedback_never_overwrite_paid_live_api_results]].
// ============================================================================

// 2026-05-24 Anthropic pricing per MTok (Sonnet 4.6 + Haiku 3.5). Adjust on
// rate-card change. Documented inline so the cost_estimate_usd line in
// responses.jsonl traces back to a single source of truth.
const SONNET_INPUT_USD_PER_MTOK = 3.00;
const SONNET_OUTPUT_USD_PER_MTOK = 15.00;
const HAIKU_INPUT_USD_PER_MTOK = 0.80;
const HAIKU_OUTPUT_USD_PER_MTOK = 4.00;

function estimateCostUsd(model, inputTokens, outputTokens) {
  const m = String(model || '').toLowerCase();
  const isHaiku = m.includes('haiku');
  const inRate = isHaiku ? HAIKU_INPUT_USD_PER_MTOK : SONNET_INPUT_USD_PER_MTOK;
  const outRate = isHaiku ? HAIKU_OUTPUT_USD_PER_MTOK : SONNET_OUTPUT_USD_PER_MTOK;
  return ((inputTokens || 0) / 1e6) * inRate + ((outputTokens || 0) / 1e6) * outRate;
}

function runIdExistsGuard(runDir) {
  // Refuses to start if responses.jsonl already exists in the runDir; an empty
  // runDir is fine (allows manual retry after a failed bootstrap).
  try {
    const f = path.join(runDir, 'responses.jsonl');
    if (fs.existsSync(f)) {
      const err = new Error('run_id_exists');
      err.code = 'RUN_ID_EXISTS';
      err.path = f;
      throw err;
    }
  } catch (e) {
    if (e && e.code === 'RUN_ID_EXISTS') throw e;
    // fs error other than ENOENT — treat as fatal to avoid clobbering.
    if (e && e.code && e.code !== 'ENOENT') throw e;
  }
}

function openResponsesJsonl(runDir) {
  fs.mkdirSync(runDir, { recursive: true });
  return fs.openSync(path.join(runDir, 'responses.jsonl'), 'a');
}

function buildResponsesLine(observation) {
  const line = {
    ts: observation.ts,
    captureId: observation.captureId || null,
    model: observation.model,
    input_tokens: observation.input_tokens || 0,
    output_tokens: observation.output_tokens || 0,
    cache_creation_input_tokens: observation.cache_creation_input_tokens || 0,
    cache_read_input_tokens: observation.cache_read_input_tokens || 0,
    latency_ms: observation.latency_ms || 0,
    cost_estimate_usd: estimateCostUsd(
      observation.model, observation.input_tokens, observation.output_tokens
    ),
    request_hash: observation.request_hash,
    raw_response: observation.raw_response || null,
    error: observation.error || null,
  };
  return JSON.stringify(line);
}

function makeResponsesObserver(fd) {
  // Synchronous fs.writeSync per call — guarantees evidence is on-disk before
  // extract() returns (T-54-09 mitigation).
  return function onLlmCall(observation) {
    const line = buildResponsesLine(observation);
    fs.writeSync(fd, line + '\n');
  };
}

function printUsage() {
  process.stdout.write(USAGE);
}

async function main(argv = process.argv.slice(2), {
  env = process.env,
  logger = console,
  poolFactory = null,
  pipelineFactory = null,
  clientFactory = null,
  extractionDb = null,
  commitRouter = null,
  now = null,
} = {}) {
  const opts = parseArgs(argv);
  if (opts.help) {
    printUsage();
    return { code: 0 };
  }

  // Prod-guard first when URL is present. Missing URL is fine on --dry-run.
  if (env.FARMOS_URL) {
    try {
      assertProdGuard(env.FARMOS_URL);
    } catch (e) {
      logger.error && logger.error(
        `REFUSING: prod-guard on FARMOS_URL=${env.FARMOS_URL}. Phase 54 is dev-only.`
      );
      return { code: 3 };
    }
  }

  try {
    assertFarmerGate(opts);
  } catch (e) {
    logger.error && logger.error(
      `REFUSING: --bulk-backfill requires --farmer=santi; got farmer=${JSON.stringify(opts.farmer)}.`
    );
    return { code: 4 };
  }

  if (!opts.dryRun) {
    const missing = ['FARMOS_URL', 'FARMOS_USERNAME', 'FARMOS_PASSWORD', 'DATABASE_URL']
      .filter((k) => !env[k]);
    if (missing.length > 0) {
      logger.error && logger.error(`MISSING env: ${missing.join(', ')}`);
      return { code: 5 };
    }
  }

  const runId = opts.runId || computeRunId(now);
  const allPages = listCorpusPages(opts.corpusDir, { logger });
  const selected = selectPages(allPages, { limit: opts.limit, resumeFrom: opts.resumeFrom });

  logger.log && logger.log(`[backfill] run_id=${runId} cycle=${opts.cycle} pages=${selected.length} dry_run=${opts.dryRun}`);
  for (const p of selected) {
    logger.log && logger.log(`[backfill] selected: ${path.basename(p)}`);
  }

  if (opts.dryRun) {
    const runSummary = selected.map((page) => ({
      captureId: `backfill-${runId}-${path.basename(page, '.jpg')}`,
      pagePath: page,
      ok: 'dry-run',
      draftIds: [],
    }));
    return { code: 0, runId, runSummary };
  }

  const sender = env.BACKFILL_SENDER_E164 || BACKFILL_SENDER_DEFAULT;
  const corpusContext = { default_year: 2025, source: 'paper_log' };
  const runDir = computeRunDir(runId);

  // Plan 03: refuse to start if responses.jsonl already exists (T-54-10).
  if (!opts.dryRun) {
    try {
      runIdExistsGuard(runDir);
    } catch (e) {
      if (e && e.code === 'RUN_ID_EXISTS') {
        logger.error && logger.error(
          `REFUSING: --run-id ${runId} already has responses.jsonl at ${e.path}. Use a fresh --run-id.`
        );
        return { code: 6 };
      }
      throw e;
    }
  }

  // Plan 02: summaries.log + Plan 03: responses.jsonl opened before any
  // dispatch (audit-first). Both written only when --bulk-backfill mode is
  // active (no audit needed for non-mutating dry-run / pending-status runs).
  let summariesFd = null;
  let responsesFd = null;
  let onLlmCall = null;
  let client = null;
  if (opts.bulkBackfill) {
    summariesFd = openSummariesLog(runDir);
    if (!opts.dryRun) {
      responsesFd = openResponsesJsonl(runDir);
      onLlmCall = makeResponsesObserver(responsesFd);
    }
    if (clientFactory) {
      client = await clientFactory({ env, logger });
    } else {
      try {
        const { createFarmosClient } = require('../src/farmos/client');
        client = createFarmosClient({
          farmosUrl: env.FARMOS_URL,
          username: env.FARMOS_USERNAME,
          password: env.FARMOS_PASSWORD,
          logger,
        });
      } catch (e) {
        logger.error && logger.error(`[backfill] createFarmosClient failed: ${e.message}`);
        if (summariesFd != null) fs.closeSync(summariesFd);
        if (responsesFd != null) fs.closeSync(responsesFd);
        return { code: 1 };
      }
    }
  }

  // Build pool + pipeline. Tests inject via poolFactory/pipelineFactory.
  // pipelineFactory receives onLlmCall so its extractor instance forwards
  // every paid call to the responses.jsonl observer.
  let pool = null;
  let pipeline = null;
  try {
    pool = poolFactory ? await poolFactory({ env, logger }) : null;
    pipeline = pipelineFactory ? await pipelineFactory({ env, logger, pool, onLlmCall }) : null;
    if (!pool || !pipeline) {
      logger.error && logger.error(
        '[backfill] real-run bootstrap not yet wired — pass poolFactory/pipelineFactory or use --dry-run.'
      );
      if (summariesFd != null) fs.closeSync(summariesFd);
      if (responsesFd != null) fs.closeSync(responsesFd);
      return { code: 1 };
    }
  } catch (e) {
    logger.error && logger.error(`[backfill] bootstrap failed: ${e.message}`);
    if (summariesFd != null) fs.closeSync(summariesFd);
    if (responsesFd != null) fs.closeSync(responsesFd);
    return { code: 1 };
  }

  const runSummary = [];
  try {
    for (const page of selected) {
      const entry = await dispatchPage({
        pool, pipeline, page, runId, sender, corpusContext, dryRun: false,
      });
      if (entry.ok === true) {
        const { drafts, commits } = await processDraftsForCapture({
          pool, client, captureId: entry.captureId, pagePath: page,
          opts, summariesFd, extractionDb, commitRouter, dryRun: false,
        });
        entry.draftIds = drafts.map((d) => d.id);
        entry.commits = commits;
      }
      runSummary.push(entry);
      logger.log && logger.log(
        `[backfill] page=${path.basename(page)} ok=${entry.ok} drafts=${entry.draftIds.length} reason=${entry.reason || ''}`
      );
    }
  } finally {
    if (summariesFd != null) {
      try { fs.closeSync(summariesFd); } catch (_e) {}
    }
    if (responsesFd != null) {
      try { fs.closeSync(responsesFd); } catch (_e) {}
    }
    // Plan 04: always emit receipt.md so a crashed run still has an audit
    // artifact (T-54-13 — repudiation mitigation).
    if (opts.bulkBackfill) {
      try {
        const { buildReceipt } = require('./build-backfill-receipt');
        const csvPath = env.MUSHROOM_LOG_CSV || '/mnt/slime-kingdom/shared/mushdatadump/mushroom_log.csv';
        buildReceipt({
          runDir,
          runSummary,
          csvPath,
          runId,
          cycleNumber: opts.cycle,
          farmosUrl: env.FARMOS_URL,
          elapsedSec: 0,
        });
      } catch (e) {
        logger.warn && logger.warn(`[backfill] buildReceipt failed: ${e.message}`);
      }
    }
  }

  return { code: 0, runId, runDir, runSummary };
}

module.exports = {
  // Pure helpers (exposed for tests).
  parseArgs,
  assertProdGuard,
  assertFarmerGate,
  listCorpusPages,
  selectPages,
  computeRunId,
  buildSyntheticCapture,
  insertSyntheticCapture,
  dispatchPage,
  // Plan 02
  assertSantiInLoop,
  flipDraftToConfirmed,
  buildSummaryLine,
  openSummariesLog,
  appendSummaryLine,
  processDraftsForCapture,
  computeRunDir,
  DRAFT_STATUS_CONFIRMED,
  RUN_DIR_ROOT,
  // Plan 03
  runIdExistsGuard,
  openResponsesJsonl,
  buildResponsesLine,
  makeResponsesObserver,
  estimateCostUsd,
  SONNET_INPUT_USD_PER_MTOK,
  SONNET_OUTPUT_USD_PER_MTOK,
  HAIKU_INPUT_USD_PER_MTOK,
  HAIKU_OUTPUT_USD_PER_MTOK,
  main,
  // Constants.
  PAGE_REGEX,
  UN_TRANSCRIBED_REGEX,
  CORPUS_DEFAULT,
  BACKFILL_SENDER_DEFAULT,
};

// Direct invocation entry-point. Wires the canonical pool + extraction-pipeline
// bootstrap (lifted into createBackfillContext) so real runs work. main()
// constructs the responses.jsonl onLlmCall observer and threads it into
// pipelineFactory. --dry-run / --help short-circuit before either factory fires.
if (require.main === module) {
  const argv = process.argv.slice(2);
  const dryRunOrHelp = argv.includes('--dry-run') || argv.includes('--help') || argv.includes('-h');
  let opts = {};
  if (!dryRunOrHelp) {
    // Lazily build the context on first factory call so main()'s prod-guard
    // (exit 3), farmer-gate (exit 4), and missing-env (exit 5) checks run first.
    let ctx = null;
    const ctxOnce = () => {
      if (!ctx) {
        const { createBackfillContext } = require('./backfill-context');
        ctx = createBackfillContext({ env: process.env, logger: console });
      }
      return ctx;
    };
    opts = {
      poolFactory: () => ctxOnce().poolFactory(),
      pipelineFactory: ({ pool, onLlmCall }) => ctxOnce().pipelineFactory({ pool, onLlmCall }),
    };
  }
  main(argv, opts).then((r) => {
    process.exit(r && typeof r.code === 'number' ? r.code : 0);
  }).catch((e) => {
    console.error('FATAL', e && e.stack || e);
    process.exit(1);
  });
}
