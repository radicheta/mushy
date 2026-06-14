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

// Load creds in-process WITHOUT printing them (the sanctioned remedy for the
// transcript secret-leak guard). Root .env supplies the username; the authoritative
// bot password lives in tenants/mossrock/secrets.env (docker-compose.override.yml:148),
// sourced second so it overrides any stale value in .env.
function loadEnvFile(p) {
  try {
    for (const line of fs.readFileSync(p, 'utf8').split('\n')) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (m) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
    }
  } catch (_) { /* file optional */ }
}
loadEnvFile('/mnt/slime-kingdom/opt/mushy/.env');
loadEnvFile('/mnt/slime-kingdom/opt/mushy/tenants/mossrock/secrets.env');

const username = process.env.FARMOS_USERNAME;
const password = process.env.FARMOS_PASSWORD;
if (!username || !password) {
  console.error('Missing FARMOS_USERNAME / FARMOS_PASSWORD after loading .env + secrets.env.');
  process.exit(2);
}

const { createFarmosClient } = require('../src/farmos/client');
const { upsertGroupAsset, deleteGroupAsset } = require('../src/farmos/groupAssets');
const { uploadFieldAttachment } = require('../src/farmos/files');

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

    // Step 2: upload a tiny JPEG to the group's `image` field via the field-scoped
    // binary route. This CREATES the file AND links it in one call (no separate PATCH).
    const tmp = path.join(os.tmpdir(), 'a1-smoke.jpg');
    fs.writeFileSync(tmp, Buffer.from([
      0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46,
      0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xff, 0xd9,
    ]));
    const up = await uploadFieldAttachment(client, '/api/asset/group', g.assetId, 'image', tmp);
    rec('image_upload', JSON.stringify(up));
    if (!up.ok) throw new Error('image upload failed: ' + (up.reason || 'unknown'));

    // Step 3: GET the group's image relationship and confirm the file is linked.
    const verify = await client.get('/api/asset/group/' + g.assetId + '/image');
    const data = verify.body && verify.body.data;
    const linked = Array.isArray(data) ? data : (data ? [data] : []);
    rec('linked_images', JSON.stringify(linked.map((f) => f && f.attributes && f.attributes.filename)));
    const found = linked.length > 0;

    if (up.ok && found) {
      verdict = 'PASS';
    } else {
      verdict = 'FAIL';
      fallbackNote = up.ok
        ? 'Upload returned ok but no image is linked on the group -- check the image field config.'
        : 'Field-scoped image upload rejected (' + JSON.stringify(up) + ').';
    }
    rec('verdict', verdict);
    if (fallbackNote) rec('fallback', fallbackNote);

    // GA1 hygiene: delete the dev smoke group so probe re-runs do not accumulate.
    const del = await deleteGroupAsset(client, g.assetId);
    rec('cleanup_delete', JSON.stringify(del));
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
assumption: A1' (field-scoped binary upload links image to asset--group)
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
  ? "A1' VERIFIED: a field-scoped binary POST to /api/asset/group/{uuid}/image (Content-Type octet-stream) creates the file AND links it to the group's image field in one call. files.uploadFieldAttachments uses this route; commit-seeding-session attaches page photos this way. No relationships.file PATCH needed."
  : "A1' FALSIFIED. " + fallbackNote}
`;
  fs.writeFileSync(SMOKE_PATH, md);
  console.log('\nWrote', SMOKE_PATH);
  console.log('\n=== A1 ' + verdict + ' ===');
  process.exit(verdict === 'PASS' ? 0 : 1);
})();
