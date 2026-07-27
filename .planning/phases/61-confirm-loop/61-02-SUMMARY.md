---
phase: 61-confirm-loop
plan: "02"
subsystem: confirm-loop
tags: [fsm, pure-function, parity-test, enums, dataclasses]
dependency_graph:
  requires: [61-01-confirm_repo, phase-56-migrations]
  provides: [state_machine-pure-fsm, SC-1-parity-test]
  affects: [farm_agent.confirm.state_machine, tests.confirm.test_state_machine]
tech_stack:
  added: []
  patterns: [pure-function-fsm, str-enum, dataclass, parametrized-parity-test]
key_files:
  created:
    - src/farm-agent/farm_agent/confirm/state_machine.py
    - src/farm-agent/tests/confirm/test_state_machine.py
  modified: []
decisions:
  - "transition() is a PURE function -- no DB, no I/O, no logging; side_effects are strings the caller dispatches"
  - "dup-YES (confirmed+farmer_yes) checked BEFORE inactive guard -- load-bearing ordering, matches Node lines 53-65"
  - "edit cap default 3; cap = event.max_edit_turns if not None else 3 (mirrors Node maxEditTurns logic)"
  - "str-Enum for ConfirmStatus/ConfirmEvent so string comparisons work against DB status values"
  - "13 parametrized rows cover all 11 golden-table cases + 2 extra inactive variants; 5 extra dedicated tests"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-28"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 61 Plan 02: Pure Transition() FSM + 100% Parity Test Summary

Pure Python port of Node confirm/state-machine.js -- PURE transition() function with ConfirmStatus/ConfirmEvent enums, 100% parametrized table-parity test covering every golden-table row (SC-1).

## What Was Built

**state_machine.py** -- Port of `src/agents/alerter/src/confirm/state-machine.js`. Pure function with no I/O:

- `ConfirmStatus(str, Enum)`: AWAITING_FARMER, CONFIRMED, DISCARDED, EXPIRED, NEEDS_REVIEW (exact Node string values)
- `ConfirmEvent(str, Enum)`: FARMER_YES, FARMER_NO, FARMER_EDIT, NUDGE_DUE, EXPIRE_DUE, SUPERSEDED
- `Event(type, max_edit_turns)`, `State(status, edit_turn_count, nudge_sent_at)`, `TransitionResult(next_status, next_edit_turn_count, side_effects, reason)` dataclasses
- `is_terminal(status)`: True for {confirmed, discarded, expired, needs_review}
- `transition(state, event) -> TransitionResult`: PURE; mirrors Node ordering exactly:
  1. None/missing event type -> noop, reason='unknown_event'
  2. dup-YES: confirmed + farmer_yes -> confirmed ['send_confirm_idempotent_ack'] 'already_confirmed' (BEFORE inactive guard)
  3. inactive guard: status != awaiting_farmer -> noop 'inactive'
  4. awaiting_farmer dispatch: yes/no/edit(cap)/nudge(x2)/expire/superseded per golden table

**test_state_machine.py** -- 100% table-parity test (SC-1), 25 tests total:

- 13-row `@pytest.mark.parametrize` block covering every golden-table row: dup-YES, 3 inactive variants (discarded+farmer_no, expired+farmer_yes, needs_review+nudge_due), 8 awaiting_farmer rows (yes/no/edit_loop/edit_cap/nudge/already_nudged/expire/superseded), unknown_event
- Dedicated `test_dup_yes_fires_before_inactive_guard` asserting the ordering rule
- 3 edit-loop increment tests: count=0->1, count=1->2, cap unchanged at cap
- Custom max_edit_turns override tests (cap=1 triggers edit_cap_exceeded, cap=5 stays edit_loop)
- `test_confirmed_farmer_no_is_inactive` verifying non-dup-YES on confirmed falls to inactive guard
- No DB, no mocks, no asyncio

All 25 tests pass in 0.04s.

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None. state_machine.py makes no network calls, no DB access, no file I/O. T-61-06 (unrecognized event -> noop) and T-61-07 (transition on terminal draft -> inactive guard noop) are both covered by the parity test.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| src/farm-agent/farm_agent/confirm/state_machine.py | FOUND |
| src/farm-agent/tests/confirm/test_state_machine.py | FOUND |
| commit c23c3d9 (state_machine.py pure FSM) | FOUND |
| commit 87db5e5 (test_state_machine.py parity test) | FOUND |
| 25 tests pass | PASSED |
| no I/O imports in state_machine.py | PASSED |
