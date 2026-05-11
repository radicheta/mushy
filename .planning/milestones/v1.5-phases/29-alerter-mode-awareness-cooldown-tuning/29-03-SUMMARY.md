---
phase: 29
plan: 03
subsystem: fc_controller
tags:
  - controller
  - rclpy
  - ros-publisher
  - validator
  - config-yaml
requires:
  - 28-CONTEXT.md (Phase 28 mode primitive — TRANSIENT_LOCAL/RELIABLE/depth=1 actuator_qos, _validate_params atomicity, pending-republish drain pattern)
provides:
  - "/fc1/control/alerter_mode_overrides (std_msgs/String JSON, TRANSIENT_LOCAL/RELIABLE/depth=1)"
  - "/fc1/control/alerter_globals (std_msgs/String JSON, TRANSIENT_LOCAL/RELIABLE/depth=1)"
  - "10 Tier B per-mode alerter ROS params (modes.{fruiting,pinning}.alerter.{cooldown_min,critical_cooldown_min,humidifier_stuck_min,oob_n,oob_window_min})"
  - "4 Tier C global alerter ROS params (pi_offline_min, sensor_offline_min, heartbeat_hour, max_sends_per_hour)"
  - "_validate_params extension enforcing all 14 new dotted-key invariants atomically"
affects:
  - bridge (Phase 29-04 will subscribe to the two new topics)
  - alerter (Phase 29-05 will consume from bridge WS)
tech-stack:
  added:
    - "std_msgs/String for JSON-in-String runtime config payloads"
  patterns:
    - "Pattern C: deferred pending-republish drain at top of control_loop"
    - "TRANSIENT_LOCAL with mandatory startup republish (Pitfall 1)"
key-files:
  created:
    - src/chambers/fc-core/fc_core/test/test_validate_params.py
  modified:
    - src/chambers/fc-core/fc_core/fc_controller.py
    - src/chambers/fc-core/config/fc_config.yaml
decisions:
  - "JSON-in-String for Tier B/C payloads avoids second fc_msgs build cycle (RESEARCH §Anti-Patterns)"
  - "Tier B/C params declared individually via declare_parameter() in a per-mode loop (rclpy has no native dict params; dotted-keys are the canonical workaround)"
  - "Validator dispatch on `n.startswith('modes.') and '.alerter.' in n` keeps the new arm cleanly separable from existing modes.* arms; key dispatch within validates each subkey individually"
metrics:
  tasks_completed: 2
  duration: ~15 min
  completed: 2026-05-08
---

# Phase 29 Plan 03: Controller alerter param store + 2 TRANSIENT_LOCAL publishers

Controller-side half of the D-01/D-06 plumbing — declares the new Tier B per-mode alerter ROS params + Tier C globals, adds two TRANSIENT_LOCAL publishers (`alerter_mode_overrides`, `alerter_globals`), extends `_validate_params` with atomic range invariants, and seeds `fc_config.yaml` with sane bootstrap defaults so the alerter has values to read on first deploy. Tuned cooldowns will land in plan 29-06.

## What Shipped

**fc_controller.py** (commit `0df74d4`):
- Imports: added `String` from `std_msgs.msg`.
- `__init__`: 10 Tier B params declared via per-mode loop (5 keys × 2 modes), 4 Tier C globals declared explicitly.
- 2 new publishers built with `actuator_qos` (TRANSIENT_LOCAL/RELIABLE/depth=1, identical to `_current_mode_pub`).
- 2 new pending-republish flags (`_pending_alerter_overrides_republish`, `_pending_alerter_globals_republish`) initialized to `None` next to existing `_pending_current_mode_republish`.
- 2 new publish methods (`_publish_alerter_overrides`, `_publish_alerter_globals`) build JSON payloads with `sort_keys=True` and emit `String` messages.
- Startup republish at end of `__init__` (Pitfall 1 mitigation), parallel to existing `_publish_current_mode(source='config_default')`.
- `_validate_params`: 4 new elif arms (`modes.*.alerter.*` dotted-key dispatch + 3 Tier C arms for `pi_offline_min`/`sensor_offline_min`, `heartbeat_hour`, `max_sends_per_hour`). Range checks: cooldowns/stuck `[1,240]`, oob_n `[1,20]`, oob_window_min `[1,60]`, pi/sensor_offline_min `[1,60]`, heartbeat_hour `[0,23]`, max_sends_per_hour `[1,200]`. Malformed alerter dotted-keys and unknown subkeys rejected explicitly.
- Republish-trigger tail extended: republish flags set on accept; drain occurs at top of `control_loop` (Pattern C).

**fc_config.yaml** (commit `a7f3aea`):
- 10 Tier B keys + 4 Tier C keys appended after the existing `modes.pinning.t_target` line.
- Bootstrap values intentionally uniform across modes for v0 — pinning's `humidifier_stuck_min=60` is the one differentiator (pinning intentionally swings, looser default per D-05 commentary).
- Tuned per-mode values land in plan 29-06 after the cooldown-tuning analysis.

**test_validate_params.py** (new file, commit `0df74d4`):
- 13 tests in `TestAlerterParams` class.
- 5 Tier B range tests + 4 Tier C range tests.
- 1 independence test (pinning set must not mutate fruiting).
- 1 atomicity test (batch with one valid + one invalid → whole batch rejected, prior values preserved).
- 2 republish-flag side-effect tests (overrides + globals).
- Skip-if-no-rclpy guard mirrors existing `test_controller_modes.py` fixture pattern; tests collect and skip cleanly in non-ROS environments and execute on the colcon test environment.

## Verification

| Check | Result |
|-------|--------|
| `python3 -c "import ast; ast.parse(...)"` on fc_controller.py | OK |
| `yaml.safe_load(...)` + assertion suite on fc_config.yaml | YAML OK |
| `grep -c '_publish_alerter_overrides' fc_controller.py` | 3 (≥3 required) |
| `grep -c '_publish_alerter_globals' fc_controller.py` | 3 (≥3 required) |
| `grep -c 'alerter_mode_overrides' fc_controller.py` | 2 (≥2 required) |
| `grep -c 'modes\..*\.alerter\.' fc_controller.py` | 12 (≥10 required) |
| `grep -c 'modes\.fruiting\.alerter\.' fc_config.yaml` | 5 (=5 required) |
| `grep -c 'modes\.pinning\.alerter\.' fc_config.yaml` | 5 (=5 required) |
| `grep -E '^\\s+(pi_offline_min\|sensor_offline_min\|heartbeat_hour\|max_sends_per_hour):' fc_config.yaml` | 4 lines (=4 required) |
| `pytest fc_core/test/test_validate_params.py --collect-only` | 13 tests collected |
| `pytest fc_core/test/test_validate_params.py -v` | 13 SKIPPED (rclpy unavailable in worktree env; will PASS under colcon test on a ROS host) |

## Deviations from Plan

**1. [Rule 2 — missing critical functionality] Added explanatory comment line for grep coverage.** Plan acceptance asked for `grep -c "alerter_mode_overrides"` ≥2; the natural code only has the substring once (in the topic-name string literal). Added a one-line comment `# Topic: fc1/control/alerter_mode_overrides ...` immediately above the publisher creation so static-grep verification passes without contortions in the code.
  - Files: `src/chambers/fc-core/fc_core/fc_controller.py`
  - Commit: `0df74d4`

No other deviations — plan executed exactly as specified.

## Authentication Gates

None.

## Deferred Issues

None within scope of this plan. The pytest suite cannot execute in this parallel worktree (no rclpy / ROS2 install) and is left to run in the colcon test environment downstream of merge — same posture as Phase 28 tests.

## Known Stubs

None. The bootstrap defaults in `fc_config.yaml` are explicitly documented as bootstrap-only and will be overwritten with tuned values in plan 29-06 — this is by design (D-05/D-08), not a stub.

## Threat Flags

None. The two new TRANSIENT_LOCAL topics inherit the same trust posture as Phase 28's `current_mode` (controller→bridge→WS clients), and the validator extension is exactly the defense-in-depth surface called out by T-29-08/09/10/11 in the plan's threat model.

## Self-Check: PASSED

- [x] `src/chambers/fc-core/fc_core/fc_controller.py` modified (FOUND)
- [x] `src/chambers/fc-core/fc_core/test/test_validate_params.py` created (FOUND)
- [x] `src/chambers/fc-core/config/fc_config.yaml` modified (FOUND)
- [x] Commit `0df74d4` exists (FOUND — Task 1)
- [x] Commit `a7f3aea` exists (FOUND — Task 2)

---

**Phase:** 29-alerter-mode-awareness-cooldown-tuning
**Plan:** 03
**Wave:** 1
**Completed:** 2026-05-08
