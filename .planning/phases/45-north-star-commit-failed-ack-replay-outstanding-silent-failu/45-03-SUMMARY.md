---
phase: 45-north-star-commit-failed-ack-replay-outstanding-silent-failu
plan: 03
subsystem: alerter/confirm
tags: [state-machine, edit-loop, commit_failed, option-x, north-star]
requires: []
provides:
  - "edit-handler accepts EDIT on commit_failed drafts (Option X transition)"
  - "test-locked: confirmed/committed/discarded still reject EDIT"
affects:
  - src/agents/alerter/src/confirm/edit-handler.js
  - src/agents/alerter/test/confirm/edit-handler.test.js
  - src/agents/alerter/test/confirm/fake-pool.js
tech-stack:
  added: []
  patterns:
    - "inline UPDATE for state-machine transition (no new confirm-db helper this plan)"
key-files:
  created: []
  modified:
    - src/agents/alerter/src/confirm/edit-handler.js
    - src/agents/alerter/test/confirm/edit-handler.test.js
    - src/agents/alerter/test/confirm/fake-pool.js
decisions:
  - "Option X locked in 45-CONTEXT.md: commit_failed -> EDIT -> awaiting_farmer mirrors the existing awaiting_farmer EDIT path."
  - "JS state guard added in edit-handler.js (defense in depth). Today the SQL WHERE clauses in bumpEditTurn / updateDraftAfterEdit are the actual enforcement; an explicit JS guard makes intent legible and short-circuits non-target states without a DB roundtrip."
  - "outcome_ack_sent_at intentionally NOT touched (per plan behavior block + 45-CONTEXT.md): the original commit's ack stands; Plan 04 ack-slot semantics govern the next attempt."
  - "Re-activation UPDATE is conditional (WHERE status='commit_failed'): if another tick already moved the draft, return state_changed without bumping edit_turn_count."
metrics:
  duration: ~25 minutes
  completed: 2026-05-23
  tests_added: 2
  tests_total_in_suite: 9 (was 7)
  confirm_suite_total: 131/131 green
---

# Phase 45 Plan 03: EDIT-from-commit_failed (Option X) Summary

State machine now permits `commit_failed -> EDIT -> awaiting_farmer`, making Plan 02's "Send EDIT to fix" affordance truthful before Plan 04 ships the failure ack to farmers.

## What changed

**`src/agents/alerter/src/confirm/edit-handler.js`** (~40 LOC added, no logic duplicated):
1. Added an explicit JS state guard at the top of `handleEdit`: accept only `awaiting_farmer` or `commit_failed`; reject all other states with `{ok:false, reason:'wrong_state'}`.
2. For `commit_failed` source-state: execute an inline conditional UPDATE that flips status to `awaiting_farmer` (WHERE `id=$1 AND status='commit_failed'`). On rowCount=0 (race with a concurrent transition), return `{ok:false, reason:'state_changed'}`. On rowCount=1, mutate `draftRow.status` in memory and fall through to the existing awaiting_farmer path (`bumpEditTurn` -> extractor -> `updateDraftAfterEdit` -> `send_preview_resend`).
3. `outcome_ack_sent_at` is NOT touched (column does not yet exist; Plan 01 owns the migration). The existing awaiting_farmer EDIT path also never touched it, so this matches the verified mirror requirement.

**`src/agents/alerter/test/confirm/edit-handler.test.js`** (+2 tests):
- "EDIT on commit_failed draft -> transition to awaiting_farmer, re-extract, send_preview_resend" — happy path. Seeds draft with `status='commit_failed'` and `terminal_reason='observation_requires_target'` (the Vikki Rambo 2026-05-15 incident shape). Asserts extractor called with `farmerCorrection`, status post-handler is `awaiting_farmer`, `edit_turn_count` bumped to 1, sideEffect=`send_preview_resend`.
- "EDIT on draft in confirmed/committed/discarded -> rejected, no transition" — loops the 3 non-target states. Asserts `ok:false`, extractor never invoked, status unchanged.

## Deviations from plan

### [Rule 3 - blocking-issue] Fake-pool taught the new UPDATE pattern

**Found during:** Task 1 implementation
**Issue:** The plan's `files_modified` frontmatter lists only `edit-handler.js` and its test, but the Option X transition requires a new SQL pattern (`UPDATE signal_draft SET status='awaiting_farmer' WHERE id=$1 AND status='commit_failed'`) that the in-memory `fake-pool.js` did not recognize. Without teaching the fake-pool this pattern the happy-path test would hit the default `rowCount=0` fallthrough and the implementation could not be tested.
**Fix:** Added one branch (~6 LOC) to `fake-pool.js` `query()` that matches the new UPDATE and flips `row.status` from `commit_failed` to `awaiting_farmer`. Conditional on actual current status to mirror prod SQL semantics. This is a test-utility change, not production code.
**Files modified:** `src/agents/alerter/test/confirm/fake-pool.js`
**Tracked as:** scope-edge of plan; called out in this Summary so the Phase verifier knows about it.

### [Rule 2 - critical-functionality] Added explicit JS state guard (not strictly in plan text)

**Found during:** Reading edit-handler.js
**Issue:** The plan task 1 says "locate the state guard (the if/switch that today permits only `awaiting_farmer`)" — but no such JS-level guard exists. Today, enforcement lives in the SQL WHERE clauses of `bumpEditTurn` and `updateDraftAfterEdit`. A JS guard would still be useful (avoids a DB roundtrip for non-target states; makes the allowed-state set legible at the call site).
**Fix:** Added the JS guard at the top of `handleEdit` with both `awaiting_farmer` and `commit_failed` allowed. Defense in depth — SQL enforcement still applies.
**Tracked as:** Intent of the plan honored; minor expansion of the diff beyond the literal "add commit_failed to allowed set" because the set itself had to be made explicit first.

## Scope NOT touched

- `src/agents/alerter/src/farmos/commit-db.js` — untouched, per acceptance criteria.
- `src/agents/alerter/src/confirm/confirm-db.js` — untouched. (`bumpEditTurn` and `updateDraftAfterEdit` SQL still WHERE on `status='awaiting_farmer'`. The new transition flips status BEFORE those helpers run, so no helper-signature changes were needed.)
- `outcome_ack_sent_at` column / Plan 01 migration — out of scope here.
- `receive-loop.js` `findAwaitingForSender` — only matches `awaiting_farmer` drafts. Plan 04 (or a follow-on) will need to extend lookup so that EDIT replies from a farmer can FIND a `commit_failed` draft. Today this path is dormant until that wiring lands. Out of scope for 45-03; called out for the Phase 45 dependency graph.

## Verification

- `cd src/agents/alerter && npm test -- test/confirm/edit-handler.test.js` -> 9/9 green.
- `cd src/agents/alerter && npm test -- test/confirm` -> 131/131 green (no regressions).
- `grep -c "commit_failed" src/agents/alerter/src/confirm/edit-handler.js` -> 8 (>=1).
- `grep -c "commit_failed" src/agents/alerter/test/confirm/edit-handler.test.js` -> 4 (>=2).
- All 3 rejected states (`confirmed`, `committed`, `discarded`) referenced in Test B.

## Follow-ons (next plans in Phase 45)

- Plan 04 (or wherever the failure ack ships) must extend `findAwaitingForSender` (or add `findActiveDraftForSender`) so EDIT replies to a `commit_failed` draft actually reach this handler in receive-loop. Without that, the affordance is wired in code but never invoked at runtime.
- Plan 01's `outcome_ack_sent_at` migration is fully independent of this plan and can ship in any order.

## Self-Check: PASSED

- `src/agents/alerter/src/confirm/edit-handler.js`: FOUND, contains `commit_failed`.
- `src/agents/alerter/test/confirm/edit-handler.test.js`: FOUND, contains 2 new tests.
- `src/agents/alerter/test/confirm/fake-pool.js`: FOUND, contains new UPDATE branch.
- Test suite: 9/9 green; broader confirm suite 131/131 green.
