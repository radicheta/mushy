#!/usr/bin/env node
'use strict';

// Phase 41 Plan 07 Task 2: regression detector for two ingestion JSONL files.
//
// Cites CONTEXT D-06b + RESEARCH section 12. Per-fixture diff via fixture_id.
// Exit codes:
//   0 -- no regressions
//   1 -- at least one regression (PASS->FAIL transition or score drop > threshold)
//   2 -- internal error (missing file, bad JSON)

const fs = require('fs');

let _fmtNum = null;
function fmtNum(n) {
  if (!_fmtNum) {
    try { _fmtNum = require('../../../src/message').fmtNum; }
    catch (_) { _fmtNum = (x) => (typeof x === 'number' ? (Math.round(x * 10) / 10).toString().replace(/\.0$/, '') : String(x)); }
  }
  return _fmtNum(n);
}

function loadJsonl(p) {
  if (!fs.existsSync(p)) throw new Error(`compare-runs: file not found: ${p}`);
  const text = fs.readFileSync(p, 'utf8');
  const lines = text.split('\n').filter((l) => l.trim().length > 0);
  return lines.map((l, idx) => {
    try { return JSON.parse(l); }
    catch (e) { throw new Error(`compare-runs: bad JSON at ${p}:${idx + 1}: ${e.message}`); }
  });
}

function fixtureScore(row) {
  // Binary: actual.ok ? 1 : 0. Future: extend to numeric scores if present.
  if (!row || !row.actual) return null;
  return row.actual.ok ? 1 : 0;
}

function compare(olderPath, newerPath, { threshold = 0.05, logger = console } = {}) {
  const older = loadJsonl(olderPath);
  const newer = loadJsonl(newerPath);
  const byId = (arr) => {
    const m = new Map();
    for (const r of arr) if (r.fixture_id) m.set(r.fixture_id, r);
    return m;
  };
  const oMap = byId(older);
  const nMap = byId(newer);
  const allIds = new Set([...oMap.keys(), ...nMap.keys()]);

  const rows = [];
  let regressions = 0;
  for (const id of allIds) {
    const o = oMap.get(id);
    const n = nMap.get(id);
    if (!o && n) { rows.push({ fixture_id: id, older_ok: null, newer_ok: !!(n.actual && n.actual.ok), delta: null, status: 'NEW' }); continue; }
    if (o && !n) { rows.push({ fixture_id: id, older_ok: !!(o.actual && o.actual.ok), newer_ok: null, delta: null, status: 'REMOVED' }); continue; }
    const os = fixtureScore(o);
    const ns = fixtureScore(n);
    const delta = (ns != null && os != null) ? (ns - os) : null;
    let status = 'PASS';
    if (os === 1 && ns === 0) { status = 'REGRESSION'; regressions += 1; }
    else if (delta != null && delta < -threshold) { status = 'REGRESSION'; regressions += 1; }
    rows.push({ fixture_id: id, older_ok: os === 1, newer_ok: ns === 1, delta, status });
  }
  // Print table
  logger.info(`compare-runs: older=${olderPath} newer=${newerPath} threshold=${threshold}`);
  logger.info('fixture_id\tolder_ok\tnewer_ok\tdelta\tstatus');
  for (const r of rows) {
    logger.info(`${r.fixture_id}\t${r.older_ok}\t${r.newer_ok}\t${r.delta == null ? 'n/a' : fmtNum(r.delta)}\t${r.status}`);
  }
  logger.info(`compare-runs: ${rows.length} fixtures, ${regressions} regressions`);
  return { rows, regressions };
}

function main(argv = process.argv) {
  const args = argv.slice(2);
  let threshold = 0.05;
  const paths = [];
  for (let i = 0; i < args.length; i += 1) {
    const a = args[i];
    if (a === '--threshold') threshold = parseFloat(args[++i]);
    else if (a.startsWith('--threshold=')) threshold = parseFloat(a.slice('--threshold='.length));
    else paths.push(a);
  }
  if (paths.length !== 2) {
    console.error('Usage: compare-runs.js <older.jsonl> <newer.jsonl> [--threshold 0.05]');
    process.exitCode = 2;
    return;
  }
  try {
    const { regressions } = compare(paths[0], paths[1], { threshold });
    process.exitCode = regressions > 0 ? 1 : 0;
  } catch (e) {
    console.error(`compare-runs: ${e.message}`);
    process.exitCode = 2;
  }
}

if (require.main === module) {
  main();
}

module.exports = { compare, loadJsonl, fixtureScore, main };
