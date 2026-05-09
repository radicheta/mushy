# Phase 26: Dual sensor publishing + offline alarms — Pattern Map

**Mapped:** 2026-04-25
**Files analyzed:** 9 (8 modified + 1 new test)
**Analogs found:** 9 / 9 (all in-tree; this is an extension phase, not a greenfield phase)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/chambers/fc-core/fc_core/fc_sensors.py` (M) | ROS2 publisher node | timer-driven pub-sub | (self — refactor) | exact (in-place) |
| `src/chambers/fc-core/fc_core/fc_controller.py` (M) | ROS2 controller node | event-driven + sub | (self — extend `_publish_sensor_health`) | exact (in-place) |
| `src/mission-control/bridge/src/index.js` (M) | WS bridge / DB writer | request-response + pub-sub | self — slot-1 sub block L619-630 | exact |
| `src/agents/alerter/src/state.js` (M) | state machine | event-driven | self — `pi_liveness` case L268-307 + `tick` case L309-345 | exact |
| `src/agents/alerter/src/rules.js` (M) | predicate module | pure function | self — `isPiOffline` L27-39 | exact |
| `src/agents/alerter/src/index.js` (M) | event router / boot | event-driven | self — `sensor_health` route L77-83 | exact |
| `src/agents/alerter/src/message.js` (M) | template formatter | pure function | self — `ALERT_TITLES` map L3-8 + `formatProblem` `pi` branch L58-62 | exact |
| `src/agents/alerter/src/snooze.js` (M) | input validator | pure function | self — `STRICT` regex L15 + `VALID_ALERT_TYPES` L3 | exact |
| `src/chambers/fc-core/fc_core/test/test_sensors.py` (NEW) | pytest unit test | test | `src/chambers/fc-core/fc_core/test/test_controller.py` | role-match |

**Note:** Slot 2 is engineer/alerter-facing this phase per `26-RESEARCH.md` Per-Consumer Impact Table. Skipped (per scope): `fc_telemetry.py`, `fc_display.py`, `farmos-agent`, farmer dashboard, OpenMCT plugin overlay (deferred to 999.17).

---

## Pattern Assignments

### `fc_sensors.py` (publisher node, timer-driven pub-sub) — MODIFIED IN PLACE

**Analog:** self — current single-slot publisher (read in full L1-143)

**Imports pattern** (L1-6, unchanged):
```python
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Temperature, RelativeHumidity
from std_msgs.msg import Float32
import random
```

**Publisher creation pattern** (L55-58 — copy exactly for slot 2):
```python
self.temp_pub = self.create_publisher(Temperature, 'fc1/temperature', 10)
self.humidity_pub = self.create_publisher(RelativeHumidity, 'fc1/humidity', 10)
self.co2_pub = self.create_publisher(Float32, 'fc1/co2', 10)
# NEW (Phase 26): two more publishers, identical depth=10 default QoS
# self.temp_2_pub     = self.create_publisher(Temperature,      'fc1/temperature_2', 10)
# self.humidity_2_pub = self.create_publisher(RelativeHumidity, 'fc1/humidity_2',    10)
```

**Header timestamp + unit conversion pattern** (L98-109 — reuse for slot 2 publishes):
```python
# Publish temperature
if temperature is not None:
    temp_msg = Temperature()
    temp_msg.header.stamp = self.get_clock().now().to_msg()
    temp_msg.temperature = float(temperature)
    self.temp_pub.publish(temp_msg)

# Publish humidity — RelativeHumidity msg expects 0.0-1.0
if humidity is not None:
    humidity_msg = RelativeHumidity()
    humidity_msg.header.stamp = self.get_clock().now().to_msg()
    humidity_msg.relative_humidity = float(humidity) / 100.0
    self.humidity_pub.publish(humidity_msg)
```

**Anti-pattern in current code (Pitfall 1 — RESEARCH §Common Pitfalls)** L67-68 wraps the entire `read_sensors` body in *one* try/except, so any SHT30 I2C exception aborts the whole tick (including SCD41). Phase 26 must split into per-sensor try/except — see RESEARCH Pattern 1 L162-203 for the canonical refactor shape.

**Slot-1 silent fallback** (L75-85 — preserve verbatim per D-01):
```python
# Read SHT30 if available
if self.sht is not None:
    temperature = self.sht.temperature
    humidity = self.sht.relative_humidity

# Read SCD41 if available
if self.scd is not None and self.scd.data_ready:
    co2 = self.scd.CO2
    # Use SCD41 temp/humidity as fallback if no SHT30
    if temperature is None:
        temperature = self.scd.temperature
        humidity = self.scd.relative_humidity
```

**Simulation mode** (L86-95 — Pitfall 6: must also feed slot-2 in sim, jittered):
```python
self.sim_temp += random.uniform(-0.1, 0.1)
self.sim_humidity += random.uniform(-0.01, 0.01)
self.sim_co2 += random.uniform(-5.0, 5.0)
self.sim_temp = max(15.0, min(30.0, self.sim_temp))
# ...
```

**Error handling** (L127-128 — non-fatal log-and-continue, established pattern):
```python
except Exception as e:
    self.get_logger().error(f'Failed to read sensor: {e}')
```

---

### `fc_controller.py` (controller node, event-driven + sub) — MODIFIED IN PLACE

**Analog:** self — `_publish_sensor_health` method L235-262, slot-1 staleness guard L283-289

**Subscription creation pattern** (L81-90 — mirror this for slot-2 subs to compute `scd41_fresh`):
```python
self.temp_sub = self.create_subscription(
    Temperature,
    'fc1/temperature',
    self.temperature_callback,
    10)
self.humidity_sub = self.create_subscription(
    RelativeHumidity,
    'fc1/humidity',
    self.humidity_callback,
    10)
# NEW (Phase 26): add temp_2_sub / humidity_2_sub on /fc1/temperature_2 / /fc1/humidity_2,
# storing self._last_temp2_timestamp / self._last_humidity2_timestamp like the existing
# self._last_humidity_timestamp at L136.
```

**Per-sensor freshness timestamp pattern** (L133-136 — copy for slot-2 callbacks):
```python
def humidity_callback(self, msg):
    self._humidity_buffer.append(msg.relative_humidity)
    self.current_humidity = median(self._humidity_buffer)
    self._last_humidity_timestamp = self.get_clock().now()
```

**Staleness check pattern** (L283-289 — reuse `sensor_stale_timeout` parameter):
```python
stale = False
if self._last_humidity_timestamp is not None:
    elapsed_sec = (
        self.get_clock().now() - self._last_humidity_timestamp
    ).nanoseconds / 1e9
    stale = elapsed_sec > self.get_parameter('sensor_stale_timeout').value
```

**TRANSIENT_LOCAL QoS for sensor_health** (L92-98, L103-106 — DO NOT change; append-only changes to KeyValue list):
```python
actuator_qos = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)
self.sensor_health_pub = self.create_publisher(
    DiagnosticStatus, 'fc1/sensor_health', actuator_qos
)
```

**KeyValue list — APPEND-ONLY extension** (L256-261 — Pitfall 4: do not rename/remove existing keys):
```python
msg.values = [
    KeyValue(key='warming_up',         value=str(warming_up).lower()),
    KeyValue(key='grace_elapsed_sec',  value=f'{elapsed:.1f}'),
    KeyValue(key='grace_total_sec',    value=f'{grace_period:.1f}'),
    KeyValue(key='buffer_full',        value=str(buffer_full).lower()),
    # NEW (Phase 26): append two freshness flags. See RESEARCH Example B L321-336.
    # KeyValue(key='sht30_fresh', value=str(sht30_fresh).lower()),
    # KeyValue(key='scd41_fresh', value=str(scd41_fresh).lower()),
]
self.sensor_health_pub.publish(msg)
```

**Quiet-topic republish pattern** (L268-275 — `_warmup_signal_published` flag — extend to per-sensor flip detection per RESEARCH Open Question 1):
```python
if self._grace_active():
    self.set_humidifier(False)
    if not self._warmup_signal_published:
        self._publish_sensor_health(warming_up=True)
        self._warmup_signal_published = True
    return
if self._warming_up:
    self._warming_up = False
    self._publish_sensor_health(warming_up=False)
    self.get_logger().info('WARMUP-CLEARED: control loop engaging')
```

Phase 26 mirrors this pattern: track `_last_sht30_fresh` / `_last_scd41_fresh`; call `_publish_sensor_health(...)` on flip only — preserves Phase 16's "quiet topic" property.

---

### `bridge/src/index.js` (WS bridge / DB writer, pub-sub + DB insert) — MODIFIED IN PLACE

**Analog:** self — slot-1 temperature subscription L619-630 (copy verbatim with topic + telemetry-name swap)

**Default-QoS subscription pattern** (L619-630 — Pitfall 2: do NOT add `{ qos: ... }` for slot 2; gap-over-noise demands VOLATILE):
```javascript
// Subscribe: fc1/temperature -> fc.temperature
node.createSubscription(
    'sensor_msgs/msg/Temperature',
    '/fc1/temperature',
    async (msg) => {
        const value = msg.temperature;
        const ts = Date.now();
        latestTelemetry.temperature = { value, timestamp: ts };
        broadcast({ temperature: value, timestamp: ts });
        await insertTelemetry('fc.temperature', value);
    }
);
```

**Slot-1 humidity subscription** (L607-617 — note `* 100` unit conversion from RelativeHumidity 0–1 to %):
```javascript
node.createSubscription(
    'sensor_msgs/msg/RelativeHumidity',
    '/fc1/humidity',
    async (msg) => {
        const value = msg.relative_humidity * 100;
        const ts = Date.now();
        latestTelemetry.humidity = { value, timestamp: ts };
        broadcast({ humidity: value, timestamp: ts });
        await insertTelemetry('fc.humidity', value);
    }
);
```

**INSERT pattern (no schema change)** (L580-591 — `topic` is free-form text):
```javascript
async function insertTelemetry(topic, value) {
    if (!dbReady) return;
    try {
        await pool.query(
            'INSERT INTO telemetry (time, topic, value) VALUES ($1, $2, $3)',
            [new Date(), topic, value]
        );
    } catch (err) {
        console.error('[db] insert failed:', err.message);
    }
}
```

**Anti-pattern to avoid:** Slot-2 subs MUST NOT use the `humidifierQos` / `sensorHealthQos` TRANSIENT_LOCAL profile (L646-679). Those are for state topics that need replay; slot-2 is a stream where gaps are signal (D-03).

**RESEARCH Example E** (line 365-379) shows the literal copy/paste shape. Two subs (`/fc1/temperature_2` → `fc.temperature_2`, `/fc1/humidity_2` → `fc.humidity_2`).

---

### `alerter/src/state.js` (state machine, event-driven) — MODIFIED IN PLACE

**Analog:** self — `pi_liveness` case L268-307 + `tick` case L309-345 + `sensor_health` ERROR pathway L212-227

**ALERT_TYPES + SEVERITY extension** (L8-11 — append, do not rename):
```javascript
const ALERT_TYPES = ['rh', 'sensor', 'pi', 'humidifier'];
// Severity per alert type
const SEVERITY = { rh: 'WARN', sensor: 'CRITICAL', pi: 'CRITICAL', humidifier: 'WARN' };
// NEW (Phase 26): add 'sht30' and 'scd41', both CRITICAL.
```

**`initialState` per-type bootstrap** (L13-24 — auto-handles new types because it iterates `ALERT_TYPES`; no extra plumbing):
```javascript
function initialState(nowMs = Date.now()) {
  const perType = {};
  for (const t of ALERT_TYPES) {
    perType[t] = {
      state: STATES.OK,
      oobCount: 0,
      firstOobAt: null,
      lastFiredAt: null,
      snoozedUntil: null,
      ctx: {},
    };
  }
  return { /* ... */ perType };
}
```

For per-sensor freshness tracking, add fields next to `humidifierLastMsgTs` (L33): `sht30LastSeenMs`, `scd41LastSeenMs`. Initialize to `bootedAtMs` (RESEARCH Pitfall 5) — never `null` — so the 60s startup grace cleanly suppresses the first ~5 min.

**oobN=1 immediate-fire trick** (L216-219 — mirror for sensor freshness; silence is binary, no consecutive-sample window needed):
```javascript
if (isError) {
    // sensor fires on first ERROR event (oobN=1, oobWindowMin=0)
    const sensorCfg = { ...config, oobN: 1, oobWindowMin: 0 };
    const r = driveAlertType(next.perType.sensor, 'sensor', true, sensorFields, now, sensorCfg);
    next.perType.sensor = r.next;
    actions.push(...r.actions);
}
```

**Startup-grace gate** (L290-291 — copy verbatim for sensor freshness):
```javascript
// Startup grace: skip Pi-offline evaluation for first 60s
if (now - next.bootedAtMs < 60000) break;
```

**Tick re-evaluation pattern** (L309-345 — sensor freshness MUST be re-evaluated here; no message arrives during silence, so without tick re-eval the FIRING transition would never happen):
```javascript
case 'tick': {
  // ...
  // Re-evaluate Pi offline
  if (now - next.bootedAtMs >= 60000) {
    const offline = isPiOffline({ /* ... */ });
    const piFields = { lastSeenMs: next.wsLastConnectedMs };
    const r = driveAlertType(next.perType.pi, 'pi', offline, piFields, now, config);
    next.perType.pi = r.next;
    actions.push(...r.actions);
  }
  // NEW (Phase 26): mirror this block for 'sht30' and 'scd41' using isSensorSilent +
  // next.sht30LastSeenMs / next.scd41LastSeenMs.
  break;
}
```

**Timestamp refresh on slot-2 arrival** (event router — see also `index.js` below). For SCD41, refresh `scd41LastSeenMs = now` whenever a `temperature_2` or `humidity_2` arrives. For SHT30, the alerter never gets a direct sensor signal (D-01 makes slot-1 ambiguous); freshness comes from `sensor_health.values.sht30_fresh` parsed inside the existing `sensor_health` case (L204-228) per RESEARCH Open Question 2.

---

### `alerter/src/rules.js` (predicate module, pure function) — MODIFIED IN PLACE

**Analog:** self — `isPiOffline` L27-39 (template for new `isSensorSilent`)

**Predicate template** (L27-39 — copy this shape exactly; threshold via `config.sensorOfflineMin * 60000`):
```javascript
function isPiOffline({ wsConnected, rosConnected, nowMs, wsLastConnectedMs, rosDisconnectedSinceMs, config }) {
  const thresholdMs = config.piOfflineMin * 60000;

  if (!wsConnected && wsLastConnectedMs != null) {
    if (nowMs - wsLastConnectedMs > thresholdMs) return true;
  }
  // ...
  return false;
}
```

**Module export** (L56 — extend the export tuple):
```javascript
module.exports = { isRhOob, isSensorError, isPiOffline, isHumidifierStuck };
// NEW (Phase 26): add isSensorSilent. RESEARCH Example D L355-361 has the canonical body.
```

---

### `alerter/src/index.js` (event router, event-driven) — MODIFIED IN PLACE

**Analog:** self — `onMessage` route table L66-85 + tick scheduler L121

**Event-routing pattern** (L66-85 — extend with `temperature_2` / `humidity_2` branches that dispatch a `sensor_freshness` event with `sensor: 'scd41'`):
```javascript
onMessage(msg) {
  if (msg.humidity !== undefined) {
    applyEvent({ type: 'humidity', value: msg.humidity });
  } else if (msg.temperature !== undefined) {
    applyEvent({ type: 'temperature', value: msg.temperature });
  } else if (msg.co2 !== undefined) {
    applyEvent({ type: 'co2', value: msg.co2 });
  } else if (msg.humidifier !== undefined) {
    applyEvent({ type: 'humidifier', value: msg.humidifier });
  } else if (msg.sensor_health) {
    applyEvent({
      type: 'sensor_health',
      level: msg.sensor_health.level,
      message: msg.sensor_health.message,
      values: msg.sensor_health.values,  // already includes sht30_fresh / scd41_fresh post-Phase-26
    });
  }
  // NEW (Phase 26): refresh scd41LastSeenMs on temperature_2 / humidity_2 arrival.
  // Per RESEARCH Open Question 2, the SHT30 freshness signal lives inside the
  // existing sensor_health route (parse values.sht30_fresh).
}
```

**Tick scheduler** (L121 — already 30s; do not change):
```javascript
const tickTimer = setInterval(() => applyEvent({ type: 'tick' }), 30000);
```

**Action dispatch** (L47-60 — `send` and `recovery` already trigger `signalClient.send`; new types inherit for free):
```javascript
for (const action of result.actions) {
  try {
    if (action.kind === 'send' || action.kind === 'recovery') {
      await signalClient.send(action.body);
    } else if (action.kind === 'heartbeat') {
      await signalClient.send(action.body, { bypassCap: true });
    } else if (action.kind === 'snooze_ack') {
      await signalClient.send(action.body);
    }
  } catch (e) { /* ... */ }
}
```

---

### `alerter/src/message.js` (template formatter, pure function) — MODIFIED IN PLACE

**Analog:** self — `ALERT_TITLES` L3-8 + `formatProblem` `pi` branch L58-62

**ALERT_TITLES extension** (L3-8 — add two entries):
```javascript
const ALERT_TITLES = {
  pi:         'Pi offline',
  sensor:     'Sensor ERROR',
  rh:         'RH out of band',
  humidifier: 'Humidifier stuck',
  // NEW (Phase 26):
  // sht30:     'SHT30 offline',
  // scd41:     'SCD41 offline',
};
```

**Per-type formatProblem branch** (L58-62 — `pi` branch is the closest template; `lastSeenMs` semantic maps cleanly):
```javascript
} else if (alertType === 'pi') {
    const { lastSeenMs } = fields;
    if (lastSeenMs != null) {
      body += `Last seen: ${fmtRelative(lastSeenMs, nowMs)}\n`;
    }
}
// NEW (Phase 26): add sht30 / scd41 branches with the same {lastSeenMs} field shape.
// Per CONTEXT specifics L82, the alert wording must make the physical sensor unmistakable —
// the `ALERT_TITLES` ('SHT30 offline' / 'SCD41 offline') already does this; no extra wording needed.
```

**`formatRecovery`** (L90-104 — auto-handles new types via `ALERT_TITLES[alertType]` lookup):
```javascript
function formatRecovery({ alertType, fields, durationMs, config }) {
  const title = ALERT_TITLES[alertType] || alertType;
  let body = `[RECOVERY] FC-1 · ${title} back\n`;
  // ...
  if (durationMs != null) {
    body += `Was OOB for ${fmtDuration(durationMs)}\n`;
  }
  body += `Open: ${config.dashboardUrl}`;
  return body;
}
```

---

### `alerter/src/snooze.js` (input validator, pure function) — MODIFIED IN PLACE

**Analog:** self — `STRICT` regex L15 + `VALID_ALERT_TYPES` L3

**Whitelist + strict regex pattern** (L3, L15 — extend alternation in both):
```javascript
const VALID_ALERT_TYPES = ['rh', 'sensor', 'pi', 'humidifier', 'all'];
// ...
// Strict whitelist regex — anchored start/end, no extra content allowed.
const STRICT = /^snooze\s+(rh|sensor|pi|humidifier|all)\s+(30m|1h|2h|4h|8h|24h)\s*$/i;
// NEW (Phase 26): add 'sht30' and 'scd41' to BOTH the array and the regex alternation.
//   const VALID_ALERT_TYPES = ['rh', 'sensor', 'pi', 'humidifier', 'sht30', 'scd41', 'all'];
//   const STRICT = /^snooze\s+(rh|sensor|pi|humidifier|sht30|scd41|all)\s+(...)\s*$/i;
```

**`fuzzyReply` help text** (L17-25 — update the "Valid alert types" line to include the new types):
```javascript
function fuzzyReply() {
  return {
    ok: false,
    reply:
      'Sorry, didn\'t get that. Try: snooze rh 4h\n' +
      'Valid alert types: rh, sensor, pi, humidifier, all\n' +
      'Valid durations: 30m, 1h, 2h, 4h, 8h, 24h',
  };
}
```

**Security note (RESEARCH §Security Domain V5):** broaden by alternation only; do NOT loosen anchoring or whitespace handling.

---

### `test/test_sensors.py` (NEW pytest unit test, simulation-mode-driven)

**Analog:** `src/chambers/fc-core/fc_core/test/test_controller.py` (role-match — same package, same fixture pattern)

**Module imports + fixtures** (test_controller.py L1-25 — copy and swap the imported node):
```python
#!/usr/bin/env python3
import pytest
import rclpy
import rclpy.time
from sensor_msgs.msg import Temperature, RelativeHumidity
from fc_core.fc_controller import FruitingChamberController
import time
from unittest.mock import patch, MagicMock

_ROS_TIME = rclpy.time.ClockType.ROS_TIME

def _mock_clock_at(nanoseconds):
    """Return a mock clock whose .now() returns the given ROS time (ROS_TIME clock type)."""
    mock_clock = MagicMock()
    mock_clock.now.return_value = rclpy.time.Time(
        nanoseconds=nanoseconds, clock_type=_ROS_TIME
    )
    return mock_clock

@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()
```

For Phase 26, swap `FruitingChamberController` for `from fc_core.fc_sensors import FruitingChamberSensors` and use `sensor_simulation_mode=True` (RESEARCH Assumption A5 — sim path is fully software).

**Construction + bypass test** (test_controller.py L27-30 — minimal smoke):
```python
def test_controller_initialization(ros_context):
    node = FruitingChamberController()
    assert node is not None
    node.destroy_node()
```

**Mock injection + control_loop driving** (test_controller.py L32-60 — same `node.destroy_node()` cleanup, same `with patch.object(node, 'get_clock', return_value=_mock_clock_at(...))` time control):

For sensor tests, mock `self.sht` / `self.scd` to control which sensor "responds" each tick (RESEARCH §Wave 0 Gaps L528). Test cases (RESEARCH §Phase Requirements → Test Map):
- `test_slot1_uses_sht30_when_present` (D-01)
- `test_slot1_falls_back_to_scd41` (D-01)
- `test_slot2_publishes_scd41` (D-02)
- `test_slot2_independent_of_sht30` (D-02)
- `test_no_stale_publish` (D-03)

---

### Existing alerter test extension (`test/state.test.js`) — MODIFIED IN PLACE

**Analog (in same file):** `describe('warmup_does_NOT_suppress_sensor_error (ALRT-05)')` L245-258

**Test structure** (L245-258 — copy block; replace `level: 2` with `values.sht30_fresh: 'false'` and assert `alertType === 'sht30'`):
```javascript
describe('warmup_does_NOT_suppress_sensor_error (ALRT-05)', () => {
  test('sensor_health level=2 fires even during warm-up', () => {
    let state = initialState(T0);
    let r = transition(state, { type: 'sensor_health', level: 1, message: 'warming up', values: {} }, T0, makeConfig());
    state = r.next;
    expect(state.warmingUp).toBe(true);
    r = transition(state, { type: 'sensor_health', level: 2, message: 'ERROR', values: {} }, T0 + 35000, makeConfig());
    const sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'sensor');
    expect(sends).toHaveLength(1);
  });
});
```

Phase-26 cases per RESEARCH §Phase Requirements (D-04 through D-06):
- `sht30 fires after sensorOfflineMin`
- `scd41 fires after sensorOfflineMin`
- `sht30 silence does not fire scd41` (D-05 isolation)
- `sht30 recovery on freshness flip` (D-06)
- `sht30 repeats after criticalCooldownMin` (cooldown reuse)

---

## Shared Patterns

### Cross-cutting: per-type state machine reuse via `driveAlertType`

**Source:** `src/agents/alerter/src/state.js` L68-152
**Apply to:** `sht30` and `scd41` alert routes (state.js dispatch sites)

The state machine is the spine of all alerting. Phase 26 adds zero new control flow — it adds two strings to `ALERT_TYPES` / `SEVERITY` and calls `driveAlertType` from the new event handler. PENDING→FIRING→RECOVERY, cooldown, snooze isolation, in-band recovery are all free.

```javascript
function driveAlertType(entry, alertType, oobNow, fields, now, config) {
  // ... PENDING → FIRING transition with oobN/oobWindowMin gating
  // ... cooldown gate via cooldownMs(alertType, config) (severity-mapped)
  // ... isSnoozed check before each send
  // ... in-band recovery emits {kind: 'recovery'} when oobNow flips false for oobN ticks
}
```

For sensor freshness, call site uses `sensorCfg = { ...config, oobN: 1, oobWindowMin: 0 }` (state.js L218 trick) — silence is binary, immediate-fire on first stale tick.

### Cross-cutting: gap-over-noise QoS discipline

**Source:** memory `feedback_gap_over_noise.md` + bridge slot-1 sub L607-630 (no `qos:` opt) vs humidifier sub L656-668 (TRANSIENT_LOCAL)
**Apply to:** all new bridge subscriptions for slot-2

Slot-2 telemetry subs use **default VOLATILE** QoS — no `{ qos: ... }` option. TRANSIENT_LOCAL is reserved for state topics (`actuators/humidifier`, `sensor_health`) that need replay on subscribe. Subscribing to slot-2 with TRANSIENT_LOCAL would surface a stale "last value" to late-joining clients during sensor outages — directly violates D-03 (RESEARCH Pitfall 2).

### Cross-cutting: Phase 16 `sensor_health` KeyValue contract

**Source:** `fc_controller.py` L256-261 + `bridge/src/index.js` L685-687 flattening
**Apply to:** any new fields added to `msg.values`

```javascript
// bridge flattening — permissive, keys appear as { warming_up, grace_elapsed_sec, ... }
const values = {};
(msg.values || []).forEach((kv) => { values[kv.key] = kv.value; });
```

Append-only changes are safe (Phase 26 adds `sht30_fresh` / `scd41_fresh`); rename or removal breaks Phase 15 grace countdown card and Phase 16 health-panel light. All values are stringified booleans (`'true'` / `'false'`) — preserve that shape (RESEARCH Pitfall 4).

### Cross-cutting: env-var config surface for new thresholds

**Source:** `src/agents/alerter/src/config.js` L36 (`piOfflineMin: parseIntEnv(env, 'ALERT_PI_OFFLINE_MIN', 5)`)
**Apply to:** new `sensorOfflineMin` env var

Mirror the existing pattern verbatim:
```javascript
sensorOfflineMin: parseIntEnv(env, 'ALERT_SENSOR_OFFLINE_MIN', 5),
```

D-04 default is 5 minutes (matches `ALERT_PI_OFFLINE_MIN`). Plan must update `docker-compose.yml` + `.env.sample` for the alerter container (RESEARCH §Runtime State Inventory L267).

---

## No Analog Found

None. Phase 26 is a pure extension of existing patterns — every new behavior has a near-identical predecessor in the codebase.

---

## Metadata

**Analog search scope:**
- `src/chambers/fc-core/fc_core/` (Pi nodes)
- `src/chambers/fc-core/fc_core/test/` (pytest)
- `src/agents/alerter/src/` (alerter)
- `src/agents/alerter/test/` (jest)
- `src/mission-control/bridge/src/index.js` (bridge sub patterns)

**Files read in full:**
- `src/chambers/fc-core/fc_core/fc_sensors.py` (143 L)
- `src/chambers/fc-core/fc_core/fc_controller.py` (355 L)
- `src/agents/alerter/src/state.js` (397 L)
- `src/agents/alerter/src/rules.js` (57 L)
- `src/agents/alerter/src/index.js` (164 L)
- `src/agents/alerter/src/message.js` (124 L)
- `src/agents/alerter/src/snooze.js` (45 L)
- `src/agents/alerter/src/config.js` (57 L)

**Files read targeted:**
- `src/mission-control/bridge/src/index.js` L575-705 (telemetry insertion + slot-1 + sensor_health)
- `src/chambers/fc-core/fc_core/test/test_controller.py` L1-80 (fixture pattern)
- `src/agents/alerter/test/state.test.js` L230-290 (warmup-does-not-suppress + snooze)

**Pattern extraction date:** 2026-04-25
