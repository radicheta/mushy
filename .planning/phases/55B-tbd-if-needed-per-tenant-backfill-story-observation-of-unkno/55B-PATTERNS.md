# Phase 55B: Fidelity / Corpus-Unblock - Pattern Map

**Mapped:** 2026-06-09
**Files analyzed:** 5 new/modified surfaces
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `scripts/backfill-notebook.js` (modified) | harness/orchestrator | batch, CRUD | itself -- existing strain-gate hold path (lines 343-376) | exact (same file) |
| `scripts/build-backfill-receipt.js` (used as import, not modified) | utility | transform | itself -- `strainSetFromCsv` / `loadCsvForPage` / `computeCsvDiff` | exact (promote to commit gate) |
| `src/farmos/commits/commit-seeding-session.js` (modified) | commit handler | request-response | `src/farmos/commits/commit-observation.js` (attachment upload wiring) | role+flow exact |
| `src/farmos/groupAssets.js` (modified -- add `patchGroupAssetFiles`) | service | request-response | itself -- `upsertGroupAsset` POST pattern (lines 52-79) | exact (same file) |
| `scripts/backfill-notebook.test.js` (modified) | test | -- | itself -- `processDraftsForCapture (Plan 54.1-02 strain-gate)` describe block (line 716) | exact (same file) |
| `test/farmos/commit-seeding-session.test.js` (modified) | test | -- | itself -- `makeSessionMockClient` + existing session happy-path tests | exact (same file) |

---

## Pattern Assignments

### `scripts/backfill-notebook.js` -- fidelity gate + session aggregation

**Analog:** the existing 54.1 strain-gate hold path within the same file, `processDraftsForCapture`, lines 343-376.

**Hold pattern to copy** (lines 343-376 of `scripts/backfill-notebook.js`):

```javascript
// This is the exact pattern to replicate for the fidelity gate.
// The new gate slots in AFTER the strain-gate (after line 376), BEFORE flipDraftToConfirmed.
if (curatedStrains && curatedStrains.length > 0) {
  const dj = (draft && draft.draft_json) || {};
  const rawStrain = dj.species_code || dj.species || dj.strain || dj.fungi_type || null;
  if (rawStrain) {
    const resolved = resolveStrain(rawStrain, curatedStrains);
    if (!resolved.known) {
      // Hold this draft -- do NOT flip to confirmed, do NOT commit.
      await db.updateDraftStatus(pool, draftId, 'needs_review', {
        needs_review_reason: 'strain_unknown_pending_confirm',
      });
      // ... accumulate heldUnknownCodes ...
      entry = {
        draftId, log_type: logType,
        ok: 'held', reason: 'strain_unknown_pending_confirm',
        strain_codes: [resolved.code],
        block_name: dj.block_name || null,
        asset_ids: [], log_ids: [],
      };
      commits.push(entry);
      if (summariesFd != null) {
        appendSummaryLine(summariesFd, buildSummaryLine({
          ts, page: path.basename(pagePath), captureId, draftId, logType,
          ok: false, assetCount: 0, logCount: 0, reason: 'strain_unknown_pending_confirm',
        }));
      }
      continue;
    }
  }
}
```

Key points:
- `ok: 'held'` (string, NOT `false`) is critical -- `computePerShapeStats` in `build-backfill-receipt.js` lines 373-378 has a dedicated `c.ok === 'held'` bucket. Using `false` would inflate `failed` counts.
- The `continue` exits the draft loop iteration. No `flipDraftToConfirmed` call.
- `summariesFd != null` guard before `appendSummaryLine` matches the existing pattern throughout the loop.
- `needs_review_reason` key name is whitelisted in `extraction-db.js` UPDATE_EXTRAS_WHITELIST (verified: the strain-gate already uses this path successfully).

**`processDraftsForCapture` signature** (line 292-295):

```javascript
async function processDraftsForCapture({
  pool, client, captureId, pagePath, opts, summariesFd, extractionDb, commitRouter, dryRun,
  curatedStrains,
}) {
```

The fidelity gate needs two new parameters: `csvPath` and `pageDate` (or `csvRowsForPage` pre-loaded). Extend the destructured parameter object -- same pattern as `curatedStrains` was added. No caller changes needed beyond the single call site in `main()` at line 748-751.

**`flipDraftToConfirmed`** (lines 253-261 -- the step the fidelity gate must stay BEFORE):

```javascript
async function flipDraftToConfirmed(pool, draftId, { extractionDb } = {}) {
  const db = extractionDb || require('../src/extraction/extraction-db');
  return db.updateDraftStatus(pool, draftId, DRAFT_STATUS_CONFIRMED, {
    needs_review_reason: 'bulk_backfill_santi',
  });
}
```

**`aggregateSeedingDraftsToSessionJson` helper -- new function** (no direct analog; derived from RESEARCH.md Pattern 3):

The field names to use for the `draft_json` grouping key come from the existing `processDraftsForCapture` commit-entry line at lines 421-422:

```javascript
const dj = (draft && draft.draft_json) || {};
const strain = dj.species_code || dj.species || dj.strain || dj.fungi_type || null;
```

The `block_name` field used in the entry at line 429:
```javascript
block_name: dj.block_name || null,
```

The session aggregation function must use the same field resolution chain for species and block_name.

**`buildCsvBudget` / `consumeCsvBudget` helpers -- new functions** (derived from `strainSetFromCsv` in `build-backfill-receipt.js` lines 77-85):

```javascript
// Analog: strainSetFromCsv in scripts/build-backfill-receipt.js lines 77-85
function strainSetFromCsv(rows) {
  const m = new Map(); // strain -> count
  for (const r of rows) {
    const s = String(r.strain || '').toUpperCase();
    if (!s) continue;
    m.set(s, (m.get(s) || 0) + 1);
  }
  return m;
}
```

`buildCsvBudget` is `strainSetFromCsv` renamed; `consumeCsvBudget` is the new decrement operation. Copy the Map construction pattern exactly -- same `.toUpperCase()` normalization, same `|| ''` null-guard.

**`loadCsvForPage` -- import from `build-backfill-receipt.js`** (lines 65-71):

```javascript
// Already used by backfill-notebook.js main() via buildReceipt require at line 771.
// For the fidelity gate, require it directly at the top of processDraftsForCapture
// (or module-level) via the same require pattern used for build-backfill-receipt.
function loadCsvForPage(csvPath, pageDate) {
  if (!csvPath || !pageDate) return [];
  let text;
  try { text = fs.readFileSync(csvPath, 'utf8'); } catch (_e) { return []; }
  const all = parseCsv(text);
  return all.filter((r) => r.page_date === pageDate);
}
```

The `pageDate` comes from `pageDateForImage(path.basename(pagePath))` also exported from `build-backfill-receipt.js` (lines 148-162). Both are already exported in `module.exports` at line 532-546.

---

### `scripts/build-backfill-receipt.js` -- CSV budget source (not modified, imported)

**Role:** This file is NOT modified. Its exports `loadCsvForPage`, `strainSetFromCsv`, `computeCsvDiff`, and `pageDateForImage` are promoted from receipt-only use to commit-gate use by importing them into `backfill-notebook.js`.

**Already exported** (lines 531-546):
```javascript
module.exports = {
  ACTIVE_STRAIN_CODES,
  KNOWN_SHAPES,
  parseCsv,
  loadCsvForPage,          // <-- needed by fidelity gate
  strainSetFromCsv,        // <-- basis for buildCsvBudget
  strainSetFromCommits,
  computeCsvDiff,          // <-- still used by receipt; gate uses budget variant
  pageDateForImage,        // <-- needed to resolve page date from image basename
  // ...
};
```

**`computePerShapeStats` already handles `ok: 'held'`** (lines 373-378):

```javascript
if (c.ok === true) {
  by_shape[shape].ok += 1;
  total.ok += 1;
} else if (c.ok === 'held') {
  by_shape[shape].held += 1;
  total.held += 1;
} else {
  by_shape[shape].failed += 1;
  total.failed += 1;
}
```

This is the proof that using `ok: 'held'` consistently in the new gate entries is the correct pattern -- the stats infrastructure already handles it. The receipt table (lines 482-490) renders `held` as its own column.

---

### `src/farmos/commits/commit-seeding-session.js` -- image upload extension

**Analog:** `src/farmos/commits/commit-observation.js` -- the only existing attachment upload path.

**Attachment upload pattern** from `commit-observation.js` lines 26-42:

```javascript
const files = require('../files');

// 1. Resolve paths (observations get them from ctx.capturePathsFor).
// For backfill sessions, paths come from ctx.sessionPagePaths directly.
const captureIds = Array.isArray(draft.source_capture_ids) ? draft.source_capture_ids : [];
let paths = [];
if (ctx && typeof ctx.capturePathsFor === 'function' && captureIds.length > 0) {
  try { paths = await ctx.capturePathsFor(captureIds); } catch (_) { paths = []; }
}
const upRes = paths.length > 0
  ? await files.uploadAttachments(client, paths, { logger: ctx && ctx.logger })
  : { fileIds: [], skipped: [], failed: [] };

// 2. Surface failures without aborting (D-05a best-effort semantics).
const attachmentsFailed = Array.isArray(upRes.failed) ? upRes.failed : [];
if (attachmentsFailed.length > 0 && ctx && ctx.logger && ctx.logger.warn) {
  ctx.logger.warn(`[commit-observation] ${attachmentsFailed.length} attachment(s) failed ...`);
}
```

**Key difference for `commit-seeding-session.js`:** instead of `ctx.capturePathsFor`, use `ctx.sessionPagePaths` (an array of absolute paths). The upload call is otherwise identical. The result is used to call the new `patchGroupAssetFiles` (not passed to `createLog` at creation time, because the group asset is already created by `upsertGroupAsset`).

**Return shape** from `commit-observation.js` lines 59-67 -- add analogous `attachments_failed` field:

```javascript
return {
  ok: true,
  asset_ids: [],
  log_ids: [r.logId],
  file_ids: upRes.fileIds,
  attachments_failed: attachmentsFailed,   // <-- add this to commitSeedingSession return
  attachments_skipped: attachmentsSkipped,
  http_status: r.http_status,
};
```

**Insertion point in `commit-seeding-session.js`:** after `upsertGroupAsset` succeeds (line 138-148) and before the children loop (line 152). The `sessionGroupId` is available at line 147. This is the exact point to call `uploadAttachments` then `patchGroupAssetFiles`.

**Current return shape** (lines 269-280) must be extended to include `file_ids` populated (already present as `file_ids: []`) and `attachments_failed`:

```javascript
return {
  ok: true,
  asset_ids: assetIdsOut,
  log_ids: logIdsOut,
  file_ids: [],       // currently always []; will become upRes.fileIds
  http_status: 201,
};
```

---

### `src/farmos/groupAssets.js` -- add `patchGroupAssetFiles`

**Analog:** the existing `upsertGroupAsset` POST pattern in the same file (lines 52-79).

**POST pattern to mirror** (lines 58-78):

```javascript
const payload = {
  data: {
    type: 'asset--group',
    attributes: {
      name,
      status: 'active',
      notes: { value: noteTrailer, format: 'plain_text' },
    },
  },
};
const r = await client.post('/api/asset/group', payload);
if (!r.ok) {
  return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
}
```

**PATCH variant for file relationship** (new function, same module):

```javascript
async function patchGroupAssetFiles(client, assetId, fileIds) {
  if (!fileIds || fileIds.length === 0) return { ok: true, skipped: true };
  const payload = {
    data: {
      type: 'asset--group',
      id: assetId,
      relationships: {
        file: {
          data: fileIds.map((id) => ({ type: 'file--file', id })),
        },
      },
    },
  };
  const r = await client.patch('/api/asset/group/' + assetId, payload);
  if (!r.ok) {
    return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
  }
  return { ok: true, http_status: r.status };
}
```

Error return shape mirrors the existing `deleteGroupAsset` pattern (lines 81-92):
```javascript
if (!r.ok) return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
```

Add `patchGroupAssetFiles` to `module.exports` at line 95-100 alongside the existing exports.

**Assumption to verify before full implementation (RESEARCH.md A1):** `client.patch` is available and farmOS `/api/asset/group/<id>` accepts a PATCH with `relationships.file`. Smoke against dev `:18080` before implementation commit.

---

### `scripts/backfill-notebook.test.js` -- fidelity gate + aggregation tests

**Analog:** the existing `processDraftsForCapture (Plan 54.1-02 strain-gate)` describe block starting at line 716.

**Mock setup pattern** (lines 716-742 of `backfill-notebook.test.js`):

```javascript
// Phase 54.1 Plan 02 Task 1 tests: strain-gate in processDraftsForCapture
describe('processDraftsForCapture (Plan 54.1-02 strain-gate)', () => {
  // ... mock extractionDb + commitRouter injected via processDraftsForCapture params
  const mockPool = {};
  const mockClient = {};

  function makeDb(overrides) {
    return {
      getDraftsForCapture: jest.fn().mockResolvedValue([makeDraft()]),
      updateDraftStatus: jest.fn().mockResolvedValue({ ok: true }),
      ...overrides,
    };
  }

  function makeRouter(overrides) {
    return {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: ['uuid-1'], log_ids: ['log-1'] }),
      ...overrides,
    };
  }
```

All new fidelity tests follow the same pattern:
- `makeDb` with `updateDraftStatus` as a jest.fn() to assert `needs_review` calls
- `makeRouter` to assert commit is/isn't called
- Inject `loadCsvForPage` (or a mock) as a parameter to `processDraftsForCapture`
- Assert `entry.ok === 'held'` and `entry.reason` for hold cases
- Assert `router.commit` was called for verified cases

**Test describe blocks to add** (new, no existing analog, but same structure as strain-gate block):

1. `processDraftsForCapture (fidelity cross-check)` -- four sub-tests:
   - no CSV rows holds all with reason `fidelity_cross_check_no_csv`
   - CSV-match commits (does not call `updateDraftStatus` with `needs_review`)
   - CSV-mismatch holds with reason `fidelity_cross_check_unverified`
   - budget-exhausted holds when CSV count < draft count for same strain

2. `aggregateSeedingDraftsToSessionJson` -- three sub-tests:
   - single parent+species group
   - multi-parent produces multiple groups
   - `child_block_names` array populated correctly

3. `buildCsvBudget / consumeCsvBudget` -- two sub-tests:
   - builds correct Map from CSV rows
   - decrement returns false when budget reaches 0

---

### `test/farmos/commit-seeding-session.test.js` -- image upload tests

**Analog:** the existing `makeSessionMockClient` and happy-path describe block (lines 37-73 of the test file).

**Mock client extension needed** (lines 37-73):

```javascript
function makeSessionMockClient(opts = {}) {
  const {
    knownAssetsByName = {},
    knownGroupsByName = {},
    failLogIndex = -1,
    failLogStatus = 422,
    failActivityLog = false,
    deleteResponse = null,
  } = opts;

  const client = makeMockClient({ knownAssetsByName, knownGroupsByName });
  client._deletes = [];

  // Replace post to support failLogIndex and failActivityLog.
  const origPost = client.post;
  // ...
  client.delete = jest.fn(async (p, o) => { ... });
  return client;
}
```

For image upload tests, `makeSessionMockClient` needs extension with:
- `client.patch` as a jest.fn() to assert the PATCH payload shape
- `client.postBinary` mock (for `uploadAttachment` inside `files.js`) to return a file UUID

**Existing `files.js` mock pattern from other test files** -- find via:

```bash
grep -r "postBinary\|uploadAttachment" src/agents/alerter/test/ --include="*.js" -l
```

**Test describe blocks to add:**

1. `commitSeedingSession -- image upload (D-03)` -- three sub-tests:
   - `patchGroupAssetFiles` sends correct JSON:API PATCH payload (assert `client.patch` call with `relationships.file`)
   - upload then patch path (assert `client.postBinary` then `client.patch` called in order)
   - image upload failure is non-fatal (mock `postBinary` to fail; assert session commit still `ok: true` and `attachments_failed` populated)

---

## Shared Patterns

### Hold state write (`updateDraftStatus`)

**Source:** `scripts/backfill-notebook.js` lines 350-353 (strain-gate hold path)
**Apply to:** every new hold path in the fidelity gate

```javascript
await db.updateDraftStatus(pool, draftId, 'needs_review', {
  needs_review_reason: 'strain_unknown_pending_confirm',  // change reason value only
});
```

Three distinct `needs_review_reason` values for 55b:
- `'fidelity_cross_check_no_csv'` -- page has no CSV rows
- `'fidelity_cross_check_unverified'` -- seeding strain not in CSV budget
- `'fidelity_cross_check_nonseeding'` -- non-seeding shape on CSV-covered page

### Held commit entry shape

**Source:** `scripts/backfill-notebook.js` lines 360-367
**Apply to:** all three hold branches in the fidelity gate

```javascript
entry = {
  draftId, log_type: logType,
  ok: 'held',                              // string, NOT false
  reason: 'strain_unknown_pending_confirm', // change to appropriate fidelity reason
  strain_codes: [resolved.code],           // use extracted strain for seeding; [] for non-seeding
  block_name: dj.block_name || null,
  asset_ids: [], log_ids: [],
};
commits.push(entry);
```

### Best-effort upload semantics

**Source:** `src/farmos/commits/commit-observation.js` lines 36-42
**Apply to:** image upload in `commit-seeding-session.js`

```javascript
// Best-effort: a failed upload is surfaced but NEVER aborts the commit.
const attachmentsFailed = Array.isArray(upRes.failed) ? upRes.failed : [];
if (attachmentsFailed.length > 0 && ctx && ctx.logger && ctx.logger.warn) {
  ctx.logger.warn(`[commit-seeding-session] ${attachmentsFailed.length} page image(s) failed to upload`);
}
// Do NOT return early here; continue to children loop.
```

### JSON:API error return shape

**Source:** `src/farmos/groupAssets.js` line 88 / `src/farmos/commits/commit-seeding-session.js` lines 143-146
**Apply to:** `patchGroupAssetFiles` error return

```javascript
return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
```

---

## No Analog Found

No files in this phase are without codebase analog. All patterns are wiring of existing infrastructure.

---

## Verification Notes

All analog claims from RESEARCH.md were verified against source:

| Claim | Verified |
|-------|---------|
| Strain-gate hold path is in `processDraftsForCapture` lines 343-376 | Yes -- exact |
| `strainSetFromCsv` is in `build-backfill-receipt.js` lines 77-85 | Yes -- exact |
| `loadCsvForPage` is exported from `build-backfill-receipt.js` | Yes -- line 533 |
| `computePerShapeStats` has `ok === 'held'` bucket at lines 373-378 | Yes -- exact |
| `commit-observation.js` is the only file with attachment upload code | Yes -- `files.js` imported only there among commit handlers |
| `upsertGroupAsset` POST in `groupAssets.js` is the PATCH shape basis | Yes -- lines 52-79 |
| `commit-seeding-session.js` has no `files.js` import today | Confirmed -- imports are `assets`, `logs`, `groupAssets`, `activityLogs` only (lines 19-22) |
| `patchGroupAssetFiles` does not yet exist in `groupAssets.js` | Confirmed -- `module.exports` lines 95-100 has only `findGroupAssetByName`, `upsertGroupAsset`, `deleteGroupAsset`, `_clearCache` |
| Existing test file `commit-seeding-session.test.js` has no image upload tests | Confirmed -- `makeSessionMockClient` has no `postBinary` or `patch` setup |

---

## Metadata

**Analog search scope:** `src/agents/alerter/scripts/`, `src/agents/alerter/src/farmos/commits/`, `src/agents/alerter/src/farmos/`, `src/agents/alerter/test/`
**Files read:** 7 source files + 2 test files
**Pattern extraction date:** 2026-06-09
