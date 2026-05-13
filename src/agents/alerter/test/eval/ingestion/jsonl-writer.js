'use strict';

// Phase 41 Plan 01 Task 2: append-only per-run JSONL writer.
//
// Contract (per .planning memory rule feedback_persist_paid_results_default):
//   * Every paid LLM / Whisper run gets a unique JSONL path.
//   * NEVER truncate. NEVER overwrite. Old runs preserved for the paper trail.
//   * Per-run filename includes corpus + UTC-iso ts + run-id (random hex).
//
// Departs intentionally from Phase 38's mushdatadump.test.js which truncates
// RESULTS_JSONL_PATH on each run. See 41-RESEARCH.md section 5.

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

function createJsonlWriter({ corpus, baseDir, runId, logger = console } = {}) {
  if (!corpus) throw new Error('createJsonlWriter: corpus is required');
  const dir = baseDir || path.resolve(__dirname, 'results');
  const rid = runId || crypto.randomBytes(4).toString('hex');
  fs.mkdirSync(dir, { recursive: true });
  const tsSafe = new Date().toISOString().replace(/[:.]/g, '-');
  const filename = `${corpus}-${tsSafe}-${rid}.jsonl`;
  const fullPath = path.join(dir, filename);

  function write(obj) {
    fs.appendFileSync(fullPath, JSON.stringify(obj) + '\n');
  }

  function close() {
    // no-op for appendFileSync; reserved for streaming refactors.
  }

  return { path: fullPath, runId: rid, write, close };
}

function openRunMetadataLine({ corpus, runId, model, mode, smoke, cap_usd }) {
  return {
    ts: new Date().toISOString(),
    corpus,
    run_id: runId,
    mode: mode || 'mock',
    smoke: !!smoke,
    model: model || null,
    cap_usd: typeof cap_usd === 'number' ? cap_usd : null,
  };
}

module.exports = { createJsonlWriter, openRunMetadataLine };
