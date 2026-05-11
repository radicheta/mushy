---
phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
plan: 04
subsystem: fc-core
tags: [ros2, rclpy, modes, set_mode-service, on_set_parameters_callback, current_mode-topic, transient_local, bumpless-pid]

requires:
  - phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
    plan: 03
    provides: ModeView + _resolve_active_mode + 11 declared mode params
provides:
  - "current_mode publisher on /fc1/control/current_mode (TRANSIENT_LOCAL/RELIABLE/depth=1) with startup republish (D-13/D-14, Pitfall 2)"
  - "_build_mode_msg + _publish_current_mode helpers (cosmetic out-of-band WARN per OQ-5/D-06)"
  - "on_set_parameters_callback validator: band invariants (atomic batch view per Pitfall 4), defend_side enum, target_humidity range, active_mode membership, PID range bounds (T-28-09 defense in depth)"
  - "/set_mode service (fc_msgs/SetMode) routing through SetParameters → validator (D-16)"
  - "D-12 bumpless re-engage on mode swap via _last_published_duty carry-over"
  - "D-15 republish primitive: synchronous from service handler (source='service_call'); next-tick drain of _pending_current_mode_republish from on_set_parameters_callback (source='param_set')"
  - "FruitingChamberController.__init__ accepts **kwargs (forwards parameter_overrides=, namespace=, etc. to rclpy.node.Node) — enables pytest fixtures to seed mode-shape params before startup current_mode publish fires"
affects: [phase-28-plan-05-bridge-control-param, phase-29-alerter-rewire-current_mode]

tech-stack:
  added:
    - "rcl_interfaces.msg.SetParametersResult (callback contract)"
    - "fc_msgs.msg.Mode + fc_msgs.srv.SetMode (created in plan 28-01, consumed here)"
  patterns:
    - "Defense-in-depth param validation: bridge allowlist (Phase 28-05) at the ingress, on_set_parameters_callback at the rcl boundary — same range bounds in both layers"
    - "Whole-batch atomic validation per Pitfall 4: post-batch view via get_post() helper checks would-be state, not pre-batch state"
    - "D-04 NaN-sentinel back-compat in the validator: when band peer is NaN (modes block absent in YAML), skip band-ordering invariant; bound to [0,1] only"
    - "Service handler routing through self.set_parameters(...) so the validator fires — single source of truth for declared-mode membership"
    - "Asymmetric republish: validator queues next-tick republish (rclpy applies param AFTER callback returns; in-callback publish would emit OLD ModeView); service handler publishes synchronously (param IS applied before set_parameters returns)"

key-files:
  created: []
  modified:
    - src/chambers/fc-core/fc_core/fc_controller.py
    - src/chambers/fc-core/fc_core/test/test_controller_modes.py

key-decisions:
  - "Service name = '/set_mode' (no namespace) — controller creates `set_mode` and rclpy resolves to `/set_mode`. Bridge (Phase 28-05) and farmOS (Phase 30+) call the same plain name."
  - "[Rule 1 fix] _declared_mode_names was using get_parameters_by_prefix('modes.') (trailing dot) — returns empty in rclpy Jazzy. Switched to 'modes' (no trailing dot); returned keys are prefix-stripped (e.g. 'fruiting.band_low'). Bug latent since Phase 28-03 — callers existed but the empty-set path wasn't exercised by any plan-03 test."
  - "[Rule 3 fix] FruitingChamberController.__init__ signature changed to accept **kwargs and forward to super().__init__('fc_controller', **kwargs). Required so tests can pass parameter_overrides= at construction time — without it the startup current_mode publish observes the declared NaN-sentinel defaults, not the test-supplied mode shape."
  - "Republish-on-band-change uses next-tick drain (not in-callback synchronous publish) because rclpy applies the new param value AFTER the callback returns successful=True. Adds at most control_interval (1s) latency; in exchange the published ModeView reflects the applied state, not pre-applied. Service-handler republish is synchronous because the param IS applied between set_parameters returning and the publish call."
  - "Range bounds on pid_kp[0,5] / pid_ki[0,1] / pid_kd[0,20] mirror the bridge allowlist Phase 28-05 will enforce — duplicated by design (defense in depth)."
  - "T-28-13 race: validator queues republish flag; if a second SetParameters lands before the next-tick drain, the consumer sees the SECOND batch's state. Accepted as benign — Mode message describes latest applied state."
  - "_engage_pid_bumplessly default last_output=0.15 preserves Phase 27's post-grace fresh-engage behavior; only set_mode handler passes a non-default."
  - "[Rule 2 add] _validate_params skips band-ordering invariant when peer is NaN (D-04 sentinel). Without this, post-construction set_parameters calls in pre-Phase-28 tests (which leave declared NaN bands intact) would all reject."

requirements-completed: [MODE-03, MODE-04]

duration: ~12min
completed: 2026-05-08
---

# Phase 28 Plan 04: Wave 4 — Mode Control Surface (current_mode + set_mode + callback validator) Summary

**Controller mode-control surface lands: `current_mode` topic publisher (TRANSIENT_LOCAL with startup republish), `set_mode` service (custom SetMode srv) with D-12 bumpless re-engage, and `on_set_parameters_callback` validator with whole-batch atomicity + defense-in-depth PID range bounds. 22/22 plan-28-03+04 mode tests GREEN; 37/37 Phase 27 regression tests GREEN. Closes MODE-03 (service-driven mode swap) and MODE-04 (current_mode topic).**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-07T23:52:16Z
- **Completed:** 2026-05-08T00:04:07Z
- **Tasks:** 3 (all auto, all TDD, no checkpoints)
- **Files modified:** 2

## Accomplishments

### Task 1 — current_mode publisher + startup republish + helpers
- Added `Mode` import + publisher on `fc1/control/current_mode` with TRANSIENT_LOCAL/RELIABLE/depth=1 QoS (mirrors Phase 27 telemetry trio).
- `_build_mode_msg(mv, source)` — assembles `fc_msgs/Mode` from a ModeView with `effective_since` stamped at build time.
- `_publish_current_mode(source)` — resolves active mode, publishes, logs INFO with band/defend/source. Emits cosmetic WARN when `target ∉ [band_low, band_high]` per OQ-5/D-06 (pinning's target=0.85 below band_low=0.90 is intentional).
- Startup republish at end of `__init__` with `source='config_default'` (Pitfall 2 mitigation: TRANSIENT_LOCAL durability does NOT survive process restart).
- `_engage_pid_bumplessly` accepts optional `last_output` arg (default 0.15 preserves Phase 27 post-grace behavior).
- `__init__` accepts `**kwargs` and forwards to `rclpy.node.Node` — required so tests can inject `parameter_overrides=` before startup current_mode publish fires.
- 5 RED→GREEN tests: topic payload, late-subscribe TRANSIENT_LOCAL, startup-publish-once, pinning out-of-band WARN, fruiting in-band silent.

### Task 2 — on_set_parameters_callback validator + republish-on-band-change
- `_validate_params(params) -> SetParametersResult` registered via `add_on_set_parameters_callback`.
- Atomic batch validation per Pitfall 4: cross-param invariants check the post-batch view via `get_post()` helper, not the pre-batch state.
- Validation rules:
  - `modes.{name}.band_low/band_high`: `0 <= band_low < band_high <= 1`
  - `modes.{name}.defend_side`: `∈ {'low', 'high', 'both'}`
  - `modes.{name}.target_humidity`: `∈ [0, 1]`
  - `active_mode`: `∈ self._declared_mode_names()`
  - `pid_kp`: `∈ [0, 5]`, `pid_ki`: `∈ [0, 1]`, `pid_kd`: `∈ [0, 20]` — defense-in-depth mirror of bridge allowlist (T-28-09).
- D-04 NaN-sentinel back-compat: when band peer is NaN, skip the band-ordering invariant; bound new value to [0,1] only.
- D-15 republish: validator queues `_pending_current_mode_republish = ('param_set',)` on accept; `control_loop` drains the flag at the top of the next tick.
- 5 RED→GREEN callback tests: band invariant, defend_side enum, unknown active_mode, atomic batched band edit, pid_kp range bound. (`current_mode_republishes_on_band_change` written in Task 1's test set, GREEN by Task 2's wiring.)

### Task 3 — set_mode service with bumpless re-engage
- `SetMode` import + `/set_mode` service registered on the controller.
- `_handle_set_mode(request, response)`:
  - Pre-check declared modes; reject with `success=False` if unknown (sets `response.active_mode.source='service_call_rejected'` for audit).
  - Routes valid name through `self.set_parameters([Parameter('active_mode', ..., name)])` so the validator fires (single source of truth for declared-mode membership).
  - On accept: D-12 bumpless re-engage with `last_output=self._last_published_duty` (carries integrator across band swap).
  - D-15 synchronous republish with `source='service_call'`. Suppresses redundant next-tick republish queued by the validator (`self._pending_current_mode_republish = None`).
- `_publish_duty` stashes post-clamp duty into `_last_published_duty` for the bumpless carry primitive.
- `_last_published_duty = 0.0` initialized in `__init__` next to `_pid_engaged`.
- 3 RED→GREEN service tests: takes_effect_in_one_tick, rejects_unknown, swap_bumpless.

## Task Commits

1. **Task 1:** `97b6db6` — feat(28-04): add current_mode publisher + startup republish (D-13/D-14)
2. **Task 2:** `c190acd` — feat(28-04): add on_set_parameters_callback validator + next-tick republish (D-15)
3. **Task 3:** `dcbfeda` — feat(28-04): add set_mode service with bumpless re-engage on swap (D-12, D-16)

## Files Created/Modified

- `src/chambers/fc-core/fc_core/fc_controller.py`:
  - Imports: added `Mode`, `SetMode`, `SetParametersResult`, `Parameter`.
  - `__init__`: `**kwargs` forwarded to super; `_current_mode_pub` after `sensor_health_pub`; `_pending_current_mode_republish=None` + `add_on_set_parameters_callback`; `_set_mode_srv = create_service(SetMode, 'set_mode', ...)`; `_last_published_duty=0.0` next to `_pid_engaged`; startup `_publish_current_mode(source='config_default')` at end.
  - `_declared_mode_names`: switched `get_parameters_by_prefix('modes.')` → `'modes'` (Rule 1 — rclpy Jazzy returns empty for trailing-dot prefix).
  - New methods: `_build_mode_msg`, `_publish_current_mode`, `_validate_params`, `_handle_set_mode`. `_engage_pid_bumplessly` extended with `last_output: float = 0.15`.
  - `_publish_duty`: tracks `_last_published_duty`.
  - `control_loop`: top-of-tick drain of `_pending_current_mode_republish`.
- `src/chambers/fc-core/fc_core/test/test_controller_modes.py`:
  - New imports: `time`, `SingleThreadedExecutor`, `Node`, `DurabilityPolicy`, `HistoryPolicy`, `QoSProfile`, `ReliabilityPolicy`, `Mode`, `SetMode`.
  - New helpers: `_fruiting_v0_overrides`, `_pinning_v0_overrides`, `_transient_local_qos`, `_collect_one_mode_msg`, `_call_set_mode`.
  - `_make_node` rewritten to use constructor-time `parameter_overrides=` (cleanly seeds startup publish state).
  - 11 RED stubs replaced with real tests (4 callback + 1 PID range + 4 current_mode + 2 WARN + 3 service).

## Decisions Made

See `key-decisions:` frontmatter. Highlights:

- **Asymmetric republish primitive.** From the validator: NEXT-TICK drain because rclpy applies new param values AFTER the callback returns; in-callback publish would emit the OLD ModeView. From the service handler: SYNCHRONOUS publish because the param IS applied between `set_parameters` returning and the publish call. Both paths use the same `_publish_current_mode` helper but with different `source` strings (`'param_set'` vs `'service_call'`) for D-15 audit.

- **`_pending_current_mode_republish` race acceptance (T-28-13).** If two `set_parameters` calls land between two control_loop ticks, the next-tick drain publishes ONE Mode message describing the latest state. No "stale ModeView from batch 1 after batch 2 lands" race. Documented in plan threat model; accepted as benign.

- **Service handler routes through `set_parameters`, not direct param mutation.** Single source of truth for declared-mode membership; the validator's `active_mode ∈ declared_modes` check is the authoritative gate. Service does its own pre-check on declared modes for the early-reject path so the response.reason can name the declared set without the validator's reason format leaking.

- **PID range bounds duplicated in validator AND bridge allowlist.** Defense in depth — same bounds in two layers, by design (T-28-09). A bridge bypass cannot push insane gains because the rcl boundary callback also enforces.

- **`__init__` accepts `**kwargs` is a clean, surgical API extension** to `rclpy.node.Node`'s pre-existing parameter_overrides surface. No breaking change — production launch still calls `FruitingChamberController()` with no args.

## rclpy / Parameter Nuances Surfaced

- **`get_parameters_by_prefix('modes.')` returns EMPTY in rclpy Jazzy** when the prefix has a trailing dot. `get_parameters_by_prefix('modes')` works. Returned keys are prefix-stripped (e.g. `'fruiting.band_low'`). This bug was latent since plan 28-03 — `_declared_mode_names()` was added there but nothing in plan 28-03's tests actually exercised the empty-set path. Plan 28-04's `active_mode` validation rule was the first caller that surfaced it. Fixed in Task 2 commit.

- **`set_parameters` returns `SetParametersResult` per param in the input list** — for a 2-param batch, you get `[result_band_low, result_band_high]`. If the validator rejects the batch atomically, BOTH results have the same `successful=False` and the same `reason` string. Confirmed in `test_param_callback_batched_band_edit_atomic`.

- **rclpy logging vs python `logging`:** `node.get_logger().warn(...)` writes through rcutils, NOT the python `logging` module. `caplog` does NOT capture these. The WARN-test (`test_target_outside_band_warn_pinning`) had to use `unittest.mock.patch.object(FruitingChamberController, 'get_logger')` with a MagicMock that intercepts `.warn` calls into a list. Documented in test docstring.

- **TRANSIENT_LOCAL latching does NOT persist across process restart** — Pitfall 2 from research. The startup republish at end of `__init__` is the mitigation. Verified in `test_current_mode_late_subscribe`.

- **Service name resolution**: `create_service(SetMode, 'set_mode', ...)` on a node named `fc_controller` (no namespace) resolves to `/set_mode`, NOT `/fc_controller/set_mode`. Test client uses the same plain name `'set_mode'` (relative resolution from the client node's namespace).

- **`param.value` round-trip for NaN floats**: confirmed `Parameter(name, Type.DOUBLE, float('nan'))` round-trips correctly (no coercion to string or 0.0). The validator's `isnan(bh)` check on band peers works without special-casing.

## Verification

**Sandbox build on fc1 (`/tmp/28-04-sandbox`):**
```
$ source /opt/ros/jazzy/setup.bash && colcon build --packages-select fc_msgs fc_core
Starting >>> fc_msgs
Finished <<< fc_msgs [42.7s]   # first build; subsequent rebuilds 2.7s (incremental)
Starting >>> fc_core
Finished <<< fc_core [7.86s]   # subsequent rebuilds 6.2s
Summary: 2 packages finished
```

**22/22 plan-28-03+04 mode tests GREEN:**
```
$ python3 -m pytest src/fc-core/fc_core/test/test_controller_modes.py -v
src/fc-core/fc_core/test/test_controller_modes.py::test_resolve_active_mode_fruiting PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_back_compat_default_fruiting PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_pinning_resolves PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_param_callback_band_invariant PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_param_callback_defend_side_enum PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_param_callback_unknown_mode PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_param_callback_batched_band_edit_atomic PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_param_callback_pid_range_bound PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_fruiting_preserves_humid04 PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_pinning_clamps_on_high_excursion PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_pinning_defends_floor PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_ramp_targets_defended_edge PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_mode_c_bypass_keys_off_nearest_defended_edge PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_set_mode_service_takes_effect_in_one_tick PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_set_mode_rejects_unknown PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_mode_swap_bumpless PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_current_mode_topic_payload PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_current_mode_late_subscribe PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_current_mode_republishes_on_band_change PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_current_mode_published_at_startup PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_target_outside_band_warn_pinning PASSED
src/fc-core/fc_core/test/test_controller_modes.py::test_target_inside_band_no_warn_fruiting PASSED
============================== 22 passed in 4.59s ==============================
```

**Phase 27 regression suite (no kernel breakage):**
```
$ python3 -m pytest src/fc-core/fc_core/test/test_controller.py
======================= 37 passed in ~5s =======================
```

**Combined:**
```
$ python3 -m pytest src/fc-core/fc_core/test/test_controller.py src/fc-core/fc_core/test/test_controller_modes.py
============================== 59 passed in 7.60s ==============================
```

**`grep "outside band"` confirms WARN source line landed:**
```
$ grep -n "outside band" src/fc-core/fc_core/fc_controller.py
403:        # OQ-5 / D-06: target outside band is intentional for pinning. Surface as
407:                f'target {mv.target} outside band [{mv.band_low},{mv.band_high}] '
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] `_declared_mode_names` empty in rclpy Jazzy.**

- **Found during:** Task 2 (`test_param_callback_unknown_mode` returned `'not in declared modes []'` instead of listing fruiting+pinning).
- **Issue:** `get_parameters_by_prefix('modes.')` (with trailing dot) returns an empty dict in rclpy Jazzy. The 28-03 implementation chose this prefix; 28-03 tests didn't exercise the empty-set path so the bug was latent.
- **Fix:** Switch to `get_parameters_by_prefix('modes')` (no trailing dot). Returned keys are prefix-stripped (`'fruiting.band_low'` etc.); the existing defensive split-on-`.` logic handles both stripped and full-path shapes.
- **Files modified:** `src/chambers/fc-core/fc_core/fc_controller.py`
- **Committed in:** `c190acd` (folded into Task 2 because Task 2 was the first caller to surface the empty-set path).

**2. [Rule 3 — Blocking] `FruitingChamberController.__init__` did not accept kwargs.**

- **Found during:** Task 1 test design.
- **Issue:** Tests need `parameter_overrides=` at construction time (so the startup current_mode publish observes the test's mode shape, not the declared NaN-sentinel defaults). The existing `__init__()` takes no args and calls `super().__init__('fc_controller')` with no forwarding.
- **Fix:** Changed signature to `def __init__(self, **kwargs)` and `super().__init__('fc_controller', **kwargs)`. Production launch still calls `FruitingChamberController()` with no args — no breaking change.
- **Files modified:** `src/chambers/fc-core/fc_core/fc_controller.py`
- **Committed in:** `97b6db6` (Task 1).

**3. [Rule 2 — Missing critical functionality] Validator did not handle D-04 NaN-sentinel band peers.**

- **Found during:** Task 2 (initial validator rejected `set_parameters([band_low=0.945])` when current `band_high` was NaN — the default for fresh `_make_node()` instances without overrides).
- **Issue:** The straight `0 <= band_low < band_high <= 1` invariant fails when `band_high` is NaN (NaN comparisons return False). This would have broken every existing 28-03 test using `_set_fruiting_v0` / `_set_pinning_v0` helpers.
- **Fix:** When band peer is NaN, skip the band-ordering invariant; bound the new value to [0,1] only. Preserves D-04 back-compat (modes block absent in YAML synthesizes fruiting from target_humidity + tolerance).
- **Files modified:** `src/chambers/fc-core/fc_core/fc_controller.py`
- **Committed in:** `c190acd` (Task 2).

**4. [Rule 1 — Bug] Service name in test client was wrong.**

- **Found during:** Task 3 verification.
- **Issue:** Test used `cli_node.create_client(SetMode, '/fc_controller/set_mode')` — but the controller creates the service as `'set_mode'` (no namespace), which rclpy resolves to `/set_mode`.
- **Fix:** Switched to `cli_node.create_client(SetMode, 'set_mode')` matching the controller-side resolution. Comment in test explains the resolution rule for Phase 28-05 bridge work.
- **Files modified:** `src/chambers/fc-core/fc_core/test/test_controller_modes.py`
- **Committed in:** `dcbfeda` (Task 3).

---

**Total deviations:** 4 (1 Rule 1 latent inherited bug, 1 Rule 1 test-side, 1 Rule 3 blocking API gap, 1 Rule 2 critical NaN-handling gap).
**Impact on plan:** None — all three tasks executed as specified, regression suite passes, no scope change.

## Issues Encountered

- elder-plops has no `/opt/ros/jazzy` install. All build + test verification ran on fc1 via the sandbox-build pattern established in 28-01..28-03 (scp tarball → /tmp/28-04-sandbox → colcon build → pytest). Fc1 SSH was not via the `fc1` config alias (LAN IP host key changed); used `ubuntu@172.16.10.5` over wg0 directly per memory `feedback_ssh_tailscale`.
- `colcon test --packages-select fc_core` fails at collection time with `ImportError: cannot import name 'Temperature' from 'sensor_msgs.msg'`. This is a pre-existing colcon-test environment issue (pytest-collection path doesn't pick up sourced ROS env on a per-test-runner basis) — same condition observed in plan 28-03. Direct `python3 -m pytest <test_file>` after `source install/setup.bash` works correctly. All verification used the direct-pytest path; `colcon test` wrapper not blocking for plan-28-04 scope.

## User Setup Required

None — code-only changes. Lands on fc1 via the standard `git push fc1/prod` → `deploy.sh` flow once plan 28-07 ships the deploy.sh edits (`PI_HOST` + multi-package build).

## Next Phase Readiness

**Ready for plan 28-05** (Wave 5 — bridge `POST /control/param` + `POST /control/persist` + allowlist):

- `/set_mode` service surface stable; bridge can wire `rclnodejs` client to it without churn.
- `on_set_parameters_callback` enforces PID range bounds at the rcl boundary; bridge allowlist enforces the SAME bounds at the HTTP ingress (defense in depth, T-28-09 mitigation).
- `current_mode` topic payload locked; Phase 29 alerter rewire (D-22 clean phase boundary) consumes the same `Mode` shape via TRANSIENT_LOCAL subscriber.

**Pre-flagged forward (carried from 28-01..28-03):**
- Plan 28-06: fc_buffer.py `POST /control/persist`.
- Plan 28-07: `deploy.sh:5 PI_HOST=fc1-ts → 172.16.10.5`, and `--packages-select fc_core → --packages-select fc_msgs fc_core`.

## Self-Check: PASSED

Files modified (verified):
- `src/chambers/fc-core/fc_core/fc_controller.py` ✓ (publisher + service + callback + 4 new methods + 1 method extended + control_loop drain + __init__ kwargs forwarding)
- `src/chambers/fc-core/fc_core/test/test_controller_modes.py` ✓ (11 RED stubs replaced + 5 helpers added + _make_node rewritten)

Commits exist (verified by git log):
- `97b6db6` Task 1 ✓
- `c190acd` Task 2 ✓
- `dcbfeda` Task 3 ✓

Acceptance gates:
- colcon build PASS for fc_msgs + fc_core (sandbox on fc1) ✓
- 22/22 mode tests GREEN ✓
- 37/37 Phase 27 regression tests GREEN ✓
- All 11 RED stubs originally tagged `RED — landed in plan 28-04` are now GREEN ✓
- `current_mode` publisher with TRANSIENT_LOCAL ✓
- Startup republish at end of `__init__` (Pitfall 2) ✓
- `set_mode` service implemented + bumpless re-engage ✓
- `on_set_parameters_callback` validates band/enum/PID per the same allowlist Phase 28-05 will use ✓
- `grep "outside band" fc_controller.py` returns hits ✓

---

*Phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con*
*Completed: 2026-05-08*
