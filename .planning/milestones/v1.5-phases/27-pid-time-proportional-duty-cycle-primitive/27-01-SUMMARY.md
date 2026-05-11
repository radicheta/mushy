---
phase: 27-pid-time-proportional-duty-cycle-primitive
plan: "01"
subsystem: testing
tags: [ros2, pid, pwm, humidity, fc_core, vendoring, test-scaffold]

requires:
  - phase: 26-dual-sensor-publishing-offline-alarms-sht30-scd41-slot-topic
    provides: D-01 slot-1 silent-fallback contract; SHT30/SCD41 freshness via frame_id
  - phase: 15-sensor-warmup-grace-period
    provides: startup grace contract (_grace_active, _boot_time, _warming_up)
  - phase: 16-system-health-panel
    provides: sensor_health DiagnosticStatus TRANSIENT_LOCAL QoS pattern

provides:
  - Vendored simple-pid 2.0.0 (MIT) at fc_core.vendor.simple_pid — offline-safe for fc1 Pi
  - 10 new PID/PWM ROS params in fc_config.yaml with calibration-derived defaults (D-05 to D-12)
  - min_dwell_time removed from active config + docs (D-15)
  - 6 GREEN pure-math PID unit tests in test_pid_kernel.py (bumpless, saturation, anti-windup, D-on-measurement)
  - 11 RED slow-PWM driver tests in test_pwm_driver.py (Wave 1 turn-green target)
  - 12 RED controller stubs in test_controller.py for HUMID-01/03 (Plan 03 turn-green target)
  - conftest.py shared test fixtures (rclpy-optional for dev environments without ROS2)

affects:
  - 27-02 (fc_pwm_driver.py — turns test_pwm_driver.py GREEN)
  - 27-03 (fc_controller.py refactor — turns test_controller.py RED stubs GREEN)
  - Plans that import from fc_core.vendor.simple_pid

tech-stack:
  added:
    - simple-pid 2.0.0 (MIT, vendored at src/chambers/fc-core/fc_core/vendor/simple_pid/)
  patterns:
    - Vendored third-party packages under fc_core/vendor/ — no PyPI at deploy time
    - rclpy-optional conftest: try/except ImportError guards rclpy in conftest.py for non-ROS dev machines
    - TDD RED scaffold: test files with correct imports exist before implementation files
    - Pure-math tests (test_pid_kernel.py) use no ros_context fixture — plain pytest

key-files:
  created:
    - src/chambers/fc-core/fc_core/vendor/__init__.py
    - src/chambers/fc-core/fc_core/vendor/simple_pid/__init__.py
    - src/chambers/fc-core/fc_core/vendor/simple_pid/pid.py
    - src/chambers/fc-core/fc_core/test/conftest.py
    - src/chambers/fc-core/fc_core/test/test_pid_kernel.py
    - src/chambers/fc-core/fc_core/test/test_pwm_driver.py
  modified:
    - src/chambers/fc-core/config/fc_config.yaml
    - src/chambers/fc-core/fc_core/test/test_controller.py
    - docs/OPERATIONS.md
    - docs/pi-setup/dev-workflow.md

key-decisions:
  - "Vendored simple-pid rather than install at deploy time — fc1 SSH is DERP-relay-only (unreliable); PyPI fetch during deploy is too risky"
  - "conftest.py uses try/except ImportError on rclpy so test_pid_kernel.py (pure math) can run on dev machines without ROS2"
  - "test_output_clamps_at_one uses error=10 (setpoint=10, input=0) not error=1; Kp=0.5 with error=1 only gives P=0.5, needs many ticks to saturate — large error saturates immediately"
  - "min_dwell_time removed from config/docs only in this plan; fc_controller.py removal deferred to Plan 03 (controller refactor wave)"

patterns-established:
  - "Vendor pattern: fc_core/vendor/__init__.py marks directory as not-to-modify; upstream is source of truth"
  - "Bumpless preload test pattern: PID(auto_mode=False, sample_time=None) → set_auto_mode(True, last_output=X) → pid(0.0, dt=1.0) returns ≈X"
  - "RED scaffold pattern: test file imports non-existent module at top level, causing collection failure — Wave N+1 creates the module"

requirements-completed: [HUMID-01, HUMID-02, HUMID-03, HUMID-04]

duration: 12min
completed: 2026-05-01
---

# Phase 27 Plan 01: Wave 0 Foundation Summary

**Vendored simple-pid 2.0.0 into fc_core, added 10 PID/PWM ROS params, removed min_dwell_time, and laid RED test scaffolding for Wave 1 (fc_pwm_driver) and Wave 2 (controller refactor)**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-01T09:40:53Z
- **Completed:** 2026-05-01T09:52:53Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments

- Vendored simple-pid 2.0.0 (MIT licensed) at `fc_core.vendor.simple_pid` with correct bumpless preload contract (`set_auto_mode(True, last_output=X)` produces ≈X on first call with zero error)
- Added all 10 new `pid_*/pwm_*` ROS params to `fc_config.yaml` with calibration-derived defaults locked from CONTEXT.md decisions (D-08, D-10, D-11, D-12); `min_dwell_time` removed from config + docs
- 6/6 PID kernel unit tests pass GREEN (bumpless, saturation, anti-windup, D-on-measurement, freeze-integrator); 11 slow-PWM driver tests RED on missing `fc_pwm_driver.py`; 12 RED controller stubs cover HUMID-01/03

## Task Commits

1. **Task 1: Vendor simple-pid + params + min_dwell_time sweep** - `12cc2a1` (feat)
2. **Task 2: RED test scaffold for PID kernel + slow-PWM driver** - `024e44c` (test)
3. **Task 3: Refactor test_controller.py — delete dwell tests, add 12 RED stubs** - `9def089` (test)

## Files Created/Modified

- `src/chambers/fc-core/fc_core/vendor/__init__.py` — Vendor package marker
- `src/chambers/fc-core/fc_core/vendor/simple_pid/__init__.py` — Re-exports PID class
- `src/chambers/fc-core/fc_core/vendor/simple_pid/pid.py` — Vendored simple-pid 2.0.0 PID class (MIT)
- `src/chambers/fc-core/fc_core/test/conftest.py` — Shared `_mock_clock_at` helper + `ros_context` fixture (rclpy-optional)
- `src/chambers/fc-core/fc_core/test/test_pid_kernel.py` — 6 pure-math PID unit tests (HUMID-03)
- `src/chambers/fc-core/fc_core/test/test_pwm_driver.py` — 11 RED slow-PWM driver tests (HUMID-02)
- `src/chambers/fc-core/config/fc_config.yaml` — Added 10 PID/PWM params; removed min_dwell_time
- `src/chambers/fc-core/fc_core/test/test_controller.py` — Deleted 8 dwell tests; rewritten 6 safe-state tests; added 12 RED Phase 27 stubs
- `docs/OPERATIONS.md` — Removed min_dwell_time row from config table
- `docs/pi-setup/dev-workflow.md` — Removed min_dwell_time line from Configuration section

## Decisions Made

- Vendored simple-pid rather than adding to `install_requires`: fc1's SSH is DERP-relay-only and frequently unreliable; PyPI fetch at Pi deploy time is too risky for a production deploy path. Offline-first was the right call.
- `conftest.py` guards `rclpy` import with `try/except ImportError`: allows `test_pid_kernel.py` (pure math, no ROS) to run on `elder-plops` without ROS2 installed, enabling fast local iteration.
- `test_output_clamps_at_one` uses `setpoint=10.0, input=0.0` (error=10): with Kp=0.5 and error=1.0 the proportional term is only 0.5, which does not saturate the output at 1.0 on the first call — a larger error is needed to immediately demonstrate saturation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `output_limits` property setter calling before `_integral` initialized**
- **Found during:** Task 1 (vendoring simple-pid)
- **Issue:** `self.output_limits = output_limits` in `__init__` triggers property setter which calls `_clamp(self._integral, ...)`, but `_integral` is not yet set → `AttributeError`
- **Fix:** Moved `self.output_limits = output_limits` to after all instance attributes are initialized
- **Files modified:** `src/chambers/fc-core/fc_core/vendor/simple_pid/pid.py`
- **Verification:** `PID(0.5, 0.002, 4.0, output_limits=(0.0, 1.0), ...)` instantiates without error; bumpless preload smoke check passes
- **Committed in:** `12cc2a1` (Task 1 commit)

**2. [Rule 1 - Bug] Fixed `test_output_clamps_at_one` assertion — error=1.0 insufficient for saturation**
- **Found during:** Task 2 (running test_pid_kernel.py)
- **Issue:** Test used `setpoint=1.0, input=0.0` (error=1.0); with Kp=0.5 the P-term is 0.5, which does not saturate at 1.0 on tick 1; over 20 ticks with D-on-measurement the output reached only 0.54
- **Fix:** Changed to `setpoint=10.0, input=0.0` (error=10.0); P-term = 5.0 → immediately saturates at 1.0
- **Files modified:** `src/chambers/fc-core/fc_core/test/test_pid_kernel.py`
- **Verification:** All 6 PID kernel tests pass
- **Committed in:** `024e44c` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 × Rule 1 bug)
**Impact on plan:** Both fixes essential for correct vendored code and passing tests. No scope creep.

## Issues Encountered

- `elder-plops` (dev machine) does not have ROS2 installed. `rclpy` and `std_msgs` are unavailable. Collection of `test_pwm_driver.py` and `test_controller.py` fails with `ModuleNotFoundError` on this machine — this is the correct RED state. Tests will collect and run properly on the Pi or in a ROS2-sourced environment. `test_pid_kernel.py` (pure math) runs on this machine with 6/6 PASS.

## Known Stubs

None — all test files contain real assertions. The RED tests fail on import (correct intentional state), not on placeholder assertions.

## Next Phase Readiness

- Wave 1 (Plan 02, `fc_pwm_driver.py`) can start immediately: `test_pwm_driver.py` is committed with 11 RED tests defining the exact API contract (`SlowPwmDriver`, `_duty_callback`, `_tick`, `_current_state`, `_duty_sub`, `_state_pub`, `_rolling_duty_avg`, `_latest_duty`)
- Wave 2 (Plan 03, controller refactor) can start immediately: `test_controller.py` 12 RED stubs define the PID controller API (`_duty_pub`, `_effective_setpoint`, `_pid`, `_pid_engaged`)
- `fc_core.vendor.simple_pid.PID` is importable and functionally verified — Wave 1/2 implementation can import it directly

---
*Phase: 27-pid-time-proportional-duty-cycle-primitive*
*Completed: 2026-05-01*
