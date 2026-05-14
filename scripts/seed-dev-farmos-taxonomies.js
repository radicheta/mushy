#!/usr/bin/env node
'use strict';

// Phase 40 Backlog B -- seed dev-farmOS taxonomy terms.
//
// 2026-05-14: rewritten against the Option A hybrid schema agreed with the
// farmOS side. See:
//   /mnt/slime-kingdom/opt/mushy/.planning/notes/2026-05-14-reply-to-farmos-option-A.md
//   /mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-14-reply-to-mushy-fungi-schema.md
//
// Vocab shape (Option A):
//   fungi_type    -- strain codes (matches upstream farm_fungi {bundle}_type
//                    convention: animal_type=breed, plant_type=cultivar,
//                    fungi_type=strain). 14 active Mossrock strains.
//   fungi_xing    -- NEW vocab; structural classifier on fungi bundle.
//                    2 terms: 'block', 'fruit'. No 'batch' -- pre-inoc
//                    substrate isn't a fungi asset (lives in material bundle
//                    or pasteurization log).
//   substrate_type -- vocab content unchanged. Field moves from fungi bundle
//                    to material bundle (config change on farmOS side; this
//                    script only seeds vocab terms).
//
// 'species' vocab is intentionally NOT seeded -- it was a strawman that did
// not survive deliberation.
//
// Idempotent: GETs first, POSTs only missing terms. Safe to re-run.
//
// Vocabulary creation is NOT possible via JSON:API (Drupal config entity).
// 404 on bundle probe => operator must drush / UI-create the vocab first.
//
// Usage:
//   FARMOS_URL=http://10.68.155.50:18080 \
//   FARMOS_USERNAME=... FARMOS_PASSWORD=... \
//   node scripts/seed-dev-farmos-taxonomies.js [--dry-run]

const { createFarmosClient } = require('../src/agents/alerter/src/farmos/client');

// 14 active Mossrock strain codes (confirmed by Don Santiago 2026-05-14).
const FUNGI_TYPE_TERMS = [
  'SHI', 'SH2', 'KOY', 'MAI', 'MALI', 'KOS', 'DT',
  'CAS', 'CAZ', 'WIN', 'ALM', 'MOR', 'BP', 'LIMA',
];

const FUNGI_XING_TERMS = ['block', 'fruit'];

const SUBSTRATE_TYPE_TERMS = [
  'agar_mea',
  'agar_pda',
  'grain_rye',
  'grain_millet',
  'grain_sorghum',
  'sawdust_supplemented',
  'hardwood_log',
  'straw_pasteurized',
  'liquid_culture',
];

const VOCABS = [
  { vocab: 'fungi_type', terms: FUNGI_TYPE_TERMS },
  { vocab: 'fungi_xing', terms: FUNGI_XING_TERMS },
  { vocab: 'substrate_type', terms: SUBSTRATE_TYPE_TERMS },
];

function parseArgs(argv) {
  return { dryRun: argv.includes('--dry-run') };
}

async function listExistingTerms(client, vocab) {
  // Page through; cap at 200 since vocabs are small.
  const r = await client.get(`/api/taxonomy_term/${vocab}?page[limit]=200`);
  if (r.status === 404) return { ok: false, reason: 'bundle_missing', status: 404 };
  if (!r.ok) return { ok: false, reason: 'list_failed', status: r.status, body: r.body };
  const names = new Set();
  const rows = (r.body && r.body.data) || [];
  for (const row of rows) {
    const n = row.attributes && row.attributes.name;
    if (n) names.add(String(n));
  }
  return { ok: true, names };
}

async function createTerm(client, vocab, name) {
  const payload = {
    data: {
      type: `taxonomy_term--${vocab}`,
      attributes: { name },
    },
  };
  const r = await client.post(`/api/taxonomy_term/${vocab}`, payload);
  if (!r.ok) {
    return { ok: false, status: r.status, body: r.body };
  }
  return { ok: true, id: r.body && r.body.data && r.body.data.id };
}

async function seedVocab(client, vocab, terms, { dryRun }) {
  const result = { vocab, existed: [], created: [], failed: [], bundleMissing: false };
  const listed = await listExistingTerms(client, vocab);
  if (!listed.ok) {
    if (listed.reason === 'bundle_missing') {
      result.bundleMissing = true;
      return result;
    }
    result.failed.push({ term: '*list*', status: listed.status });
    return result;
  }
  for (const name of terms) {
    if (listed.names.has(name)) {
      result.existed.push(name);
      continue;
    }
    if (dryRun) {
      result.created.push(name + ' (dry-run)');
      continue;
    }
    const c = await createTerm(client, vocab, name);
    if (c.ok) {
      result.created.push(name);
    } else {
      result.failed.push({ term: name, status: c.status, body: c.body });
    }
  }
  return result;
}

function fmtResult(r) {
  const parts = [];
  parts.push(`  vocab: ${r.vocab}`);
  if (r.bundleMissing) {
    parts.push(`    !! BUNDLE MISSING (404) -- operator must create vocabulary first (drush / admin UI).`);
    return parts.join('\n');
  }
  parts.push(`    existed:  ${r.existed.length}  ${r.existed.join(', ')}`);
  parts.push(`    created:  ${r.created.length}  ${r.created.join(', ')}`);
  if (r.failed.length) {
    parts.push(`    FAILED:   ${r.failed.length}`);
    for (const f of r.failed) {
      parts.push(`      - ${f.term}  status=${f.status}  body=${JSON.stringify(f.body).slice(0, 240)}`);
    }
  }
  return parts.join('\n');
}

async function main() {
  const { dryRun } = parseArgs(process.argv.slice(2));
  const farmosUrl = process.env.FARMOS_URL;
  const username = process.env.FARMOS_USERNAME;
  const password = process.env.FARMOS_PASSWORD;
  if (!farmosUrl || !username || !password) {
    console.error('FATAL: FARMOS_URL / FARMOS_USERNAME / FARMOS_PASSWORD must be set');
    process.exit(2);
  }

  console.log(`[seed] target: ${farmosUrl}`);
  console.log(`[seed] user:   ${username}`);
  console.log(`[seed] mode:   ${dryRun ? 'dry-run' : 'apply'}`);
  console.log('');

  const client = createFarmosClient({ farmosUrl, username, password });

  const results = [];
  for (const { vocab, terms } of VOCABS) {
    const r = await seedVocab(client, vocab, terms, { dryRun });
    results.push(r);
    console.log(fmtResult(r));
    console.log('');
  }

  let exit = 0;
  const anyBundleMissing = results.some((r) => r.bundleMissing);
  const anyFailed = results.some((r) => r.failed.length > 0);
  if (anyBundleMissing) {
    console.error('At least one vocabulary bundle is missing on dev-farmOS.');
    console.error('Create it via drush:  drush vocab-create <vocab>  (or via Admin UI -> Structure -> Taxonomy -> Add).');
    console.error('Required vocab machine names: ' + results.filter((r) => r.bundleMissing).map((r) => r.vocab).join(', '));
    exit = 3;
  }
  if (anyFailed) {
    console.error('At least one term-create call failed -- see "FAILED" sections above.');
    exit = exit || 4;
  }

  if (exit === 0) {
    console.log('OK -- all vocabularies fully seeded.');
  }
  process.exit(exit);
}

main().catch((e) => {
  console.error('FATAL:', e && e.stack || e);
  process.exit(1);
});
