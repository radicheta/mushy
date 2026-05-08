# Plan 31-01 Summary — Foundation: srv defs + force-mode config

**Status:** complete (autonomous tasks); colcon build verification deferred to live deploy.

## What was built

- `src/chambers/fc-msgs/srv/StartExperiment.srv` — request `(experiment_name, duration_minutes)`, response `(ok, message, started_at_iso, reverts_at_iso, prior_mode)`. Matches CONTEXT D-10/D-13.
- `src/chambers/fc-msgs/srv/CancelExperiment.srv` — empty request, response `(ok, message, ended_at_iso)`.
- `src/chambers/fc-msgs/CMakeLists.txt` — appended both srvs to `rosidl_generate_interfaces`.
- `src/chambers/fc-core/config/fc_config.yaml` — added `modes.force-condensation.*` and `modes.force-evaporation.*` blocks immediately after `modes.pinning.t_target`. Wide-open bands [0.0, 1.0], defend_side=both, t_target=NaN. `force_duty=1.0` on force-condensation, `force_duty=0.0` on force-evaporation. fruiting/pinning carry no force_duty key (sentinel = absent).
- `src/chambers/fc-core/fc_core/test/test_force_modes_config.py` — 10 invocations, all PASS, locks the four invariants (force_duty values, wide-open bands, defend_side, t_target NaN, baseline-modes-no-force_duty).

## Verification

- pytest 10/10 PASS (locally on elder-plops with system pytest 9.0.3 / Python 3.12).
- YAML parses; grep checks confirm 4 modes declared and exactly 2 `force_duty:` keys.
- **Deferred:** `colcon build --packages-select fc_msgs` and srv-import introspection — elder-plops has no ROS install; this verification fires on fc1 deploy along with 31-04.

## Decisions

- Followed plan exactly. No deviations.

## Hand-off to next plans

- 31-02 (controller wiring) can now `from fc_msgs.srv import StartExperiment, CancelExperiment` after fc1 colcon build.
- 31-02 must extend `declare_parameters` with `modes.force-condensation.*` and `modes.force-evaporation.*` (including the `force_duty` schema-extension key with NaN default for fruiting/pinning).
- 31-03 reads no fc_msgs Python directly — uses rosbridge JSON for service calls.
