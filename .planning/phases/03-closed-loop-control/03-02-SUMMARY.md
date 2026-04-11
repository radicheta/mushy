---
phase: 03-closed-loop-control
plan: "02"
subsystem: fc_core/controller
tags: [control-loop, dwell-time, safety, tdd]
dependency_graph:
  requires: [03-01]
  provides: [dwell-time-guard, _set_humidifier_with_dwell]
  affects: [fc_controller.py, test_controller.py]
tech_stack:
  added: []
  patterns: [dwell-time guard, ROS2 clock mocking, bang-bang with hysteresis]
key_files:
  created: []
  modified:
    - src/chambers/fc-core/fc_core/fc_controller.py
    - src/chambers/fc-core/fc_core/test/test_controller.py
decisions:
  - "Dwell guard implemented as separate _set_humidifier_with_dwell method (Option B from RESEARCH) — preserves set_humidifier as thin hardware abstraction, keeps guard logic visible at call sites"
  - "test_dwell_time_applies_both_directions pre-sets humidifier_state=True to ensure the first control_loop produces a real ON->OFF transition that records _last_humidifier_toggle"
  - "test_humidity_control updated to mock clock advancing 301s between toggles — now fixed (was pre-existing failure)"
  - "5x _send_humidity buffer fill per test phase ensures median filter is fully loaded before control_loop is called"
metrics:
  duration: 5min
  completed: "2026-04-04"
  tasks: 1
  files: 2
---

# Phase 03 Plan 02: Humidifier Dwell Time Guard Summary

**One-liner:** Added `_set_humidifier_with_dwell` method gating bang-bang humidifier calls by `min_dwell_time` (300s default), with safe-state None-check bypassing the guard entirely.

## What Was Built

1. **`_set_humidifier_with_dwell(self, state)` method** in `fc_controller.py`:
   - Checks `_last_humidifier_toggle` timestamp; skips transition if `elapsed < min_dwell_time`
   - No-ops if requested state already matches current state (no transition needed)
   - First call always permitted (`_last_humidifier_toggle is None`)
   - Applies equally to both ON→OFF and OFF→ON transitions (D-06)
   - Uses `self.get_clock().now()` for ROS2-compatible timestamps (testable with clock mocks)
   - Logs at DEBUG level when toggling is suppressed

2. **`control_loop` bang-bang section** updated:
   - `self.set_humidifier(True)` → `self._set_humidifier_with_dwell(True)`
   - `self.set_humidifier(False)` → `self._set_humidifier_with_dwell(False)`
   - None-check safe-state call retained as `self.set_humidifier(False)` direct (bypasses dwell guard per D-10)

3. **Tests added** (`test_controller.py`):
   - `_mock_clock_at(nanoseconds)` helper using `MagicMock` + `rclpy.time.Time`
   - `test_dwell_time_blocks_toggle`: toggle blocked when only 10s elapsed (< 300s dwell)
   - `test_dwell_time_allows_toggle_after_wait`: toggle permitted after 301s
   - `test_dwell_time_first_toggle_always_allowed`: first toggle always allowed (None timestamp)
   - `test_dwell_time_applies_both_directions`: OFF→ON transition also guarded

4. **`test_humidity_control` repaired** (was pre-existing failure):
   - Now uses clock mocking with 0s / 301s time points to allow the ON→OFF sequence to complete
   - Uses 5x `_send_humidity` buffer fill to ensure median passes thresholds

## Commits

| Hash    | Type | Description |
|---------|------|-------------|
| 92322ab | test | Add failing tests for dwell time guard (RED) |
| 4c1b49c | feat | Add dwell time guard to humidifier control (GREEN) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_dwell_time_applies_both_directions initial state assumption**
- **Found during:** Task 1 GREEN phase
- **Issue:** Test assumed turning OFF a humidifier that starts in OFF state (simulation default) would record `_last_humidifier_toggle`. The `_set_humidifier_with_dwell` no-ops when state == current_state, so `_last_humidifier_toggle` remained None and the second toggle was incorrectly allowed.
- **Fix:** Pre-set `node.humidifier_state = True` before the first control_loop call to ensure a real ON→OFF transition happens and records the timestamp.
- **Files modified:** `src/chambers/fc-core/fc_core/test/test_controller.py`
- **Commit:** 4c1b49c

**2. [Rule 1 - Bug] Fixed test_humidity_control dwell guard interaction (pre-existing failure now fixed)**
- **Found during:** Task 1 GREEN phase
- **Issue:** `test_humidity_control` sent humidity below threshold then above threshold in sequence without advancing clock. After dwell guard was added to bang-bang, the second toggle was blocked (< 300s elapsed), causing test failure. This test was already a pre-existing failure in Plan 01 (different reason: wrong assertions for simulation mode).
- **Fix:** Updated test to use clock mocking (0s → 301s) and 5x buffer fill per phase. Test now passes.
- **Files modified:** `src/chambers/fc-core/fc_core/test/test_controller.py`
- **Commit:** 4c1b49c

**3. [Rule 2 - Missing Functionality] Added 5x buffer fill in all dwell tests**
- **Found during:** Task 1 RED phase
- **Issue:** Plan's test templates used single `_send_humidity` calls. With the rolling median buffer (maxlen=5), a single call after a previous call results in a 2-element buffer whose median may not cross the ±tolerance band. E.g., after sending [0.70] then [0.95], median([0.70, 0.95]) = 0.825 < 0.90 (upper band), so OFF toggle never fires.
- **Fix:** All dwell tests now send each humidity value 5 times to fully load the median buffer with a clear signal.
- **Files modified:** `src/chambers/fc-core/fc_core/test/test_controller.py`
- **Commit:** 92322ab

## Known Stubs

None — `_last_humidifier_toggle` is now populated on every humidifier state change. The dwell guard is fully functional.

## Self-Check: PASSED

- `src/chambers/fc-core/fc_core/fc_controller.py` — contains `def _set_humidifier_with_dwell(self, state):`, `self._set_humidifier_with_dwell(True)`, `self._set_humidifier_with_dwell(False)`, None-check still uses `self.set_humidifier(False)` directly
- `src/chambers/fc-core/fc_core/test/test_controller.py` — contains `test_dwell_time_blocks_toggle`, `test_dwell_time_allows_toggle_after_wait`, `test_dwell_time_first_toggle_always_allowed`, `test_dwell_time_applies_both_directions`
- Commits 92322ab and 4c1b49c exist in git log
- 12/14 tests pass (2 pre-existing failures: `test_temperature_control` and `test_light_control` — out of scope since Phase 02)
