#!/usr/bin/env node
'use strict';

// Phase 42 D-03.3: pilot timeline reconstruct.
//
// Emits a human-readable timeline of pilot events derived ENTIRELY from
// farmOS logs (no Signal refs). Validates PILOT-06: operator can reconstruct
// the lifecycle from farmOS alone.
//
// Strategy: fetch every log touching the block uuid + every harvest log
// produced from the block (which surfaces bag assets). Sort ascending by
// timestamp; emit one row per log.
//
// Query-only. No em-dashes.

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

const USAGE = `Usage: node tools/farmos-pilot-reconstruct.js <block_uuid>

Reconstructs the pilot lifecycle timeline from farmOS logs alone.

Env required: FARMOS_URL, FARMOS_USERNAME, FARMOS_PASSWORD.

Output: text timeline, one event per line (sorted by timestamp).`;

const LOG_TYPES = ['seeding', 'activity', 'observation', 'harvest', 'input'];

function parseArgs(argv) {
  const args = argv.slice(2);
  if (args.length === 0 || args.includes('--help') || args.includes('-h')) {
    return { help: true };
  }
  const uuid = args.find((a) => !a.startsWith('--')) || null;
  if (!uuid) return { help: true };
  return { uuid };
}

function envCreds() {
  const farmosUrl = process.env.FARMOS_URL;
  const username = process.env.FARMOS_USERNAME;
  const password = process.env.FARMOS_PASSWORD;
  if (!farmosUrl || !username || !password) return null;
  return { farmosUrl, username, password };
}

async function fetchLogsForType(client, type, uuid) {
  const q = `/api/log/${type}?filter[asset.id]=${encodeURIComponent(uuid)}&sort=timestamp`;
  const r = await client.get(q);
  if (!r.ok) return [];
  return (r.body && r.body.data) || [];
}

async function gatherAllLogs(client, blockUuid) {
  // First pass: every log touching the block.
  const all = [];
  for (const type of LOG_TYPES) {
    const logs = await fetchLogsForType(client, type, blockUuid);
    all.push(...logs);
  }

  // Second pass: every harvest log surfaces bag assets. Fetch logs touching
  // each bag too so the timeline includes the bag-side events (harvest +
  // archive_spent on the harvest_batch, etc).
  const seenAssets = new Set([blockUuid]);
  for (const log of all) {
    if ((log.type || '').endsWith('harvest')) {
      const refs = (log.relationships && log.relationships.asset && log.relationships.asset.data) || [];
      for (const r of refs) {
        if (r.id && !seenAssets.has(r.id)) {
          seenAssets.add(r.id);
          for (const type of LOG_TYPES) {
            const more = await fetchLogsForType(client, type, r.id);
            all.push(...more);
          }
        }
      }
    }
  }

  // Dedupe by log id; sort ascending by timestamp.
  const byId = new Map();
  for (const log of all) {
    if (log && log.id && !byId.has(log.id)) byId.set(log.id, log);
  }
  const deduped = Array.from(byId.values());
  deduped.sort((a, b) => {
    const ta = (a.attributes && a.attributes.timestamp) || '';
    const tb = (b.attributes && b.attributes.timestamp) || '';
    return ta.localeCompare(tb);
  });
  return deduped;
}

function fmtRow(log) {
  const a = log.attributes || {};
  const ts = a.timestamp || '?';
  const type = (log.type || '').replace(/^log--/, '');
  const name = a.name || '';
  const refs = (log.relationships && log.relationships.asset && log.relationships.asset.data) || [];
  const refIds = refs.map((r) => r.id).join(',');
  const parts = [`[${ts}]`, type];
  if (name) parts.push(name);
  if (refIds) parts.push(`refs=${refIds}`);
  return parts.join(' ');
}

function fmtTimeline(logs) {
  if (logs.length === 0) return '(no logs)';
  return logs.map(fmtRow).join('\n');
}

async function main(argv, deps) {
  deps = deps || {};
  const { uuid, help } = parseArgs(argv);
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
  const logs = await gatherAllLogs(client, uuid);
  process.stdout.write(fmtTimeline(logs) + '\n');
  return 0;
}

module.exports = { parseArgs, gatherAllLogs, fmtRow, fmtTimeline, main };

if (require.main === module) {
  main(process.argv).then((code) => process.exit(code)).catch((e) => {
    process.stderr.write(`error: ${e.message}\n`);
    process.exit(1);
  });
}
