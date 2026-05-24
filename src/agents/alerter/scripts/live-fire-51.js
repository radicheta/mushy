'use strict';

// 51-LIVE-FIRE harness — Phase 51 UPSERT-07 ship-gate attestation. Replays the
// May-22 inoc fixture against dev farmOS (which already has the 4 ancestor
// stubs from the 48-LIVE-FIRE prod run, mirrored or pre-seeded on dev) and
// asserts that the upsert layer enriches the stubs in place rather than
// duplicating them, and that the children's parent[] lineage resolves to the
// expected stub UUIDs.
//
// Forks scripts/live-fire-48.js verbatim for the env-var preamble, client
// construction, and result-write idiom. Phase-51 deltas:
//   - audit-logger tallies outcome counts per write kind (asset vs log)
//   - assertion block: tally.asset.patched >= 4, no duplicate asset UUIDs
//   - lineage walk: GET /api/asset/fungi/<id> for each child, assert
//     relationships.parent.data[].id matches expected stub UUIDs from
//     .planning/notes/2026-05-24-prod-write-receipt-uuids.json.
//
// Env in:
//   FARMOS_URL        (dev e.g. http://elder-plops:18080)
//   FARMOS_USERNAME
//   FARMOS_PASSWORD
//   DRAFT_JSON_PATH   (default: test/fixtures/seeding-session-may22-commit/draft.json)
//   OUTPUT_PATH       (default: /tmp/51-live-fire-result.json)
//
// Exit codes:
//   0  — green: all assertions pass
//   1  — runtime or assertion failure
//   2  — missing required env var

const fs = require('fs');
const path = require('path');
const { createFarmosClient } = require('../src/farmos/client');
const commitSeedingSession = require('../src/farmos/commits/commit-seeding-session');

// Expected stub map from the 48-LIVE-FIRE prod write. Names → UUIDs.
// On dev these UUIDs may differ; the lineage walk asserts that the children's
// parent[] resolves to whatever the dev stub UUIDs ARE (i.e. zero duplicates,
// and the parent name matches the expected stub name in the draft).
const STUB_UUIDS = require('../../../../.planning/notes/2026-05-24-prod-write-receipt-uuids.json');
const EXPECTED_STUB_NAMES = ['260304_SHI_5', '260118_SHI_23', '260118_SHI_26', '260118_KOY_12'];

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
  const outputPath = process.env.OUTPUT_PATH || '/tmp/51-live-fire-result.json';

  const draftJson = JSON.parse(fs.readFileSync(draftJsonPath, 'utf8'));
  const client = createFarmosClient({
    farmosUrl,
    username,
    password,
    logger: console,
  });
  const draft = {
    id: 'live-fire-51-' + Date.now(),
    log_type: 'seeding_session',
    draft_json: draftJson,
  };

  // Outcome tally — bucket by kind (asset vs log) and outcome.
  const tally = {
    asset: { created: 0, patched: 0, noop: 0, mixed: 0 },
    log: { created: 0, patched: 0, noop: 0, mixed: 0 },
  };
  const auditEvents = [];
  const auditLogger = {
    async logCommit(event, d, r) {
      auditEvents.push({ event, outcome: r && r.outcome, http_status: r && r.http_status });
      if (event === 'upsert_outcome' && r && r.outcome) {
        const kind = (r.asset_ids && r.asset_ids.length) ? 'asset'
          : (r.log_ids && r.log_ids.length) ? 'log'
            : null;
        if (kind && tally[kind][r.outcome] != null) {
          tally[kind][r.outcome] += 1;
        }
      }
      console.log('[audit]', event, r && r.outcome, r && r.http_status);
    },
  };

  const t0 = Date.now();
  const result = await commitSeedingSession(client, draft, { auditLogger });
  const elapsedMs = Date.now() - t0;

  // ── Assertion block ────────────────────────────────────────────────────
  const failures = [];

  // 1. Commit-level result must be ok.
  if (!result || !result.ok) {
    failures.push('commit not ok: ' + JSON.stringify(result));
  }

  // 2. No duplicate UUIDs in asset_ids (T-51-13 — DoS via runaway dupes).
  const allMintedIds = (result && result.asset_ids) || [];
  const uniqueIds = new Set(allMintedIds);
  if (uniqueIds.size !== allMintedIds.length) {
    failures.push('duplicate UUIDs in result.asset_ids: ' + JSON.stringify(allMintedIds));
  }

  // 3. Stub enrichment: tally.asset.patched >= 4 (the 4 stubs were enriched).
  if (tally.asset.patched < 4) {
    failures.push('expected >=4 stub assets patched; got ' + tally.asset.patched);
  }

  // 4. Lineage walk: for each child, fetch and assert parent[] contains the
  //    expected stub for that child's group. The fixture's groups[i].parent
  //    names map child→parent.
  const lineageReport = [];
  for (const group of (draftJson.groups || [])) {
    const parentName = group && group.parent && group.parent.value;
    const childNames = (group && group.child_block_names && group.child_block_names.value) || [];
    for (const childName of childNames) {
      const found = await client.get('/api/asset/fungi?filter%5Bname%5D%5Bvalue%5D=' +
        encodeURIComponent(childName));
      if (!found || !found.ok || !found.body || !found.body.data || !found.body.data.length) {
        lineageReport.push({ child: childName, parent: parentName, ok: false, reason: 'child_not_found' });
        failures.push('child not found on dev: ' + childName);
        continue;
      }
      const childAsset = found.body.data[0];
      const parentRefs = (childAsset.relationships
        && childAsset.relationships.parent
        && childAsset.relationships.parent.data) || [];
      const parentIds = parentRefs.map((r) => r.id);
      // Resolve expected parent UUID — STUB_UUIDS keyed by name when available;
      // otherwise (e.g. parent already existed pre-stub-mint), look up by name.
      let expectedParentId = STUB_UUIDS[parentName];
      if (!expectedParentId) {
        const pf = await client.get('/api/asset/fungi?filter%5Bname%5D%5Bvalue%5D=' +
          encodeURIComponent(parentName));
        if (pf && pf.ok && pf.body && pf.body.data && pf.body.data.length) {
          expectedParentId = pf.body.data[0].id;
        }
      }
      const matched = expectedParentId && parentIds.indexOf(expectedParentId) !== -1;
      lineageReport.push({
        child: childName,
        child_id: childAsset.id,
        parent: parentName,
        expected_parent_id: expectedParentId || null,
        actual_parent_ids: parentIds,
        ok: !!matched,
      });
      if (!matched) {
        failures.push('lineage mismatch for ' + childName +
          ' → ' + parentName + ' (expected ' + expectedParentId +
          ', got ' + JSON.stringify(parentIds) + ')');
      }
    }
  }

  const verdict = failures.length === 0 ? 'PASS' : 'FAIL';
  const out = {
    elapsed_ms: elapsedMs,
    draft_id: draft.id,
    farmos_url: farmosUrl,
    verdict,
    failures,
    tally,
    expected_stub_names: EXPECTED_STUB_NAMES,
    lineage_report: lineageReport,
    audit_event_count: auditEvents.length,
    ...result,
  };
  fs.writeFileSync(outputPath, JSON.stringify(out, null, 2));
  console.log(JSON.stringify(out, null, 2));
  console.log('TALLY:', JSON.stringify(tally));
  console.log('VERDICT:', verdict);
  if (verdict === 'FAIL') process.exit(1);
})().catch((e) => {
  console.error('FATAL', e && e.stack || e);
  process.exit(1);
});
