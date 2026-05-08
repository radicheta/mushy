---
phase: 29
plan: 02
subsystem: mission-control-bridge
tags:
  - bridge
  - ros-subscription
  - websocket
  - transient-local
dependency-graph:
  requires:
    - 29-01 (Mode.msg + controller-side TRANSIENT_LOCAL publishers on /fc1/control/current_mode, /fc1/control/alerter_mode_overrides, /fc1/control/alerter_globals)
  provides:
    - WS envelopes {current_mode}, {alerter_overrides}, {alerter_globals} broadcast to all connected clients with on-connect replay (≤2s after bridge start) — consumed by Wave 2 alerter (29-04/29-05).
  affects:
    - mission-control-bridge image (rebuild required on deploy)
tech-stack:
  added: []
  patterns:
    - "Module-scope cache var + on-connect replay (extends Phase 16.1 sensor_health pattern to mode/alerter envelopes)."
    - "JSON-in-String topic with try/catch parse-and-drop (avoids second fc_msgs build cycle for alerter Tier B/C config)."
key-files:
  created: []
  modified:
    - src/mission-control/bridge/src/index.js (+90 lines: 3 cache decls, 3 on-connect replay sends, 3 createSubscription blocks)
decisions:
  - "Reused existing humidifierQos (TRANSIENT_LOCAL/RELIABLE/depth=1) for all 3 new subs — matches D-01/D-06 publisher QoS contract."
  - "Did NOT collapse pre-existing humidifierQos vs sensorHealthQos duplication despite RESEARCH §Anti-Patterns flagging it — out of scope per plan §Action step 4."
  - "JSON-in-String for alerter_mode_overrides + alerter_globals avoids a second fc_msgs build; controller is co-managed code so payload-tampering threat (T-29-06) accepted."
  - "Explicit Number.isFinite(msg.t_target) coercion (Pitfall 5) — documented in code comment to prevent reintroduction of implicit NaN→null footgun."
metrics:
  duration: ~10 min
  completed: 2026-05-08
---

# Phase 29 Plan 02: Bridge mode + alerter-config WS plumbing — Summary

**One-liner:** Added 3 TRANSIENT_LOCAL ROS subscriptions in mission-control bridge for `current_mode`, `alerter_mode_overrides`, and `alerter_globals`, broadcasting each as a typed WS envelope with on-connect replay so the alerter (Wave 2) sees current state within one handshake of cold start.

## What shipped

- 3 new `node.createSubscription(...)` calls in `bridge/src/index.js` co-located with the existing `sensor_health` block (after line 846):
  - `/fc1/control/current_mode` — `fc_msgs/msg/Mode`, full field-by-field projection, NaN-safe `t_target`.
  - `/fc1/control/alerter_mode_overrides` — `std_msgs/msg/String`, JSON-parsed inside try/catch.
  - `/fc1/control/alerter_globals` — `std_msgs/msg/String`, JSON-parsed inside try/catch.
- 3 new module-scope cache vars next to `lastSensorHealthBroadcast`:
  - `lastModeBroadcast`, `lastAlerterModeOverridesBroadcast`, `lastAlerterGlobalsBroadcast`.
- 3 new on-connect replay sends in `wss.on('connection', ...)` — guarded by `ws.readyState === WebSocket.OPEN`.
- All 3 subs reuse existing `humidifierQos` (TRANSIENT_LOCAL/RELIABLE/depth=1).
- Malformed JSON payloads on the two String topics: warn-log + drop (no broadcast of garbage).

## Verification

- `node -c src/mission-control/bridge/src/index.js` → parses cleanly.
- Acceptance greps:
  - `lastModeBroadcast` count = 4 (≥3 required).
  - `lastAlerterModeOverridesBroadcast` count = 4 (≥3 required).
  - `lastAlerterGlobalsBroadcast` count = 4 (≥3 required).
  - `/fc1/control/current_mode` count = 3 (≥1 required).
  - `/fc1/control/alerter_mode_overrides` count = 2 (≥1 required).
  - `/fc1/control/alerter_globals` count = 2 (≥1 required).
  - `humidifierQos` count = 8 (≥4 required).
  - `fc_msgs/msg/Mode` count = 1 (≥1 required).
- `npx jest` in bridge: **125/125 tests passed**, 0 regressions. (Two test suites fail to *load* due to pre-existing missing modules `js-yaml` and `jimp` — confirmed identical failure before and after this change via `git stash` round-trip; out of scope per executor scope boundary.)

## Smoke test

Bridge image was NOT rebuilt or deployed in this plan — that lands in plan 29-07 (on-host fc1 smoke). The `[mode_update]`-within-2s USER-OBSERVABLE truth is verifiable there.

## Deviations from Plan

None. Plan executed exactly as written.

## Deferred Issues

- Pre-existing bridge jest infrastructure: `test/control_persist.test.js` and `test/burn_bar.test.js` cannot load due to missing `js-yaml` and `jimp` deps. Pre-existing on the base commit (657232f). Not blocking; 125 actual tests pass.
- Pre-existing duplicate QoS profile (`humidifierQos` vs `sensorHealthQos`) — flagged in 29-RESEARCH §Anti-Patterns; intentionally left untouched per plan §Action step 4 to keep blast radius minimal.

## Commits

- `a909961` feat(29-02): add bridge ROS subs for mode + alerter Tier B/C config

## Self-Check: PASSED

- File `src/mission-control/bridge/src/index.js` exists and modified: FOUND.
- Commit `a909961` exists in git log: FOUND.
- All acceptance grep counts pass.
- `node -c` parses cleanly.
- jest baseline (125 passed) preserved.
