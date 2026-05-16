---
phase: 43
plan: "01"
subsystem: alerter/farmos/commits
tags: [normalizer, schema, tdd, idempotency]
dependency_graph:
  requires: []
  provides: [normalize.js, normalize.test.js]
  affects: [commit-router.js (Plan 43-03 wire-in)]
tech_stack:
  added: []
  patterns: [pure-function normalizer, idempotency-by-guard]
key_files:
  created:
    - src/agents/alerter/src/farmos/commits/normalize.js
    - src/agents/alerter/test/farmos/normalize.test.js
  modified: []
decisions:
  - D-09 recipe_lot PREPEND: normalizer prepends "recipe_lot: <value>\n" before any existing notes, so commit-input.js ingredients serializer chains naturally after it
  - D-05 source_block_refs verbatim: no B5 regex filtering at normalizer layer
  - D-11 seeding lineage distinct: batch_name and parent_batch_name left separate
  - D-12 single-bag synth: qty_g -> bags only when qty_g present and bags absent
metrics:
  duration: "3 minutes"
  completed: "2026-05-16"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
---

# Phase 43 Plan 01: Schema Normalizer (normalize.js) Summary

Router-side extractor->commit shape normalizer with TDD; 26 unit tests covering all 5 log_types, SCHEMA-03 idempotency, and non-mutation guarantees.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Write normalize.test.js (RED) | b983116 | test/farmos/normalize.test.js |
| 2 | Implement normalize.js (GREEN) | 37d9eea | src/farmos/commits/normalize.js |

## What Was Built

`normalize.js` is a pure function `(draft) -> draft'` that translates extractor-shape `draft_json` to commit-shape per `log_type`, ready to be wired into `commit-router.js` in Plan 43-03 (one-line edit at dispatch site).

### Transforms implemented

**Common (all log_types):**
- `event_timestamp` ISO string -> `timestamp` unix seconds (Math.floor(Date.parse/1000))
- `asset_ref` string -> `qr_codes` single-element array; `<UNKNOWN>` sentinel -> empty array

**Per-log_type:**
- `activity`: `name` -> `activity_subtype`
- `harvest`: `source_block_refs` -> `source_qr_codes` (verbatim, D-05); `harvest_batch_id` -> `harvest_batch_name`; `qty_g` -> `bags: [{weight_grams: qty_g}]` single-bag synth (D-12)
- `seeding`: `species` -> `species_code` when absent; `batch_name` and `parent_batch_name` left distinct (D-11)
- `input`: `recipe_lot` PREPENDED to notes as `"recipe_lot: <value>\n"` before any existing content (D-09), so commit-input.js's ingredients serializer chains naturally after
- `observation`: `state` appended to notes as `"\nstate: <value>"`

**Idempotency (SCHEMA-03):** Every transform is guarded -- if the commit-shape marker is already present, the transform is skipped. All 5 log_type idempotency tests confirm byte-identical pass-through.

## Test Results

```
Test Suites: 1 passed, 1 total
Tests:       26 passed, 26 total
```

All farmos tests (17 suites, 135 tests) pass with no regressions. Pre-existing extraction suite failures (missing `zod` dependency, 11 suites) are unrelated to this plan.

## Deviations from Plan

### D-09 prepend direction (audit sketch vs CONTEXT.md decision)

The audit sketch (§3, line 438) showed recipe_lot APPENDED to notes:
```js
out.notes = (out.notes ? out.notes + '\n' : '') + 'recipe_lot: ' + out.recipe_lot;
```

CONTEXT.md D-09 locks the correct order as PREPEND:
```js
out.notes = 'recipe_lot: ' + out.recipe_lot + (out.notes ? '\n' + out.notes : '');
```

This is not a deviation -- the plan explicitly states to follow D-09 over the audit sketch. Implementation follows D-09.

No other deviations. Plan executed exactly as written.

## Known Stubs

None. normalize.js is complete and ready for wire-in.

## Self-Check: PASSED

- `src/agents/alerter/src/farmos/commits/normalize.js` -- FOUND
- `src/agents/alerter/test/farmos/normalize.test.js` -- FOUND
- Commit b983116 -- FOUND (test RED)
- Commit 37d9eea -- FOUND (impl GREEN)
- 26/26 tests passing
- module.exports count: 1
