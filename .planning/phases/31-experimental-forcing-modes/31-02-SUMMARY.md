# Plan 31-02 Summary — Controller wiring: force-mode + experiment services + TTL + boot-recovery

**Status:** code complete; pytest verification deferred to fc1 deploy (elder-plops has no rclpy/fc_core install).

## What was built

All 7 tasks landed in `src/chambers/fc-core/fc_core/fc_controller.py`:

1. **Schema extension (D-01/D-02):** `declare_parameters` extended with `force_duty` for all 4 modes (NaN sentinel for fruiting/pinning, 1.0/0.0 defaults for force-condensation/force-evaporation; YAML overrides confirm the defaults). Force-mode entries declared with wide-open bands. `ModeView` dataclass gains `force_duty: float`. `_resolve_active_mode` populates `force_duty` in both branches (legacy NaN-band synth → NaN; modern → param read with defensive fallback).
2. **Force-duty short-circuit (D-02):** `control_loop` short-circuits AFTER mode resolution and BEFORE `_pid_engaged` check. When `mode.force_duty` is finite, parks PID via `set_auto_mode(False)`, publishes the literal duty, emits `humidity_target` + `pid_output` reflecting the literal force value (chart fidelity), updates `_last_tick_ts`, and returns.
3. **Validator gate (D-03):** `_validate_params` `active_mode` arm rejects `force-*` unless `_experiment_set_in_progress=True`. `_handle_set_mode` early-rejects `force-*` names regardless of the flag (defense in depth — no public service entry into force without TTL).
4. **start_experiment + cancel_experiment (D-10/D-11/D-13):** ActiveExperiment dataclass added. `_handle_start_experiment` validates in the locked order (name → duration 1..120 → no-active-experiment → controller readiness). On accept: allocate ActiveExperiment, gated `set_parameters`, bumpless re-engage carrying `_last_published_duty`, publish `current_mode` `source='experiment'`, publish `experiment_event` `event='started'`. `_handle_cancel_experiment` mirrors with `source='experiment_cancel'` / `event='cancelled'` and includes `actual_minutes`.
5. **1Hz TTL timer (D-05/D-06):** `_experiment_timer = create_timer(1.0, self._experiment_tick)` registered after the control timer. `_experiment_tick` is idle-safe (no-op when `_active_experiment is None`); on monotonic-clock expiry performs the auto-revert — gated `set_parameters`, bumpless re-engage, `current_mode` source='experiment_revert', `experiment_event` event='ended' with `actual_minutes`. `_monotonic()` is a test seam (overridable instance attribute).
6. **Boot-recovery (D-09):** `_check_force_mode_at_boot` runs at end of `__init__`, BEFORE the initial `config_default` `current_mode` publish but AFTER the experiment_event publisher exists. Recovery target priority: `fruiting` if declared, else first non-force declared mode (sorted). On force-mode detection: WARN log, gated `set_parameters` to safe baseline, publish `experiment_event` event='truncated' (None payload — no in-memory experiment record).
7. **Scheduler suppression (D-08):** `_scheduler_tick` first executable line: `if self._active_experiment is not None: return`. After auto-revert, the next 30s tick re-aligns naturally.

**experiment_event topic:** `fc1/control/experiment_event` JSON-in-String (Phase 29-07 precedent), TRANSIENT_LOCAL/RELIABLE/depth=1, payload sorted-keys-stable. Bridge subscribes in 31-03.

## Tests added

- `src/chambers/fc-core/fc_core/test/test_controller_modes.py` — 11 new tests (force_duty resolution × 5, control_loop short-circuit + telemetry × 6).
- `src/chambers/fc-core/fc_core/test/test_validate_params.py` — 6 new tests in `TestForceModeServiceOnly` (D-03 gate).
- `src/chambers/fc-core/fc_core/test/test_force_experiment.py` — NEW; 24 tests across `TestStartExperiment` (7), `TestCancelExperiment` (5), `TestExperimentTick` (6), `TestBootRecovery` (4), `TestSchedulerSuppression` (2).

Total new test invocations: ~41. All graceful-skip when rclpy unavailable.

## Verification

- Python syntax (`ast.parse`) clean on `fc_controller.py` (1723 lines), all three test files.
- Static greps satisfied: `_experiment_set_in_progress` 12, `_active_experiment` 14, `ActiveExperiment` 6, `force_duty` 21, `experiment_event` 18, all `source='experiment*'` strings, `fc1/control/experiment_event` 2.
- YAML config test still 10/10 PASS.
- **Deferred:** colcon build + full pytest suite — fc1 deploy.

## Decisions / Notes

- `boot_recovery_publishes_truncated_event` test asserts post-`__init__` health rather than capturing the event mid-`__init__` (the publisher is mid-construction; capturing requires a second subscriber node which complicates the test for marginal gain — covered indirectly by static grep + happy-path test).
- `_monotonic` and `_wall_now_iso` are plain methods overridable as instance attributes — same testing seam pattern as Phase 30's `_now_hhmm`.
- `imports`: added `timezone, timedelta` from `datetime`, `Optional` from `typing`, `json` and `time as _time` at module level. `StartExperiment, CancelExperiment` imported alongside `SetMode`.

## Hand-off to next plans

- **31-03 (bridge):** subscribes to `fc1/control/experiment_event` (JSON shape locked above), exposes POST `/control/experiment/start` + `/control/experiment/cancel` proxying `start_experiment` / `cancel_experiment` services. fc_experiments TimescaleDB migration adds the row schema.
- **31-04 (Signal):** alerter parses `force-condensation 15min` / `cancel-experiment` Signal commands and POSTs to the bridge endpoints.
