'use strict';

// 48-LIVE-FIRE harness — runs commitSeedingSession against a real farmOS
// instance using the May-22 fixture draft. Replaces the inline node -e snippet
// in 48-LIVE-FIRE.md which was written against an older client signature
// (createFarmOSClient / {baseUrl, token}); the live client takes
// {farmosUrl, username, password} and session-cookie auth.
//
// Env in:
//   FARMOS_URL        (e.g. http://10.68.155.50:18080)
//   FARMOS_USERNAME   (e.g. mushy-bot)
//   FARMOS_PASSWORD
//   DRAFT_JSON_PATH   (default: test/fixtures/seeding-session-may22-commit/draft.json)
//   OUTPUT_PATH       (default: /tmp/48-live-fire-result.json)
//
// Writes the commit result JSON to OUTPUT_PATH and prints it to stdout.

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
  const draftJsonPath = process.env.DRAFT_JSON_PATH ||
    path.join(__dirname, '..', 'test', 'fixtures',
      'seeding-session-may22-commit', 'draft.json');
  const outputPath = process.env.OUTPUT_PATH || '/tmp/48-live-fire-result.json';

  const draftJson = JSON.parse(fs.readFileSync(draftJsonPath, 'utf8'));
  const client = createFarmosClient({
    farmosUrl,
    username,
    password,
    logger: console,
  });
  const draft = {
    id: 'live-fire-48-' + Date.now(),
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
  const out = { elapsed_ms: Date.now() - t0, draft_id: draft.id, ...result };
  fs.writeFileSync(outputPath, JSON.stringify(out, null, 2));
  console.log(JSON.stringify(out, null, 2));
})().catch((e) => {
  console.error('FATAL', e && e.stack || e);
  process.exit(1);
});
