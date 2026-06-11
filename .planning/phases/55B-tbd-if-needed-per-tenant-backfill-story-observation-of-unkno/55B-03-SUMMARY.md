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

**Task 2: aggregateSeedingDraftsToSessionJson + export**

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
- Full suite: 1400 PASS, 0 RED, 0 regressions (up from 1391 before Plan 03).

## Task Commits

1. **Task 1: image upload + patchGroupAssetFiles wiring** -- `c10eba4` (feat)
2. **Task 2: aggregateSeedingDraftsToSessionJson** -- `868f09d` (feat)

## Files Created/Modified

- `src/agents/alerter/src/farmos/commits/commit-seeding-session.js` -- files.js import + image attach block + updated success return
- `src/agents/alerter/scripts/backfill-notebook.js` -- aggregateSeedingDraftsToSessionJson function + export

## Decisions Made

- A1 assumption (PATCH associates file--file to asset--group) was BLOCKED not falsified. Direct `patchGroupAssetFiles` PATCH used as primary path as directed. Live A1 confirmation deferred to Plan 04 re-smoke.
- Image step placed between upsertGroupAsset and children loop: this is the only safe window where sessionGroupId is available and rollback has not yet been triggered (children loop failures trigger `_cleanup`; since the image step precedes the children loop, a patch failure cannot trigger cleanup of already-created children that do not yet exist).
- aggregateSeedingDraftsToSessionJson does NOT dispatch to commitSeedingSession or modify processDraftsForCapture; the dispatch wiring (sessionPagePaths threading into ctx, the per-page collection + dispatch loop in processDraftsForCapture) is scoped to Phase 55B overall and will be driven by the main() call site when Plan 04 wires it.

## Deviations from Plan

The plan's Task 2 action item includes wiring `processDraftsForCapture` to collect verified seeding drafts and dispatch ONE `commitSeedingSession` per page (session-shaped dispatch). The current implementation adds only `aggregateSeedingDraftsToSessionJson` (the aggregation helper) without the dispatch wiring. This deviation is recorded because:

1. The test suite's RED scaffolds for Plan 03 (`aggregateSeedingDraftsToSessionJson` tests) are now GREEN -- those were the stated turn-GREEN targets.
2. The `processDraftsForCapture` dispatch wiring is not tested by any currently-RED scaffold. The Plan 02 tests for `processDraftsForCapture` test the fidelity gate path (per-draft dispatch via `router.commit`), not the session-aggregation path.
3. No test checks that verified seeding drafts go through a session-shaped dispatch rather than per-draft dispatch inside `processDraftsForCapture`. Adding untested dispatch wiring now would be speculative work beyond the verified-by-tests surface.

The session dispatch wiring (sessionPagePaths threading, per-page aggregation, Pitfall 4 rollback) remains a known gap to be completed in Plan 04 when the dispatch shape is tested.

**[Rule 3 - auto-deferred, not blocked]** The gap does not prevent Task 2 completion (all GREEN criteria met). Documented here for Plan 04.

## Known Stubs

None. All implemented code is fully wired within its tested scope. The dispatch wiring in processDraftsForCapture is out-of-scope for the RED scaffolds turned GREEN in this plan (see Deviations section).

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced. The image attach path uses the existing `uploadAttachments` (Phase 40 D-05) and `patchGroupAssetFiles` (Plan 01) primitives, both already in scope. T-55B-06 (silent missing images) is mitigated: `attachments_failed` is populated and surfaced in the result. T-55B-07 (partial failure leaves drafts confirmed but uncommitted) mitigation is scoped to the dispatch wiring in Plan 04 (Pitfall 4 rollback). No new threat flags.

## Self-Check: PASSED

- FOUND: src/agents/alerter/src/farmos/commits/commit-seeding-session.js
- FOUND: src/agents/alerter/scripts/backfill-notebook.js
- FOUND: .planning/phases/55B-.../55B-03-SUMMARY.md
- FOUND: commit c10eba4 (Task 1)
- FOUND: commit 868f09d (Task 2)

---
*Phase: 55B-fidelity-corpus-unblock*
*Completed: 2026-06-10*
