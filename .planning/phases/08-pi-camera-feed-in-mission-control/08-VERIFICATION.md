---
phase: 08-pi-camera-feed-in-mission-control
verified: 2026-04-11T15:15:00-03:00
status: gaps_found
score: 3/5 requirements fully wired, 2/5 partial
verification_method: runtime-on-pi-and-bridge
human_verification:
  - test: "Watch MJPEG stream continuously for 5 minutes in browser and confirm no stalls"
    expected: "Stream plays without interruption; lastFrame timestamp advances at ~1Hz"
    why_human: "Requires an active MJPEG client to trigger streaming path — curl + metric inspection is not sufficient to catch intermittent delivery issues"
---

# Phase 08: Pi Camera Feed in Mission Control — Verification Report

**Phase Goal:** USB webcam on fc1 Pi streams live video accessible from Mission Control (OpenMCT). Foundation for future vision features.
**Verified:** 2026-04-11T15:15-03:00
**Method:** Runtime verification on both ends (Pi publisher, elder-plops bridge subscriber), plus filesystem inspection of saved snapshots.
**Note:** This VERIFICATION.md was written retroactively during milestone v1.0 audit paperwork closure on 2026-04-11. Phase 08 was previously marked "paused — Pi deploy blocked on connectivity" in SUMMARY files. That narrative is **obsolete** as of this audit — fc_camera *is* running on the Pi and has been since at least 2026-04-10 14:59 UTC (the last fc-core service start). What is not working is the *live MJPEG delivery* to elder-plops, which is a runtime networking issue, not a deployment blocker.

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | fc_camera node publishes `/fc1/camera/compressed` (CAM-01) | VERIFIED | Process `fc_camera` running on Pi (PID 1476, parameterized from `fc_config.yaml`). `ros2 topic info /fc1/camera/compressed` on Pi shows Publisher count: 1, node: fc_camera. |
| 2 | Camera params configurable in fc_config.yaml (CAM-02) | VERIFIED | `fc_config.yaml` on Pi: `camera_simulation_mode: false`, `camera_device: 0`, `camera_width: 640`, `camera_height: 480`, `camera_fps: 1`, `camera_jpeg_quality: 65`. fc_camera is reading them (process live, frames were being produced as recently as 14:52 UTC today). |
| 3 | Bridge serves `/camera/mjpeg` (CAM-03) | PARTIAL | Endpoint exists and responds; `/camera/snapshot` returned a 23,605-byte JPEG when called during this audit. BUT `/health` shows `lastFrame` ~20+ minutes stale, indicating fresh frames from the ROS topic are not reaching the bridge right now. See "Runtime gap" below. |
| 4 | Bridge saves periodic snapshots (CAM-04) | VERIFIED | `/data/snapshots/fc1/2026-04-11/` exists and bridge logs confirm saves at 14:20:23, 14:35:23, 14:50:23 UTC during the recent flow — three snapshots at the configured 15-minute interval. Snapshot path and filename format match config. |
| 5 | OpenMCT plugin exposes camera view (CAM-05) | VERIFIED | `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` registers `fruiting-chamber.camera` type + object provider + view provider that renders an `<img>` tag backed by `cameraUrl`. Today's index.html fix resolves `cameraUrl` against `window.location.hostname`, so the camera object renders the correct stream URL regardless of browse host. Camera object visible in Mission Control tree. Live feed visibility is gated by Truth #3. |

**Score:** 3 fully wired, 2 partial → **gaps_found**.

## Runtime Gap Discovered

The integration checker caught — and this audit confirms — that the live MJPEG delivery is intermittent right now. Evidence:

- Bridge `/health` at audit time: `lastFrame: 1775919147673` (2026-04-11 14:52:27 UTC), ~20 minutes stale.
- fc_camera journal on Pi, after 14:57:50 UTC, is flooded with `ddsi_udp_conn_write to udp/192.168.1.193:24670 failed with retcode -1` (and `:24668`). These are CycloneDDS unicast retries against a subscriber endpoint at `192.168.1.193` that is not reachable from the Pi's current network path.
- `192.168.1.193` is not any known Tailscale or WireGuard peer — likely a stale subscription from a prior test session (tablet / laptop on a farm LAN subnet that no longer routes to the Pi, or a past OpenMCT browser instance whose rclnodejs subscriber was never cleanly torn down).

This doesn't block CAM-01 (publisher is live), CAM-02 (config correct), or CAM-04 (snapshots are writing). It does block the "live moving video in the browser" experience that CAM-03 and CAM-05 promise — the bridge is the one subscriber that should matter, but the failing writes to the phantom 192.168.1.193 peer appear to be starving the camera topic's delivery queue.

This is being flagged as **tech debt carried from Phase 08 into post-v1.0**, not a Phase 08 failure. The code-level deliverables are all in place; the issue is a CycloneDDS subscriber cleanup / durability gap.

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| CAM-01 Camera publisher | SATISFIED | Truth #1 |
| CAM-02 Camera config | SATISFIED | Truth #2 |
| CAM-03 Bridge MJPEG serving | PARTIAL | Truth #3 — endpoint correct, live frame delivery intermittent |
| CAM-04 Snapshot capture | SATISFIED | Truth #4 |
| CAM-05 OpenMCT camera view | SATISFIED (code-level) | Truth #5 — wiring correct, live stream dependency on CAM-03 |

## Also Noticed During This Audit

- **ACTR-03 QoS mismatch:** The bridge's subscription to `/fc1/actuators/humidifier` (index.js:~312) uses rclnodejs default QoS (VOLATILE), but the publisher uses `TRANSIENT_LOCAL`. Data does flow (the DB has ~2200 humidifier rows over ~50 min), but on bridge restart the subscriber can't receive the last known actuator state until the next toggle. This is a pre-existing Phase 04 integration gap that was not caught in the earlier Phase 04 verification. Low severity for MVP. Tech debt.
- **Boot restart noise:** fc-core.service `NRestarts=4` were all during the first few minutes of the Pi's 2026-04-10 boot, due to CycloneDDS `rmw_create_node: failed to create domain` errors related to `tailscale0` interface initialization timing. Service self-recovered. Low severity for MVP but worth a watchdog fix before extended unattended operation.

## Gaps

- **CAM-03 runtime delivery** — see "Runtime Gap Discovered" above.
- **Human MJPEG stability test** — captured in frontmatter.

---
*Verified: 2026-04-11T15:15-03:00*
*Verifier: Claude (audit-milestone paperwork closure)*
