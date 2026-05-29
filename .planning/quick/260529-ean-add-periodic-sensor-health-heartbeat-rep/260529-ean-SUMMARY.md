---
phase: quick-260529-ean
plan: 01
subsystem: fc_core/controller
tags: [sensor_health, heartbeat, alerter, watchdog, false-alarm-fix]
dependency_graph:
  requires: []
  provides: [sensor_health periodic republish, SENSOR_HEALTH_HEARTBEAT_SEC constant]
  affects: [alerter isSensorSilent watchdog, fc1/sensor_health topic]
tech_stack:
  added: []
  patterns: [ROS clock idiom (get_clock().now()), shared last-publish timestamp, heartbeat guard]
key_files:
  created: []
  modified:
    - src/chambers/fc-core/fc_core/fc_controller.py
    - src/chambers/fc-core/fc_core/test/test_controller.py
decisions:
  - Module constant SENSOR_HEALTH_HEARTBEAT_SEC=60.0 (not a fc_config param) -- quick task scope; 60s is well under the minimum 1-minute alerter watchdog floor
  - _last_sensor_health_publish stamped inside _publish_sensor_health (not at each call site) -- single source of truth; all publish paths (warmup, flip, heartbeat) reset the clock automatically
  - None guard on _last_sensor_health_publish provides defense-in-depth against heartbeat firing before first real publish
metrics:
  duration: ~10min
  completed: 2026-05-29
  tasks_completed: 2
  files_modified: 2
---

# Quick Task 260529-ean: Add Periodic sensor_health Heartbeat Republish

**One-liner:** 60s heartbeat republish of fc1/sensor_health via shared _last_sensor_health_publish timestamp, eliminating the false "Primary Humidity Sensor offline" alert for a healthy, stable SHT30.

## What Was Built

Added a periodic heartbeat republish of `fc1/sensor_health` from `fc_controller.control_loop()` so the alerter's `isSensorSilent` watchdog keeps receiving DiagnosticStatus messages even when a healthy SHT30 never triggers a freshness flip.

**Root cause addressed:** `sensor_health` was QUIET/TRANSIENT_LOCAL -- fc_controller only published on freshness flips and warmup transitions. A perfectly healthy SHT30 (the primary RH sensor) never triggers a flip, so `sht30LastSeenMs` went stale after `sensor_offline_min` minutes, causing the alerter to false-fire "Primary Humidity Sensor offline" on an hourly cooldown.

## Changes

### fc_controller.py

- **Module constant** `SENSOR_HEALTH_HEARTBEAT_SEC = 60.0` added after imports (before the `@dataclass` for `ModeView`), with a comment explaining the 60s value relative to the alerter's [1,60]-minute watchdog range.
- **`__init__`**: `self._last_sensor_health_publish = None` initialized after `_warmup_signal_published = False`. `None` = never published yet.
- **`_publish_sensor_health()`**: Added `self._last_sensor_health_publish = self.get_clock().now()` at the end of the method (after the existing `_last_scd41_fresh` stamp). Every publish path -- warmup WARN, grace-exit OK, flip, heartbeat -- resets the shared clock.
- **`control_loop()`**: Heartbeat check inserted after the flip-based republish block (lines ~1590-1592) and before the `if self.current_temp is None` block. Fires when `_last_sensor_health_publish is not None` AND elapsed >= `SENSOR_HEALTH_HEARTBEAT_SEC`. Uses the ROS clock idiom `(self.get_clock().now() - ts).nanoseconds / 1e9` matching all other freshness math in the file.

### test_controller.py

Three new tests added at end of file (TDD RED committed first, GREEN second):

- `test_sensor_health_heartbeat_republishes_when_stale`: grace bypassed, no flip, clock advanced past interval -- exactly 1 OK publish with `warming_up='false'`.
- `test_sensor_health_heartbeat_clock_reset_by_flip`: flip stamps `_last_sensor_health_publish`; tick immediately after (clock not advanced past interval) -- no extra publish.
- `test_sensor_health_heartbeat_not_fired_in_grace`: `_grace_active()` real implementation (true at t=5s), clock far past interval -- only 1 WARN publish.

`SENSOR_HEALTH_HEARTBEAT_SEC` imported from `fc_core.fc_controller` and converted to nanoseconds for time advancement.

## Verification

**Static:** Both files parse cleanly (`ast.parse` confirmed).

**Unit tests (rclpy required, fc1 only):** Tests use `ros_context` fixture which skips when rclpy unavailable (elder-plops has no ROS2 installation). All three heartbeat tests are syntactically valid and follow the existing `patch.object(node, 'get_clock', ...)` pattern.

Non-rclpy tests (scheduler, pid_kernel, etc.) continue to pass -- 16 + 10 + 16 = 42 passing.

**Deploy gate (human, gated):** Push to fc1/prod via `git push fc1/prod` + `scripts/pi-deploy` -> `colcon build` -> restart fc-core. Verify `ros2 topic echo fc1/sensor_health` shows a fresh DiagnosticStatus at least once per ~60s with `sht30_fresh: true`.

## Must-Haves Satisfied

| Truth | Met? |
|-------|------|
| Healthy SHT30 republishes at least once per heartbeat interval | Yes -- heartbeat check fires when elapsed >= 60s |
| Flip publish resets heartbeat clock | Yes -- _publish_sensor_health stamps _last_sensor_health_publish on every call |
| No heartbeat during startup grace window | Yes -- grace returns early + None guard defense-in-depth |
| Real-failure detection preserved | Yes -- flip-based publish block unchanged |
| _last_sht30_fresh / _last_scd41_fresh bookkeeping unchanged | Yes -- verified unmodified |

## Commits

| # | Hash | Message |
|---|------|---------|
| 1 (RED) | 5854ffe | test(260529-ean): add failing heartbeat tests for sensor_health periodic republish |
| 2 (GREEN) | 403caaa | feat(260529-ean): add periodic sensor_health heartbeat republish to control_loop |

## Deviations from Plan

None. Plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None. No new network endpoints, auth paths, or trust boundary changes. The change only adds more frequent publishing on an existing topic (`fc1/sensor_health`), which already carried a TRANSIENT_LOCAL QoS with depth=1. The alerter already subscribes to this topic; no new consumers or producers introduced.

## Self-Check: PASSED

- [x] `src/chambers/fc-core/fc_core/fc_controller.py` modified (verified via grep)
- [x] `src/chambers/fc-core/fc_core/test/test_controller.py` modified (verified via grep)
- [x] Commit 5854ffe exists (`git log --oneline | grep 5854ffe`)
- [x] Commit 403caaa exists (`git log --oneline | grep 403caaa`)
- [x] `SENSOR_HEALTH_HEARTBEAT_SEC = 60.0` present in fc_controller.py at line 28
- [x] `self._last_sensor_health_publish = None` present at line 371
- [x] `self._last_sensor_health_publish = self.get_clock().now()` present at line 1528
- [x] Heartbeat check present at lines 1600-1603
