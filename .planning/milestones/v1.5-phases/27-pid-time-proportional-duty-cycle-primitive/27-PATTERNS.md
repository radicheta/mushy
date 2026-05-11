# Phase 27: PID + time-proportional duty-cycle primitive — Pattern Map

**Mapped:** 2026-05-01
**Files analyzed:** 9 (3 NEW source, 3 NEW test, 3 MODIFY) + ancillary (setup.py, launch, config, bridge, systemd)
**Analogs found:** 9 / 9 — every new file has a strong in-repo analog

---

## File Classification

| File | New/Modified | Role | Data Flow | Closest Analog | Match Quality |
|------|--------------|------|-----------|----------------|---------------|
| `src/chambers/fc-core/fc_core/fc_pwm_driver.py` | NEW | controller (ROS node) | event-driven (sub) + periodic-tick (timer) → GPIO + pub | `src/chambers/fc-core/fc_core/fc_controller.py` | exact (same role, same data flow shape) |
| `src/chambers/fc-core/fc_core/_pid_kernel.py` | NEW | utility (thin wrapper) | pure transform (error → duty) | none — pure-Python helper, no ROS | n/a (use `simple-pid` API directly per RESEARCH §Code Examples) |
| `src/chambers/fc-core/fc_core/vendor/simple_pid/` | NEW (vendored, optional) | third-party library | n/a | n/a | vendored verbatim from PyPI — do not modify |
| `src/chambers/fc-core/fc_core/fc_controller.py` | MODIFY | controller (ROS node) | request-response → periodic + pub | self (in-place refactor) | n/a |
| `src/chambers/fc-core/fc_core/test/test_pid_kernel.py` | NEW | test (unit, pure-math) | request-response | none in repo (no pure-math tests yet) | partial — see test pattern from `test_controller.py` for fixture shape only |
| `src/chambers/fc-core/fc_core/test/test_pwm_driver.py` | NEW | test (ROS node) | event-driven | `src/chambers/fc-core/fc_core/test/test_controller.py` | exact |
| `src/chambers/fc-core/fc_core/test/test_controller.py` | MODIFY | test (ROS node) | event-driven | self (delete dwell tests, add PID-branch tests) | n/a |
| `src/chambers/fc-core/config/fc_config.yaml` | MODIFY | config | static | self | n/a |
| `src/chambers/fc-core/setup.py` | MODIFY | config (build) | static | self | n/a |
| `src/chambers/fc-core/launch/fc.launch.py` | MODIFY | config (launch) | static | self (existing `Node(...)` blocks) | n/a |
| `src/mission-control/bridge/src/index.js` | MODIFY | service (bridge subscriber) | event-driven (ROS sub → WS broadcast → DB insert) | self (existing `humidifier` subscription block) | n/a |
| `scripts/pi-deploy/fc-core.service` | NO CHANGE expected | config (systemd) | n/a | already-correct shape | n/a — see Shared Patterns §Restart=always trap |

---

## Pattern Assignments

### `src/chambers/fc-core/fc_core/fc_pwm_driver.py` (NEW — controller node, event-driven + periodic-tick)

**Analog:** `src/chambers/fc-core/fc_core/fc_controller.py` (single closest match — same package, same node skeleton, same QoS conventions, same sim/hw branch shape)

**Imports + node skeleton** (`fc_controller.py:1-13`, `:14-16`):
```python
#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Temperature, RelativeHumidity
from std_msgs.msg import Bool
import time
from collections import deque
from diagnostic_msgs.msg import DiagnosticStatus, KeyValue
from datetime import datetime
from statistics import median

class FruitingChamberController(Node):
    def __init__(self):
        super().__init__('fc_controller')
```
For the new driver: use `from std_msgs.msg import Float32, Bool`, drop sensor_msgs/diagnostic_msgs/datetime/median/deque-for-buffer (keep `deque` for the 5-min rolling-cap window per RESEARCH Pattern 2). Class name `SlowPwmDriver` (RESEARCH:317) or `FruitingChamberPwmDriver`; node name `'fc_pwm_driver'`.

**Parameter declaration pattern** (`fc_controller.py:18-40`):
```python
self.declare_parameters(
    namespace='',
    parameters=[
        ('actuator_simulation_mode', True),
        ('humidifier_pin', 17),
        ...
    ]
)
```
For the driver, declare: `humidifier_pin`, `pwm_window_seconds`, `min_pulse_seconds`, `max_duty_5min_avg`, `actuator_simulation_mode`, `duty_topic_timeout_seconds` (RESEARCH:320-327). Read each tick via `self.get_parameter('...').value` (matches existing pattern at `fc_controller.py:43, 209, 264`).

**Sim-mode / hardware branch pattern** (`fc_controller.py:42-78`):
```python
if not self.get_parameter('actuator_simulation_mode').value:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    self.humidifier_pin = self.get_parameter('humidifier_pin').value
    GPIO.setup(self.humidifier_pin, GPIO.OUT)
    GPIO.output(self.humidifier_pin, GPIO.LOW)
    self.GPIO = GPIO
else:
    self.humidifier_state = False
    self.get_logger().info('Actuators in simulation mode')
```
Copy verbatim, dropping fan/light. This is the exact GPIO-ownership block being moved out of fc_controller.

**TRANSIENT_LOCAL QoS profile** (`fc_controller.py:104-113`):
```python
actuator_qos = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)
self.humidifier_state_pub = self.create_publisher(
    Bool, 'fc1/actuators/humidifier', actuator_qos
)
```
Use the same profile for **both** the duty `Float32` subscription (RELIABLE+TRANSIENT_LOCAL — see Pitfall 5 in RESEARCH) and the `humidifier` Bool publisher (preserves the Phase 04 ACTR-03 contract — bridge already expects this; see `bridge/src/index.js:676-683`).

**Subscription pattern** (`fc_controller.py:81-90`):
```python
self.temp_sub = self.create_subscription(
    Temperature, 'fc1/temperature', self.temperature_callback, 10)
```
For the new duty subscription, pass `actuator_qos` (the QoSProfile) instead of `10` so it matches the publisher's TRANSIENT_LOCAL durability. Pattern: see `fc_controller.py:116-118` where `sensor_health_pub` uses `actuator_qos` directly.

**Timer + tick handler** (`fc_controller.py:142-145`, `:327`):
```python
self.timer = self.create_timer(
    self.get_parameter('control_interval').value,
    self.control_loop
)
```
Driver uses a 1.0s tick; tick body is RESEARCH Pattern 2 `_tick()` (lines 356-391 of 27-RESEARCH.md). Critical: do not bake `pwm_window_seconds` into timer period — keep tick at 1Hz and compare elapsed inside the tick.

**State-change-only relay-edge publish** (analog: `_publish_sensor_health` change-detection at `fc_controller.py:343-347`, `_set_humidifier_with_dwell` no-op short-circuit at `:204-207`):
```python
if state == current_state:
    return  # no transition
self.set_humidifier(state)
# ... publish on edge
```
Driver should publish `Bool` on every edge (not every tick) — matches the publish-on-change spirit and avoids the bridge writing a row to TimescaleDB at 1Hz when nothing changed. RESEARCH:393-399 already encodes this.

**Defensive OFF on subscription silence** (no exact analog — closest is staleness guard `fc_controller.py:354-360`):
```python
stale = False
if self._last_humidity_timestamp is not None:
    elapsed_sec = (
        self.get_clock().now() - self._last_humidity_timestamp
    ).nanoseconds / 1e9
    stale = elapsed_sec > self.get_parameter('sensor_stale_timeout').value
```
Apply same shape with `_last_duty_msg_ts` and `duty_topic_timeout_seconds` param. Defense-in-depth per RESEARCH §Architectural Responsibility Map row 6.

**`main()` shutdown pattern** (`fc_controller.py:410-423`):
```python
def main(args=None):
    rclpy.init(args=args)
    node = FruitingChamberController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if not node.get_parameter('actuator_simulation_mode').value:
            node.GPIO.cleanup()
        node.destroy_node()
        rclpy.shutdown()
```
Copy verbatim, dropping `fan_pwm.stop()`. GPIO cleanup is the only real-mode teardown the driver needs.

---

### `src/chambers/fc-core/fc_core/fc_controller.py` (MODIFY — refactor)

**Analog:** self. Modifications listed for planner sweep:

**KEEP unchanged:**
- `__init__` parameter declaration block (`:18-40`) minus `min_dwell_time` per D-15
- Sensor subscriptions (`:81-102`) — slot-1 + slot-2 + frame_id provenance unchanged
- `sensor_health_pub` and `_publish_sensor_health()` (`:115-118`, `:268-302`) — Phase 16/26 contract preserved
- `_grace_active()` (`:251-266`) — D-14
- Stale-detection block (`:354-360`) — D-13 still applies but now drives `duty=0.0` not GPIO
- `_compute_sht30_fresh()` / `_compute_scd41_fresh()` (`:304-325`) — Phase 26 contract preserved
- Light + fan branches in `control_loop()` (`:362-371`, `:394-395`) — outside humidity scope
- `_humidity_buffer` median pattern (`:122-123`, `:155-158`) — input to PID

**REMOVE:**
- `_set_humidifier_with_dwell()` method (`:198-226`) entirely
- `humidifier_state_pub = self.create_publisher(Bool, 'fc1/actuators/humidifier', ...)` (`:111-113`) — fc_pwm_driver is now the sole writer (RESEARCH Pitfall 4)
- `humidifier_state_pub.publish(state_msg)` block at end of `control_loop()` (`:397-400`) — same reason
- `_last_humidifier_toggle`, `_dwell_blocked_desired` state attrs (`:125, :127`)
- `humidifier_pin` GPIO setup branch (`:62-72` real-mode, lines 75-78 sim-mode `humidifier_state`) — moves to fc_pwm_driver
- `set_humidifier()`, `get_humidifier_state()` methods (`:192-196`, `:241-244`)
- `min_dwell_time` from `declare_parameters` (`:36`) per D-15

**ADD:**
- `from std_msgs.msg import Float32` (alongside existing `Bool` import — though Bool import can be dropped since the publisher leaves)
- `from simple_pid import PID` (or `from fc_core.vendor.simple_pid import PID` if vendored)
- New params: `pid_kp`, `pid_ki`, `pid_kd`, `pid_setpoint_ramp_seconds`, `bypass_threshold`, `pid_derivative_filter_tau`
- `self._duty_pub = self.create_publisher(Float32, 'fc1/actuators/humidifier_duty', actuator_qos)` (mirrors `:111-113` shape, TRANSIENT_LOCAL QoS — RESEARCH Pitfall 5)
- PID engagement state machine (RESEARCH §Code Examples "Bumpless transfer engagement", `_engage_pid_bumplessly()` / `_disengage_pid()`)
- `_effective_setpoint` + `_ramp_setpoint(dt)` (RESEARCH §Code Examples "Setpoint ramp")
- PID compute block in `control_loop()` replacing the `if/elif` at `:389-392` — see RESEARCH Pattern 1 (lines 281-305 of 27-RESEARCH.md)

**Safe-state contract preserved** — old `set_humidifier(False)` calls at `:330, :350, :380` become `self._publish_duty(0.0)` + `self._disengage_pid()` (RESEARCH Pattern 1 lines 282-285). The grace-active path at `:330` and the `current_humidity is None` path at `:350` and the stale-active path at `:380` all share the same "duty=0, disengage" treatment.

---

### `src/chambers/fc-core/fc_core/test/test_pwm_driver.py` (NEW)

**Analog:** `src/chambers/fc-core/fc_core/test/test_controller.py`

**Fixture pattern** (`test_controller.py:21-25`):
```python
@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()
```
Copy verbatim.

**Mock-clock pattern** (`test_controller.py:13-19`):
```python
_ROS_TIME = rclpy.time.ClockType.ROS_TIME

def _mock_clock_at(nanoseconds):
    mock_clock = MagicMock()
    mock_clock.now.return_value = rclpy.time.Time(
        nanoseconds=nanoseconds, clock_type=_ROS_TIME
    )
    return mock_clock
```
Copy verbatim — needed for window-elapsed math and rolling-5min cap tests.

**Time-stepping test pattern** (`test_controller.py:185-204` `test_dwell_time_blocks_toggle`):
```python
with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
    for _ in range(5):
        _send_humidity(node, 0.70)
    node.control_loop()
    assert node.humidifier_state == True

with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(10e9))):
    ...
    node.control_loop()
    assert node.humidifier_state == True  # blocked
```
Apply this shape to: window-rollover at exactly `pwm_window_seconds`, min-pulse round-down (duty=0.05 → 0 ON within window), rolling-5min cap engagement, defensive-OFF on duty silence.

**Capture-published-messages pattern** (`test_controller.py:371-388` `test_humidifier_state_published`):
```python
published = []
node.humidifier_state_pub.publish = lambda msg: published.append(msg.data)
...
node.control_loop()
assert len(published) == 1
assert published[0] == True
```
Use this to assert the driver publishes `Bool` only on edges, not every tick.

**QoS assertion pattern** (`test_controller.py:558-564`):
```python
def test_sensor_health_qos_transient_local(ros_context):
    node = FruitingChamberController()
    qos = node.sensor_health_pub.qos_profile
    assert qos.durability == DurabilityPolicy.TRANSIENT_LOCAL
    assert qos.depth == 1
```
Copy for the duty subscription QoS check (RESEARCH Pitfall 5).

---

### `src/chambers/fc-core/fc_core/test/test_pid_kernel.py` (NEW — pure unit tests)

**Analog:** none in repo (no existing pure-math tests). Use ordinary pytest layout — no `ros_context` fixture needed since `simple-pid` does not depend on rclpy. Tests assert on numerical behavior:

- bumpless preload: `pid.set_auto_mode(True, last_output=0.15); first_call(error=0)` returns ≈ 0.15
- output saturation at 1.0 for large positive error
- conditional integration when saturated (`pid._integral` does not grow beyond what output_limits accept) — see RESEARCH Pattern 1 commentary
- D-on-measurement does not kick on setpoint change

---

### `src/chambers/fc-core/fc_core/test/test_controller.py` (MODIFY)

**Delete** (because the underlying behavior is gone):
- `test_humidity_control` (`:62-87`) — bang-bang ON/OFF assertions on `node.humidifier_state` (attribute moves to fc_pwm_driver)
- `test_dwell_time_blocks_toggle` (`:185-204`)
- `test_dwell_time_allows_toggle_after_wait` (`:207-226`)
- `test_dwell_time_first_toggle_always_allowed` (`:229-242`)
- `test_dwell_time_applies_both_directions` (`:245-266`)
- `test_safe_state_updates_dwell_toggle` (`:329-347`) — no more `_last_humidifier_toggle`
- `test_humidifier_state_published` (`:371-388`) — replace with duty-published variant (assert `_duty_pub` got `Float32(0.0)` on grace, etc.)
- `test_new_params_declared` (`:155-160`) `min_dwell_time == 300.0` assertion
- `test_none_humidity_safe_state`, `test_none_temp_safe_state` (`:163-181`) — rewrite to assert duty=0 published instead of `humidifier_state == False`
- `test_sensor_staleness` (`:269-285`), `test_safe_state_recovery` (`:288-309`), `test_fresh_data_not_stale` (`:350-368`) — rewrite to assert duty topic instead of GPIO state

**Keep unchanged:**
- `test_controller_initialization`, `test_temperature_control`, `test_light_control`
- `test_humidity_spike_rejection`, `test_humidity_median_partial_buffer`, `test_humidity_buffer_fifo`
- All `test_warmup_*` tests (`:402-555`) — D-14 grace contract preserved, but if any of them reach into `node.humidifier_state` they need the same duty-pub rewrite (e.g. `test_warmup_grace_blocks_actuation:420` asserts `humidifier_state == False` — change to `duty_published[-1] == 0.0`)
- All `test_sht30/scd41_*` tests (`:572-631`) — Phase 26 D-03 unchanged
- `test_sensor_health_*` (`:484-564`) — Phase 16 contract unchanged
- `test_staleness_log_deduplication` (`:312-326`) — log dedupe pattern still applies

**Add:** PID engagement, bumpless preload happens on grace-clear, Mode C activation when `|error| > bypass_threshold`, ramp slews effective_setpoint not actual target.

---

### `src/chambers/fc-core/config/fc_config.yaml` (MODIFY)

**Analog:** self.

**Remove:** line 37 `min_dwell_time: 180.0  # ...` (D-15).

**Add** (under "Safety guards" or new "PID + slow-PWM" section), with values from RESEARCH §Discretion-Default Recommendations:
```yaml
    # PID gains (Phase 27 — Skogestad SIMC defaults from 2026-04-11 calibration)
    pid_kp: 0.5
    pid_ki: 0.002
    pid_kd: 4.0
    pid_derivative_filter_tau: 10.0
    pid_setpoint_ramp_seconds: 30.0
    bypass_threshold: 0.025         # Mode C entry: |error| > 2.5% RH
    # Slow-PWM (fc_pwm_driver)
    pwm_window_seconds: 120.0       # LOCKED per D-08
    min_pulse_seconds: 10.0         # LOCKED per D-11
    max_duty_5min_avg: 0.40         # rolling 5-min duty cap (D-12)
    duty_topic_timeout_seconds: 5.0 # defensive OFF if duty subscription silent
```

Existing comment style is inline-`#`; match it.

---

### `src/chambers/fc-core/setup.py` (MODIFY)

**Analog:** self.

**Add to `install_requires`** (`:18-27`):
```python
'simple-pid>=2.0,<3.0',
```
Or skip if vendoring (RESEARCH:131 — fallback path).

**Add to `entry_points.console_scripts`** (`:34-42`), matching the existing comma-list shape:
```python
'fc_pwm_driver = fc_core.fc_pwm_driver:main',
```

---

### `src/chambers/fc-core/launch/fc.launch.py` (MODIFY)

**Analog:** self — copy any existing `Node(...)` block (`:24-30` `fc_sensors`, `:33-39` `fc_controller`, `:42-48` `fc_display`, `:51-57` `fc_camera`).

**Add new `Node(...)` entry** before `fc_camera`:
```python
Node(
    package='fc_core',
    executable='fc_pwm_driver',
    name='fc_pwm_driver',
    parameters=[LaunchConfiguration('config_file')],
    output='screen'
),
```
Verbatim shape from RESEARCH Pattern 3 (line 406-412) and matches existing `:33-39` four-attribute structure.

---

### `src/mission-control/bridge/src/index.js` (MODIFY)

**Analog:** the existing humidifier-Bool subscription block (`:675-699`) is the closest match (TRANSIENT_LOCAL, broadcast + DB insert).

**Add to ALLOWED_TOPICS** (`:346`):
```javascript
const ALLOWED_TOPICS = ['fc.humidity', 'fc.temperature', 'fc.co2', 'fc.humidifier', 'fc.humidity_2', 'fc.temperature_2', 'fc.humidifier_duty'];
```

**Add a new subscription** mirroring the humidifier block (RESEARCH Pitfall 5 — must use TRANSIENT_LOCAL to match publisher):
```javascript
// Phase 27: subscribe to fc1/actuators/humidifier_duty -> fc.humidifier_duty
// TRANSIENT_LOCAL matches fc_controller publisher (Pitfall 5).
node.createSubscription(
    'std_msgs/msg/Float32',
    '/fc1/actuators/humidifier_duty',
    { qos: humidifierQos },           // reuse the QoS object defined at :676-683
    async (msg) => {
        const value = msg.data;        // already 0.0–1.0 per D-02 — do NOT rescale
        const ts = Date.now();
        latestTelemetry.humidifier_duty = { value, timestamp: ts };
        broadcast({ humidifier_duty: value, timestamp: ts });
        await insertTelemetry('fc.humidifier_duty', value);
    }
);
console.log('[bridge] Humidifier-duty subscription: TRANSIENT_LOCAL QoS');
```

**Note:** the float-scalar shape is identical to the existing `/fc1/co2` block (`:663-673`), but the QoS must be TRANSIENT_LOCAL (like humidifier Bool, NOT like co2 which is VOLATILE). The QoS object at `:676-683` is reusable as-is.

**Specifics insight from CONTEXT (line 112):** "Don't rescale to 0–100% downstream for readability." The bridge must pass through the 0.0–1.0 value untouched, unlike the existing `humidity` line (`:612` `msg.relative_humidity * 100`).

---

### `scripts/pi-deploy/fc-core.service` — NO CHANGE expected

**Analog:** self.

The unit at `:28` is already `Restart=always` — **leave it alone**. RESEARCH:415 confirms: adding fc_pwm_driver to `fc.launch.py` does not require a new systemd unit or unit-file change. The launch wrapper already covers the new node under the existing `Restart=always` policy.

**Memory anchor — `feedback_systemd_restart_ros2_launch`:** if a planner is tempted to "be safe" by switching to `Restart=on-failure` because the new node has a defensive-OFF path that exits cleanly: don't. `ros2 launch` exits 0 on child crashes, so `on-failure` would not restart on a child crash. Keep `Restart=always`. (See StartLimitBurst=5 / StartLimitIntervalSec=300 already at lines 5-6 — burst guard already in place.)

**Memory anchor — `feedback_diff_repo_vs_pi_systemd`:** before any planner edits this file, diff against `/etc/systemd/system/fc-core.service` on fc1 over Tailscale. Hand-edits on the Pi exist and have drifted from the repo before.

---

## Shared Patterns

### TRANSIENT_LOCAL QoS for actuator + diagnostic topics

**Source:** `src/chambers/fc-core/fc_core/fc_controller.py:104-118`

**Apply to:** `humidifier_duty` publisher (fc_controller), `humidifier_duty` subscriber (fc_pwm_driver), bridge subscription on `humidifier_duty`.

```python
actuator_qos = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)
self.humidifier_state_pub = self.create_publisher(
    Bool, 'fc1/actuators/humidifier', actuator_qos
)
self.sensor_health_pub = self.create_publisher(
    DiagnosticStatus, 'fc1/sensor_health', actuator_qos
)
```

Bridge equivalent (`src/mission-control/bridge/src/index.js:676-683`):
```javascript
const humidifierQos = new rclnodejs.QoS(
    rclnodejs.QoS.HistoryPolicy.RMW_QOS_POLICY_HISTORY_KEEP_LAST,
    1,
    rclnodejs.QoS.ReliabilityPolicy.RMW_QOS_POLICY_RELIABILITY_RELIABLE,
    rclnodejs.QoS.DurabilityPolicy.RMW_QOS_POLICY_DURABILITY_TRANSIENT_LOCAL,
    rclnodejs.QoS.LivelinessPolicy.RMW_QOS_POLICY_LIVELINESS_SYSTEM_DEFAULT,
    false
);
```

### Publish-on-change-only

**Source:** `src/chambers/fc-core/fc_core/fc_controller.py:268-302` (`_publish_sensor_health`) and the change-detection guard at `:341-347`:
```python
sht30_fresh = self._compute_sht30_fresh()
scd41_fresh = self._compute_scd41_fresh()
if (sht30_fresh != self._last_sht30_fresh
        or scd41_fresh != self._last_scd41_fresh):
    self._publish_sensor_health(warming_up=False)
```

Also seen at `_set_humidifier_with_dwell` short-circuit (`:204-207`):
```python
if state == current_state:
    self._dwell_blocked_desired = None
    return  # no transition needed
```

**Apply to:** fc_pwm_driver `_set_relay()` — only publish `Bool` when `state != self._current_state`. Avoids spamming the bridge / Timescale at 1Hz when the relay is steady within a window.

**Note:** `humidifier_duty` itself is published *every* tick (RESEARCH Anti-Pattern: 1Hz is fine, 86k rows/day). Publish-on-change applies to the relay-edge `Bool`, not the duty `Float32`.

### Stale-detection / safe-state guard

**Source:** `src/chambers/fc-core/fc_core/fc_controller.py:354-381`
```python
stale = False
if self._last_humidity_timestamp is not None:
    elapsed_sec = (
        self.get_clock().now() - self._last_humidity_timestamp
    ).nanoseconds / 1e9
    stale = elapsed_sec > self.get_parameter('sensor_stale_timeout').value

if stale:
    if not self._safe_state_active:
        self._safe_state_active = True
        self.get_logger().warn(
            'Sensor data stale — humidifier OFF for safety'
        )
    self.set_humidifier(False)
    ...
else:
    if self._safe_state_active:
        self._safe_state_active = False
        self.get_logger().info('Fresh sensor data received — resuming control')
```

**Apply to:**
- fc_controller `control_loop()` (modified): replace `self.set_humidifier(False)` with `self._publish_duty(0.0); self._disengage_pid()` while preserving the log-dedupe `_safe_state_active` flag
- fc_pwm_driver `_tick()`: same shape but for `_last_duty_msg_ts` against `duty_topic_timeout_seconds` — defensive OFF when controller goes silent

### Sim/hardware mode branching

**Source:** `fc_controller.py:42-78` (init), `:185-249` (set_*/get_* methods).

Pattern:
```python
def set_humidifier(self, state):
    if not self.get_parameter('actuator_simulation_mode').value:
        self.GPIO.output(self.humidifier_pin, self.GPIO.HIGH if state else self.GPIO.LOW)
    else:
        self.humidifier_state = state
```

**Apply to:** fc_pwm_driver `_set_relay()`. Tests will set `actuator_simulation_mode=True` and read `node.humidifier_state` directly. Critical (RESEARCH Pitfall 7): tests in `test_controller.py` that read `node.humidifier_state` must move to `test_pwm_driver.py`.

### Mock-clock test fixture

**Source:** `src/chambers/fc-core/fc_core/test/test_controller.py:13-25`

Reuse for fc_pwm_driver tests (window rollover, defensive-OFF timeout, rolling-5min cap need clock-stepping).

---

## No Analog Found

| File | Reason | Planner falls back to |
|------|--------|-----------------------|
| `fc_core/_pid_kernel.py` (or `vendor/simple_pid/`) | No PID code anywhere in the repo | RESEARCH §Code Examples (Bumpless transfer + Setpoint ramp blocks); `simple-pid` upstream README. Plan: import `simple_pid.PID` directly in fc_controller — a separate `_pid_kernel.py` is only needed if vendoring or wrapping with project-specific helpers (probably not necessary; YAGNI per CLAUDE.md "Simplicity First"). |
| `test_pid_kernel.py` | No pure-math tests in repo (all tests are ROS-node tests) | Plain pytest, no `ros_context` fixture. Pattern is straight pytest assertions on `pid()` return values. |

---

## Memory-Anchor Reminders for the Planner

These project-memory items must surface in the affected plan(s):

1. **`feedback_systemd_restart_ros2_launch`** — fc-core.service must stay on `Restart=always`. Adding fc_pwm_driver to fc.launch.py does NOT need a new unit. (See `scripts/pi-deploy/fc-core.service:28`.)
2. **`feedback_diff_repo_vs_pi_systemd`** — diff repo unit against fc1's `/etc/systemd/system/fc-core.service` over Tailscale (fc1-ts, 100.96.239.75) before any commit that touches `scripts/pi-deploy/`.
3. **`feedback_gap_over_noise`** — confirms D-13: stale → duty=0.0, NOT "freeze last duty". Already locked, but worth surfacing in the controller plan's safety section.
4. **TRANSIENT_LOCAL pattern** — both publisher (controller) and subscriber (pwm_driver, bridge) must agree. Mismatch = silent data drop. RESEARCH Pitfall 5 has the warning sign.
5. **Publish-on-change-only** — apply to relay edges, not to the duty topic itself.

---

## Metadata

**Analog search scope:**
- `src/chambers/fc-core/fc_core/` (all .py files)
- `src/chambers/fc-core/fc_core/test/` (all .py files)
- `src/chambers/fc-core/launch/`, `config/`, `setup.py`
- `src/mission-control/bridge/src/index.js`
- `scripts/pi-deploy/fc-core.service`

**Files scanned:** ~12
**Pattern extraction date:** 2026-05-01
