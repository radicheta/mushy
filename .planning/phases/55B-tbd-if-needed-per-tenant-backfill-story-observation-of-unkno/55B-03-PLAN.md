---
phase: 55B-fidelity-corpus-unblock
plan: 03
type: execute
wave: 2
depends_on: ["55B-01", "55B-02"]
files_modified:
  - src/agents/alerter/src/farmos/commits/commit-seeding-session.js
  - src/agents/alerter/scripts/backfill-notebook.js
autonomous: true
requirements: [SESSION-01, SESSION-02, SESSION-03]
must_haves:
  truths:
    - "CSV-verified backfill seeding drafts for a page aggregate into ONE seeding_session commit, grouping their blocks under the inoc-session group asset"
    - "The source notebook page image(s) attach to the session group asset (1..N pages), best-effort"
    - "An image upload/PATCH failure is surfaced but NEVER aborts the session commit"
    - "Held (needs_review) drafts produce no farmOS member, so they are visibly absent from the session view (F2 surface)"
  artifacts:
    - path: "src/agents/alerter/src/farmos/commits/commit-seeding-session.js"
      provides: "page-image upload + patchGroupAssetFiles wiring after upsertGroupAsset"
      contains: "uploadAttachments"
    - path: "src/agents/alerter/scripts/backfill-notebook.js"
      provides: "aggregateSeedingDraftsToSessionJson + session-shaped dispatch with sessionPagePaths in ctx"
      contains: "aggregateSeedingDraftsToSessionJson"
  key_links:
    - from: "commit-seeding-session uploadAttachments"
      to: "groupAssets.patchGroupAssetFiles(client, sessionGroupId, fileIds)"
      via: "file--file relationship PATCH"
      pattern: "patchGroupAssetFiles"
    - from: "aggregateSeedingDraftsToSessionJson"
      to: "commitSeedingSession (g.parent.value / g.species.value / g.child_block_names.value)"
      via: "synthesized seeding_session draft_json"
      pattern: "seeding_session"
---

<objective>
Route CSV-verified backfill seeding drafts through the Phase 52 session mechanism so
their blocks group under one inoc-session group asset, and attach the source notebook
page image(s) to that session asset (D-03). This builds the F2 reconcile surface: a
human opens the session in farmOS, sees the page image(s) beside the committed members,
and the held drafts are the visible gaps (D-02 / SESSION-03).

Purpose: At corpus scale ~half the entries hold; a Signal confirm blast is unusable.
The session view + attached page image IS the resolution UI. No farmOS UI code is
needed — held drafts are simply absent from the member list against the page image.
Output: aggregateSeedingDraftsToSessionJson + session-shaped dispatch (turns SESSION-01
scaffold green) and the image-upload wiring in commit-seeding-session.js (turns the
Plan 01 image scaffolds green). Image attach is best-effort, never aborts the commit.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-CONTEXT.md
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-RESEARCH.md
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-PATTERNS.md
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-A1-SMOKE.md

<interfaces>
Confirmed against source (2026-06-09):

commit-seeding-session.js (src/farmos/commits/commit-seeding-session.js):
- commitSeedingSession(client, draft, ctx) at line 116.
- Reads dj.event_date (line 119), dj.groups[] (line 120); rejects if either missing
  ('invalid_seeding_session').
- Per group g it consumes: g.species.value, g.parent.value, g.qty.value,
  g.child_block_names.value (lines 153-156). >>> The aggregation helper MUST emit
  exactly this nested {value:...} shape. <<<
- upsertGroupAsset success at line 138-148; sessionGroupId = groupRes.assetId (line 147);
  sessionGroupJustCreated = groupRes.outcome === 'created' (line 148). Children loop
  starts line 152. INSERT image upload between line 148 and 152.
- Current return shape has file_ids: [] (always empty today) — populate it + add attachments_failed.
- Imports today: assets, logs, groupAssets, activityLogs (no files import yet).

groupAssets.patchGroupAssetFiles(client, assetId, fileIds) — added in Plan 01.
files.uploadAttachments(client, paths, opts) returns { fileIds, skipped, failed }.

commit-observation.js (analog) — best-effort upload pattern lines 26-42; attachments_failed
surfaced via ctx.logger.warn without aborting; return shape lines 59-67.

backfill-notebook.js:
- Synthetic capture sets attachment_paths:[page] (~line 189) — page provenance carried.
- processDraftsForCapture (now with fidelity gate from Plan 02). The session aggregation
  collects CSV-VERIFIED seeding drafts (those that passed the gate) and dispatches ONE
  commitSeedingSession via the commit-router/ctx, threading sessionPagePaths into ctx.
- ctx is created in commit-router.commit(); for the session path, enrich it with
  sessionPagePaths: [pagePath, ...] before calling commitSeedingSession.
- aggregateSeedingDraftsToSessionJson emits { type:'seeding_session', event_date,
  groups:[{ parent:{value}, species:{value}, qty:{value}, child_block_names:{value:[]} }] }.

normalize.js (src/farmos/commits/normalize.js): D-11 keeps batch_name and
parent_batch_name distinct (no fold). The session consumer reads g.parent.value directly,
so aggregation maps dj.parent_batch_name || dj.parent -> group.parent.value. (OQ#2 resolved.)
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Image upload + patchGroupAssetFiles wiring in commit-seeding-session.js</name>
  <files>src/agents/alerter/src/farmos/commits/commit-seeding-session.js</files>
  <read_first>
    - src/agents/alerter/src/farmos/commits/commit-seeding-session.js (the file being modified — insertion region lines 138-152; current return shape)
    - src/agents/alerter/src/farmos/commits/commit-observation.js (analog — uploadAttachments best-effort lines 26-42 + return shape lines 59-67; the attachments_failed convention)
    - src/agents/alerter/src/farmos/files.js (uploadAttachments contract: { fileIds, skipped, failed })
    - src/agents/alerter/src/farmos/groupAssets.js (patchGroupAssetFiles added in Plan 01)
    - src/agents/alerter/test/farmos/commit-seeding-session.test.js (the RED image scaffolds from Plan 01 — the contract)
    - .planning/phases/55B-*/55B-A1-SMOKE.md (A1 outcome — if A1 was FALSIFIED, follow the recorded two-step fallback instead of PATCH)
  </read_first>
  <behavior>
    - ctx.sessionPagePaths non-empty -> uploadAttachments called with those paths, then patchGroupAssetFiles called with the returned fileIds against sessionGroupId.
    - Result carries file_ids = uploaded UUIDs and attachments_failed = upRes.failed.
    - uploadAttachments failure (failed non-empty / patch !ok) -> session result STILL ok:true; warn logged; attachments_failed populated; children loop + membership log unaffected.
    - ctx.sessionPagePaths empty/absent -> no upload, no patch, file_ids stays [], no behavior change (live non-backfill sessions unaffected).
  </behavior>
  <action>
    Require '../files' in commit-seeding-session.js. After upsertGroupAsset succeeds
    (line 148, sessionGroupId in hand) and BEFORE the children loop (line 152): read
    `const attachPaths = (ctx && ctx.sessionPagePaths) || []`. If non-empty, call
    `files.uploadAttachments(client, attachPaths, { logger: ctx && ctx.logger })`;
    collect `uploadedFileIds = upRes.fileIds || []` and `attachmentsFailed = upRes.failed || []`.
    Surface failures via ctx.logger.warn (mirror commit-observation lines 36-42) WITHOUT
    returning early. If uploadedFileIds non-empty, call
    `groupAssets.patchGroupAssetFiles(client, sessionGroupId, uploadedFileIds)`; if that
    returns !ok, add it to attachmentsFailed and warn — do NOT abort. (If 55B-A1-SMOKE.md
    recorded the PATCH as falsified, use the recorded fallback path instead.) Extend the
    success return to set `file_ids: uploadedFileIds` and add `attachments_failed: attachmentsFailed`.
    The image step must NEVER change the ok-status of an otherwise-successful session commit.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/farmos/commit-seeding-session.test.js -t "image|patch_files"</automated>
  </verify>
  <acceptance_criteria>
    - Plan 01 image scaffolds GREEN (-t "image").
    - Upload-then-patch order asserted; PATCH targets sessionGroupId with relationships.file.
    - Non-fatal: on upload/patch failure the session result is `ok: true` and
      `attachments_failed` is populated.
    - Empty sessionPagePaths => no upload/patch, file_ids stays []; existing session
      happy-path tests still green.
    - `cd src/agents/alerter && npx jest test/farmos/commit-seeding-session.test.js` fully green.
  </acceptance_criteria>
  <done>Page images attach to the session group asset best-effort; failures never abort the commit.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: aggregateSeedingDraftsToSessionJson + session-shaped backfill dispatch</name>
  <files>src/agents/alerter/scripts/backfill-notebook.js</files>
  <read_first>
    - src/agents/alerter/scripts/backfill-notebook.js (the file being modified — processDraftsForCapture with the Plan 02 fidelity gate; the verified-draft fall-through; main() call site line 748; synthetic attachment_paths ~line 189)
    - src/agents/alerter/src/farmos/commits/commit-seeding-session.js (the consumer — group field shape g.parent.value / g.species.value / g.qty.value / g.child_block_names.value lines 153-156; event_date + groups requirement lines 119-122)
    - src/agents/alerter/src/farmos/commits/normalize.js (D-11: parent_batch_name vs parent distinct — confirms the aggregation key source)
    - src/agents/alerter/scripts/backfill-notebook.test.js (the RED 'aggregateSeedingDraftsToSessionJson' scaffold from Plan 01)
    - .planning/phases/55B-*/55B-RESEARCH.md (Pattern 3 + "Session aggregation from verified seeding drafts" Code Example; Pitfall 4 rollback note)
  </read_first>
  <behavior>
    - aggregateSeedingDraftsToSessionJson([draftA(parent=P1,species=SHI), draftB(parent=P1,species=SHI)], '2025-02-01') -> one group, qty summed, both block_names in child_block_names.value.
    - Two distinct parents -> two groups.
    - Output shape exactly { type:'seeding_session', event_date:'2025-02-01', groups:[{ parent:{value}, species:{value}, qty:{value}, child_block_names:{value:[...]} }] }.
    - Session commit failure flips the constituent seeding draft IDs back to needs_review with reason 'session_commit_failed' (Pitfall 4).
  </behavior>
  <action>
    Add `aggregateSeedingDraftsToSessionJson(verifiedDrafts, pageDate)` to backfill-notebook.js
    (per RESEARCH Code Example): group verified seeding drafts by `(parent_batch_name||parent||'NO_PARENT')::species`
    where species = `(dj.species_code||dj.species||dj.strain||dj.fungi_type||'').toUpperCase()`;
    accumulate qty (dj.qty||1) and push dj.block_name into child_block_names. Emit the nested
    {value:...} group shape the session consumer reads. Export it.
    In processDraftsForCapture, when opts.bulkBackfill: instead of dispatching each verified
    seeding draft individually through commit-seeding, collect the CSV-VERIFIED seeding drafts
    for the page, synthesize ONE seeding_session draft via aggregateSeedingDraftsToSessionJson
    (event_date = pageDate), and dispatch it ONCE through the commit-router as a 'seeding_session'
    shape, enriching ctx with `sessionPagePaths` = the page path(s) for the session (from the
    synthetic capture's attachment_paths). Attribute the single session result back to all
    constituent draft IDs in the commits[] entries (keep each constituent draft row 'confirmed';
    the synthesized draft is in-memory only, never persisted). On session-commit failure, flip
    the constituent seeding draft IDs back to 'needs_review' with
    needs_review_reason:'session_commit_failed' (Pitfall 4) and record the failure in commits[].
    Non-seeding verified drafts (if any reach here) keep the existing per-draft commit path.
    Document the known cross-page-session limitation (a session spanning two pages yields two
    group assets) as a code comment + a note for the receipt.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest scripts/backfill-notebook.test.js -t "aggregate"</automated>
  </verify>
  <acceptance_criteria>
    - Plan 01 'aggregate' scaffold GREEN.
    - Output group shape matches the consumer: g.parent.value / g.species.value /
      g.qty.value / g.child_block_names.value all present.
    - Multi-parent input yields multiple groups; same parent+species merges with summed qty.
    - Session dispatch happens once per page (not once per draft); constituent draft IDs
      attributed in commits[].
    - Session-commit failure flips constituents to needs_review with 'session_commit_failed'.
    - `cd src/agents/alerter && npx jest --testPathPattern=backfill` green.
  </acceptance_criteria>
  <done>Backfill emits one session-shaped commit per page; blocks group under the inoc-session asset; failures roll constituents back to needs_review.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| harness -> farmOS (POST/PATCH) | session group create + file relationship PATCH + child asset/log creates; all authenticated, harness-controlled inputs |
| local page JPEG -> farmOS file | trusted local corpus image bytes uploaded via existing uploadAttachments |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-55B-06 | Tampering | session group created but page image silently missing (broken F2 surface) | mitigate | surface attachments_failed in the result + receipt (Pitfall 3); best-effort but never silent |
| T-55B-07 | Repudiation | partial session failure leaves constituent drafts 'confirmed' but uncommitted | mitigate | on failure flip constituents back to needs_review 'session_commit_failed' (Pitfall 4) |
| T-55B-08 | Spoofing | backfill session name collides with a live inoc session for same date | accept | _resolveSessionName #N suffix is by-design (Pitfall 5); receipt surfaces the name used |
| T-55B-SC | Tampering | npm installs | mitigate | zero new packages this phase; no install task |
</threat_model>

<verification>
- Plan 01 image + aggregate scaffolds GREEN.
- `cd src/agents/alerter && npx jest --testPathPattern="backfill|commit-seeding-session"` GREEN.
- Full suite green: `cd src/agents/alerter && npx jest --passWithNoTests` (all Wave 0
  scaffolds now green).
- Manual spot-read: image step sits between upsertGroupAsset (148) and children loop (152)
  and cannot flip ok:false on an otherwise-successful commit.
</verification>

<success_criteria>
- SESSION-01: backfill emits session-shaped commits; per-page blocks group under one inoc-session asset.
- SESSION-02: 1..N page images attach to the session group asset (best-effort).
- SESSION-03: held drafts produce no member -> visibly absent from the session view (no UI code needed).
</success_criteria>

<output>
Create `.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-03-SUMMARY.md` when done.
</output>
