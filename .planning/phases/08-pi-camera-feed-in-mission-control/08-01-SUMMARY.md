---
phase: 08-pi-camera-feed-in-mission-control
plan: "01"
subsystem: fc_core
tags: [camera, ros2, compressed-image, opencv, simulation-mode]
dependency_graph:
  requires: []
  provides: [fc_camera_node, fc1/camera/compressed]
  affects: [fc.launch.py, fc_config.yaml, setup.py]
tech_stack:
  added: [sensor_msgs/CompressedImage, cv2 (system apt package on Pi)]
  patterns: [lazy-import-cv2, simulation-mode-guard, try-except-non-blocking]
key_files:
  created:
    - src/chambers/fc-core/fc_core/fc_camera.py
    - src/chambers/fc-core/fc_core/test/test_camera.py
  modified:
    - src/chambers/fc-core/config/fc_config.yaml
    - src/chambers/fc-core/launch/fc.launch.py
    - src/chambers/fc-core/setup.py
decisions:
  - "Topic named fc1/camera/compressed (not fc/camera/compressed) to match all existing fc1/ topics"
  - "cv2 imported lazily inside __init__ and capture_and_publish to avoid ImportError on dev machines"
  - "camera_simulation_mode defaults to True in fc_config.yaml so existing Pi deployment is unaffected until webcam physically connected"
  - "_patch_param helper in tests patches FakeNode.declare_parameters to override single parameter defaults"
metrics:
  duration: "4 min"
  completed: "2026-04-08"
  tasks: 2
  files: 5
---

# Phase 08 Plan 01: Camera ROS2 Node Summary

ROS2 Python camera node using cv2.VideoCapture for USB webcam capture and sensor_msgs/CompressedImage publishing to fc1/camera/compressed, with simulation mode, graceful degradation, and 4 unit tests.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create fc_camera.py ROS2 node with unit tests (TDD) | fd5b7f7 | fc_camera.py, test_camera.py |
| 2 | Register camera node in config, launch file, and setup.py | 81e9265 | fc_config.yaml, fc.launch.py, setup.py |

## What Was Built

### fc_camera.py

`FcCamera(Node)` follows the exact fc_sensors.py pattern: declare 6 parameters, create publisher, create timer, timer callback wraps all work in try/except.

Key behaviors:
- `camera_simulation_mode=True` (runtime default from config): sets `self.cap = None`, timer callbacks are immediate no-ops. No cv2 import at all.
- `camera_simulation_mode=False`: lazy `import cv2`, creates `cv2.VideoCapture(device)`, checks `isOpened()` — if False, logs warning and continues (never crashes).
- `capture_and_publish()`: reads frame, encodes with `cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])`, wraps in `CompressedImage` with `format='jpeg'`, publishes.
- `destroy_node()`: releases VideoCapture before calling `super().destroy_node()`.
- Topic: `fc1/camera/compressed` (matches all existing `fc1/` topic prefix).

### fc_config.yaml additions

```yaml
camera_simulation_mode: true    # safe default — no USB webcam required
camera_device: 0                # /dev/video0
camera_width: 640
camera_height: 480
camera_fps: 1                   # 1 FPS for cellular bandwidth
camera_jpeg_quality: 65         # 60-70% per D-06
```

### fc.launch.py

Camera node added as 4th entry after fc_display, using same config_file pattern.

### setup.py

`fc_camera = fc_core.fc_camera:main` added to console_scripts.

### test_camera.py

4 unit tests that mock both rclpy and sensor_msgs at module level (no ROS2 daemon needed):

1. `test_camera_sim_mode` — sim mode sets cap=None, VideoCapture never called
2. `test_camera_unavailable` — isOpened()=False: cap is set, capture_and_publish returns without publish
3. `test_camera_publishes_compressed_image` — mocked cv2 with valid frame: publishes CompressedImage with format='jpeg' and correct bytes
4. `test_camera_parameters_declared` — all 6 parameters present in node._params

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Test design] Added `_patch_param` helper to override single parameter defaults in FakeNode**
- **Found during:** Task 1 GREEN phase — tests 1-3 all need to override `camera_simulation_mode` but the FakeNode stores whatever the node passes to `declare_parameters`
- **Fix:** Extracted `_patch_param(name, value)` context manager that wraps `FakeNode.declare_parameters` to override one parameter's default value, replacing per-test inline `patched_declare` closures in tests 2 and 3
- **Files modified:** src/chambers/fc-core/fc_core/test/test_camera.py

### Out-of-scope notes

- The plan verification command `python3 -m pytest` fails in this worktree because `.python-version` references `mushroom_farm` pyenv version which is not installed on elder-plops dev machine. Tests were run with `PYENV_VERSION=3.11.12 python3 -m pytest` (the pyenv version that has pytest). This is a pre-existing environment config issue, not caused by this plan.
- `test_controller.py` requires real rclpy and cannot run without ROS2 installed — pre-existing, out of scope.

## Threat Model Coverage

| Threat | Mitigation | Verified |
|--------|-----------|---------|
| T-08-01: DoS via camera failure | try/except in capture_and_publish wraps all cv2 calls | test_camera_unavailable passes |
| T-08-02: DoS via config change affecting live Pi | camera_simulation_mode defaults to true in fc_config.yaml | verified in config |
| T-08-03: Info disclosure via ROS topic | Accept — VPN-only access | no change needed |

## Known Stubs

None. The camera node is fully wired: publishes real CompressedImage messages when a USB webcam is connected and camera_simulation_mode is set to false in config.

## Self-Check: PASSED

- [x] `src/chambers/fc-core/fc_core/fc_camera.py` exists with `class FcCamera(Node)`
- [x] `src/chambers/fc-core/fc_core/test/test_camera.py` exists with 4 tests
- [x] `fc_config.yaml` contains `camera_simulation_mode: true`
- [x] `fc.launch.py` contains `executable='fc_camera'`
- [x] `setup.py` contains `fc_camera = fc_core.fc_camera:main`
- [x] 4 tests pass: `PYENV_VERSION=3.11.12 python3 -m pytest test_camera.py -x -q → 4 passed`
- [x] Commits exist: fd5b7f7 (feat), 81e9265 (chore)
