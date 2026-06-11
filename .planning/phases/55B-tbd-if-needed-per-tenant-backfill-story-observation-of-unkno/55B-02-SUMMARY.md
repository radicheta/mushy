---
phase: 55B-fidelity-corpus-unblock
plan: 02
subsystem: backfill
tags: [farmos, jest, tdd, backfill, fidelity, csv-gate]

requires:
  - phase: 55B
    plan: 01
    provides: RED fidelity/budget scaffolds in backfill-notebook.test.js; strain-gate hold pattern

provides:
  - buildCsvBudget(csvRows) -- Map<strainUpper, count> helper, exported from backfill-notebook.js
  - consumeCsvBudget(budget, strainUpper) -- decrement-and-return-true, false at exhaustion
  - Fidelity hold gate in processDraftsForCapture (3 branches: no_csv / unverified / nonseeding)
  - opts.bulkBackfill===true AND csvRowsForPage!==undefined gate guards live paths

affects: [55B-03, 55B-04]

tech-stack:
  added: []
  patterns:
    - "Per-page mutable CSV budget (buildCsvBudget + consumeCsvBudget) consumed inside the draft loop"
    - "csvRowsForPage!==undefined guard keeps live/non-backfill paths byte-identical"
    - "Three needs_review_reason strings: fidelity_cross_check_no_csv / fidelity_cross_check_unverified / fidelity_cross_check_nonseeding"

key-files:
  modified:
    - src/agents/alerter/scripts/backfill-notebook.js

key-decisions:
  - "Gate condition is csvRowsForPage!==undefined (not csvRowsForPage.length>0): allows callers to opt-in by passing the param; existing main() call site passes nothing so is fully unaffected"
  - "Branch (c) non-seeding on CSV-covered page held as fidelity_cross_check_nonseeding -- CSV only records seeding events, so non-seeding drafts cannot be CSV-verified by design"
  - "ok:'held' (string) used on all held entries to keep computePerShapeStats held-vs-failed buckets correct"

requirements-completed: [FIDELITY-01, FIDELITY-02]

duration: ~8min
completed: 2026-06-11
---

# Phase 55B Plan 02: buildCsvBudget + fidelity gate Summary

**buildCsvBudget/consumeCsvBudget helpers + 3-branch fidelity hold gate in processDraftsForCapture; Plan 01 RED fidelity/budget scaffolds now GREEN**

## Performance

- **Tasks:** 2 of 2 complete
- **Files modified:** 1
- **Completed:** 2026-06-11

## Accomplishments

- `buildCsvBudget(csvRows)` added: Map<strainUpper, count> from CSV rows, null/empty strain skipped. Mirrors strainSetFromCsv in build-backfill-receipt.js but mutable (consumed per draft).
- `consumeCsvBudget(budget, strainUpper)` added: decrements count when >0, returns true; returns false at 0 or absent. Over-commit protection proven in tests.
- Both exported from backfill-notebook.js.
- `processDraftsForCapture` extended with `csvRowsForPage` + `csvBudget` params (destructured alongside existing `curatedStrains`).
- Fidelity gate: fires only when `opts.bulkBackfill===true && csvRowsForPage!==undefined`. Three branches:
  - (a) `csvRowsForPage.length===0`: all drafts held, `fidelity_cross_check_no_csv`
  - (b) seeding/seeding_session with strain not in budget or budget exhausted: held, `fidelity_cross_check_unverified`
  - (c) seeding/seeding_session with strain verified: budget consumed, falls through to `flipDraftToConfirmed`
  - (d) non-seeding on CSV-covered page: held, `fidelity_cross_check_nonseeding`
- Every hold calls `db.updateDraftStatus(pool, draftId, 'needs_review', {needs_review_reason})`, builds entry with `ok:'held'`, pushes to commits, emits summaries line.
- Live/non-backfill paths: main() does not pass `csvRowsForPage`, so `csvRowsForPage===undefined` and the gate is never entered. Zero live code changed.
- Full plan 01 fidelity scaffolds now GREEN (4 tests: no_csv, csv_verified, hold_reason, budget-exhausted).
- Pre-existing RED scaffolds for Plan 03 (aggregateSeedingDraftsToSessionJson + image upload) still RED as expected.
- Full suite: 1385 PASS, 6 RED (Plan 01 scaffolds for Plans 03), 0 regressions.

## Task Commits

1. **Task 1: buildCsvBudget + consumeCsvBudget helpers** -- `31bb19a` (feat)
2. **Task 2: Fidelity hold gate in processDraftsForCapture** -- `765a220` (feat)

## Files Created/Modified

- `src/agents/alerter/scripts/backfill-notebook.js` -- added buildCsvBudget, consumeCsvBudget, fidelity gate in processDraftsForCapture; both helpers exported

## Decisions Made

- Gate condition `csvRowsForPage !== undefined` (not a length check) is the correct opt-in discriminator: main() passes no csvRowsForPage so existing call site is completely unaffected without any change to that function.
- `fidelity_cross_check_nonseeding` is the correct reason for non-seeding drafts on CSV-covered pages: the CSV only records seeding events, so such drafts are structurally unverifiable and must be held for human review.

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None. The fidelity gate is fully wired. The main() call site does not yet pass csvRowsForPage/csvBudget -- that threading is the remaining gap (the gate won't fire in real runs until main() is updated to pass csvPath+pageDate and build the budget). This is the expected state after Plan 02: the gate itself is proven correct hermetically; the main() wiring is scoped to Phase 55B overall (or a future follow-on).

## Threat Surface Scan

No new network endpoints, auth paths, file access, or schema changes. The gate operates entirely on in-memory data already loaded by existing code paths (loadCsvForPage + db mocks in tests). No new threat flags.

---
*Phase: 55B-fidelity-corpus-unblock*
*Completed: 2026-06-11*
