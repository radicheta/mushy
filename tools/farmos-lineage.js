#!/usr/bin/env node
'use strict';

// Phase 42 D-03.2: lineage walk.
//
// Walks parent refs through harvest and seeding logs and emits the ancestry
// chain. For the pilot the expected chain is:
//   bag -> harvest_batch -> block -> sterilization_batch
//
// Per C4: lineage is an event (a log), not a property. Each step walks BACK
// through the log whose output references the current asset to find the
// source asset(s) on that same log.
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

const USAGE = `Usage: node tools/farmos-lineage.js <asset_uuid>

Walks parent refs through harvest+seeding logs and emits ancestry chain.

Env required: FARMOS_URL, FARMOS_USERNAME, FARMOS_PASSWORD.

Output: JSON { chain: [{ uuid, name, type }, ...] }.`;

const MAX_DEPTH = 16; // pilot needs ~4; cap defends against accidental cycles.

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

async function fetchAsset(client, uuid) {
  // We don't know the asset type a priori; the JSON:API requires a bundle in
  // the path. Try the two bundles the pilot touches; broaden if needed.
  for (const bundle of ['fungi', 'group']) {
    const r = await client.get(`/api/asset/${bundle}/${encodeURIComponent(uuid)}`);
    if (r.ok && r.body && r.body.data) {
      return r.body.data;
    }
  }
  return null;
}

// Find the log whose OUTPUT references this asset (i.e. the log that created
// the asset). For a bag this is the harvest log; for a block this is the
// seeding log.
async function findParentLog(client, uuid) {
  const types = ['harvest', 'seeding'];
  for (const t of types) {
    const q = `/api/log/${t}?filter[asset.id]=${encodeURIComponent(uuid)}&sort=-timestamp`;
    const r = await client.get(q);
    if (!r.ok) continue;
    const data = (r.body && r.body.data) || [];
    if (data.length > 0) {
      // Heuristic: the parent log is the EARLIEST one whose output references
      // this asset; harvest output refs include the new bag. Sort ascending
      // then take first.
      data.sort((a, b) => {
        const ta = (a.attributes && a.attributes.timestamp) || '';
        const tb = (b.attributes && b.attributes.timestamp) || '';
        return ta.localeCompare(tb);
      });
      return data[0];
    }
  }
  return null;
}

// From a parent log, extract the SOURCE asset ids (i.e. parents in the chain).
// For a harvest: source assets are the blocks; the new bag is in the same
// relationships array, so we exclude the current asset.
function sourceAssetIds(log, currentUuid) {
  const rel = log && log.relationships && log.relationships.asset;
  const refs = (rel && rel.data) || [];
  return refs.map((r) => r.id).filter((id) => id && id !== currentUuid);
}

async function walk(client, startUuid) {
  const chain = [];
  let curUuid = startUuid;
  let depth = 0;
  while (curUuid && depth < MAX_DEPTH) {
    const asset = await fetchAsset(client, curUuid);
    if (!asset) break;
    chain.push({
      uuid: asset.id,
      name: (asset.attributes && asset.attributes.name) || null,
      type: asset.type || null,
    });
    const parentLog = await findParentLog(client, curUuid);
    if (!parentLog) break;
    const parents = sourceAssetIds(parentLog, curUuid);
    if (parents.length === 0) break;
    curUuid = parents[0]; // single-parent walk for pilot; multi-parent surfaces in pilot-reconstruct.
    depth += 1;
  }
  return chain;
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
  const chain = await walk(client, uuid);
  process.stdout.write(JSON.stringify({ chain }, null, 2) + '\n');
  return 0;
}

module.exports = { parseArgs, walk, sourceAssetIds, findParentLog, fetchAsset, main };

if (require.main === module) {
  main(process.argv).then((code) => process.exit(code)).catch((e) => {
    process.stderr.write(`error: ${e.message}\n`);
    process.exit(1);
  });
}
