'use strict';

// Phase 41 ingestion fixtures-loader.
//
// Cites CONTEXT D-02..D-02b (synthetic corpus) + D-03..D-03c (paper-log,
// reuses Phase 38 loader and does NOT re-hand-label mushdatadump v1.6) +
// D-04..D-04b (audio corpus).
//
// All loaders return uniform Fixture[] (see 41-RESEARCH.md section 3):
//   { name, kind, session_id?, envelope, attachments[], expected, mockResponse?, mock_transcript? }

const fs = require('fs');
const path = require('path');

const IMG_EXT_RE = /\.(jpe?g|png)$/i;
const AUDIO_EXT_RE = /\.(m4a|aac|ogg|opus|wav|mp3)$/i;

function loadSyntheticCorpus(dir, { logger = console } = {}) {
  if (!fs.existsSync(dir)) {
    logger.warn && logger.warn(`[fixtures-loader] synthetic dir not found at ${dir}`);
    return [];
  }
  const subdirs = fs.readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    .sort();
  const out = [];
  for (const sub of subdirs) {
    const subPath = path.join(dir, sub);
    const inputPath = path.join(subPath, 'input.json');
    const expectedPath = path.join(subPath, 'expected.json');
    if (!fs.existsSync(inputPath)) {
      throw new Error(`[fixtures-loader] missing input.json in ${subPath}`);
    }
    if (!fs.existsSync(expectedPath)) {
      logger.warn && logger.warn(`[fixtures-loader] skipping ${sub}: no expected.json`);
      continue;
    }
    const envelope = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
    const expected = JSON.parse(fs.readFileSync(expectedPath, 'utf8'));

    const files = fs.readdirSync(subPath);
    const attachments = [];
    for (const f of files) {
      const fp = path.join(subPath, f);
      if (IMG_EXT_RE.test(f)) attachments.push({ type: 'image', path: fp });
      else if (AUDIO_EXT_RE.test(f)) attachments.push({ type: 'audio', path: fp });
    }
    // Honor symlinked attachments listed in input.json explicitly.
    if (Array.isArray(envelope.attachments)) {
      for (const a of envelope.attachments) {
        if (a && a.path && a.type) attachments.push({ type: a.type, path: a.path });
      }
    }

    let mockResponse = null;
    const mrPath = path.join(subPath, 'mock-response.json');
    if (fs.existsSync(mrPath)) {
      mockResponse = JSON.parse(fs.readFileSync(mrPath, 'utf8'));
    }

    out.push({
      name: sub,
      kind: 'synthetic',
      session_id: expected.session_id || null,
      envelope,
      attachments,
      expected,
      mockResponse,
      mock_transcript: envelope.mock_transcript || null,
    });
  }
  return out;
}

function loadMockSidecars(fixtures) {
  const m = {};
  for (const f of fixtures) m[f.name] = f;
  return m;
}

function loadMockTranscripts(fixtures) {
  // Identical structure; harness builds path lookup downstream.
  return loadMockSidecars(fixtures);
}

// --- Paper-log corpus (Plan 04) ---

const phase38Loader = require('../extraction/fixtures-loader');

function findExpectedSidecar(fx, prodDir) {
  // Per CONTEXT D-03a: session-grain expected.json preferred; fall back to
  // per-image .expected.json. fx.name is "prod:<subdir>" from Phase 38 loader.
  const sessionName = fx.name.replace(/^prod:/, '');
  const sessionDir = path.join(prodDir, sessionName);
  const sessionExp = path.join(sessionDir, 'expected.json');
  if (fs.existsSync(sessionExp)) {
    try { return JSON.parse(fs.readFileSync(sessionExp, 'utf8')); }
    catch (e) { return null; }
  }
  // per-image fallback: scan for any <name>.expected.json
  if (fs.existsSync(sessionDir)) {
    const files = fs.readdirSync(sessionDir);
    for (const f of files) {
      if (/\.expected\.json$/.test(f)) {
        try { return JSON.parse(fs.readFileSync(path.join(sessionDir, f), 'utf8')); }
        catch (_) { /* try next */ }
      }
    }
  }
  return null;
}

function loadPaperLogCorpus(opts = {}) {
  const {
    curatedDir = process.env.EXTRACTION_FIXTURE_DIR || '/mnt/mossrock/shared/mushdatadump',
    prodDir = process.env.EXTRACTION_PROD_FIXTURE_DIR || '/mnt/mossrock/shared/mushdatadump-prod',
    logger = console,
  } = opts;

  // Reuse Phase 38 loader; do NOT re-hand-label mushdatadump v1.6.
  let curated = [];
  if (fs.existsSync(curatedDir)) {
    try {
      curated = phase38Loader.loadFixtures(curatedDir, { logger }).map((fx) => ({
        name: `mushdatadump:${fx.name}`,
        kind: 'paper-log',
        session_id: null,
        envelope: { sender: 'synthetic-paperlog', body: '', ts: null },
        attachments: [{ type: 'image', path: fx.imagePath }],
        expected: fx.expected,
      }));
    } catch (e) {
      logger.warn && logger.warn(`[fixtures-loader] curated paper-log load failed: ${e.message}`);
    }
  } else {
    logger.warn && logger.warn(`[fixtures-loader] curated paper-log dir not found at ${curatedDir}`);
  }

  const prod = [];
  let missingLabels = 0;
  if (fs.existsSync(prodDir)) {
    const prodRaw = phase38Loader.loadProdFixtures(prodDir, { skipNames: ['MANIFEST.md'], logger });
    for (const fx of prodRaw) {
      const sidecar = findExpectedSidecar(fx, prodDir);
      if (!sidecar) { missingLabels += 1; continue; }
      const sessionName = fx.name.replace(/^prod:/, '');
      prod.push({
        name: `prod:${sessionName}`,
        kind: 'paper-log',
        session_id: sidecar.session_id || null,
        envelope: { sender: 'synthetic-paperlog-prod', body: '', ts: null },
        attachments: [
          ...(fx.imagePaths || []).map((p) => ({ type: 'image', path: p })),
          ...(fx.audioPaths || []).map((p) => ({ type: 'audio', path: p })),
        ],
        expected: sidecar,
      });
    }
  } else {
    logger.warn && logger.warn(`[fixtures-loader] prod paper-log dir not found at ${prodDir}`);
  }
  if (missingLabels > 0) {
    logger.warn && logger.warn(`[fixtures-loader] ${missingLabels} prod sessions lack .expected.json sidecars; see 41-RUNBOOK.md section 3`);
  }
  return [...curated, ...prod];
}

// --- Audio corpus (Plan 05) ---

function loadAudioCorpus(opts = {}) {
  const {
    dir = process.env.AUDIO_FIXTURE_DIR || path.resolve(__dirname, 'fixtures/audio'),
    logger = console,
  } = opts;
  if (!fs.existsSync(dir)) {
    logger.warn && logger.warn(`[fixtures-loader] AUDIO_FIXTURE_DIR not found at ${dir}; INGEST-03 will run as human_needed`);
    return [];
  }
  const subdirs = fs.readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    .sort();
  const out = [];
  let missingLabels = 0;
  for (const sub of subdirs) {
    const subPath = path.join(dir, sub);
    const files = fs.readdirSync(subPath);
    const audios = files.filter((f) => AUDIO_EXT_RE.test(f)).map((f) => path.join(subPath, f));
    if (audios.length === 0) continue;
    const expPath = path.join(subPath, 'expected.json');
    if (!fs.existsSync(expPath)) { missingLabels += 1; continue; }
    let expected;
    try { expected = JSON.parse(fs.readFileSync(expPath, 'utf8')); }
    catch (_) { missingLabels += 1; continue; }
    out.push({
      name: `audio:${sub}`,
      kind: 'audio',
      session_id: expected.session_id || null,
      envelope: { sender: 'synthetic-audio', body: '', ts: null },
      attachments: audios.map((p) => ({ type: 'audio', path: p })),
      expected,
    });
  }
  if (missingLabels > 0) {
    logger.warn && logger.warn(`[fixtures-loader] ${missingLabels} audio sessions lack expected.json; see 41-RUNBOOK.md section 4`);
  }
  return out;
}

module.exports = {
  loadSyntheticCorpus,
  loadMockSidecars,
  loadMockTranscripts,
  loadPaperLogCorpus,
  findExpectedSidecar,
  loadAudioCorpus,
  IMG_EXT_RE,
  AUDIO_EXT_RE,
};
