---
phase: 16-system-health-panel
plan: "01"
subsystem: mission-control/bridge
tags: [bridge, websocket, health, ros, diagnostics]
dependency_graph:
  requires: [phase-15-sensor-warmup-grace-period]
  provides: [sensor_health_ws_broadcast, ros_connected_health_field, humidifier_liveness_health_field]
  affects: [plan-16-02]
tech_stack:
  added: []
  patterns: [TRANSIENT_LOCAL QoS subscription, /health JSON extension]
key_files:
  created: []
  modified:
    - src/mission-control/bridge/src/index.js
decisions:
  - "Flatten DiagnosticStatus KeyValue[] into plain JS object before broadcast for easy browser consumption"
  - "rosReady flips true immediately before node.spin() so it reflects full subscription readiness"
  - "humidifierLastMsgTs set as first line of callback so it captures arrival time accurately"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-17"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 1
---

# Phase 16 Plan 01: Bridge Health Signals Summary

Bridge forwards `/fc1/sensor_health` DiagnosticStatus over WebSocket and adds `ros.connected` + `humidifier.last_msg_ts` to `/health` endpoint, giving Plan 02's health panel all the signals it needs.

## What Was Done

### Change A — Module-level state (line 28-29)
Added `rosReady` and `humidifierLastMsgTs` variables after `let dbReady = false;`.

### Change B — `/health` handler extended (lines ~165-180)
Added `ros: { connected: rosReady }` and `humidifier: { last_msg_ts: humidifierLastMsgTs }` blocks alongside the existing `camera` block. All pre-existing fields (`camera.last_frame_age_sec`, `camera.subscribed`, `camera.lastFrame`, `camera.clients`) are unchanged.

### Change C — Humidifier callback updated (line ~390)
`humidifierLastMsgTs = Date.now();` inserted as the first statement in the `/fc1/actuators/humidifier` subscription callback.

### Change D — `/fc1/sensor_health` subscription (lines ~398-424)
New subscription using the same TRANSIENT_LOCAL QoS profile as the humidifier. Flattens `msg.values` (KeyValue[]) into a plain object and broadcasts `{ sensor_health: { level, name, message, values }, timestamp }` to all WebSocket clients.

### Change E — `rosReady = true` (line before `node.spin()`)
Flipped after all subscriptions are wired so it accurately reflects full readiness.

## Commit

- `df9f4b6` — feat(16-01): bridge forwards sensor_health + exposes ros.connected and humidifier.last_msg_ts

## Runtime Verification

`/health` response captured post-rebuild (bridge up ~12s):

```json
{
    "status": "ok",
    "db": true,
    "ros": {
        "connected": true
    },
    "camera": {
        "lastFrame": null,
        "last_frame_age_sec": null,
        "clients": 0,
        "subscribed": false
    },
    "humidifier": {
        "last_msg_ts": 1776476557639
    }
}
```

- `ros.connected`: `true` (rclnodejs init completed, all subscriptions wired)
- `humidifier.last_msg_ts`: `1776476557639` (TRANSIENT_LOCAL replayed last state from fc1 within seconds of bridge start)
- `camera.last_frame_age_sec`: `null` (no MJPEG clients connected — expected)
- Bridge logs confirm both subscription lines: `[bridge] Humidifier subscription: TRANSIENT_LOCAL QoS` and `[bridge] Sensor health subscription: TRANSIENT_LOCAL QoS (/fc1/sensor_health)`

## Deviations from Plan

None — plan executed exactly as written. Five changes (A–E) applied surgically. The plan's verify script used `'"subscribed"'` (quoted key) which does not match unquoted JS object literal syntax; the field `subscribed:` is present and verified correctly with an adjusted pattern.

## Known Stubs

None.

## Threat Flags

None. No new network endpoints or auth paths introduced. `/health` is an existing unauthenticated internal endpoint; the two new fields (`ros.connected`, `humidifier.last_msg_ts`) expose no sensitive data beyond what is already served.

## Self-Check: PASSED

- Commit `df9f4b6`: FOUND
- `.planning/phases/16-system-health-panel/16-01-SUMMARY.md`: FOUND
