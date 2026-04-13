---
phase: 12-subscriber-aware-camera
plan: "01"
subsystem: camera
tags: [camera, bandwidth, subscriber-aware, tdd, rate-switching]
dependency_graph:
  requires: []
  provides: [subscriber-aware-camera-rate-switching]
  affects: [fc_camera, fc_config, bridge-camera-subscription]
tech_stack:
  added: []
  patterns: [subscriber-count-polling, grace-period-timer, idle-active-rate-switching]
key_files:
  created: []
  modified:
    - src/chambers/fc-core/fc_core/fc_camera.py
    - src/chambers/fc-core/fc_core/test/test_camera.py
    - src/chambers/fc-core/config/fc_config.yaml
decisions:
  - "Inline grace cancellation in capture_and_publish rather than in _ramp_up, so the active-with-grace state is handled without a full ramp-up cycle"
  - "camera_fps becomes idle rate (0.000278 = 1/hour); camera_active_fps is the new active rate (1.0)"
  - "Test _make_node patches camera_fps to 0.000278 explicitly — fc_camera.py default stays 1.0 for safe fallback"
metrics:
  duration: "~15 minutes"
  completed: "2026-04-13"
  tasks_completed: 2
  files_modified: 3
---

# Phase 12 Plan 01: Subscriber-Aware Camera Rate Switching Summary

Subscriber-aware camera rate switching using ROS2 get_subscription_count() with 5s grace period and 1-frame/hour idle rate.

## What Was Built

`fc_camera.py` now polls `get_subscription_count()` on every timer tick and switches between two operating modes:

- **Idle** (default): 1 frame/hour (0.000278 fps) — runs when no Mission Control viewers are connected
- **Active**: 1 fps — runs when the bridge has an active subscriber on `fc1/camera/compressed`

A 5-second grace period prevents thrashing when a viewer briefly disconnects (page reload, reconnect).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Write subscriber-aware tests (RED) | 7dab38f | test_camera.py |
| 2 | Implement rate switching + config (GREEN) | fbad3d0 | fc_camera.py, test_camera.py, fc_config.yaml |

## Key Changes

**fc_camera.py:**
- Two new declared parameters: `camera_active_fps` (1.0), `camera_subscriber_grace_sec` (5.0)
- `__init__`: stores `_idle_fps`, `_active_fps`, `_grace_sec`, `_is_active=False`, `_grace_timer=None`; timer stored as `self._cam_timer`
- `capture_and_publish`: subscriber-count check before frame capture — calls `_ramp_up`, inline grace cancel, or `_start_grace`
- New methods: `_ramp_up`, `_start_grace`, `_grace_expired`, `_ramp_down`
- `destroy_node`: cleans up `_grace_timer` before releasing VideoCapture

**fc_config.yaml:**
- `camera_fps`: `0.0167` → `0.000278` (1 frame/hour idle rate)
- Added `camera_active_fps: 1.0`
- Added `camera_subscriber_grace_sec: 5.0`

**test_camera.py:**
- `FakePublisher`: added `_sub_count=0` and `get_subscription_count()`
- `FakeTimer`: added `period`, `callback`, `cancel()` attributes
- `FakeNode`: added `destroy_timer()`; `create_timer()` now stores `period` and `callback` on FakeTimer
- New helper `_patch_params(dict)` for multi-param overrides
- New test class `TestSubscriberAwareCamera` (4 tests: idle start, ramp-up, stays active, params declared)
- New test class `TestSubscriberGracePeriod` (4 tests: grace starts, expires to idle, resub cancels, destroy cleanup)

## Test Results

```
12 passed in 0.03s
```

All 4 existing tests still pass. All 8 new tests pass (GREEN).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Grace cancellation missing from capture_and_publish subscriber-reconnect path**
- **Found during:** Task 2 GREEN verification
- **Issue:** Plan specified grace cancellation only inside `_ramp_up()`, but `_ramp_up` is only called when `not self._is_active`. When a subscriber reconnects during grace (node is already active), neither branch fired, leaving `_grace_timer` non-None.
- **Fix:** Added explicit inline branch `elif count > 0 and self._is_active and self._grace_timer is not None` in `capture_and_publish` to destroy the grace timer directly.
- **Files modified:** `fc_camera.py`, `test_camera.py` (`_make_node` also needed `camera_fps: 0.000278` patch so idle period assertion matched the expected ~3600s)
- **Commits:** fbad3d0

## Known Stubs

None — all data flows are wired. `get_subscription_count()` reads live ROS2 publisher state; timer switching is fully implemented.

## Threat Flags

None — threat model in plan covers all new surface (T-12-01 through T-12-03, all accepted).

## Self-Check: PASSED

| Item | Status |
|------|--------|
| src/chambers/fc-core/fc_core/fc_camera.py | FOUND |
| src/chambers/fc-core/fc_core/test/test_camera.py | FOUND |
| src/chambers/fc-core/config/fc_config.yaml | FOUND |
| .planning/phases/12-subscriber-aware-camera/12-01-SUMMARY.md | FOUND |
| commit 7dab38f (RED tests) | FOUND |
| commit fbad3d0 (GREEN implementation) | FOUND |
