#!/usr/bin/env node
'use strict';

// 2026-05-12 one-shot replay: re-run today's captured prod inoc session through
// the now-fixed pipeline (image-loading wire fix + whisper GPU restored). Does
// NOT write to signal_draft / DB / outbound -- just proves the extractor sees
// real images and produces schema-valid drafts.

const { Pool } = require('pg');
const { createExtractor } = require('../src/extraction/extractor');
const { readImageToBase64 } = require('../src/extraction/multimodal');
const { createTranscribeClient } = require('../src/transcribe-client');

const IMAGE_EXT_RE = /\.(jpe?g|png|gif|webp)$/i;
const AUDIO_EXT_RE = /\.(m4a|aac|ogg|opus|wav|mp3)$/i;

async function loadImageBlocks(paths) {
  const blocks = [];
  for (const p of paths || []) {
    if (!IMAGE_EXT_RE.test(p)) continue;
    const r = await readImageToBase64(p, { logger: console });
    if (!r.ok) { console.warn(`  image load skipped: ${p} (${r.reason})`); continue; }
    blocks.push({ data: r.data, media_type: r.media_type });
  }
  return blocks;
}

async function transcribeAudio(transcribeClient, paths) {
  const transcripts = [];
  for (const p of paths || []) {
    if (!AUDIO_EXT_RE.test(p)) continue;
    const t0 = Date.now();
    const r = await transcribeClient.transcribe(p);
    if (!r.ok) { console.warn(`  audio degraded: ${p} (${r.reason})`); continue; }
    console.log(`  whisper: ${Date.now() - t0}ms duration=${r.duration_ms}ms lang=${r.language} chars=${(r.text||'').length}`);
    transcripts.push(r.text);
  }
  return transcripts;
}

(async () => {
  if (!process.env.ANTHROPIC_API_KEY) { console.error('ANTHROPIC_API_KEY required'); process.exit(1); }
  const pool = new Pool({
    host: process.env.PGHOST || 'timescale',
    user: process.env.PGUSER || 'postgres',
    password: process.env.PGPASSWORD || process.env.TIMESCALE_PASSWORD,
    database: process.env.PGDATABASE || 'postgres',
  });
  const extractor = createExtractor({ apiKey: process.env.ANTHROPIC_API_KEY, logger: console, maxTokens: 16384 });
  const transcribeClient = createTranscribeClient({ apiUrl: process.env.WHISPER_URL || 'http://host.docker.internal:8090', logger: console });

  // Today's prod inoc session captures, oldest first. Skip butt-dial (the short .aac).
  const idsArg = process.argv[2];
  const ids = idsArg
    ? idsArg.split(',')
    : ['01KRF0P0DGRM7PVVM3P7XJ1XZT', '01KRF0TN311A11CW3C7J890R43'];

  const { rows } = await pool.query(
    `SELECT id, captured_at, sender, message_type, raw_text, attachment_paths, farmos_person
       FROM signal_capture WHERE id = ANY($1::text[]) ORDER BY captured_at ASC`,
    [ids]
  );

  for (const cap of rows) {
    console.log(`\n========== ${cap.id} ${cap.captured_at.toISOString()} type=${cap.message_type} ==========`);
    console.log(`  sender=${cap.sender} farmos=${cap.farmos_person} attachments=${(cap.attachment_paths||[]).length}`);

    const imageBlocks = await loadImageBlocks(cap.attachment_paths);
    const transcripts = await transcribeAudio(transcribeClient, cap.attachment_paths);
    console.log(`  -> imageBlocks=${imageBlocks.length} transcripts=${transcripts.length}`);

    const captures = [{
      captureId: cap.id,
      text: cap.raw_text || null,
      transcript: transcripts.length ? transcripts.join('\n') : null,
      images: imageBlocks,
    }];

    const t0 = Date.now();
    const r = await extractor.extract({ captures, inFlightDraft: null });
    console.log(`  extractor: ${Date.now() - t0}ms ok=${r.ok} reason=${r.reason || '-'}`);
    if (!r.ok) {
      console.log(`  errors: ${JSON.stringify(r.errors).slice(0, 1500)}`);
      continue;
    }
    const drafts = r.drafts || [];
    console.log(`  continuity=${r.continuity_decision} reason="${r.continuity_reason || ''}" drafts=${drafts.length}`);
    drafts.forEach((e, i) => {
      const d = e.draft || {};
      const c = e.per_field_confidence || {};
      const f = (k) => `${d[k] ?? '-'}(${c[k] ?? '?'})`;
      console.log(`    [${String(i+1).padStart(2)}] ${d.type} sp=${f('species')} blk=${f('block_name')} qty=${f('qty')} ts=${f('event_timestamp')}${d.parent_batch_name ? ' parent=' + f('parent_batch_name') : ''}`);
    });
    if (r.usage) console.log(`  usage in=${r.usage.input_tokens} out=${r.usage.output_tokens} cache_r=${r.usage.cache_read_input_tokens} cache_w=${r.usage.cache_creation_input_tokens}`);
  }
  await pool.end();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
