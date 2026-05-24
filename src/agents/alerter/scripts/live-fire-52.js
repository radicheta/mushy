'use strict';

// 52-LIVE-FIRE harness -- runs commitSeedingSession against dev farmOS at
// :18080 using the May-22 fixture draft. Validates the Phase 52 shape:
//
//   1 asset--group  (session, named "inoc YYYY-MM-DD" + optional "#N")
//   5 asset--fungi  (source blocks; POST first run, PATCH/noop on subsequent)
//  11 asset--fungi  (child blocks;  POST first run, noop on subsequent)
//   1 log--activity (membership, is_group_assignment=true)
//  11 log--seeding  (one per child; POST first run, noop on subsequent)
//
// Verification probes after commit:
//   - membership walk: GET /api/log/activity?filter[is_group_assignment]=1
//                          &filter[asset.id]=<childId>
//     -> response[0].relationships.group.data[0].id === sessionGroupId
//   - lineage walk:   GET /api/asset/fungi/<childId>
//     -> relationships.parent.data has ONE entry of type 'asset--fungi'
//        (the source block, NOT the session group)
//
// Hard PROD-GUARD: refuses to run against :8082 (prod farmOS). See
// .planning/phases/52-.../52-CONTEXT.md "NO prod live-fire in this phase".
//
// Env in:
//   FARMOS_URL        (e.g. http://10.68.155.50:18080 -- DEV ONLY)
//   FARMOS_USERNAME   (e.g. mushy-bot)
//   FARMOS_PASSWORD
//   DRAFT_JSON_PATH   (default: test/fixtures/seeding-session-may22-commit/draft.json)
//   OUTPUT_PATH       (default: /tmp/52-live-fire-result.json)
//
// Writes the commit result + probe outcomes to OUTPUT_PATH and stdout.
// Exit codes:
//   0  success (commit ok + both probes pass)
//   1  fatal (unhandled exception)
//   2  probe assertion failed
//   3  prod-guard tripped

const fs = require('fs');
const path = require('path');
const { createFarmosClient } = require('../src/farmos/client');
const commitSeedingSession = require('../src/farmos/commits/commit-seeding-session');

(async () => {
  const farmosUrl = process.env.FARMOS_URL;
  const username = process.env.FARMOS_USERNAME;
  const password = process.env.FARMOS_PASSWORD;
  if (!farmosUrl || !username || !password) {
    console.error('FARMOS_URL + FARMOS_USERNAME + FARMOS_PASSWORD required');
    process.exit(2);
  }

  // Hard PROD-GUARD per 52-CONTEXT.md (NO prod live-fire this phase).
  const lowerUrl = String(farmosUrl).toLowerCase();
  if (lowerUrl.endsWith(':8082') || lowerUrl.includes(':8082/') || lowerUrl.includes('prod')) {
    console.error('REFUSING to run live-fire-52 against a prod-looking URL: ' + farmosUrl);
    console.error('Phase 52 is dev-only. See .planning/phases/52-.../52-CONTEXT.md.');
    process.exit(3);
  }

  const draftJsonPath = process.env.DRAFT_JSON_PATH ||
    path.join(__dirname, '..', 'test', 'fixtures',
      'seeding-session-may22-commit', 'draft.json');
  const outputPath = process.env.OUTPUT_PATH || '/tmp/52-live-fire-result.json';

  const draftJson = JSON.parse(fs.readFileSync(draftJsonPath, 'utf8'));
  const client = createFarmosClient({
    farmosUrl,
    username,
    password,
    logger: console,
  });
  const draft = {
    id: 'live-fire-52-' + Date.now(),
    log_type: 'seeding_session',
    draft_json: draftJson,
  };
  const auditLogger = {
    logCommit: async (event, d, r) => {
      console.log('[audit]', event, r && r.status);
    },
  };

  const t0 = Date.now();
  const result = await commitSeedingSession(client, draft, { auditLogger });
  const elapsed_ms = Date.now() - t0;

  let membership_walk_ok = false;
  let lineage_walk_ok = false;
  const probe_details = {};

  if (result.ok) {
    // sessionGroupId is at asset_ids[0] when newly created (see Plan 03 contract).
    // To be defensive, probe each asset_id with GET-by-id and pick the first
    // type 'asset--group'.
    let sessionGroupId = null;
    let childId = null;
    for (const id of result.asset_ids || []) {
      const probe = await client.get('/api/asset/group/' + id);
      if (probe.ok && probe.body && probe.body.data && probe.body.data.type === 'asset--group') {
        sessionGroupId = id;
        break;
      }
    }
    for (const id of result.asset_ids || []) {
      if (id === sessionGroupId) continue;
      const probe = await client.get('/api/asset/fungi/' + id);
      if (probe.ok && probe.body && probe.body.data && probe.body.data.type === 'asset--fungi') {
        // pick a child (name starts with the event-date prefix); fall back to any fungi
        const name = probe.body.data.attributes && probe.body.data.attributes.name;
        childId = id;
        if (name && /^2[0-9]{5}_/.test(name)) break; // YYMMDD_-prefix is a child block
      }
    }
    probe_details.sessionGroupId = sessionGroupId;
    probe_details.childId = childId;

    if (sessionGroupId && childId) {
      // Membership walk.
      const memPath = '/api/log/activity?filter[is_group_assignment]=1'
        + '&filter[asset.id]=' + encodeURIComponent(childId);
      const memResp = await client.get(memPath);
      probe_details.membership_walk_status = memResp.status;
      if (memResp.ok && memResp.body && Array.isArray(memResp.body.data)) {
        for (const log of memResp.body.data) {
          const groupData = log && log.relationships && log.relationships.group
            && log.relationships.group.data;
          const arr = Array.isArray(groupData) ? groupData : (groupData ? [groupData] : []);
          if (arr.some((g) => g && g.id === sessionGroupId)) {
            membership_walk_ok = true;
            break;
          }
        }
      }

      // Lineage walk.
      const linResp = await client.get('/api/asset/fungi/' + childId);
      probe_details.lineage_walk_status = linResp.status;
      if (linResp.ok && linResp.body && linResp.body.data) {
        const parentData = linResp.body.data.relationships
          && linResp.body.data.relationships.parent
          && linResp.body.data.relationships.parent.data;
        const parents = Array.isArray(parentData) ? parentData : (parentData ? [parentData] : []);
        probe_details.parent_count = parents.length;
        probe_details.parent_types = parents.map((p) => p && p.type);
        if (parents.length === 1
            && parents[0].type === 'asset--fungi'
            && parents[0].id !== sessionGroupId) {
          lineage_walk_ok = true;
        }
      }
    }
  }

  const out = {
    elapsed_ms,
    draft_id: draft.id,
    membership_walk_ok,
    lineage_walk_ok,
    probe_details,
    ...result,
  };
  fs.writeFileSync(outputPath, JSON.stringify(out, null, 2));
  console.log(JSON.stringify(out, null, 2));

  if (!result.ok) {
    process.exit(2);
  }
  if (!membership_walk_ok || !lineage_walk_ok) {
    console.error('PROBE FAILURE: membership_walk_ok=' + membership_walk_ok
      + ' lineage_walk_ok=' + lineage_walk_ok);
    process.exit(2);
  }
})().catch((e) => {
  console.error('FATAL', e && e.stack || e);
  process.exit(1);
});
