---
phase: 30-time-of-day-mode-scheduling
plan: 02
subsystem: bridge
tags: [bridge, allowlist, validator, jest, schedule_windows]

requires:
  - phase: 28
    provides: "control_param.js + control_persist.js + DECLARED_MODES + cp.validate"
  - phase: 30-01
    provides: "fc_core.scheduler validator rules — JS validator mirrors them for defense-in-depth"
provides:
  - "Bridge accepts schedule_windows on POST /control/param (Layer 1 hot edit) — forwards as STRING via SetParameters"
  - "Bridge accepts schedule_windows on POST /control/persist (Layer 2) — round-trips as JSON STRING preserved verbatim"
  - "Defense-in-depth JS validator catches malformed schedules before they cross the rcl boundary"
affects: [phase-30-03, mission-control, farmos]

tech-stack:
  added: []
  patterns:
    - "Bridge JS validator mirrors rclpy validator (T-30-06 = Phase 30 instance of T-28-09 pattern)"

key-files:
  created: []
  modified:
    - src/mission-control/bridge/src/control_param.js
    - src/mission-control/bridge/test/control_param.test.js
    - src/mission-control/bridge/test/control_persist.test.js

key-decisions:
  - "control_persist.js requires zero code changes — cp.validate is the only allowlist gate, and the Phase 28 D-17 mergeOverlay path already writes top-level keys flat under fc_controller.ros__parameters."
  - "JS validator does NOT enforce wraparound semantics — bridge only checks well-formedness; runtime evaluation lives in the controller. This keeps the bridge stateless."
  - "DECLARED_MODES is shared between active_mode + schedule_windows validators — adding new modes is still one edit (D-03 deploy gate preserved)."

patterns-established: []

requirements-completed: [SCHED-01]

duration: ~15min
completed: 2026-05-08
---

# Plan 30-02: Bridge allowlist extension — SUMMARY

**`schedule_windows` now flows through both Layer 1 (hot edit) and Layer 2 (persist) of the Phase 28 two-layer config delivery path. JS validator mirrors the rclpy validator for defense in depth.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2 (allowlist + validator, persist test)
- **Files modified:** 3 (1 source + 2 tests)

## Accomplishments

- `control_param.js` — added `HHMM_RE` constant, `entrySchedule()` validator helper, and `ALLOWLIST['schedule_windows']` entry of type T_STRING.
- `control_param.test.js` — added 13 new tests covering allowlist shape (1) + validate accept/reject cases (12, mirroring scheduler.py rules) + a handler integration test that asserts the STRING wire shape on `/fc_controller/set_parameters`.
- `control_persist.test.js` — added 3 new tests proving Layer 2 round-trip: JSON STRING preserved verbatim, malformed JSON 400 without write, merges with existing overlay.
- **Full bridge jest suite: 188/188 PASS, no regressions.**

## Task Commits

1. **Task 1+2 — allowlist + tests:** `9a6156d`

## Verification

| Check | Status | Evidence |
|---|---|---|
| `npm test -- --testPathPattern=control_param` | **PASS** | 89/89 (existing 76 + 13 new) |
| `npm test` (full bridge suite) | **PASS** | 188/188 across 9 suites |
| Static: `grep "schedule_windows" src/control_param.js` | **PASS (≥2)** | helper + ALLOWLIST entry |

## Self-Check: PASSED

- [x] All tasks executed
- [x] Atomic commit
- [x] SUMMARY.md created
- [x] No regressions in Phase 28/29 tests
- [x] Plan 30-03 can issue Layer 1 + Layer 2 curl pairs against the live bridge

## Notes for Plan 30-03

- Layer 1 happy path: `curl -X POST .../control/param -d '{"node":"fc_controller","param":"schedule_windows","value":"[]"}'` returns 200.
- Layer 2 happy path: `curl -X POST .../control/persist -d '{...same shape...}'` writes `runtime_overrides.yaml` with `schedule_windows: '[]'` (single-quoted JSON string verbatim under `fc_controller.ros__parameters`).
- Validator error messages contain the offending value (e.g. `schedule_windows[0].start: must be HH:MM (got "6:00")`) — useful for SMOKE.md evidence.
