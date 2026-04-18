# Architecture Patterns: ROS2 Sensor Reading + Closed-Loop Control

**Domain:** ROS2 Jazzy Python node — environmental sensor + on/off actuator control
**Researched:** 2026-03-28
**Overall confidence:** HIGH (patterns verified against official ROS2 Jazzy docs, existing codebase, community sources)

---

## Recommended Architecture

The existing codebase already follows the correct high-level separation: a dedicated sensor node (`fc_sensors`) publishes to topics, and a separate controller node (`fc_controller`) subscribes and drives actuators via a timer-based control loop. **This split is the right call and should not change.**

What follows documents the specific patterns for implementing the humidity control path correctly within this architecture, including the gaps and improvements needed.

---

## Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `FruitingChamberSensors` | Read DHT22, publish `fc/temperature` and `fc/humidity` at `sensor_read_interval` | Publisher to controller, display, telemetry |
| `FruitingChamberController` | Subscribe to sensor topics, run control loop on timer, drive actuators | Subscriber of sensors; direct GPIO/PWM write |
| `FruitingChamberDisplay` | Log current state to console | Subscriber of sensors |
| `FruitingChamberTelemetry` | Emit JSON over WebSocket to OpenMCT | Subscriber of sensors |

The humidity control path lives entirely inside `FruitingChamberController`. The sensor node is already correct and does not need structural changes — only the controller's humidity logic needs to be hardened.

---

## Control Loop Pattern: Timer-Driven Subscriber Cache

This is the canonical ROS2 pattern for closed-loop control. It is what the codebase already uses and is the correct choice.

```
Sensor node                Controller node
────────────────           ─────────────────────────────────
timer fires (2s)           subscription callback (async)
  read DHT22                 humidity_callback(msg)
  publish fc/humidity          self.current_humidity = msg.relative_humidity
                               self.last_humidity_ts = self.get_clock().now()

                           control timer fires (1s)
                             control_loop()
                               check if data is fresh
                               compare current vs setpoint
                               drive humidifier GPIO
```

**Why this works:** The subscription callback fires asynchronously whenever a message arrives and caches the value. The control timer fires independently at the control frequency and reads the cached value. They never block each other in a `SingleThreadedExecutor` (the default for `rclpy.spin()`).

**Threading note (confirmed against Jazzy docs):** With the default `SingleThreadedExecutor`, all callbacks including timers run serially. This is fine here — sensor reads at 2s intervals and control decisions at 1s intervals are not time-critical enough to require `MultiThreadedExecutor`. Do not add threading complexity unless profiling shows it is needed.

---

## Hysteresis (Bang-Bang) Control Pattern

The existing controller implements basic hysteresis for the humidifier — on below `target - tolerance`, off above `target + tolerance`. This is correct for an on/off actuator and should be preserved. The dead band (`humidity_tolerance = 0.05`, i.e. 5%) prevents constant switching at the setpoint.

**Current implementation (correct baseline):**
```python
if self.current_humidity < (target - tolerance):
    self.set_humidifier(True)
elif self.current_humidity > (target + tolerance):
    self.set_humidifier(False)
# else: inside dead band → no state change (implicit, correct)
```

**What is missing: minimum on/off time guard.** DHT22 humidity readings have noise. Without a minimum dwell time, the humidifier can switch rapidly near the dead-band edge (chattering), which degrades actuator lifespan and produces oscillating telemetry. The fix is to track `last_humidifier_change_ts` and enforce a minimum interval (e.g., 10 seconds) before allowing a state change.

```
Pattern:
  when deciding to change humidifier state:
    if time_since_last_change < min_dwell_time: skip
    else: change state, record timestamp
```

The `min_dwell_time` should be a config parameter, not a hardcode, so it can be tuned per-chamber without a code change.

---

## Stale Data Guard Pattern

**The existing code has a gap here.** The controller checks `if self.current_humidity is None: return` — this correctly handles the startup case before the first sensor message arrives. However, it does not handle the case where the sensor node restarts or the DHT22 fails after initially working: `current_humidity` will hold a stale value indefinitely and the controller will continue acting on it silently.

**Recommended pattern — timestamp-based freshness check:**

```
In humidity_callback:
  self.current_humidity = msg.relative_humidity
  self.last_humidity_ts = self.get_clock().now()

In control_loop:
  if self.last_humidity_ts is None: return early  # no data yet
  age = (self.get_clock().now() - self.last_humidity_ts).nanoseconds / 1e9
  if age > sensor_stale_timeout:  # e.g. 10.0s = 5 missed reads
    self.get_logger().warn('Humidity data stale, holding actuator state')
    return
  # else proceed with control decision
```

`sensor_stale_timeout` should be a config parameter. A reasonable default is `5 * sensor_read_interval` (10 seconds at the default 2s read interval).

**Why hold (not safe-off):** Turning the humidifier off on stale data is not obviously the right safe state for a mushroom farm. Holding the current actuator state is safer than forced-off, which could dry the chamber. If a safety override is needed, that is a separate explicit feature, not a default behavior.

---

## State Publishing Pattern

The controller currently drives hardware directly but does not publish actuator state to any ROS topic. This means:
- The display node reads sensor topics but cannot show actuator state
- Telemetry has no visibility into what the controller is doing
- Tests must inspect internal instance variables directly (a test smell visible in `test_controller.py`)

**Recommended addition:** Publish humidifier state to a topic like `fc/actuators/humidifier` using `std_msgs/Bool`. This decouples state reporting from the controller's internals and allows display/telemetry nodes to subscribe without coupling to the controller implementation.

```
Topic:   fc/actuators/humidifier
Message: std_msgs/Bool  (data: True = ON)
QoS:     Reliability=RELIABLE, Durability=TRANSIENT_LOCAL (last-value available to late-joiners)
```

The `TRANSIENT_LOCAL` durability is important: when the display or telemetry node starts after the controller, it should receive the current state without waiting for the next control cycle.

---

## Parameter Configuration Pattern

All control parameters should be declared in `fc_config.yaml` and loaded via `declare_parameters()` in `__init__`. The existing pattern is correct.

**Gap identified:** The humidifier GPIO pin is hardcoded in `fc_controller.py` as `self.humidifier_pin = 17` and is not declared as a parameter. This means changing the pin requires a code edit. It should be promoted to a config parameter (`humidifier_pin: 17`) alongside `dht_pin` and `light_pin`.

**Live parameter updates:** For MVP, `get_parameter()` inside `control_loop()` on every tick is acceptable and is what the existing code does. It is slightly inefficient (a dict lookup each tick) but avoids stale parameter state. If performance profiling ever shows this as a bottleneck, cache with `add_on_set_parameters_callback()`. For Raspberry Pi at 1Hz control rate, this is not a concern.

---

## Node vs Nodelet / Composable Node

Do not use composable nodes (nodelets) for this project. The rationale:

- Composable nodes exist to reduce serialization overhead for high-frequency data between nodes running in the same process. This system runs at 1-2Hz, where serialization is irrelevant.
- The existing plain `rclpy.node.Node` pattern is correct and adding composable nodes adds build complexity (requires `rclcpp_components`, not native to `ament_python`).
- Keep separate processes: if the controller crashes, the sensor node keeps publishing. This isolation is valuable for a production system.

---

## LifecycleNode Decision

Do not use `LifecycleNode` for MVP. The rationale:

- Lifecycle nodes are valuable when startup order dependencies are safety-critical (e.g., Nav2 where a failed planner should prevent the robot from moving). In this system, if the controller starts before the sensor, it simply waits for data (the `None` guard handles this).
- The added complexity — explicit state transitions, lifecycle manager configuration, transition callbacks — is not justified for a single-chamber system with two loosely coupled nodes.
- If the system grows to multiple chambers with strict startup ordering requirements, revisit this decision.

---

## Data Flow: Humidity Control Path (Complete)

```
DHT22 hardware / simulation
        |
        v  (every sensor_read_interval, default 2s)
FruitingChamberSensors.read_sensors()
        |
        v  publish
fc/humidity  (sensor_msgs/RelativeHumidity, field: relative_humidity [0.0–1.0])
        |
        v  subscription callback (async)
FruitingChamberController.humidity_callback()
   self.current_humidity = msg.relative_humidity
   self.last_humidity_ts = self.get_clock().now()
        |
        v  (every control_interval, default 1s, independent timer)
FruitingChamberController.control_loop()
   1. freshness check: is data recent enough?
   2. hysteresis: compare current vs [target ± tolerance]
   3. dwell guard: has enough time passed since last state change?
   4. set_humidifier(state) → GPIO.output() or sim variable
   5. publish to fc/actuators/humidifier  [recommended addition]
        |
        v
MOSFET GPIO pin → ultrasonic humidifier
```

---

## Error Handling Patterns

| Scenario | Current Handling | Recommended |
|----------|-----------------|-------------|
| No humidity data yet | `return` if `current_humidity is None` | Keep; add `last_humidity_ts` init to `None` |
| Sensor node stopped/crashed | Silent: uses stale value forever | Add timestamp freshness check, log warning |
| DHT22 read failure | Logged in `fc_sensors`, no publish | Controller detects via stale data timeout |
| GPIO write failure | No handling (real hardware) | Catch exception, log error, do not crash node |
| Humidifier chattering | No handling | Minimum dwell time guard |
| Invalid humidity value | No validation | Check value in [0.0, 1.0] range before use |

---

## Anti-Patterns to Avoid

### Blocking in Timer Callbacks

**What:** Using `time.sleep()` inside a timer callback or subscription callback.

**Current occurrence:** `fc_sensors.py` calls `time.sleep(2.0)` inside the `except RuntimeError` block of `read_sensors()`. This blocks the entire executor for 2 seconds while the ROS spin loop cannot process any other callbacks on that node.

**Why bad:** With `SingleThreadedExecutor` (the default), `time.sleep()` in any callback blocks all other callbacks on that node until it returns. No other timer fires, no subscriptions are processed.

**Instead:** Use a `self.retry_after` timestamp: set it when a read fails, and skip the read in subsequent timer fires until the time has passed. All callbacks remain non-blocking.

### Hardcoded Hardware Pins

**What:** GPIO pin numbers embedded in code rather than parameters.

**Current occurrence:** `self.humidifier_pin = 17` in `fc_controller.py`.

**Why bad:** Changing hardware requires a code edit rather than a config edit; makes testing harder; blocks multi-chamber scaling.

**Instead:** Declare `humidifier_pin: 17` in `fc_config.yaml` and read via `get_parameter()` in `__init__`.

### Testing Internal State Directly

**What:** Tests checking `node.humidifier_pin == 1` to verify the humidifier turned on.

**Current occurrence:** `test_controller.py` lines 66 and 74 test `node.humidifier_pin` as if it were a boolean state flag, but `humidifier_pin` is a GPIO pin number (17). This test is broken — it conflates the pin assignment with the pin output state.

**Why bad:** Test couples to implementation internals; will break if humidifier state is stored differently; currently tests incorrect thing.

**Instead:** Either expose a `get_humidifier_state()` method (already exists) and test that, or test that the published topic message is correct once the actuator state topic is added.

---

## Scalability Considerations

| Concern | At 1 chamber (MVP) | At 4 chambers | At 10+ chambers |
|---------|-------------------|---------------|-----------------|
| Node organization | Single fc_core package | Namespace per chamber (`fc1/`, `fc2/`) | Same namespacing, orchestrated via launch |
| Config management | Single `fc_config.yaml` | Per-chamber config files | Templated config generation |
| Topic naming | `fc/humidity` | `fc1/humidity`, `fc2/humidity` | Same pattern |
| Hardware isolation | All in one controller | Separate controller node per chamber | Same pattern |
| Control logic sharing | N/A | Shared base class or common module | Python module extracted to shared package |

For MVP, none of this needs to be built. The `fc/` topic prefix already accommodates future namespacing. Do not over-engineer for multi-chamber now.

---

## Sources

- [Using Callback Groups — ROS 2 Jazzy docs](https://docs.ros.org/en/jazzy/How-To-Guides/Using-callback-groups.html) — HIGH confidence (official)
- [rclpy Timer API — ROS 2 Jazzy](https://docs.ros.org/en/jazzy/p/rclpy/api/timers.html) — HIGH confidence (official)
- [Managed Nodes design article — ROS 2](https://design.ros2.org/articles/node_lifecycle.html) — HIGH confidence (official)
- [How to Use ROS 2 Lifecycle Nodes — Foxglove](https://foxglove.dev/blog/how-to-use-ros2-lifecycle-nodes) — MEDIUM confidence (third-party, consistent with official docs)
- [ROS2 rclpy Parameter Callback — Robotics Back-End](https://roboticsbackend.com/ros2-rclpy-parameter-callback/) — MEDIUM confidence (third-party tutorial, verified against official API)
- [Handling sensor timeouts/disconnects in ROS2 — ROS Answers](https://answers.ros.org/question/414290/handling-sensor-timeoutsdisconnects-in-ros2/) — MEDIUM confidence (community, consistent with timestamp pattern)
- [ROS 2 Common Issues and Mistakes — Karelics](https://karelics.fi/blog/2023/05/19/ros-2-common-issues-and-mistakes/) — MEDIUM confidence (practitioner post)
- Existing codebase: `fc_controller.py`, `fc_sensors.py`, `fc_config.yaml`, `test_controller.py` — HIGH confidence (ground truth for current state)
