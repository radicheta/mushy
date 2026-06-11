---
phase: 55B-fidelity-corpus-unblock
plan: 03
subsystem: backfill
tags: [farmos, jest, tdd, backfill, session, image-upload, patchGroupAssetFiles]

requires:
  - phase: 55B
    plan: 01
    provides: RED image + aggregate scaffolds; patchGroupAssetFiles in groupAssets.js
  - phase: 55B
    plan: 02
    provides: fidelity gate; CSV-verified seeding drafts that reach session aggregation

provides:
  - uploadAttachments + patchGroupAssetFiles wiring in commitSeedingSession (best-effort, D-03)
  - aggregateSeedingDraftsToSessionJson(verifiedDrafts, {event_date}) exported from backfill-notebook.js
  - ctx.sessionPagePaths non-empty => page images attached to session group asset after upsertGroupAsset
  - processDraftsForCapture session dispatch wiring: CSV-verified seeding drafts aggregate into ONE seeding_session per page; Pitfall 4 rollback on failure (SESSION-01)

affects: [55B-04]

tech-stack:
  added: []
  patterns:
    - "Best-effort image attach: uploadAttachments -> patchGroupAssetFiles between upsertGroupAsset and children loop; failures never abort session commit"
    - "aggregateSeedingDraftsToSessionJson groups by (parentValue::speciesUpper) key; emits {value:...} nested shape matching commitSeedingSession consumer"
    - "ctx.sessionPagePaths empty/absent => no-op (live non-backfill sessions fully unaffected)"

key-files:
  modified:
    - src/agents/alerter/src/farmos/commits/commit-seeding-session.js
    - src/agents/alerter/scripts/backfill-notebook.js

key-decisions:
  - "Direct patchGroupAssetFiles PATCH used as primary image-attach design (A1 BLOCKED not falsified; hermetic tests cover the path; live A1 confirmation deferred to Plan 04 re-smoke)"
  - "Image step inserted between upsertGroupAsset (line 148) and children loop: sessionGroupId is available, children loop is unaffected; the image step can never cause rollback since it runs before any child that could trigger _cleanup"
  - "aggregateSeedingDraftsToSessionJson takes second arg as {event_date} object (matches test fixture calls); parent extracted via parent_batch_name / parent.value / parent string chain (D-11 aware)"
  - "Known cross-page session limitation documented in code comment: a session spanning two pages yields two separate group assets; accepted for first corpus run"
  - "Session dispatch wiring: Branch (c) of fidelity gate stages verified seeding drafts into verifiedSeedingDrafts list; each draft is flipped to confirmed immediately so the row is in the right state; Pitfall 4 rollback reverts to needs_review only on session commit failure"
  - "pageDate passed as new param to processDraftsForCapture; caller (main) threads it from corpus page metadata; defaults to null for backward compat"

requirements-completed: [SESSION-01, SESSION-02, SESSION-03]

duration: ~12min
completed: 2026-06-10
---

# Phase 55B Plan 03: Image upload wiring + aggregateSeedingDraftsToSessionJson Summary

**Best-effort page-image attach to inoc-session group asset (D-03) wired in commitSeedingSession; aggregateSeedingDraftsToSessionJson added to backfill-notebook.js; all Plan 01 image + aggregate RED scaffolds now GREEN**

## Performance

- **Tasks:** 2 of 2 complete
- **Files modified:** 2
- **Completed:** 2026-06-10

## Accomplishments

**Task 1: Image upload + patchGroupAssetFiles wiring in commit-seeding-session.js**

- Added `const files = require('../files')` import.
- After `upsertGroupAsset` succeeds (sessionGroupId in hand), before the children loop: reads `ctx.sessionPagePaths || []`.
- If non-empty: calls `files.uploadAttachments(client, attachPaths, { logger })`, then `groupAssets.patchGroupAssetFiles(client, sessionGroupId, uploadedFileIds)`.
- Upload failure: warns via ctx.logger.warn, populates attachmentsFailed, continues (never aborts).
- PATCH failure: appended to attachmentsFailed with reason prefix `patch_files_failed:`, warns, continues.
- Success return extended: `file_ids: uploadedFileIds`, `attachments_failed: attachmentsFailed`.
- Empty sessionPagePaths: no upload, no patch, file_ids stays [] -- live non-backfill sessions fully unaffected.
- All 17 commit-seeding-session tests GREEN (3 new image tests + 14 pre-existing).

**Task 2: aggregateSeedingDraftsToSessionJson + session dispatch wiring**

- Added `aggregateSeedingDraftsToSessionJson(verifiedDrafts, { event_date })` to backfill-notebook.js.
- Groups by `(parentValue::speciesUpper)` key.
- Parent extracted: `dj.parent_batch_name || dj.parent.value || dj.parent (string) || 'NO_PARENT'`.
- Species extracted: `dj.species_code || dj.species.value || dj.species (string) || dj.strain || dj.fungi_type`.
- qty summed per group (default 1 per draft if not specified).
- child_block_names.value array populated from dj.block_name per draft.
- Emits `{ type: 'seeding_session', event_date, groups: [{ parent:{value}, species:{value}, qty:{value}, child_block_names:{value:[]} }] }`.
- Exported from module.exports.
- Cross-page limitation documented in code comment.
- All 3 Plan 01 aggregate scaffolds now GREEN.

**Task 2 continuation (dispatch wiring -- completed in this continuation):**

- Added `pageDate` param to `processDraftsForCapture`.
- Branch (c) of fidelity gate now stages CSV-verified seeding drafts into `verifiedSeedingDrafts` list instead of dispatching per-draft. Each constituent draft is flipped to confirmed immediately.
- After the per-draft loop: aggregate all staged seeding drafts via `aggregateSeedingDraftsToSessionJson`, dispatch ONE seeding_session via `router.commit` with `sessionPagePaths: [pagePath]` in ctx.
- Success: session result attributed back to all constituent draft IDs in commits[].
- Failure (Pitfall 4): all constituents flipped back to `needs_review` with `needs_review_reason:'session_commit_failed'`.
- Non-seeding drafts and non-bulkBackfill paths are unchanged.
- 6 new RED-then-GREEN tests added to backfill-notebook.test.js.
- Full suite: 173 tests PASS, 0 RED, 0 regressions (up from 167 before this continuation).

## Task Commits

1. **Task 1: image upload + patchGroupAssetFiles wiring** -- `c10eba4` (feat)
2. **Task 2: aggregateSeedingDraftsToSessionJson** -- `868f09d` (feat)
3. **Task 2 continuation: session dispatch wiring** -- `f2cd141` (feat)

## Files Created/Modified

- `src/agents/alerter/src/farmos/commits/commit-seeding-session.js` -- files.js import + image attach block + updated success return
- `src/agents/alerter/scripts/backfill-notebook.js` -- aggregateSeedingDraftsToSessionJson function + export + session dispatch wiring in processDraftsForCapture
- `src/agents/alerter/scripts/backfill-notebook.test.js` -- 6 new RED-then-GREEN session dispatch tests

## Decisions Made

- A1 assumption (PATCH associates file--file to asset--group) was BLOCKED not falsified. Direct `patchGroupAssetFiles` PATCH used as primary path as directed. Live A1 confirmation deferred to Plan 04 re-smoke.
- Image step placed between upsertGroupAsset and children loop: this is the only safe window where sessionGroupId is available and rollback has not yet been triggered (children loop failures trigger `_cleanup`; since the image step precedes the children loop, a patch failure cannot trigger cleanup of already-created children that do not yet exist).
- aggregateSeedingDraftsToSessionJson does NOT dispatch to commitSeedingSession or modify processDraftsForCapture; the dispatch wiring (sessionPagePaths threading into ctx, the per-page collection + dispatch loop in processDraftsForCapture) is scoped to Phase 55B overall and will be driven by the main() call site when Plan 04 wires it.

## Deviations from Plan

None. The original Task 2 deviation (dispatch wiring missing) was closed in the plan continuation. All plan requirements are now satisfied.

## Known Stubs

None. All implemented code is fully wired and tested. The session dispatch path is exercised by 6 hermetic tests covering success, multi-parent, Pitfall 4 rollback, non-seeding passthrough, and bulkBackfill=false passthrough.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced. The image attach path uses the existing `uploadAttachments` (Phase 40 D-05) and `patchGroupAssetFiles` (Plan 01) primitives, both already in scope. T-55B-06 (silent missing images) is mitigated: `attachments_failed` is populated and surfaced in the result. T-55B-07 (partial failure leaves drafts confirmed but uncommitted): now mitigated -- Pitfall 4 rollback flips constituents to needs_review on session commit failure. No new threat flags.

## Self-Check: PASSED

- FOUND: src/agents/alerter/src/farmos/commits/commit-seeding-session.js
- FOUND: src/agents/alerter/scripts/backfill-notebook.js
- FOUND: src/agents/alerter/scripts/backfill-notebook.test.js
- FOUND: .planning/phases/55B-.../55B-03-SUMMARY.md
- FOUND: commit c10eba4 (Task 1)
- FOUND: commit 868f09d (Task 2 helper)
- FOUND: commit f2cd141 (Task 2 dispatch wiring)

---
*Phase: 55B-fidelity-corpus-unblock*
*Completed: 2026-06-10*
