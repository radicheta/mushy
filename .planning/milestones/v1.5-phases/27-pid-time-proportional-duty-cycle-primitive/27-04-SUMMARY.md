---
phase: 27-pid-time-proportional-duty-cycle-primitive
plan: "04"
subsystem: mission_control_bridge
tags: [bridge, mission-control, telemetry, ros2, pid, float32, transient-local]
dependency_graph:
  requires:
    - phase: 27-03
      provides: fc_controller publishes fc1/actuators/humidifier_duty, fc1/control/humidity_target, fc1/control/pid_output (all Float32, TRANSIENT_LOCAL)
  provides:
    - bridge subscribes to fc1/actuators/humidifier_duty -> WS broadcast + TimescaleDB (fc.humidifier_duty)
    - bridge subscribes to fc1/control/humidity_target -> WS broadcast + TimescaleDB (fc.humidity_target)
    - bridge subscribes to fc1/control/pid_output -> WS broadcast + TimescaleDB (fc.pid_output)
    - ALLOWED_TOPICS includes all three new topics for history queries
  affects: [27-05-deploy, openmct-charts, farmos-ui]

tech-stack:
  added: []
  patterns:
    - Float32 subscription reusing humidifierQos (TRANSIENT_LOCAL keep-last-1 reliable) — same as humidifier-Bool path
    - latestTelemetry slot + WS broadcast + insertTelemetry per subscription (established bridge pattern)
    - ALLOWED_TOPICS allowlist extended for SQL injection prevention (T-07-04)

key-files:
  created: []
  modified:
    - src/mission-control/bridge/src/index.js

key-decisions:
  - "Three topics wired instead of one per additional_requirement directive: farmer needs duty + setpoint + raw PID output side-by-side in OpenMCT for tuning sanity checks"
  - "humidifierQos reused for all three (not redeclared) — TRANSIENT_LOCAL matches fc_controller publishers per Pitfall 5 in RESEARCH.md"
  - "Duty value passed verbatim (0.0-1.0), no rescale per D-02 — operator overlay depends on raw 0-1 scale"

metrics:
  duration: 10min
  completed: "2026-05-01"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
---

# Phase 27 Plan 04: Bridge Telemetry Wiring Summary

**Three PID telemetry topics (humidifier_duty, humidity_target, pid_output) wired through the Mission Control bridge via TRANSIENT_LOCAL Float32 subscriptions with WebSocket broadcast and TimescaleDB insert**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-05-01
- **Tasks:** 1/1
- **Files modified:** 1

## Accomplishments

- Added `fc.humidifier_duty`, `fc.humidity_target`, `fc.pid_output` to `ALLOWED_TOPICS` (SQL injection guard for history endpoint)
- Subscribed to `/fc1/actuators/humidifier_duty` (Float32, TRANSIENT_LOCAL via reused `humidifierQos`): value passed verbatim 0.0–1.0, no rescale (D-02); WS broadcast as `{ humidifier_duty, timestamp }` + `insertTelemetry('fc.humidifier_duty', value)` + `latestTelemetry.humidifier_duty` slot
- Subscribed to `/fc1/control/humidity_target` (Float32, TRANSIENT_LOCAL): effective post-ramp setpoint; WS + DB + latestTelemetry
- Subscribed to `/fc1/control/pid_output` (Float32, TRANSIENT_LOCAL): raw PID output pre-clamp; WS + DB + latestTelemetry
- `qos: humidifierQos` used 4× total (original humidifier-Bool + 3 new); `humidifierQos` declared exactly once
- `node --check` passes; syntax clean

## Task Commits

1. **Task 1: Wire three PID telemetry topics through bridge** - `3f73e73` (feat)

## Files Created/Modified

- `src/mission-control/bridge/src/index.js` — ALLOWED_TOPICS extended + 3 new Float32 subscriptions added after humidifier-Bool block (lines 347, 702–752)

## Decisions Made

- Wired all three topics (`humidifier_duty`, `humidity_target`, `pid_output`) per `additional_requirement` directive. Plan 27-04 spec only mentioned `humidifier_duty`; the other two were published by Plan 27-03 and required for the farmer's PID tuning overlay in OpenMCT.
- Reused `humidifierQos` for all three subscriptions. TRANSIENT_LOCAL keep-last-1 reliable matches the fc_controller publishers (RESEARCH §Pitfall 5). No new QoS object declared.
- Duty value is NOT rescaled to 0–100%. The `* 100` on `relative_humidity` (humidity subscription at line 612) is for SI fraction → percent conversion. Duty is already a dimensionless ratio by design (D-02).

## Deviations from Plan

### Auto-fixed Issues

**1. [Additional Requirement] Two extra telemetry topics beyond plan spec**
- **Found during:** Task 1 start (additional_requirement in prompt)
- **Issue:** Plan 27-04 spec only wired `fc1/actuators/humidifier_duty`. Plan 27-03 added two additional telemetry publishers (`fc1/control/humidity_target` and `fc1/control/pid_output`) per its own additional_requirement. Without wiring all three, the farmer's OpenMCT PID tuning view (duty + setpoint + raw output overlay) would be incomplete.
- **Fix:** Added subscriptions for `/fc1/control/humidity_target` and `/fc1/control/pid_output` using the same TRANSIENT_LOCAL QoS pattern. Both added to ALLOWED_TOPICS, latestTelemetry, WS broadcast, and TimescaleDB insert paths.
- **Files modified:** `src/mission-control/bridge/src/index.js`
- **Commit:** 3f73e73

## Known Stubs

None. All three subscriptions are wired to real ROS topics published by fc_controller (verified in 27-03-SUMMARY.md). No placeholder values.

## Threat Flags

No new trust boundaries introduced. The three new subscriptions follow the identical trust model as the existing humidifier-Bool subscription:
- ROS bus → bridge: same tailnet, same fc_controller publisher, same TRANSIENT_LOCAL QoS
- Bridge → WebSocket clients: same WS trust model, CORS_ORIGIN-gated
- Bridge → TimescaleDB: new topic strings in the existing `telemetry` hypertable; no schema migration required

STRIDE dispositions: same as T-27-04-01/02/03 in plan threat register (accept / accept / accept for T, I, D respectively). `pid_output` exposes internal PID computation state — operational tuning data, not secrets.

## Self-Check: PASSED

- `src/mission-control/bridge/src/index.js` exists and modified
- Commit 3f73e73 present in git log
- `node --check` passes (syntax valid)
- All acceptance criteria from plan verified:
  - `grep -c "'fc.humidifier_duty'"` → 2 (ALLOWED_TOPICS + insertTelemetry)
  - `grep -c "/fc1/actuators/humidifier_duty"` → 1
  - `grep -c "std_msgs/msg/Float32"` → 4 (co2 + 3 new)
  - `grep -c "qos: humidifierQos"` → 4 (humidifier-Bool + 3 new)
  - `grep -c "humidifierQos\s*="` → 1 (not redeclared)
  - No `humidifier_duty * 100` rescale
  - Startup log line present for all three subscriptions

---
*Phase: 27-pid-time-proportional-duty-cycle-primitive*
*Completed: 2026-05-01*
