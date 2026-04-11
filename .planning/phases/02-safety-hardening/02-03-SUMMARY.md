---
phase: 02-safety-hardening
plan: 03
subsystem: control
tags: [rolling-median, spike-rejection, humidity, deque, statistics, tdd]

requires:
  - phase: 02-safety-hardening
    plan: 04
    provides: humidifier_pin configurable from fc_config.yaml

provides:
  - Rolling median (5-sample window) spike rejection in humidity_callback
  - self._humidity_buffer deque(maxlen=5) in FruitingChamberController
  - Three tests covering spike rejection, partial buffer, and FIFO behavior

affects:
  - 03-closed-loop-control

tech-stack:
  added: [collections.deque, statistics.median]
  patterns: [receive-side filtering — sensors publish raw truth, controller filters before acting]

key-files:
  created: []
  modified:
    - src/chambers/fc-core/fc_core/fc_controller.py
    - src/chambers/fc-core/fc_core/test/test_controller.py

key-decisions:
  - "Filter lives in controller (receive side), not sensor node — sensors publish raw truth per D-02"
  - "statistics.median handles both odd and even-length sequences correctly"
  - "deque(maxlen=5) provides automatic FIFO eviction without manual length management"

patterns-established:
  - "Sensor spike rejection: deque(maxlen=N) buffer + statistics.median, inserted in callback"

requirements-completed:
  - SENS-05

duration: 3min
completed: 2026-03-30
---

# Phase 02 Plan 03: Humidity Spike Rejection Summary

**5-sample rolling median filter added to humidity_callback via collections.deque + statistics.median, protecting control loop from single-point outlier readings**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-30T18:14:00Z
- **Completed:** 2026-03-30T18:16:44Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Added `from collections import deque` and `from statistics import median` imports to fc_controller.py
- Added `self._humidity_buffer = deque(maxlen=5)` in `__init__` for FIFO window tracking
- Replaced raw assignment in `humidity_callback` with buffer append + median computation
- Control loop now acts on filtered humidity; sensors still publish raw truth on fc/humidity
- Three TDD tests verify spike rejection, partial-buffer median, and FIFO eviction behavior

## Task Commits

TDD flow produced two commits:

1. **RED — failing tests** - `873c4db` (test)
2. **GREEN — rolling median implementation** - `8a151c6` (feat)

## Files Created/Modified

- `src/chambers/fc-core/fc_core/fc_controller.py` - Added deque buffer + median filter in humidity_callback
- `src/chambers/fc-core/fc_core/test/test_controller.py` - Added three new test functions for spike rejection

## Decisions Made

- Used `statistics.median` (stdlib) over manual sort — handles odd/even lengths correctly with no extra dependency
- Filter placed in controller callback (receive side) per D-02: sensors always publish raw truth; controller decides what to act on

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- ROS2 not installed locally; tests run via `docker run ros2-mushy:jazzy`. Pre-existing test failures (`test_temperature_control`, `test_humidity_control`, `test_light_control`) confirmed to predate this plan — they are out-of-scope.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SENS-05 satisfied: humidity spike rejection active on live fc1 data path
- Control loop reads median-filtered humidity; single bad SHT30 reading cannot falsely trigger humidifier
- Ready for Phase 3 closed-loop control plans

---
*Phase: 02-safety-hardening*
*Completed: 2026-03-30*
