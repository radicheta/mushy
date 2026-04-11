---
phase: 05-production-deployment
plan: "01"
subsystem: infra
tags: [ros2, raspberry-pi, systemd, humidity-control, operations-docs, grower-handoff]

# Dependency graph
requires:
  - phase: 04-observability-integration
    provides: fc-core service running on FC-1, deploy pipeline proven, OpenMCT dashboard live
  - phase: 06-wireguard-vpn-routing-for-ros-traffic
    provides: WireGuard VPN for remote access, CycloneDDS over wg0
provides:
  - Production fc_config.yaml with target_humidity 0.80 (75-85% operational band)
  - OPERATIONS.md developer reference with 7-section layout
  - FC1-GROWER-CHECKLIST.md printable grower handoff document
affects: [soak-test, grower-handoff, production-deployment]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Ops doc pattern: OPERATIONS.md (developer) + printable checklist (grower) — two-tier for different audiences"
    - "Config change pattern: edit fc_config.yaml in repo -> deploy.sh, never edit on Pi directly"

key-files:
  created:
    - docs/OPERATIONS.md
    - docs/FC1-GROWER-CHECKLIST.md
  modified:
    - src/chambers/fc-core/config/fc_config.yaml
    - src/chambers/fc-core/fc_core/test/test_controller.py

key-decisions:
  - "target_humidity updated to 0.80 per D-01 — 80% setpoint, ±5% tolerance gives 75-85% operational band"
  - "Two-tier operations docs: OPERATIONS.md for developers (SSH, journalctl, deploy.sh), grower checklist for non-technical farmer (no CLI jargon)"

patterns-established:
  - "Grower checklist: symptom-first table format, plain language, no ROS2/systemctl/SSH terminology"
  - "OPERATIONS.md: 7-section layout with symptom-first H3 recovery procedures"

requirements-completed: [DEPL-01]

# Metrics
duration: 15min
completed: 2026-04-05
---

# Phase 05 Plan 01: Production Config and Grower Handoff Docs Summary

**Production fc_config.yaml set to 80% humidity target, OPERATIONS.md developer reference and FC1-GROWER-CHECKLIST.md grower printable created — all deployment artifacts ready for soak test**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-05T22:43:00Z
- **Completed:** 2026-04-05T22:58:05Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Updated `target_humidity` from 0.75 to 0.80 in `fc_config.yaml` per D-01; all 20 tests pass
- Created `docs/OPERATIONS.md` with 7-section developer reference: overview, architecture diagram, full config table, deploy procedure, 5 recovery subsections (symptom-first), monitoring, known limitations
- Created `docs/FC1-GROWER-CHECKLIST.md` printable 1-page grower handoff with 5 symptom/action pairs, plain language, no ROS2 terminology, black-and-white compatible

## Task Commits

1. **Task 1: Update target_humidity to 0.80 and verify tests pass** - `b8ac039` (feat)
2. **Task 2: Create OPERATIONS.md developer reference** - `05f95c7` (feat)
3. **Task 3: Create grower printable checklist** - `f44ce7c` (feat)

## Files Created/Modified

- `src/chambers/fc-core/config/fc_config.yaml` — target_humidity changed 0.75 → 0.80 per D-01
- `src/chambers/fc-core/fc_core/test/test_controller.py` — fixed pre-existing test_light_control bug
- `docs/OPERATIONS.md` — developer reference guide with 7 sections per UI-SPEC layout contract
- `docs/FC1-GROWER-CHECKLIST.md` — grower printable checklist with 5 symptom/action pairs

## Decisions Made

- target_humidity set to 0.80 per D-01: 80% setpoint, ±5% tolerance = 75-85% operational band. humidity_tolerance (0.05) and min_dwell_time (300.0) unchanged per D-01 and D-03.
- Two-tier doc format confirmed: OPERATIONS.md uses SSH/journalctl/systemctl commands for developer audience; grower checklist uses zero CLI jargon, symptom-first plain language for farmer near the chamber.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pre-existing test_light_control failure**
- **Found during:** Task 1 (running test suite to verify config change)
- **Issue:** `test_light_control` used non-existent `node.set_parameter('light_start_hour', 6)` (no such API on ROS2 Node). Test had been silently broken. Also patched `datetime.datetime` instead of `fc_core.fc_controller.datetime` (wrong import site), so `should_light_be_on()` always saw real clock.
- **Fix:** Removed invalid `set_parameter()` calls (defaults at init are already correct for the test). Fixed datetime patch target to `fc_core.fc_controller.datetime`.
- **Files modified:** `src/chambers/fc-core/fc_core/test/test_controller.py`
- **Verification:** All 20 tests pass (was 19/20 before fix).
- **Committed in:** `b8ac039` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - pre-existing test bug)
**Impact on plan:** Fix was necessary to meet acceptance criteria (pytest exits 0 with all tests passing). No scope creep — test logic unchanged, only the broken mock API calls repaired.

## Issues Encountered

- ROS2 not installed in worktree environment — ran tests via `ros2-mushy:jazzy` Docker image (same image used throughout the project). No impact on outcome.

## User Setup Required

None — no external service configuration required. Physical Pi relocation to farm and soak test start are human gates tracked in `04-HUMAN-UAT.md`, gated by D-06.

## Next Phase Readiness

- Production config ready to deploy: `./scripts/pi-deploy/deploy.sh` from repo root
- OPERATIONS.md and grower checklist ready to hand off
- Remaining Phase 5 gate: physical Pi relocation to farm, then 24-hour soak test (D-04, D-06)
- After soak: verify `NRestarts` count via `ssh fc1 'sudo systemctl show fc-core --property=NRestarts'`

## Known Stubs

None — all documents are complete with production values. The only placeholder is "Pi location: [Fill in after installation at farm]" in the grower checklist, which is intentional (location is unknown until physical install).

---
*Phase: 05-production-deployment*
*Completed: 2026-04-05*
