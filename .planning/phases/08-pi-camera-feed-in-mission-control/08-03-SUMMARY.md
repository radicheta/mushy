---
phase: 08-pi-camera-feed-in-mission-control
plan: "03"
subsystem: frontend
tags: [openmct, camera, mjpeg, plugin, javascript]
dependency_graph:
  requires: [08-02]
  provides: [CAM-05]
  affects: [src/mission-control/frontend/plugins/fruiting-chamber/plugin.js]
tech_stack:
  added: []
  patterns: [OpenMCT custom view provider, configurable plugin options]
key_files:
  modified:
    - src/mission-control/frontend/plugins/fruiting-chamber/plugin.js
decisions:
  - "cameraUrl is configurable via plugin options (not hardcoded) — index.html can pass production host when deployed (Pitfall 5 per research)"
  - "Camera object inserted via .concat([CAMERA_ID]) on root composition — preserves existing SENSORS ordering"
  - "Camera check placed before sensor find in object provider get() — explicit early return, no risk of null sensor lookup"
  - "onerror handler hides broken img and shows text message — graceful degradation when no camera connected"
metrics:
  duration: 2min
  completed_date: "2026-04-08"
  tasks_completed: 1
  tasks_total: 2
  files_modified: 1
---

# Phase 08 Plan 03: Camera View in Mission Control Summary

**One-liner:** OpenMCT plugin extended with fruiting-chamber.camera type, FC-1 Camera object in FC-1 tree, and custom view provider rendering configurable MJPEG img tag with graceful unavailable fallback.

## What Was Built

Modified `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` to add a live camera feed panel to the Mission Control UI:

- **`CAMERA_ID` constant** — `{ namespace: 'fruiting-chamber', key: 'fc.camera' }` declared after SENSORS array
- **`cameraUrl` option** — extracted from plugin options with `'http://localhost:8081/camera/mjpeg'` default; configurable for production deployment
- **`fruiting-chamber.camera` type** — registered with `icon-image` cssClass, `creatable: false`
- **Root composition** — updated via `.concat([CAMERA_ID])` so FC-1 Camera appears in the tree alongside sensors
- **Object provider** — resolves `identifier.key === 'fc.camera'` to a camera domain object before the sensor lookup block
- **`fruiting-chamber.camera-view` view provider** — `canView` gates on camera type; `show` injects an `<img src="cameraUrl">` on black background with `onerror` fallback; `destroy` clears container
- All existing SENSORS, telemetry provider, WebSocket logic unchanged

## Tasks

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Add camera type, object, and custom view provider to plugin.js | Complete | 6c70f62 |
| 2 | Verify camera view in Mission Control browser | Checkpoint (awaiting human verify) | — |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — `cameraUrl` is wired to the actual bridge MJPEG endpoint. The view will show an error message (not a stub) if the camera is unavailable.

## Threat Surface Scan

No new threat surface beyond what was documented in the plan's threat model (T-08-08, T-08-09). The MJPEG URL is set from plugin constructor options sourced from `index.html`, not from any external user input.

## Self-Check: PARTIAL

Plan is at checkpoint — Task 2 awaiting human verification. Task 1 self-check:

- plugin.js exists and modified: FOUND
- Commit 6c70f62 exists: FOUND
- All 13 acceptance criteria: PASS (verified via grep)
