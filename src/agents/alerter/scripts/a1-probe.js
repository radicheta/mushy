#!/usr/bin/env node
// Phase 55B Plan 01 Task 4 — A1 PATCH-associates-files dev smoke probe.
// DEV-LOCKED: the dev URL is hardcoded here and prod (:8082) is refused, so this
// probe physically cannot touch production even if FARMOS_URL in the env is prod.
// Reads only credentials from the environment (FARMOS_USERNAME / FARMOS_PASSWORD).
// Writes the outcome to 55B-A1-SMOKE.md.

const fs = require('fs');
const os = require('os');
const path = require('path');

const DEV_URL = 'http://10.68.155.50:18080'; // dev only — never :8082
if (/:8082|prod/i.test(DEV_URL)) { console.error('FATAL: dev URL guard tripped'); process.exit(2); }

const username = process.env.FARMOS_USERNAME;
const password = process.env.FARMOS_PASSWORD;
if (!username || !password) {
  console.error('Missing FARMOS_USERNAME / FARMOS_PASSWORD in env.');
  console.error('Run:  set -a; source /mnt/slime-kingdom/opt/mushy/.env; set +a   then re-run this script.');
  process.exit(2);
}

const { createFarmosClient } = require('../src/farmos/client');
const { upsertGroupAsset, patchGroupAssetFiles } = require('../src/farmos/groupAssets');
const { uploadAttachments } = require('../src/farmos/files');

const SMOKE_PATH = '/mnt/slime-kingdom/opt/mushy/.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-A1-SMOKE.md';

(async () => {
  const log = [];
  const rec = (k, v) => { log.push(`- ${k}: ${v}`); console.log(k + ':', v); };
  let verdict = 'FAIL';
  let fallbackNote = '';
  try {
    const client = createFarmosClient({ farmosUrl: DEV_URL, username, password });
    rec('dev_url', DEV_URL);

    // Step 1: create/reuse a test group
    const g = await upsertGroupAsset(client, { name: 'A1-smoke-test-group', draftId: 'smoke-probe-55B-01' });
    rec('group_upsert', JSON.stringify(g));
    if (!g.ok) throw new Error('group upsert failed');

    // Step 2: upload a tiny JPEG to get a file--file UUID
    const tmp = path.join(os.tmpdir(), 'a1-smoke.jpg');
    fs.writeFileSync(tmp, Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46]));
    const up = await uploadAttachments(client, [tmp]);
    rec('upload', JSON.stringify(up));
    const fileId = up.fileIds && up.fileIds[0];
    if (!fileId) throw new Error('upload produced no fileIds');

    // Step 3: PATCH the group to associate the file
    const pr = await patchGroupAssetFiles(client, g.assetId, [fileId]);
    rec('patch_result', JSON.stringify(pr));

    // Step 4: GET ?include=file and confirm the relationship
    const verify = await client.get('/api/asset/group/' + g.assetId + '?include=file');
    const related = verify.body && verify.body.data && verify.body.data.relationships
      && verify.body.data.relationships.file && verify.body.data.relationships.file.data;
    rec('relationships_file_data', JSON.stringify(related));
    const found = Array.isArray(related) && related.some((f) => f.id === fileId);

    if (pr.ok && found) {
      verdict = 'PASS';
    } else {
      verdict = 'FAIL';
      fallbackNote = pr.ok
        ? 'PATCH returned ok but file UUID absent from relationships.file.data — use two-step fallback (set file relationship in the group-creation POST, or POST /api/asset/group with relationships.file inline).'
        : 'PATCH rejected (' + JSON.stringify(pr) + ') — Plan 03 must set file in the group-creation POST instead of a relationship PATCH.';
    }
    rec('verdict', verdict);
    if (fallbackNote) rec('fallback', fallbackNote);
  } catch (e) {
    verdict = 'FAIL';
    fallbackNote = 'Probe error: ' + e.message + ' — investigate before choosing fallback.';
    rec('error', e.message);
  }

  const now = new Date().toISOString();
  const md = `---
phase: 55B-fidelity-corpus-unblock
plan: 01
artifact: A1-SMOKE
assumption: A1 (PATCH associates file--file to asset--group)
verdict: ${verdict}
target: dev farmOS :18080
recorded: ${now}
---

# A1 PATCH-associates-files dev smoke probe

Target: ${DEV_URL} (dev only; prod :8082 refused by script guard)

## Result: ${verdict}

${log.join('\n')}

## Interpretation

${verdict === 'PASS'
  ? 'A1 VERIFIED: patchGroupAssetFiles associates a file--file UUID to an asset--group via a JSON:API relationships.file PATCH. Plan 03 uses the direct PATCH (patchGroupAssetFiles) as designed.'
  : 'A1 FALSIFIED. ' + fallbackNote + ' Plan 03 must adapt before writing the image-attach implementation.'}
`;
  fs.writeFileSync(SMOKE_PATH, md);
  console.log('\nWrote', SMOKE_PATH);
  console.log('\n=== A1 ' + verdict + ' ===');
  process.exit(verdict === 'PASS' ? 0 : 1);
})();
