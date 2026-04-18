---
phase: 14-fc-camera-idle-stall-hotfix
plan: 03
subsystem: infra
tags: [bridge, health, camera, observability, docker, ros2]

# Dependency graph
requires:
  - phase: 14-02
    provides: "fc_camera 1Hz graph-poll fallback (undeployed to fc1 until plan 14-05)"
provides:
  - "bridge /health exposes camera.last_frame_age_sec (integer seconds or null) server-side"
  - "mushy-bridge-1 rebuilt and running on elder-plops with updated /health shape"
affects:
  - "14-04 (two-lights UI — consumes last_frame_age_sec and subscribed)"
  - "Phase 16 (system health panel — same /health primitives)"
  - "farmos_agent daily report (additive field, existing consumers unaffected)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Server-side age computation in /health avoids client clock-skew"
    - "null distinguishes 'no frame ever' from age=0 (fresh frame)"

key-files:
  created: []
  modified:
    - src/mission-control/bridge/src/index.js

key-decisions:
  - "Math.round(.../ 1000) produces integer seconds — simpler threshold comparisons for UI and Phase 16; sub-second precision can be added later if needed"
  - "null when lastFrameTime === null explicitly distinguishes no-data from age=0; downstream UI renders grey/unknown vs green"
  - "Additive change only — camera.lastFrame, camera.clients, camera.subscribed all preserved in original positions"

patterns-established:
  - "Bridge /health is the single source of truth for camera status — two lights in 14-04 and Phase 16 health panel both read from here"

requirements-completed: [HFIX-03]

# Metrics
duration: 12min
completed: 2026-04-17
---

# Phase 14 Plan 03: Bridge /health camera.last_frame_age_sec Summary

**Server-computed integer age field added to bridge /health — null on no frame, integer seconds on any frame — rebuilds mushy-bridge-1 on elder-plops making the 2026-04-17 stall legible without client clock-skew**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-04-17T21:28:00Z
- **Completed:** 2026-04-17T21:40:00Z
- **Tasks:** 3
- **Files modified:** 1

## Accomplishments

- Added `camera.last_frame_age_sec` to bridge `/health` JSON — server-side `Math.round((Date.now() - lastFrameTime) / 1000)`, or `null` when `lastFrameTime` is null
- Preserved all existing fields (`camera.lastFrame`, `camera.clients`, `camera.subscribed`) in original positions — farmos_agent and other consumers unaffected
- Rebuilt `mushy-bridge-1` on elder-plops using `docker compose up -d --build bridge` (compose v2.40.3)

## Task Commits

1. **Task 1: Add last_frame_age_sec to /health handler** - `88ed07c` (feat)
2. **Task 2: Rebuild bridge container on elder-plops and smoke-test /health** - (rebuild only, no new commit — container deploy is not a file change)
3. **Task 3: Commit bridge change** - `88ed07c` (combined with Task 1 per plan instruction to stage only index.js)

## /health Response Observed Post-Rebuild

### Null case (immediately post-restart, no MJPEG viewer, fc_camera not yet streaming):

```json
{
  "status": "ok",
  "db": true,
  "camera": {
    "lastFrame": null,
    "last_frame_age_sec": null,
    "clients": 0,
    "subscribed": false
  }
}
```

### Numeric case:

Not reproduced in this plan — fc_camera on fc1 has not sent frames to the bridge since restart (plan 14-02 fix not yet deployed to fc1; that happens in plan 14-05). `last_frame_age_sec` returned `null` even after briefly opening an MJPEG client, confirming the bridge correctly reports null until a frame actually arrives. The numeric path will be exercised in plan 14-05's soak test.

## Compose Version Used

`docker compose` (v2.40.3+ds1-0ubuntu1~22.04.1) — v2 confirmed available on elder-plops.

## Logs of Note During Rebuild

No errors. Standard startup sequence:
- `[db] Schema initialized`
- `[bridge] Humidifier subscription: TRANSIENT_LOCAL QoS`
- `[bridge] HTTP + WebSocket server on port 8081`

One expected warning about `ROS_LOCALHOST_ONLY` deprecation (pre-existing, not introduced by this plan).

## Files Created/Modified

- `src/mission-control/bridge/src/index.js` — `/health` handler extended with `last_frame_age_sec` computation (7 insertions, 2 deletions)

## Decisions Made

- Used `Math.round(... / 1000)` for integer seconds rather than float — threshold comparisons in plan 14-04 UI (`< N seconds`) are simpler with integers; JSON float noise avoided
- `null` when `lastFrameTime === null` (strict equality) — explicitly distinguishes "bridge never received a frame" from age=0 (frame just arrived). The two-lights UI in plan 14-04 uses this to render grey (unknown) vs green (live).

## Deviations from Plan

None — plan executed exactly as written.

The plan's automated verification script for Task 1 used a single-line regex (`grep -qE "lastFrameTime === null\s*\?\s*null"`) that does not match multiline ternaries. The actual code uses a two-line ternary which is functionally correct and matches the plan's spec. The `Math.round` pattern verification via Node.js passed correctly. This is a plan-script limitation, not a code issue.

## Issues Encountered

None.

## Note on fc_camera Deployment

Plan 14-02's fc_camera fix is NOT yet deployed to fc1 at the end of this plan. The `last_frame_age_sec` field will return `null` until either:
1. An MJPEG viewer connects AND fc_camera sends frames (stall permitting), or
2. Plan 14-05 deploys the fc_camera fix to fc1 and the recovery is verified in the soak test.

This is expected behavior. The field is present and functional.

## Next Phase Readiness

- `camera.last_frame_age_sec` is live in `/health` — plan 14-04 can begin building the two-lights UI immediately
- Bridge `/health` now provides both primitives D-03 specifies: `last_frame_age_sec` (feed live light) and `subscribed` (camera subscribed light)
- Phase 16 system health panel can consume these same signals without rework

---
*Phase: 14-fc-camera-idle-stall-hotfix*
*Completed: 2026-04-17*

## Self-Check: PASSED

- `src/mission-control/bridge/src/index.js` — modified, committed in `88ed07c`
- Commit `88ed07c` exists: confirmed via `git log`
- `mushy-bridge-1` container: Up (confirmed `docker compose ps`)
- `/health` returns `camera.last_frame_age_sec`: confirmed via `curl | jq`
- No Co-Authored-By trailer: confirmed via `git log -1 --pretty=%B`
