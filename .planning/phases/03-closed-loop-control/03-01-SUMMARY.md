---
phase: 03-closed-loop-control
plan: "01"
subsystem: fc_core/controller
tags: [control-loop, safety, parameters, tdd]
dependency_graph:
  requires: [phase-02-safety-hardening]
  provides: [min_dwell_time param, sensor_stale_timeout param, safe-state None-check fix]
  affects: [fc_controller.py, fc_config.yaml]
tech_stack:
  added: []
  patterns: [ROS2 declare_parameters, bang-bang control, safe-state fallback]
key_files:
  created: []
  modified:
    - src/chambers/fc-core/fc_core/fc_controller.py
    - src/chambers/fc-core/config/fc_config.yaml
    - src/chambers/fc-core/fc_core/test/test_controller.py
decisions:
  - "D-12 fix: set_humidifier(False) on None sensor data instead of silent return — prevents humidifier freezing in last state on sensor failure"
  - "Instance vars _last_humidity_timestamp, _last_humidifier_toggle, _safe_state_active initialized for Plans 02 and 03 use"
metrics:
  duration: 7min
  completed: "2026-04-04"
  tasks: 1
  files: 3
---

# Phase 03 Plan 01: New Control Parameters, Instance Variables, and Safe-State None-Check Fix Summary

**One-liner:** Declared min_dwell_time (300s) and sensor_stale_timeout (10s) parameters, initialized timestamp-tracking instance vars, and fixed D-12 safety bug where None sensor data froze humidifier in last state.

## What Was Built

This plan lays the foundation for dwell-time (Plan 02) and staleness (Plan 03) features by:

1. **New ROS2 parameters** added to `declare_parameters` in `fc_controller.py`:
   - `min_dwell_time`: 300.0 seconds — minimum time between humidifier on/off toggles
   - `sensor_stale_timeout`: 10.0 seconds — sensor data older than this triggers safe state

2. **New instance variables** initialized in `__init__`:
   - `_last_humidity_timestamp`: will be set in `humidity_callback` when Plans 02/03 are implemented
   - `_last_humidifier_toggle`: will be set when humidifier changes state
   - `_safe_state_active`: deduplication flag for WARN logging

3. **D-12 safety bug fix** in `control_loop`: the original `if None: return` silently left the humidifier in its last state. Now calls `set_humidifier(False)` before returning, ensuring OFF on any sensor absence.

4. **Config entries** added to `fc_config.yaml` under "Safety guards" comment block.

## Tests Added

- `test_new_params_declared`: asserts min_dwell_time=300.0, sensor_stale_timeout=10.0 accessible via `get_parameter()`
- `test_none_humidity_safe_state`: humidifier was ON, humidity is None, control_loop drives it OFF
- `test_none_temp_safe_state`: humidifier was ON, temp is None, control_loop drives it OFF

All 7 working tests pass. 3 pre-existing failures (`test_temperature_control`, `test_humidity_control`, `test_light_control`) were already broken before this plan and are out of scope.

## Commits

| Hash    | Type | Description |
|---------|------|-------------|
| f990006 | test | Add failing tests for new params and None-check safe state (RED) |
| 2de0725 | feat | Add new control params, instance vars, and fix None-check safe state (GREEN) |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — `_last_humidity_timestamp` and `_last_humidifier_toggle` are initialized to `None` intentionally; they will be populated in Plans 02 and 03 respectively. This is documented in the plan and does not affect the plan's goal of fixing D-12 and declaring parameters.

## Self-Check: PASSED

- `src/chambers/fc-core/fc_core/fc_controller.py` — exists and contains `min_dwell_time`, `_last_humidity_timestamp`, `set_humidifier(False)` in None-check
- `src/chambers/fc-core/config/fc_config.yaml` — exists and contains `min_dwell_time: 300.0`
- `src/chambers/fc-core/fc_core/test/test_controller.py` — exists and contains `test_new_params_declared`, `test_none_humidity_safe_state`
- Commits f990006 and 2de0725 exist in git log
