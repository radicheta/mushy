#!/usr/bin/env node
'use strict';

// Plan 08 seed: extract 2 mushdatadump jpegs against the live Anthropic extractor.
// Prints all 4 required fields + confidences + raw notes for visual verification
// by Don Santiago against the actual photographs. No scoring -- the output IS
// the seed of per-event ground truth for Plan 08.

const path = require('path');
const fs = require('fs');
const { createExtractor } = require('../src/extraction/extractor');
const { readImageToBase64 } = require('../src/extraction/multimodal');

const FIXTURE_DIR = '/mnt/mossrock/shared/mushdatadump/jpeg';
const NAMES = (process.argv[2] || 'IMG_3775.jpg,IMG_3800.jpg').split(',').map(s => s.trim());

(async () => {
  if (!process.env.ANTHROPIC_API_KEY) {
    console.error('ANTHROPIC_API_KEY required'); process.exit(1);
  }
  // 21+ drafts blow past 8192 (saw 8257 + truncation on IMG_3800). Bump to 16K.
  const extractor = createExtractor({ apiKey: process.env.ANTHROPIC_API_KEY, logger: console, maxTokens: 16384 });
  const out = [];
  for (const name of NAMES) {
    const p = path.join(FIXTURE_DIR, name);
    if (!fs.existsSync(p)) { console.error(`missing: ${p}`); continue; }
    const img = await readImageToBase64(p, { logger: console });
    if (!img.ok) { console.error(`load failed: ${img.reason}`); continue; }
    const t0 = Date.now();
    const r = await extractor.extract({
      captures: [{ text: '', transcript: '', images: [{ data: img.data, media_type: img.media_type }] }],
      inFlightDraft: null,
      corpusContext: { default_year: 2025 },
    });
    out.push({ name, path: p, latencyMs: Date.now() - t0, result: r });
  }
  console.log('\n========== RESULTS ==========\n');
  for (const row of out) {
    console.log(`=== ${row.name} (${row.latencyMs}ms) ===`);
    console.log(`path: ${row.path}`);
    const r = row.result;
    if (!r.ok) { console.log(`FAIL: ${r.reason}\n`); continue; }
    const drafts = r.drafts || [];
    console.log(`continuity:      ${r.continuity_decision} -- ${r.continuity_reason || ''}`);
    if (r.usage) console.log(`usage:           in=${r.usage.input_tokens} out=${r.usage.output_tokens} cache_w=${r.usage.cache_creation_input_tokens} cache_r=${r.usage.cache_read_input_tokens}`);
    console.log(`drafts:          ${drafts.length}`);
    for (let i = 0; i < drafts.length; i += 1) {
      const e = drafts[i] || {};
      const d = e.draft || {};
      const pfc = e.per_field_confidence || {};
      const fld = (k) => `${d[k] ?? '-'} (${pfc[k] ?? '?'})`;
      const extra = d.parent_batch_name ? ` parent=${fld('parent_batch_name')}` : '';
      console.log(`  [${String(i + 1).padStart(2)}] ${d.type} sp=${fld('species')} blk=${fld('block_name')} qty=${fld('qty')} ts=${fld('event_timestamp')}${extra}`);
    }
    console.log('');
  }
  // Persistence: per-image timestamped files (NEVER overwrite). Also append a single
  // aggregate JSONL so the full history of every paid-for call lives on disk.
  const outDir = path.resolve(__dirname, '../../../../.planning/phases/38-extraction-pipeline/plan08-runs');
  fs.mkdirSync(outDir, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  for (const row of out) {
    const file = path.join(outDir, `${row.name.replace(/\.jpg$/i, '')}_${ts}.json`);
    fs.writeFileSync(file, JSON.stringify(row, null, 2));
    console.log(`persisted -> ${path.relative(process.cwd(), file)}`);
  }
  const aggregate = path.join(outDir, 'all-runs.jsonl');
  for (const row of out) {
    fs.appendFileSync(aggregate, JSON.stringify({ ts, ...row }) + '\n');
  }
  console.log(`appended  -> ${path.relative(process.cwd(), aggregate)}`);
})();
