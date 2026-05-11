# Phase 29: Alerter mode awareness + cooldown tuning - Pattern Map

**Mapped:** 2026-05-08
**Files analyzed:** 9 modified + 2 new artifacts
**Analogs found:** 9 / 9 (every modification has a verbatim in-tree twin per RESEARCH.md "every Phase 29 mechanism has a working twin already in tree")

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/chambers/fc-core/fc_core/fc_controller.py` (modify) | controller / rclpy node | pub-sub + param-event | self (Phase 28 `_current_mode_pub` + `_validate_params`) | exact (extend existing) |
| `src/chambers/fc-core/config/fc_config.yaml` (modify) | config | n/a | self (Phase 28 `modes.{name}.*` block lines 76-90) | exact |
| `src/mission-control/bridge/src/index.js` (modify) | bridge / ROS-WS forwarder | pub-sub → broadcast | `sensor_health` subscription block (index.js:816-846) | exact |
| `src/agents/alerter/src/index.js` (modify) | service / event router | event-driven | self (existing `onMessage` switch lines 115-138) | exact (extend) |
| `src/agents/alerter/src/state.js` (modify) | state machine | event-driven FSM | self (existing `transition()` switch) | exact (extend) |
| `src/agents/alerter/src/rules.js` (modify) | utility / pure predicates | request-response | self (existing `isRhOob`, `isHumidifierStuck`) | exact (gate-wrap) |
| `src/agents/alerter/src/message.js` (modify) | utility / formatter | transform | self (existing `formatProblem` `pi` branch lines 60-64) | exact (extend) |
| `src/agents/alerter/src/config.js` (modify) | config | n/a | self (existing `load(env)` lines 23-58) | exact (narrow scope, do not relocate) |
| `src/agents/alerter/test/{rules,message,state,bridge-client}.test.js` (modify/add) | test | request-response | `test/rules.test.js` (existing per-rule jest cases) | exact |
| `.planning/phases/29-.../29-COOLDOWN-TUNING.md` (new artifact) | docs / one-shot analysis | n/a | n/a (D-07 deliverable; no precedent) | none |
| `ROADMAP.md` (modify) | docs | n/a | self (existing 999.x backlog entries) | exact |

---

## Pattern Assignments

### `fc_controller.py` — add 2 TRANSIENT_LOCAL publishers + extend validator

**Analog:** self — Phase 28's `_current_mode_pub` block + `_validate_params` chain

**QoS reuse** (`fc_controller.py:153-159`) — DO NOT redefine; reuse this exact `actuator_qos` for both new publishers:
```python
# Actuator QoS — TRANSIENT_LOCAL so late-joiners get last value (D-01, ACTR-03)
actuator_qos = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)
```

**Publisher pattern** (sibling of `fc_controller.py:186-188`):
```python
self._current_mode_pub = self.create_publisher(
    Mode, 'fc1/control/current_mode', actuator_qos
)
```
New for Phase 29 — message type is `std_msgs/msg/String` carrying JSON (RESEARCH §Anti-Patterns "JSON-in-String avoids a second fc_msgs build cycle"):
```python
self._alerter_overrides_pub = self.create_publisher(
    String, 'fc1/control/alerter_mode_overrides', actuator_qos
)
self._alerter_globals_pub = self.create_publisher(
    String, 'fc1/control/alerter_globals', actuator_qos
)
```

**Startup republish pattern** (`fc_controller.py:253-257`) — Pitfall 2 mitigation; MUST be added at the same site for both new topics:
```python
# Phase 28 Pitfall 2: TRANSIENT_LOCAL durability does NOT persist across
# process restart. Publish current_mode once at startup AFTER the param
# store is initialized so late subscribers ... see the active mode without polling.
self._publish_current_mode(source='config_default')
```

**Pending-republish drain pattern** (`fc_controller.py:196`) — extend with sibling flags:
```python
self._pending_current_mode_republish = None
# NEW Phase 29:
self._pending_alerter_overrides_republish = None
self._pending_alerter_globals_republish = None
```
Drained at top of `control_loop` (same site as Phase 28 — locate via grep `_pending_current_mode_republish` callers).

**Validator extension pattern** (`fc_controller.py:434-548`) — extend the elif chain after the existing `modes.*.target_humidity` branch (line 507). Reuses the exact "build post-batch view, range-check, set republish flag" idiom:
```python
# Existing reference shape (line 466-483) — DO NOT modify, just add new elifs:
if n.startswith('modes.') and n.endswith('.band_low'):
    prefix = n.rsplit('.', 1)[0]
    bh = get_post(f'{prefix}.band_high')
    if isnan(bh):
        if not (0.0 <= v <= 1.0):
            return SetParametersResult(successful=False,
                reason=f'{n}: must be in [0,1] (got {v})')
    elif not (0.0 <= v < bh <= 1.0):
        return SetParametersResult(successful=False,
            reason=f'{n}: must satisfy 0<=band_low<band_high<=1 ...')
    republish_current_mode = True
```
New Phase 29 elif arms (Tier B per-mode + Tier C globals — see RESEARCH §"Validator extension pattern"):
- `modes.{name}.alerter.cooldown_min` → range `[1,240]`, set `republish_alerter_overrides = True`
- `modes.{name}.alerter.critical_cooldown_min`, `humidifier_stuck_min`, `oob_n`, `oob_window_min`
- `pi_offline_min`, `sensor_offline_min` → `[1,60]`, set `republish_alerter_globals = True`
- `heartbeat_hour` → `[0,23]`
- `max_sends_per_hour` → `[1,200]`

**Republish-trigger tail** (`fc_controller.py:542-546`):
```python
if republish_current_mode:
    self._pending_current_mode_republish = ('param_set',)
```
Mirror with `_pending_alerter_overrides_republish` / `_pending_alerter_globals_republish`.

---

### `fc_config.yaml` — add `modes.{name}.alerter.*` block + global Tier C defaults

**Analog:** existing `modes.fruiting.*` / `modes.pinning.*` block (lines 76-90).

**Pattern** (`fc_config.yaml:76-90`):
```yaml
fc_controller:
  ros__parameters:
    active_mode: fruiting
    modes.fruiting.target_humidity: 0.96
    modes.fruiting.band_low: 0.945
    modes.fruiting.band_high: 0.975
    modes.fruiting.defend_side: both
    modes.fruiting.t_target: .nan
```
New keys for Phase 29 (Tier B nested under each mode; Tier C as siblings of `active_mode`):
```yaml
    # Tier B — per-mode alerter overrides (D-05 / D-08; values from 29-COOLDOWN-TUNING.md)
    modes.fruiting.alerter.cooldown_min: <tuned>
    modes.fruiting.alerter.critical_cooldown_min: <tuned>
    modes.fruiting.alerter.humidifier_stuck_min: <tuned>
    modes.fruiting.alerter.oob_n: <tuned>
    modes.fruiting.alerter.oob_window_min: <tuned>
    # ... and modes.pinning.alerter.* mirror block
    # Tier C — global liveness/cadence (runtime-mutable via SetParameters)
    pi_offline_min: 5
    sensor_offline_min: 5
    heartbeat_hour: 8
    max_sends_per_hour: 20
```

---

### `bridge/src/index.js` — 3 new ROS subscriptions + 3 cache slots + on-connect replay

**Analog:** `sensor_health` subscription + `lastSensorHealthBroadcast` block (`index.js:588-604`, `816-846`).

**QoS reuse** (`index.js:735-743`) — DO NOT redefine; bind to the existing `humidifierQos` constant (already TRANSIENT_LOCAL/RELIABLE/depth=1):
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
NOTE: the file already defines a second identical `sensorHealthQos` at line 817 — RESEARCH §Anti-Patterns flags this as drift; Phase 29 should bind to one constant (extract to module-scope `transientLocalQos` once OR just re-use `humidifierQos` for the new subs).

**Subscription + cache + broadcast pattern** (verbatim from `index.js:825-846`):
```javascript
node.createSubscription(
    'diagnostic_msgs/msg/DiagnosticStatus',
    '/fc1/sensor_health',
    { qos: sensorHealthQos },
    (msg) => {
        const values = {};
        (msg.values || []).forEach((kv) => { values[kv.key] = kv.value; });
        const payload = {
            sensor_health: { level: msg.level, name: msg.name, message: msg.message, values: values },
            timestamp: Date.now()
        };
        lastSensorHealthBroadcast = payload;
        broadcast(payload);
    }
);
console.log('[bridge] Sensor health subscription: TRANSIENT_LOCAL QoS (/fc1/sensor_health)');
```
New for Phase 29 — three siblings keyed by message type:
- `/fc1/control/current_mode` → `fc_msgs/msg/Mode` → `lastModeBroadcast` → broadcast `{current_mode: {...all 7 fields...}, timestamp}`
- `/fc1/control/alerter_mode_overrides` → `std_msgs/msg/String` (JSON) → `lastAlerterModeOverridesBroadcast` → broadcast `{alerter_overrides: JSON.parse(msg.data), timestamp}`
- `/fc1/control/alerter_globals` → `std_msgs/msg/String` → `lastAlerterGlobalsBroadcast` → broadcast `{alerter_globals: JSON.parse(msg.data), timestamp}`

**On-connect replay pattern** (verbatim from `index.js:592-604`):
```javascript
let lastSensorHealthBroadcast = null;  // (line 590) module scope

wss.on('connection', (ws) => {
    console.log('[bridge] Client connected');
    clients.add(ws);

    if (lastSensorHealthBroadcast && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(lastSensorHealthBroadcast));
    }
    // ...
});
```
Phase 29 extends with three more `if (lastXBroadcast && ws.readyState === WebSocket.OPEN) ws.send(...)` lines inside the same `wss.on('connection')` block. Module-scope let declarations beside line 590.

**Broadcast helper** (`index.js:607-614`) — already exists; new code calls `broadcast(payload)` unchanged:
```javascript
function broadcast(data) {
    const payload = JSON.stringify(data);
    clients.forEach((client) => {
        if (client.readyState === WebSocket.OPEN) {
            client.send(payload);
        }
    });
}
```

---

### `alerter/src/index.js` — extend `onMessage` switch with 3 new branches

**Analog:** self (`index.js:115-138`).

**Existing pattern** (verbatim):
```javascript
const bridge = createBridgeClient({
    wsUrl: config.bridgeWsUrl,
    healthUrl: config.bridgeHealthUrl,
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
        applyEvent({ type: 'sensor_health', level: msg.sensor_health.level, ... });
      } else if (msg.temperature_2 !== undefined || msg.humidity_2 !== undefined) {
        applyEvent({ type: 'sensor_freshness', sensor: 'scd41', lastSeenMs: clock() });
      }
    },
    ...
});
```
New Phase 29 branches (append to the if/else chain):
```javascript
else if (msg.current_mode) {
  applyEvent({ type: 'mode_update', mode: msg.current_mode });
} else if (msg.alerter_overrides) {
  applyEvent({ type: 'overrides_update', overrides: msg.alerter_overrides });
} else if (msg.alerter_globals) {
  applyEvent({ type: 'globals_update', globals: msg.alerter_globals });
}
```

---

### `alerter/src/state.js` — 3 new event types + dedup-reset on mode swap

**Analog:** existing `transition()` switch in same file (`state.js:169-200+`).

**Existing pattern** (verbatim from `state.js:173-199`):
```javascript
switch (event.type) {
    case 'humidity': {
      next.currentRh = event.value;
      next.lastRhMsgTs = now;
      if (!next.warmingUp) {
        const oobNow = isRhOob(event.value, config);
        const r = driveAlertType(next.perType.rh, 'rh', oobNow, rhFields, now, config);
        next.perType.rh = r.next;
        actions.push(...r.actions);
        // ...
      }
      break;
    }
```

**New for Phase 29** — three new cases. Critical D-09 pattern:
```javascript
case 'mode_update': {
  next.currentMode = event.mode;
  next.modeReceivedAtMs = now;
  // D-09: RESET in-progress dedup but PRESERVE lastFiredAt (cooldown carries
  // across mode swaps to dampen spam during fruiting->pinning transition).
  for (const t of ['rh', 'humidifier']) {
    next.perType[t].oobCount = 0;
    next.perType[t].firstOobAt = null;
    next.perType[t].ctx.inBandCount = 0;
    // lastFiredAt INTENTIONALLY NOT reset
  }
  break;
}
case 'overrides_update': {
  next.alerterOverrides = event.overrides;
  next.overridesReceivedAtMs = now;
  break;
}
case 'globals_update': {
  next.alerterGlobals = event.globals;
  next.globalsReceivedAtMs = now;
  break;
}
```

**State seed extension** — `initialState()` at `state.js:32-55` adds:
```javascript
currentMode: null,
modeReceivedAtMs: null,
alerterOverrides: null,
overridesReceivedAtMs: null,
alerterGlobals: null,
globalsReceivedAtMs: null,
```

**Effective-config builder** (NEW helper, called inside `transition` before `isRhOob` / `isHumidifierStuck`):
- If `state.modeReceivedAtMs` is null AND boot-grace (≤60s since `bootedAtMs`) → use env `config` (D-03 state 3).
- Else if `state.modeReceivedAtMs` is null OR `(now - modeReceivedAtMs) > mode_stale_min*60000` OR `!wsConnected` → freshness=`stale` (D-03 state 2).
- Else → freshness=`fresh`, override `rhTarget`, `rhBand` (or `band_low`/`band_high`) from `currentMode`; merge `alerterOverrides` over `cooldownMin`/`oobN`/etc; merge `alerterGlobals` over `piOfflineMin`/`sensorOfflineMin`.

---

### `alerter/src/rules.js` — gate `isRhOob` + `isHumidifierStuck` on freshness state

**Analog:** self (`rules.js:7-9` and `rules.js:47-54`).

**Existing pattern** (verbatim):
```javascript
function isRhOob(humidity, config) {
  return Math.abs(humidity - config.rhTarget) > config.rhBand;
}

function isHumidifierStuck({ humidifierOnSinceMs, rhAtOn, currentRh, nowMs, config }) {
  if (humidifierOnSinceMs == null) return false;
  const onDurationMs = nowMs - humidifierOnSinceMs;
  const thresholdMs = config.humidifierStuckMin * 60000;
  if (onDurationMs <= thresholdMs) return false;
  const rhRise = currentRh - rhAtOn;
  return rhRise < 3.0;
}
```

**Phase 29 gate-wrap pattern** (RESEARCH §Pattern 4 — DO NOT refactor the rule body, only prepend a freshness short-circuit). The signature gains an `effective` shape with a `freshness` sub-object:
```javascript
function isRhOob(humidity, effective) {
  // effective = { rhTarget, rhBand, freshness: { state: 'fresh'|'stale'|'cold', source: 'mode'|'env' } }
  if (effective.freshness.state === 'stale') return false;  // D-03 state 2
  return Math.abs(humidity - effective.rhTarget) > effective.rhBand;
}

function isHumidifierStuck({ humidifierOnSinceMs, rhAtOn, currentRh, nowMs, config, wsConnected, humidifierLastMsgTs }) {
  // D-04: suspend when offline-blind
  if (!wsConnected) return false;
  if (humidifierLastMsgTs == null) return false;
  if ((nowMs - humidifierLastMsgTs) > config.sensorOfflineMin * 60000) return false;
  // ...existing math unchanged...
}
```

**Backward-compat:** existing `rules.test.js` shape `{ rhTarget: 90, rhBand: 3 }` (test line 8) must keep passing — provide a default `freshness: { state: 'fresh' }` when absent OR update the small set of test fixtures. RESEARCH explicitly: "Tests that assert 'RH 83 with target 90 ± 3 is OOB' continue to pass when the rule is given a fresh effective config. Only NEW tests assert the gating behavior."

---

### `alerter/src/message.js` — extend `formatProblem` for `alertType==='pi'` with last-known summary

**Analog:** self (`message.js:60-64`).

**Existing pattern** (verbatim):
```javascript
} else if (alertType === 'pi') {
    const { lastSeenMs } = fields;
    if (lastSeenMs != null) {
      body += `Last seen: ${fmtRelative(lastSeenMs, nowMs)}\n`;
    }
}
```

**Phase 29 extension** — append last-known sensor + actuator summary (D-04 / 999.39):
```javascript
} else if (alertType === 'pi') {
    const { lastSeenMs, lastKnown } = fields;
    if (lastSeenMs != null) {
      body += `Last seen: ${fmtRelative(lastSeenMs, nowMs)}\n`;
    }
    if (lastKnown) {
      body += `Last sample: RH ${lastKnown.rh}% · T ${lastKnown.temp}°C · humidifier ${lastKnown.humidifier}\n`;
      body += `(captured ${fmtRelative(lastKnown.tsMs, nowMs)})\n`;
    }
}
```
Caller (`state.js`) builds `lastKnown` from `state.currentRh`, `state.currentTemp`, `humidifierOnSinceMs ? 'ON' : 'OFF'`, `state.lastRhMsgTs`. Reuse the `fmtRelative` helper at `message.js:31-37` — already in module.

---

### `alerter/src/config.js` — narrow scope to Tier D; keep Tier A/B/C as bootstrap fallback

**Analog:** self (`config.js:23-58`).

**Existing pattern** (verbatim of the relevant lines):
```javascript
function load(env = process.env) {
  return Object.freeze({
    rhTarget:            parseFloatEnv(env, 'ALERT_RH_TARGET', 90),
    rhBand:              parseFloatEnv(env, 'ALERT_RH_BAND', 3),
    oobN:                parseIntEnv(env, 'ALERT_OOB_N', 5),
    oobWindowMin:        parseIntEnv(env, 'ALERT_OOB_WINDOW_MIN', 3),
    cooldownMin:         parseIntEnv(env, 'ALERT_COOLDOWN_MIN', 30),
    criticalCooldownMin: parseIntEnv(env, 'ALERT_CRITICAL_COOLDOWN_MIN', 60),
    piOfflineMin:        parseIntEnv(env, 'ALERT_PI_OFFLINE_MIN', 5),
    sensorOfflineMin:    parseIntEnv(env, 'ALERT_SENSOR_OFFLINE_MIN', 5),
    humidifierStuckMin:  parseIntEnv(env, 'ALERT_HUMIDIFIER_STUCK_MIN', 30),
    heartbeatHour:       parseIntEnv(env, 'ALERT_HEARTBEAT_HOUR', 8),
    // ...
  });
}
```

**Phase 29 change** — DO NOT remove fields. Per CONTEXT.md "Backwards-compat path: `.env` keeps old `ALERT_*` vars as bootstrap fallback values (D-03 state 3) and Tier C deploy-time defaults". Add a new derived field:
```javascript
modeStaleMin: parseIntEnv(env, 'ALERT_MODE_STALE_MIN', 5),     // D-03 state 2 threshold
modeBootGraceMs: parseIntEnv(env, 'ALERT_MODE_BOOT_GRACE_SEC', 60) * 1000,  // D-03 state 3 grace
```
Document in source comment which fields are now bootstrap-only (Tier A/B/C bootstrap fallback) vs. live (Tier D operational).

---

### Tests — `rules.test.js`, `message.test.js`, `state.test.js`, `bridge-client.test.js`

**Analog:** existing jest cases per file (e.g. `rules.test.js:7-25`).

**Existing pattern** (verbatim):
```javascript
describe('isRhOob', () => {
  const cfg = { rhTarget: 90, rhBand: 3 };

  test('exactly on target: false', () => {
    expect(isRhOob(90, cfg)).toBe(false);
  });
  test('83.2 is OOB (|90-83.2|=6.8 > 3): true', () => {
    expect(isRhOob(83.2, cfg)).toBe(true);
  });
});
```

**Phase 29 additions** — new describe blocks, do not edit existing:
- `rules.test.js`: freshness-gated `isRhOob` (returns false when `effective.freshness.state==='stale'`); `isHumidifierStuck` returns false when `wsConnected===false` or `humidifierLastMsgTs` stale.
- `state.test.js`: `mode_update` event resets `oobCount`/`firstOobAt` for `rh` and `humidifier` perType but PRESERVES `lastFiredAt` (D-09 invariant).
- `state.test.js`: cold-start grace — first 60s after boot uses env defaults, then transitions to `stale` until first `mode_update`.
- `state.test.js`: `overrides_update` and `globals_update` merge into effective config (Tier B over env defaults; Tier C over env defaults).
- `message.test.js`: `formatProblem(alertType='pi')` includes "Last sample:" line when `fields.lastKnown` provided; omits when null.
- `bridge-client.test.js`: parses `current_mode` / `alerter_overrides` / `alerter_globals` envelope shapes through `onMessage` callback (use existing fixture pattern at `test/fixtures/bridge-messages.js`).

---

## Shared Patterns

### Pattern A: TRANSIENT_LOCAL pub/sub for late-joiner state
**Source:** `fc_controller.py:153-159` (`actuator_qos`) + `bridge/index.js:735-743` (`humidifierQos`)
**Apply to:** All 3 new topics in this phase — `current_mode`, `alerter_mode_overrides`, `alerter_globals`.
**Invariant:** publisher-side TRANSIENT_LOCAL/RELIABLE/depth=1 MUST be matched by subscriber-side identical QoS or DDS rejects matching silently. Phase 28 already proved this end-to-end.

### Pattern B: Startup republish to defeat per-process durability cache
**Source:** `fc_controller.py:253-257` (Pitfall 2 mitigation)
**Apply to:** Both new controller publishers — emit once at end of `__init__` after param store is initialized.
**Why:** TRANSIENT_LOCAL durability is per-process; controller restart leaves the durable cache empty until first publish.

### Pattern C: Validator-driven next-tick republish
**Source:** `fc_controller.py:434-548` + the `_pending_current_mode_republish` drain
**Apply to:** Tier B/C param edits — set `_pending_alerter_overrides_republish` / `_pending_alerter_globals_republish` flag, drain at top of `control_loop`.
**Why:** rclpy applies new param values AFTER the validator returns `successful=True`; in-callback publish would emit pre-applied state.

### Pattern D: Atomic batch-validation on `add_on_set_parameters_callback`
**Source:** `fc_controller.py:434-548` (`_validate_params`)
**Apply to:** Every new dotted key. Build `post = {p.name: p.value for p in params}` for cross-param invariants; range-check against bounds; first violation aborts whole batch.

### Pattern E: WS broadcast helper + on-connect replay
**Source:** `bridge/index.js:588-604, 607-614, 825-846`
**Apply to:** All 3 new bridge subscriptions. Module-scope `let lastXBroadcast = null;` next to existing `lastSensorHealthBroadcast`; on-connect block sends cached payload if non-null.

### Pattern F: Alerter event-routing in `onMessage`
**Source:** `alerter/src/index.js:115-138`
**Apply to:** Three new WS payload keys (`current_mode`, `alerter_overrides`, `alerter_globals`) → three new `applyEvent` dispatches.

### Pattern G: Pure-rule short-circuit gate
**Source:** `alerter/src/rules.js:7-9, 47-54`
**Apply to:** `isRhOob` (freshness state gate) + `isHumidifierStuck` (offline-blindness gate, D-04). Prepend gate; do NOT refactor the existing math body.

### Pattern H: WS-only alerter contract preservation
**Source:** Memory `project_alerter_is_ws_only` + `alerter/src/index.js` (no Timescale reads anywhere)
**Apply to:** Tier B/C delivery — must flow over WS via D-06 topics; NO new HTTP endpoints, NO Timescale queries from alerter.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `.planning/phases/29-.../29-COOLDOWN-TUNING.md` | docs / one-shot offline analysis | n/a | First-of-kind deliverable per D-07. No precedent in `.planning/phases/*`. Format: per-rule fires/dedup/ack/inter-fire/P95 stats from `docker logs mushy-alerter` parse + proposed defaults + rationale. RESEARCH §"Tuning Data Access" specifies the recipe — planner uses RESEARCH.md directly, not a code analog. |

`alert_history` Timescale table does NOT exist (RESEARCH verified `find -name '*.sql'` returns nothing); the docker-logs path is the only path.

---

## Metadata

**Analog search scope:** `src/agents/alerter/`, `src/mission-control/bridge/src/`, `src/chambers/fc-core/`, `.planning/phases/28-*/`
**Files scanned:** 8 source files read line-anchored (fc_controller.py, bridge/index.js, alerter src/{index,state,rules,message,bridge-client,config}.js), 1 config (fc_config.yaml), 1 test (rules.test.js)
**Pattern extraction date:** 2026-05-08
