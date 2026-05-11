---
phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
plan: 01
subsystem: infra
tags: [ros2, ament_cmake, rosidl, fc_msgs, rclnodejs, jest, pytest, spike]

requires:
  - phase: 27-pid-time-proportional-duty-cycle-primitive
    provides: PID kernel + bumpless transfer that plan 28-03 will wrap in mode resolution
provides:
  - fc_msgs ament_cmake package (Mode.msg + SetMode.srv) — buildable, Python bindings import OK
  - Wave 0 RED scaffolds: 16 pytest stubs (test_controller_modes.py) + 9 jest todos (control_param + control_persist)
  - 28-01-SPIKE.md locking rclnodejs SetParameters wire shape verbatim and Layer 2 transport choice
affects: [phase-28-plans-02-through-07, phase-29-alerter-rewire, phase-30-scheduler]

tech-stack:
  added: [fc_msgs ROS2 package (ament_cmake + rosidl)]
  patterns:
    - "Wave 0 RED test scaffolds enumerate later-wave contracts (each stub names the plan that turns it GREEN)"
    - "Wave 0 SPIKE pattern — verify load-bearing assumptions against live stack before downstream waves"
    - "fc_buffer HTTP relay as Layer 2 transport (forced pivot from SSH-from-bridge)"

key-files:
  created:
    - src/chambers/fc-msgs/package.xml
    - src/chambers/fc-msgs/CMakeLists.txt
    - src/chambers/fc-msgs/msg/Mode.msg
    - src/chambers/fc-msgs/srv/SetMode.srv
    - src/chambers/fc-core/fc_core/test/test_controller_modes.py
    - src/mission-control/bridge/test/control_param.test.js
    - src/mission-control/bridge/test/control_persist.test.js
    - .planning/phases/28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con/28-01-SPIKE.md
  modified: []

key-decisions:
  - "rclnodejs 1.9.0 SetParameters wire shape confirmed verbatim — request {parameters:[{name,value:{type,<typename>_value}}]}, response {results:[{successful,reason}]}; Pattern 4 locked, no pivot for plan 28-05"
  - "rclnodejs node MUST be spinning to receive sendRequest callbacks — without spin the request transmits but response never arrives (5s TIMEOUT). Bridge's existing node already spins; document for plan 28-05"
  - "Layer 2 transport pivots from SSH-from-bridge to fc_buffer HTTP relay — bridge container has no ssh binary (exit 127); even if installable, would put an SSH key inside the container's blast radius (T-28-03 mitigate). Plan 28-06 grows by one task: add POST /control/persist route to fc_buffer.py"
  - "Overlay path locked at /var/lib/fc-core/runtime_overrides.yaml; namespace fc_controller.ros__parameters; atomic .tmp+rename with single-generation .bak"
  - "deploy.sh side-finding: PI_HOST=fc1-ts no longer resolves on elder-plops; plan 28-07 must default to 172.16.10.5 and build fc_msgs+fc_core (Pitfall 5)"

patterns-established:
  - "Sandbox-build on fc1: scp package tarball → /tmp/<sandbox>/src/<pkg> → colcon build --packages-select → import test → cleanup. Validates a new ament_cmake package without polluting the production workspace at /home/ubuntu/mushroom_farm_ws"
  - "RED scaffold convention: each stub fails with 'RED — landed in plan NN-NN' naming the plan that turns it GREEN (mechanical RED→GREEN cycle for downstream waves)"
  - "rclnodejs live-probe inside bridge container: docker exec mushy-bridge-1 bash -c 'source /opt/ros/jazzy/setup.bash && node -e \"...\"' — PID1 inherits ROS env via entry script; ad-hoc exec shells must source it themselves"

requirements-completed: []

duration: ~25min
completed: 2026-05-07
---

# Phase 28 Plan 01: Mode-primitive Wave 0 Foundation + SPIKE Summary

**fc_msgs ament_cmake package (Mode.msg + SetMode.srv) + 16 RED pytest stubs + 9 jest todos + locked-architecture SPIKE: rclnodejs Pattern 4 confirmed verbatim, Layer 2 forced-pivot to fc_buffer HTTP relay due to bridge container missing ssh binary.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-07T23:15Z (approx — agent spawn)
- **Completed:** 2026-05-07T23:24Z
- **Tasks:** 4 (Tasks 1-3 executed; Task 4 checkpoint:human-verify auto-approved per workflow.auto_advance=true)
- **Files created:** 8

## Accomplishments

- New `fc_msgs` ROS2 package: builds via colcon on fc1, Python bindings (`from fc_msgs.msg import Mode; from fc_msgs.srv import SetMode`) import without error; Mode field assignment verified (`name`, `band_low`, `band_high`, `defend_side`).
- Wave 0 RED scaffolds: 16 pytest stubs covering MODE-01..04 (resolve, back-compat, param-callback validation, fruiting/pinning behavior, set_mode service, current_mode topic with TRANSIENT_LOCAL late-subscribe and startup-republish coverage). Jest stubs covering MODE-05 Layer 1 (5 todos) and Layer 2 (4 todos).
- Live-probed rclnodejs SetParameters against the running fc_controller (no-op `pid_kp=0.35`); captured the verbatim wire shape; documented the spin-required gotcha; confirmed research §Pattern 4 needs no pivot.
- Architectural pivot recorded: bridge container has no ssh binary, so Layer 2 (overlay yaml persistence) routes through fc_buffer HTTP rather than SSH-from-bridge. Threat-aligned with T-28-03 (no SSH key inside bridge blast radius).
- Side-finding flagged for plan 28-07: `deploy.sh:5 PI_HOST=fc1-ts` no longer resolves on elder-plops post-wg0 cutover.

## Task Commits

1. **Task 1: Scaffold fc_msgs ament_cmake package** — `3b7688f` (feat)
2. **Task 2: Drop Wave 0 test scaffolds (pytest + jest)** — `5776c24` (test)
3. **Task 3: Wave 0 SPIKE — rclnodejs shape + bridge→fc1 transport** — `23ed96f` (docs)
4. **Task 4: Operator review checkpoint** — auto-approved (workflow.auto_advance=true; checkpoint:human-verify policy: auto-approve and continue)

**Plan metadata commit:** see final commit at the end of this plan.

## Files Created/Modified

- `src/chambers/fc-msgs/package.xml` — ament_cmake package metadata, format=3, rosidl_default_generators buildtool_depend, member_of_group rosidl_interface_packages
- `src/chambers/fc-msgs/CMakeLists.txt` — rosidl_generate_interfaces(msg/Mode.msg, srv/SetMode.srv) DEPENDENCIES builtin_interfaces; ament_export_dependencies(rosidl_default_runtime)
- `src/chambers/fc-msgs/msg/Mode.msg` — D-13 fields verbatim (name, target_humidity, band_low, band_high, defend_side, t_target, builtin_interfaces/Time effective_since, source)
- `src/chambers/fc-msgs/srv/SetMode.srv` — D-16 shape: req {name}, resp {success, reason, fc_msgs/Mode active_mode}
- `src/chambers/fc-core/fc_core/test/test_controller_modes.py` — 16 RED stubs, each tagged with the plan that turns it GREEN
- `src/mission-control/bridge/test/control_param.test.js` — 5 jest todos for MODE-05 Layer 1
- `src/mission-control/bridge/test/control_persist.test.js` — 4 jest todos for MODE-05 Layer 2 (last todo references SPIKE.md §B for transport)
- `.planning/phases/28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con/28-01-SPIKE.md` — §A rclnodejs shape + §B SSH-vs-fc_buffer-relay decision + §C 11 locked decisions for plans 05/06/07

## Decisions Made

See `key-decisions:` frontmatter above. Full decision register lives in `28-01-SPIKE.md §C`. Highlights:

- **rclnodejs Pattern 4 confirmed verbatim** — request `{parameters:[{name,value:{type:int, <typename>_value}}]}`, response `{results:[{successful, reason}]}`. Plan 28-05's `toParamValue(name, jsValue)` allowlist must carry `expected_type` per param to map JS Number → DOUBLE/INTEGER/STRING correctly.
- **rclnodejs spin requirement** — `node.spin()` MUST be running for `sendRequest` callbacks to fire. Bridge already spins its existing node; plan 28-05 reuses it.
- **Layer 2 = fc_buffer HTTP relay (architectural pivot)** — bridge container has no ssh binary (`exec: "ssh": executable file not found in $PATH`, exit 127). Threat-aligned with T-28-03. Plan 28-06 grows by one task: add `POST /control/persist` route to `src/chambers/fc-core/fc_core/fc_buffer.py` (Python http.server, runs as `ubuntu` on fc1, already binds 172.16.10.5:8765).
- **Overlay path / namespace** — `/var/lib/fc-core/runtime_overrides.yaml` (dir already ubuntu-owned per fc-core.service ExecStartPre); yaml namespace `fc_controller.ros__parameters` (narrows scope vs `/**:`).
- **deploy.sh side-finding** — `PI_HOST=fc1-ts` no longer resolves on elder-plops; canonical link is wg0 = 172.16.10.5. Not blocker-priority for 28-01 (deploy not invoked); plan 28-07 owns the fix.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] rclnodejs `node -e` ad-hoc exec required ROS env source**

- **Found during:** Task 3 (SPIKE §A — first attempt at live SetParameters call)
- **Issue:** `docker exec mushy-bridge-1 node -e "..."` failed with rclnodejs trying to rebuild from source (`Error: Command failed: which ros2`). PID1 in the bridge container has full ROS env via the entry script, but ad-hoc `docker exec` shells do not inherit it.
- **Fix:** Wrap the probe in `bash -c 'source /opt/ros/jazzy/setup.bash && node -e "..."'`. Documented in SPIKE §A "Container ROS env" row.
- **Files modified:** none (operational discovery; documented in 28-01-SPIKE.md)
- **Verification:** Probe succeeded; SERVICE_READY=true; live response captured.
- **Committed in:** `23ed96f` (Task 3 SPIKE commit captures the discovery)

**2. [Rule 3 - Blocking] rclnodejs sendRequest callback never fires without `node.spin()`**

- **Found during:** Task 3 (SPIKE §A — second attempt)
- **Issue:** Initial probe with sourced ROS env got `SERVICE_READY=true` but the `sendRequest` callback timed out at 5s. Without an active executor, rclnodejs delivers the request but cannot dispatch the async response.
- **Fix:** Add `n.spin()` before `sendRequest`. Probe immediately returned `{"results":[{"successful":true,"reason":""}]}`.
- **Files modified:** none (operational discovery)
- **Verification:** Live response captured verbatim.
- **Committed in:** `23ed96f` — locked as decision D-A5 in §C.

**3. [Rule 4 - Architectural] Layer 2 transport: SSH-from-bridge → fc_buffer HTTP relay**

- **Found during:** Task 3 (SPIKE §B)
- **Issue:** Bridge container has no `ssh` binary (`exec: "ssh": executable file not found`, exit 127). Research §Pattern 4 / §Pitfall 3 had assumed SSH-from-bridge. Installing openssh-client + provisioning a key inside the container would expand T-28-03's blast radius (bridge compromise → fc1 ubuntu shell).
- **Fix:** Pivot to fc_buffer HTTP relay. fc_buffer already runs on fc1 as `ubuntu`, already binds `172.16.10.5:8765`, already has filesystem access to `/var/lib/fc-core/`. Plan 28-06 grows by one task to add `POST /control/persist` route. **This is a Rule 4 (architectural) deviation — surfaced as a checkpoint via the SPIKE document; auto-approved under workflow.auto_advance=true.**
- **Files modified:** none in this plan (the pivot is a SPIKE finding; implementation lands in plans 28-05 and 28-06)
- **Verification:** SPIKE §B records the probe, exit code, and decision rationale; cross-referenced in jest todo 4 of `control_persist.test.js`.
- **Committed in:** `23ed96f`

---

**Total deviations:** 3 (2 Rule 3 blocking — operational gotchas resolved inline; 1 Rule 4 architectural pivot — surfaced through SPIKE artifact and accepted by checkpoint policy).
**Impact on plan:** Plan 28-01's tasks executed exactly as written. Plan 28-06 must grow by one task (fc_buffer route addition) — pre-flagged in §C decision D-B5 so plan 28-06's planner picks it up automatically. No re-plan needed.

## Issues Encountered

- `setup.sh` references `/opt/ros/jazzy/setup.bash` on the host (elder-plops), but elder-plops has no `/opt/ros/` install. ROS lives only on fc1 and inside Docker images. Workaround: use `docker exec mushy-bridge-1 bash -c 'source /opt/ros/jazzy/setup.bash && ...'` for any host-side ROS interaction. **Not a Phase 28 concern** — orthogonal to mode work; flagged here for any future executor that assumes elder-plops has a local ROS install.
- pytest is not installed on elder-plops (`No module named pytest`). Collection verified by scp'ing the test file to fc1 and running `python3 -m pytest --collect-only` there. **Not a blocker** — `colcon test` is the canonical runner per CLAUDE.md and runs on fc1.

## User Setup Required

None — no external service configuration required for this plan. Plan 28-04+ may surface farmOS-side coordination needs (D-20).

## Next Phase Readiness

**Ready for plan 28-02** (Wave 1 controller surgery — back-compat default fruiting + ModeView resolver):
- `fc_msgs` package buildable, Python bindings import-tested.
- Test scaffolds in place — plan 28-02 turns `test_back_compat_default_fruiting` GREEN.
- SPIKE locks the wire shape and transport plans 28-05 / 28-06 will consume verbatim — no further architectural ambiguity in the phase.

**Pre-flagged for plan 28-06:** task list grows by one (fc_buffer.py `POST /control/persist` route).
**Pre-flagged for plan 28-07:** `deploy.sh` PI_HOST default + multi-package build (`fc_msgs fc_core`).

## Self-Check: PASSED

Files exist (verified):
- `src/chambers/fc-msgs/package.xml` ✓
- `src/chambers/fc-msgs/CMakeLists.txt` ✓
- `src/chambers/fc-msgs/msg/Mode.msg` ✓
- `src/chambers/fc-msgs/srv/SetMode.srv` ✓
- `src/chambers/fc-core/fc_core/test/test_controller_modes.py` ✓
- `src/mission-control/bridge/test/control_param.test.js` ✓
- `src/mission-control/bridge/test/control_persist.test.js` ✓
- `.planning/phases/28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con/28-01-SPIKE.md` ✓

Commits exist (verified by git log):
- `3b7688f` Task 1 ✓
- `5776c24` Task 2 ✓
- `23ed96f` Task 3 ✓

Acceptance gates:
- colcon build PASS for fc_msgs (sandbox build on fc1, 43.9s) ✓
- Python bindings import OK (Mode + SetMode_Request) ✓
- pytest collected 16 tests in test_controller_modes.py ✓
- jest discovers control_param.test.js + control_persist.test.js ✓
- 28-01-SPIKE.md contains §A + §B + §C and "fc_buffer HTTP relay" decision ✓

---

*Phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con*
*Completed: 2026-05-07*
