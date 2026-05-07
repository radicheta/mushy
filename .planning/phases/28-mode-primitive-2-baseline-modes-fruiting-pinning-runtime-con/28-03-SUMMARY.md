---
phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
plan: 03
subsystem: fc-core
tags: [ros2, rclpy, pid, modes, fruiting, pinning, controller-surgery, band-aware-projection]

requires:
  - phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
    plan: 02
    provides: fc_config.yaml modes block + fc_core <depend>fc_msgs</depend> build edge
provides:
  - "ModeView dataclass + _resolve_active_mode (D-08) with D-04 NaN-sentinel back-compat"
  - "Band-aware error projection in fc_controller.control_loop (D-09 four-case)"
  - "_ramp_setpoint_to_band targeting defended edge (D-10)"
  - "Mode C bypass keyed off nearest defended edge (D-11)"
  - "11 declared mode params at startup (active_mode + 5×fruiting + 5×pinning) — Pitfall 7 strict declaration preserved"
affects: [phase-28-plan-04-set_mode-service, phase-28-plan-04-current_mode-topic, phase-28-plan-05-bridge-control-param]

tech-stack:
  added: []
  patterns:
    - "Mode-aware control hot path: resolve once per tick → ModeView → band projection → bypass-edge → PID"
    - "NaN sentinel as 'param not in YAML' marker (D-04 back-compat trigger via math.isnan)"
    - "Public get_parameters_by_prefix() preferred over underscore-prefixed _parameters introspection"
    - "Band geometry where cosmetic target lies outside the band (pinning: target=0.85 < band_low=0.90) — bypass MUST key off defended edge, not target"

key-files:
  created: []
  modified:
    - src/chambers/fc-core/fc_core/fc_controller.py
    - src/chambers/fc-core/fc_core/test/test_controller_modes.py
    - src/chambers/fc-core/fc_core/test/test_controller.py

key-decisions:
  - "D-08 implementation uses get_parameters_by_prefix('modes.') for _declared_mode_names — public API, stable across rclpy versions, no underscore-prefixed access"
  - "D-09 high-side defend_side=low clamp publishes the telemetry trio (humidity_target + pid_output=0) before early return — Mission Control visibility preserved"
  - "D-11 nearest-defended-edge for defend_side='both' splits at mode.target (rh<=target → band_low, else band_high) — chosen so pinning-style geometry stays consistent with the symmetric case"
  - "Mode C entry now also gated on rh < nearest_defended — high-side excursions never enter Mode C (those are handled by the defend_side=low clamp branch or by linear PID under defend_side ∈ {high, both})"
  - "Legacy _ramp_setpoint preserved (no callers in hot path) for any external callers; new _ramp_setpoint_to_band is the active code path"
  - "[Rule 1 fix] test_pid_gains_live_reload regression: pre-Phase-28 fixture seeded rh=0.935 inside default band → error_pct=0 → Kp masked. Reseeded to rh=0.88 (linear region just below band_low). PID kernel intent unchanged."

requirements-completed: [MODE-01, MODE-02]

duration: ~17min
completed: 2026-05-07
---

# Phase 28 Plan 03: Wave 3 Controller Surgery — Mode-Aware PID Hot Path Summary

**Mode-aware control hot path lands: ModeView + _resolve_active_mode (D-08), band-edge error projection (D-09), defended-edge ramp (D-10), nearest-defended-edge bypass (D-11). PID kernel math byte-identical to Phase 27. 8 in-scope mode tests GREEN, full Phase 27 regression suite (37 tests) GREEN.**

## Performance

- **Duration:** ~17 min
- **Started:** 2026-05-07T23:31Z (after 28-02 completion)
- **Completed:** 2026-05-07T23:48Z
- **Tasks:** 2 (both auto, no checkpoints)
- **Files modified:** 3

## Accomplishments

- ModeView dataclass landed at module level above FruitingChamberController (D-08).
- 11 mode params declared at __init__: active_mode (default 'fruiting') + 5 fruiting fields + 5 pinning fields. NaN sentinel on band_low/band_high triggers D-04 back-compat in the resolver when the YAML modes block is absent.
- `_resolve_active_mode()` returns ModeView. NaN-on-band detection synthesizes a fruiting-shape ModeView from legacy `target_humidity` + `humidity_tolerance` (D-04 back-compat).
- `_declared_mode_names()` helper uses public `get_parameters_by_prefix('modes.')` (rather than underscore-prefixed `_parameters`).
- Control loop hot path replaced (lines ~462–544 post-edit):
  - `_resolve_active_mode()` called once per tick (D-08).
  - `_ramp_setpoint_to_band(dt, mode)` ramps toward defended band edge (D-10) — replaces midpoint-targeting `_ramp_setpoint`.
  - Band-aware error projection (D-09 four-case):
    - `rh < band_low` → `error_pct = (rh - band_low) * 100`
    - `rh > band_high & defend_side ∈ {high, both}` → `error_pct = (rh - band_high) * 100`
    - `rh > band_high & defend_side = low` → clamp duty=0, freeze integrator, publish telemetry trio, return early
    - in-band → `error_pct = 0`
  - Mode C bypass keys off `nearest_defended` (D-11) — defend_side=low → band_low; high → band_high; both → band_low if rh<=target else band_high. Mode C entry gated additionally on `rh < nearest_defended`.
- PID kernel math (Kp/Ki/Kd live-reload, integrator, `differential_on_measurement=True`, `output_limits=(0.0, 1.0)`, bumpless re-engage primitive) byte-identical to before.

## Task Commits

1. **Task 1: ModeView + _resolve_active_mode + parameter declarations + D-04 back-compat** — `b28b275` (feat)
2. **Task 2: Band-aware error projection + ramp-to-defended-edge + nearest-defended-edge bypass** — `8edec1a` (feat)

**Plan metadata commit:** see final commit at the end of this plan.

## Files Created/Modified

- `src/chambers/fc-core/fc_core/fc_controller.py`:
  - Imports: added `dataclass`, `isnan`, `nan`.
  - Module-level `ModeView` dataclass (6 fields).
  - `__init__`: second `declare_parameters` block adding 11 mode params (active_mode + modes.{fruiting,pinning}.{target_humidity,band_low,band_high,defend_side,t_target}).
  - New methods: `_declared_mode_names()`, `_resolve_active_mode() -> ModeView`, `_ramp_setpoint_to_band(dt, mode)`.
  - Replaced control_loop PID block (was lines 415–450; now lines ~462–544 — ~80 lines for the new band-aware branch). Surrounding logic (grace, sensor_health publish, staleness guard, temperature/light control, log debug) untouched.
- `src/chambers/fc-core/fc_core/test/test_controller_modes.py`:
  - 3 RED→GREEN: `test_resolve_active_mode_fruiting`, `test_back_compat_default_fruiting`, `test_pinning_resolves`.
  - 5 RED→GREEN: `test_fruiting_preserves_humid04`, `test_pinning_clamps_on_high_excursion`, `test_pinning_defends_floor`, `test_ramp_targets_defended_edge`, `test_mode_c_bypass_keys_off_nearest_defended_edge`.
  - Helper fixtures: `_make_node`, `_prep_controller`, `_seed_buffer`, `_set_pinning_v0`, `_set_fruiting_v0`, mock-clock helper.
  - Remaining 11 tests in the file are RED stubs marked `RED — landed in plan 28-04` (param-callback validation, set_mode service, current_mode topic) — out of scope for this plan.
- `src/chambers/fc-core/fc_core/test/test_controller.py`:
  - `test_pid_gains_live_reload`: rh seed changed `0.935 → 0.88` to drive non-zero error under D-04 fallback band [0.89, 0.99]; comment updated explaining Phase 28 band-aware projection. PID kernel intent of the test (Kp live-reload propagates next tick) preserved.

## Decisions Made

See `key-decisions:` frontmatter. Highlights:

- **Public API for mode introspection.** `_declared_mode_names()` uses `get_parameters_by_prefix('modes.')` rather than underscore-prefixed `_parameters` access. Defensive split-on-dot handles both prefix-stripped and full-name shapes; the rclpy Jazzy implementation strips the prefix.
- **High-side clamp publishes telemetry trio.** When `defend_side=low` and `rh > band_high`, the early-return path still publishes `humidifier_duty=0`, `humidity_target=effective_setpoint`, `pid_output=0` so Mission Control's continuous chart streams don't gap. Bumpless re-engage on return into band uses the existing `set_auto_mode(True, last_output=1.0)` primitive in the linear branch — no new bumpless code needed.
- **Mode C entry gated on `rh < nearest_defended`.** This narrows Mode C to the crash-below-floor case. High-side excursions on `defend_side=low` are handled earlier by the clamp branch; high-side excursions on `defend_side ∈ {high, both}` produce positive error_pct that the linear PID with `output_limits=(0,1)` clamps to 0 naturally — no Mode C needed.
- **Legacy `_ramp_setpoint` preserved.** It now targets `target_humidity` only, while the active hot path uses `_ramp_setpoint_to_band`. No external callers in fc_core, but kept for any out-of-tree caller; could be removed in a future cleanup pass.
- **[Rule 1] Phase 27 regression test fixup.** `test_pid_gains_live_reload` seeded rh=0.935 expecting linear PID against `target=0.94`. With band-aware projection and D-04 fallback (band [0.89, 0.99]), rh=0.935 is in-band → error_pct=0 → Kp has no effect. The test's intent (live param reload propagates) is preserved by reseeding rh=0.88 — just below band_low (distance 0.01, well below bypass 0.025), in linear PID territory. This is a legitimate test-fixture migration to the new error model, not a kernel regression.

## rclpy / Parameter Nuances Surfaced

- `get_parameters_by_prefix('modes.')` returns a dict keyed by the **prefix-stripped** name in rclpy Jazzy (e.g., `'fruiting.band_low'`). The introspection code splits on `'.'` and handles both shapes defensively (in case of version drift) — `parts[1]` if first token == 'modes', else `parts[0]`.
- `math.isnan(float('nan'))` is True; rclpy's parameter store round-trips `float('nan')` correctly without coercion to a string. Verified live in the resolved-mode tests.
- Setting Parameter values via `node.set_parameters([Parameter('foo', value=val)])` on already-declared params does NOT fire any callback in this plan (callback is plan 28-04 work). Direct mutation is fine for tests.

## Verification

**Sandbox build on fc1 (`/tmp/28-03-sandbox`):**
```
$ source /opt/ros/jazzy/setup.bash && colcon build --packages-select fc_msgs fc_core
Starting >>> fc_msgs
Finished <<< fc_msgs [43.1s]
Starting >>> fc_core
Finished <<< fc_core [7.54s]
Summary: 2 packages finished [51.5s]
```

**8 in-scope plan-28-03 tests (all GREEN):**
```
$ python3 -m pytest src/fc-core/fc_core/test/test_controller_modes.py -k '<8 in-scope names>'
test_resolve_active_mode_fruiting PASSED [ 12%]
test_back_compat_default_fruiting PASSED [ 25%]
test_pinning_resolves PASSED [ 37%]
test_fruiting_preserves_humid04 PASSED [ 50%]
test_pinning_clamps_on_high_excursion PASSED [ 62%]
test_pinning_defends_floor PASSED [ 75%]
test_ramp_targets_defended_edge PASSED [ 87%]
test_mode_c_bypass_keys_off_nearest_defended_edge PASSED [100%]
======================= 8 passed, 11 deselected in 2.27s =======================
```

**Phase 27 regression suite (no kernel breakage):**
```
$ python3 -m pytest src/fc-core/fc_core/test/test_controller.py
............................. (37 tests)
============================== 37 passed in 6.08s ==============================
```

**Out-of-scope RED stubs in test_controller_modes.py (still correctly RED for plan 28-04):**
- test_param_callback_band_invariant
- test_param_callback_defend_side_enum
- test_param_callback_unknown_mode
- test_param_callback_batched_band_edit_atomic
- test_set_mode_service_takes_effect_in_one_tick
- test_set_mode_rejects_unknown
- test_mode_swap_bumpless
- test_current_mode_topic_payload
- test_current_mode_late_subscribe
- test_current_mode_republishes_on_band_change
- test_current_mode_published_at_startup

All 11 fail with `RED — landed in plan 28-04` per the Wave 0 scaffold contract.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `test_pid_gains_live_reload` regression in Phase 27 suite**

- **Found during:** Task 2 verification (full test_controller.py run)
- **Issue:** Pre-existing test seeded `rh=0.935` with `target_humidity=0.94`. Pre-Phase-28: error_pct=(0.935-0.94)*100=-0.5, linear PID active, Kp affects duty. Post-Phase-28 with D-04 fallback (no modes block in test config): synthesized band is [target-tolerance, target+tolerance] = [0.89, 0.99]; rh=0.935 is in-band → error_pct=0 → PID returns ~bumpless preload (0.15) regardless of Kp. Assertion `duty_high_kp != duty_low_kp` failed because both were 0.15.
- **Fix:** Reseed rh=0.88 — just 0.01 below band_low=0.89, well within bypass_threshold=0.025, so linear PID active and error_pct=-1.0 makes Kp materially affect output. Test's intent (Kp live-reload propagates next tick) preserved.
- **Files modified:** `src/chambers/fc-core/fc_core/test/test_controller.py`
- **Verification:** Full suite GREEN 37/37 after fix.
- **Committed in:** `8edec1a` (folded into Task 2 commit since the fixup is a direct consequence of the band-aware projection surgery).

---

**Total deviations:** 1 (Rule 1 — test fixture migration to new error model; PID kernel math unchanged).
**Impact on plan:** None — both tasks executed as specified, regression suite passes, no scope change.

## Issues Encountered

- elder-plops has no `/opt/ros/jazzy` install or pytest with rclpy. All build + test verification ran on fc1 via the sandbox-build pattern established in 28-01/28-02 (scp tarball → /tmp/28-03-sandbox → colcon build → pytest). No new tooling required.
- `tar` from repo root produced a nested layout (`src/chambers/fc-core/...`); colcon expects packages directly under `src/`. Worked around by `mv src/chambers/* src/ && rmdir src/chambers` post-extract on fc1.

## User Setup Required

None — code-only changes. Lands on fc1 via the standard `git push fc1/prod` → `deploy.sh` flow once plan 28-07 ships the deploy.sh edits (PI_HOST + multi-package build).

## Next Phase Readiness

**Ready for plan 28-04** (Wave 4 — set_mode service + current_mode topic + on_set_parameters_callback validation):

- ModeView shape locked. SetMode service (D-16) can `set_parameters([Parameter('active_mode', ...)])` and immediately call `_resolve_active_mode()` to publish current_mode.
- `_engage_pid_bumplessly()` is the established mode-swap primitive (D-12) — already wired in the in-band branch as the Mode-C-exit re-engage path.
- 11 RED stubs in test_controller_modes.py are pre-tagged with `RED — landed in plan 28-04`; they collect cleanly and will turn GREEN with plan 04 work.
- Telemetry trio (`humidifier_duty`, `humidity_target`, `pid_output`) preserved on every code path including the new defend_side=low high-side clamp — Mission Control charts won't gap on mode-driven clamps.

**Pre-flagged forward (carried from 28-01):**
- Plan 28-06 task list still grows by one (fc_buffer.py `POST /control/persist`).
- Plan 28-07 still owns: `deploy.sh:5 PI_HOST=fc1-ts` → `172.16.10.5`, and `--packages-select fc_core` → `--packages-select fc_msgs fc_core`.

## Self-Check: PASSED

Files modified (verified):
- `src/chambers/fc-core/fc_core/fc_controller.py` ✓ (ModeView dataclass + 11-param declare block + 3 new methods + control_loop replaced)
- `src/chambers/fc-core/fc_core/test/test_controller_modes.py` ✓ (8 RED→GREEN tests; 11 stubs remain correctly RED for plan 28-04)
- `src/chambers/fc-core/fc_core/test/test_controller.py` ✓ (one rh seed reseeded; comment updated)

Commits exist (verified by git log):
- `b28b275` Task 1 ✓
- `8edec1a` Task 2 ✓

Acceptance gates:
- colcon build PASS for fc_msgs + fc_core (sandbox on fc1, 51.5s) ✓
- 8/8 in-scope mode tests GREEN ✓
- 37/37 Phase 27 regression tests GREEN ✓
- 11 out-of-scope stubs correctly RED with plan-04 tag ✓
- ModeView dataclass present at module level (def class found via grep) ✓
- `def _resolve_active_mode` present (must_haves.artifacts contract) ✓
- D-04 back-compat verified via test_back_compat_default_fruiting ✓
- D-09 four-case projection covered ✓
- D-10 ramp-to-defended-edge covered ✓
- D-11 nearest-defended-edge bypass covered ✓
- PID kernel math unchanged (gains live-reload still works; bumpless re-engage primitive intact) ✓

---

*Phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con*
*Completed: 2026-05-07*
