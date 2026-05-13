#!/usr/bin/env node
'use strict';

// Phase 42 D-03: C1 current-stage derivation tool.
//
// Derives stage from log history per the locked farmOS schema rule (C1):
//   contam > archive_spent > cold_shock > seeding > pre-inoc
// Terminal stages (spent, contaminated) dominate; otherwise the most
// advanced lifecycle event wins.
//
// Query-only. Reuses Phase 40 client. No writes. No em-dashes.

const path = require('path');
const ALERTER_CLIENT = path.join(
  __dirname,
  '..',
  'src',
  'agents',
  'alerter',
  'src',
  'farmos',
  'client.js'
);
const { createFarmosClient } = require(ALERTER_CLIENT);

const USAGE = `Usage: node tools/farmos-current-stage.js <asset_uuid> [--at <iso_timestamp>]

Derives the C1 current stage of a fungi asset from its farmOS log history.

Env required: FARMOS_URL, FARMOS_USERNAME, FARMOS_PASSWORD.

Output: JSON { asset, at, stage, evidence }.`;

function parseArgs(argv) {
  const args = argv.slice(2);
  if (args.length === 0 || args.includes('--help') || args.includes('-h')) {
    return { help: true };
  }
  let uuid = null;
  let at = null;
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === '--at') {
      at = args[++i] || null;
    } else if (!a.startsWith('--') && uuid == null) {
      uuid = a;
    }
  }
  if (!uuid) return { help: true };
  return { uuid, at };
}

function envCreds() {
  const farmosUrl = process.env.FARMOS_URL;
  const username = process.env.FARMOS_USERNAME;
  const password = process.env.FARMOS_PASSWORD;
  if (!farmosUrl || !username || !password) {
    return null;
  }
  return { farmosUrl, username, password };
}

// Derive stage from a list of log entries. Logs MUST be sorted ascending by
// timestamp; we scan once and record the most-advanced lifecycle event seen.
// Terminal events (contam, archive_spent) lock the verdict immediately.
function deriveStage(logs) {
  let stage = 'pre-inoc';
  let evidence = null;
  for (const log of logs) {
    const t = (log && log.type) || '';
    const name = (log && log.attributes && log.attributes.name) || '';
    if (t === 'activity' && name === 'contam') {
      return { stage: 'contaminated', evidence: summarize(log) };
    }
    if (t === 'activity' && name === 'archive_spent') {
      return { stage: 'spent', evidence: summarize(log) };
    }
    if (t === 'activity' && name === 'cold_shock') {
      stage = 'fruiting';
      evidence = summarize(log);
      continue;
    }
    if (t === 'seeding' && stage === 'pre-inoc') {
      stage = 'colonizing';
      evidence = summarize(log);
    }
  }
  return { stage, evidence };
}

function summarize(log) {
  if (!log) return null;
  const a = log.attributes || {};
  return {
    id: log.id || null,
    type: log.type || null,
    name: a.name || null,
    timestamp: a.timestamp || null,
  };
}

async function fetchLogs(client, uuid, at) {
  // farmOS JSON:API filter on asset.id; sort ascending by timestamp.
  // We deliberately fetch all log types in a single query and sort here so the
  // derivation logic is testable without mocking pagination.
  let q = `/api/log?filter[asset.id]=${encodeURIComponent(uuid)}&sort=timestamp`;
  if (at) {
    q += `&filter[timestamp][condition][operator]=%3C%3D&filter[timestamp][condition][value]=${encodeURIComponent(at)}`;
  }
  const r = await client.get(q);
  if (!r.ok) {
    throw new Error(`farmOS GET failed: status=${r.status} error=${r.error || 'unknown'}`);
  }
  const body = r.body || {};
  return Array.isArray(body.data) ? body.data : [];
}

async function main(argv, deps) {
  deps = deps || {};
  const { uuid, at, help } = parseArgs(argv);
  if (help) {
    process.stdout.write(USAGE + '\n');
    return 0;
  }
  const creds = envCreds();
  if (!creds) {
    process.stderr.write('error: FARMOS_URL / FARMOS_USERNAME / FARMOS_PASSWORD required\n');
    return 1;
  }
  const client = deps.client || createFarmosClient({ ...creds, fetchImpl: deps.fetchImpl });
  const logs = await fetchLogs(client, uuid, at);
  const { stage, evidence } = deriveStage(logs);
  const out = { asset: uuid, at: at || 'now', stage, evidence };
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
  return 0;
}

module.exports = { deriveStage, parseArgs, fetchLogs, main };

if (require.main === module) {
  main(process.argv).then((code) => process.exit(code)).catch((e) => {
    process.stderr.write(`error: ${e.message}\n`);
    process.exit(1);
  });
}
