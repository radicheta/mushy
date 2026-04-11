---
phase: 03-closed-loop-control
plan: "03"
subsystem: fc_core/controller
tags: [control-loop, sensor-staleness, safe-state, tdd]
dependency_graph:
  requires: [03-02]
  provides: [sensor-staleness-detection, safe-state-humidifier-off, _safe_state_active]
  affects: [fc_controller.py, test_controller.py]
tech_stack:
  added: []
  patterns: [staleness flag for log deduplication, ROS2 clock arithmetic, safe-state bypass of dwell guard]
key_files:
  created: []
  modified:
    - src/chambers/fc-core/fc_core/fc_controller.py
    - src/chambers/fc-core/fc_core/test/test_controller.py
decisions:
  - "Staleness check placed in control_loop (not in humidity_callback) — check happens on every control tick so recovery is immediate when fresh data arrives"
  - "_safe_state_active flag for log deduplication — WARN on entry, INFO on exit, not every tick at 1 Hz"
  - "Safe-state OFF bypasses dwell guard (calls set_humidifier directly) and updates _last_humidifier_toggle — prevents post-recovery rapid cycling (Pitfall 5)"
  - "Temperature and light control run regardless of humidity staleness — D-13 satisfied by else-branching only the humidity bang-bang section"
metrics:
  duration: 4min
  completed: "2026-04-04"
  tasks: 1
  files: 2
---

# Phase 03 Plan 03: Sensor Staleness Detection and Safe-State Summary

**One-liner:** Added staleness guard to `control_loop` tracking `_last_humidity_timestamp` via `get_clock().now()`, driving humidifier OFF with WARN log when data exceeds `sensor_stale_timeout` (10s default), auto-recovering with INFO log when fresh data arrives.

## What Was Built

1. **`humidity_callback` timestamp tracking** in `fc_controller.py`:
   - Adds `self._last_humidity_timestamp = self.get_clock().now()` after the median line (D-08)
   - Uses ROS2 clock (not `time.time()`) for sim-time compatibility

2. **Staleness guard in `control_loop`** in `fc_controller.py`:
   - After None-check (which calls `set_humidifier(False)` + return), before any actuator logic
   - `stale = elapsed_sec > sensor_stale_timeout` using `(now - _last_humidity_timestamp).nanoseconds / 1e9`
   - Guarded by `if self._last_humidity_timestamp is not None:` (Pitfall 2 from RESEARCH)
   - When stale: calls `set_humidifier(False)` directly (bypasses dwell guard), updates `_last_humidifier_toggle`, logs WARN once (`_safe_state_active` flag deduplicates)
   - When not stale: logs INFO on recovery transition, then runs normal humidity bang-bang via `_set_humidifier_with_dwell`
   - Temperature control (fan) and light control run regardless of staleness (D-13)

3. **Tests added** (`test_controller.py`):
   - `test_sensor_staleness`: humidity at t=0, control at t=15s → humidifier OFF, `_safe_state_active == True`
   - `test_safe_state_recovery`: enter stale, send fresh data at t=20s → `_safe_state_active == False`
   - `test_staleness_log_deduplication`: two stale ticks → `warn()` called exactly once
   - `test_safe_state_updates_dwell_toggle`: safe-state OFF at t=15s → `_last_humidifier_toggle == Time(ns=15e9)`
   - `test_fresh_data_not_stale`: data at t=0, control at t=5s (under 10s threshold) → `_safe_state_active == False`, humidifier ON

## Commits

| Hash    | Type | Description |
|---------|------|-------------|
| 6487f81 | test | Add failing tests for sensor staleness and safe-state (RED) |
| 46e115a | feat | Add sensor staleness detection and safe-state to control loop (GREEN) |

## Deviations from Plan

None - plan executed exactly as written. Tests followed the exact templates in the plan. Implementation matched the specified approach from CONTEXT.md and RESEARCH.md.

## Known Stubs

None — staleness detection is fully wired: timestamp set in callback, checked in control_loop, safe-state drives actual hardware state change via `set_humidifier(False)`.

## Self-Check: PASSED

- `src/chambers/fc-core/fc_core/fc_controller.py` — contains `self._last_humidity_timestamp = self.get_clock().now()`, `sensor_stale_timeout`, `Sensor data stale`, `Fresh sensor data received`, `self._safe_state_active`, `_last_humidifier_toggle = self.get_clock().now()` in staleness block
- `src/chambers/fc-core/fc_core/test/test_controller.py` — contains `test_sensor_staleness`, `test_safe_state_recovery`, `test_staleness_log_deduplication`, `test_safe_state_updates_dwell_toggle`, `test_fresh_data_not_stale`
- Commits 6487f81 and 46e115a exist in git log
- 17/19 tests pass (2 pre-existing failures: `test_temperature_control` and `test_light_control` — out of scope)
