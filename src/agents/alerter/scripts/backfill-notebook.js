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
    return { captureId, pagePath: page, ok: 'dry-run', draftIds: [] };
  }
  const row = buildSyntheticCapture({ page, runId, sender });
  try {
    await insertSyntheticCapture(pool, row);
  } catch (e) {
    return { captureId, pagePath: page, ok: false, reason: `capture_insert_failed: ${e.message}`, draftIds: [] };
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
    return { captureId, pagePath: page, ok: false, reason: `enqueue_threw: ${e.message}`, draftIds: [] };
  }
  return {
    captureId,
    pagePath: page,
    ok: !!(result && result.ok),
    reason: result && result.reason,
    draftIds: [],
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

  // Build pool + pipeline. Tests inject via poolFactory/pipelineFactory.
  let pool = null;
  let pipeline = null;
  try {
    pool = poolFactory ? await poolFactory({ env, logger }) : null;
    pipeline = pipelineFactory ? await pipelineFactory({ env, logger, pool }) : null;
    if (!pool || !pipeline) {
      // Plan 02 wires the canonical bootstrap. For Plan 01 a real run without injection
      // is unsupported; return a clear marker rather than silently no-oping.
      logger.error && logger.error(
        '[backfill] real-run bootstrap not wired in Plan 01 — pass poolFactory/pipelineFactory or use --dry-run.'
      );
      return { code: 1 };
    }
  } catch (e) {
    logger.error && logger.error(`[backfill] bootstrap failed: ${e.message}`);
    return { code: 1 };
  }

  const sender = env.BACKFILL_SENDER_E164 || BACKFILL_SENDER_DEFAULT;
  const corpusContext = { default_year: 2025, source: 'paper_log' };
  const runSummary = [];
  for (const page of selected) {
    const entry = await dispatchPage({
      pool, pipeline, page, runId, sender, corpusContext, dryRun: false,
    });
    runSummary.push(entry);
    logger.log && logger.log(
      `[backfill] page=${path.basename(page)} ok=${entry.ok} reason=${entry.reason || ''}`
    );
  }

  return { code: 0, runId, runSummary };
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
  main,
  // Constants.
  PAGE_REGEX,
  UN_TRANSCRIBED_REGEX,
  CORPUS_DEFAULT,
  BACKFILL_SENDER_DEFAULT,
};

// Direct invocation entry-point.
if (require.main === module) {
  main().then((r) => {
    process.exit(r && typeof r.code === 'number' ? r.code : 0);
  }).catch((e) => {
    console.error('FATAL', e && e.stack || e);
    process.exit(1);
  });
}
