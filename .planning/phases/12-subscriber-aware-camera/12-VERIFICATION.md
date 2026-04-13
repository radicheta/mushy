---
phase: 12-subscriber-aware-camera
verified: 2026-04-13T00:00:00Z
status: human_needed
score: 9/10 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Deploy bridge (docker compose up -d --build bridge) and fc_camera changes to Pi (push fc1/prod, run deploy). With Mission Control CLOSED, run: ros2 topic hz /fc1/camera/compressed --window 10. Should show ~0.000278 Hz (~1 frame/hour). Run: curl http://localhost:8081/health — should show subscribed:false, clients:0."
    expected: "Topic rate ~0.000278 Hz at idle. Health endpoint shows subscribed:false."
    why_human: "Requires live Pi hardware + 4G + ROS2 runtime. Cannot be verified from codebase static analysis."
  - test: "Open Mission Control camera view in browser at http://10.68.155.50:8080. Within 5 seconds the badge should change to LIVE with teal (#4ecdc4) dot and border. Run ros2 topic hz on Pi — should jump to ~1 Hz. Run curl health — should show subscribed:true."
    expected: "LIVE badge within 5 seconds of opening camera view. Topic rate jumps to ~1 Hz. Health shows subscribed:true."
    why_human: "Requires browser + live camera feed + visual badge observation."
  - test: "Close Mission Control tab and wait 6+ seconds (past grace period). Run ros2 topic hz — should drop back to ~0 Hz. Re-open Mission Control — camera should resume without stutter and badge shows LIVE."
    expected: "Rate drops to idle after tab close + grace period. Seamless ramp-up on re-open."
    why_human: "Requires live hardware timing observation of grace period expiry."
  - test: "With Mission Control camera view open, do a quick page refresh (within 5 seconds). Camera should NOT cycle through idle — grace period keeps the bridge subscribed during the reconnect window."
    expected: "No idle/active cycling on page refresh within 5 seconds."
    why_human: "Requires live hardware timing test of grace period behavior."
  - test: "Run python3 -m pytest src/chambers/fc-core/fc_core/test/test_camera.py -v in the correct pyenv environment (mushroom_farm). All 12 tests must pass."
    expected: "12 passed, 0 failed."
    why_human: "pyenv environment 'mushroom_farm' not available in current shell. Cannot run tests via static verification."
---

# Phase 12: Subscriber-Aware Camera Verification Report

**Phase Goal:** fc_camera conserves 4G bandwidth by idling when no viewers are watching; Mission Control gets full-rate feed the moment someone connects
**Verified:** 2026-04-13
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | fc_camera starts in idle mode at 1 frame/hour (0.000278 fps) | VERIFIED | `fc_camera.py:47-48` `_is_active=False`, `_cam_timer` created at `1.0/self._idle_fps`; `fc_config.yaml:45` `camera_fps: 0.000278` |
| 2 | fc_camera ramps to 1.0 fps when get_subscription_count() > 0 | VERIFIED | `fc_camera.py:94-95` checks `count > 0 and not self._is_active` → `_ramp_up()`; `_ramp_up` creates timer at `1.0/self._active_fps` |
| 3 | fc_camera drops back to idle after 5s grace when subscribers go to 0 | VERIFIED | `fc_camera.py:100-101` starts `_start_grace()` when `count==0 and _is_active`; `_grace_expired` calls `_ramp_down()` |
| 4 | Grace period is cancelled if a subscriber reconnects within 5 seconds | VERIFIED | `fc_camera.py:96-99` inline branch `count>0 and _is_active and _grace_timer is not None` destroys grace timer |
| 5 | fc_config.yaml declares camera_active_fps and camera_subscriber_grace_sec | VERIFIED | `fc_config.yaml:47-48` contains both params with correct values |
| 6 | Bridge subscribes to /fc1/camera/compressed only when MJPEG clients are connected | VERIFIED | `index.js:68-79` `ensureCameraSubscribed()` guards with `cameraSubscription !== null` check; called at `mjpegClients.add(res)` line 235 |
| 7 | Bridge unsubscribes from /fc1/camera/compressed when last MJPEG client disconnects | VERIFIED | `index.js:81-86` `maybeCameraUnsubscribe()` guards with `mjpegClients.size > 0` check; called in `req.on('close')` line 239 |
| 8 | Mission Control camera view shows LIVE badge when frames are flowing | VERIFIED | `plugin.js:344-348` `isLive` condition: `cam.subscribed===true AND lastFrame within 10s` → sets `#4ecdc4` colors and "LIVE" text |
| 9 | Mission Control camera view shows IDLE badge when no frames arrive for 10+ seconds | VERIFIED | `plugin.js:349-353` else branch sets `#555` colors and "IDLE · 1 frame/hr" text |
| 10 | End-to-end hardware verification (rate switching, badge, grace period on real Pi) | PENDING HUMAN | Plan 02 Task 3 was `auto-approved` in SUMMARY but is a `gate: blocking` human checkpoint requiring live hardware |

**Score:** 9/10 truths verified (1 pending human verification)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/chambers/fc-core/fc_core/fc_camera.py` | Subscriber-aware rate switching with grace period | VERIFIED | Contains `get_subscription_count`, `_ramp_up`, `_ramp_down`, `_start_grace`, `_grace_expired`, `_is_active`, `_grace_timer`, `camera_active_fps`, `camera_subscriber_grace_sec` |
| `src/chambers/fc-core/fc_core/test/test_camera.py` | Tests for subscriber-aware behavior and grace period | VERIFIED | Contains `TestSubscriberAwareCamera` (4 tests), `TestSubscriberGracePeriod` (4 tests), updated `FakePublisher`, `FakeTimer`, `FakeNode`, `_patch_params` helper |
| `src/chambers/fc-core/config/fc_config.yaml` | New camera parameters | VERIFIED | Contains `camera_fps: 0.000278`, `camera_active_fps: 1.0`, `camera_subscriber_grace_sec: 5.0` |
| `src/mission-control/bridge/src/index.js` | Conditional camera subscription based on MJPEG client count | VERIFIED | Contains `ensureCameraSubscribed`, `maybeCameraUnsubscribe`, `cameraSubscription`, `rosNode`; health endpoint includes `subscribed` field; no always-on CompressedImage subscription |
| `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` | LIVE/IDLE status badge on camera view | VERIFIED | Contains `IDLE`, `LIVE`, `#4ecdc4`, `updateBadge`, `setInterval(updateBadge, 5000)`, `clearInterval`, `fetch(healthUrl)` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| fc_camera.py | fc_config.yaml | declare_parameters with camera_active_fps, camera_subscriber_grace_sec | VERIFIED | `fc_camera.py:32-33` declares both params; `fc_config.yaml:47-48` defines them |
| fc_camera.py | self._cam_pub | get_subscription_count() checked on every timer tick | VERIFIED | `fc_camera.py:93` `count = self._cam_pub.get_subscription_count()` is first statement in `capture_and_publish` |
| index.js | mjpegClients | ensureCameraSubscribed on client connect, maybeCameraUnsubscribe on client close | VERIFIED | `index.js:235` `ensureCameraSubscribed()` after `mjpegClients.add(res)`; `index.js:239` `maybeCameraUnsubscribe()` after `mjpegClients.delete(res)` |
| plugin.js | MJPEG img element | polling lastFrameTimestamp to detect idle vs active | VERIFIED | `plugin.js:343` `isLive = cam.subscribed===true && cam.lastFrame && (Date.now()-cam.lastFrame < 10000)`; badge updated via `setInterval(updateBadge, 5000)` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| fc_camera.py `_is_active` | `count` from `get_subscription_count()` | ROS2 `rcl_publisher` C layer | Yes — live subscriber count from DDS | FLOWING |
| index.js badge data | `cameraSubscription` state | `mjpegClients.size` guards real `rosNode.createSubscription` call | Yes — real ROS2 subscription lifecycle | FLOWING |
| plugin.js badge state | `cam.subscribed`, `cam.lastFrame` | `fetch(healthUrl)` polls `/health` endpoint which returns `cameraSubscription !== null` and `lastFrameTime` | Yes — live bridge state | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 12 camera tests pass | `python3 -m pytest src/chambers/fc-core/fc_core/test/test_camera.py -v` | pyenv environment 'mushroom_farm' not active; cannot run | ? SKIP |
| No always-on CompressedImage subscription | `grep -n "node.createSubscription.*CompressedImage\|createSubscription.*fc1/camera" src/mission-control/bridge/src/index.js` | No output — no match found | PASS |
| ensureCameraSubscribed wired in 4 places | `grep -c "ensureCameraSubscribed\|maybeCameraUnsubscribe" src/mission-control/bridge/src/index.js` | 4 | PASS |
| fc_config.yaml idle rate correct | `grep 'camera_fps: 0.000278' src/chambers/fc-core/config/fc_config.yaml` | Match found | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| CAM-01 | Plans 01, 02 | fc_camera publishes at full configured rate only when subscribers are present on /fc1/camera/compressed | SATISFIED | Bridge `ensureCameraSubscribed`/`maybeCameraUnsubscribe` gates the ROS subscription; `get_subscription_count()` drives rate in `fc_camera.py` |
| CAM-02 | Plan 01 | fc_camera drops to idle rate (1 frame/min or less) when no subscribers are connected | SATISFIED | `camera_fps: 0.000278` in config (~1 frame/hour, well below 1/min threshold); `_is_active=False` at startup |
| CAM-03 | Plans 01, 02 | Transition between idle and active is automatic and transparent to bridge/Mission Control | SATISFIED | Bridge subscribes lazily on MJPEG connect; fc_camera detects subscriber count change on next tick; LIVE/IDLE badge informs operator without interrupting feed |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| fc_camera.py | 79, 138, 159 | `1.0 / self._idle_fps` — no zero guard | Warning (WR-01) | ZeroDivisionError crash if config param set to 0; current YAML values are safe |
| index.js | 69 | `ensureCameraSubscribed()` returns early when `rosNode === null` with no retry | Warning (WR-02) | MJPEG client connecting during ROS init window gets no frames until next connect cycle |
| plugin.js | 315 | `cameraUrl.replace('/camera/mjpeg', '/health')` fragile string replacement | Warning (WR-03) | Silently wrong health URL if cameraUrl uses different path; low risk with current config |
| index.js | 72 vs fc_camera.py:75 | Absolute topic (`/fc1/camera/compressed`) in bridge vs relative (`fc1/camera/compressed`) in camera node | Warning (WR-04) | Works now (default namespace); breaks silently if namespace added for multi-chamber |

None of these are blockers for the current phase goal — WR-02 has a tiny attack window, WR-01 only triggers on misconfiguration, WR-03 only triggers on non-default config, WR-04 only triggers on future namespace changes. All four were captured in the code review report (12-REVIEW.md).

### Human Verification Required

#### 1. Idle rate on Pi with no viewers

**Test:** Deploy bridge (`docker compose up -d --build bridge`) and fc_camera changes to Pi (push to fc1/prod, run deploy.sh). With Mission Control CLOSED, run on Pi: `ros2 topic hz /fc1/camera/compressed --window 10`
**Expected:** Rate shows ~0.000278 Hz (~1 frame/hour). Bridge health `curl http://localhost:8081/health` returns `"subscribed": false, "clients": 0`
**Why human:** Requires live Pi hardware with ROS2 running and 4G connectivity.

#### 2. LIVE badge on Mission Control open

**Test:** Open Mission Control camera view in browser at http://10.68.155.50:8080. Wait up to 5 seconds.
**Expected:** Badge transitions from IDLE to LIVE with teal (#4ecdc4) dot and border. `ros2 topic hz` on Pi shows ~1 Hz. Bridge health shows `"subscribed": true`
**Why human:** Requires browser, live camera feed, and visual badge observation.

#### 3. Grace period — idle after tab close

**Test:** Close Mission Control tab. Wait 6+ seconds. Check `ros2 topic hz` on Pi.
**Expected:** Rate drops back to ~0 Hz after grace period expires. Re-opening Mission Control should resume smoothly with LIVE badge reappearing.
**Why human:** Requires timing observation of the 5-second grace period expiry on live hardware.

#### 4. Grace period — no cycling on page refresh

**Test:** With Mission Control camera view open, do a quick browser page refresh (within 5 seconds of previous connection).
**Expected:** Camera does NOT cycle through idle — bridge stays subscribed during the reconnect window. No stutter in the MJPEG stream.
**Why human:** Requires live hardware timing test; cannot verify grace period behavior with static analysis.

#### 5. Test suite pass confirmation

**Test:** In the correct pyenv environment (`mushroom_farm`), run: `python3 -m pytest src/chambers/fc-core/fc_core/test/test_camera.py -v`
**Expected:** 12 passed, 0 failed (4 original + 4 TestSubscriberAwareCamera + 4 TestSubscriberGracePeriod)
**Why human:** pyenv environment 'mushroom_farm' not available in current verification shell. Test code structure is correct but execution confirmation requires the project's Python environment.

### Gaps Summary

No automated gaps. All 9 statically-verifiable must-haves pass at all four levels (exist, substantive, wired, data flowing). The one outstanding item is human hardware verification.

**Note on auto-approved checkpoint:** Plan 02 Task 3 is a `gate: blocking` human checkpoint explicitly requiring visual verification on real hardware. The 12-02-SUMMARY.md recorded it as `auto-approved`. This is insufficient for a blocking gate — human verification items 1-4 above correspond exactly to the 12 steps listed in the plan's human verification task and must be completed before this phase is considered closed.

---

_Verified: 2026-04-13T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
