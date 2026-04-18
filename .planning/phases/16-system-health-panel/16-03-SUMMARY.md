---
phase: 16-system-health-panel
plan: 03
subsystem: mission-control-frontend
tags: [smoke-test, evidence, health-panel, openmct]
dependency_graph:
  requires: [16-01, 16-02]
  provides: [16-SMOKE-EVIDENCE.md, phase-16-closure]
  affects: []
tech_stack:
  added: []
  patterns: [automated-smoke-evidence, per-light-state-evaluation]
key_files:
  created:
    - .planning/phases/16-system-health-panel/16-SMOKE-EVIDENCE.md
  modified: []
decisions:
  - "SMOKE_PASS: true — all 6 lights have labels in asset, live data sources, and computable states"
  - "sensor_health WS gap is expected behavior (transition-only publish + TRANSIENT_LOCAL) — documented in evidence, not a failure"
  - "Humidifier cycling confirmed via successive /health polls showing updating timestamps"
metrics:
  duration: ~15min
  completed: 2026-04-18
  tasks_completed: 1
  files_modified: 1
---

# Phase 16 Plan 03: System Health Panel Smoke Test Summary

Automated smoke test confirming the six-light health strip shipped in Plans 16-01 and 16-02 is correctly wired to live data on the elder-plops stack. All automated pass criteria met; SMOKE_PASS: true.

## What Was Done

Ran the full suite of automated checks against the live stack (no code changes):

1. Verified container state — bridge and openmct running with freshly rebuilt images (Plan 16-02 deploy)
2. Confirmed `/health` JSON has all required new fields: `ros.connected`, `humidifier.last_msg_ts`, `camera.last_frame_age_sec`, `camera.subscribed`
3. Confirmed served `plugin.js` has 12 `makeStatusLight` instances (threshold: >=10) and all six label strings present
4. Verified sensor_health ROS topic directly on fc1 (ROS_DOMAIN_ID=69) — level=0 OK, buffer_full=true, warmup cleared
5. Captured 15s of WebSocket stream — humidifier, temperature, humidity, CO2 all flowing; sensor_health not received (expected — transition-only publish cadence)
6. Confirmed bridge logs show "Sensor health subscription" startup line, no errors
7. Evaluated all 6 lights to computed states based on live signal values

## Per-Light Results

| Light | State | Signal | Value |
|-------|-------|--------|-------|
| Sensors | GREEN | ROS /fc1/sensor_health level=0 | OK, buffer_full=true, grace cleared |
| Camera feed | GREY | /health camera.subscribed=false | No active viewer (expected) |
| Humidifier | GREEN | /health humidifier.last_msg_ts | age=4.7s < 30s threshold |
| Bridge | GREEN | HTTP /health | 200 OK |
| Pi reachable | GREEN | /health ros.connected | true |
| Grace | GREEN | ROS /fc1/sensor_health level=0 | grace_elapsed(25s) > grace_total(20s) |

## Container Image IDs

- bridge: `sha256:8306006564d86a5feef7dbd963f1fcb71aec622024a99162089bceb08795ac76`
- openmct: `sha256:7545f826bf377baafb0a5c2a6e4b2b5dc2776d67cf57443050740f76c00e17c7`

## Unexpected Behaviors

**sensor_health not seen in WS capture window** — Not a failure. `fc_controller` publishes `sensor_health` only at state transitions (warmup start / warmup end). Bridge subscribes with TRANSIENT_LOCAL QoS at startup, receives the last message, but no WS clients are connected at that moment. Subsequent WS clients miss it until the next transition. The light correctly goes GREY (gap-over-noise) until the next sensor_health message arrives. This matches the design intent.

**Follow-up idea:** cache last `sensor_health` payload in bridge memory and replay to new WS clients on connect. Would eliminate the gap and make the Sensors/Grace lights immediately green on page load rather than grey until the next transition. Low effort, meaningful UX improvement.

## Commit

`da1b82e` — `docs(16): smoke evidence for system health panel`
- 1 file created: `.planning/phases/16-system-health-panel/16-SMOKE-EVIDENCE.md`
- No Co-Authored-By trailer

## Deviations from Plan

None — plan executed exactly as written. WS capture attempted exactly as specified; websocat absence handled per plan fallback (documented in evidence file).

## Known Stubs

None.

## Threat Flags

None. This plan creates no code, no endpoints, no schema changes.

## Self-Check: PASSED

- `.planning/phases/16-system-health-panel/16-SMOKE-EVIDENCE.md` — FOUND
- `grep -E '^SMOKE_PASS: (true|false)'` returns 2 lines (both `SMOKE_PASS: true`) — PASS
- Commit `da1b82e` — FOUND
- No Co-Authored-By trailer — CONFIRMED
