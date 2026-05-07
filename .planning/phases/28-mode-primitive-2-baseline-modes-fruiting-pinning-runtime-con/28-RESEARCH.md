# Phase 28: Mode primitive + 2 baseline modes (`fruiting`, `pinning`) + runtime config delivery — Research

**Researched:** 2026-05-07
**Domain:** ROS2 Jazzy custom interfaces + parameter-service runtime tuning + bridge HTTP plumbing
**Confidence:** HIGH (controller surgery + topic shape; verified against codebase) / MEDIUM (rclnodejs SetParameters surface; doc-thin, code-confirmed) / MEDIUM (overlay-yaml path conventions; ops choice not standardized)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01** Mode schema = `(target_humidity, band_low, band_high, defend_side: low|high|both, T_target_optional)` — SEED-004 verbatim. **REQUIREMENTS.md MODE-01 is rewritten** by this phase.
- **D-02** `T_target` reserved for VPD anchoring (Phase 31+). Default `null` / `NaN`.
- **D-03** Mode definitions = **flat dotted-key ROS2 params** under `fc_controller` namespace (e.g. `modes.fruiting.band_low`). Adding new modes (beyond fruiting/pinning) is a deploy in v0.
- **D-04** Back-compat: if `modes:` block absent, derive default `fruiting` from `target_humidity` + `humidity_tolerance`.
- **D-05** `fruiting` v0 = `target=0.96, band_low=0.945, band_high=0.975, defend_side=both, T_target=null` (preserves HUMID-04).
- **D-06** `pinning` v0 = `target=0.85, band_low=0.90, band_high=0.99, defend_side=low, T_target=null`.
- **D-07** Pinning v0 is **passive only** — rides diurnal swing; no active forcing.
- **D-08** Add `_resolve_active_mode()` helper, called once per tick, returns `ModeView`. PID kernel math unchanged.
- **D-09** Replace `error_pct = (rh - effective_setpoint) * 100` with band-edge projection (rh<band_low → negative error; rh>band_high & defend_side ∈ {high,both} → positive error; rh>band_high & defend_side=low → clamp duty=0, freeze integrator, return early; in-band → error=0).
- **D-10** Setpoint ramp targets `band_low` (or `band_high` on the defended side) — **not** midpoint.
- **D-11** Mode C bypass keys off distance from **nearest defended band edge**, not from `target_humidity`.
- **D-12** Mode swap calls `_engage_pid_bumplessly()` with current duty.
- **D-13** New `fc_msgs` package; `fc_msgs/msg/Mode.msg` with name, target, band_low, band_high, defend_side, t_target (NaN-when-unset), effective_since, source.
- **D-14** Topic `fc1/control/current_mode`, **TRANSIENT_LOCAL** durability.
- **D-15** Republish on every mode swap or band-edge tweak.
- **D-16** Service `fc_controller/set_mode` (custom srv in `fc_msgs`); writes `active_mode` ROS2 param via callback; effect on next tick (≤1s); no confirm.
- **D-17** Two-layer runtime config: Layer 1 = `POST /control/param` → ROS2 SetParameters via `rclnodejs`; Layer 2 = `POST /control/persist` → write `runtime_overrides.yaml` on fc1.
- **D-18** Reject MQTT, scp+SIGHUP, Timescale-poll.
- **D-19** Persistence policy = explicit "Save to repo" button. No auto-debounce-commit in v0. Manual scp escape hatch remains.
- **D-20** UI surface v0 = **farmOS** (Zoy-side). Phase 28 ships data plane only — no Mission Control card.
- **D-21..D-22** Alerter coordination = Phase 29 work; Phase 28 ships topic + payload only.
- **D-23..D-25** VPD out of scope as control input; lives as derived telemetry on bridge `fc_metrics` (Phase 999.27); `T_target` reserves the future hook.

### Claude's Discretion

- High-side behavior internals (clamp + freeze integrator + bumpless re-engage) — research recommendation accepted.
- Exact mode-switch service signature, exact bridge endpoint path conventions, exact overlay-yaml location on disk — **lock during planning** (recommendations below).
- Whether to inline `set_mode` srv into `fc_msgs` or split — **recommend inline**, see D-13 implementation notes below.

### Deferred Ideas (OUT OF SCOPE)

- Active forcing modes (`force-condensation` / `force-evaporation`) — Phase 31.
- VPD-targeted closed-loop control — Phase 31+ / 999.33.
- VPD as derived telemetry on Mission Control — Phase 999.27 (bridge `fc_metrics`).
- Time-of-day scheduler — Phase 30.
- Alerter rewire to consume `current_mode` — Phase 29 / ALRT-08.
- Runtime addition of new named modes beyond fruiting/pinning — explicit deploy in v0.
- Mission Control mode-switch UI — farmOS-side per Phase 18/22 architecture.
- Auto-commit-on-debounce — v1+.
- SHT30 heater coordination during pinning — Phase 999.34.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MODE-01 | Mode registry: named bundles `(target_humidity, band_low, band_high, defend_side, T_target_optional)` as dotted-key ROS2 params; YAML-declarative | Schema in §A.1 + flat-param declaration pattern in §A.2. `fc_config.yaml` already supports dotted keys. |
| MODE-02 | Two baselines `fruiting` + `pinning` shipped with farmer-locked values (D-05/D-06) | Values locked; soak-test strategies in §Validation Architecture |
| MODE-03 | Mode switch via ROS service; takes effect on next control tick | Custom `SetMode.srv` in `fc_msgs`; service callback writes `active_mode` param; per-tick `get_parameter()` already established (Phase 27 lines 419–423) |
| MODE-04 | Publish `current_mode` topic so downstream (alerter/dashboard/scheduler) read live | `fc_msgs/msg/Mode.msg` + TRANSIENT_LOCAL on `fc1/control/current_mode` (same QoS pattern as Phase 27 telemetry trio) |
| MODE-05 | Mode definitions runtime-tunable without deploy; live + persistent paths | Bridge `POST /control/param` + `POST /control/persist`; rclnodejs SetParameters; overlay yaml loaded after `fc_config.yaml` |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Build:** `colcon build --packages-select fc_core` (and now `fc_msgs`)
- **Pi deploy:** edit → commit → push `fc1/prod` → `scripts/pi-deploy/deploy.sh` (memory `feedback_deploy_method`)
- **ROS env:** `ROS_DOMAIN_ID=69`, `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, DDS bound to `wg0` via `/etc/cyclonedds.xml` (post-2026-05-03 transport switch)
- **Service unit:** `scripts/pi-deploy/fc-core.service` — already has `Restart=always`, `After=wg-quick@wg0.service`, IPv4-on-wg0 ExecStartPre. Any launch-arg edit goes here AND in `fc.launch.py`.
- **No Co-Authored-By trailer on commits** (memory `feedback_no_coauthor`)
- **Diff repo vs Pi systemd before committing** (memory `feedback_diff_repo_vs_pi_systemd`)

## Summary

Phase 28 is **plumbing through what already exists**, not new infrastructure. The PID hot path is already live-reload-friendly (per-tick `get_parameter()`), the bridge already runs `rclnodejs`, the launch system already accepts multiple `--params-file` arguments, the deploy plumbing already handles git→pull→build→restart. The phase's net-new artefacts are: one new colcon package (`fc_msgs`), ~50 lines of band-aware error projection in `fc_controller.py`, one `on_set_parameters_callback` validator, two new bridge endpoints, one `fc.launch.py` edit to load an overlay yaml, and one `fc-core.service` no-op (the launch file owns the params-file argument).

**Primary recommendation:** Build the phase in 5 task waves: (1) `fc_msgs` package + Mode.msg + SetMode.srv as a foundation wave; (2) `fc_controller.py` mode resolution + band-aware error + bumpless re-engage on swap; (3) `current_mode` publisher + `set_mode` service + `on_set_parameters_callback` validator; (4) bridge `POST /control/param` + `POST /control/persist`; (5) overlay-yaml load in `fc.launch.py` + integration soak. Each wave has independent test surface (Validation Architecture below).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Mode schema definition (declarative source) | fc_config.yaml on Pi | runtime_overrides.yaml on Pi (overlay) | Mode is a controller-owned concept; declaring at the controller node keeps the rcl-param contract single-source |
| Mode resolution per tick | fc_controller (rclpy on Pi) | — | Control-plane decision; PID kernel reads ModeView from local param store; no off-Pi dependency in the hot path |
| Custom interfaces (`Mode.msg`, `SetMode.srv`) | fc_msgs (new colcon ament_cmake package on Pi) | — | ROS2 idiomatic. Build-time generated; runtime `.so` shipped to bridge as well via tailnet-installed Jazzy |
| Mode switching (origin: farmer) | farmOS UI (off-Pi, separate repo) | bridge HTTP layer (elder-plops) | Per Phase 18/22 architecture (memory `project_phase18_22_farmos_proxy_architecture`); farmOS owns presentation, bridge owns transport |
| Live param tuning transport | bridge HTTP `POST /control/param` (elder-plops) | rclnodejs SetParameters client → fc_controller | Bridge already speaks ROS2 + Express; adding endpoints is small (~50 lines) |
| Persistence (overlay yaml) | bridge writes file on fc1 via SSH or HTTP-relayed file write | git-commit via `deploy.sh` plumbing | Layer 2 = explicit "Save to repo" button per D-19 |
| Validation (allowlist + range) | bridge (allowlist) + fc_controller `on_set_parameters_callback` (range) | — | Defense in depth: bridge rejects unknown params before they hit ROS; controller rejects bad values before they hit PID |
| `current_mode` topic durability | rclpy publisher on fc_controller (Pi) | TRANSIENT_LOCAL → bridge subscriber + future alerter/scheduler subscribers | Same QoS pattern as `humidifier_duty`, `humidity_target`, `pid_output`, `sensor_health` |

## Standard Stack

### Core (already installed; no version bumps)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `rclpy` | Jazzy (3.2.1) `[CITED: docs.ros.org/en/jazzy/p/rclpy]` | Controller node + parameter callbacks | Established by Phase 27 |
| `rclnodejs` | Already in bridge `[VERIFIED: src/mission-control/bridge/src/index.js:4]` | Bridge SetParameters client | Already wired for Phase 27.1 buffer replay |
| `rosidl_default_generators` | Jazzy `[CITED: docs.ros.org/en/jazzy/Tutorials/.../Custom-ROS2-Interfaces.html]` | Generates Python bindings for `Mode.msg` + `SetMode.srv` | Standard ROS2 interface pipeline |
| `ament_cmake` | Jazzy | `fc_msgs` package buildtool | **Required** for rosidl-generated interfaces; Python `ament_python` packages cannot host msg/srv `[CITED: docs.ros.org/en/jazzy/Tutorials/.../Single-Package-Define-And-Use-Interface.html]` |
| `simple_pid` (vendored) | Phase 27 vendor | Unchanged | Already vendored in `fc_core/vendor/simple_pid` |
| Express | already in bridge | HTTP routing for `POST /control/*` | Already serves `/health`, `/farmer/summary`, `/history/*`, `/camera/*` (verified `index.js` lines 285–550) |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pyyaml` | already in `fc_core` setup.py install_requires | Read/write overlay yaml on fc1 (Layer 2 persistence write target only — rclpy itself parses params via the launch system) | Bridge-side write of `runtime_overrides.yaml`; rclpy's launch system handles the read-side via `--params-file` |
| `js-yaml` | likely already in bridge node_modules | Bridge-side YAML serialization for `POST /control/persist` | If bridge writes overlay directly; verify presence in bridge `package.json` during planning |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `fc_msgs` package | JSON-string in `std_msgs/String` for `current_mode` | Zero-typing, but loose coupling already burned us once (memory `project_alerter_rh_two_source_bug`). **Reject** per D-13. |
| Custom `SetMode.srv` | Bridge calls `SetParameters(active_mode=…)` directly (no custom srv) | Simpler — no new srv. **Considered**, see §Implementation Note below: a custom srv adds atomicity (validate + republish in one call) and is a deliberate verb the alerter/scheduler can audit-log. |
| Overlay yaml path `/etc/fc-core/` | `/var/lib/fc-core/` or alongside `fc_config.yaml` in repo working tree | See §Pitfalls #3 |
| Auto-debounce commit | Explicit "Save to repo" button (D-19) | Locked. |

**Installation:** No new packages. `fc_msgs` is a new package *inside* the workspace.

**Version verification:**
- rclpy 3.2.1 on Jazzy `[CITED: docs.ros.org/en/jazzy/p/rclpy]`
- ROS2 Jazzy custom-interfaces tutorial unchanged from earlier distros for the rosidl_generate_interfaces pattern `[CITED: docs.ros.org/en/jazzy/Tutorials/Beginner-Client-Libraries/Custom-ROS2-Interfaces.html]`
- rclnodejs latest stable supports parameter-service operations `[CITED: robotwebtools.github.io/rclnodejs/docs/0.22.3/Node.html]` `[ASSUMED: bridge's pinned version supports SetParameters via createClient — verify against bridge package.json during Wave 4]`

## Architecture Patterns

### System Architecture Diagram

```
                                    ┌────────────────────────────────────────┐
                                    │              farmOS UI                 │  (off-Pi; Zoy-owned, separate repo)
                                    │  "Switch to pinning"  / "band_low ←"   │
                                    └───────────────────┬────────────────────┘
                                                        │ HTTP
                                                        ▼
        ┌──────────────────────────────────────────────────────────────────────────┐
        │   bridge (elder-plops, Node.js, existing rclnodejs node + Express)       │
        │                                                                          │
        │   POST /control/param          POST /control/persist                     │
        │   ├─ allowlist check            ├─ allowlist check                       │
        │   ├─ value type/range           ├─ write runtime_overrides.yaml on fc1   │
        │   └─ rclnodejs SetParameters    └─ git add/commit/push fc1/prod          │
        │            │                                  │                          │
        │            ▼                                  ▼                          │
        │   /fc_controller/                       (existing deploy.sh plumbing)    │
        │      set_parameters service                                              │
        │                                                                          │
        │   Subscribes:                                                            │
        │      /fc1/control/current_mode  (TRANSIENT_LOCAL)                        │
        │      → broadcast over WS to dashboards (and future Mission Control       │
        │        read-only mode indicator, deferred)                               │
        └─────────────────┬─────────────────────────────────────────┬──────────────┘
                          │                                         │
                          │ DDS / wg0                               │ SSH (deploy)
                          ▼                                         ▼
        ┌──────────────────────────────────────────────────────────────────────────┐
        │  fc1 (Raspberry Pi)                                                      │
        │                                                                          │
        │  Boot:  systemd → fc-core.service → ros2 launch fc_core fc.launch.py     │
        │            ├─ load fc_config.yaml         (base)                         │
        │            └─ load runtime_overrides.yaml (overlay; missing-OK)          │
        │                                                                          │
        │  fc_controller (rclpy):                                                  │
        │     ┌────────────────────────────────────────────────────────────────┐   │
        │     │ control_loop tick:                                             │   │
        │     │   mode = _resolve_active_mode()  ← reads modes.{name}.* params │   │
        │     │   ┌─────────────────────────────────────────────────────────┐  │   │
        │     │   │ band-aware error projection (see §A.2)                  │  │   │
        │     │   │   rh < band_low                  → error = (rh-bL)*100  │  │   │
        │     │   │   rh > band_high & defend ∋ high → error = (rh-bH)*100  │  │   │
        │     │   │   rh > band_high & defend = low  → duty=0, freeze I, ret│  │   │
        │     │   │   in-band                        → error = 0            │  │   │
        │     │   └─────────────────────────────────────────────────────────┘  │   │
        │     │   _ramp_setpoint(dt) targets defended edge                     │   │
        │     │   bypass_threshold keys off nearest defended edge              │   │
        │     │   PID kernel UNCHANGED                                          │   │
        │     │   self._duty_pub.publish(duty)                                  │   │
        │     └────────────────────────────────────────────────────────────────┘   │
        │                                                                          │
        │  Services (NEW):                                                         │
        │     /fc_controller/set_mode  (fc_msgs/srv/SetMode)                       │
        │       → validates name ∈ declared modes, writes active_mode param,       │
        │         calls _engage_pid_bumplessly(), republishes current_mode         │
        │                                                                          │
        │  Parameter callback (NEW):                                               │
        │     on_set_parameters_callback                                           │
        │       → validates band invariants (0 ≤ band_low < band_high ≤ 1)         │
        │       → returns SetParametersResult(successful, reason)                  │
        │       → on success of band-edge param: republishes current_mode (D-15)   │
        │                                                                          │
        │  Publishers:                                                             │
        │     /fc1/actuators/humidifier_duty    (existing, TRANSIENT_LOCAL)        │
        │     /fc1/control/humidity_target      (existing, TRANSIENT_LOCAL)        │
        │     /fc1/control/pid_output           (existing, TRANSIENT_LOCAL)        │
        │     /fc1/control/current_mode         (NEW, TRANSIENT_LOCAL, fc_msgs/Mode)│
        └──────────────────────────────────────────────────────────────────────────┘
```

Data flow primary use case (mode switch from farmOS):
1. Farmer taps "Switch to pinning" in farmOS.
2. farmOS POSTs to bridge `/control/param` with `{node, param: "active_mode", value: "pinning"}`.
3. Bridge allowlist permits → rclnodejs SetParameters → fc_controller param callback validates `pinning ∈ modes.*` → param store updated.
4. Next control tick (≤1s): `_resolve_active_mode()` returns pinning's ModeView; bumpless re-engage; publishes new `current_mode` (TRANSIENT_LOCAL → late subscribers see new state on subscribe).
5. Bridge subscribes to `current_mode`, broadcasts via WS to farmOS for confirmation.

### Recommended Project Structure

```
src/chambers/
├── fc-core/                       # existing — modifications only
│   ├── fc_core/
│   │   └── fc_controller.py       # +50 lines: _resolve_active_mode, band error, on_set_parameters_callback, set_mode service
│   ├── config/
│   │   └── fc_config.yaml         # +modes block (D-05/D-06)
│   ├── launch/
│   │   └── fc.launch.py           # +runtime_overrides.yaml as 2nd --params-file (optional)
│   └── package.xml                # +depend fc_msgs
└── fc-msgs/                       # NEW colcon ament_cmake package
    ├── CMakeLists.txt             # rosidl_generate_interfaces(${PROJECT_NAME} "msg/Mode.msg" "srv/SetMode.srv" DEPENDENCIES builtin_interfaces)
    ├── package.xml                # buildtool_depend rosidl_default_generators; exec_depend rosidl_default_runtime; member_of_group rosidl_interface_packages
    ├── msg/
    │   └── Mode.msg
    └── srv/
        └── SetMode.srv

src/mission-control/bridge/src/
├── index.js                       # +POST /control/param, +POST /control/persist, +/fc1/control/current_mode subscriber
├── control_param.js               # NEW: allowlist + value-validation helpers (testable in isolation)
└── control_persist.js             # NEW: overlay-yaml read/write + git plumbing (testable; mock fs+exec)

scripts/pi-deploy/
├── fc-core.service                # No edit needed — launch file owns params-file args
└── deploy.sh                      # No edit needed — already builds workspace, fc_msgs picked up by colcon
```

### Pattern 1: Custom interfaces in a single ament_cmake package
**What:** Define `Mode.msg` and `SetMode.srv` together in `fc_msgs` (NOT in `fc_core`, which is `ament_python` and cannot host rosidl-generated interfaces).
**When to use:** Always — ROS2 idiomatic; alerter (Phase 29) and scheduler (Phase 30) will share the package.

**`fc_msgs/CMakeLists.txt`** (key lines):
```cmake
# Source: docs.ros.org/en/jazzy/Tutorials/Beginner-Client-Libraries/Custom-ROS2-Interfaces.html
cmake_minimum_required(VERSION 3.8)
project(fc_msgs)

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Mode.msg"
  "srv/SetMode.srv"
  DEPENDENCIES builtin_interfaces
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
```

**`fc_msgs/package.xml`** (key lines):
```xml
<buildtool_depend>ament_cmake</buildtool_depend>
<buildtool_depend>rosidl_default_generators</buildtool_depend>
<depend>builtin_interfaces</depend>
<exec_depend>rosidl_default_runtime</exec_depend>
<member_of_group>rosidl_interface_packages</member_of_group>
<export>
  <build_type>ament_cmake</build_type>
</export>
```

**`fc_msgs/msg/Mode.msg`:**
```
string name
float32 target_humidity
float32 band_low
float32 band_high
string defend_side
float32 t_target
builtin_interfaces/Time effective_since
string source
```

**`fc_msgs/srv/SetMode.srv`:**
```
string name
---
bool success
string reason
fc_msgs/Mode active_mode
```

### Pattern 2: rclpy `on_set_parameters_callback` for validation
**What:** Pre-set callback that returns `SetParametersResult(successful, reason)`. Receives a list of `Parameter` objects.
**When to use:** Whenever Layer 1 SetParameters lands a value that needs invariant-checking (band ordering, side enum, T_target NaN-or-(0,40)).
**Atomicity caveat:** `[VERIFIED: github.com/ros2/rclcpp/issues/1550]` rclpy's pre-set callback receives the *whole batch* and returns a *single* `SetParametersResult`. **If any param in the batch fails, the entire batch is rejected.** This is the desired behavior here (band_low + band_high should travel together). However, when a client sends multiple params in *separate* calls, each call gets its own batch; sequence band_low → band_high transiently violates `band_low < band_high`. **Mitigation:** clients (bridge `POST /control/param`) submit band edits as one batch (`{params: [{name: "modes.pinning.band_low", value: 0.78}, {name: "modes.pinning.band_high", value: 0.99}]}`) or the callback is tolerant of staged updates by checking against *the new value of the param being set* against *current other-edge value*.

**Source:** docs.ros.org/en/jazzy/p/rclpy/rclpy.node.html#rclpy.node.Node.add_on_set_parameters_callback

```python
# In fc_controller.__init__:
from rcl_interfaces.msg import SetParametersResult
self.add_on_set_parameters_callback(self._validate_params)

def _validate_params(self, params):
    for p in params:
        # Band-edge invariants
        if p.name.startswith('modes.') and p.name.endswith('.band_low'):
            sibling_high = self.get_parameter(p.name.rsplit('.',1)[0] + '.band_high').value
            if not (0.0 <= p.value < sibling_high <= 1.0):
                return SetParametersResult(successful=False, reason=f'{p.name}: must satisfy 0<=band_low<band_high<=1')
        if p.name.startswith('modes.') and p.name.endswith('.band_high'):
            sibling_low = self.get_parameter(p.name.rsplit('.',1)[0] + '.band_low').value
            if not (0.0 <= sibling_low < p.value <= 1.0):
                return SetParametersResult(successful=False, reason=f'{p.name}: must satisfy 0<=band_low<band_high<=1')
        if p.name.startswith('modes.') and p.name.endswith('.defend_side'):
            if p.value not in ('low','high','both'):
                return SetParametersResult(successful=False, reason=f'{p.name}: must be low|high|both')
        if p.name == 'active_mode':
            # Must be in declared modes set
            declared = self._declared_mode_names()  # introspect from current params
            if p.value not in declared:
                return SetParametersResult(successful=False, reason=f'active_mode={p.value!r} not in declared modes {sorted(declared)}')
    return SetParametersResult(successful=True)
```

### Pattern 3: Multiple `--params-file` for overlay
**What:** ROS2 launch's `Node(parameters=[...])` accepts a list; each entry can be a yaml-file path. Last file wins for duplicate keys `[VERIFIED: ros2/rclcpp#953 — "command line order is respected; later overrides earlier"]`.
**Pitfall:** If `runtime_overrides.yaml` doesn't exist, `ros2 launch` errors "Couldn't parse params file" `[VERIFIED: WebSearch result, multiple SO/answers.ros entries]`. Must guard:

```python
# fc.launch.py — discretion (not locked in CONTEXT)
import os
from ament_index_python.packages import get_package_share_directory
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    pkg_share = get_package_share_directory('fc_core')
    config_file = os.path.join(pkg_share, 'config', 'fc_config.yaml')
    OVERLAY_PATH = os.environ.get('FC_RUNTIME_OVERLAY', '/etc/fc-core/runtime_overrides.yaml')

    controller_params = [LaunchConfiguration('config_file')]
    if os.path.exists(OVERLAY_PATH):
        controller_params.append(OVERLAY_PATH)

    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=config_file),
        Node(
            package='fc_core', executable='fc_controller', name='fc_controller',
            parameters=controller_params,   # base + optional overlay
            output='screen',
        ),
        # ... other nodes unchanged (overlay only applies to fc_controller per D-17)
    ])
```

**Caveat — declared-vs-overridden:** `[ASSUMED]` rclpy ignores overlay-file entries for params not declared by the node *unless* `automatically_declare_parameters_from_overrides=True` is set on the Node. Recommendation: keep the existing strict declaration model; the overlay yaml only carries values for already-declared params (band edges, target, active_mode). New mode = deploy (per D-03), so overlay never declares new `modes.*` keys.

### Pattern 4: rclnodejs SetParameters from bridge
**What:** Bridge creates a service client to `/fc_controller/set_parameters` (the standard parameter-service endpoint every rclpy node exposes) and POSTs a `rcl_interfaces/srv/SetParameters` request.
**Signature:** `node.createClient('rcl_interfaces/srv/SetParameters', '/fc_controller/set_parameters')`. The request shape is `{parameters: [{name, value: {type, <type_specific_field>}}]}`. `type` is an int enum (1=BOOL, 2=INTEGER, 3=DOUBLE, 4=STRING, …). `[CITED: robotwebtools.github.io/rclnodejs/docs/0.22.3/Node.html]` `[ASSUMED: exact request shape — verify by inspecting `rcl_interfaces/msg/Parameter` after rclnodejs codegen at planning time; type-coercion float vs int is a known footgun]`.

```javascript
// Source: rclnodejs Node.createClient docs (0.22.3) — exact API may vary by pinned version
const setParamClient = rosNode.createClient(
  'rcl_interfaces/srv/SetParameters',
  '/fc_controller/set_parameters'
);
const req = {
  parameters: [{
    name: 'active_mode',
    value: { type: 4, string_value: 'pinning' }   // type 4 = STRING
  }]
};
setParamClient.sendRequest(req, (resp) => {
  // resp.results: [{successful, reason}, ...]
});
```

**Pitfall — float vs int coercion:** JS `0.96` is a Number; if the param is declared as DOUBLE the request must use `type: 3, double_value: 0.96`. If the controller declares `target_humidity` as DOUBLE but bridge sends `type: 2, integer_value: 1`, rclpy rejects it. Allowlist must carry the *expected type* per param.

### Anti-Patterns to Avoid

- **JSON-string in std_msgs/String for `current_mode`** — already considered, rejected per D-13.
- **Polling Timescale for mode state** — couples control plane to telemetry sink; rejected per D-18.
- **Auto-debounce-commit on every slider drag** — spammy git history; rejected per D-19.
- **Putting overlay yaml in the repo working tree on fc1** — git-clobber risk; deploy.sh's `git pull` would either reject (unstaged changes) or overwrite. Keep overlay outside the repo (`/etc/fc-core/...`); commit a *copy* into the repo separately at "Save to repo" time.
- **Declaring `modes` as a dict-typed param** — rclpy has no native dict params; flat dotted keys only (D-03). Already locked.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Live param tuning protocol | Custom WS/HTTP RPC for "set this controller value" | Standard ROS2 `/<node>/set_parameters` service via rclnodejs | Already exists; fires `on_set_parameters_callback`; `ros2 param set` interoperates for ops |
| Param validation framework | Custom JSON schema per param | rclpy `ParameterDescriptor` + `on_set_parameters_callback` | Native; controller-local; one source of truth |
| Mode message serialization | JSON-in-String over `current_mode` | Custom `fc_msgs/Mode.msg` | Type-safe; alerter/scheduler get free codegen; locked per D-13 |
| Overlay-yaml hot-reload | Custom file watcher → SIGHUP loop | rclpy reads overlay only at launch; runtime tuning goes through SetParameters; persistence is a separate explicit step | Two-layer split (D-17) cleanly separates "live now" from "stick after reboot" |
| Multi-file params merge | Hand-rolled YAML deep-merge in launch | ROS2 launch's native `parameters=[file1, file2]` — last wins | Built-in; no surprises |
| Mode-switch confirmation/audit | Custom audit log | `current_mode.source` field (D-13) + ROS2 logging at INFO | Free; replayable from `journalctl -u fc-core` |

**Key insight:** Phase 28 is almost entirely "use what's already there with one new schema." The only *novel* artefact is `fc_msgs` (and that's standard ROS2 boilerplate). Resist the urge to invent.

## Runtime State Inventory

> Phase 28 is a feature add, not a rename. This section is included because the controller's param store is mutable runtime state with a non-trivial lifecycle.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | None — Phase 28 introduces no new persistent stores. The overlay yaml is the only file artefact, and it's purely a derivative of in-memory param state. | No data migration. |
| Live service config | fc_controller's parameter store on fc1 (in-memory, populated at launch from yaml). After Phase 28: `active_mode` is the canonical "current mode" source-of-truth in memory. | None — first deploy seeds the store from `fc_config.yaml` via the existing `fc-update.service` pull. |
| OS-registered state | `fc-core.service` systemd unit. ExecStart unchanged (launch file owns params-file args). | None — verified `fc-core.service` ExecStart is `ros2 launch fc_core fc.launch.py`; no edit. |
| Secrets/env vars | None new in fc-core. Bridge gets `FC_RUNTIME_OVERLAY_PATH` and `FC_PARAM_ALLOWLIST_PATH` env candidates (discuss during planning). | Document in compose env if used. |
| Build artifacts | `fc_msgs` adds `install/fc_msgs/` build output. `colcon build` picks it up automatically. | First deploy must `colcon build` the workspace (not `--packages-select fc_core`); update deploy.sh OR confirm full-workspace build is the default — deploy.sh uses `--packages-select fc_core`, **needs change to also build fc_msgs**. |

**Critical action — deploy.sh edit:** `[VERIFIED: deploy.sh:19]` Current build line is `colcon build --packages-select fc_core`. After Phase 28, this must become `colcon build --packages-select fc_msgs fc_core` (order matters — fc_msgs is a build dependency of fc_core's `package.xml` via the new `<depend>fc_msgs</depend>`). Plan must include this edit.

## Common Pitfalls

### Pitfall 1: ament_python cannot host msg/srv
**What goes wrong:** Adding `msg/Mode.msg` to `fc_core` (an ament_python package) fails to generate Python bindings.
**Why it happens:** rosidl_generate_interfaces requires ament_cmake. `[CITED: docs.ros.org/en/jazzy/.../Single-Package-Define-And-Use-Interface.html]` "It is, and can only be, an ament_cmake package."
**How to avoid:** Put interfaces in a separate ament_cmake package (`fc_msgs`).
**Warning signs:** `colcon build` succeeds but `from fc_core.msg import Mode` fails at runtime; or rosidl files silently ignored.

### Pitfall 2: TRANSIENT_LOCAL is in-process, not on-disk
**What goes wrong:** Operator assumes `current_mode` survives a controller restart.
**Why it happens:** TRANSIENT_LOCAL persists in the *publisher's* memory for the *publisher's lifetime* `[VERIFIED: docs.vulcanexus.org persistency tutorial; ros2/ros2#464]`. After restart, the publisher republishes whatever the controller computes from the param store on startup — which after first deploy will be `active_mode = fruiting` from the base yaml, *unless* the overlay yaml has been written with `active_mode: pinning`.
**How to avoid:** Cross-restart persistence belongs to Layer 2 (overlay yaml), not to QoS. If the farmer wants pinning to survive a reboot, they must hit "Save to repo" or accept the new explicit "Save current as default" pattern.
**Warning signs:** Mode silently reverts to fruiting after a Pi reboot — diagnose by checking `runtime_overrides.yaml` content and `journalctl -u fc-core | grep active_mode`.

### Pitfall 3: Overlay-yaml file location & permissions
**What goes wrong:** Bridge can't write to `/etc/fc-core/...`; or systemd can't read it; or `git pull` clobbers it.
**Why it happens:** `/etc/` is root-owned by default; bridge runs in container on elder-plops, has SSH-only access to fc1.
**How to avoid:** Recommended path = `/var/lib/fc-core/runtime_overrides.yaml` `[ASSUMED]`:
- Already used as `db_path: /var/lib/fc-core/buffer.sqlite` (`fc_config.yaml:66`) — directory exists, owner = `ubuntu` (per `fc-core.service:16` ExecStartPre `install -d -o ubuntu -g ubuntu /var/lib/fc-core`).
- Lives outside the repo working tree → no `git pull` collision.
- Write transport: bridge uses SSH-as-ubuntu (same channel as `deploy.sh`). Or bridge writes locally on elder-plops and `deploy.sh` rsyncs.
**Lock during planning:** path + write transport. Recommendation: `/var/lib/fc-core/runtime_overrides.yaml`, written via SSH from bridge, copy-into-repo on "Save to repo" via existing deploy.sh plumbing.
**Warning signs:** "Couldn't parse params file" at controller boot → check overlay file is valid YAML and readable by `ubuntu`.

### Pitfall 4: Param-callback batch atomicity vs. staged band updates
**What goes wrong:** Bridge sends `band_low: 0.78` and then `band_high: 0.99` as two separate SetParameters calls. Between the two, if old `band_high` was 0.80, the first call transiently violates `band_low < band_high` (0.78 < 0.80 OK actually — OK in this example). But if old `band_low` was 0.95 and we want to lower to 0.78 then raise band_high too, the first call alone is fine in this direction; the failure mode is the *opposite*: raising band_low above current band_high.
**Why it happens:** rclpy validates each batch independently `[VERIFIED: ros2/rclcpp#1550 — callback returns single SetParametersResult per batch]`. No transactional view across calls.
**How to avoid:** Bridge submits coupled edits as **one batched SetParameters call** with all related params in `parameters[]`. The callback validates the whole batch atomically — entire batch accepted or rejected.
**Warning signs:** UI shows "saved" but band invariants violated at next tick → bridge silently sent params one-at-a-time.

### Pitfall 5: deploy.sh `--packages-select fc_core` skips fc_msgs
**What goes wrong:** First deploy succeeds for fc_core source but fc_msgs interfaces never built; controller imports fail at runtime on Pi.
**Why it happens:** `[VERIFIED: scripts/pi-deploy/deploy.sh:19]` deploy.sh selects only fc_core.
**How to avoid:** Update deploy.sh to `--packages-select fc_msgs fc_core` (msgs first; fc_core depends on it). Plan must include this edit. Alternative: drop `--packages-select` entirely and build the whole workspace; risk = pulling unrelated changes into the build.
**Warning signs:** `ImportError: cannot import name 'Mode' from 'fc_msgs.msg'` in `journalctl -u fc-core` after deploy.

### Pitfall 6: Mode C bypass with wide bands stays asleep when you want it awake
**What goes wrong:** Pinning has midpoint 0.85 with band_low 0.90, band_high 0.99. If RH crashes to 0.60, `|rh - 0.85| = 0.25` triggers Mode C, BUT if computed against midpoint not nearest defended edge — and midpoint is *inside* the band of [0.90, 0.99] which is geometrically inverted, this is a config-error landmine.
**Why it happens:** Operator chose `target=0.85` cosmetic but band starts at 0.90. The midpoint is *below* `band_low`, which is unusual.
**How to avoid:** D-11 already locks "Mode C bypass keys off nearest defended edge." But also: validate at param-callback time that `target_humidity` is within `[band_low, band_high]` — or remove `target_humidity` from the pinning case entirely (D-06 says it's "cosmetic"). **Recommendation:** Add a soft warning in `_validate_params` if `target` is outside `[band_low, band_high]`, but don't reject (it's farmer's call). Log at WARN at startup if any active mode has `target` out-of-band.
**Warning signs:** Pinning enters Mode C at unexpected RH; or never enters Mode C when RH is genuinely pathological.

### Pitfall 7: rclpy `automatically_declare_parameters_from_overrides` interaction
**What goes wrong:** `[VERIFIED: github.com/ros2/rclpy/issues/1167 + #829]` Setting params declared in YAML but not in code can fail silently or behave differently across rclpy versions.
**Why it happens:** Strict-declaration mode (default) ignores YAML keys with no `declare_parameter` counterpart.
**How to avoid:** Keep strict mode. Declare all `modes.<name>.<field>` for every shipped mode at `__init__` time. New modes = code change = deploy (already locked D-03).
**Warning signs:** Adding a new mode in yaml only and finding it absent from `get_parameter` calls.

### Pitfall 8: Memory `project_bridge_buffer_replay_cursor_bug` is in the same file
**What goes wrong:** Phase 28 work in `bridge/src/index.js` accidentally touches the buffer-replay cursor logic at line 613.
**Why it happens:** Same file, different concerns; the bug is open and unrelated.
**How to avoid:** Per CONTEXT canonical_refs note — Phase 28 endpoints land in a different code path. Keep `POST /control/*` handlers in their own helper modules (`control_param.js`, `control_persist.js`) imported into index.js. Don't refactor live-path replay code as a side trip.

## Code Examples

### Example 1: `_resolve_active_mode` and band-aware error
```python
# Source: derived from research/2026-05-06-phase28-mode-schema-and-runtime-config.md A.2
# (Verified pattern; pseudocode adapted for current fc_controller.py PID block at lines 415–441)

from dataclasses import dataclass
from math import isnan

@dataclass
class ModeView:
    name: str
    target: float
    band_low: float
    band_high: float
    defend_side: str   # 'low' | 'high' | 'both'
    t_target: float    # NaN when unset

def _resolve_active_mode(self) -> ModeView:
    name = self.get_parameter('active_mode').value
    return ModeView(
        name=name,
        target=self.get_parameter(f'modes.{name}.target_humidity').value,
        band_low=self.get_parameter(f'modes.{name}.band_low').value,
        band_high=self.get_parameter(f'modes.{name}.band_high').value,
        defend_side=self.get_parameter(f'modes.{name}.defend_side').value,
        t_target=self.get_parameter(f'modes.{name}.t_target').value,
    )

# Inside control_loop, replacing lines 423–425:
mode = self._resolve_active_mode()
self._ramp_setpoint_to_band(dt, mode)   # ramps toward defended edge per D-10
rh = self.current_humidity

if rh < mode.band_low:
    error_pct = (rh - mode.band_low) * 100.0
elif rh > mode.band_high:
    if mode.defend_side in ('high', 'both'):
        error_pct = (rh - mode.band_high) * 100.0
    else:
        # pinning: don't fight upward; clamp duty + freeze integrator + bumpless re-engage on return
        if self._pid.auto_mode:
            self._pid.set_auto_mode(False)
        self._publish_duty(0.0)
        # still publish telemetry trio for Mission Control visibility
        self._humidity_target_pub.publish(Float32(data=float(self._effective_setpoint)))
        self._pid_output_pub.publish(Float32(data=0.0))
        return
else:
    error_pct = 0.0

# bypass_threshold keyed off NEAREST DEFENDED edge (D-11)
nearest_defended = (
    mode.band_low if rh < mode.band_low else
    mode.band_high if (rh > mode.band_high and mode.defend_side in ('high','both')) else
    mode.band_low  # in-band: distance to floor (which is always defended)
)
edge_distance = abs(rh - nearest_defended)
bypass_pct = self.get_parameter('bypass_threshold').value * 100.0
# … rest of PID branch unchanged
```

### Example 2: `set_mode` service handler
```python
# Source: ROS2 Jazzy Custom-ROS2-Interfaces tutorial pattern
from fc_msgs.srv import SetMode
from rclpy.parameter import Parameter

# In __init__:
self._set_mode_srv = self.create_service(
    SetMode, 'set_mode', self._handle_set_mode
)

def _handle_set_mode(self, request, response):
    declared = self._declared_mode_names()
    if request.name not in declared:
        response.success = False
        response.reason = f'unknown mode {request.name!r}; declared: {sorted(declared)}'
        return response

    # Use SetParameters internally so on_set_parameters_callback fires
    result = self.set_parameters([Parameter('active_mode', Parameter.Type.STRING, request.name)])
    if not result[0].successful:
        response.success = False
        response.reason = result[0].reason
        return response

    # bumpless re-engage with current duty (D-12)
    self._engage_pid_bumplessly()
    # republish current_mode (D-15)
    self._publish_current_mode(source='service_call')

    response.success = True
    response.reason = ''
    response.active_mode = self._build_mode_msg(self._resolve_active_mode(), source='service_call')
    return response
```

### Example 3: Bridge `POST /control/param`
```javascript
// Source: rclnodejs Node.createClient docs; Express patterns from src/mission-control/bridge/src/index.js
const ALLOWLIST = require('./control_param.js').ALLOWLIST;  // module-local, see Pitfall 4

app.post('/control/param', express.json(), async (req, res) => {
  const { node, param, value } = req.body;
  if (node !== 'fc_controller') return res.status(400).json({error: 'node not allowlisted'});
  const spec = ALLOWLIST[param];
  if (!spec) return res.status(400).json({error: `param ${param} not allowlisted`});
  const validation = spec.validate(value);
  if (!validation.ok) return res.status(400).json({error: validation.reason});

  try {
    const setParamClient = rosNode.createClient(
      'rcl_interfaces/srv/SetParameters',
      `/${node}/set_parameters`
    );
    const req_msg = {
      parameters: [{ name: param, value: spec.toParamValue(value) }]
    };
    const resp = await new Promise((resolve, reject) =>
      setParamClient.sendRequest(req_msg, (r) => r ? resolve(r) : reject(new Error('no response'))));
    const result = resp.results[0];
    if (!result.successful) return res.status(422).json({error: result.reason});
    res.json({ok: true, applied: {param, value}});
  } catch (e) {
    res.status(500).json({error: e.message});
  }
});
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Bang-bang on/off humidifier | PID + slow-PWM duty | Phase 27 (2026-05-02) | Phase 28 wraps this in mode abstraction |
| `target_humidity` + `humidity_tolerance` scalars | `(target, band_low, band_high, defend_side, T_target)` mode bundle | Phase 28 (this) | New `humidity_tolerance` becomes redundant once a mode is active; D-04 keeps it as fallback |
| Alerter env-fed RH thresholds (`HUMIDITY_TARGET`/`HUMIDITY_BAND`) | Alerter subscribes to `current_mode` | Phase 29 (next) | Closes memory `project_alerter_rh_two_source_bug` — Phase 28 publishes the topic, Phase 29 retires the env |
| `ros2 param set` manual + commit later | `POST /control/param` + `POST /control/persist` | Phase 28 (this) | Memory `feedback_humidity_runtime_param` becomes first-class |

**Deprecated/outdated:**
- REQUIREMENTS.md MODE-01 wording `(target_RH, band, duty-cycle behavior)` — retired by D-01.
- Memory `project_phase28_mode_schema_seed004_conflict` — closed by D-01..D-04 (verified MEMORY.md notes "RESOLVED 2026-05-07").

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest` via `colcon test --packages-select fc_core fc_msgs` `[VERIFIED: src/chambers/fc-core/setup.cfg, fc-core/test/]` |
| Config file | `setup.cfg` (fc_core); `package.xml` test_depend python3-pytest |
| Quick run command | `pytest src/chambers/fc-core/fc_core/test/test_controller.py -x` |
| Full suite command | `colcon test --packages-select fc_core fc_msgs && colcon test-result --verbose` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MODE-01 | Schema: load `fc_config.yaml` with `modes.fruiting.*` + `modes.pinning.*` block; `_resolve_active_mode()` returns ModeView matching declared values | unit | `pytest test/test_controller_modes.py::test_resolve_active_mode_fruiting -x` | ❌ Wave 0 |
| MODE-01 | Schema: back-compat — if no `modes:` block, derive default `fruiting` from `target_humidity` + `humidity_tolerance` (D-04) | unit | `pytest test/test_controller_modes.py::test_back_compat_default_fruiting -x` | ❌ Wave 0 |
| MODE-01 | Param-callback rejects `band_low >= band_high` | unit | `pytest test/test_controller_modes.py::test_param_callback_band_invariant -x` | ❌ Wave 0 |
| MODE-01 | Param-callback rejects `defend_side` not in {low,high,both} | unit | `pytest test/test_controller_modes.py::test_param_callback_defend_side_enum -x` | ❌ Wave 0 |
| MODE-01 | Param-callback rejects `active_mode` not in declared set | unit | `pytest test/test_controller_modes.py::test_param_callback_unknown_mode -x` | ❌ Wave 0 |
| MODE-02 | `fruiting` v0 preserves HUMID-04 contract: at humidity=0.96, target=0.96 → duty stays bounded; at humidity=0.93 → PID demands non-zero duty (existing soak still PASS) | unit + replay-soak | existing `test_controller.py::test_pid_normal_operation` should still pass; add `test_controller_modes.py::test_fruiting_preserves_humid04` | partial — extend Wave 0 |
| MODE-02 | `pinning` v0: `defend_side=low` clamps duty to 0 when RH > band_high (0.99) | unit | `pytest test/test_controller_modes.py::test_pinning_clamps_on_high_excursion -x` | ❌ Wave 0 |
| MODE-02 | `pinning` v0: when RH < 0.90 floor, PID demands duty (defend_side: low still defends floor) | unit | `pytest test/test_controller_modes.py::test_pinning_defends_floor -x` | ❌ Wave 0 |
| MODE-03 | `set_mode` service: switching fruiting → pinning takes effect within ≤1 control_interval; current duty unchanged at swap (bumpless) | integration | `pytest test/test_controller_modes.py::test_set_mode_service_takes_effect_in_one_tick -x` | ❌ Wave 0 |
| MODE-03 | `set_mode` service: unknown mode name → response.success=False, no param mutation | unit | `pytest test/test_controller_modes.py::test_set_mode_rejects_unknown -x` | ❌ Wave 0 |
| MODE-03 | Bumpless transfer: mode-swap during high-duty operation does not produce duty glitch (delta < 0.1 between pre-swap and post-swap tick) | integration | `pytest test/test_controller_modes.py::test_mode_swap_bumpless -x` | ❌ Wave 0 |
| MODE-04 | Subscriber to `/fc1/control/current_mode` receives full `Mode` payload matching active config | integration (rclpy spin in fixture) | `pytest test/test_controller_modes.py::test_current_mode_topic_payload -x` | ❌ Wave 0 |
| MODE-04 | TRANSIENT_LOCAL: late subscriber gets last `current_mode` value on subscribe | integration | `pytest test/test_controller_modes.py::test_current_mode_late_subscribe -x` | ❌ Wave 0 |
| MODE-04 | Republish on every band-edge change (`modes.fruiting.band_low` SetParameters → new `current_mode` published) | integration | `pytest test/test_controller_modes.py::test_current_mode_republishes_on_band_change -x` | ❌ Wave 0 |
| MODE-05 | `POST /control/param` updates live param; controller reads new value next tick | integration (bridge + fc_controller in fixture) | `node --test test/control_param.test.js` (bridge-side) | ❌ Wave 0 |
| MODE-05 | `POST /control/param` rejects non-allowlisted param (e.g. `humidifier_pin`) with 400 | unit | `node --test test/control_param.test.js` | ❌ Wave 0 |
| MODE-05 | `POST /control/persist` writes overlay yaml on fc1 with the new value | integration | `node --test test/control_persist.test.js` (mock SSH or local fs) | ❌ Wave 0 |
| MODE-05 | After persist + restart fc-core, overlay value wins over base yaml | manual / soak | manual: `curl -X POST .../control/persist -d '{...band_low...0.945→0.94}' && ssh fc1 sudo systemctl restart fc-core && ros2 param get /fc_controller modes.fruiting.band_low` | manual-only |
| MODE-05 | Overlay yaml missing → fc-core launches successfully (no error) | manual | manual: `ssh fc1 sudo rm /var/lib/fc-core/runtime_overrides.yaml && sudo systemctl restart fc-core` | manual-only |

### Sampling Rate
- **Per task commit:** `pytest src/chambers/fc-core/fc_core/test/test_controller_modes.py -x` (sub-30s expected; mode tests should not load full ros stack — use rclpy `Node` in unit-test fixture)
- **Per wave merge:** `colcon test --packages-select fc_msgs fc_core && colcon test-result --verbose`
- **Phase gate:** Full suite green + manual MODE-05 persistence test on fc1 before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `src/chambers/fc-core/fc_core/test/test_controller_modes.py` — covers MODE-01..MODE-04
- [ ] `src/chambers/fc-msgs/test/test_msg_codegen.py` (or equivalent compile-test) — verifies `from fc_msgs.msg import Mode` and `from fc_msgs.srv import SetMode` import successfully
- [ ] `src/mission-control/bridge/test/control_param.test.js` — covers Layer 1 (allowlist + SetParameters round-trip with mocked rclnodejs client)
- [ ] `src/mission-control/bridge/test/control_persist.test.js` — covers Layer 2 (yaml write + git commit, with mocked fs/exec)
- [ ] Soak harness for pinning floor defense: 30-min sim with RH ramp 0.99 → 0.85 → verify duty stays 0 above band_high then ramps up below band_low. Wall-clock acceptable since chamber tests already use sim sensors via `actuator_simulation_mode`.

## Security Domain

> Security enforcement enabled (no explicit `false` in config). Phase 28 changes the bridge's HTTP attack surface and the controller's runtime-mutation surface — non-trivial.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (limited) | Bridge is on tailscale/wg0 only; no public exposure. No new auth this phase. Document tailnet trust as the bound. |
| V3 Session Management | no | No sessions; HTTP requests are stateless |
| V4 Access Control | yes | Allowlist on bridge `POST /control/param` is the access-control layer. Allowlist excludes: `humidifier_pin`, `light_pin`, `dht_pin`, `fan_pwm_*`, `actuator_simulation_mode`, `sensor_simulation_mode`, `*_offset_*`, anything not in a curated whitelist of band edges + targets + `active_mode` + PID gains |
| V5 Input Validation | yes | Bridge validates type+range before SetParameters; controller `on_set_parameters_callback` validates invariants (band ordering, enum values, mode-name membership). Defense in depth. |
| V6 Cryptography | no | No new crypto; tailnet handles transport encryption |

### Known Threat Patterns for ROS2-rclpy + Express bridge

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Setting `humidifier_pin` to bogus GPIO number → controller writes to wrong pin → physical damage potential | Tampering | Allowlist excludes hardware-pin params (locked) |
| Setting `actuator_simulation_mode=true` in production → controller stops touching hardware silently | Tampering / Denial-of-control | Allowlist excludes simulation-mode params |
| Setting `pid_kp` to insane value → runaway humidifier | Tampering | Allowlist includes pid_kp/ki/kd but with range bounds (e.g. `0 ≤ pid_kp ≤ 5.0`); controller's `on_set_parameters_callback` enforces |
| Persisting bad overlay yaml → fc-core fails to launch on next reboot → silent loss of control | Denial of Service | (a) pre-flight validate yaml on bridge before write; (b) `ExecStartPre` could yaml-lint the overlay; (c) fail-open to base config if overlay parse fails — but ROS2 launch fails hard on bad yaml, so we can't fail-open transparently. Mitigation: `POST /control/persist` writes to a `.tmp` file, atomically renames, and the bridge keeps the previous version as `.bak` for one-step revert |
| Race between two `POST /control/param` calls for related params (band_low, band_high) leaving invariant violated mid-flight | Tampering / data integrity | Bridge submits coupled edits as one batched SetParameters call (Pitfall 4) |
| Allowlist file tampered to add dangerous param | Tampering | Allowlist is hardcoded in `control_param.js` (in repo, code-reviewed) — not loaded from disk |

**Threat note:** Bridge is on `tailscale-only access`. farmOS proxies. No public internet exposure. Trust boundary = tailnet membership. Allowlist + range validation is "defense in depth against an authenticated farmer-app caller" — not against a network attacker.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| ROS2 Jazzy | controller + msgs build on Pi | ✓ | rclpy 3.2.1 | — |
| `rosidl_default_generators` | fc_msgs build | ✓ (part of Jazzy desktop) | Jazzy | — |
| `ament_cmake` | fc_msgs build | ✓ | Jazzy | — |
| `rclnodejs` in bridge container | Layer 1 SetParameters call | ✓ `[VERIFIED: bridge/src/index.js:4]` | unknown pinned ver | — |
| `js-yaml` in bridge | Layer 2 overlay write | `[ASSUMED]` likely; verify in bridge package.json | — | use `yaml` npm or hand-format if not present |
| SSH from elder-plops bridge container to fc1 ubuntu user | Layer 2 file write | `[ASSUMED]` — bridge container would need ssh key + `wg0` reachability | — | Alternative: bridge writes to a local mount, separate sync agent on Pi pulls — adds complexity, reject |
| Write access to `/var/lib/fc-core/` on fc1 | Layer 2 overlay path | ✓ — owned by `ubuntu`; `fc-core.service` ExecStartPre creates it | — | — |
| Build access on Pi (deploy.sh) | First deploy of fc_msgs | ✓ | — | — |

**Missing dependencies with no fallback:** None blocking — but the bridge-container → fc1 SSH path is `[ASSUMED]` and **MUST be verified during planning** (Wave 0 spike). Compose stack runs on elder-plops; bridge container needs an outbound SSH credential to write to fc1. If absent, Layer 2 architecture must change (e.g. bridge POSTs the overlay payload to fc_buffer's HTTP server, which writes locally — simpler, no SSH credentialing inside the container).

**Recommended pre-planning verification:**
```bash
docker exec mushy-bridge-1 ssh -o BatchMode=yes ubuntu@172.16.10.5 'echo ok && id'   # confirms key present
docker exec mushy-bridge-1 ssh ubuntu@172.16.10.5 'ls -la /var/lib/fc-core/'         # confirms write target
```
If this fails → **architectural pivot in planning:** Layer 2 transport becomes "bridge POSTs payload to a new fc_buffer endpoint `/control/persist`, fc_buffer writes the file." This is a cleaner architecture anyway (bridge doesn't need SSH; fc1 owns fc1 disk).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | rclnodejs's pinned version in the bridge container supports `createClient('rcl_interfaces/srv/SetParameters', ...)` | Pattern 4 | Bridge needs upgrade; verify against bridge `package.json` first wave |
| A2 | rclpy's overlay-file behavior ignores undeclared keys (strict declaration mode default) | Pattern 3 | If overlay declares non-declared keys, behavior may differ; mitigate by overlay containing only band-edges/targets which are always declared |
| A3 | `js-yaml` is already installed in bridge container | Standard Stack — Supporting | If absent, install or use alternative; trivial to fix |
| A4 | Bridge container can SSH to fc1 as `ubuntu` for Layer 2 file write | Environment Availability | If absent, pivot to fc_buffer HTTP endpoint for persistence — actually preferable architecturally |
| A5 | `/var/lib/fc-core/runtime_overrides.yaml` is the right location | Pitfall 3 | Discretionary; `/etc/fc-core/` is alternative; lock during planning |
| A6 | Pinning floor 0.90 is "tight enough" — won't cause excess humidifier wear during pinning vs aspirational 0.78 | D-06 (locked by user) | Operator's call; not Claude's to second-guess |
| A7 | rclpy `param_callback` returning `successful=False` for one param in a batch rejects the entire batch atomically | Pattern 2 | If atomicity is per-param in some rclpy version, band invariants could be violated mid-batch; mitigate by bridge always-batching coupled edits |

## Open Questions (RESOLVED)

1. **rclnodejs pinned version + SetParameters API exact request shape**
   - What we know: rclnodejs supports service clients; ParameterClient class introduced in 1.7.0.
   - What's unclear: Exact request-message field names for `rcl_interfaces/srv/SetParameters` after rclnodejs codegen (snake_case vs camelCase; `parameter_value` field structure).
   - Recommendation: Wave 0 spike — write a 5-line script that calls `/fc_controller/set_parameters` from a bridge-style node, verify request shape and codepath. Or use rclnodejs's `Node.setParameters()` if available, which abstracts this.
   - **Resolution (Phase 28 planning):** Deferred to Wave 0 spike — plan 28-01 Task 3 verifies request shape against bridge's pinned rclnodejs.

2. **Bridge container SSH credentials to fc1**
   - What we know: `deploy.sh` runs from elder-plops shell, has SSH to fc1; `PI_HOST=fc1-ts` per `deploy.sh:6` — but per memory `feedback_ssh_tailscale`, `fc1-ts` is stale post-wg0 cutover; correct is `172.16.10.5`.
   - What's unclear: Does the *bridge container* (not the host) have an SSH key with reach to fc1?
   - Recommendation: Pre-planning verify (Environment Availability section). If absent, pivot to fc_buffer HTTP endpoint for Layer 2 (simpler architecture).
   - **Resolution (Phase 28 planning):** Deferred to Wave 0 spike — plan 28-01 Task 3 probes bridge-container SSH reach to fc1. If SSH unavailable, pivot to fc_buffer-hosted persist endpoint per plan 28-06 Branch B.

3. **deploy.sh `PI_HOST=fc1-ts` is stale**
   - What we know: Memory `feedback_ssh_tailscale` says use `172.16.10.5` (wg0).
   - What's unclear: Does deploy.sh currently work? It'd fail on `fc1-ts` resolution today.
   - Recommendation: Independent fix (not gated on Phase 28); but Phase 28's first deploy will surface this. Add to plan as a small upstream fix or defer to a 999.* item.
   - **Resolution (Phase 28 planning):** Plan 28-07 Task 2 replaces stale `fc1-ts` with wg0 IP `172.16.10.5`.

4. **Overlay yaml namespace structure**
   - What we know: Base yaml uses `/**:` global namespace `[VERIFIED: fc_config.yaml:1]`.
   - What's unclear: Should overlay use `fc_controller:` specifically, or `/**:`? Both load; `fc_controller:` is more precise but less forgiving of node renames.
   - Recommendation: Use `fc_controller:\n  ros__parameters:\n    ...` in overlay — narrows scope, prevents accidental override of other nodes' params.
   - **Resolution (Phase 28 planning):** Locked to node-specific namespace (`fc_controller:`) in plans 28-06 (overlay yaml shape) and 28-07 actions.

5. **Pitfall 6 surface check: should the param callback also enforce `band_low <= target <= band_high`?**
   - What we know: D-06 sets pinning target=0.85 outside [0.90, 0.99] band; this is intentional (cosmetic).
   - What's unclear: Should validation warn but accept, or silently accept?
   - Recommendation: WARN log at startup if any active mode has `target` outside band; do not reject. Operator's call.
   - **Resolution (Phase 28 planning):** Implemented as a one-line WARN log in plan 28-04 Task 1's startup `_publish_current_mode` path: when active mode's `target` is outside `[band_low, band_high]`, log `WARN target {target} outside band [{band_low},{band_high}] for mode {name} — cosmetic, by D-06`. Cosmetic-target choice from D-06 acknowledged at startup; not rejected.

## Sources

### Primary (HIGH confidence — cited in research)
- `[CITED]` ROS 2 Jazzy custom interfaces tutorial — https://docs.ros.org/en/jazzy/Tutorials/Beginner-Client-Libraries/Custom-ROS2-Interfaces.html
- `[CITED]` ROS 2 Jazzy single-package interface tutorial — https://docs.ros.org/en/jazzy/Tutorials/Beginner-Client-Libraries/Single-Package-Define-And-Use-Interface.html
- `[CITED]` rclpy 3.2.1 docs (Jazzy) — https://docs.ros.org/en/jazzy/p/rclpy/
- `[CITED]` ROS 2 Jazzy parameters concept — https://docs.ros.org/en/jazzy/Concepts/Basic/About-Parameters.html
- `[CITED]` ROS 2 QoS / TRANSIENT_LOCAL — https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Quality-of-Service-Settings.html
- `[CITED]` Vulcanexus persistency tutorial — https://docs.vulcanexus.org/en/latest/rst/tutorials/core/qos/persistency/persistency.html
- `[VERIFIED: codebase grep]` `src/chambers/fc-core/fc_core/fc_controller.py` lines 1–460 (PID + bumpless + per-tick get_parameter pattern)
- `[VERIFIED: codebase grep]` `src/mission-control/bridge/src/index.js` (Express + rclnodejs already wired; routes at lines 285–550; rclnodejs init at 621)
- `[VERIFIED: codebase grep]` `scripts/pi-deploy/deploy.sh:19` `colcon build --packages-select fc_core` (must be updated for fc_msgs)
- `[VERIFIED: codebase grep]` `scripts/pi-deploy/fc-core.service` ExecStart unchanged (no edit needed)
- `[VERIFIED: codebase grep]` `src/chambers/fc-core/launch/fc.launch.py` parameters=[LaunchConfiguration('config_file')] is the edit site

### Secondary (MEDIUM confidence — WebSearch with multi-source corroboration)
- `[VERIFIED: ros2/rclcpp#953]` Multiple `--params-file` last-file-wins — https://github.com/ros2/rclcpp/issues/953
- `[VERIFIED: ros2/rclcpp#1550]` Param callback receives batch + returns single SetParametersResult (whole-batch atomicity) — https://github.com/ros2/rclcpp/issues/1550
- `[CITED]` rclnodejs Node JSDoc 0.22.3 — https://robotwebtools.github.io/rclnodejs/docs/0.22.3/Node.html
- `[CITED]` rclnodejs GitHub — https://github.com/RobotWebTools/rclnodejs
- `[VERIFIED: ros2/rclpy#1167 + #829]` "Cannot set parameters declared in YAML file" history — strict-declaration interaction with overlay files

### Tertiary (LOW confidence — flag for validation)
- `[ASSUMED]` Exact rclnodejs request shape for `rcl_interfaces/srv/SetParameters` — verify in Wave 0 spike (see Open Question 1)
- `[ASSUMED]` Bridge container SSH credentials present (see Open Question 2)
- `[ASSUMED]` `js-yaml` already in bridge `package.json`

## Metadata

**Confidence breakdown:**
- Mode schema + controller surgery: HIGH — D-01..D-12 are locked; controller code path verified in `fc_controller.py`; SEED-004 alignment confirmed
- `current_mode` topic + `fc_msgs` package: HIGH — ROS2 Jazzy custom-interfaces pattern is well-trodden; QoS pattern matches existing topics
- Bridge Layer 1 (`POST /control/param` → SetParameters): MEDIUM — rclnodejs API shape needs Wave 0 spike confirmation
- Bridge Layer 2 (overlay yaml + persistence): MEDIUM — file path, transport, and SSH-from-container all `[ASSUMED]` and need pre-planning verification (architectural pivot to fc_buffer endpoint is the recommended fallback if SSH credentialing is absent)
- Validation Architecture: HIGH — test surfaces are concrete; framework is `pytest` already used by Phase 27 tests
- Security/allowlist: HIGH for the threat model; MEDIUM for the exact allowlist contents (lock during planning)

**Research date:** 2026-05-07
**Valid until:** 2026-06-07 (ROS2 Jazzy is LTS; APIs stable for 30 days+)

---

*Phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con*
*Research completed: 2026-05-07*
