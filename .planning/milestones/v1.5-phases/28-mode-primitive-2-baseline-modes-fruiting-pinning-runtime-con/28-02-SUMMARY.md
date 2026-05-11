---
phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
plan: 02
subsystem: fc-core
tags: [ros2, yaml, package-xml, modes, fruiting, pinning, colcon]

requires:
  - phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
    plan: 01
    provides: fc_msgs ament_cmake package — buildable on fc1
provides:
  - "fc_controller modes block in fc_config.yaml (1 active_mode + 5 fruiting + 5 pinning = 11 keys) with farmer-locked v0 values D-05/D-06"
  - "fc_core <depend>fc_msgs</depend> wiring colcon build order (fc_msgs → fc_core)"
affects: [phase-28-plan-03-controller-surgery, phase-28-plan-07-deploy-script]

tech-stack:
  added: []
  patterns:
    - "Dotted-key flat ROS2 params (D-03) — modes.fruiting.band_low rather than nested dict; rclpy has no native dict params"
    - "Two-scope YAML for one node — /**: keeps shared params (D-04 back-compat); fc_controller: scope holds modes block; last-section-wins for duplicates"
    - ".nan YAML 1.1 NaN literal (lowercase, leading dot) parses to float('nan') in pyyaml — D-02 NaN-when-unset shape preserved"

key-files:
  created: []
  modified:
    - src/chambers/fc-core/config/fc_config.yaml
    - src/chambers/fc-core/package.xml

key-decisions:
  - "active_mode: fruiting declared explicitly (not relying on D-04 fallback) so first-boot get_parameter('active_mode') works with no surprises; D-04 fallback reserved for stripped-modes-block forks"
  - "Modes block landed under new fc_controller: scope alongside existing /**: block, leaving target_humidity/humidity_tolerance in /**: intact for D-04 back-compat and for nodes that don't read modes (fc_pwm_driver)"
  - "Sandbox-build pattern from 28-01 reused: scp tarball → /tmp/28-02-sandbox on fc1 → colcon build --packages-select fc_msgs fc_core. Build order verified: fc_msgs (42.2s) → fc_core (7.6s)"

requirements-completed: []  # MODE-01/MODE-02 are partially advanced by this plan but mark complete only when controller surgery (plan 03) consumes the keys

duration: 2m31s
completed: 2026-05-07
---

# Phase 28 Plan 02: Wave 2 Modes Block + fc_msgs Build Dep Summary

**Modes block lands in fc_config.yaml with 11 farmer-locked v0 keys (D-05/D-06) and fc_core declares <depend>fc_msgs</depend>. Sandbox colcon build on fc1 confirms fc_msgs → fc_core order resolves cleanly. YAML/XML only — no Python touched.**

## Performance

- **Duration:** 2m31s
- **Started:** 2026-05-07T23:29:23Z
- **Completed:** 2026-05-07T23:31:54Z
- **Tasks:** 2 (both auto, no checkpoints)
- **Files modified:** 2 (no new files)

## Accomplishments

- `fc_config.yaml` extended with a new top-level `fc_controller:` scope that declares `active_mode: fruiting` plus 10 dotted-key mode params for `fruiting` and `pinning`. All values match CONTEXT.md D-05/D-06 verbatim.
- `t_target` slot present in both modes as YAML `.nan` literal — pyyaml parses to `float('nan')`, `math.isnan` returns True (D-02 contract held).
- `/**:` block left untouched: `target_humidity: 0.96`, `humidity_tolerance: 0.015` still present so D-04 back-compat path remains exercised by plan 03's `_resolve_active_mode()` fallback branch.
- `fc_core/package.xml` declares `<depend>fc_msgs</depend>` between `diagnostic_msgs` and `rpi_hardware_pwm`. Sandbox colcon build on fc1 (`/tmp/28-02-sandbox`) succeeded: `Starting >>> fc_msgs … Finished <<< fc_msgs [42.2s]` → `Starting >>> fc_core … Finished <<< fc_core [7.60s]` → `Summary: 2 packages finished [50.8s]`. No "Cannot find package fc_msgs" or build-order errors.

## Task Commits

1. **Task 1: Add modes block to fc_config.yaml under fc_controller.ros__parameters** — `c2c129d` (feat)
2. **Task 2: Add fc_msgs build dependency to fc_core/package.xml** — `494aacc` (feat)

**Plan metadata commit:** see final commit at the end of this plan.

## Files Created/Modified

- `src/chambers/fc-core/config/fc_config.yaml` — appended `fc_controller:` scope (11 keys: `active_mode` + 5 fruiting + 5 pinning); preserved `/**:` block in full
- `src/chambers/fc-core/package.xml` — inserted `<depend>fc_msgs</depend>` after `diagnostic_msgs`

## Decisions Made

- See `key-decisions:` frontmatter. No new architectural decisions — this plan executes D-03/D-05/D-06 verbatim from CONTEXT.md.

## Verification

**Task 1 (YAML parse + value lock-in):**
```
$ python3 -c "import yaml; data=yaml.safe_load(open('src/chambers/fc-core/config/fc_config.yaml')); m=data['fc_controller']['ros__parameters']; ..."
YAML OK — all 11 keys parse to expected values, t_target is NaN both modes
```
- `active_mode == 'fruiting'`
- `modes.fruiting.band_low == 0.945`, `modes.fruiting.band_high == 0.975`, `modes.fruiting.defend_side == 'both'`
- `modes.pinning.band_low == 0.90`, `modes.pinning.defend_side == 'low'`
- `math.isnan(modes.fruiting.t_target)` and `math.isnan(modes.pinning.t_target)` both True

**D-04 back-compat preserved:**
```
D-04 back-compat preserved: target_humidity=0.96, humidity_tolerance=0.015
```

**Task 2 (package.xml + sandbox colcon build on fc1):**
```
$ python3 -c "... ET.parse('package.xml') ..."
package.xml OK — fc_msgs in ['rclpy', 'std_msgs', 'sensor_msgs', 'diagnostic_msgs', 'fc_msgs', 'rpi_hardware_pwm', 'RPi.GPIO', 'adafruit-circuitpython-dht']

$ ssh ubuntu@172.16.10.5 "cd /tmp/28-02-sandbox && source /opt/ros/jazzy/setup.bash && colcon build --packages-select fc_msgs fc_core"
Starting >>> fc_msgs
Finished <<< fc_msgs [42.2s]
Starting >>> fc_core
Finished <<< fc_core [7.60s]
Summary: 2 packages finished [50.8s]
```

## rclpy Parameter-Declaration Nuances Surfaced

- pyyaml's `.nan` literal parses to `float('nan')` as expected. The capitalized form `NaN` would parse as the string `"NaN"` — flagged in plan 03 if anyone normalizes the YAML.
- Dotted keys (`modes.fruiting.band_low`) round-trip as flat string keys in the parsed dict — pyyaml does NOT auto-nest. This is exactly the shape `get_parameter('modes.fruiting.band_low')` expects per D-03. Verified live via the safe_load assertion above; controller-side live verification will land with plan 03's `_resolve_active_mode()`.
- `defend_side: both` and `defend_side: low` parse as plain strings — no YAML keyword collision (verified: pyyaml `safe_load` returns `<class 'str'>`).

## Deviations from Plan

None — plan executed exactly as written. Both tasks completed in order; verification commands ran clean on first try.

## Issues Encountered

- elder-plops has no `/opt/ros/` install or `colcon` binary, so the in-plan `colcon build` verification step ran on fc1 via the sandbox-build pattern established in 28-01. Same pattern, same scp-tarball mechanic — no new tooling required.

## User Setup Required

None — config-only changes. Will land on fc1 via the standard `git push fc1/prod` → `deploy.sh` flow once plan 28-07 ships the deploy.sh edit.

## Next Phase Readiness

**Ready for plan 28-03** (Wave 2 controller surgery):

- 11 modes params now declared in `fc_config.yaml`; plan 03's `declare_parameters([...])` call will pick them up cleanly.
- `fc_core` build will pick up `fc_msgs` Python bindings on first colcon run; `from fc_msgs.msg import Mode` import safe.
- D-04 back-compat path preserved — `_resolve_active_mode()` fallback to `target_humidity`/`humidity_tolerance` still works for any deploy that strips the modes block.
- Wave 0 RED test `test_back_compat_default_fruiting` (and the other ModeView/resolve stubs in `test_controller_modes.py`) is now wired against a controller config that exercises both code paths.

**Pre-flagged forward (carried from 28-01):**
- Plan 28-06 task list still grows by one (fc_buffer.py `POST /control/persist`).
- Plan 28-07 still owns: `deploy.sh:5 PI_HOST=fc1-ts` → `172.16.10.5`, and `--packages-select fc_core` → `--packages-select fc_msgs fc_core`.

## Self-Check: PASSED

Files modified (verified):
- `src/chambers/fc-core/config/fc_config.yaml` ✓ (modes block present, 11 keys, .nan literal both modes)
- `src/chambers/fc-core/package.xml` ✓ (`<depend>fc_msgs</depend>` between diagnostic_msgs and rpi_hardware_pwm)

Commits exist (verified by git log):
- `c2c129d` Task 1 ✓
- `494aacc` Task 2 ✓

Acceptance gates:
- YAML parse + 11 keys at locked values + NaN check ✓
- D-04 back-compat preserved (target_humidity 0.96 + humidity_tolerance 0.015 in /**:) ✓
- package.xml XML-parses with fc_msgs in deps list ✓
- Sandbox colcon build on fc1 succeeded with fc_msgs → fc_core order, 2 packages, 50.8s ✓

---

*Phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con*
*Completed: 2026-05-07*
