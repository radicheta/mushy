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
  --all-pages             Process all corpus pages (overrides --limit).
  --farmer=<name>         Farmer identity (santi required for --bulk-backfill).
  --cycle=<n>             Cycle number (1 or 2). Default 1.
  --limit=<n>             Max pages to process. Default 5.
  --dry-run               Skip DB + pipeline; list selected pages only.
  --allow-prod-write      Opt in to writing to PROD farmOS (:8082). Requires
                          --farmer=santi. Bypasses the prod-guard for an
                          explicit, operator-authorized promotion (BACK-11).
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
    allPages: false,
    allowProdWrite: false,
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
    if (arg === '--all-pages') { opts.allPages = true; continue; }
    if (arg === '--allow-prod-write') { opts.allowProdWrite = true; continue; }
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

// ============================================================================
// Phase 55B Plan 02: CSV budget helpers for fidelity cross-check gate.
// ============================================================================

function buildCsvBudget(csvRows) {
  // Build Map<strainUpper, count> from CSV rows. Mirrors strainSetFromCsv in
  // build-backfill-receipt.js but lives here so processDraftsForCapture can
  // consume/decrement entries per draft (mutable budget).
  const m = new Map();
  for (const r of (csvRows || [])) {
    const s = String(r.strain || '').toUpperCase();
    if (!s) continue;
    m.set(s, (m.get(s) || 0) + 1);
  }
  return m;
}

function consumeCsvBudget(budget, strainUpper) {
  // Returns true and decrements the count if budget for strainUpper > 0.
  // Returns false when budget is exhausted or the strain is absent.
  const remaining = budget.get(strainUpper) || 0;
  if (remaining <= 0) return false;
  budget.set(strainUpper, remaining - 1);
  return true;
}

// Phase 55B Plan 03: aggregate CSV-verified seeding drafts for a page into one
// seeding_session draft_json shape, ready for commitSeedingSession.
//
// Groups by (parentValue::speciesUpper) key. Emits the nested {value:...} shape
// that commitSeedingSession reads at g.parent.value / g.species.value / g.qty.value /
// g.child_block_names.value (lines 153-156 of commit-seeding-session.js).
//
// Known limitation: a session spanning two pages yields two separate group assets
// (one per aggregateSeedingDraftsToSessionJson call). This is accepted for the
// first backfill corpus run; a cross-page merge pass is a future follow-on.
function aggregateSeedingDraftsToSessionJson(verifiedDrafts, { event_date } = {}) {
  // Map from groupKey -> {parent, species, qty, childBlockNames}
  const groupMap = new Map();

  for (const draft of (verifiedDrafts || [])) {
    const dj = (draft && draft.draft_json) || {};

    // Parent: prefer parent_batch_name (D-11 normalized), then parent.value, then parent string.
    const parentValue = dj.parent_batch_name
      || (dj.parent && typeof dj.parent === 'object' && dj.parent.value)
      || (typeof dj.parent === 'string' ? dj.parent : null)
      || 'NO_PARENT';

    // Species: prefer species_code, then species.value, then other fallbacks.
    const rawSpecies = dj.species_code
      || (dj.species && typeof dj.species === 'object' && dj.species.value)
      || (typeof dj.species === 'string' ? dj.species : null)
      || dj.strain
      || dj.fungi_type
      || '';
    const speciesUpper = String(rawSpecies).toUpperCase();

    const groupKey = parentValue + '::' + speciesUpper;

    if (!groupMap.has(groupKey)) {
      groupMap.set(groupKey, { parent: parentValue, species: speciesUpper, qty: 0, childBlockNames: [] });
    }
    const g = groupMap.get(groupKey);
    g.qty += (typeof dj.qty === 'number' ? dj.qty : 1);
    if (dj.block_name) g.childBlockNames.push(dj.block_name);
  }

  const groups = [];
  for (const g of groupMap.values()) {
    groups.push({
      parent: { value: g.parent },
      species: { value: g.species },
      qty: { value: g.qty },
      child_block_names: { value: g.childBlockNames },
    });
  }

  return {
    type: 'seeding_session',
    event_date,
    groups,
  };
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
  curatedStrains,
  csvRowsForPage, csvBudget,
  // pageDate: ISO date string for the page (e.g. '2025-02-01'). Used as
  // event_date when synthesizing the seeding_session draft_json for session
  // dispatch. Derived from the corpus filename when not provided by the caller.
  pageDate,
}) {
  // Hard re-assertion per T-54-05.
  assertSantiInLoop(opts);

  const { resolveStrain } = require('../src/farmos/strain-resolver');
  const db = extractionDb || require('../src/extraction/extraction-db');
  const router = commitRouter || require('../src/farmos/commits/commit-router');
  const drafts = await db.getDraftsForCapture(pool, captureId);
  const commits = [];
  // Collection of held unknown codes: [{ code, nearest, draftIds }].
  // Accumulated across drafts in this capture; caller merges across pages.
  const heldUnknownCodes = [];

  // Phase 55B Plan 03 Task 2: Staging list for CSV-verified seeding drafts that
  // will be aggregated into ONE seeding_session commit after the per-draft loop.
  // Only populated when opts.bulkBackfill=true AND csvRowsForPage is defined
  // (fidelity gate active). Each element is { draft, commitIndex } where
  // commitIndex is the index in commits[] reserved for this draft's attribution.
  //
  // Cross-page limitation: a session spanning two pages yields two separate
  // group assets (one per processDraftsForCapture call). This is accepted for
  // the first backfill corpus run; a cross-page merge pass is a future follow-on.
  const verifiedSeedingDrafts = [];

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

    // 1a. Strain-gate (T-54.1-03): resolve the extracted strain code against the
    // curated set BEFORE flipping to confirmed. An unknown code is held as
    // needs_review with reason 'strain_unknown_pending_confirm' and never committed.
    // Only fires when curatedStrains is non-empty (empty = legacy/hermetic test mode).
    if (curatedStrains && curatedStrains.length > 0) {
      const dj = (draft && draft.draft_json) || {};
      const rawStrain = dj.species_code || dj.species || dj.strain || dj.fungi_type || null;
      if (rawStrain) {
        const resolved = resolveStrain(rawStrain, curatedStrains);
        if (!resolved.known) {
          // Hold this draft -- do NOT flip to confirmed, do NOT commit.
          await db.updateDraftStatus(pool, draftId, 'needs_review', {
            needs_review_reason: 'strain_unknown_pending_confirm',
          });
          // Accumulate into the per-run held-codes collection (deduped by code in main()).
          let existing = heldUnknownCodes.find((h) => h.code === resolved.code);
          if (!existing) {
            existing = { code: resolved.code, nearest: resolved.nearest || null, draftIds: [] };
            heldUnknownCodes.push(existing);
          }
          existing.draftIds.push(draftId);
          entry = {
            draftId, log_type: logType,
            ok: 'held', reason: 'strain_unknown_pending_confirm',
            strain_codes: [resolved.code],
            block_name: dj.block_name || null,
            asset_ids: [], log_ids: [],
          };
          commits.push(entry);
          if (summariesFd != null) {
            appendSummaryLine(summariesFd, buildSummaryLine({
              ts, page: path.basename(pagePath), captureId, draftId, logType,
              ok: false, assetCount: 0, logCount: 0, reason: 'strain_unknown_pending_confirm',
            }));
          }
          continue;
        }
      }
    }

    // 1b. Fidelity cross-check gate (T-55B-03): compare extracted strain against
    // the per-page CSV reading BEFORE committing. Only active inside bulkBackfill.
    // Three branches:
    //   (a) no CSV rows for this page -> hold everything (fidelity_cross_check_no_csv)
    //   (b) seeding/seeding_session with strain not in budget -> hold (fidelity_cross_check_unverified)
    //   (c) seeding/seeding_session with strain verified -> consume budget, fall through
    //   (d) non-seeding on CSV-covered page -> hold (fidelity_cross_check_nonseeding)
    if (opts.bulkBackfill === true && csvRowsForPage !== undefined) {
      const dj = (draft && draft.draft_json) || {};
      const isSeedingDraft = logType === 'seeding' || logType === 'seeding_session';

      if (!csvRowsForPage || csvRowsForPage.length === 0) {
        // Branch (a): no CSV coverage for this page.
        await db.updateDraftStatus(pool, draftId, 'needs_review', {
          needs_review_reason: 'fidelity_cross_check_no_csv',
        });
        entry = {
          draftId, log_type: logType,
          ok: 'held', reason: 'fidelity_cross_check_no_csv',
          strain_codes: [],
          block_name: dj.block_name || null,
          asset_ids: [], log_ids: [],
        };
        commits.push(entry);
        if (summariesFd != null) {
          appendSummaryLine(summariesFd, buildSummaryLine({
            ts, page: path.basename(pagePath), captureId, draftId, logType,
            ok: false, assetCount: 0, logCount: 0, reason: 'fidelity_cross_check_no_csv',
          }));
        }
        continue;
      } else if (isSeedingDraft) {
        // Branch (b/c): seeding draft on a CSV-covered page.
        const rawStrain = dj.species_code || dj.species || dj.strain || dj.fungi_type || null;
        const strainUpper = rawStrain ? String(rawStrain).toUpperCase() : null;
        const budget = csvBudget || new Map();
        const verified = strainUpper && consumeCsvBudget(budget, strainUpper);
        if (!verified) {
          // Branch (b): strain absent from CSV or budget exhausted.
          await db.updateDraftStatus(pool, draftId, 'needs_review', {
            needs_review_reason: 'fidelity_cross_check_unverified',
          });
          entry = {
            draftId, log_type: logType,
            ok: 'held', reason: 'fidelity_cross_check_unverified',
            strain_codes: strainUpper ? [strainUpper] : [],
            block_name: dj.block_name || null,
            asset_ids: [], log_ids: [],
          };
          commits.push(entry);
          if (summariesFd != null) {
            appendSummaryLine(summariesFd, buildSummaryLine({
              ts, page: path.basename(pagePath), captureId, draftId, logType,
              ok: false, assetCount: 0, logCount: 0, reason: 'fidelity_cross_check_unverified',
            }));
          }
          continue;
        }
        // Branch (c): budget consumed -> stage for session aggregation (bulkBackfill).
        // The draft is confirmed (individual flip below), but its commit entry is
        // deferred: we collect all CSV-verified seeding drafts for the page and dispatch
        // ONE seeding_session after the per-draft loop (SESSION-01).
        const commitIndex = commits.length;
        const dj_c = (draft && draft.draft_json) || {};
        const strain_c = dj_c.species_code || dj_c.species || dj_c.strain || dj_c.fungi_type || null;
        // Flip draft to 'confirmed' now so the row is in the right state regardless of
        // the session dispatch outcome (Pitfall 4 rollback will set it back if needed).
        const flipC = await flipDraftToConfirmed(pool, draftId, { extractionDb: db });
        if (!flipC || flipC.ok !== true) {
          // Flip failed -- treat as per-draft failure; do NOT stage for session.
          const badEntry = {
            draftId, log_type: logType, ok: false, asset_ids: [], log_ids: [],
            reason: `draft_flip_failed: ${(flipC && flipC.reason) || 'unknown'}`,
          };
          commits.push(badEntry);
          if (summariesFd != null) {
            appendSummaryLine(summariesFd, buildSummaryLine({
              ts, page: path.basename(pagePath), captureId, draftId, logType,
              ok: false, assetCount: 0, logCount: 0, reason: badEntry.reason,
            }));
          }
          continue;
        }
        // Reserve a placeholder in commits[]; filled after session dispatch.
        commits.push({ draftId, log_type: logType, _pending_session: true, asset_ids: [], log_ids: [],
          strain_codes: strain_c ? [String(strain_c).toUpperCase()] : [],
          block_name: dj_c.block_name || null,
        });
        verifiedSeedingDrafts.push({ draft, commitIndex });
        continue;
      } else {
        // Branch (d): non-seeding draft on a CSV-covered page.
        await db.updateDraftStatus(pool, draftId, 'needs_review', {
          needs_review_reason: 'fidelity_cross_check_nonseeding',
        });
        entry = {
          draftId, log_type: logType,
          ok: 'held', reason: 'fidelity_cross_check_nonseeding',
          strain_codes: [],
          block_name: dj.block_name || null,
          asset_ids: [], log_ids: [],
        };
        commits.push(entry);
        if (summariesFd != null) {
          appendSummaryLine(summariesFd, buildSummaryLine({
            ts, page: path.basename(pagePath), captureId, draftId, logType,
            ok: false, assetCount: 0, logCount: 0, reason: 'fidelity_cross_check_nonseeding',
          }));
        }
        continue;
      }
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

  // Phase 55B Plan 03 Task 2: session dispatch for CSV-verified seeding drafts.
  // If any verified seeding drafts were staged, aggregate them into ONE
  // seeding_session and dispatch it through the commit-router.
  //
  // sessionPagePaths: the page path(s) for the session. The synthetic capture has
  // attachment_paths:[pagePath] (buildSyntheticCapture ~line 189); we use pagePath
  // directly here since each processDraftsForCapture call handles one page.
  if (opts.bulkBackfill && verifiedSeedingDrafts.length > 0) {
    const constituentDrafts = verifiedSeedingDrafts.map((v) => v.draft);
    const constituentIndices = verifiedSeedingDrafts.map((v) => v.commitIndex);
    const sessionJson = aggregateSeedingDraftsToSessionJson(constituentDrafts, {
      event_date: pageDate || null,
    });
    // Synthetic in-memory draft — never persisted. The log_type field tells the
    // commit-router to route this to commitSeedingSession.
    const syntheticDraft = {
      id: `synthetic-session-${captureId}`,
      log_type: 'seeding_session',
      draft_json: sessionJson,
    };
    let sessionResult;
    try {
      sessionResult = await router.commit(client, syntheticDraft, {
        auditLogger: { logCommit: async () => {} },
        createMissingFungiType: false,
        sessionPagePaths: pagePath ? [pagePath] : [],
      });
    } catch (e) {
      sessionResult = { ok: false, reason: `session_commit_threw: ${e.message}`, asset_ids: [], log_ids: [] };
    }

    const ts = new Date().toISOString();

    if (sessionResult && sessionResult.ok) {
      // Session committed successfully. The session minted its assets/logs ONCE, so credit
      // the full asset_ids/log_ids to a single representative constituent (the first); the
      // rest are recorded as ok session members carrying no assets. Copying the whole set
      // onto every constituent inflates the receipt's asset/log totals and trips the
      // duplicate-asset detector (same UUID under N block_names = false positive). The
      // member drafts keep their strain_codes/block_name so the CSV diff is unaffected.
      verifiedSeedingDrafts.forEach(({ draft: cDraft, commitIndex }, i) => {
        const cDj = (cDraft && cDraft.draft_json) || {};
        const cStrain = cDj.species_code || cDj.species || cDj.strain || cDj.fungi_type || null;
        const isRep = i === 0;
        const cAssetIds = isRep ? (sessionResult.asset_ids || []) : [];
        const cLogIds = isRep ? (sessionResult.log_ids || []) : [];
        commits[commitIndex] = {
          draftId: cDraft.id,
          log_type: 'seeding',
          ok: true,
          asset_ids: cAssetIds,
          log_ids: cLogIds,
          reason: sessionResult.reason,
          session_member: !isRep,
          strain_codes: cStrain ? [String(cStrain).toUpperCase()] : [],
          block_name: cDj.block_name || null,
        };
        if (summariesFd != null) {
          appendSummaryLine(summariesFd, buildSummaryLine({
            ts, page: path.basename(pagePath), captureId, draftId: cDraft.id, logType: 'seeding',
            ok: true, assetCount: cAssetIds.length, logCount: cLogIds.length,
          }));
        }
      });
    } else {
      // Session commit failed. Pitfall 4 rollback: flip all constituents back to
      // needs_review so they are visibly absent from the session view and can be
      // manually reviewed or retried.
      const rollbackReason = (sessionResult && sessionResult.reason) || 'session_commit_failed';
      for (const { draft: cDraft, commitIndex } of verifiedSeedingDrafts) {
        const cDj = (cDraft && cDraft.draft_json) || {};
        const cStrain = cDj.species_code || cDj.species || cDj.strain || cDj.fungi_type || null;
        await db.updateDraftStatus(pool, cDraft.id, 'needs_review', {
          needs_review_reason: 'session_commit_failed',
        });
        commits[commitIndex] = {
          draftId: cDraft.id,
          log_type: 'seeding',
          ok: false,
          reason: 'session_commit_failed',
          session_commit_reason: rollbackReason,
          asset_ids: [],
          log_ids: [],
          strain_codes: cStrain ? [String(cStrain).toUpperCase()] : [],
          block_name: cDj.block_name || null,
        };
        if (summariesFd != null) {
          appendSummaryLine(summariesFd, buildSummaryLine({
            ts, page: path.basename(pagePath), captureId, draftId: cDraft.id, logType: 'seeding',
            ok: false, assetCount: 0, logCount: 0, reason: 'session_commit_failed',
          }));
        }
      }
    }
  }

  return { drafts, commits, heldUnknownCodes };
}

function computeRunDir(runId) {
  return path.join(RUN_DIR_ROOT, runId);
}

// ============================================================================
// Phase 54.1 Plan 02 Task 2: batched Signal message for unknown strains.
// ============================================================================

/**
 * Build a farmer-facing Signal message listing all unknown strain codes collected
 * during the run, with nearest-known suggestions for each.
 *
 * Rules: no em-dashes ([[feedback_no_em_dashes_in_artifacts]]), plain ASCII only.
 * @param {{ code: string, nearest: string|null, draftIds: string[] }[]} unknowns
 * @returns {string}
 */
function buildUnknownStrainMessage(unknowns) {
  const codeList = unknowns.map((u) => u.code).join(', ');
  const suggestions = unknowns
    .filter((u) => u.nearest)
    .map((u) => `${u.code} -> ${u.nearest}`)
    .join(', ');
  const hint = suggestions
    ? `Nearest known: ${suggestions}.`
    : '';
  // No em-dashes; use plain ASCII punctuation.
  const msg = `Backfill found unknown strain codes: ${codeList}. Real new strains, or typos? ${hint} Reply: NEW <code> to mint, or <bad>=<good> to remap.`;
  // Strip any stray em-dashes from upstream data that may have leaked into code/nearest values.
  return msg.replace(/[–—]/g, '--');
}

/**
 * After the page loop, if any unknown strain codes were held: send ONE batched
 * Signal message and write pending-strain-confirm.json to runDir.
 *
 * Best-effort: a send failure is logged but never throws; the pending file is
 * always written so the follow-up pass can run regardless.
 *
 * @param {{ unknowns, runDir, runId, signalSend, recipient, logger }} opts
 */
async function sendUnknownStrainBatch({ unknowns, runDir, runId, signalSend, recipient, logger }) {
  if (!unknowns || unknowns.length === 0) return;

  const pendingPath = path.join(runDir, 'pending-strain-confirm.json');
  const pending = { runId, unknowns };

  // Write pending file FIRST so the follow-up pass can run even if send fails.
  try {
    fs.mkdirSync(runDir, { recursive: true });
    fs.writeFileSync(pendingPath, JSON.stringify(pending, null, 2) + '\n');
  } catch (e) {
    logger && logger.warn && logger.warn(`[backfill] pending-strain-confirm.json write failed: ${e.message}`);
  }

  // Build message and send -- best-effort.
  const msg = buildUnknownStrainMessage(unknowns);
  if (signalSend && recipient) {
    try {
      await signalSend(msg, { to: recipient, intent: 'ask_back', sourceModule: 'backfill-notebook' });
    } catch (e) {
      logger && logger.warn && logger.warn(`[backfill] strain-confirm signal send failed: ${e.message}`);
    }
  }
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

  // --all-pages overrides --limit: select the full corpus.
  if (opts.allPages) opts.limit = Infinity;

  // Prod-guard first when URL is present. Missing URL is fine on --dry-run.
  // BACK-11: an explicit, operator-authorized promotion may opt in to a PROD
  // write via --allow-prod-write, but ONLY together with --farmer=santi. The
  // flag alone (without santi) does NOT bypass the guard.
  const prodWriteAuthorized = opts.allowProdWrite && opts.farmer === 'santi';
  if (env.FARMOS_URL && !prodWriteAuthorized) {
    try {
      assertProdGuard(env.FARMOS_URL);
    } catch (e) {
      logger.error && logger.error(
        `REFUSING: prod-guard on FARMOS_URL=${env.FARMOS_URL}. Pass --allow-prod-write --farmer=santi to authorize a PROD promotion.`
      );
      return { code: 3 };
    }
  }
  if (prodWriteAuthorized && env.FARMOS_URL) {
    logger.warn && logger.warn(
      `[backfill] PROD WRITE AUTHORIZED (--allow-prod-write --farmer=santi): committing to ${env.FARMOS_URL}`
    );
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
    const missing = ['FARMOS_URL', 'FARMOS_USERNAME', 'FARMOS_PASSWORD', 'DATABASE_URL', 'ANTHROPIC_API_KEY']
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
  const startMs = Date.now();
  // Phase 55B fix (2026-06-14): wire the fidelity-gate inputs into the real driver.
  // Without csvRowsForPage the gate guard (csvRowsForPage !== undefined) is false and
  // every draft auto-confirms -- the gate was a silent no-op (the 2026-06-14 re-smoke
  // reproduced the POY-committed-as-KOY misattribution). loadCsvForPage returns [] for a
  // page with no resolvable CSV date, which the gate treats as hold-all
  // (fidelity_cross_check_no_csv). The budget is per-page (consumed per verified draft).
  const { loadCsvForPage, pageDateForImage } = require('./build-backfill-receipt');
  const csvPath = env.MUSHROOM_LOG_CSV || '/mnt/slime-kingdom/shared/mushdatadump/mushroom_log.csv';
  try {
    for (const page of selected) {
      const entry = await dispatchPage({
        pool, pipeline, page, runId, sender, corpusContext, dryRun: false,
      });
      if (entry.ok === true) {
        const pageDate = pageDateForImage(path.basename(page));
        const csvRowsForPage = loadCsvForPage(csvPath, pageDate);
        const csvBudget = buildCsvBudget(csvRowsForPage);
        const { drafts, commits } = await processDraftsForCapture({
          pool, client, captureId: entry.captureId, pagePath: page,
          opts, summariesFd, extractionDb, commitRouter, dryRun: false,
          csvRowsForPage, csvBudget, pageDate,
        });
        entry.draftIds = drafts.map((d) => d.id);
        entry.commits = commits;
        entry.event_date = pageDate; // surface page date for the receipt heading
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
    // artifact (T-54-13 -- repudiation mitigation).
    if (opts.bulkBackfill) {
      try {
        const { buildReceipt } = require('./build-backfill-receipt');
        const csvPath = env.MUSHROOM_LOG_CSV || '/mnt/slime-kingdom/shared/mushdatadump/mushroom_log.csv';
        // BACK-09: full-corpus runs (--all-pages) write a permanent receipt + UUID JSONL
        // to .planning/notes/ so the artifacts are git-tracked. Cycle runs (no --all-pages)
        // keep writing only to the gitignored run-dir.
        let notesReceiptPath;
        let notesJsonlPath;
        if (opts.allPages) {
          const dateStr = (now ? new Date(now) : new Date()).toISOString().slice(0, 10);
          const notesDir = path.resolve(__dirname, '../../../../.planning/notes');
          const basename = `${dateStr}-2025-notebook-backfill-receipt`;
          notesReceiptPath = path.join(notesDir, `${basename}.md`);
          notesJsonlPath = path.join(notesDir, `${basename}.jsonl`);
        }
        buildReceipt({
          runDir,
          runSummary,
          csvPath,
          runId,
          cycleNumber: opts.cycle,
          farmosUrl: env.FARMOS_URL,
          elapsedSec: Math.round((Date.now() - startMs) / 1000),
          notesReceiptPath,
          notesJsonlPath,
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
  buildCsvBudget,
  consumeCsvBudget,
  aggregateSeedingDraftsToSessionJson,
  flipDraftToConfirmed,
  buildSummaryLine,
  openSummariesLog,
  appendSummaryLine,
  processDraftsForCapture,
  computeRunDir,
  DRAFT_STATUS_CONFIRMED,
  RUN_DIR_ROOT,
  // Plan 54.1-02 Task 2
  buildUnknownStrainMessage,
  sendUnknownStrainBatch,
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
