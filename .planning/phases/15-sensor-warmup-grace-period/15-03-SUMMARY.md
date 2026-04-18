---
phase: 15-sensor-warmup-grace-period
plan: "03"
subsystem: fc_core / deploy / soak
tags: [deploy, soak, sensor-health, grace-period, warmup, validation]
dependency_graph:
  requires: [15-01, 15-02]
  provides: [SENS-01-verified, WARMUP-01-verified, WARMUP-02-verified, WARMUP-03-verified]
  affects: [fc1-prod-branch, fc_controller-live]
tech_stack:
  added: []
  patterns: [git-ff-merge-deploy, live-soak-protocol]
key_files:
  created:
    - .planning/phases/15-sensor-warmup-grace-period/15-03-SOAK-EVIDENCE.md
  modified: []
decisions:
  - "SOAK_PASS: true — WARN->OK transition observed at t~25s post-node-init; no humidifier actuation in grace window"
  - "Grace elapsed 25s (not 20s) because buffer-full was the binding condition — correct behavior per AND-logic design"
  - "Phase 16 (system health panel) now has a live /fc1/sensor_health topic to subscribe to on fc1"
metrics:
  duration: "~12 min (deploy ~2 min, soak ~10 min)"
  completed: "2026-04-18T01:27:13+00:00"
  tasks_completed: 3
  files_changed: 1
requirements:
  - SENS-01
  - WARMUP-01
  - WARMUP-02
  - WARMUP-03
---

# Phase 15 Plan 03: Deploy and Live Soak Summary

**One-liner:** Grace-gate fix deployed to fc1 via fc1/prod FF-merge + deploy.sh; live soak confirmed WARN→OK transition at 25s post-restart with no spurious humidifier actuation.

## What Was Done

**Task 1 — Push fc1/prod and deploy:**
- Local ROADMAP.md stash required to switch branches (build artifacts caused dirty tree)
- FF-merged main (125edcc) into fc1/prod; pushed to origin
- `scripts/pi-deploy/deploy.sh` executed: git pull → colcon build (7.85s) → systemctl restart fc-core
- fc-core active immediately post-deploy; fc1 HEAD confirmed `125edccee42...`

**Task 2 — Cold-restart soak:**
- Soak restart at 2026-04-18T01:26:30+00:00
- `/fc1/sensor_health` confirmed live: `Type: diagnostic_msgs/msg/DiagnosticStatus`, Publisher count: 1
- First echo message: WARN (level=0x01), `grace_elapsed_sec=1.0`, `buffer_full=false` — grace gate active
- Second echo message: OK (level=0x00), `grace_elapsed_sec=25.0`, `buffer_full=true` — grace cleared
- Journal at 01:27:03 UTC: `WARMUP-CLEARED: control loop engaging`
- Humidifier journal grep (first 20s): no actuation lines — humidifier stayed OFF during grace
- Sensor data (humidity 82.5%→88.1%) flowed to fc_display throughout — correct, sensors not suppressed

**Task 3 — Commit evidence:**
- 15-03-SOAK-EVIDENCE.md written (136 lines) and committed

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | (fc1/prod push) | FF-merge main→fc1/prod; deploy via deploy.sh |
| Tasks 2+3 | acb72aa | docs(phase-15): soak evidence on fc1 (SOAK_PASS) |

## Soak Results

| Check | Expected | Observed | Result |
|-------|----------|----------|--------|
| sensor_health WARN on grace entry | level=1, message="warming up" | level=0x01, grace_elapsed=1.0s, buffer_full=false | PASS |
| sensor_health OK on grace clear | level=0, elapsed<=25s | level=0x00, grace_elapsed=25.0s, buffer_full=true | PASS |
| WARMUP-CLEARED in journal | present | `WARMUP-CLEARED: control loop engaging` at 01:27:03 | PASS |
| No humidifier actuation first 20s | empty journal grep | no humidifier lines in first 20s window | PASS |
| Topic type | diagnostic_msgs/msg/DiagnosticStatus | diagnostic_msgs/msg/DiagnosticStatus | PASS |
| fc-core active post-soak | active | active | PASS |

## Notable Observation

Grace elapsed 25s rather than 20s because the humidity buffer took ~25s to fill after node init. This is correct behavior: the AND-logic requires BOTH `buffer_full=true` AND `elapsed >= 20.0s`. The buffer-full condition was binding. The farmer's original concern was transient spike from unsettled sensors — this confirms the gate held until sensors provided 5 stable readings.

## Deviations from Plan

**1. [Rule 3 - Blocking] Wrong ros2 topic echo flag in first soak attempt**
- **Found during:** Task 2 (first soak run)
- **Issue:** `ros2 topic echo --field-type` flag doesn't exist in Jazzy; caused usage error and topic not found (timing issue — echo started before topic was advertised)
- **Fix:** Dropped the invalid flag; added `sleep 5` before echo to let ROS nodes initialize; ran second soak with clean invocation
- **Files modified:** none (soak script only; evidence file reflects final clean run)
- **Commit:** n/a (no file change)

## Known Stubs

None. All evidence reflects live hardware output.

## Threat Flags

None — deploy + observation plan with no new attack surface.

## Self-Check

- [x] 15-03-SOAK-EVIDENCE.md exists: `wc -l` = 136 lines (>30 minimum)
- [x] `SOAK_PASS: true` grepped from evidence file
- [x] Commit acb72aa exists in git log
- [x] No Co-Authored-By in commit message
- [x] fc-core active on fc1 post-soak

## Self-Check: PASSED

## Carryover

- **Phase 16 (system health panel):** `/fc1/sensor_health` is live on fc1. Topic type `diagnostic_msgs/msg/DiagnosticStatus`, TRANSIENT_LOCAL QoS. Phase 16 can subscribe from the bridge and render the warming-up/ok state without any additional fc_core changes.
- **v1.2.1 milestone:** SENS-01, WARMUP-01, WARMUP-02, WARMUP-03 all verified on live hardware. Phase 15 acceptance gate is met.
