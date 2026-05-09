# 2026-05-09 Phase 31 — bugs found during lab UAT

Discovered during the saturday lab visit, while running the first force-evaporation
experiment against the freshly-deployed Phase 31 stack. None block the experiment
running end-to-end (proven via direct ROS2 service call), but all three should be
filed before declaring Phase 31 attested.

---

## BUG-31-A — bridge POST `/control/experiment` calls wrong service path

**File:** `src/mission-control/bridge/src/control_experiment.js`

**Symptom:** POST `/control/experiment` returns `504 timeout` (`/fc_controller/start_experiment timeout after 5000ms`). Same for `/control/cancel-experiment`.

**Root cause:** bridge calls `/fc_controller/start_experiment` (namespaced). fc_controller registers the service such that **only the un-namespaced `/start_experiment` actually responds** to a service call, even though both paths appear in `ros2 service list` and `ros2 service type`. Confirmed by direct CLI from fc1: namespaced path hangs at "waiting for service to become available" and errors with "rcl node's context is invalid"; un-namespaced path responds immediately.

**Fix applied during visit (line 92, 120 of control_experiment.js):**
```diff
- '/fc_controller/start_experiment',
+ '/start_experiment',

- '/fc_controller/cancel_experiment',
+ '/cancel_experiment',
```

**Open question for follow-up:** *why* does fc_controller's namespaced service path appear discoverable but not callable? This may be a deeper rclpy + jazzy service naming bug worth understanding before relying on it. For now, the un-namespaced path works — but if fc_controller is later refactored under multi-chamber namespacing (memory `project_multi_chamber_pi_zero`), the un-namespaced shortcut will collide.

---

## BUG-31-B — duplicate row insertion on bridge restart (idempotency gap)

**File:** `src/mission-control/bridge/src/control_experiment.js` (experiment_event subscriber, around line 218)

**Symptom:** On bridge restart while an experiment is in flight, the TRANSIENT_LOCAL replay of the `started` event causes a SECOND row to be INSERTed into `fc_experiments`, with the same `started_at` but `baseline_rh = NULL`. Original row remains intact.

**Reproduction (from today):**
1. Started force-evaporation experiment via `ros2 service call /start_experiment ...` at 17:20:26
2. fc_experiments had id=1: `baseline_rh=95.42535`, `started_at=17:20:26.003261`
3. Rebuilt + restarted bridge container at ~17:21
4. After restart, fc_experiments had id=1 AND id=2, both with `started_at=17:20:26.003261`. id=2 has `baseline_rh=NULL`.

**Root cause hypothesis:** the experiment_event subscriber's INSERT path does not check whether a row already exists for the given `started_at`. TRANSIENT_LOCAL guarantees the last published "started" event is replayed to any new subscriber, which is the correct DDS behavior — but the bridge handler should be idempotent against it.

**Fix shape:**
- INSERT becomes `INSERT ... ON CONFLICT (started_at) DO NOTHING` (requires unique constraint on started_at, OR a uniqueness check via separate SELECT first).
- Alternative: track in-memory "I already ingested an event with this started_at this session" set and short-circuit.
- Test seam: `experiment_event_subscriber.test.js` should add a "double-replay" case.

**Severity:** Medium. Pollutes `fc_experiments` history; would also confuse any UI showing "experiments today". Doesn't break the running experiment.

---

## BUG-31-C — bridge container had no fc_msgs srv definitions (build-time)

**File:** `src/mission-control/bridge/Dockerfile` + `docker-compose.yml`

**Symptom:** First POST to `/control/experiment` returned:
```
"createClient failed: The message required does not exist: fc_msgs, srv, StartExperiment at /opt/bridge/node_modules/rclnodejs/generated/"
```

**Root cause:** the bridge Docker image's `npm install` runs at image-build time, and `rclnodejs` generates JS bindings for srv/msg types from `AMENT_PREFIX_PATH` at that moment. Phase 31 added `fc_msgs/srv/StartExperiment` + `CancelExperiment` and wired the bridge to call them, but the Dockerfile did not include a step to build fc_msgs into the image — so the generated/ dir lacked the bindings, and `createClient` failed.

This is in the same family as memory `feedback_verify_runtime_compose` ("verify runtime compose, not plan target") — Phase 31 verification ran on the JS unit tests but never proved the bridge container could actually instantiate the generated srv types at runtime.

**Fix applied during visit:**
1. Bridge Dockerfile: add colcon + ament-cmake + rosidl deps; build fc_msgs into `/opt/fc_msgs_ws/install` overlay; source it before npm install.
2. Bridge entrypoint.sh: source `/opt/fc_msgs_ws/install/setup.bash` before exec node.
3. docker-compose.yml: change bridge build context to repo root so Dockerfile can `COPY src/chambers/fc-msgs/`.

These changes are committed. Next bridge rebuild from a fresh image will produce the fc_msgs srv bindings.

**Severity:** High at the time, fixed-in-flight.

**Process note:** Phase 31 should have included a "rebuild bridge container from scratch + verify rclnodejs can construct StartExperiment_Request" check in 31-03 verification. Without that, the JS-side unit tests pass but the actual deploy is broken. Worth making this a standing verification gate for any phase that adds fc_msgs srv/msg types and wires them into the bridge.

---

## Summary table

| Bug | Severity | Status | Owner |
|-----|----------|--------|-------|
| 31-A bridge namespace path wrong | Medium | Fixed in flight (control_experiment.js) | radicheta |
| 31-B duplicate row on TRANSIENT_LOCAL replay | Medium | Filed, fix shape known | follow-up |
| 31-C bridge Dockerfile missing fc_msgs build | High | Fixed in flight (Dockerfile + entrypoint + compose) | radicheta |

All three should ship together as a Phase 31.1 follow-up, with the verification-gate process note from 31-C as a CLAUDE.md / phase-template addition.
