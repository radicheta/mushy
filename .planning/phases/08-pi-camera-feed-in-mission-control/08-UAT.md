---
status: partial
phase: 08-pi-camera-feed-in-mission-control
source: [08-01-SUMMARY.md, 08-02-SUMMARY.md, 08-03-SUMMARY.md]
started: 2026-04-09T12:00:00Z
updated: 2026-04-09T12:10:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: docker-compose up from src/ starts all services. Bridge logs show ROS init and camera subscription. /health responds.
result: blocked
blocked_by: server
reason: "Requires docker-compose up on elder-plops — verified code paths instead: docker-compose.yml has SNAPSHOT_DIR, SNAPSHOT_INTERVAL_MIN, CAMERA_ID env vars and /data/snapshots mount. Bridge index.js starts ROS, creates camera subscription, starts snapshot timer, serves /health with camera field."

### 2. Camera Node Starts in Simulation Mode
expected: fc_camera node launches without webcam. No crash, no error — silent no-ops because camera_simulation_mode: true in config.
result: pass
note: "Code verified: fc_config.yaml has camera_simulation_mode: true. FcCamera.__init__ sets self.cap = None when simulation_mode is True, timer callback returns immediately when cap is None. 4 unit tests pass including test_camera_sim_mode."

### 3. MJPEG Stream Endpoint
expected: Bridge serves /camera/mjpeg as multipart/x-mixed-replace. Pushes JPEG frames to connected clients. Handles stale client cleanup.
result: pass
note: "Code verified: index.js:196-209 — GET /camera/mjpeg sends correct multipart headers, adds res to mjpegClients Set, removes on req close. pushFrame() checks res.writable, catches write errors, removes stale clients."

### 4. Snapshot Endpoint
expected: GET /camera/snapshot returns JPEG when frame available, 503 when not.
result: pass
note: "Code verified: index.js:212-222 — returns 503 JSON when latestFrame is null, otherwise sends image/jpeg with correct Content-Type and Content-Length headers."

### 5. Health Endpoint Shows Camera Status
expected: GET /health includes camera.lastFrame and camera.clients fields.
result: pass
note: "Code verified: index.js:122-129 — /health response includes camera: { lastFrame: lastFrameTime, clients: mjpegClients.size }."

### 6. Snapshot Storage on Disk
expected: saveSnapshot writes to /data/snapshots/fc1/YYYY-MM-DD/ with date-organized dirs and timestamped filenames. setInterval triggers at SNAPSHOT_INTERVAL_MS.
result: pass
note: "Code verified: index.js:64-76 — mkdirSync with recursive:true, ISO date dir, timestamped filename. Line 327: setInterval(saveSnapshot, SNAPSHOT_INTERVAL_MS) started after ROS init."

### 7. Camera Object in Mission Control Tree
expected: FC-1 Camera appears in Mission Control tree alongside sensors.
result: issue
reported: "FC-1 Camera visible in tree but naming is inconsistent — sensors are just 'Humidity', 'Temperature' etc. while camera has 'FC-1' prefix. Folder already says 'Fruiting Chamber FC-1' so prefix is redundant."
severity: cosmetic

### 8. Camera Live View in Mission Control
expected: Clicking FC-1 Camera shows MJPEG feed on black background with live video from connected USB webcam.
result: issue
reported: "Camera is connected but view shows only black — no pixels. Feed not reaching the browser."
severity: major

### 9. Camera Unavailable Fallback
expected: When camera unavailable, view shows text message instead of broken image icon.
result: skipped
reason: "Camera is connected — cannot test unavailable scenario right now. Will revisit after feed bug is fixed."

## Summary

total: 9
passed: 5
issues: 2
pending: 0
skipped: 1
blocked: 1

## Gaps

- truth: "Camera object naming matches existing sensor naming convention (no FC-1 prefix)"
  status: fixed
  reason: "User reported: naming inconsistent — sensors are 'Humidity', 'Temperature' etc. but camera is 'FC-1 Camera'. Folder already identifies the chamber."
  fix: "08-04 renamed to 'Camera' in plugin.js:115 (commit 8255d37)"
  severity: cosmetic
  test: 7
  root_cause: "Camera object name is 'FC-1 Camera' (plugin.js:115) while sensors use bare names like 'Humidity', 'Temperature'. Parent folder already says 'Fruiting Chamber FC-1'."
  artifacts:
    - path: "src/mission-control/frontend/plugins/fruiting-chamber/plugin.js"
      issue: "Line 115: name 'FC-1 Camera' should be 'Camera' to match sensor naming convention"
  missing:
    - "Rename 'FC-1 Camera' to 'Camera' in object provider"
  debug_session: ""

- truth: "Live camera feed visible in Mission Control when USB webcam is connected"
  status: fixed-pending-deploy
  reason: "User reported: camera is connected but view shows only black — no pixels reaching browser"
  fix: "08-04 wired production URLs in index.html (commit 8255d37), set camera_simulation_mode: false (commit 3b813d7). Deploy to Pi blocked — fc1 offline. Awaiting 4G hotspot."
  severity: major
  test: 8
  root_cause: "Two independent causes: (1) fc_config.yaml line 41 has camera_simulation_mode: true — camera node never publishes frames. (2) index.html:99 installs FruitingChamberPlugin() with no options, so cameraUrl defaults to localhost:8081 — wrong host when browser is not on elder-plops."
  artifacts:
    - path: "src/chambers/fc-core/config/fc_config.yaml"
      issue: "Line 41: camera_simulation_mode: true prevents frame capture"
    - path: "src/mission-control/frontend/index.html"
      issue: "Line 99: FruitingChamberPlugin() called with no options — cameraUrl defaults to localhost"
    - path: "src/mission-control/frontend/plugins/fruiting-chamber/plugin.js"
      issue: "Line 74: cameraUrl default is http://localhost:8081/camera/mjpeg"
  missing:
    - "Set camera_simulation_mode: false in fc_config.yaml (requires redeploy to Pi)"
    - "Pass correct host URLs in FruitingChamberPlugin() options in index.html"
  debug_session: ""
