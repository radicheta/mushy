'use strict';

// Phase 54 Plan 04: build-backfill-receipt.js — the single farmer-facing
// document for Cycle 1 / Cycle 2 review (D-08). Reads:
//   - runSummary[]      (in-memory, from backfill-notebook.js dispatch loop)
//   - summaries.log     (audit lines per draft; informational)
//   - responses.jsonl   (paid-LLM evidence; aggregated cost_estimate_usd only)
//   - mushroom_log.csv  (ground truth for IMG_3775..IMG_3861)
// Writes:
//   - <runDir>/receipt.md — markdown, ASCII-only (no em-dashes).
//
// Validates the Phase 51 upsert-by-stable-identity contract via the intra-
// cycle "upsert stability" check (BACK-08 N/A resolution — the original
// May-22-ancestor stub-enrichment check is N/A because those ancestor codes
// are 2026-dated and cannot appear in 2025 paper-log pages).

const fs = require('fs');
const path = require('path');

const ACTIVE_STRAIN_CODES = [
  'SHI', 'SH2', 'KOY', 'MAI', 'MALI', 'KOS',
  'DT', 'CAS', 'CAZ', 'WIN', 'ALM', 'MOR', 'BP', 'LIMA',
];

// ============================================================================
// CSV parsing (minimal — handles double-quote escapes for notes column).
// ============================================================================

function parseCsvLine(line) {
  const out = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const c = line[i];
    if (inQuotes) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i += 1; continue; }
      if (c === '"') { inQuotes = false; continue; }
      cur += c;
      continue;
    }
    if (c === '"') { inQuotes = true; continue; }
    if (c === ',') { out.push(cur); cur = ''; continue; }
    cur += c;
  }
  out.push(cur);
  return out;
}

function parseCsv(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.length > 0);
  if (lines.length === 0) return [];
  const header = parseCsvLine(lines[0]);
  const rows = [];
  for (let i = 1; i < lines.length; i += 1) {
    const fields = parseCsvLine(lines[i]);
    const row = {};
    for (let j = 0; j < header.length; j += 1) row[header[j]] = fields[j] != null ? fields[j] : '';
    rows.push(row);
  }
  return rows;
}

function loadCsvForPage(csvPath, pageDate) {
  if (!csvPath || !pageDate) return [];
  let text;
  try { text = fs.readFileSync(csvPath, 'utf8'); } catch (_e) { return []; }
  const all = parseCsv(text);
  return all.filter((r) => r.page_date === pageDate);
}

// ============================================================================
// CSV diff calculator.
// ============================================================================

function strainSetFromCsv(rows) {
  const m = new Map(); // strain -> count
  for (const r of rows) {
    const s = String(r.strain || '').toUpperCase();
    if (!s) continue;
    m.set(s, (m.get(s) || 0) + 1);
  }
  return m;
}

function strainSetFromCommits(commits) {
  // Each commit corresponds to one draft. We treat each commit's log_type as
  // generating one CSV-equivalent row keyed by strain inferred from the draft.
  // The draft_json's species or block_name carries the strain prefix; commits
  // here carry asset_ids[] but not the strain directly. To make the diff
  // useful, callers should attach `strain_codes:[]` on each commit entry when
  // they have richer per-draft info. Default fallback: empty set.
  const m = new Map();
  for (const c of commits || []) {
    const codes = c.strain_codes || c.strainCodes || [];
    for (const s of codes) {
      const u = String(s || '').toUpperCase();
      if (!u) continue;
      m.set(u, (m.get(u) || 0) + 1);
    }
  }
  return m;
}

function computeCsvDiff({ csvRowsForPage, committedAssets }) {
  // Match by strain code (case-insensitive). Hit = in both, Miss = in CSV only,
  // Extra = in commits only.
  const csvSet = strainSetFromCsv(csvRowsForPage || []);
  const committedSet = strainSetFromCommits(committedAssets || []);
  let hit = 0;
  let miss = 0;
  let extra = 0;
  const missingStrains = [];
  const extraStrains = [];
  for (const [s, n] of csvSet.entries()) {
    if (committedSet.has(s)) {
      hit += Math.min(n, committedSet.get(s));
      const diff = n - committedSet.get(s);
      if (diff > 0) {
        miss += diff;
        missingStrains.push(`${s}(${diff})`);
      }
    } else {
      miss += n;
      missingStrains.push(`${s}(${n})`);
    }
  }
  for (const [s, n] of committedSet.entries()) {
    if (!csvSet.has(s)) {
      extra += n;
      extraStrains.push(`${s}(${n})`);
    } else {
      const diff = n - csvSet.get(s);
      if (diff > 0) {
        extra += diff;
        extraStrains.push(`${s}(${diff})`);
      }
    }
  }
  return { hit, miss, extra, missing_strain_codes: missingStrains, extra_strain_codes: extraStrains };
}

// ============================================================================
// Image -> pageDate resolution.
// ============================================================================

function pageDateForImage(imageBasename, { fixturesRoot } = {}) {
  // Prefer the fixture directory naming convention: `<YYYY-MM-DD>_<IMG_ID>`.
  // Fallback to null when not resolvable.
  if (!fixturesRoot) {
    fixturesRoot = path.resolve(__dirname, '..', 'test', 'eval', 'ingestion', 'fixtures', 'notebook-2025');
  }
  const imgId = path.basename(imageBasename, '.jpg');
  let entries;
  try { entries = fs.readdirSync(fixturesRoot); } catch (_e) { return null; }
  for (const entry of entries) {
    const m = /^(\d{4}-\d{2}-\d{2})_(IMG_\d+)$/.exec(entry);
    if (m && m[2] === imgId) return m[1];
  }
  return null;
}

// ============================================================================
// Per-page rendering.
// ============================================================================

function renderPageSection(pageEntry, csvRowsForPage) {
  const basename = path.basename(pageEntry.pagePath || pageEntry.page || 'unknown');
  const commits = pageEntry.commits || [];
  const okCommits = commits.filter((c) => c.ok === true);
  const failCommits = commits.filter((c) => c.ok === false);
  const assetsCreated = commits.reduce((acc, c) => acc + ((c.asset_ids || []).length), 0);
  const assetsReused = pageEntry.assets_reused || 0;
  const logsCreated = commits.reduce((acc, c) => acc + ((c.log_ids || []).length), 0);
  const pageDate = pageEntry.event_date || pageEntry.pageDate || pageDateForImage(basename);
  const heading = pageDate ? `### ${basename} (${pageDate})` : `### ${basename}`;
  const lines = [heading];
  lines.push(`- drafts: ${(pageEntry.draftIds || []).length}`);
  lines.push(`- commits: ${okCommits.length} ok, ${failCommits.length} fail`);
  lines.push(`- assets created: ${assetsCreated}`);
  lines.push(`- assets reused: ${assetsReused}`);
  lines.push(`- logs created: ${logsCreated}`);

  if (Array.isArray(csvRowsForPage) && csvRowsForPage.length > 0) {
    const diff = computeCsvDiff({ csvRowsForPage, committedAssets: commits });
    lines.push(`- CSV diff: ${diff.hit} hit / ${diff.miss} miss / ${diff.extra} extra`);
    if (diff.missing_strain_codes.length > 0) {
      lines.push(`  - missing: ${diff.missing_strain_codes.join(', ')}`);
    }
    if (diff.extra_strain_codes.length > 0) {
      lines.push(`  - extra: ${diff.extra_strain_codes.join(', ')}`);
    }
  } else {
    lines.push(`- CSV diff: N/A (no ground truth)`);
  }

  if (failCommits.length > 0) {
    lines.push(`- failure reasons:`);
    for (const c of failCommits) {
      lines.push(`  - ${c.draftId}: ${c.reason || 'unknown'}`);
    }
  }

  return lines.join('\n');
}

// ============================================================================
// Aggregate + Phase 51 upsert-stability check.
// ============================================================================

function computeAggregate(runSummary, csvRowsAll) {
  let pages = 0;
  let drafts = 0;
  let assets_created = 0;
  let assets_reused = 0;
  let logs_created = 0;
  const per_strain = {};
  const allCommitAssetIds = new Map(); // uuid -> Set<block_name>
  const blockNameToUuids = new Map();  // block_name -> Set<uuid>

  for (const page of runSummary || []) {
    pages += 1;
    drafts += (page.draftIds || []).length;
    assets_reused += page.assets_reused || 0;
    for (const c of (page.commits || [])) {
      assets_created += (c.asset_ids || []).length;
      logs_created += (c.log_ids || []).length;
      const blockName = c.block_name || (c.draftJson && c.draftJson.block_name) || null;
      for (const u of (c.asset_ids || [])) {
        if (!allCommitAssetIds.has(u)) allCommitAssetIds.set(u, new Set());
        if (blockName) allCommitAssetIds.get(u).add(blockName);
        if (blockName) {
          if (!blockNameToUuids.has(blockName)) blockNameToUuids.set(blockName, new Set());
          blockNameToUuids.get(blockName).add(u);
        }
      }
      for (const s of (c.strain_codes || c.strainCodes || [])) {
        const u = String(s || '').toUpperCase();
        if (!u) continue;
        per_strain[u] = (per_strain[u] || 0) + 1;
      }
    }
  }

  // CSV-side per_strain (informational, not used by the diff math).
  for (const r of csvRowsAll || []) {
    const s = String(r.strain || '').toUpperCase();
    if (!s) continue;
    // Don't double-count if commits already populated it; per_strain is a
    // commits-side report. CSV per_strain is separately the diff target.
  }

  const unknown_strain_codes = Object.keys(per_strain)
    .filter((s) => !ACTIVE_STRAIN_CODES.includes(s));

  // duplicate_asset_count: same UUID across DIFFERENT block_names (cross-block
  // collision; same-block_name repeats are expected reuse).
  let duplicate_asset_count = 0;
  for (const [_uuid, names] of allCommitAssetIds.entries()) {
    if (names.size > 1) duplicate_asset_count += 1;
  }

  // Phase 51 upsert stability: block_names referenced >=2 times must resolve
  // to a single UUID. Multiple UUIDs for the same block_name = instability.
  let checked = 0;
  let stable = 0;
  const unstable = [];
  // Need to count how many *commits* referenced each block_name.
  const blockNameRefs = new Map();
  for (const page of runSummary || []) {
    for (const c of (page.commits || [])) {
      const bn = c.block_name || (c.draftJson && c.draftJson.block_name) || null;
      if (!bn) continue;
      blockNameRefs.set(bn, (blockNameRefs.get(bn) || 0) + 1);
    }
  }
  for (const [bn, refs] of blockNameRefs.entries()) {
    if (refs < 2) continue;
    checked += 1;
    const uuids = blockNameToUuids.get(bn) || new Set();
    if (uuids.size === 1) {
      stable += 1;
    } else {
      unstable.push({ block_name: bn, uuids: Array.from(uuids) });
    }
  }

  return {
    pages,
    drafts,
    assets_created,
    assets_reused,
    duplicate_asset_count,
    logs_created,
    per_strain,
    unknown_strain_codes,
    upsert_stability: { checked, stable, unstable },
  };
}

// ============================================================================
// Cost aggregate (reads responses.jsonl).
// ============================================================================

function aggregateCost(responsesJsonlPath) {
  if (!responsesJsonlPath) return { total_cost_usd: 0, n_calls: 0 };
  let text;
  try { text = fs.readFileSync(responsesJsonlPath, 'utf8'); } catch (_e) { return { total_cost_usd: 0, n_calls: 0 }; }
  let total = 0;
  let n = 0;
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    try {
      const obj = JSON.parse(line);
      total += Number(obj.cost_estimate_usd || 0);
      n += 1;
    } catch (_e) { /* skip malformed */ }
  }
  return { total_cost_usd: total, n_calls: n };
}

// ============================================================================
// Receipt builder.
// ============================================================================

function buildReceipt({ runDir, runSummary, csvPath, runId, cycleNumber, farmosUrl, elapsedSec, generatedAt }) {
  fs.mkdirSync(runDir, { recursive: true });
  const csvRowsByDate = {};
  for (const page of runSummary || []) {
    const basename = path.basename(page.pagePath || page.page || '');
    const pageDate = page.event_date || page.pageDate || pageDateForImage(basename);
    if (pageDate && !csvRowsByDate[pageDate]) {
      csvRowsByDate[pageDate] = loadCsvForPage(csvPath, pageDate);
    }
  }

  const allCsvRows = [].concat(...Object.values(csvRowsByDate));
  const aggregate = computeAggregate(runSummary, allCsvRows);
  const cost = aggregateCost(path.join(runDir, 'responses.jsonl'));

  const lines = [];
  lines.push(`# Backfill Receipt — Cycle ${cycleNumber} (run ${runId})`);
  lines.push('');
  lines.push(`- run_id: ${runId}`);
  lines.push(`- cycle: ${cycleNumber}`);
  lines.push(`- generated_at: ${generatedAt || new Date().toISOString()}`);
  lines.push(`- dev_farmos_url: ${farmosUrl || 'n/a'}`);
  lines.push(`- elapsed_seconds: ${elapsedSec || 0}`);
  lines.push(`- BACK-08 contract: Phase 51 upsert-by-stable-identity, validated via intra-cycle upsert stability (the original May-22-ancestor stub-enrichment check is N/A because those codes are 2026-dated and post-date the 2025 paper-log corpus).`);
  lines.push('');

  lines.push(`## Per-page detail`);
  lines.push('');
  for (const page of runSummary || []) {
    const basename = path.basename(page.pagePath || page.page || '');
    const pageDate = page.event_date || page.pageDate || pageDateForImage(basename);
    lines.push(renderPageSection(page, pageDate ? csvRowsByDate[pageDate] : null));
    lines.push('');
  }

  lines.push(`## Aggregate`);
  lines.push('');
  lines.push(`- pages: ${aggregate.pages}`);
  lines.push(`- drafts: ${aggregate.drafts}`);
  lines.push(`- assets_created: ${aggregate.assets_created}`);
  lines.push(`- assets_reused: ${aggregate.assets_reused}`);
  lines.push(`- logs_created: ${aggregate.logs_created}`);
  lines.push(`- duplicate_asset_count: ${aggregate.duplicate_asset_count} ${aggregate.duplicate_asset_count === 0 ? '(PASS)' : '(FAIL)'}`);
  lines.push(`- total_cost_usd: ${cost.total_cost_usd.toFixed(4)} (across ${cost.n_calls} LLM calls)`);
  lines.push('');

  lines.push(`### Per-strain breakdown (commits side)`);
  const strainEntries = Object.entries(aggregate.per_strain).sort((a, b) => b[1] - a[1]);
  if (strainEntries.length === 0) {
    lines.push(`- none`);
  } else {
    for (const [s, n] of strainEntries) {
      const flag = ACTIVE_STRAIN_CODES.includes(s) ? '' : ' [UNKNOWN — review with farmer]';
      lines.push(`- ${s}: ${n}${flag}`);
    }
  }
  if (aggregate.unknown_strain_codes.length > 0) {
    lines.push('');
    lines.push(`- unknown_strain_codes (not in mossrock_active_strain_codes memory): ${aggregate.unknown_strain_codes.join(', ')}`);
  }
  lines.push('');

  lines.push(`### Phase 51 upsert stability (BACK-08 contract validation)`);
  lines.push(`- checked: ${aggregate.upsert_stability.checked} block_names referenced >=2 times`);
  lines.push(`- stable: ${aggregate.upsert_stability.stable} resolved to a single UUID`);
  if (aggregate.upsert_stability.unstable.length === 0) {
    lines.push(`- unstable: 0 (PASS)`);
  } else {
    lines.push(`- unstable: ${aggregate.upsert_stability.unstable.length} (FAIL — Phase 51 contract regression)`);
    for (const u of aggregate.upsert_stability.unstable) {
      lines.push(`  - ${u.block_name}: ${u.uuids.join(', ')}`);
    }
  }
  lines.push('');

  lines.push(`## Farmer review`);
  lines.push('');
  lines.push(`Receipt is the SINGLE document for farmer review of Cycle ${cycleNumber}. dev-farmOS UI is too noisy for per-entry verification — trust this receipt + spot-check a handful of UUIDs.`);
  lines.push('');
  lines.push(`Pass criteria: duplicate_asset_count == 0 AND upsert_stability.unstable == [] AND no surprising failure reasons in the per-page sections.`);
  lines.push('');

  let body = lines.join('\n');
  // ASCII-only enforcement: strip em-dashes (— and –) to '--'.
  body = body.replace(/[–—]/g, '--');

  const receiptPath = path.join(runDir, 'receipt.md');
  fs.writeFileSync(receiptPath, body, 'utf8');
  return receiptPath;
}

module.exports = {
  ACTIVE_STRAIN_CODES,
  parseCsv,
  loadCsvForPage,
  strainSetFromCsv,
  strainSetFromCommits,
  computeCsvDiff,
  pageDateForImage,
  renderPageSection,
  computeAggregate,
  aggregateCost,
  buildReceipt,
};
