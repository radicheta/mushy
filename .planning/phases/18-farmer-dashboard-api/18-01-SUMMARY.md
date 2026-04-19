---
phase: 18-farmer-dashboard-api
plan: 18-01
title: Read-only /farmer/summary endpoint on mushy bridge
status: shipped
mode: retrofit
completed: 2026-04-19
commits:
  - effb17e  # feat(18): add GET /farmer/summary read-only endpoint
tags: [bridge, api, farmer, farmos, delegation, retrofit]
metrics:
  duration: ~45min
  completed: "2026-04-19"
  tasks: 4 of 4
  files: 1
---

# Phase 18 Plan 01: /farmer/summary Endpoint Summary

**One-liner:** Added `GET /farmer/summary` to the mushy bridge — a read-only
JSON snapshot of current chamber state (sensors, actuators, sensor_health,
camera status) for the farmOS-hosted farmer dashboard to consume.

## Performance

- **Duration:** ~45 min (including rebuild + live verification)
- **Completed:** 2026-04-19
- **Tasks:** 4 of 4
- **Files modified:** 1

## Accomplishments

### Task 1: Latest-value cache

- Added module-level `latestTelemetry` object in `index.js` alongside the
  existing `humidifierLastMsgTs` / `lastSensorHealthBroadcast` state.
- Shape: `{ humidity, temperature, co2, humidifier }`, each `null` or
  `{ value, timestamp }`.

### Task 2: Subscription callback updates

- Appended `latestTelemetry.*` writes to the humidity / temperature / co2 /
  humidifier callbacks. One line each. No new subscriptions.
- `sensor_health` cache already existed from Phase 16.1 — reused directly.
- `lastFrameTime` + `cameraSubscription` already existed from Phases 12 / 14
  — reused directly.

### Task 3: /farmer/summary route

- Added route after `/health` in `src/mission-control/bridge/src/index.js`.
- Response shape matches the draft proposed to Zoy-side via
  `/mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md` entry 2026-04-19.
- Camera `last_frame_age_sec` computed from `Date.now() - lastFrameTime`,
  `null` when no frame has ever been received (matches `/health` behavior).

### Task 4: Rebuild + live verification

- `docker compose up -d --build bridge` on elder-plops.
- `curl http://localhost:8081/farmer/summary` returned valid JSON with live
  values: humidity 91.4, temperature 16.5, co2 492, humidifier 0, sensor_health
  level 0 (OK), camera subscribed=false (no MJPEG client active — expected
  per Phase 12 subscriber-aware behavior).

## Task Commits

1. **feat(18): add GET /farmer/summary read-only endpoint** — `effb17e`

## Deviations from Plan

None. Retrofit plan — written after the work shipped. No execution
surprises to capture.

## Known Gaps

- **No alerts feed in payload.** Deferred to a follow-up phase (requires
  alerter→bridge back-channel — see CONTEXT.md "Deferred Ideas"). Farmer
  still receives alerts via Signal; dashboard's current-state visibility
  is unaffected.
- **Single-chamber only.** Response returns `chamber_id: "fc1"` always.
  Multi-chamber generalization defers to 999.6 / Pi Zero pattern work.
- **CORS decision pending Zoy-side.** If Zoy goes browser-direct fetch from
  a farmOS page, we'll need to add the farmOS origin to `CORS_ORIGIN`. Cheap
  flip — one env-var change.

## Verification Evidence

Live curl output against elder-plops bridge 2026-04-19:

```json
{
  "chamber_id": "fc1",
  "timestamp": 1776562715206,
  "sensors": {
    "humidity":    { "value": 91.40764476997025, "timestamp": 1776562711239 },
    "temperature": { "value": 16.465629053177686, "timestamp": 1776562711238 },
    "co2":         { "value": 492, "timestamp": 1776562711239 }
  },
  "actuators": {
    "humidifier":  { "value": 0, "timestamp": 1776562714569 }
  },
  "sensor_health": {
    "level": 0, "name": "fc1/controller", "message": "ok",
    "values": {
      "warming_up": "false",
      "grace_elapsed_sec": "25.0",
      "grace_total_sec": "20.0",
      "buffer_full": "true"
    }
  },
  "camera": { "last_frame_age_sec": null, "subscribed": false }
}
```
