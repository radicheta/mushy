'use strict';

// 54.2-LIVE-FIRE harness -- one-shot driver for the Phase 54.2
// (strain-detection-trigger) human checkpoint (54.2-02 task 5/5).
//
// The checkpoint has two halves, both gated on real DEV farmOS (:18080):
//
//   (A) An admin must DELETE the bogus dev `fungi_type` terms minted by 54.1
//       testing (LIM / SHIITAKE / OYS / CAR -- and anything else non-curated).
//       They read as "known" and SUPPRESS the strain ask in dev. The bot
//       account gets 403 on DELETE, so this needs admin creds (or the Drupal UI).
//
//   (B) With those gone, an unknown strain code must resolve as a clean
//       `fungi_type_not_found` (-> ask), a curated code must resolve `ok:true`
//       (-> no ask), and the ask-back line must render. That's the live farmOS
//       seam the 64 hermetic tests cannot cover.
//
// This script makes the human step one-shot: it inventories the live vocab,
// flags every non-curated term with its UUID, optionally deletes them, and
// probes the live existence-gate that `maybeHoldForStrainConfirm` depends on
// (pipeline.js:229 -> fungi-type-cache.getFungiTypeUuid). PASS/FAIL is printed;
// no phone required for the farmOS-facing half.
//
// The remaining truly-manual bit (farmer receives the Signal ask-back, replies
// YES, term upserts + commits) still needs a human + phone -- but this script
// removes every farmOS-side ambiguity and gives a go/no-go before you bother.
//
// Modes (combine freely; default = --inventory + --probe, both read-only):
//   --inventory   List all fungi_type terms; flag non-curated (bogus) ones.
//   --probe       Live existence-gate probe; PASS only when the gate is clean.
//   --delete      DELETE every bogus term (needs admin creds; bot 403s).
//
// Env:
//   FARMOS_URL        DEV ONLY -- prod-guard refuses :8082 / 'prod'.
//   FARMOS_USERNAME   bot for --inventory/--probe; ADMIN for --delete.
//   FARMOS_PASSWORD
//
// Exit codes:
//   0  ok (inventory/delete fine; probe -- if run -- PASSED)
//   2  probe FAILED (gate not clean: bogus terms remain, or unknown resolved known)
//   3  prod-guard tripped
//   4  delete blocked (403 -- needs admin creds)
//   5  missing creds

const { createFarmosClient } = require('../src/farmos/client');
const { getFungiTypeUuid, _clear } = require('../src/farmos/fungi-type-cache');
const { nearestKnown } = require('../src/farmos/strain-resolver');
const { renderStrainAskBack } = require('../src/confirm/strain-ask-back');

// 14 active Mossrock strain codes. Source-of-truth: tenants/mossrock/strains.yaml
// (== [[mossrock_active_strain_codes]] memory). Hardcoded here matching the
// seed-dev-farmos-taxonomies.js precedent; any term NOT in this set is bogus.
const CURATED = [
  'SHI', 'SH2', 'KOY', 'MAI', 'MALI', 'KOS', 'DT',
  'CAS', 'CAZ', 'WIN', 'ALM', 'MOR', 'BP', 'LIMA',
];
const CURATED_SET = new Set(CURATED);

function assertProdGuard(url) {
  const lower = String(url).toLowerCase();
  if (lower.endsWith(':8082') || lower.includes(':8082/') || lower.includes('prod')) {
    throw new Error(`prod-guard: refusing to run against prod-looking URL: ${url}`);
  }
}

// GET the full fungi_type vocab (one generous page; the vocab is ~14-20 terms).
async function listFungiTypes(client) {
  const r = await client.get('/api/taxonomy_term/fungi_type?page[limit]=100');
  if (!r.ok) {
    throw new Error(`list fungi_type failed: status=${r.status} reason=${r.error || 'http'}`);
  }
  const arr = (r.body && r.body.data) || [];
  return arr.map((t) => ({ name: t.attributes && t.attributes.name, id: t.id }));
}

function classify(terms) {
  const curated = [];
  const bogus = [];
  for (const t of terms) {
    if (CURATED_SET.has(t.name)) curated.push(t);
    else bogus.push(t);
  }
  return { curated, bogus };
}

async function runInventory(client) {
  const terms = await listFungiTypes(client);
  const { curated, bogus } = classify(terms);

  console.log('\n=== Phase A: fungi_type vocab inventory (DEV) ===');
  console.log(`Total terms: ${terms.length}  |  curated: ${curated.length}/${CURATED.length}  |  bogus: ${bogus.length}`);

  const missingCurated = CURATED.filter((c) => !terms.some((t) => t.name === c));
  if (missingCurated.length) {
    console.log(`\n  NOTE: curated codes NOT present in dev vocab: ${missingCurated.join(', ')}`);
    console.log('  (not a blocker -- they auto-mint on first confirmed use)');
  }

  if (bogus.length === 0) {
    console.log('\n  ✓ No bogus terms. Vocab is clean -- the dev ask is not suppressed.');
  } else {
    console.log('\n  ⚠ Bogus (non-curated) terms present -- these SUPPRESS the strain ask in dev:');
    for (const t of bogus) console.log(`    - ${t.name.padEnd(12)} ${t.id}`);
    console.log('\n  To remove (admin creds required; bot 403s):');
    console.log('    FARMOS_URL=$FARMOS_URL FARMOS_USERNAME=<admin> FARMOS_PASSWORD=<...> \\');
    console.log('      node scripts/live-fire-strain-54-2.js --delete');
    console.log('  Or delete via Drupal UI: /admin/structure/taxonomy/manage/fungi_type/overview');
  }
  return { terms, curated, bogus };
}

async function runDelete(client, bogus) {
  console.log('\n=== Phase A: deleting bogus fungi_type terms ===');
  if (!bogus.length) {
    console.log('  Nothing to delete.');
    return { deleted: [], blocked: false };
  }
  const deleted = [];
  let blocked = false;
  for (const t of bogus) {
    const r = await client.delete(`/api/taxonomy_term/fungi_type/${t.id}`);
    if (r.ok || r.status === 204) {
      deleted.push(t.name);
      console.log(`  ✓ deleted ${t.name} (${t.id})`);
    } else if (r.status === 403) {
      blocked = true;
      console.log(`  ✗ 403 on ${t.name} -- this account cannot DELETE. Use admin creds.`);
    } else {
      console.log(`  ✗ failed ${t.name}: status=${r.status} ${r.error || ''}`);
    }
  }
  return { deleted, blocked };
}

async function runProbe(client) {
  console.log('\n=== Phase B: live existence-gate probe ===');
  _clear(); // drop any LRU state so every lookup hits live farmOS

  const checks = [];

  // 1. A curated code must resolve ok:true (-> NO ask).
  const knownCode = 'SHI';
  const knownRes = await getFungiTypeUuid(client, knownCode);
  const knownPass = knownRes.ok === true;
  checks.push({
    pass: knownPass,
    line: `curated ${knownCode}: ${knownPass ? 'ok:true (known -> no ask) ✓' : `UNEXPECTED ${JSON.stringify(knownRes)} ✗`}`,
  });

  // 2. A fresh unknown code must resolve clean fungi_type_not_found (-> ask).
  const freshCode = `ZZTEST${Date.now().toString().slice(-6)}`;
  const freshRes = await getFungiTypeUuid(client, freshCode);
  const freshPass = !freshRes.ok && freshRes.reason === 'fungi_type_not_found';
  checks.push({
    pass: freshPass,
    line: `fresh-unknown ${freshCode}: ${freshPass ? 'fungi_type_not_found (-> ask) ✓' : `UNEXPECTED ${JSON.stringify(freshRes)} ✗`}`,
  });

  // 3. No bogus terms may remain (each would resolve ok:true and suppress the ask).
  const terms = await listFungiTypes(client);
  const { bogus } = classify(terms);
  const bogusPass = bogus.length === 0;
  checks.push({
    pass: bogusPass,
    line: bogusPass
      ? 'no bogus terms remain (ask not suppressed) ✓'
      : `${bogus.length} bogus term(s) STILL PRESENT -> ask suppressed: ${bogus.map((b) => b.name).join(', ')} ✗`,
  });

  for (const c of checks) console.log(`  ${c.line}`);

  // Show the farmer-facing ask-back line that an unknown code would produce.
  const sample = renderStrainAskBack(freshCode, nearestKnown(freshCode, CURATED));
  console.log('\n  Sample ask-back the farmer would receive for an unknown code:');
  console.log(sample.split('\n').map((l) => `    | ${l}`).join('\n'));

  const allPass = checks.every((c) => c.pass);
  console.log(`\n  Probe verdict: ${allPass ? 'PASS -- dev gate is clean, ready for the manual phone step' : 'FAIL -- resolve the above before the phone step'}`);
  return allPass;
}

async function main(argv = process.argv.slice(2), env = process.env) {
  const wantInventory = argv.includes('--inventory');
  const wantProbe = argv.includes('--probe');
  const wantDelete = argv.includes('--delete');
  // Default: inventory + probe (both read-only).
  const doInventory = wantInventory || (!wantProbe && !wantDelete);
  const doProbe = wantProbe || (!wantInventory && !wantProbe && !wantDelete);

  const farmosUrl = env.FARMOS_URL;
  const username = env.FARMOS_USERNAME;
  const password = env.FARMOS_PASSWORD;
  if (!farmosUrl || !username || !password) {
    console.error('MISSING: FARMOS_URL + FARMOS_USERNAME + FARMOS_PASSWORD required.');
    return 5;
  }
  try {
    assertProdGuard(farmosUrl);
  } catch (e) {
    console.error(`REFUSING: ${e.message}`);
    return 3;
  }

  const client = createFarmosClient({ farmosUrl, username, password, logger: console });
  console.log(`live-fire-strain-54-2  url=${farmosUrl}  user=${username}`);

  let bogus = [];
  if (doInventory || wantDelete) {
    ({ bogus } = await runInventory(client));
  }

  if (wantDelete) {
    const { blocked } = await runDelete(client, bogus);
    if (blocked) return 4;
    // Re-inventory so the post-delete state is visible.
    await runInventory(client);
  }

  if (doProbe) {
    const pass = await runProbe(client);
    if (!pass) return 2;
  }

  console.log('\nNext (manual, needs phone): drive a real dev capture with an unknown strain');
  console.log('code; confirm HELD (strain_unknown_pending_confirm) + ONE batched ask-back;');
  console.log('reply YES -> term upserts + commits; confirm an infra error does NOT ask.');
  return 0;
}

module.exports = { assertProdGuard, classify, CURATED, main };

if (require.main === module) {
  main()
    .then((code) => process.exit(code))
    .catch((e) => {
      console.error(e);
      process.exit(1);
    });
}
