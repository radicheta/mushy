---
phase: 43
plan: "05"
subsystem: farmos-write-path
tags: [integration-tests, schema-normalizer, regression-guard, chain-tests]
dependency_graph:
  requires: [43-01, 43-02, 43-03, 43-04]
  provides: [chain-integration-suite, extractor-to-commit-test]
  affects: [src/agents/alerter/test/farmos/integration/]
tech_stack:
  added: []
  patterns: [jest-mock-anthropic-sdk, three-boundary-assertion, mock-client-name-fallback]
key_files:
  created:
    - src/agents/alerter/test/farmos/integration/extractor-to-commit.test.js
  modified: []
decisions:
  - "Test 2 uses Option A (commit-failure path) per 43-FIXTURES.md recommendation: verbatim <UNKNOWN> transcript -> classified no_target_asset_for_activity. Stronger regression guard than happy-path because it directly captures the 2026-05-15 failure mode."
  - "notes assertions use .notes.value (not .notes) because logs.js:30 wraps notes as {value, format:'plain_text'} for farmOS JSON:API."
  - "FARMOS_INTEGRATION string appears 2x in comments (negative documentation: 'Do NOT add a gate') -- verification grep count is 2, not 0, but no process.env gate exists in actual test code."
  - "seeding qr_codes not asserted as array: seeding extractor-shape has no asset_ref field so normalize's asset_ref->qr_codes guard does not fire; qr_codes stays absent, commit-seeding uses block_name path."
metrics:
  duration: "~25 minutes"
  completed: "2026-05-16T20:02:43Z"
  tasks_completed: 1
  files_changed: 1
---

# Phase 43 Plan 05: Chain Integration Test Suite Summary

**One-liner:** 5-test extractor->normalize->commit chain suite with verbatim 2026-05-15 lion's-mane regression guard, mock LLM + mock farmOS, all log_types covered GREEN.

## What Was Built

Created `src/agents/alerter/test/farmos/integration/extractor-to-commit.test.js` -- a 5-test chain integration suite implementing the three-boundary assertion pattern (D-17) across all log_types.

**Test structure (D-17 applied to each test):**
1. (a) Post-extract boundary: extractor-shape markers present (type, asset_ref/block_name, event_timestamp, etc.)
2. (b) Post-normalize boundary: commit-shape markers present (qr_codes, timestamp as unix number, activity_subtype, source_qr_codes, bags, species_code)
3. (c) Post-commit boundary: commit_success or classified failure with correct reason; side-effects verified (asset created, log created, asset relationship IDs, notes content)

**Tests:**

| # | Log type | Transcript / input | Post-normalize key assertion | Commit result |
|---|----------|--------------------|------------------------------|---------------|
| 1 | seeding | synthetic inoc event | species_code: 'SHI', timestamp is number | ok:true, block created |
| 2 | activity (regression guard) | verbatim 2026-05-15 lion's-mane audio | qr_codes:[], activity_subtype:'relocate' | ok:false, reason:'no_target_asset_for_activity' |
| 3 | observation | pin emergence on 260513_SHI_2 | qr_codes:['260513_SHI_2'], notes contains 'state: pinning' | ok:true, asset relationship + notes verified |
| 4 | input | substrate mixed for 260514_KOY_3, recipe RB-2026-05 | notes starts with 'recipe_lot: RB-2026-05' | ok:true, log notes verified |
| 5 | harvest | 3 bags from 260512_DT_11, HBATCH-2026-05-15-DT-001 | source_qr_codes:['260512_DT_11'], bags:[{weight_grams:740}] | ok:true, source block in log relationships |

**Test 2 (2026-05-15 regression guard, D-16):**
Uses the verbatim transcript from 43-FIXTURES.md:
> "Two days ago, I put a lion's mane block into the fruiting chamber to fruiting Two days ago forgot to tell to tell you so yeah log it up Lion"

Mock LLM returns the live 2026-05-15 extractor output: `name:'relocate', asset_ref:'<UNKNOWN>', event_timestamp:'2026-05-13T00:00:00Z'`. After normalize: `qr_codes:[]`. Commit returns `no_target_asset_for_activity` -- a classifiable failure, not a crash. Before normalize.js (Plan 43-01), commit-activity would crash on wrong field names. This test would fail without normalize.js.

**Test 5 (Plan 43-02 name-fallback exercise):**
`260512_DT_11` seeded in mock-client by name only (no id_tag entry). `resolveQr` id_tag lookup returns `data:[]`, falls back to name lookup, finds `dt-block-src`. Verifies Plan 43-02's D-06 name-fallback works in the end-to-end chain.

## Results

- 5/5 tests GREEN
- Full `npm test`: 697/697 tests pass (8 skipped, pre-existing), 56/57 suites pass (1 skipped, pre-existing)
- No regressions in pre-existing suites

## Decisions Made

**D1: notes.value vs notes (Rule 1 fix inline):** farmOS logs module wraps notes as `{value, format:'plain_text'}` for JSON:API serialization (logs.js:30). Assertions use `logPayload.data.attributes.notes.value` -- discovered during test run.

**D2: seeding qr_codes boundary simplified:** Seeding extractor-shape has no `asset_ref` field (uses `block_name` instead), so normalize's `asset_ref->qr_codes` common transform guard does not fire. The normalize boundary assertion was simplified to remove the misleading `Array.isArray(qr_codes)` check; a comment explains this in the test.

**D3: FARMOS_INTEGRATION in comments:** The plan's verification criterion `grep -c "FARMOS_INTEGRATION" | grep -v '^# ' returns 0` matches the intent (no env gate in code). The file contains 2 comment lines documenting the SCHEMA-04 constraint ("no FARMOS_INTEGRATION gate"). No `process.env.FARMOS_INTEGRATION` check exists in test code.

**D4: expect() second argument not supported:** Jest 29.7.0 doesn't support `expect(val, customMessage)` at the `expect()` level. Boundary labels moved to comments adjacent to assertions.

## Optional Regression-Guard Demo (manual, per plan)

To verify Test 2 fails without normalize.js:
```
git stash -- src/agents/alerter/src/farmos/commits/normalize.js
cd src/agents/alerter && npm test -- test/farmos/integration/extractor-to-commit.test.js
# Test 2 fails: commit-activity crashes before reaching no_target_asset_for_activity
git stash pop
cd src/agents/alerter && npm test -- test/farmos/integration/extractor-to-commit.test.js
# Test 2 passes
```
This was not run as part of the automated suite (per plan: document, not automate).

## Commit

- `dd70837`: `test(43-05): add 5-test extractor->normalize->commit chain integration suite`

## Deviations from Plan

Three minor discoveries handled inline (Rule 1: bugs found during test run):

**1. [Rule 1 - Bug] notes is {value, format} object, not plain string**
- Found during: Task 1 (Test 3 and 4 failures on first run)
- Issue: logs.js:30 wraps notes as `{value, format:'plain_text'}` for farmOS JSON:API. Plan description said "assert notes contains X" without specifying the object shape.
- Fix: assertions use `logPayload.data.attributes.notes.value`
- Files modified: extractor-to-commit.test.js (inline fix)

**2. [Rule 2 - Boundary simplification] seeding qr_codes guard does not fire**
- Found during: Task 1 (Test 1 failure on first run)
- Issue: seeding extractor-shape has no `asset_ref` field (only `block_name`, `species`, `qty`). normalize's `asset_ref->qr_codes` common transform guard is `!Array.isArray(out.qr_codes) && typeof out.asset_ref === 'string'`. The second condition is false for seeding, so `qr_codes` stays absent.
- Fix: removed the misleading `expect(Array.isArray(qr_codes)).toBe(true)` assertion; added explanatory comment.
- Files modified: extractor-to-commit.test.js (inline fix)

**3. [Rule 1 - Jest compat] expect() second argument rejected**
- Found during: Task 1 (all 5 tests failed on first run)
- Issue: `expect(val, 'boundary label').toBe(true)` throws "Expect takes at most one argument" in Jest 29.7.0. The second arg is a custom message feature not available at this level.
- Fix: removed second argument, moved boundary labels to inline comments.
- Files modified: extractor-to-commit.test.js (inline fix)

## Known Stubs

None.

## Threat Flags

None -- test-only file, no new network endpoints or auth paths.

## Self-Check

### Files Created
- [x] `src/agents/alerter/test/farmos/integration/extractor-to-commit.test.js` -- FOUND (git show dd70837 --stat)

### Commits
- [x] `dd70837` -- FOUND

## Self-Check: PASSED
