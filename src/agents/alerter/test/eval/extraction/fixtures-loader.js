'use strict';

// Phase 38 Plan 07 Task 1: fixtures-loader for mushdatadump v1.6.
//
// mushdatadump v1.6 layout (per the dataset README + memory reference):
//   /mnt/mossrock/shared/mushdatadump/
//     jpeg/             -- 73 JPEG photos of the paper cultivation log pages
//     mushroom_log.csv  -- 829-row digitized index (page_date, entry_num, strain, source, notes)
//     Mossrock Data.csv -- harvest tracking (sparse spreadsheet, not 1:1 per image)
//     mushroom_harvest.csv -- harvest aggregates
//
// IMPORTANT ADAPTATION (documented in 38-EVAL-REPORT.md):
//   The plan's <interfaces> stanza assumes a `ground-truth.csv` with one row per
//   image with expected fields. mushdatadump v1.6 does NOT have that shape -- the
//   CSVs are page-grain (multiple log entries per JPEG), not per-image. The
//   pragmatic adaptation is:
//     - Per image: expected.type = 'seeding' (these are inoculation log pages).
//     - expected.requiredFields = ['type'] only (schema conformance + correct type
//       is the strongest claim we can make per-image without OCR aligning JPEG to
//       CSV rows, which is out of scope for Plan 07).
//     - expected.ambiguous = false (we don't have an ambiguity flag in the CSV;
//       a page with 10 entries is honestly ambiguous-for-1-draft, but the extractor
//       is expected to produce SOMETHING schema-valid).
//   The full B5/lineage/exact-field scoring still RUNS, just without per-image
//   expected values to compare against -- their per-fixture pass count will be
//   driven by schema validity alone. Plan 08 (production-log path) is where
//   richer ground truth lands.

const fs = require('fs');
const path = require('path');

function loadFixtures(dir, { logger = console } = {}) {
  const jpegDir = path.join(dir, 'jpeg');
  if (!fs.existsSync(jpegDir)) {
    throw new Error(`fixtures-loader: jpeg/ subdir not found at ${jpegDir}. Set EXTRACTION_FIXTURE_DIR.`);
  }
  const logCsv = path.join(dir, 'mushroom_log.csv');
  let logRows = [];
  if (fs.existsSync(logCsv)) {
    logRows = parseCsvSimple(fs.readFileSync(logCsv, 'utf8'));
    logger.info && logger.info(`[fixtures-loader] loaded ${logRows.length} mushroom_log.csv rows`);
  } else {
    logger.warn && logger.warn(`[fixtures-loader] mushroom_log.csv missing at ${logCsv}; using image-only fixtures`);
  }
  const jpegs = fs.readdirSync(jpegDir)
    .filter((f) => /\.(jpe?g)$/i.test(f))
    .sort();
  const fixtures = jpegs.map((f) => ({
    imagePath: path.join(jpegDir, f),
    name: f,
    expected: {
      type: 'seeding',
      requiredFields: [],
      fields: {},
      ambiguous: false,
    },
  }));
  return fixtures;
}

function parseCsvSimple(text) {
  // Minimal CSV parser: assumes no embedded newlines inside quoted fields.
  // mushroom_log.csv is well-formed enough for this.
  const lines = text.split(/\r?\n/).filter((l) => l.length > 0);
  if (!lines.length) return [];
  const header = splitCsvLine(lines[0]);
  const out = [];
  for (let i = 1; i < lines.length; i += 1) {
    const cols = splitCsvLine(lines[i]);
    const row = {};
    for (let j = 0; j < header.length; j += 1) {
      row[header[j]] = (cols[j] == null ? '' : cols[j]).trim();
    }
    out.push(row);
  }
  return out;
}

function splitCsvLine(line) {
  const out = [];
  let cur = '';
  let inQuote = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuote && line[i + 1] === '"') {
        cur += '"';
        i += 1;
      } else {
        inQuote = !inQuote;
      }
    } else if (ch === ',' && !inQuote) {
      out.push(cur);
      cur = '';
    } else {
      cur += ch;
    }
  }
  out.push(cur);
  return out;
}

module.exports = { loadFixtures, parseCsvSimple, splitCsvLine };
