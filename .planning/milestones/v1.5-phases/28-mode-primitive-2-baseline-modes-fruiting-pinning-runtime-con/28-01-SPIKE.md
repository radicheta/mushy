# Phase 28 — Plan 01 — Wave 0 SPIKE findings

**Run:** 2026-05-07 against the live stack (elder-plops bridge container ↔ fc1 fc_controller over wg0).
**Purpose:** Lock the two architectural unknowns that gate plans 05/06 — rclnodejs SetParameters wire shape (Open Question 1) and the bridge→fc1 Layer 2 transport (Open Question 2).

---

## §A — rclnodejs SetParameters wire shape

### Environment

| Property | Value |
|----------|-------|
| Bridge container | `mushy-bridge-1` |
| rclnodejs version | **1.9.0** (from `require('rclnodejs/package.json').version`) |
| ROS distro | jazzy (sourced from `/opt/ros/jazzy/setup.bash` inside container) |
| Container ROS env | `ROS_DISTRO=jazzy`, `ROS_DOMAIN_ID=69`, `ROS_LOCALHOST_ONLY=0`, `AMENT_PREFIX_PATH=/opt/ros/jazzy` (PID1 inherits via entry script; ad-hoc `docker exec` shells must `source /opt/ros/jazzy/setup.bash` themselves) |

### Live test

Probed against `/fc_controller/set_parameters` with `pid_kp=0.35` (a no-op — 0.35 is the current declared value per `fc_config.yaml:37`; no controller-state mutation):

```javascript
const r = require('rclnodejs');
await r.init();
const n = new r.Node('spike_setparam');
const cli = n.createClient(
  'rcl_interfaces/srv/SetParameters',
  '/fc_controller/set_parameters'
);
const ok = await cli.waitForService(5000);   // SERVICE_READY=true
n.spin();                                     // ← REQUIRED to dispatch async callbacks
cli.sendRequest(
  { parameters: [{ name: 'pid_kp', value: { type: 3, double_value: 0.35 } }] },
  (resp) => console.log(JSON.stringify(resp))
);
```

### Captured wire shape (verbatim)

**Request:**
```json
{"parameters":[{"name":"pid_kp","value":{"type":3,"double_value":0.35}}]}
```

**Response:**
```json
{"results":[{"successful":true,"reason":""}]}
```

### Field-name conventions (locked for plan 28-05)

- Top-level keys: snake_case (`parameters`, `results`).
- `Parameter` shape: `{name: string, value: ParameterValue}`.
- `ParameterValue` discriminator: integer `type` per `rcl_interfaces/msg/ParameterType`:
  | `type` | Constant | Field name |
  |--------|----------|------------|
  | 1 | PARAMETER_BOOL | `bool_value` |
  | 2 | PARAMETER_INTEGER | `integer_value` |
  | 3 | PARAMETER_DOUBLE | `double_value` |
  | 4 | PARAMETER_STRING | `string_value` |
  | 5 | PARAMETER_BYTE_ARRAY | `byte_array_value` |
  | 6 | PARAMETER_BOOL_ARRAY | `bool_array_value` |
  | 7 | PARAMETER_INTEGER_ARRAY | `integer_array_value` |
  | 8 | PARAMETER_DOUBLE_ARRAY | `double_array_value` |
  | 9 | PARAMETER_STRING_ARRAY | `string_array_value` |
- `SetParametersResult` shape: `{successful: bool, reason: string}`. `reason` is `""` on success.
- Plan 05's `toParamValue(name, jsValue)` helper MUST consult an allowlist that carries `expected_type` per param. Sending `{type:2, integer_value: 0}` against a DOUBLE-declared param like `pid_kp` would be rejected by rclpy with type mismatch (research §Pattern 4 footgun confirmed by inference; not exercised here because no-op preserved type).

### Operational gotcha — node MUST spin

Without `n.spin()` the request transmits but the response callback is never fired (first attempt without spin → 5s TIMEOUT). The bridge's existing rclnodejs usage (buffer replay, telemetry subscriber) already spins its node; plan 05 reuses that node, no extra spin required. **Document this in plan 05's implementation notes** — anyone copying this spike snippet without a running event loop will see ghost timeouts.

### Pattern 4 confirmation

Research §Pattern 4 captured the shape exactly. **No pivot.** Locked verbatim for plan 28-05.

---

## §B — Bridge → fc1 Layer 2 transport

### Probe 1: SSH client present in bridge container?

```
$ docker exec mushy-bridge-1 ssh -o BatchMode=yes ubuntu@172.16.10.5 'echo ok'
OCI runtime exec failed: exec failed: unable to start container process:
  exec: "ssh": executable file not found in $PATH: unknown
EXIT=127
```

**The bridge container has NO `ssh` binary.** Image is `node:20-bookworm`-derived; openssh-client was not installed and is not in the production image. Adding it is possible but introduces an SSH key inside the container's filesystem — increasing the bridge's blast radius for a CVE compromise.

### Probe 2: Threat model alignment

Per CONTEXT D-19 (conservative posture, "Save to repo" is explicit) and the threat register T-28-03 (`bridge container holding SSH key to fc1 ubuntu` — disposition: **mitigate**), even if we shipped the openssh-client install, plan 06 should default to the lower-blast-radius path.

### Probe 3: fc_buffer HTTP relay feasibility

`fc_buffer.py` already runs on fc1 as the `ubuntu` user (per `fc-core.service`). It already binds an HTTP server on `172.16.10.5:8765` (per `fc_config.yaml:67-68` and Phase 27.1 buffer-replay endpoint). Adding one more route — `POST /control/persist` — is a same-process Python http.server addition; the existing process already has filesystem access to `/var/lib/fc-core/` as `ubuntu`. **No new SSH key, no new daemon, no new trust boundary.**

### Decision

**Layer 2 transport = fc_buffer HTTP relay.** Architectural pivot from research §Pattern 4 / §Pitfall 3's SSH-from-bridge recommendation to a same-host write through fc_buffer. Justifications:

1. **Forced:** bridge container has no ssh binary; remediation requires Dockerfile change AND a key inside the container.
2. **Threat-aligned:** matches T-28-03 `mitigate` disposition (no SSH key in bridge container).
3. **Reuses existing surface:** fc_buffer already serves HTTP on the same wg0 IP; adding a POST handler is a small diff (`src/chambers/fc-core/fc_core/fc_buffer.py`).
4. **Owner-correct:** fc_buffer runs as `ubuntu`, which already owns `/var/lib/fc-core/` per `fc-core.service` ExecStartPre — no privilege escalation needed.

### Plan 06 contract (locked)

Bridge `POST /control/persist {param, value}` →
  HTTP `POST http://172.16.10.5:8765/control/persist {param, value, expected_type}` →
  fc_buffer writes `/var/lib/fc-core/runtime_overrides.yaml` atomically (`.tmp` + rename, `.bak` of previous) →
  responds `{success, reason}` to bridge → bridge proxies to caller (farmOS).

Plan 06 task list grows by one: add the route to fc_buffer.py with the same allowlist enforcement the bridge does (defense in depth — fc_buffer cannot trust an arbitrary HTTP poster from the wg0 subnet).

### Side-finding — `deploy.sh` `fc1-ts` resolution

`deploy.sh:5` defaults `PI_HOST=fc1-ts`. From elder-plops:

```
$ getent hosts fc1-ts → (no result)
$ getent hosts fc1.tailee56a6.ts.net → 100.96.239.75
```

Bare `fc1-ts` no longer resolves; deploy depends on shell aliases or `/etc/hosts` on whichever host invokes it (Santi's elder-plops user shell, presumably). Per memory `feedback_ssh_tailscale`, post-2026-05-03 cutover the canonical link is **wg0 = 172.16.10.5**. This is **not blocker-priority** for plan 28-01 (deploy hasn't been invoked this session), but plan 28-07's deploy.sh edit MUST set `PI_HOST` default to `172.16.10.5` (or `fc1-wg`) AND build `fc_msgs` before `fc_core`. Both edits already in plan 28-07 scope; flag for verifier sweep at end of phase.

---

## §C — Decisions for downstream waves (locked)

| Decision | Locked value | Source |
|----------|--------------|--------|
| **D-A1** rclnodejs request shape | `{parameters: [{name, value: {type:int, <field>_value}}]}` — snake_case `<typename>_value` keys | §A captured live |
| **D-A2** rclnodejs response shape | `{results: [{successful: bool, reason: string}]}` | §A captured live |
| **D-A3** Type-coercion table | type 1=BOOL/`bool_value`, 2=INTEGER/`integer_value`, 3=DOUBLE/`double_value`, 4=STRING/`string_value` (arrays 5-9 unused in plan 28 scope) | §A inferred from rcl_interfaces/msg/ParameterType |
| **D-A4** Allowlist must carry `expected_type` | yes — bridge `toParamValue(name, jsValue)` looks up allowlist entry, picks correct `<X>_value` field | §A operational gotcha |
| **D-A5** Bridge node must be spinning | yes — sendRequest callbacks need running executor; reuse existing bridge node (already spins) | §A TIMEOUT-without-spin observed |
| **D-B1** Layer 2 transport | **fc_buffer HTTP relay** (NOT SSH-from-bridge) | §B forced + threat-aligned |
| **D-B2** Overlay path | `/var/lib/fc-core/runtime_overrides.yaml` | research §Pitfall 3 (dir exists, ubuntu-owned) |
| **D-B3** Overlay yaml namespace | `fc_controller:\n  ros__parameters:\n    ...` | research §Open Question 4 (narrows scope vs `/**:`) |
| **D-B4** Atomic write semantics | write `.tmp`, rename to target, prior version preserved as `.bak` (single-generation) | research §Pitfall 3 + plan 28-01 jest stub |
| **D-B5** Plan 06 scope expansion | add `POST /control/persist` route to `src/chambers/fc-core/fc_core/fc_buffer.py` (Python http.server) AND bridge proxy to it | §B forced pivot |
| **D-B6** deploy.sh fc1-ts fix | not blocker for 28-01; plan 28-07 must set `PI_HOST` default to `172.16.10.5` and build `fc_msgs fc_core` (Pitfall 5) | §B side-finding |

### Operator-review prompt (Task 4 checkpoint)

The §C decisions above lock the rclnodejs wire (Pattern 4 confirmed verbatim, no pivot) and pivot Layer 2 from SSH-from-bridge to fc_buffer HTTP relay (forced — no ssh binary in bridge container). Plan 28-06 grows by one task (fc_buffer route) but is otherwise unchanged. Confirm or amend before plan 28-02 begins.
