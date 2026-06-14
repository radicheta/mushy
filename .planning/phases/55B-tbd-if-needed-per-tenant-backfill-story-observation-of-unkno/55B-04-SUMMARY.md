---
phase: 55B-fidelity-corpus-unblock
plan: 04
subsystem: testing
tags: [backfill, re-smoke, fidelity-gate, ga1-isolation, runbook, live-fire, farmos]

requires:
  - phase: 55B
    plan: 02
    provides: commit-time CSV fidelity hold gate (fidelity_cross_check_* reasons)
  - phase: 55B
    plan: 03
    provides: session routing + page-image attach for CSV-verified seeding drafts

provides:
  - 55B-RE-SMOKE-RUNBOOK.md (GA1-isolated 5-page re-smoke procedure + per-page PASS criteria + operator held-draft SQL + F2 reconcile step + scope fence)
  - 55B-RE-SMOKE.md (attested live re-smoke result; hard gate PASS run 3)
  - Live ship-gate attestation: the 2026-06-07 POY-committed-as-KOY silent misattribution is now CAUGHT and HELD

affects: [55-full-corpus-run-receipt]

tech-stack:
  added: []
  patterns:
    - "GA1 isolation Option A: throwaway postgres :5433; prod alerter stays UP (watchdog polls :5432 only); throwaway DB torn down in aftercare"
    - "Live-fire is the real ship-gate: hermetic tests passed but the driver never supplied the gate inputs (feedback_unit_tests_dont_catch_wiring)"

key-files:
  created:
    - .planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-RE-SMOKE-RUNBOOK.md
    - .planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-RE-SMOKE.md

key-decisions:
  - "Checkpoint resolved as hard-gate PASS (IMG_3776 POY held, not committed as KOY). SESSION-03 F2 reconcile (image-on-session + held-absent-from-members) accepted as a tracked human-needed follow-on (D-03), not a blocker on the hard gate. Operator (Santi) accepted 2026-06-14."
  - "Re-smoke is a GATE before the parked full-corpus run; it does NOT trigger the full run (Phase 55 / GA2 owns promotion). Scope fence held."
  - "Harness selected contiguous IMG_3775-3779 (runbook mis-specified a non-contiguous set incl. IMG_3782); hard-gate page 3776, hold-all 3777, and mode-1 pages 3775/3778 all present, so the gate was exercised on the right pages. IMG_3779 substitutes for 3782 (both no-CSV hold-all)."

requirements-completed: [SMOKE-01, SESSION-03]

duration: live re-smoke across 3 runs 2026-06-14 (gate-wiring fixes between runs)
completed: 2026-06-14
---

# Phase 55B Plan 04: GA1-isolated 5-page re-smoke gate Summary

**Authored the GA1-isolated 5-page re-smoke runbook and executed it as the phase live ship-gate: the fidelity gate HELD IMG_3776 POY (not committed as KOY) on real paid extraction against an isolated dev DB, proving the 2026-06-07 silent-misattribution regression is caught before the parked full-corpus run.**

## Performance

- **Tasks:** 2 of 2 complete
- **Files created:** 2 (55B-RE-SMOKE-RUNBOOK.md, 55B-RE-SMOKE.md)
- **Completed:** 2026-06-14

## Accomplishments

**Task 1: 55B-RE-SMOKE-RUNBOOK.md authored (465 lines)**

- Reuses the GA1 isolation pre-flight from 55-FULL-CORPUS-RUNBOOK.md (Option A throwaway postgres :5433 + 4 pre-flight assertions).
- Documents the exact invocation (`--limit=5 --resume-from=IMG_3775.jpg --bulk-backfill --farmer santi`) against dev :18080 (NEVER :8082).
- Enumerates per-page PASS criteria (IMG_3776 POY held not KOY; IMG_3775 7 held / 17 hits; IMG_3777 all held no_csv; session group asset + page image per page).
- Includes the operator held-draft SQL query snippet and the F2 reconcile step.
- States the scope fence explicitly: GATE before the parked full run; the full corpus run remains Phase-55/GA2-owned.
- Automated verify green: file mentions IMG_3776, fidelity_cross_check, and the :5433 isolated DB.

**Task 2: Live 5-page GA1-isolated re-smoke executed (HARD GATE PASS)**

- Run 1 (gate NOT wired): all 64 drafts auto-confirmed, POY committed as KOY (reproduced the exact 2026-06-07 regression). Root cause: main() called processDraftsForCapture without csvRowsForPage/csvBudget/pageDate; fixed by wiring at backfill-notebook.js:1050 (`96d1cd0`).
- Run 2 (gate wired): IMG_3776 POY HELD as fidelity_cross_check_unverified, not committed as KOY. 31 held / 33 committed.
- Run 3 (receipt attribution fix `0526025`): duplicate_asset_count: 0 (PASS); hard gate intact (KOY x4 / CAR x4 / LIM x5 / PIN x3 held as fidelity_cross_check_unverified; SHI/CAS/POY held as no_csv).
- Result recorded in 55B-RE-SMOKE.md with per-page held/hit counts, held reasons, isolation notes, and outstanding items.

## Task Commits

The supporting code fixes that made the gate pass were committed during this session:

1. **Page-image attach via field-scoped farmOS route (A1 PASS)** -- `bbd9212` (fix)
2. **Wire fidelity-gate inputs into the backfill driver (hard gate PASS)** -- `96d1cd0` (fix)
3. **Credit session assets to one representative draft (receipt dup false-positive)** -- `0526025` (fix)
4. **STATE breadcrumb -- hard gate green, 2 follow-ons open** -- `344078b` (docs)

The runbook (55B-RE-SMOKE-RUNBOOK.md, `e3fe848`-era) and re-smoke result (55B-RE-SMOKE.md) are the Plan 04 artifacts.

## Files Created/Modified

- `55B-RE-SMOKE-RUNBOOK.md` -- GA1-isolated 5-page re-smoke procedure, per-page PASS criteria, operator SQL, F2 reconcile, scope fence
- `55B-RE-SMOKE.md` -- attested live re-smoke result (runs 1-3); hard gate PASS

## Decisions Made

- Checkpoint resolved as hard-gate PASS. The hard pass/fail criterion (IMG_3776 POY held, not committed as KOY) is GREEN. The SESSION-03 F2 reconcile (page image confirmed on the session group asset + held blocks absent from members) is accepted as a tracked human-needed follow-on (D-03), not a blocker on the hard gate. Santi accepted this disposition 2026-06-14.
- Scope fence held: this re-smoke gates but does NOT trigger the parked full-corpus run (Phase 55 / GA2 owns promotion, gated on Cycle-2 farmer sign-off).

## Deviations from Plan

- Harness selected contiguous IMG_3775-3779 rather than the runbook's non-contiguous set (which mis-specified IMG_3782). The hard-gate page (3776), hold-all page (3777), and mode-1 pages (3775/3778) were all present, so the gate was exercised on the right pages; IMG_3779 substitutes for IMG_3782 (both no-CSV hold-all). No impact on the gate validity.

## Issues Encountered

- Run 1 falsified the assumption that hermetic-green meant the gate worked end to end: the driver never supplied the gate inputs, so every draft auto-confirmed. Fixed by wiring csvRowsForPage/csvBudget/pageDate at the call site (`96d1cd0`). Reinforces feedback_unit_tests_dont_catch_wiring.
- Receipt duplicate_asset_count=22 false positive (session aggregation credited the whole session's asset_ids to every constituent draft). Fixed in `0526025` (credit one representative; rest session_member:true with empty asset lists). Re-smoke after fix: duplicate_asset_count: 0.

## Outstanding (tracked, not blocking the hard-gate PASS)

1. **SESSION-03 F2 reconcile / D-03 (human-needed):** open each session group asset in dev farmOS :18080, confirm 1..N page images attached and that held blocks are ABSENT from the member list. The A1 attach mechanism is proven standalone (55B-A1-SMOKE.md PASS), but the re-smoke routes via the per-page seeding_session and image-on-session is not yet confirmed live.
2. **Strain gate (Phase 54.1) also unwired in this driver** -- curatedStrains not passed at backfill-notebook.js:1050; needs a curated-strain SOURCE decision (live farmOS fungi_type terms vs the hardcoded 14/24 set). Not the 55B hard gate, same call-site gap.

## Next Phase Readiness

- Phase 55B hard gate satisfied. The parked full-corpus run is unblocked for the separate Phase-55/GA2 promotion decision (NOT triggered here; still gated on Cycle-2 farmer sign-off).

## Self-Check: PASSED

- FOUND: .planning/phases/55B-.../55B-RE-SMOKE-RUNBOOK.md (mentions IMG_3776, fidelity_cross_check, 5433)
- FOUND: .planning/phases/55B-.../55B-RE-SMOKE.md (hard gate PASS, run 3)
- FOUND: .planning/phases/55B-.../55B-04-SUMMARY.md
- FOUND: commits bbd9212, 96d1cd0, 0526025, 344078b

---
*Phase: 55B-fidelity-corpus-unblock*
*Completed: 2026-06-14*
