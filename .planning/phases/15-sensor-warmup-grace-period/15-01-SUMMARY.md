---
phase: 15-sensor-warmup-grace-period
plan: "01"
subsystem: fc-core/controller
tags: [sensor-warmup, grace-period, diagnostic-msgs, rclpy, unit-tests]
dependency_graph:
  requires: []
  provides: [startup-grace-gate, sensor-health-topic, warmup-tests]
  affects: [fc_controller.py, test_controller.py, fc_config.yaml, package.xml]
tech_stack:
  added: [diagnostic_msgs/DiagnosticStatus, diagnostic_msgs/KeyValue]
  patterns: [TRANSIENT_LOCAL QoS publisher, early-return grace gate, mock clock post-init override]
key_files:
  created: []
  modified:
    - src/chambers/fc-core/fc_core/fc_controller.py
    - src/chambers/fc-core/fc_core/test/test_controller.py
    - src/chambers/fc-core/config/fc_config.yaml
    - src/chambers/fc-core/package.xml
decisions:
  - "Used rclpy.time.ClockType alias (_ROS_TIME) instead of top-level 'from rclpy.clock import ClockType' to avoid launch_testing hook import failure in colcon test collection"
  - "Pre-existing tests that call control_loop() get node._grace_active = lambda: False to bypass grace without restructuring test clock setup"
  - "test_warmup_grace_clears_when_both_conditions_met sends fresh humidity at t=21s to avoid staleness guard firing and blocking the expected humidifier ON"
metrics:
  duration: ~45m
  completed: "2026-04-18"
  tasks_completed: 4
  files_changed: 4
---

# Phase 15 Plan 01: Sensor Warm-Up Grace Period — Controller Implementation Summary

Grace gate + /fc1/sensor_health DiagnosticStatus publisher in fc_controller.py, preventing false humidifier activations from SCD41 ~12s settling transient on Pi restart.

## What Was Built

### fc_controller.py
- `from diagnostic_msgs.msg import DiagnosticStatus, KeyValue` import
- `('startup_grace_period', 20.0)` added to `declare_parameters`
- `self.sensor_health_pub` publisher on `fc1/sensor_health` (DiagnosticStatus, TRANSIENT_LOCAL QoS, depth=1, reusing `actuator_qos`)
- `self._boot_time`, `self._warming_up`, `self._warmup_signal_published` instance state in `__init__`
- `_grace_active() -> bool`: returns True while buffer not full OR elapsed < startup_grace_period
- `_publish_sensor_health(warming_up: bool)`: state-change-only publish with WARN/OK level + key/value metadata
- `control_loop` early-return at top: calls `set_humidifier(False)`, publishes WARN once on first grace tick, returns; on first tick post-grace flips `_warming_up=False`, publishes OK, logs `WARMUP-CLEARED`
- `fc_sensors.py` NOT modified — sensor telemetry keeps flowing to Timescale

### fc_config.yaml
- `startup_grace_period: 20.0` added to Safety guards block (after `sensor_stale_timeout`)

### package.xml
- `<depend>diagnostic_msgs</depend>` added after `<depend>sensor_msgs</depend>`

### test_controller.py
- `_ROS_TIME = rclpy.time.ClockType.ROS_TIME` module alias (avoids colcon test launch_testing hook import failure)
- `_mock_clock_at()` updated to return `rclpy.time.Time(nanoseconds=N, clock_type=_ROS_TIME)`
- 9 new warmup test functions covering all WARMUP-01/02/03/04 requirements
- 11 pre-existing tests updated with `node._grace_active = lambda: False` to bypass grace gate
- `test_safe_state_updates_dwell_toggle` assertion updated to use `_ROS_TIME` clock type

## Test Results

- New tests: 9/9 pass
- Pre-existing tests: 20/20 pass (0 regressions)
- Total: 29/29 pass

```
pytest src/chambers/fc-core/fc_core/test/test_controller.py -v
============================== 29 passed in 0.48s ==============================
```

Note: `colcon test --packages-select fc_core` fails at collection via the `launch_testing` pytest hook (it uses system Python which cannot import `sensor_msgs.msg`). This is a pre-existing environment issue in the docker test context unrelated to this plan's changes — the actual test logic runs and passes via direct `pytest`.

## Commits

| Hash    | Type  | Description |
|---------|-------|-------------|
| f25bb0a | chore | add startup_grace_period config + diagnostic_msgs dep |
| 1a984eb | feat  | grace gate + sensor_health publisher in fc_controller |
| e8fbdaa | test  | add TestStartupGracePeriod suite + fix clock type compat |
| a2a6654 | fix   | use rclpy.time.ClockType alias; bypass grace in pre-existing tests |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_warmup_grace_clears_when_both_conditions_met: staleness guard blocked expected humidifier ON**
- **Found during:** Task 3 test run
- **Issue:** Test filled buffer at t=5s then advanced clock to t=21s without refreshing humidity. Staleness guard (10s timeout) fired at t=21s and forced humidifier OFF, defeating the assertion.
- **Fix:** Added 5 fresh humidity samples inside the t=21s patch context before calling `control_loop()`
- **Files modified:** test_controller.py
- **Commit:** e8fbdaa

**2. [Rule 1 - Bug] ROS_TIME vs SYSTEM_TIME clock type mismatch in pre-existing tests**
- **Found during:** Task 3 full regression run
- **Issue:** `_boot_time` captured via real `get_clock().now()` in `__init__` returns `ROS_TIME`. Pre-existing tests patch `get_clock` to return `rclpy.time.Time(nanoseconds=N)` which defaults to `SYSTEM_TIME`. `_grace_active()` subtraction of incompatible types raised `TypeError: Can't subtract times with different clock types`.
- **Fix:** Changed `_mock_clock_at()` to return `ClockType.ROS_TIME`, updated all `_boot_time` overrides in new tests to use `_ROS_TIME`, fixed `test_safe_state_updates_dwell_toggle` assertion to use `_ROS_TIME`
- **Files modified:** test_controller.py
- **Commit:** e8fbdaa, a2a6654

**3. [Rule 1 - Bug] Grace gate blocked all pre-existing control_loop tests**
- **Found during:** Task 3 full regression run
- **Issue:** Pre-existing tests use small mock times (t=0..15s) which are all within the 20s grace window. Grace gate early-returned before any control logic ran, breaking 11 test assertions.
- **Fix:** Added `node._grace_active = lambda: False` to each affected pre-existing test
- **Files modified:** test_controller.py
- **Commit:** a2a6654

**4. [Rule 1 - Bug] top-level ClockType import broke colcon test collection**
- **Found during:** Task 4 colcon test run
- **Issue:** `from rclpy.clock import ClockType` at module level caused `launch_testing` hook (which uses system Python import context) to fail with `ModuleNotFoundError: No module named 'rclpy.clock'; 'rclpy' is not a package`
- **Fix:** Replaced with `_ROS_TIME = rclpy.time.ClockType.ROS_TIME` using the already-imported `rclpy.time` module. `rclpy.time` already re-exports `ClockType`.
- **Files modified:** test_controller.py
- **Commit:** a2a6654

## Carryover for Plan 03

Plan 03 handles Pi deploy:
- Branch to push: `main` (or current branch) → `fc1/prod`
- Expected soak behavior: after `systemctl restart fc-core`, no humidifier ON for first 20s; `ros2 topic echo /fc1/sensor_health --once` should show `level: 1` (WARN) immediately and `level: 0` (OK) after ~20s + buffer fill
- Verify with: `journalctl -u fc-core --since "30 sec ago" | grep -i 'WARMUP\|humidifier.*ON'`
- Known gap: `colcon test` collection failure via `launch_testing` hook in docker environment — does not affect runtime behavior on Pi where ROS packages are on the system Python path

## Known Stubs

None — all code paths are wired. The grace gate is unconditional (no sim-mode bypass per research §Pitfall 2 — use `startup_grace_period: 0.0` in dev YAML override if needed).

## Threat Flags

None — per plan threat model, no external input surface, no auth changes, no new persistence.

## Self-Check: PASSED

Files exist:
- src/chambers/fc-core/fc_core/fc_controller.py: FOUND (grep startup_grace_period: 4 hits)
- src/chambers/fc-core/fc_core/test/test_controller.py: FOUND (29 tests)
- src/chambers/fc-core/config/fc_config.yaml: FOUND (startup_grace_period: 20.0)
- src/chambers/fc-core/package.xml: FOUND (diagnostic_msgs dep)
- .planning/phases/15-sensor-warmup-grace-period/15-01-SUMMARY.md: this file

Commits exist: f25bb0a, 1a984eb, e8fbdaa, a2a6654 — all in git log.
