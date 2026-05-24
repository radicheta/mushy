'use strict';

// Phase 53 Plan 04 (BACK-04): notebook-2025 corpus loader.
//
// Mirrors sessions-loader.js shape but reads from fixtures/notebook-2025/.
// Each fixture subdir must contain:
//   - image.jpg (or .jpeg/.png) -- source image (symlink into mushdatadump-prod ok)
//   - manifest.json -- { name, year, corpus_context, expected_capture_kind, regression_guard }
//   - ground-truth.json -- expected extraction envelope (drafts[], optional capture_kind)
//   - mock-extraction.json -- raw Anthropic tool_use response for hermetic replay
//
// Output shape per entry:
//   { name, dir, manifest, groundTruth, mockExtraction, imagePath }

const fs = require('fs');
const path = require('path');

const IMAGE_RE = /\.(jpe?g|png)$/i;

function loadNotebook2025Corpus(dir, { logger = console } = {}) {
  if (!fs.existsSync(dir)) {
    logger.warn && logger.warn(`[notebook-2025-loader] dir not found at ${dir}`);
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
    const manifestPath = path.join(subPath, 'manifest.json');
    const truthPath = path.join(subPath, 'ground-truth.json');
    const mockPath = path.join(subPath, 'mock-extraction.json');

    if (!fs.existsSync(manifestPath)) {
      logger.warn && logger.warn(`[notebook-2025-loader] skip ${sub}: no manifest.json`);
      continue;
    }
    if (!fs.existsSync(truthPath)) {
      logger.warn && logger.warn(`[notebook-2025-loader] skip ${sub}: no ground-truth.json`);
      continue;
    }
    if (!fs.existsSync(mockPath)) {
      logger.warn && logger.warn(`[notebook-2025-loader] skip ${sub}: no mock-extraction.json`);
      continue;
    }

    let manifest, groundTruth, mockExtraction;
    try {
      manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
      groundTruth = JSON.parse(fs.readFileSync(truthPath, 'utf8'));
      mockExtraction = JSON.parse(fs.readFileSync(mockPath, 'utf8'));
    } catch (e) {
      throw new Error(`[notebook-2025-loader] ${sub}: failed to parse fixture JSON: ${e.message}`);
    }

    // Find the source image (symlink ok). May be null if the operator
    // committed only the metadata triplet.
    let imagePath = null;
    for (const f of fs.readdirSync(subPath)) {
      if (IMAGE_RE.test(f)) {
        imagePath = path.join(subPath, f);
        break;
      }
    }

    out.push({ name: sub, dir: subPath, manifest, groundTruth, mockExtraction, imagePath });
  }
  return out;
}

module.exports = { loadNotebook2025Corpus };
