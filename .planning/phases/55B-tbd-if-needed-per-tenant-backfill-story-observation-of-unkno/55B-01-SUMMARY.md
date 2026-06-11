---
phase: 55B-fidelity-corpus-unblock
plan: 01
subsystem: testing
tags: [farmos, jsonapi, jest, tdd, backfill, group-asset]

requires:
  - phase: 54.1
    provides: strain-gate hold pattern in processDraftsForCapture; makeDb/makeRouter test factories
  - phase: 52
    provides: commitSeedingSession + upsertGroupAsset session mechanism
provides:
  - patchGroupAssetFiles JSON:API PATCH helper (relationships.file edge) on asset--group
  - RED test scaffolds for the fidelity gate, session aggregation, csv budget, and image-attach paths
  - dev-locked A1 probe harness (scripts/a1-probe.js)
affects: [55B-02, 55B-03, 55B-04]

tech-stack:
  added: []
  patterns:
    - "JSON:API relationships PATCH (relationships.file.data of file--file refs) to associate files to an asset--group"
    - "RED-first scaffolds asserting missing exports / unhonored params before the impl waves"

key-files:
  created:
    - src/agents/alerter/scripts/a1-probe.js
  modified:
    - src/agents/alerter/src/farmos/groupAssets.js
    - src/agents/alerter/scripts/backfill-notebook.test.js
    - src/agents/alerter/test/farmos/commit-seeding-session.test.js

key-decisions:
  - "patchGroupAssetFiles early-returns {ok:true,skipped:true} on empty fileIds; canonical http_ error shape on failure"
  - "A1 dev smoke could not run: dev :18080 rejects the prod bot creds (HTTP 400 unrecognized). A1 recorded BLOCKED, not falsified."
  - "Direct-PATCH kept as the PRIMARY image-attach design for Plan 03 (assumed-A1); two-step fallback documented; LIVE A1 confirmation folded into Plan 04 re-smoke once dev creds work."

patterns-established:
  - "Pattern: dev-locked operator probe (hardcoded :18080, refuses :8082, self-loads creds, never prints them)"

requirements-completed: [FIDELITY-01, FIDELITY-02, SESSION-01, SESSION-02]

duration: ~12min
completed: 2026-06-10
---

# Phase 55B Plan 01: Validation floor + A1 probe Summary

**patchGroupAssetFiles JSON:API helper + RED scaffolds (fidelity/aggregate/budget/image) committed; A1 dev smoke BLOCKED on dev :18080 auth (creds), recorded for operator resolution**

## Performance

- **Tasks:** 3 of 4 complete (Task 4 = operator-run live checkpoint, deferred-BLOCKED)
- **Files modified:** 3 + 1 created
- **Completed:** 2026-06-10

## Accomplishments
- `patchGroupAssetFiles(client, assetId, fileIds)` added + exported in groupAssets.js; `patch_files` payload test GREEN (5 tests).
- RED fidelity / aggregation / csv-budget scaffolds added (9 RED, missing-symbol — correct signal).
- RED image-upload scaffolds added (3 RED, commitSeedingSession not yet wired — correct signal).
- Pre-existing suite: 1379 PASS, 0 regressions.
- Dev-locked A1 probe harness authored (`scripts/a1-probe.js`).

## Task Commits

1. **Task 1: patchGroupAssetFiles + patch_files test** - `202c300` (feat)
2. **Task 2: RED fidelity/aggregation/budget scaffolds** - `f66410e` (test)
3. **Task 3: RED image-upload scaffolds** - `2f45f3b` (test)
4. **Task 4: A1 dev smoke probe** - DEFERRED/BLOCKED (see below); harness `42dbbe4` + `d8d2e43`

**Tracking:** `7cd1fe9`

## Files Created/Modified
- `src/farmos/groupAssets.js` - added patchGroupAssetFiles (relationships.file PATCH) + export
- `scripts/backfill-notebook.test.js` - 3 RED describe blocks (fidelity / aggregate / buildCsvBudget)
- `test/farmos/commit-seeding-session.test.js` - patch_files (GREEN) + image-upload (RED) describes
- `scripts/a1-probe.js` - dev-locked operator probe (created)

## Decisions Made
- See key-decisions. The pivotal one: **A1 is BLOCKED, not verified and not falsified.** The dev
  :18080 instance is reachable (`GET /api` 200) but rejects the prod bot credentials
  (`POST /user/login` -> 400 "unrecognized username or password"). The PATCH was never exercised.
- To keep the phase moving, Plan 03 implements the direct `patchGroupAssetFiles` PATCH as the
  primary design (it is fully hermetically unit-tested) and the LIVE A1 confirmation is folded into
  Plan 04's 5-page re-smoke (which already writes to dev :18080). Fallback (file in group-creation
  POST) is documented in 55B-A1-SMOKE.md.

## Deviations from Plan
The Task 4 checkpoint could not be resolved as written (requires live dev :18080 auth that currently
fails). Recorded as BLOCKED in 55B-A1-SMOKE.md with three unblock options. This is an outstanding
operator item, surfaced to phase verification.

## Issues Encountered
- Dev :18080 rejects prod bot creds (HTTP 400). Root cause: the `mushy-bot` account does not exist
  on dev or uses a different password than prod. Blocks BOTH live operator gates in this phase
  (A1 probe + Plan 04 re-smoke). Requires operator-provided dev credentials.

## User Setup Required
**Outstanding:** working dev farmOS :18080 credentials (bot password, or a dev admin account).
With them, `node src/agents/alerter/scripts/a1-probe.js` runs the A1 smoke, and Plan 04's re-smoke
can execute. See `55B-A1-SMOKE.md`.

## Next Phase Readiness
- Plan 02 (fidelity gate) and Plan 03 (session + image-attach) can proceed: they only need the
  committed RED scaffolds + patchGroupAssetFiles, both present.
- **Blocker for phase sign-off:** A1 live verification + Plan 04 live re-smoke remain gated on dev
  :18080 credentials.

---
*Phase: 55B-fidelity-corpus-unblock*
*Completed (code): 2026-06-10*
