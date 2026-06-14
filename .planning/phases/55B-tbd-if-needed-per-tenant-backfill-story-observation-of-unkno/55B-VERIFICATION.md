---
phase: 55B-fidelity-corpus-unblock
verified: 2026-06-14T21:05:00Z
status: human_needed
score: 12/13 must-haves verified
overrides_applied: 1
overrides:
  - must_have: "patchGroupAssetFiles exists and PATCHes asset--group file relationships (A1 PATCH-associates-files)"
    reason: "A1 PATCH route was falsified live against dev farmOS :18080 (no octet-stream route at /api/file/file; the `file` field rejects images). Replaced by the field-scoped binary route files.uploadFieldAttachments to /api/asset/group/{uuid}/image which creates+links in one call. A1-SMOKE.md records PASS for the replacement (A1'). Same intent (page image lands on the session group asset) achieved via a verified alternative. Documented in groupAssets.js lines 95-100 and memory project_farmos_image_upload_needs_field_scoped_route."
    accepted_by: "santi"
    accepted_at: "2026-06-14T20:03:32Z"
human_verification:
  - test: "F2 reconcile against live dev farmOS :18080 (SESSION-03 / D-03): open each re-smoke session group asset, confirm 1..N page image(s) attached AND held blocks are visibly ABSENT from the member list."
    expected: "Each per-page inoc session group asset shows its source notebook page image(s) on the `image` field; only CSV-verified blocks appear as members; held (needs_review) drafts produce no member so the human sees them as gaps against the page photo."
    why_human: "Requires opening live dev farmOS UI/API; the attach mechanism is proven standalone (A1-SMOKE PASS) and the upload+children code path is wired and unit-tested, but image-on-session-via-the-per-page-seeding_session-route is not yet confirmed on a real session asset. Cannot be verified by grep or hermetic tests."
---

# Phase 55B: Fidelity / corpus-unblock Verification Report

**Phase Goal:** Land the blockers before the parked full-corpus run is safe to execute. (1) Commit-time fidelity cross-check that HOLDS every entry not exact-verified against the per-page CSV reading (needs_review, never hard-reject). (2) F1+F2 reconcile surface: backfill per-block logs/assets group under the inoc-session group asset with source notebook page image(s) attached, so a human reconciles a session 1:1 against the physical notebook.
**Verified:** 2026-06-14T21:05:00Z
**Status:** human_needed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
| -- | ----- | ------ | -------- |
| 1  | A backfill seeding draft whose strain is not in the page's CSV reading is HELD, never committed (FIDELITY-01) | VERIFIED | backfill-notebook.js:511-536 branch (b) holds with `fidelity_cross_check_unverified`; test `fidelity hold_reason` + `budget-exhausted` PASS; live run 2/3 held KOY x4 / CAR x4 / LIM x5 / PIN x3 |
| 2  | A backfill draft on a page with no CSV reading at all is HELD (FIDELITY-01) | VERIFIED | backfill-notebook.js:491-510 branch (a) `fidelity_cross_check_no_csv`; test `no_csv` PASS; live IMG_3777/3779 held-all (SHI x8, CAS x4, POY x2) |
| 3  | Only exact-CSV-verified seeding drafts proceed to commit (FIDELITY-01) | VERIFIED | branch (c) consumes budget then falls through; test `csv_verified` confirms no needs_review write + commit dispatched |
| 4  | Held drafts use ok:'held' (string) so the receipt counts them held, not failed (FIDELITY-02) | VERIFIED | every hold entry sets `ok: 'held'` (lines 498, 524, 577); summary lines emitted under summariesFd guard |
| 5  | Three distinct needs_review_reason values disambiguate no-csv / unverified / nonseeding (FIDELITY-02) | VERIFIED | `fidelity_cross_check_no_csv` / `_unverified` / `_nonseeding` all present (grep lines 494/520/573); whitelisted updateDraftStatus path |
| 6  | The gate is actually wired into the live driver (not a hermetic-only no-op) | VERIFIED | call site backfill-notebook.js:1066-1072 threads csvRowsForPage/csvBudget/pageDate; this was run-1's root-cause failure, fixed in `96d1cd0`; live run 2/3 hard gate PASS |
| 7  | CSV-verified backfill seeding drafts aggregate into ONE seeding_session commit per page (SESSION-01) | VERIFIED | aggregateSeedingDraftsToSessionJson (line 289) + single dispatch (line 666-681); test `router.commit called ONCE` PASS |
| 8  | The source notebook page image(s) attach to the session group asset, best-effort (SESSION-02) | VERIFIED (override) | commit-seeding-session.js:157-172 uploadFieldAttachments to /api/asset/group/{id}/image; sessionPagePaths threaded line 681; 3 image tests PASS. Original PATCH design (patchGroupAssetFiles) overridden -- see override note |
| 9  | An image upload/PATCH failure is surfaced but NEVER aborts the session commit (SESSION-02) | VERIFIED | failure collected into attachmentsFailed + warn, no early return (lines 166-172); test `upload failure is non-fatal -- result.ok is true` PASS |
| 10 | Held (needs_review) drafts produce no farmOS member, so absent from session view (SESSION-03, code level) | VERIFIED | held drafts `continue` before commit (lines 510/536/...); only verified drafts become session constituents; asset_ids:[] on holds |
| 11 | A 5-page re-smoke exercises all three failure modes plus no-CSV (SMOKE-01) | VERIFIED | 55B-RE-SMOKE.md run 3: unverified (KOY/CAR/LIM/PIN) + no_csv (SHI/CAS/POY) both fired across IMG_3775-3779 |
| 12 | IMG_3776 POY entries HELD not committed as KOY -- mode-2 regression guard (SMOKE-01) | VERIFIED | 55B-RE-SMOKE.md run 3 (run_id re-smoke-55b-1781472903): img3776_poy_held=yes, KOY x4 held as fidelity_cross_check_unverified, duplicate_asset_count: 0 |
| 13 | Held blocks visibly absent from session members reconciled against the attached page image (SESSION-03, LIVE) | UNCERTAIN | code path correct + A1 attach mechanism proven standalone, but image-on-session via the per-page seeding_session route not confirmed on a live session asset -> human verification (D-03) |

**Score:** 12/13 truths verified (1 override applied; 1 routed to human verification)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `scripts/backfill-notebook.js` | buildCsvBudget/consumeCsvBudget, 3-branch fidelity gate, aggregateSeedingDraftsToSessionJson, session dispatch, gate-input wiring | VERIFIED | all symbols present + exported (lines 257/270/289, exports 1141-1143); 168/168 backfill+seeding tests green |
| `src/farmos/groupAssets.js` | file-association helper | VERIFIED (deviation) | patchGroupAssetFiles REMOVED (A1 falsified); replacement via files.uploadFieldAttachments; documented lines 95-100 |
| `src/farmos/files.js` | field-scoped upload | VERIFIED | uploadFieldAttachments exported (line 113); creates+links to image field in one call |
| `src/farmos/commits/commit-seeding-session.js` | page-image upload wiring after upsertGroupAsset | VERIFIED | lines 157-172 best-effort attach; file_ids + attachments_failed in return |
| `55B-RE-SMOKE-RUNBOOK.md` | GA1-isolated 5-page re-smoke procedure | VERIFIED | mentions IMG_3776 (11x), fidelity_cross_check (11x), :5433 (8x), zero em-dashes |
| `55B-RE-SMOKE.md` | attested run result | VERIFIED | run 3 hard gate PASS recorded |
| `55B-A1-SMOKE.md` | A1 probe outcome | VERIFIED | A1' field-scoped route PASS recorded |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| processDraftsForCapture fidelity gate | db.updateDraftStatus needs_review | needs_review_reason fidelity_cross_check_* | WIRED | lines 493/519/572 |
| main() driver | processDraftsForCapture | csvRowsForPage/csvBudget/pageDate args | WIRED | lines 1066-1072 (the fix for run-1 no-op) |
| commit-seeding-session | files.uploadFieldAttachments | image field on /api/asset/group/{id} | WIRED | lines 161-164; replaces planned patchGroupAssetFiles |
| aggregateSeedingDraftsToSessionJson | commitSeedingSession | synthesized seeding_session draft_json | WIRED | lines 666-681; constituent attribution + session_member flag line 709 |
| backfill session dispatch | sessionPagePaths in ctx | enrich ctx before commit | WIRED | line 681 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Fidelity gate 3 branches + budget | `jest backfill-notebook.test.js -t "fidelity\|no_csv\|csv_verified\|hold_reason"` | 10 passed | PASS |
| Session dispatch (once-per-page, multi-parent, rollback, page-paths) | `jest backfill-notebook.test.js -t "session dispatch wiring"` | 6 passed | PASS |
| Image attach (route, order, non-fatal failure) | `jest commit-seeding-session.test.js -t "image"` | 3 passed | PASS |
| Full backfill + seeding-session suites (regression) | `jest --testPathPattern="backfill\|commit-seeding-session"` | 168 passed / 168 | PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| Live re-smoke (operator-run, Plan 04 checkpoint) | runbook --limit=5 --resume-from=IMG_3775.jpg --bulk-backfill | run 3: 33 confirmed / 31 held, duplicate_asset_count 0, IMG_3776 POY held | PASS (attested 55B-RE-SMOKE.md) |

Note: the live re-smoke is an operator-run checkpoint executed in an isolated dev environment (:5433 throwaway DB + dev farmOS :18080) and cannot be re-run by the verifier without that environment. The attested result + the hermetic suites + the code-level wiring inspection corroborate the PASS.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| FIDELITY-01 | 55B-01, 55B-02 | CSV cross-check holds mismatched-strain + no-CSV drafts; verified strains commit | SATISFIED | truths 1-3, 6; live gate PASS |
| FIDELITY-02 | 55B-01, 55B-02 | Correct needs_review_reason per branch; held never reach farmOS; ok:'held' bucketing | SATISFIED | truths 4-5 |
| SESSION-01 | 55B-01, 55B-03 | Backfill emits session-shaped commits; per-page blocks group under one inoc-session asset | SATISFIED | truth 7 |
| SESSION-02 | 55B-01, 55B-03 | 1..N page images attach to session group asset (best-effort) | SATISFIED (deviation) | truths 8-9; override on attach mechanism |
| SESSION-03 | 55B-03, 55B-04 | Held drafts produce no member -> absent from session view (F2 surface) | PARTIAL | truth 10 (code) SATISFIED; truth 13 (live F2) NEEDS HUMAN |
| SMOKE-01 | 55B-04 | 5-page re-smoke green vs isolated dev; receipt shows held for IMG_3776 | SATISFIED | truths 11-12 |

Note on requirement IDs: REQUIREMENTS.md (dated 2026-05-25) predates Phase 55B and does NOT contain FIDELITY-*/SMOKE-01; SESSION-01/02/03 in REQUIREMENTS/ROADMAP belong to Phase 52. The 55B plans reuse the SESSION IDs with 55B-specific meaning (session-routing + page-image attach for backfill). Verified against the PLAN frontmatter must_haves and the ROADMAP 55b section goal, which is the controlling contract for this phase. No orphaned IDs.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | -- | No TBD/FIXME/XXX in any modified file | -- | clean |

### Advisory Findings (from 55B-REVIEW.md -- NOT gating this phase)

| Finding | Severity | Note |
| ------- | -------- | ---- |
| Strain gate (Phase 54.1) unwired in live driver (curatedStrains not passed at backfill-notebook.js:1050) -- CR-02/WR-06 | Advisory | Tracked in STATE.md; same call-site shape as the fidelity-gate fix; needs a curated-strain SOURCE decision before the parked full-corpus run. Does NOT gate 55B must_haves (strain gate is moot when terms pre-exist + createMissingFungiType:false per memory). |
| Receipt duplicate_asset_count attribution (now fixed `0526025`) | Resolved | session_member flag at line 709; re-smoke run 3 duplicate_asset_count: 0 |

These are advisory follow-ons for the separate Phase-55/GA2 promotion decision, already tracked. They are noted, not counted as gaps.

### Human Verification Required

#### 1. F2 reconcile on live dev farmOS (SESSION-03 / D-03)

**Test:** Open each re-smoke session group asset (inoc YYYY-MM-DD) in dev farmOS :18080. Confirm the source notebook page image(s) are attached on the `image` field, and that held (needs_review) blocks are ABSENT from the session member list.
**Expected:** Page image visible on each session asset; only CSV-verified blocks are members; held drafts appear as visible gaps when compared 1:1 against the physical notebook page.
**Why human:** Requires the live dev farmOS UI/API. The attach mechanism is proven standalone (A1-SMOKE PASS) and the upload+children+membership code path is wired and hermetically tested, but image-on-session via the per-page seeding_session route has not been confirmed on a real session asset. Operator (Santi) explicitly accepted closing the Plan 04 checkpoint on the hard-gate PASS and carrying this as a tracked human-needed follow-on.

### Gaps Summary

No blocking gaps. The phase's core deliverables -- the commit-time fidelity hold gate (closing the 2026-06-07 POY-as-KOY silent misattribution) and the session-routing + page-image-attach surface -- are implemented, wired into the live driver, hermetically tested (168/168 in scope), and validated by an attested live re-smoke (hard gate PASS, run 3). One observable truth (live F2 reconcile, SESSION-03) is routed to human verification per the operator-accepted disposition; it is not a code gap. The planned patchGroupAssetFiles PATCH approach was correctly abandoned after A1 falsification and replaced with the verified field-scoped upload route (override applied). Two advisory review findings (strain-gate unwired, receipt-dup already fixed) are tracked for the separate full-corpus promotion decision and do not gate this phase.

---

_Verified: 2026-06-14T21:05:00Z_
_Verifier: Claude (gsd-verifier)_
