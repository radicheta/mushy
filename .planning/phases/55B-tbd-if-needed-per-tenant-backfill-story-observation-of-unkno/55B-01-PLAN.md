---
phase: 55B-fidelity-corpus-unblock
plan: 01
type: execute
wave: 0
depends_on: []
files_modified:
  - src/agents/alerter/scripts/backfill-notebook.test.js
  - src/agents/alerter/test/farmos/commit-seeding-session.test.js
  - src/agents/alerter/src/farmos/groupAssets.js
autonomous: false
requirements: [FIDELITY-01, FIDELITY-02, SESSION-01, SESSION-02]
must_haves:
  truths:
    - "RED test scaffolds exist for the fidelity gate, session aggregation, and image-attach paths before any implementation lands"
    - "patchGroupAssetFiles exists and PATCHes asset--group file relationships"
    - "The A1 PATCH-associates-files assumption is proven against dev farmOS :18080 before the image-attach implementation is written"
  artifacts:
    - path: "src/agents/alerter/scripts/backfill-notebook.test.js"
      provides: "Fidelity cross-check + aggregation + csv-budget RED test describe blocks"
      contains: "fidelity cross-check"
    - path: "src/agents/alerter/test/farmos/commit-seeding-session.test.js"
      provides: "patch_files + image-upload RED test describe blocks"
      contains: "patch_files"
    - path: "src/agents/alerter/src/farmos/groupAssets.js"
      provides: "patchGroupAssetFiles JSON:API PATCH helper"
      contains: "patchGroupAssetFiles"
  key_links:
    - from: "src/farmos/groupAssets.js patchGroupAssetFiles"
      to: "client.patch('/api/asset/group/<id>')"
      via: "JSON:API relationships.file payload"
      pattern: "relationships.*file"
---

<objective>
Stand up the Wave 0 validation floor for Phase 55B: add the RED test scaffolds the
two implementation waves will turn green, add the `patchGroupAssetFiles` JSON:API
helper, and prove the A1 assumption (PATCH associates files to an `asset--group`)
against dev farmOS BEFORE any image-attach implementation is written.

Purpose: The phase's two riskiest unknowns are (1) whether held drafts produce the
right buckets/reasons and (2) whether farmOS even accepts a relationship PATCH on
`asset--group` for files. Both must be locked before implementation. The A1 probe is
a hard gate — if it fails, the image-attach design changes to a two-step fallback.
Output: RED test blocks (per 55B-VALIDATION.md Wave 0 Requirements) + `patchGroupAssetFiles`
+ an operator-run dev smoke that flips A1 from [ASSUMED] to verified.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-CONTEXT.md
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-RESEARCH.md
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-PATTERNS.md
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-VALIDATION.md

<interfaces>
Confirmed against source (2026-06-09):

groupAssets.js exports (src/farmos/groupAssets.js:95-99): findGroupAssetByName,
upsertGroupAsset, deleteGroupAsset, _clearCache. upsertGroupAsset POST shape at
lines 52-79; deleteGroupAsset error return at line 87:
  return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };

client (src/farmos/client.js:174): `async function patch(path, body, opts)` exists —
client.patch is available.

backfill-notebook.test.js strain-gate analog: describe block
'processDraftsForCapture (Plan 54.1-02 strain-gate)' at line 716; makeDb / makeRouter
mock factories pattern (updateDraftStatus + commit as jest.fn()).

commit-seeding-session.test.js analog: makeSessionMockClient (lines 37-73); it has NO
client.patch and NO postBinary mock today — both must be added.

files.js exports (src/farmos/files.js:49): uploadAttachment, uploadAttachments.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add patchGroupAssetFiles to groupAssets.js + its RED payload test</name>
  <files>src/agents/alerter/src/farmos/groupAssets.js, src/agents/alerter/test/farmos/commit-seeding-session.test.js</files>
  <read_first>
    - src/agents/alerter/src/farmos/groupAssets.js (the file being modified — read upsertGroupAsset POST pattern lines 52-79 and deleteGroupAsset error return line 87)
    - src/agents/alerter/test/farmos/commit-seeding-session.test.js (analog test file — read makeSessionMockClient lines 37-73 to mirror the mock factory style)
    - .planning/phases/55B-*/55B-PATTERNS.md (the patchGroupAssetFiles PATCH-variant code excerpt, "src/farmos/groupAssets.js -- add patchGroupAssetFiles" section)
  </read_first>
  <action>
    Add `patchGroupAssetFiles(client, assetId, fileIds)` to src/farmos/groupAssets.js,
    mirroring the upsertGroupAsset POST shape but using `client.patch('/api/asset/group/' + assetId)`
    with a JSON:API body `{ data: { type: 'asset--group', id: assetId, relationships: { file: { data: fileIds.map(id => ({ type: 'file--file', id })) } } } }`.
    Early-return `{ ok: true, skipped: true }` when fileIds is empty/falsy. On `!r.ok`
    return the canonical error shape `{ ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status }`.
    On success return `{ ok: true, http_status: r.status }`. Export it in module.exports
    alongside findGroupAssetByName/upsertGroupAsset/deleteGroupAsset/_clearCache.
    Add a unit test (place in commit-seeding-session.test.js OR a new groupAssets test —
    use commit-seeding-session.test.js to keep the patch mock co-located) under a
    describe titled with the literal `patch_files` that asserts: client.patch was called
    with path `/api/asset/group/<id>` and a body whose relationships.file.data is
    `[{ type: 'file--file', id: '<fid>' }]`; and that empty fileIds returns `skipped: true`
    without calling client.patch. Extend makeSessionMockClient with a `client.patch`
    jest.fn() returning `{ ok: true, status: 200 }`.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/farmos/commit-seeding-session.test.js -t "patch_files"</automated>
  </verify>
  <acceptance_criteria>
    - `npx jest test/farmos/commit-seeding-session.test.js -t "patch_files"` passes.
    - patchGroupAssetFiles is in groupAssets.js module.exports.
    - The asserted PATCH body relationships.file.data entries are exactly `{ type: 'file--file', id }`.
    - Empty fileIds returns `{ ok: true, skipped: true }` and does NOT call client.patch.
  </acceptance_criteria>
  <done>patchGroupAssetFiles exists, exported, and its payload-shape test is green.</done>
</task>

<task type="auto">
  <name>Task 2: Add RED fidelity-gate + aggregation + csv-budget test scaffolds</name>
  <files>src/agents/alerter/scripts/backfill-notebook.test.js</files>
  <read_first>
    - src/agents/alerter/scripts/backfill-notebook.test.js (the file being modified — read the 'processDraftsForCapture (Plan 54.1-02 strain-gate)' describe block at line 716, including makeDb / makeRouter factories)
    - src/agents/alerter/scripts/backfill-notebook.js (read processDraftsForCapture signature line 292-295 + strain-gate hold path lines 343-376 + flipDraftToConfirmed lines 253-261 to mirror expected param/return shapes)
    - src/agents/alerter/scripts/build-backfill-receipt.js (read strainSetFromCsv lines 77-85 + loadCsvForPage + the `ok === 'held'` bucket in computePerShapeStats lines 373-378)
    - .planning/phases/55B-*/55B-VALIDATION.md (Per-Task Verification Map: exact -t test name tokens)
  </read_first>
  <action>
    In scripts/backfill-notebook.test.js add three NEW describe blocks, each authored to
    FAIL until the Wave 1/2 implementation lands (RED). They reference functions/params
    that do not exist yet (buildCsvBudget, consumeCsvBudget, aggregateSeedingDraftsToSessionJson,
    and the csvRowsForPage/csvBudget params of processDraftsForCapture). Use the existing
    makeDb / makeRouter mock factory style.
    (a) describe 'processDraftsForCapture (fidelity cross-check)' with test titles containing
    the tokens `no_csv`, `csv_verified`, `fidelity`, `hold_reason`, `no_csv_reason` covering:
    no-CSV-rows holds all with `needs_review_reason === 'fidelity_cross_check_no_csv'` and
    `entry.ok === 'held'`; CSV-match draft does NOT call updateDraftStatus('needs_review')
    and DOES call router.commit; CSV-mismatch holds with `needs_review_reason === 'fidelity_cross_check_unverified'`;
    budget-exhausted (CSV count < draft count for same strain) holds the overflow draft.
    (b) describe 'aggregateSeedingDraftsToSessionJson' with test title token `aggregate`
    covering single parent+species -> one group, multi-parent -> multiple groups, and
    child_block_names array populated. Assert output shape `{ type: 'seeding_session',
    event_date, groups: [{ parent: { value }, species: { value }, qty: { value }, child_block_names: { value: [] } }] }`.
    (c) describe 'buildCsvBudget / consumeCsvBudget' covering: builds Map<strainUpper,count>
    from CSV rows (uppercased, empty-strain skipped); consume returns false when budget hits 0.
    These tests MUST be RED now — the executor should confirm they fail referencing
    undefined exports, NOT pass vacuously.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest scripts/backfill-notebook.test.js -t "fidelity|aggregate|buildCsvBudget|no_csv|csv_verified|hold_reason" 2>&1 | grep -Eq "fidelity|aggregate" && echo "scaffold present"</automated>
  </verify>
  <acceptance_criteria>
    - The three describe blocks exist with the exact title tokens from 55B-VALIDATION.md
      (`no_csv`, `csv_verified`, `fidelity`, `hold_reason`, `no_csv_reason`, `aggregate`).
    - Running them FAILS (RED) because buildCsvBudget / consumeCsvBudget /
      aggregateSeedingDraftsToSessionJson are not yet exported and the csvRowsForPage /
      csvBudget params are not yet honored — failure is a missing-symbol / wrong-behavior
      assertion, not a syntax error.
    - Assertions reference the literal strings `fidelity_cross_check_no_csv` and
      `fidelity_cross_check_unverified` and `entry.ok === 'held'`.
  </acceptance_criteria>
  <done>RED fidelity/aggregation/budget scaffolds committed; they fail for the right reason.</done>
</task>

<task type="auto">
  <name>Task 3: Add RED image-upload test scaffolds to commit-seeding-session.test.js</name>
  <files>src/agents/alerter/test/farmos/commit-seeding-session.test.js</files>
  <read_first>
    - src/agents/alerter/test/farmos/commit-seeding-session.test.js (the file being modified — makeSessionMockClient lines 37-73)
    - src/agents/alerter/src/farmos/commits/commit-observation.js (canonical attachment analog — uploadAttachments best-effort pattern lines 26-42 + return shape lines 59-67)
    - src/agents/alerter/src/farmos/files.js (uploadAttachments contract: returns { fileIds, skipped, failed })
    - src/agents/alerter/src/farmos/commits/commit-seeding-session.js (read insertion region: upsertGroupAsset success line 138-148, children loop start line 152, return shape)
  </read_first>
  <action>
    In test/farmos/commit-seeding-session.test.js add a describe
    'commitSeedingSession -- image upload (D-03)' with three RED tests (token `image`):
    (1) when `ctx.sessionPagePaths` is non-empty, commitSeedingSession calls
    uploadAttachments then client.patch (assert order: upload UUIDs feed the PATCH);
    (2) the PATCH targets the session group asset id with relationships.file (reuse the
    `patch_files` assertion shape from Task 1); (3) image upload failure is non-fatal —
    mock uploadAttachments to return `{ fileIds: [], failed: ['/p.jpg'] }`, assert the
    session result is still `ok: true` and carries `attachments_failed` populated.
    Extend makeSessionMockClient with a `client.postBinary` jest.fn() (or mock the files
    module's uploadAttachments via jest.mock) returning a file UUID. These tests MUST be
    RED — commitSeedingSession does not yet import files.js nor accept ctx.sessionPagePaths.
    To locate the existing files-mock convention first run:
    `grep -rn "postBinary\|uploadAttachment" src/agents/alerter/test/ --include="*.js" -l`
    and mirror whichever mocking style that file uses.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/farmos/commit-seeding-session.test.js -t "image" 2>&1 | grep -Eq "image upload|D-03" && echo "scaffold present"</automated>
  </verify>
  <acceptance_criteria>
    - describe 'commitSeedingSession -- image upload (D-03)' exists with token `image`.
    - Tests are RED: commitSeedingSession does not yet call uploadAttachments /
      patchGroupAssetFiles, so the upload-then-patch and non-fatal-failure assertions fail.
    - The non-fatal test asserts `result.ok === true` AND `result.attachments_failed` length > 0.
  </acceptance_criteria>
  <done>RED image-upload scaffolds committed against the not-yet-wired commit-seeding-session path.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 4: A1 PATCH-associates-files dev smoke probe (:18080)</name>
  <action>Operator runs the dev :18080 smoke described in how-to-verify to confirm patchGroupAssetFiles associates a file--file UUID to an asset--group; records outcome in 55B-A1-SMOKE.md. Resolves assumption A1 before Plan 03 image-attach implementation.</action>
  <what-built>
    `patchGroupAssetFiles` (Task 1) plus an operator-runnable dev probe that PATCHes a
    real `asset--group` on dev farmOS :18080 to bind a real `file--file` UUID — the A1
    assumption verification. This is the hard gate before Plan 03 writes the image-attach
    implementation. No prod write (dev :18080 only; GA1 discipline).
  </what-built>
  <how-to-verify>
    Against dev farmOS :18080 (NEVER :8082), with FARMOS_URL/USERNAME/PASSWORD set:
    1. Create or pick an existing `asset--group` id (e.g. via `node -e` calling
       groupAssets.upsertGroupAsset, or an existing 'inoc *' group).
    2. Upload a small page JPEG via files.uploadAttachments to get a `file--file` UUID.
    3. Call `patchGroupAssetFiles(client, <groupId>, [<fileUuid>])`.
    4. GET `/api/asset/group/<groupId>?include=file` and confirm the file UUID appears in
       relationships.file.data.
    PASS = the file is associated (HTTP 200 + relationship present). FAIL = 4xx/5xx or the
    relationship is empty -> A1 falsified; record the fallback (two-step create -> upload ->
    associate, or set file in the POST at group-creation time) so Plan 03 adapts.
    Record the outcome (group id, file id, HTTP status, include result) in
    `.planning/phases/55B-*/55B-A1-SMOKE.md`.
  </how-to-verify>
  <resume-signal>Type "A1 verified" (PATCH associates files) or paste the failure + chosen fallback</resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| harness -> farmOS JSON:API | authenticated PATCH to /api/asset/group/<id>; assetId + fileIds are operator/harness-controlled, not external-user input |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-55B-01 | Tampering | patchGroupAssetFiles assetId path interpolation | accept | assetId is a farmOS UUID from upsertGroupAsset, not external input; no path traversal surface beyond existing groupAssets POST already trusts the same id |
| T-55B-02 | Information disclosure | A1 smoke probe writes a file to dev farmOS | accept | dev :18080 only (GA1 isolation); page JPEGs are local non-secret corpus data |
| T-55B-SC | Tampering | npm installs | mitigate | none — Phase 55B adds ZERO new packages (RESEARCH "No New Packages"); no install task exists |
</threat_model>

<verification>
- `npx jest test/farmos/commit-seeding-session.test.js -t "patch_files"` GREEN (Task 1).
- Fidelity/aggregation/image scaffolds RED for the right reason (Tasks 2, 3).
- A1 probe result recorded in 55B-A1-SMOKE.md; checkpoint resumed only on "A1 verified"
  or an explicit recorded fallback.
- Full suite still green except the new RED scaffolds:
  `cd src/agents/alerter && npx jest --passWithNoTests` (expect only the new RED describes failing).
</verification>

<success_criteria>
- patchGroupAssetFiles implemented + exported + payload test green.
- All Wave 0 RED scaffolds from 55B-VALIDATION.md present and failing for the right reason.
- A1 PATCH-associates-files assumption resolved (verified or fallback chosen) before any
  Plan 03 implementation begins.
</success_criteria>

<output>
Create `.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-01-SUMMARY.md` when done.
Record the A1 probe in `.planning/phases/55B-*/55B-A1-SMOKE.md`.
</output>
