'use strict';

// One-off fused image+audio extraction test for the 2026-05-30 inoc session.
//
// Why: image-only extraction misread the faint-pencil notebook badly; audio-only
// got structure/species right but mangled some parent batch codes. This runs
// three variants -- image-only, audio-only, fused -- through the REAL extractor
// to see whether fusion (audio for structure, full-res image for batch codes)
// yields a committable draft.
//
// Read-only w.r.t. farmOS (no commit). It IS a paid Anthropic call, so the raw
// response is persisted append-only to a unique path (project rule: never
// overwrite paid results).
//
// Run inside the alerter container (after docker cp):
//   docker exec -e FUSED_TRANSCRIPT_B64=... mushy-alerter-1 \
//     node /app/scripts/fused-extract-260530.js

const fs = require('fs');
const path = require('path');
const { createExtractor } = require('../src/extraction/extractor');
const multimodal = require('../src/extraction/multimodal');

const IMAGE_PATH =
  '/data/signal-capture/2026-05-30/14-36-28-01KSWN18QH7GCH00FX8F7XVB7Y-C0tmR_Vt7j9sF2Uk5GE6.jpg.jpg';

// Audio transcript (capture 01KSX7NM9W), passed base64 to dodge shell quoting.
const TRANSCRIPT = process.env.FUSED_TRANSCRIPT_B64
  ? Buffer.from(process.env.FUSED_TRANSCRIPT_B64, 'base64').toString('utf8')
  : '';

const OUT_DIR = process.env.FUSED_OUT_DIR || '/data/fused-out';
const MODEL = process.env.EXTRACTION_MODEL || 'claude-sonnet-4-6';

function tag() {
  return `${process.pid}-${process.hrtime.bigint().toString()}`;
}

function summarize(label, res) {
  const out = [];
  const draft = (res && res.draft) || null;
  out.push(`--- ${label} ---`);
  out.push(`ok=${res && res.ok} reason=${(res && res.reason) || '-'}`);
  if (draft) {
    out.push(`type=${draft.type} event_date=${draft.event_date} needs_input=${draft.needs_input || '-'}`);
    const groups = Array.isArray(draft.groups) ? draft.groups : [];
    groups.forEach((g, i) => {
      const sp = g && g.species && g.species.value;
      const pa = g && g.parent && g.parent.value;
      const qty = g && g.qty && g.qty.value;
      out.push(`  ${i + 1}: sp=${sp} parent=${pa} qty=${qty}`);
    });
  }
  return out.join('\n');
}

async function main() {
  if (!TRANSCRIPT) throw new Error('FUSED_TRANSCRIPT_B64 not set');
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const runId = tag();
  const outPath = path.join(OUT_DIR, `fused-${runId}.jsonl`);
  const append = (obj) => fs.appendFileSync(outPath, JSON.stringify(obj) + '\n');

  const img = await multimodal.readImageToBase64(IMAGE_PATH, { logger: console });
  if (!img.ok) throw new Error('image read failed: ' + img.reason);
  console.log(`[fused] image loaded media=${img.media_type} b64len=${img.data.length}`);

  // createExtractor reads ANTHROPIC_API_KEY from env (SDK default). onLlmCall
  // persists every paid response raw.
  const extractor = createExtractor({
    apiKey: process.env.ANTHROPIC_API_KEY,
    model: MODEL,
    logger: console,
    onLlmCall: (rec) => append({ kind: 'llm_call', run_id: runId, variant: CURRENT, ...rec }),
  });

  const imageBlock = [{ data: img.data, media_type: img.media_type }];
  const variants = [
    { name: 'image_only', text: null, transcript: null, images: imageBlock },
    { name: 'audio_only', text: null, transcript: TRANSCRIPT, images: [] },
    { name: 'fused_image_plus_audio', text: null, transcript: TRANSCRIPT, images: imageBlock },
  ];

  const report = [];
  for (const v of variants) {
    CURRENT = v.name;
    console.log(`\n[fused] === ${v.name} ===`);
    let res;
    try {
      res = await extractor.extract({
        captures: [{ captureId: `fused-${v.name}`, text: v.text, transcript: v.transcript, images: v.images }],
        corpusContext: { year: 2026, source: 'paper_log' },
      });
    } catch (e) {
      res = { ok: false, reason: e.message };
      console.log(`[fused] ${v.name} threw: ${e.message}`);
    }
    append({ kind: 'variant_result', run_id: runId, variant: v.name, result: res });
    const s = summarize(v.name, res);
    console.log(s);
    report.push(s);
  }

  console.log(`\n[fused] raw results -> ${outPath}`);
  console.log('\n========== SUMMARY ==========\n' + report.join('\n\n'));
}

let CURRENT = 'init';
main().catch((e) => {
  console.error('[fused] FATAL', e && e.stack ? e.stack : e);
  process.exit(1);
});
