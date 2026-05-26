'use strict';

// Phase 54.1 Plan 02 Task 3: follow-up confirmed-mint + remap + commit pass.
//
// CLI:
//   node scripts/backfill-confirm-strains.js --run-id=<id> --farmer=santi --reply="NEW LIM; SHITAKE=SHI"
//
// Flags:
//   --run-id=<id>    Required. The backfill run id whose pending-strain-confirm.json to process.
//   --farmer=<name>  Required. Must be 'santi' (santi-only gate, same as backfill-notebook).
//   --reply=<text>   Required. Farmer reply text, e.g. "NEW LIM; SHITAKE=SHI".
//
// Env:
//   FARMOS_URL       Required; dev-only (prod-guard blocks :8082 / 'prod').
//   DATABASE_URL     Required.
//   FARMOS_USERNAME, FARMOS_PASSWORD  Required for real runs.
//
// Exit codes:
//   0   ok
//   3   prod-guard tripped
//   4   farmer-gate (not santi)
//   5   missing required arg (--run-id or --reply)
//   7   pending-strain-confirm.json not found for the given run-id

const fs = require('fs');
const path = require('path');

const { assertProdGuard, assertFarmerGate, RUN_DIR_ROOT } = require('./backfill-notebook');
const { resolveStrain } = require('../src/farmos/strain-resolver');

const PENDING_FILENAME = 'pending-strain-confirm.json';

// ============================================================================
// parseStrainReply
// ============================================================================

/**
 * Parse a farmer reply string into mint and remap instructions.
 *
 * Accepted token forms:
 *   NEW <code>      -- confirm a new strain term should be minted
 *   <bad>=<good>    -- remap a typo/variant to a canonical code
 *
 * Tokens are separated by whitespace, semicolons, or commas.
 * Unrecognized tokens are silently ignored.
 *
 * @param {string} text
 * @returns {{ mint: string[], remap: Record<string,string> }}
 */
function parseStrainReply(text) {
  const mint = [];
  const remap = {};
  if (!text || typeof text !== 'string') return { mint, remap };

  // Split on whitespace / semicolons / commas.
  const tokens = text.split(/[\s;,]+/).filter(Boolean);

  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i].toUpperCase();
    if (t === 'NEW') {
      // Next token is the code to mint.
      const code = tokens[++i];
      if (code) mint.push(code.toUpperCase());
      continue;
    }
    // <bad>=<good>
    const eqIdx = t.indexOf('=');
    if (eqIdx > 0) {
      const bad = t.slice(0, eqIdx);
      const good = t.slice(eqIdx + 1);
      if (bad && good) remap[bad] = good;
      continue;
    }
    // Unrecognized -- ignore.
  }

  return { mint, remap };
}

// ============================================================================
// applyStrainConfirmations
// ============================================================================

/**
 * Apply the parsed farmer reply to the held drafts from pending-strain-confirm.json.
 *
 * For each confirmed-new code (in `parsed.mint` AND in `pending.unknowns`):
 *   - Call ensureFungiTypeUuid(client, code, {create:true}) to mint the term.
 *   - Flip held drafts to 'confirmed' (reason: 'strain_confirmed_backfill').
 *   - Call router.commit with {createMissingFungiType:true}.
 *
 * For each remap correction (in `parsed.remap` AND in `pending.unknowns`):
 *   - Validate remap target is a curated code via resolveStrain; reject if not.
 *   - Rewrite draft_json strain to the canonical code (no mint).
 *   - Flip held drafts to 'confirmed' (reason: 'strain_confirmed_backfill').
 *   - Call router.commit with {createMissingFungiType:true}.
 *
 * Anti-injection: codes in the reply but NOT in pending are ignored.
 * Non-curated remap targets are rejected (logged, not applied).
 *
 * @param {{ pending, parsed, client, pool, extractionDb, commitRouter, curatedStrains, fungiTypeCache, logger }} opts
 * @returns {{ committed: string[], rejected: string[], errors: string[] }}
 */
async function applyStrainConfirmations({
  pending,
  parsed,
  client,
  pool,
  extractionDb,
  commitRouter,
  curatedStrains,
  fungiTypeCache,
  logger,
}) {
  const log = logger || console;
  const committed = [];
  const rejected = [];
  const errors = [];

  const db = extractionDb || require('../src/extraction/extraction-db');
  const router = commitRouter || require('../src/farmos/commits/commit-router');
  const cache = fungiTypeCache || require('../src/farmos/fungi-type-cache');

  const pendingCodes = new Set((pending.unknowns || []).map((u) => u.code));

  // Build a map from code -> draftIds for easy lookup.
  const codeToDraftIds = {};
  for (const u of (pending.unknowns || [])) {
    codeToDraftIds[u.code] = u.draftIds || [];
  }

  // Process confirmed-new codes (mint path).
  for (const code of (parsed.mint || [])) {
    if (!pendingCodes.has(code)) {
      // Anti-injection: code not actually held -- ignore.
      log.warn && log.warn(`[confirm-strains] anti-injection: ${code} not in pending; skipping`);
      continue;
    }
    // Mint the term.
    try {
      await cache.ensureFungiTypeUuid(client, code, { create: true });
    } catch (e) {
      errors.push(`mint_threw:${code}:${e.message}`);
      log.warn && log.warn(`[confirm-strains] ensureFungiTypeUuid threw for ${code}: ${e.message}`);
    }

    // Flip and commit each held draft for this code.
    for (const draftId of (codeToDraftIds[code] || [])) {
      await _flipAndCommit({ draftId, pool, client, db, router, log, committed, errors });
    }
  }

  // Process remap corrections.
  for (const [bad, good] of Object.entries(parsed.remap || {})) {
    if (!pendingCodes.has(bad)) {
      log.warn && log.warn(`[confirm-strains] anti-injection: ${bad} not in pending; skipping`);
      continue;
    }
    // Validate remap target is curated.
    const resolved = resolveStrain(good, curatedStrains || []);
    if (!resolved.known) {
      log.warn && log.warn(`[confirm-strains] rejected remap ${bad}=${good}: target not curated`);
      rejected.push(bad);
      continue;
    }

    // Rewrite draft_json for each held draft, then commit.
    for (const draftId of (codeToDraftIds[bad] || [])) {
      let draft;
      try {
        draft = await db.getDraftById(pool, draftId);
      } catch (e) {
        errors.push(`getDraftById_threw:${draftId}:${e.message}`);
        continue;
      }
      if (!draft) {
        errors.push(`draft_not_found:${draftId}`);
        continue;
      }
      // Rewrite strain field in draft_json to the canonical code.
      const dj = Object.assign({}, draft.draft_json || {});
      if (dj.species_code !== undefined) dj.species_code = good;
      else if (dj.species !== undefined) dj.species = good;
      else if (dj.strain !== undefined) dj.strain = good;
      else if (dj.fungi_type !== undefined) dj.fungi_type = good;
      else dj.species_code = good;

      // Persist the rewritten draft_json before committing.
      try {
        await db.updateDraftStatus(pool, draftId, 'confirmed', {
          needs_review_reason: 'strain_confirmed_backfill',
          draft_json: dj,
        });
      } catch (e) {
        errors.push(`update_threw:${draftId}:${e.message}`);
        continue;
      }

      // Use the rewritten draft for commit.
      const remappedDraft = Object.assign({}, draft, { draft_json: dj });
      try {
        await router.commit(client, remappedDraft, {
          auditLogger: { logCommit: async () => {} },
          createMissingFungiType: true,
        });
        committed.push(draftId);
      } catch (e) {
        errors.push(`commit_threw:${draftId}:${e.message}`);
      }
    }
  }

  return { committed, rejected, errors };
}

/**
 * Flip a held draft to 'confirmed' and commit it via commit-router.
 * @private
 */
async function _flipAndCommit({ draftId, pool, client, db, router, log, committed, errors }) {
  try {
    await db.updateDraftStatus(pool, draftId, 'confirmed', {
      needs_review_reason: 'strain_confirmed_backfill',
    });
  } catch (e) {
    errors.push(`update_threw:${draftId}:${e.message}`);
    log.warn && log.warn(`[confirm-strains] updateDraftStatus threw for ${draftId}: ${e.message}`);
    return;
  }

  let draft;
  try {
    draft = await db.getDraftById(pool, draftId);
  } catch (e) {
    errors.push(`getDraftById_threw:${draftId}:${e.message}`);
    return;
  }

  if (!draft) {
    errors.push(`draft_not_found:${draftId}`);
    return;
  }

  try {
    await router.commit(client, draft, {
      auditLogger: { logCommit: async () => {} },
      createMissingFungiType: true,
    });
    committed.push(draftId);
  } catch (e) {
    errors.push(`commit_threw:${draftId}:${e.message}`);
  }
}

// ============================================================================
// main CLI
// ============================================================================

function parseArgs(argv) {
  const opts = { runId: null, farmer: null, reply: null };
  for (const arg of argv) {
    const eq = arg.indexOf('=');
    if (eq < 0) continue;
    const k = arg.slice(0, eq);
    const v = arg.slice(eq + 1);
    if (k === '--run-id') opts.runId = v;
    else if (k === '--farmer') opts.farmer = v;
    else if (k === '--reply') opts.reply = v;
  }
  return opts;
}

async function main(argv = process.argv.slice(2), {
  env = process.env,
  logger = console,
  poolFactory = null,
  clientFactory = null,
  extractionDb = null,
  commitRouter = null,
  fungiTypeCache = null,
  curatedStrains = null,
} = {}) {
  const opts = parseArgs(argv);

  // Prod-guard.
  if (env.FARMOS_URL) {
    try {
      assertProdGuard(env.FARMOS_URL);
    } catch (e) {
      logger.error && logger.error(`REFUSING: prod-guard on FARMOS_URL=${env.FARMOS_URL}.`);
      return { code: 3 };
    }
  }

  // Farmer-gate: santi-only.
  try {
    assertFarmerGate({ bulkBackfill: true, farmer: opts.farmer });
  } catch (e) {
    logger.error && logger.error(`REFUSING: --farmer must be santi; got ${JSON.stringify(opts.farmer)}.`);
    return { code: 4 };
  }

  if (!opts.runId || !opts.reply) {
    logger.error && logger.error('MISSING: --run-id and --reply are required.');
    return { code: 5 };
  }

  // Locate pending-strain-confirm.json.
  const runDir = require('./backfill-notebook').computeRunDir(opts.runId);
  const pendingPath = path.join(runDir, PENDING_FILENAME);
  if (!fs.existsSync(pendingPath)) {
    logger.error && logger.error(`MISSING: pending file not found at ${pendingPath}`);
    return { code: 7 };
  }

  let pending;
  try {
    pending = JSON.parse(fs.readFileSync(pendingPath, 'utf8'));
  } catch (e) {
    logger.error && logger.error(`PARSE_ERROR: ${pendingPath}: ${e.message}`);
    return { code: 1 };
  }

  const parsed = parseStrainReply(opts.reply);
  logger.log && logger.log(`[confirm-strains] run=${opts.runId} mint=${parsed.mint.join(',')} remap=${JSON.stringify(parsed.remap)}`);

  // Load curated set.
  const strains = curatedStrains || (() => {
    try {
      return require('../src/config').strains || [];
    } catch (_e) { return []; }
  })();

  // Bootstrap pool + client.
  let pool = null;
  let client = null;
  if (poolFactory) {
    try { pool = await poolFactory({ env, logger }); } catch (e) {
      logger.error && logger.error(`[confirm-strains] poolFactory failed: ${e.message}`);
      return { code: 1 };
    }
  }
  if (clientFactory) {
    try { client = await clientFactory({ env, logger }); } catch (e) {
      logger.error && logger.error(`[confirm-strains] clientFactory failed: ${e.message}`);
      return { code: 1 };
    }
  }

  const result = await applyStrainConfirmations({
    pending,
    parsed,
    client,
    pool,
    extractionDb,
    commitRouter,
    curatedStrains: strains,
    fungiTypeCache,
    logger,
  });

  logger.log && logger.log(`[confirm-strains] committed=${result.committed.length} rejected=${result.rejected.length} errors=${result.errors.length}`);
  return { code: 0, ...result };
}

module.exports = {
  parseStrainReply,
  applyStrainConfirmations,
  main,
};

if (require.main === module) {
  main().then((r) => process.exit(r.code || 0)).catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
