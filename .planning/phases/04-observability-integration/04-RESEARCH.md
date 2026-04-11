# Phase 4: Observability & Integration - Research

**Researched:** 2026-04-04
**Domain:** ROS2 topic publishing (QoS), OpenMCT/rosbridge telemetry plugin extension
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Publish humidifier state as `std_msgs/Bool` on `fc/actuators/humidifier` with `TRANSIENT_LOCAL` QoS durability — satisfies ACTR-03 spec exactly.
- **D-02:** Also publish all available actuator/sensor data for logging. Current telemetry: temperature, humidity, CO2 (SCD41), humidifier on/off, fan speed, light state. Lower refresh rate acceptable for logging topics.
- **D-03:** Design for extensibility — more sensors will be connected later. Topic structure should accommodate new data sources without restructuring.
- **D-04:** Full OpenMCT integration — add CO2 (`fc/co2`, Float32) and actuator state (`fc/actuators/humidifier`, Bool) to both the WebSocket bridge and the OpenMCT plugin.
- **D-05:** Live charts in browser for all telemetry: humidity, temperature, CO2, humidifier state. Existing plugin pattern (SENSORS array with extract function) is the template for new entries.
- **D-06:** Breath test from prior session validates control loop end-to-end but does NOT satisfy TEST-02 fully.
- **D-07:** Soak test required: run system for 1+ hours with real humidifier in the actual fruiting chamber. Gated by physical Pi relocation from lab to farm.
- **D-08:** Remote access (WireGuard over internet) is a blocker for soak test but is deferred as a separate network issue — not Phase 4 scope.
- **D-09:** ACTR-01 satisfied: SSR on GPIO27 verified toggling 220V load (lamp test).
- **D-10:** SENS-02 satisfied: humidity published correctly on `fc/humidity` in 0.0-1.0 range from SCD41.
- **D-11:** SCD41 CO2 sensor integrated, publishing on `fc/co2` (Float32). Falls back to SCD41 temp/humidity when SHT30 is absent.
- **D-12:** Fan hardware PWM made optional — controller starts without rpi_hardware_pwm installed.
- **D-13:** Humidifier pin moved from GPIO17 to GPIO27.

### Claude's Discretion

- QoS profile details for non-actuator topics (CO2, fan speed, light state)
- OpenMCT chart axis ranges and display formatting for CO2 (ppm) and boolean actuator state
- Whether to add a combined "system status" endpoint or keep individual topics

### Deferred Ideas (OUT OF SCOPE)

- Remote WireGuard access over internet — needed for soak test when Pi moves to farm, but separate from observability code.
- Actuator bundle message — custom msg with all actuator states in one message. Rejected in favor of individual topics per actuator.
- TimescaleDB telemetry storage — docker-compose has a timescale service defined but not wired. Future phase for historical data.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SENS-02 | Humidity published to `fc/humidity` in consistent 0.0–1.0 range | Already satisfied per D-10; needs verification test |
| ACTR-01 | Humidifier controlled via GPIO pin (on/off) | Already satisfied per D-09; needs end-to-end test |
| ACTR-03 | Actuator state published to `fc/actuators/humidifier` (`std_msgs/Bool`, `TRANSIENT_LOCAL`) | Requires new publisher in fc_controller.py; QoS pattern documented in Standard Stack |
| TEST-02 | Full control loop verified on real FC-1 hardware (sensor → control → actuator) | Requires soak test on real hardware; documented in Validation Architecture |
</phase_requirements>

---

## Summary

Phase 4 has two distinct workstreams: (1) a small code change — adding `fc/actuators/humidifier` publisher to `fc_controller.py` — and (2) a hardware validation procedure on FC-1.

The OpenMCT integration is simpler than the CONTEXT.md wording implies. The bridge in production is `rosbridge_websocket` (from the `ros-jazzy-rosbridge-suite` apt package), launched via `bridge.launch.py`. Rosbridge handles any ROS topic automatically — no bridge code changes are required to expose new topics. Adding CO2 and humidifier state to the OpenMCT dashboard requires only adding entries to the `SENSORS` array in `plugin.js`. The `src/mission-control/bridge/src/index.js` file (custom Node.js WebSocket bridge) is legacy code that is not invoked by the Docker entrypoint and should be ignored.

The actuator state publisher (ACTR-03) is a 10-line addition to `fc_controller.py`: import `std_msgs/Bool`, create a publisher with `TRANSIENT_LOCAL` QoS in `__init__`, and call `publish()` at the end of `control_loop()`.

**Primary recommendation:** Add the Bool publisher to `fc_controller.py`, extend `plugin.js` SENSORS array with CO2 and humidifier entries, deploy to Pi, and run a 1-hour soak test.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| rclpy QoSProfile | ROS2 Jazzy (rclpy 6.x) | Publisher QoS configuration | Official rclpy API for setting durability, reliability, depth |
| std_msgs/Bool | ROS2 Jazzy | Humidifier state topic message type | Standard ROS2 message for boolean signals |
| rosbridge_websocket | ros-jazzy-rosbridge-suite (apt) | WebSocket bridge between ROS2 and browser | Already in Docker image; handles any topic by default |

[VERIFIED: codebase — bridge/Dockerfile installs ros-jazzy-rosbridge-suite]
[VERIFIED: codebase — bridge/launch/bridge.launch.py uses rosbridge_websocket]

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rclpy DurabilityPolicy | same as rclpy | TRANSIENT_LOCAL enum value | Setting "late-joiner" semantics on actuator state topic |
| rclpy ReliabilityPolicy | same as rclpy | RELIABLE enum value | Required pairing with TRANSIENT_LOCAL |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| TRANSIENT_LOCAL publisher in controller | Separate state node | More isolation, but adds complexity; controller already has all state |
| Individual actuator topics | Bundle message (custom msg) | Bundle rejected by D-02; individual topics are simpler and ACTR-03 compliant |

### Installation

No new packages needed — `std_msgs` is already a ROS2 built-in and the project's `setup.py` already lists it.

**Version verification:** [VERIFIED: codebase — setup.py lists `std_msgs` in install_requires]

---

## Architecture Patterns

### Key Architectural Discovery: Bridge is Rosbridge, Not Custom Node.js

The `src/mission-control/bridge/src/index.js` (custom rclnodejs bridge) is **not used in production**. The Docker entrypoint (`entrypoint.sh`) sources ROS2 and runs `ros2 launch .../bridge.launch.py`, which starts `rosbridge_websocket`. [VERIFIED: codebase — entrypoint.sh and launch/bridge.launch.py]

Rosbridge uses a JSON protocol where the browser sends `{"op": "subscribe", "topic": "/fc/co2", "type": "std_msgs/msg/Float32"}` and receives `{"op": "publish", "topic": "/fc/co2", "msg": {"data": 415.3}}`. The plugin.js already implements this protocol correctly in its `addSub`/`removeSub`/`ws.onmessage` handlers.

### Pattern 1: TRANSIENT_LOCAL Publisher in rclpy

**What:** Publisher with durability that delivers the last message to late-joining subscribers.
**When to use:** Actuator state topics where a new subscriber (dashboard reload) needs the current state immediately without waiting for the next publish cycle.

```python
# Source: rclpy QoS API [ASSUMED: based on rclpy Jazzy patterns — standard API unchanged since ROS2 Foxy]
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Bool

# In __init__:
actuator_qos = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)
self.humidifier_pub = self.create_publisher(Bool, 'fc/actuators/humidifier', actuator_qos)

# In control_loop() (at the end, after all state changes):
msg = Bool()
msg.data = self.get_humidifier_state()
self.humidifier_pub.publish(msg)
```

**TRANSIENT_LOCAL requires RELIABLE** — mixing TRANSIENT_LOCAL with BEST_EFFORT is not supported in DDS and will cause QoS incompatibility. [ASSUMED: well-established DDS/ROS2 constraint]

### Pattern 2: OpenMCT SENSORS Array Extension

**What:** Adding new telemetry sources by appending to the SENSORS array in plugin.js.
**When to use:** Any new ROS topic that should appear as a chart in the dashboard.

```javascript
// Source: codebase — src/mission-control/frontend/plugins/fruiting-chamber/plugin.js
// Add these entries to the SENSORS array:

{
    identifier: { namespace: 'fruiting-chamber', key: 'fc.co2' },
    name: 'CO2',
    unit: 'ppm',
    topic: '/fc/co2',
    msgType: 'std_msgs/msg/Float32',
    extract: function (msg) { return msg.data; },
    min: 300,
    max: 5000
},
{
    identifier: { namespace: 'fruiting-chamber', key: 'fc.humidifier' },
    name: 'Humidifier',
    unit: '',
    topic: '/fc/actuators/humidifier',
    msgType: 'std_msgs/msg/Bool',
    extract: function (msg) { return msg.data ? 1 : 0; },
    min: 0,
    max: 1
}
```

**Bool → numeric:** OpenMCT charts require numeric values. Convert `msg.data` (boolean) to `1`/`0` in the extract function.

**Float32 JSON shape from rosbridge:** `{"data": 415.3}` — extract is `function(msg) { return msg.data; }`.

**Bool JSON shape from rosbridge:** `{"data": true}` — extract is `function(msg) { return msg.data ? 1 : 0; }`.

[VERIFIED: codebase — existing plugin.js extract functions for RelativeHumidity and Temperature]
[ASSUMED: rosbridge JSON field names for Float32 and Bool — standard rosbridge behavior]

### Pattern 3: End-to-End Hardware Soak Test

**What:** Run fc_core for 1+ hours on real hardware with humidifier connected.
**When to use:** TEST-02 validation after all code changes deployed.

Verification commands (run from elder-plops workstation over WireGuard):
```bash
# Verify fc/humidity topic is live
ros2 topic echo /fc/humidity --once

# Verify actuator state topic with TRANSIENT_LOCAL (new subscriber gets last value immediately)
ros2 topic echo /fc/actuators/humidifier --once

# Watch control loop in action
ros2 topic hz /fc/humidity
ros2 topic hz /fc/actuators/humidifier

# Monitor systemd service log for bang-bang transitions
ssh fc1 'sudo journalctl -u fc-core -f'
```

### Recommended Project Structure (no changes needed)

```
src/chambers/fc-core/fc_core/
├── fc_controller.py    # Add humidifier_pub here (ACTR-03)
├── fc_sensors.py       # Already publishes fc/co2 — no changes
└── test/
    └── test_controller.py   # Add test_humidifier_state_published

src/mission-control/frontend/plugins/fruiting-chamber/
└── plugin.js           # Add CO2 + humidifier SENSORS entries (D-04, D-05)
```

### Anti-Patterns to Avoid

- **Publishing in set_humidifier() instead of control_loop():** The `set_humidifier()` method is a hardware abstraction layer. Publishing belongs in `control_loop()` so it fires every tick with consistent state, not only on transitions. This also correctly handles safe-state forced-OFF.
- **Using BEST_EFFORT with TRANSIENT_LOCAL:** Not supported by DDS. Always pair TRANSIENT_LOCAL with RELIABLE.
- **Editing src/mission-control/bridge/src/index.js:** This file is dead code. The active bridge is `rosbridge_websocket` from the launch file. Changes to `index.js` have no effect.
- **Adding ROS subscriptions to bridge.launch.py for new topics:** Rosbridge subscribes on demand when the browser requests a topic. No server-side config changes needed for new topics.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Late-joiner topic delivery | Custom state cache | TRANSIENT_LOCAL QoS | Built into DDS; just a QoSProfile parameter |
| WebSocket → ROS topic bridging | Custom bridge code | rosbridge_websocket | Already installed and running in Docker |
| Boolean-to-numeric conversion for charts | Custom OpenMCT widget type | extract function returning `msg.data ? 1 : 0` | Plugin.js already handles per-sensor extraction |

---

## Common Pitfalls

### Pitfall 1: `src/index.js` Is Dead Code
**What goes wrong:** Developer edits `src/mission-control/bridge/src/index.js` to add CO2/humidifier subscriptions, but nothing changes in the running system.
**Why it happens:** The file looks like the bridge, but the Docker entrypoint launches `rosbridge_websocket` from the launch file instead.
**How to avoid:** Edit only `plugin.js` for OpenMCT changes. The rosbridge server needs no changes.
**Warning signs:** Changes to index.js have no visible effect after `docker-compose up`.

### Pitfall 2: QoS Mismatch on `fc/actuators/humidifier`
**What goes wrong:** `ros2 topic echo /fc/actuators/humidifier` prints nothing; subscriber and publisher QoS are incompatible.
**Why it happens:** Publisher is TRANSIENT_LOCAL/RELIABLE but subscriber uses default VOLATILE/BEST_EFFORT.
**How to avoid:** When testing from CLI, use: `ros2 topic echo /fc/actuators/humidifier --qos-durability transient_local --qos-reliability reliable`. Or just check with `ros2 topic info -v /fc/actuators/humidifier` to see offered/requested QoS.
**Warning signs:** `ros2 topic echo` produces no output but `ros2 topic info` shows a publisher.

### Pitfall 3: TRANSIENT_LOCAL Requires depth=1 to Be Useful
**What goes wrong:** Late-joiner gets 10 stale messages instead of just the current state.
**Why it happens:** `depth=10` (default) with TRANSIENT_LOCAL replays the full history buffer.
**How to avoid:** Use `depth=1` and `history=KEEP_LAST` for actuator state topics.

### Pitfall 4: `test_temperature_control` Already Has a Bug
**What goes wrong:** `test_temperature_control` accesses `node.fan_pwm.get_duty_cycle()` in simulation mode, but `fan_pwm` is `None` in simulation mode (fan speed is tracked via `node.fan_speed`).
**Why it happens:** The test was written before the "fan PWM optional" change from Phase 2.
**How to avoid:** If `test_temperature_control` is failing locally, it's a pre-existing issue. Fix it by checking `node.fan_speed` instead of `node.fan_pwm.get_duty_cycle()` in simulation mode. This is separate from Phase 4 scope but will surface during test runs.
**Warning signs:** `AttributeError: 'NoneType' object has no attribute 'get_duty_cycle'`.

### Pitfall 5: Float32 `fc/co2` Has No Header — Use Date.now() Fallback
**What goes wrong:** CO2 chart shows no data or errors.
**Why it happens:** `Float32` has no `header.stamp` field. The existing `getTimestamp()` function already handles this with `return Date.now()` fallback, so it's safe.
**How to avoid:** No action needed — `getTimestamp(msg)` already falls back to `Date.now()` when `msg.header` is absent.

### Pitfall 6: Soak Test Requires min_dwell_time Reset to Production Value
**What goes wrong:** Humidifier cycles rapidly during soak test instead of 5-minute dwell.
**Why it happens:** `fc_config.yaml` has `min_dwell_time: 5.0` (set for integration testing). Production value should be 300.0 (5 minutes).
**How to avoid:** Before the soak test, update `fc_config.yaml` to `min_dwell_time: 300.0` and deploy.
**Warning signs:** Humidifier toggling multiple times per minute.

---

## Code Examples

### ACTR-03: Add Humidifier State Publisher to fc_controller.py

```python
# Source: codebase pattern [VERIFIED] + rclpy QoS API [ASSUMED: standard Jazzy API]

# --- Imports (add to existing imports at top of fc_controller.py) ---
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Bool

# --- In __init__, after existing subscriber creation ---
actuator_qos = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)
self.humidifier_state_pub = self.create_publisher(
    Bool, 'fc/actuators/humidifier', actuator_qos
)

# --- At the end of control_loop(), after the debug log ---
state_msg = Bool()
state_msg.data = self.get_humidifier_state()
self.humidifier_state_pub.publish(state_msg)
```

### D-04/D-05: Extend plugin.js SENSORS Array

```javascript
// Source: codebase [VERIFIED: plugin.js SENSORS pattern]
// Append to SENSORS array in plugin.js after existing temperature entry:

{
    identifier: { namespace: 'fruiting-chamber', key: 'fc.co2' },
    name: 'CO2',
    unit: 'ppm',
    topic: '/fc/co2',
    msgType: 'std_msgs/msg/Float32',
    extract: function (msg) { return msg.data; },
    min: 300,
    max: 5000
},
{
    identifier: { namespace: 'fruiting-chamber', key: 'fc.humidifier' },
    name: 'Humidifier',
    unit: '',
    topic: '/fc/actuators/humidifier',
    msgType: 'std_msgs/msg/Bool',
    extract: function (msg) { return msg.data ? 1 : 0; },
    min: 0,
    max: 1
}
```

### Verify TRANSIENT_LOCAL from CLI

```bash
# CLI subscriber with matching QoS (required to receive TRANSIENT_LOCAL messages):
ros2 topic echo /fc/actuators/humidifier \
    --qos-durability transient_local \
    --qos-reliability reliable

# Inspect QoS compatibility:
ros2 topic info -v /fc/actuators/humidifier
```

### Unit Test: Humidifier State Is Published

```python
# Source: existing test pattern [VERIFIED: test_controller.py] + new assertion
def test_humidifier_state_published(ros_context):
    """control_loop publishes current humidifier state on fc/actuators/humidifier."""
    node = FruitingChamberController()
    node.current_temp = 23.0

    published = []
    # Monkey-patch publisher to capture outgoing messages
    node.humidifier_state_pub.publish = lambda msg: published.append(msg.data)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        for _ in range(5):
            _send_humidity(node, 0.70)  # below threshold -> humidifier ON
        node.control_loop()

    assert len(published) == 1
    assert published[0] == True  # humidifier ON

    node.destroy_node()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Custom rclnodejs bridge (src/index.js) | rosbridge_websocket | During OpenMCT integration work | No bridge code changes needed for new topics |
| Manual topic subscription in bridge | rosbridge on-demand subscribe | Same | Plugin.js is the only config point |
| min_dwell_time: 300.0 | min_dwell_time: 5.0 (integration testing) | Phase 3 | Must restore to 300.0 before soak test |

**Deprecated/outdated:**
- `src/mission-control/bridge/src/index.js`: legacy custom bridge. Not called by entrypoint. Can be retained for reference but must not be edited as if it were active.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | rclpy QoSProfile imports (`DurabilityPolicy`, `ReliabilityPolicy`, `HistoryPolicy`) use the same enum names in Jazzy as in prior ROS2 distros | Code Examples | Wrong import names → ImportError; fix by checking `python3 -c "from rclpy.qos import ..."` on Pi |
| A2 | rosbridge JSON for `std_msgs/msg/Float32` is `{"data": <float>}` and for `std_msgs/msg/Bool` is `{"data": <bool>}` | Code Examples, Pitfalls | Wrong field name → extract function returns undefined; fix by logging `msg` in plugin.js |
| A3 | TRANSIENT_LOCAL must be paired with RELIABLE (DDS constraint) | Architecture Patterns, Code Examples | If wrong, QoS mismatch won't occur but late-joiner delivery may fail silently |

---

## Open Questions

1. **Does the `fake_sensors.py` need updating for CO2/humidifier simulation?**
   - What we know: `fake_sensors.py` only publishes temperature and humidity. If running with `FAKE_SENSORS=1` (no Pi), the OpenMCT dashboard will show CO2 and humidifier as offline.
   - What's unclear: Is fake_sensors used for testing Phase 4? The phase focuses on real hardware.
   - Recommendation: Ignore for Phase 4 (real hardware only). If needed, add `Float32` CO2 and `Bool` humidifier publishers to fake_sensors.py using the same pattern.

2. **Should `test_temperature_control` be fixed in this phase?**
   - What we know: The test accesses `node.fan_pwm.get_duty_cycle()` but `fan_pwm` is `None` in simulation mode. This is a pre-existing bug from Phase 2.
   - What's unclear: Does it actually fail in the test suite, or does it pass because fan_pwm is mocked elsewhere?
   - Recommendation: Include a fix for this test as a Wave 0 cleanup task if it fails during `pytest`.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| FC-1 Pi (SSH: fc1) | Soak test (TEST-02) | Physical requirement | — | Cannot substitute; soak test is gated on Pi relocation to farm |
| WireGuard VPN | ROS topic visibility from elder-plops | Known working | — | LAN SSH direct when on same network |
| docker-compose | OpenMCT dashboard | [ASSUMED: installed on elder-plops] | — | Run bridge/frontend manually |
| ROS2 Jazzy (on Pi) | All ROS node operations | Confirmed working | Jazzy | — |
| deploy.sh | Code deployment to Pi | Confirmed working | — | Manual rsync + ssh |

**Missing dependencies with no fallback:**
- Physical Pi relocation to farm — required for the soak test with real humidifier. Gated by user (D-07).

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (via `colcon test`) |
| Config file | none — `setup.py` with `tests_require=['pytest']` |
| Quick run command | `pytest src/chambers/fc-core/fc_core/test/test_controller.py -x` |
| Full suite command | `colcon test --packages-select fc_core && colcon test-result --verbose` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SENS-02 | fc/humidity publishes in 0.0-1.0 range | unit | `pytest .../test_controller.py::test_humidity_control -x` | ✅ (existing) |
| ACTR-01 | Humidifier GPIO activates on control command | integration/hardware | Manual on FC-1: `ssh fc1 'sudo journalctl -u fc-core -f'` + observe SSR | Manual only |
| ACTR-03 | `fc/actuators/humidifier` Bool topic published with TRANSIENT_LOCAL | unit | `pytest .../test_controller.py::test_humidifier_state_published -x` | ❌ Wave 0 |
| TEST-02 | Full control loop verified on real hardware | hardware/soak | Manual: 1-hour soak test with logging | Manual only |

### Sampling Rate

- **Per task commit:** `pytest src/chambers/fc-core/fc_core/test/test_controller.py -x`
- **Per wave merge:** `colcon test --packages-select fc_core && colcon test-result --verbose`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `src/chambers/fc-core/fc_core/test/test_controller.py::test_humidifier_state_published` — covers ACTR-03 (new test, file exists, add function)
- [ ] Verify `test_temperature_control` passes (fan_pwm None bug from Phase 2 may cause failure)

---

## Security Domain

This phase involves no authentication, network services, or user-facing input. The only new code is a ROS topic publisher (ACTR-03) and a client-side JavaScript array extension (OpenMCT plugin).

Applicable ASVS categories: none for this phase scope. The OpenMCT dashboard is already behind the existing network boundary (LAN/WireGuard).

---

## Sources

### Primary (HIGH confidence)

- Codebase: `src/mission-control/bridge/entrypoint.sh` — confirms rosbridge_websocket is the active bridge
- Codebase: `src/mission-control/bridge/launch/bridge.launch.py` — confirms rosbridge_websocket launch
- Codebase: `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` — SENSORS array pattern verified
- Codebase: `src/chambers/fc-core/fc_core/fc_controller.py` — actuator state getters verified
- Codebase: `src/chambers/fc-core/fc_core/fc_sensors.py` — CO2 publisher on fc/co2 (Float32) verified
- Codebase: `src/chambers/fc-core/config/fc_config.yaml` — min_dwell_time: 5.0 confirmed (needs reset)

### Secondary (MEDIUM confidence)

- Codebase: `src/chambers/fc-core/fc_core/test/test_controller.py` — existing test patterns for mocking and publisher patching

### Tertiary (LOW confidence — flagged as ASSUMED)

- rclpy QoSProfile API (A1) — standard ROS2 pattern, not verified on target Jazzy installation
- rosbridge JSON wire format for Float32/Bool (A2) — standard rosbridge behavior, not verified by live test

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — bridge architecture verified from codebase; existing patterns are direct templates
- Architecture: HIGH — exact file locations, method names, and integration points verified from source
- Pitfalls: HIGH — dead code trap and QoS mismatch verified from codebase; dwell time pitfall from config
- Test coverage: MEDIUM — test patterns verified, new test function is additive

**Research date:** 2026-04-04
**Valid until:** 2026-05-04 (stable stack, no external dependencies changing)
