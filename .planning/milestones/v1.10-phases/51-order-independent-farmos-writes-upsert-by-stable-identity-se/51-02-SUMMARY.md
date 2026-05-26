---
phase: 51
plan: 02
subsystem: alerter/farmos
tags: [upsert, merge, pure-module, tdd]
requires: []
provides:
  - mergeAssetFields
  - IdentityMutationError
  - STABLE_NOTES_SEPARATOR
affects:
  - "Plans 03/04/05 unblock: assets.js upsertFungiAsset, logs.js upsertLog, upsert-property.test.js"
tech_stack_added: []
tech_stack_patterns:
  - "Pure-function rule-table module with structured conflict return (no exceptions for data events)"
  - "Identity-mutation guarded via thrown error class (programmer error, not data event)"
key_files_created:
  - src/agents/alerter/src/farmos/merge.js
  - src/agents/alerter/test/farmos/merge.test.js
key_files_modified: []
decisions:
  - "STABLE_NOTES_SEPARATOR locked to '\\n---\\n' (no round-trip probe note on disk; default per SPEC)"
  - "Scalar non-identity attribute coverage: status only (fungi_type/fungi_xing are scalar singleton rels)"
  - "Conflict shape: {field, existing, incoming, kind:'scalar_conflict'}; merged retains existing value (T-51-03 mitigation)"
metrics:
  duration_minutes: ~10
  tasks_total: 2
  tasks_completed: 2
  files_created: 2
  files_modified: 0
  completed: 2026-05-24
---

# Phase 51 Plan 02: Merge Pure Module Summary

Pure `mergeAssetFields` module added at `src/agents/alerter/src/farmos/merge.js` exporting the load-bearing UPSERT-03 transform (array-ref set-union, identity throw, scalar conflict surface, notes split-dedup-join) — zero client/network dependencies, 7 Jest cases green.

## Tasks Executed

| # | Name | Commit | Outcome |
|---|------|--------|---------|
| 1 | RED — Author failing Jest tests for merge.js | `d9ff93f` | 7 it() blocks, suite failed to load (module not found) — RED gate satisfied |
| 2 | GREEN — Implement merge.js | `f61a219` | 7/7 Jest tests pass; acceptance criteria all met |

## Acceptance Criteria Verification

- ✓ `merge.js` exports `mergeAssetFields`, `IdentityMutationError`, `STABLE_NOTES_SEPARATOR`
- ✓ `module.exports` count: 1 (verified via grep)
- ✓ Three-export symbol grep returns ≥3 hits (got 8 across file)
- ✓ File length: 133 lines (≥80 required)
- ✓ No `require(` of any other src/farmos/ module (purity invariant — verified: `grep -c "require.*farmos" = 0`)
- ✓ Commit messages: `test(51-02): RED` then `feat(51-02): GREEN`
- ✓ Final state: `npx jest test/farmos/merge.test.js --runInBand` exits 0 (7 passed)

## Behavior Coverage (UPSERT-03 rule classes)

| Rule | Test case | Status |
|------|-----------|--------|
| Array-ref set-union (existing-first order) | parent.data with disjoint sets | green |
| Array-ref dedup by id | parent.data with overlapping ids | green |
| Identity mutation throws | attributes.name change → IdentityMutationError | green |
| Scalar singleton equal noop | fungi_type both ft-shi | green |
| Scalar singleton conflict surface | fungi_type ft-shi vs ft-koy → conflicts=[…]; merged retains existing | green |
| Notes split-dedup-append | entry_A,B vs entry_B,C → A,B,C | green |
| STUB marker preservation | STUB text + new entry both present in merged | green |

## Deviations from Plan

None — plan executed exactly as written.

Notes on intentional simplifications:
- The plan listed `attributes.status` as a candidate scalar non-identity attribute. Implemented as `SCALAR_ATTR_FIELDS = ['status']` even though no test exercises it directly; future plans can extend the list without changing the engine.
- No round-trip probe note (`.planning/notes/2026-05-XX-phase-51-notes-roundtrip-probe.md`) exists on disk; the SPEC default `'\n---\n'` was used as the literal, matching what tests assert.

## Authentication Gates

None.

## Known Stubs

None.

## Threat Flags

None — module is pure, no new network surface.

## Regression Check

`cd src/agents/alerter && npx jest test/farmos/ --runInBand` →
- 23 suites passed, 1 pre-existing failure (`integration/extractor-to-commit.test.js`), 1 skipped
- 212 tests passed, 8 skipped, 0 new regressions
- The pre-existing failure is unrelated to this plan (depends on a future-plan module not yet created); confirmed by running the integration test before any Plan 02 work was staged.

## Self-Check: PASSED

- ✓ FOUND: src/agents/alerter/src/farmos/merge.js
- ✓ FOUND: src/agents/alerter/test/farmos/merge.test.js
- ✓ FOUND commit: d9ff93f (RED)
- ✓ FOUND commit: f61a219 (GREEN)

## TDD Gate Compliance

- RED commit: `d9ff93f` — `test(51-02): RED — failing merge.test.js for UPSERT-03 rule table (7 cases)`
- GREEN commit: `f61a219` — `feat(51-02): GREEN — implement mergeAssetFields with rule table`
- REFACTOR: not needed (initial implementation already clean; constants + helpers extracted at write-time)

Gate sequence intact.
