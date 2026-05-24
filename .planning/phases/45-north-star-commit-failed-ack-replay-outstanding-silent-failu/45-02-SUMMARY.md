---
phase: 45
plan: 02
subsystem: alerter/farmos
tags: [renderer, ack, commit-outcome, snapshot-tests, style-locks]
requires: []
provides:
  - renderOutcomeAck(draftRow, {outcome, reason, farmosLink}) -> string
  - reasonMap (8-code -> farmer-vocab)
  - reasonFor(code) with generic_validation_error fallback
affects: []
tech_stack_added: []
tech_stack_patterns: [pure-function-renderer, jest-snapshot]
files_created:
  - src/agents/alerter/src/farmos/commit-outcome-preview.js
  - src/agents/alerter/test/farmos/commit-outcome-preview.test.js
  - src/agents/alerter/test/farmos/__snapshots__/commit-outcome-preview.test.js.snap
files_modified: []
decisions:
  - "log_type label for 'input' is 'input log' (other 4 labels match log_type verbatim)"
  - "No-target success uses 3 minor variants (observation/activity/input); seeding/harvest fall back to observation phrasing since they realistically always have a target"
  - "Numeric targets pass through fmtNum; string targets pass through (sanitization at end)"
  - "Greeting omitted entirely when sender_name absent/empty (no 'friend,' / no 'operator,' / no leading comma)"
metrics:
  duration: "~10 min"
  completed_date: "2026-05-23"
  tasks_completed: 2
  files_touched: 3
  tests_added: 24
  snapshots_pinned: 13
---

# Phase 45 Plan 02: commit-outcome-preview renderer Summary

Pure-function farmer-facing ack renderer for commit_success (T4) + commit_failed (T6) terminal states. 10 templates (5 log_types x 2 outcomes) + 3 farm-level no-target variants = 13 templates pinned under jest snapshot. 8-code reason -> farmer-vocab map with generic_validation_error fallback. Style locks (no em-dash, fmtNum, named address) enforced by tests, not just review.

## What shipped

- `src/agents/alerter/src/farmos/commit-outcome-preview.js` (130 LOC). Exports `renderOutcomeAck`, `reasonMap`, `reasonFor`. Imports `sanitizeFarmerText` from `extraction/preview-builder` and `fmtNum` from `message`. No I/O. Sanitization applied last on every branch.
- `src/agents/alerter/test/farmos/commit-outcome-preview.test.js` (24 tests). 13 snapshot tests + 2 em-dash/en-dash style-lock loops + 2 fmtNum behavior tests + 4 reasonMap fallback tests + 3 named-address tests.
- `__snapshots__/commit-outcome-preview.test.js.snap` (13 entries).

## Template shapes (sanitized output)

- Success with target: `"Hi {name}, saved {log_type label} for {target}. Open in farmOS: {link}"`
- Success no-target (3 variants): `"Hi {name}, saved that {observation|activity|input} as a general farm note since I couldn't match a specific block. Send EDIT to attach a block if you want."`
- Failed: `"Hi {name}, couldn't save {log_type label}: {reason phrase}. Send EDIT to fix or NO to drop."`

## reasonMap (8 codes)

| Code | Farmer vocab |
|---|---|
| observation_requires_target | couldn't match a block |
| no_target_asset_for_activity | no asset to attach this activity to |
| asset_not_found | couldn't find that asset |
| duplicate_log | already logged |
| farmos_unreachable | farm server down |
| schema_invalid | data format issue |
| taxonomy_term_missing | missing a taxonomy term |
| generic_validation_error | data validation failed |

Unknown codes fall back to `generic_validation_error` phrasing via `reasonFor(code)`. Bare error codes never leak to farmer (proven by test `unknown reason code in failed render uses fallback phrasing, never bare code`).

## Test results

```
Test Suites: 1 passed, 1 total
Tests:       24 passed, 24 total
Snapshots:   13 written, 13 total
```

## Deviations from Plan

None. Plan executed as written. One implementation note: per plan latitude, log_type label for `input` is `"input log"` (others match log_type verbatim) since "saved input for X" reads ambiguously; "saved input log for X" matches farmer vocabulary in existing seeding/harvest templates.

## Known Stubs

None. Module is import-ready for Plan 04 wiring.

## Self-Check: PASSED

- File `src/agents/alerter/src/farmos/commit-outcome-preview.js`: FOUND
- File `src/agents/alerter/test/farmos/commit-outcome-preview.test.js`: FOUND
- File `src/agents/alerter/test/farmos/__snapshots__/commit-outcome-preview.test.js.snap`: FOUND (13 entries)
- All 24 tests green
- No em-dash / en-dash in source or snapshots
- All 5 log_types appear in snapshot file (seeding, activity, input, observation, harvest)
- 5 distinct reason codes exercised in snapshots (schema_invalid, no_target_asset_for_activity, taxonomy_term_missing, observation_requires_target, duplicate_log)
- reasonMap exports all 8 keys
