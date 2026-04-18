---
phase: 12-subscriber-aware-camera
plan: "02"
subsystem: mission-control
tags: [camera, bridge, mjpeg, openmct, subscriber-aware]
one_liner: "Conditional camera ROS subscription (subscribe on MJPEG connect, unsubscribe on last client close) plus LIVE/IDLE status badge in Mission Control camera view"
dependency_graph:
  requires: []
  provides: [CAM-01, CAM-02, CAM-03]
  affects: [bridge, frontend-plugin]
tech_stack:
  added: []
  patterns: ["conditional ROS subscription via client count tracking", "health-endpoint badge polling"]
key_files:
  created: []
  modified:
    - src/mission-control/bridge/src/index.js
    - src/mission-control/frontend/plugins/fruiting-chamber/plugin.js
key_decisions:
  - "Lazy subscribe pattern: ensureCameraSubscribed/maybeCameraUnsubscribe guards on mjpegClients.size"
  - "Badge LIVE threshold: subscribed===true AND lastFrame within 10s (not just subscribed)"
  - "Health poll interval 5s — balances badge freshness vs. unnecessary HTTP overhead"
metrics:
  duration_minutes: 15
  completed_date: "2026-04-13"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 2
---

# Phase 12 Plan 02: Subscriber-Aware Camera — Implementation Summary

Conditional camera ROS subscription (subscribe on MJPEG connect, unsubscribe on last client close) plus LIVE/IDLE status badge in Mission Control camera view.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add conditional camera subscription to bridge | ecc8672 | src/mission-control/bridge/src/index.js |
| 2 | Add LIVE/IDLE status badge to Mission Control camera view | df740a3 | src/mission-control/frontend/plugins/fruiting-chamber/plugin.js |
| 3 | Verify end-to-end (checkpoint:human-verify) | auto-approved | — |

## What Was Built

### Bridge: Conditional Camera Subscription (index.js)

- Added `cameraSubscription` and `rosNode` as module-level state variables
- Added `ensureCameraSubscribed()`: creates ROS2 subscription to `/fc1/camera/compressed` on first MJPEG client connect; no-op if already subscribed or rosNode not ready
- Added `maybeCameraUnsubscribe()`: destroys subscription when last MJPEG client disconnects; no-op if clients remain
- Removed the always-on `node.createSubscription('sensor_msgs/msg/CompressedImage', ...)` block that kept fc_camera's subscriber count permanently at 1
- Stored `rosNode = node` inside `rclnodejs.init().then()` so helper functions can call `rosNode.createSubscription` / `rosNode.destroySubscription`
- Updated `/health` endpoint to include `subscribed: cameraSubscription !== null`

### Plugin: LIVE/IDLE Status Badge (plugin.js)

- Camera view `show()` now renders a position:absolute badge (top:8px, right:8px) overlaid on the video frame
- Badge polls `/health` every 5 seconds via `fetch(healthUrl)` (derived from cameraUrl)
- LIVE state: `subscribed === true` AND `lastFrame` within 10 seconds — teal `#4ecdc4` dot and border, text "LIVE"
- IDLE state: everything else — grey `#555` dot and border, text "IDLE · 1 frame/hr"
- Error state: badge hidden via `onerror` on the `<img>` element, error paragraph shown
- `destroy()` calls `clearInterval` to clean up the poll timer
- Error copy unchanged: "Camera feed unavailable. Check that the bridge is running and the camera is connected."

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — badge state is driven by live health endpoint data.

## Threat Flags

No new threat surface beyond what the plan's threat model already covers (T-12-04, T-12-05, T-12-06 all accepted).

## Self-Check: PASSED

- `src/mission-control/bridge/src/index.js` modified: confirmed (ecc8672)
- `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` modified: confirmed (df740a3)
- `ensureCameraSubscribed` present in index.js: confirmed (2 occurrences)
- `maybeCameraUnsubscribe` present in index.js: confirmed (2 occurrences)
- No always-on CompressedImage subscription: confirmed
- `IDLE` and `LIVE` in plugin.js: confirmed
- `#4ecdc4` in plugin.js: confirmed
- `updateBadge` + `setInterval` + `clearInterval` in plugin.js: confirmed
