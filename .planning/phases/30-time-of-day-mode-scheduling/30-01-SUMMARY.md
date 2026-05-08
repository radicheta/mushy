---
phase: 30-time-of-day-mode-scheduling
plan: 01
subsystem: controller
tags: [scheduler, rclpy, validator, tdd, fc_controller]

requires:
  - phase: 28
    provides: "set_mode service + current_mode topic + _engage_pid_bumplessly + on_set_parameters_callback"
provides:
  - "fc_core.scheduler pure helpers: parse_schedule, validate_window, compute_desired_mode"
  - "schedule_windows ROS param (JSON-encoded string, default '[]')"
  - "_validate_params arm rejecting malformed JSON / missing keys / bad HH:MM / unknown modes"
  - "_scheduler_tick — 30s timer + startup-alignment in-process mode swap with source='scheduler'"
  - "Gap WARN debounced via _last_scheduler_log — no per-tick spam"
affects: [phase-30-02, phase-30-03, alerter, mission-control]

tech-stack:
  added: []
  patterns:
    - "JSON-string-as-ROS-param — first usage in mushy; precedent for future schedule-of-X knobs"
    - "Plain-attribute clock seam (`self._now_hhmm = lambda: ...`) for testing — no monkeypatch / global mutation"

key-files:
  created:
    - src/chambers/fc-core/fc_core/scheduler.py
    - src/chambers/fc-core/fc_core/test/test_scheduler.py
  modified:
    - src/chambers/fc-core/fc_core/fc_controller.py
    - src/chambers/fc-core/fc_core/test/test_validate_params.py
    - src/chambers/fc-core/fc_core/test/test_controller_modes.py

key-decisions:
  - "scheduler module is pure-Python (no rclpy) so unit tests run with bare pytest and helpers are REPL-friendly. fc_controller imports it at module level."
  - "Wraparound modeled via `start_min > end_min` branch; full-day window expressible as {start='00:00', end='24:00'}. Half-open [start, end) per D-02."
  - "Validator delegates to scheduler.parse_schedule + scheduler.validate_window — single source of truth for schedule shape between bridge (Plan 30-02 mirrors rules) and controller."
  - "Manual override semantics implemented as 'scheduler unconditionally fires whenever desired != active' — the simpler reading of D-10/D-11. Within-window manual swaps are visible only between two ticks (≤30s); the boundary recovery property still holds and is tested."

patterns-established:
  - "JSON-encoded list params: declare as STRING with default '[]', validate via on_set_parameters_callback, evaluate in a periodic timer rather than synchronously"
  - "Gap-debounce via last-emitted (kind, mode) tuple — covers continuous gaps without flooding logs"

requirements-completed: [SCHED-01, SCHED-02, SCHED-03]

duration: ~30min
completed: 2026-05-08
---

# Plan 30-01: Controller-side scheduler — SUMMARY

**Pure scheduler helpers + schedule_windows param + 30s timer wired into fc_controller. Reboot-mid-window now self-aligns; manual overrides expire at the next boundary as designed (D-10/D-11).**

## Performance

- **Duration:** ~30 min
- **Tasks:** 2 (Task 1 RED→GREEN, Task 2 wire-up)
- **Files modified:** 5 (2 new, 3 edited)

## Accomplishments

- `fc_core/scheduler.py` (pure) — parse_schedule, validate_window, compute_desired_mode. **16/16 unit tests PASS** locally (Python 3.12, no rclpy required).
- `fc_controller.py` — `schedule_windows` declared, validator arm, `_scheduler_tick` method, startup-alignment call + 30s `create_timer`.
- D-19 transition log emitted at INFO with `[scheduler] transition: A → B at HH:MM (window=...)`. Gap WARN debounced via `_last_scheduler_log` tuple state.
- Source attribution on `current_mode` set to `'scheduler'` for schedule-initiated transitions; bridge JSON sibling published the same way (Phase 29-07 path).
- All schedule edits go through `_validate_params` — defense-in-depth against bridge bypass (T-30-01).

## Task Commits

1. **Task 1 — pure scheduler helpers + 16 unit tests:** `a7cd7da`
2. **Task 2 — fc_controller wire-up + validator/controller tests:** `f72fd20`

## Files Created/Modified

- `src/chambers/fc-core/fc_core/scheduler.py` *(new)* — public API: `parse_schedule`, `validate_window`, `compute_desired_mode`. No rclpy import (verified `grep -c '^import rclpy' = 0`).
- `src/chambers/fc-core/fc_core/test/test_scheduler.py` *(new)* — 16 tests (parse OK/reject + validate reject + compute_desired_mode normal/wraparound/boundary/gap/overlap/empty).
- `src/chambers/fc-core/fc_core/fc_controller.py` — `from fc_core import scheduler`, `schedule_windows` param decl, validator arm, `_default_now_hhmm` + `_now_hhmm` seam, `_scheduler_tick` method (~85 lines), startup tick + 30s create_timer at end of `__init__`.
- `src/chambers/fc-core/fc_core/test/test_validate_params.py` — `TestScheduleWindowsParam` class: 8 validator tests (default empty, valid set, malformed JSON / missing key / bad HH:MM / unknown mode / not array / empty always valid).
- `src/chambers/fc-core/fc_core/test/test_controller_modes.py` — 6 controller tests: startup alignment, already-aligned no-op, empty schedule no-op, gap + debounce, transition INFO log, manual-override boundary recovery.

## Verification

| Check | Status | Evidence |
|---|---|---|
| `pytest fc_core/test/test_scheduler.py -v` | **PASS** | 16/16 (Python 3.12, no rclpy) |
| Static: `grep -c '^import rclpy\|^from rclpy' scheduler.py` | **PASS (=0)** | pure-Python module |
| Static: `grep -c "schedule_windows" fc_controller.py` | **PASS (=3)** | declare + validator arm + _scheduler_tick body |
| Static: `grep -c "source='scheduler'" fc_controller.py` | **PASS (=5)** | transition publish path |
| Static: `python -c "import ast; ast.parse(...)"` | **PASS** | controller + both new test modules parse cleanly |
| `pytest fc_core/test/test_validate_params.py -v` | **deferred** | rclpy unavailable in this worktree; runs under colcon on fc1 (same posture as Phase 28/29 plans) |
| `pytest fc_core/test/test_controller_modes.py -v` | **deferred** | same |

## Self-Check: PASSED

- [x] All tasks executed
- [x] Each task committed individually
- [x] SUMMARY.md created
- [x] No modifications to STATE.md / ROADMAP.md (orchestrator owns those)

## Notes for Plan 30-02

- Bridge allowlist must mirror the JS-side validator rules in `entrySchedule()` against `DECLARED_MODES`. Validator messages (`'JSON'`, `'array'`, `'HH:MM'`, `'declared'`) are matched by 30-02's regex assertions — keep them stable.
- Bridge does **not** need to know about wraparound — that's a runtime evaluation concern. Bridge simply validates HH:MM regex on `start` and `end` independently.
- `runtime_overrides.yaml` round-trip preserves the JSON STRING verbatim under `fc_controller.ros__parameters.schedule_windows` (NOT pre-parsed into a YAML list) — Plan 30-02 Task 2 asserts this.
