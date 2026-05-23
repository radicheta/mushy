'use strict';

// Phase 49 Plan 01 sessions-loader.
//
// Sibling of fixtures-loader.js: iterates test/eval/ingestion/fixtures/sessions/
// and yields one normalized entry per direct child subdir that contains both
// `ground-truth.json` and `MANIFEST.md`.
//
// Output shape:
//   {
//     name,          // subdir basename (e.g. '2026-05-22_inoc_santi')
//     dir,           // absolute path to the subdir
//     manifest,      // parsed first ```json``` fenced block from MANIFEST.md
//     groundTruth,   // parsed ground-truth.json (literal seeding_session draft)
//     audioPath,     // absolute path to any audio.{m4a,aac,wav,mp3,ogg,opus} file, or null
//     photoPath,     // absolute path to any paper-log{,.*}.{jpg,jpeg,png} file, or null
//   }
//
// Missing groundTruth: warn + skip. Missing MANIFEST.md: warn + skip.
// Non-fatal -- only throws on programmer error (parse failures).

const fs = require('fs');
const path = require('path');

const AUDIO_EXT_RE = /^audio\.(m4a|aac|ogg|opus|wav|mp3)$/i;
const PHOTO_RE = /^paper-log(\..+)?\.(jpe?g|png)$/i;

function extractJsonBlock(md) {
  // Match the first fenced ```json``` block.
  const m = md.match(/```json\s*([\s\S]*?)```/);
  if (!m) return null;
  try {
    return JSON.parse(m[1]);
  } catch (_e) {
    return null;
  }
}

function loadSessionsCorpus(dir, { logger = console } = {}) {
  if (!fs.existsSync(dir)) {
    logger.warn && logger.warn(`[sessions-loader] sessions dir not found at ${dir}`);
    return [];
  }
  const subdirs = fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    .sort();

  const out = [];
  for (const sub of subdirs) {
    const subPath = path.join(dir, sub);
    const truthPath = path.join(subPath, 'ground-truth.json');
    const manifestPath = path.join(subPath, 'MANIFEST.md');

    if (!fs.existsSync(truthPath)) {
      logger.warn && logger.warn(`[sessions-loader] skipping ${sub}: no ground-truth.json`);
      continue;
    }
    if (!fs.existsSync(manifestPath)) {
      logger.warn && logger.warn(`[sessions-loader] skipping ${sub}: no MANIFEST.md`);
      continue;
    }

    let groundTruth;
    try {
      groundTruth = JSON.parse(fs.readFileSync(truthPath, 'utf8'));
    } catch (e) {
      throw new Error(`[sessions-loader] ${sub}/ground-truth.json failed to parse: ${e.message}`);
    }

    const manifestText = fs.readFileSync(manifestPath, 'utf8');
    const manifest = extractJsonBlock(manifestText);
    if (!manifest) {
      logger.warn && logger.warn(`[sessions-loader] ${sub}/MANIFEST.md has no parseable \`\`\`json\`\`\` block; entry retained with manifest=null`);
    }

    const files = fs.readdirSync(subPath);
    let audioPath = null;
    let photoPath = null;
    for (const f of files) {
      if (audioPath === null && AUDIO_EXT_RE.test(f)) {
        audioPath = path.join(subPath, f);
      } else if (photoPath === null && PHOTO_RE.test(f)) {
        photoPath = path.join(subPath, f);
      }
    }

    out.push({
      name: sub,
      dir: subPath,
      manifest,
      groundTruth,
      audioPath,
      photoPath,
    });
  }
  return out;
}

module.exports = {
  loadSessionsCorpus,
  AUDIO_EXT_RE,
  PHOTO_RE,
};
