---
phase: 03-closed-loop-control
verified: 2026-04-04T20:00:00Z
status: human_needed
score: 5/5 must-haves verified
human_verification:
  - test: "Run full test suite: PYENV_VERSION=3.11.12 pytest src/chambers/fc-core/fc_core/test/test_controller.py -v (requires ROS2 Jazzy installed)"
    expected: "17/19 tests pass. test_temperature_control and test_light_control fail — pre-existing failures documented in Plans 02 and 03 summaries, out of phase 3 scope. All 13 phase-3-relevant tests pass."
    why_human: "ROS2/rclpy is not installed on the verification host. Cannot import test module without ROS2 environment."
  - test: "Confirm main() shutdown path: note that fc_controller.py line 241 references get_parameter('simulation_mode') but the declared param is 'actuator_simulation_mode'. Run ros2 run fc_core fc_controller on Pi with actuator_simulation_mode: false and interrupt — verify no ParameterNotDeclaredException on exit."
    expected: "Either the bug is benign (simulation_mode always True during testing) or it surfaces as a runtime exception on hardware shutdown. Should be filed as a defect for Phase 4."
    why_human: "Pre-existing bug in main() cleanup path only fires on non-simulation hardware shutdown — untestable without the Pi."
---

# Phase 3: Closed-Loop Control Verification Report

**Phase Goal:** Control algorithm is complete and correct — maintains setpoint, won't damage the actuator, and fails safe when sensor data is missing or stale.
**Verified:** 2026-04-04T20:00:00Z
**Status:** human_needed (all code checks passed; test execution blocked by missing ROS2 environment on verifier host)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | Humidifier turns ON below lower threshold, OFF above upper threshold | ✓ VERIFIED | control_loop lines 217-220 implement bang-bang via `_set_humidifier_with_dwell`; `test_humidity_control` exercises ON/OFF path with clock mocking |
| 2  | Setpoint and deadband thresholds configurable in fc_config.yaml | ✓ VERIFIED | `target_humidity: 0.85`, `humidity_tolerance: 0.05` in fc_config.yaml; referenced via `get_parameter()` in control_loop |
| 3  | Humidifier cannot cycle faster than min_dwell_time | ✓ VERIFIED | `_set_humidifier_with_dwell` method at fc_controller.py:133-153; 4 dwell tests present in test_controller.py |
| 4  | Stale sensor data triggers humidifier OFF | ✓ VERIFIED | Staleness guard at fc_controller.py:182-209; `sensor_stale_timeout` param read; 5 staleness tests present |
| 5  | Sensor failure drives humidifier OFF, not frozen last state | ✓ VERIFIED | None-check at fc_controller.py:177-179 calls `set_humidifier(False)` before return; `test_none_humidity_safe_state` and `test_none_temp_safe_state` test this |

**Score:** 5/5 truths verified

---

## Required Artifacts

### Plan 01 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/chambers/fc-core/fc_core/fc_controller.py` | New params declared, None-check calls set_humidifier(False), instance vars initialized | ✓ VERIFIED | Line 33: `('min_dwell_time', 300.0)`, Line 34: `('sensor_stale_timeout', 10.0)`, Lines 87-89: all three instance vars; Line 178: `set_humidifier(False)` in None-check |
| `src/chambers/fc-core/config/fc_config.yaml` | min_dwell_time and sensor_stale_timeout config entries | ✓ VERIFIED | Lines 36-37: `min_dwell_time: 300.0` and `sensor_stale_timeout: 10.0` under "Safety guards" comment |
| `src/chambers/fc-core/fc_core/test/test_controller.py` | Tests for new params and None-humidity safe state | ✓ VERIFIED | `test_new_params_declared` at line 149, `test_none_humidity_safe_state` at line 157, `test_none_temp_safe_state` at line 168 |

### Plan 02 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/chambers/fc-core/fc_core/fc_controller.py` | `_set_humidifier_with_dwell` method, dwell guard in control_loop | ✓ VERIFIED | Method defined at lines 133-153; bang-bang calls route through it at lines 218, 220; None-check retains direct `set_humidifier(False)` at line 178 |
| `src/chambers/fc-core/fc_core/test/test_controller.py` | Dwell time tests | ✓ VERIFIED | All 4 required tests present: `test_dwell_time_blocks_toggle`, `test_dwell_time_allows_toggle_after_wait`, `test_dwell_time_first_toggle_always_allowed`, `test_dwell_time_applies_both_directions` |

### Plan 03 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/chambers/fc-core/fc_core/fc_controller.py` | Staleness check in control_loop, timestamp in humidity_callback, log dedup | ✓ VERIFIED | `_last_humidity_timestamp = self.get_clock().now()` at line 105; staleness guard at lines 182-214; `Sensor data stale` warn at line 206; `Fresh sensor data received` info at line 214; `_safe_state_active` flag at lines 203-213 |
| `src/chambers/fc-core/fc_core/test/test_controller.py` | Staleness and recovery tests | ✓ VERIFIED | All 5 required tests present: `test_sensor_staleness`, `test_safe_state_recovery`, `test_staleness_log_deduplication`, `test_safe_state_updates_dwell_toggle`, `test_fresh_data_not_stale` |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| fc_controller.py declare_parameters | fc_config.yaml | ROS2 parameter loading | ✓ WIRED | `('min_dwell_time', 300.0)` and `('sensor_stale_timeout', 10.0)` in declare_parameters; matching entries in yaml |
| fc_controller.py control_loop None-check | set_humidifier(False) | Direct call on sensor absence | ✓ WIRED | Line 178: `self.set_humidifier(False)` before return when temp or humidity is None |
| fc_controller.py control_loop bang-bang | _set_humidifier_with_dwell | bang-bang calls routed through dwell guard | ✓ WIRED | Lines 218-220: both ON and OFF bang-bang calls use `_set_humidifier_with_dwell` |
| _set_humidifier_with_dwell | set_humidifier(state) | dwell check passes | ✓ WIRED | Line 152: `self.set_humidifier(state)` after dwell check passes |
| fc_controller.py humidity_callback | _last_humidity_timestamp | self.get_clock().now() on each message | ✓ WIRED | Line 105: `self._last_humidity_timestamp = self.get_clock().now()` after median computation |
| fc_controller.py control_loop staleness check | set_humidifier(False) | elapsed > sensor_stale_timeout | ✓ WIRED | Line 208: `self.set_humidifier(False)` in stale block; line 187 computes elapsed against sensor_stale_timeout |
| fc_controller.py control_loop staleness | _safe_state_active flag | log on transition only | ✓ WIRED | Lines 203-204: flag set True on entry; lines 212-213: flag cleared on recovery |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| fc_controller.py control_loop | `self.current_humidity` | `humidity_callback` → median of `_humidity_buffer` | Yes — populated by ROS2 subscriber callback | ✓ FLOWING |
| fc_controller.py control_loop | `self._last_humidity_timestamp` | `humidity_callback` → `self.get_clock().now()` | Yes — ROS2 clock stamp on each message | ✓ FLOWING |
| fc_controller.py _set_humidifier_with_dwell | `self._last_humidifier_toggle` | Updated on state change via `self.get_clock().now()` | Yes — set at lines 153 and 209 | ✓ FLOWING |
| fc_controller.py control_loop | `stale` boolean | `elapsed_sec > sensor_stale_timeout` | Yes — derived from real timestamp arithmetic | ✓ FLOWING |

---

## Behavioral Spot-Checks

Step 7b: SKIPPED — ROS2 is not installed on this host. All behaviors require `rclpy` which is only available in the ROS2 Jazzy environment on the Pi or a machine with ROS2 installed. Routed to human verification above.

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CTRL-01 | 03-01 | Closed-loop bang-bang control maintains humidity setpoint with hysteresis | ✓ SATISFIED | Bang-bang logic at fc_controller.py:217-220; `target_humidity` and `humidity_tolerance` params; `test_humidity_control` exercises full ON/OFF cycle |
| CTRL-02 | 03-01 | Setpoint and deadband configurable via fc_config.yaml | ✓ SATISFIED | `target_humidity: 0.85`, `humidity_tolerance: 0.05` in fc_config.yaml; read via `get_parameter()` calls at control time |
| CTRL-03 | 03-02 | Minimum dwell time enforced — humidifier cannot cycle faster than configurable interval | ✓ SATISFIED | `_set_humidifier_with_dwell` enforces `min_dwell_time` (300s default); 4 dwell tests cover all directions and edge cases |
| CTRL-04 | 03-03 | Stale sensor data detected — control loop does not act on data older than threshold | ✓ SATISFIED | Staleness guard at fc_controller.py:182-187 using `sensor_stale_timeout` (10s default); 5 staleness tests |
| CTRL-05 | 03-01, 03-03 | Sensor failure drives humidifier to safe state (OFF), not frozen last state | ✓ SATISFIED | None-check at line 178 (no data path) and staleness path at line 208 (stale data path) both call `set_humidifier(False)` directly |

All 5 phase requirements are satisfied. No orphaned requirements found — REQUIREMENTS.md Traceability table lists all five CTRL-xx as "Phase 3 / Complete" and all five are claimed in plan frontmatter.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `fc_controller.py` | 241 | `get_parameter('simulation_mode')` — param not declared; declared name is `actuator_simulation_mode` | ⚠️ Warning | Throws `ParameterNotDeclaredException` on graceful shutdown in non-simulation mode (hardware Pi). Does not affect control algorithm or tests. Pre-existing before phase 3. |

No stub patterns, no hardcoded empty returns, no `TODO`/`FIXME` in phase-modified code paths. The `time.time()` import is present (line 6) but is never called in the control or callback paths — no timestamp tracking uses wall time.

---

## Human Verification Required

### 1. Full Test Suite Execution

**Test:** In a ROS2 Jazzy environment on a machine with rclpy installed, run:
```
source /opt/ros/jazzy/setup.bash
source install/setup.bash
pytest src/chambers/fc-core/fc_core/test/test_controller.py -v
```
**Expected:** 17/19 tests pass. Failures are `test_temperature_control` (accesses `node.fan_pwm` which does not exist in simulation mode) and `test_light_control` (uses `node.set_parameter()` API incompatibly). Both failures pre-date phase 3 and are documented as out-of-scope in all three plan summaries. All 13 tests added or fixed in phase 3 pass.
**Why human:** rclpy is not installed on the verification host. The test module cannot be imported without ROS2.

### 2. Pre-existing Bug Assessment — main() Shutdown Path

**Test:** Review `fc_controller.py` line 241: `node.get_parameter('simulation_mode').value`. The declared parameter is `actuator_simulation_mode`, not `simulation_mode`. Determine if this will cause a runtime error during hardware deployment.
**Expected:** Either file a defect for Phase 4 to fix the parameter name, or confirm this code path is never reached in the MVP (since `actuator_simulation_mode: true` in fc_config.yaml means the `if not ...` branch is never entered).
**Why human:** Runtime behavior on the Pi hardware is needed to confirm. Static analysis identifies the bug but cannot determine impact without execution.

---

## Gaps Summary

No gaps found. All five phase success criteria are structurally satisfied in the codebase:

1. Bang-bang control at correct thresholds is implemented and wired through the dwell guard.
2. Config parameters `target_humidity`, `humidity_tolerance`, `min_dwell_time`, `sensor_stale_timeout` are all declared with correct defaults and present in fc_config.yaml.
3. `_set_humidifier_with_dwell` enforces the dwell guard for both ON→OFF and OFF→ON transitions; safe-state paths bypass it correctly.
4. Staleness detection computes elapsed time from `_last_humidity_timestamp` (set in the humidity callback) and drives humidifier OFF when exceeded.
5. Both sensor absence (None values) and stale data paths call `set_humidifier(False)` directly — the humidifier is never frozen at its last state.

The only action item is human test execution to confirm the test suite passes in the ROS2 environment, plus a pre-existing bug note for Phase 4.

---

_Verified: 2026-04-04T20:00:00Z_
_Verifier: Claude (gsd-verifier)_
