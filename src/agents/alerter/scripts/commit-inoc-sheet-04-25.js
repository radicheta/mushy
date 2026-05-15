#!/usr/bin/env node
'use strict';

// One-shot: re-extract the 2026-05-12 sheet capture, filter to 2026-04-25
// drafts, insert as `status=confirmed` signal_draft rows so the commit-
// watchdog writes them to prod-farmOS as real Mossrock seeding logs.
//
// Block_name middle token is the canonical strain code (260425_SHI_1 -> SHI),
// which is what fungi_type expects on prod-farmOS.

const { Pool } = require('pg');
const { createExtractor } = require('../src/extraction/extractor');
const { readImageToBase64 } = require('../src/extraction/multimodal');

const CAPTURE_ID = '01KRF0P0DGRM7PVVM3P7XJ1XZT';
const DAY_FILTER = '2026-04-25';
const SOURCE_TAG = 'sheet-04-25-real-inoc-2026-04-25';

function strainFromBlock(blockName) {
  const m = /^[0-9]{6}_([A-Z]{2,4})_[0-9]+$/.exec(blockName || '');
  return m ? m[1] : null;
}

async function main() {
  if (!process.env.ANTHROPIC_API_KEY) { console.error('ANTHROPIC_API_KEY required'); process.exit(1); }
  const pool = new Pool({
    host: process.env.PGHOST || 'timescale',
    user: process.env.PGUSER || 'postgres',
    password: process.env.PGPASSWORD || process.env.TIMESCALE_PASSWORD,
    database: process.env.PGDATABASE || 'postgres',
  });
  const extractor = createExtractor({ apiKey: process.env.ANTHROPIC_API_KEY, logger: console, maxTokens: 16384 });

  const { rows } = await pool.query(
    `SELECT id, sender, raw_text, attachment_paths, farmos_person
       FROM signal_capture WHERE id = $1`,
    [CAPTURE_ID]
  );
  if (rows.length === 0) { console.error('capture not found'); process.exit(2); }
  const cap = rows[0];

  const imageBlocks = [];
  for (const p of cap.attachment_paths || []) {
    if (!/\.(jpe?g|png)$/i.test(p)) continue;
    const r = await readImageToBase64(p, { logger: console });
    if (r.ok) imageBlocks.push({ data: r.data, media_type: r.media_type });
  }
  console.log(`extractor input: ${imageBlocks.length} image(s), capture=${cap.id}`);

  const captures = [{ captureId: cap.id, text: cap.raw_text || null, transcript: null, images: imageBlocks }];
  const t0 = Date.now();
  const r = await extractor.extract({ captures, inFlightDraft: null });
  console.log(`extractor: ${Date.now() - t0}ms ok=${r.ok} drafts=${(r.drafts||[]).length}`);
  if (!r.ok) { console.error('extract failed:', r.reason, JSON.stringify(r.errors).slice(0,500)); process.exit(3); }

  const filtered = (r.drafts || []).filter((e) => {
    const ts = e.draft && e.draft.event_timestamp;
    return e.draft.type === 'seeding' && typeof ts === 'string' && ts.startsWith(DAY_FILTER);
  });
  console.log(`filtered to ${DAY_FILTER}: ${filtered.length} drafts`);

  let inserted = 0;
  const ids = [];
  for (const e of filtered) {
    const d = e.draft;
    const blockName = d.block_name;
    const strain = strainFromBlock(blockName);
    if (!strain) { console.warn(`skip: no strain from block ${blockName}`); continue; }
    const ts = Math.floor(new Date(d.event_timestamp).getTime() / 1000);
    const id = 'real_sheet_2026-04-25_' + blockName + '_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2,6);
    const draftJson = {
      batch_name: d.parent_batch_name || null,
      block_name: blockName,
      species_code: strain,
      qr_codes: [],
      timestamp: ts,
      notes: `real inoc session 2026-04-25; source: paper logsheet scan (capture ${cap.id}); strain=${strain}; qty=${d.qty || 1}` +
             (d.parent_batch_name ? `; parent_batch=${d.parent_batch_name}` : ''),
    };
    const conf = e.per_field_confidence || {};
    await pool.query(
      `INSERT INTO signal_draft (
        id, sender_e164, farmos_person, source_capture_ids, status, log_type,
        draft_json, per_field_confidence, farmer_facing_preview, reply_target_kind,
        group_id, commit_attempt_count, created_at, updated_at, confirmed_at
      ) VALUES ($1,$2,$3,$4,'confirmed','seeding',$5,$6,$7,'dm',NULL,0,NOW(),NOW(),NOW())`,
      [
        id, cap.sender, cap.farmos_person, [cap.id], JSON.stringify(draftJson),
        JSON.stringify(conf), `Inoc ${blockName} (${strain})`,
      ]
    );
    inserted++;
    ids.push(id);
    console.log(`  inserted: ${id}  block=${blockName} strain=${strain} parent=${d.parent_batch_name || '-'}`);
  }
  console.log(`\n=> inserted ${inserted} signal_draft rows as status=confirmed`);
  console.log(`watchdog should pick them up on the next tick (interval=30s)`);
  await pool.end();
}

main().catch(e => { console.error('FATAL', e); process.exit(1); });
