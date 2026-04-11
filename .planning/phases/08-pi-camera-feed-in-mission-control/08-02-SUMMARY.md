---
phase: 08-pi-camera-feed-in-mission-control
plan: 02
subsystem: bridge
tags: [mjpeg, camera, streaming, snapshots, rclnodejs, express]
requirements: [CAM-03, CAM-04]

dependency_graph:
  requires: [08-01]
  provides: [MJPEG stream at /camera/mjpeg, snapshot storage, CompressedImage subscription]
  affects: [src/mission-control/bridge/src/index.js, src/docker-compose.yml]

tech_stack:
  added: [Node.js fs (built-in), Node.js path (built-in)]
  patterns:
    - Push-based MJPEG with client Set and writable guard
    - Date-organized snapshot directories via fs.mkdirSync recursive
    - Buffer.from(msg.data) for rclnodejs Uint8Array conversion
    - Bind mount /data/snapshots for host filesystem persistence

key_files:
  modified:
    - src/mission-control/bridge/src/index.js
    - src/docker-compose.yml

decisions:
  - "pushFrame checks res.writable before each write and catches errors — removes stale MJPEG clients without blocking event loop (T-08-04)"
  - "CAMERA_ID sourced from env var only (not HTTP request) — prevents path traversal in snapshot filenames (T-08-05)"
  - "No auth on /camera/mjpeg — accepted per T-08-06 (VPN-only access, same trust as /health and /history)"
  - "Snapshot interval defaults to 15 min from SNAPSHOT_INTERVAL_MIN env var — disk usage ~3MB/day accepted (T-08-07)"

metrics:
  duration: ~8min
  completed: 2026-04-09T02:37:05Z
  tasks_completed: 2
  files_modified: 2
---

# Phase 08 Plan 02: MJPEG Streaming and Snapshot Storage in Bridge Summary

Bridge now subscribes to `fc1/camera/compressed` CompressedImage frames from ROS2 and re-serves them as an HTTP MJPEG stream at `/camera/mjpeg`, with periodic snapshot saving to date-organized directories at `/data/snapshots/fc1/YYYY-MM-DD/`.

## What Was Built

### Task 1: MJPEG endpoint and snapshot storage in index.js (commit 73bdd4a)

Added camera functionality to `src/mission-control/bridge/src/index.js`:

- `require('fs')` and `require('path')` for filesystem I/O
- Camera state: `BOUNDARY = 'frameboundary'`, `mjpegClients` Set, `latestFrame`, `lastFrameTime`
- Env var config: `SNAPSHOT_DIR`, `SNAPSHOT_INTERVAL_MS`, `CAMERA_ID`
- `pushFrame(jpegBuffer)` — writes multipart frame to all connected MJPEG clients; checks `res.writable` before each write; catches write errors and removes stale clients
- `saveSnapshot()` — uses `fs.mkdirSync(dir, { recursive: true })` before every write; async `fs.writeFile` with error logging; logs path + camera ID + byte count
- `GET /camera/mjpeg` — sends `multipart/x-mixed-replace` response headers, registers response in `mjpegClients`, removes on request close
- `GET /camera/snapshot` — returns latest frame as single JPEG; 503 if no frame yet
- `createSubscription('sensor_msgs/msg/CompressedImage', '/fc1/camera/compressed', ...)` — converts `msg.data` to Buffer via `Buffer.from(msg.data)` before calling `pushFrame`
- `setInterval(saveSnapshot, SNAPSHOT_INTERVAL_MS)` started after ROS init
- `/health` response extended with `camera: { lastFrame, clients }` fields

### Task 2: Snapshot volume and env vars in docker-compose.yml (commit b03ad6c)

Updated `bridge` service in `src/docker-compose.yml`:

- Added env vars: `SNAPSHOT_DIR=/data/snapshots`, `SNAPSHOT_INTERVAL_MIN=15`, `CAMERA_ID=fc1`
- Added bind mount: `/data/snapshots:/data/snapshots`
- Operator note as YAML comment: `mkdir -p /data/snapshots/fc1` must be run on elder-plops host before first container start
- All existing env vars and volumes preserved unchanged

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — no hardcoded empty values or placeholder data. The `/camera/snapshot` endpoint returns 503 when `latestFrame` is null, which is correct behavior before any camera frame arrives (not a stub).

## Threat Surface

All threats addressed as designed:

| Flag | File | Status |
|------|------|--------|
| T-08-04 (DoS - stale MJPEG clients) | index.js | Mitigated — `res.writable` check + catch + Set.delete |
| T-08-05 (Tampering - snapshot path) | index.js | Accepted — CAMERA_ID from env only, path.join is safe |
| T-08-06 (Info Disclosure - /camera/mjpeg) | index.js | Accepted — VPN-only access, same trust as /health |
| T-08-07 (DoS - snapshot disk) | docker-compose.yml | Accepted — ~3MB/day at 15-min interval |

## Self-Check: PASSED

- `src/mission-control/bridge/src/index.js` exists and contains all required patterns
- `src/docker-compose.yml` exists with SNAPSHOT_DIR, SNAPSHOT_INTERVAL_MIN, CAMERA_ID, and /data/snapshots mount
- Commit 73bdd4a: feat(08-02) bridge camera MJPEG + snapshots
- Commit b03ad6c: chore(08-02) docker-compose snapshot volume + env vars
