# Phase 26: Dual sensor publishing + offline alarms — Research

**Researched:** 2026-04-25
**Domain:** ROS2 publisher refactor + Node.js alerter rule extension
**Confidence:** HIGH (all claims grounded in repo source — no external lookups needed)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Slot 1 keeps the existing silent-fallback behavior — when SHT30 is unavailable, SCD41 values publish on `fc1/temperature` / `fc1/humidity` with no flag or gap. Controller continues to consume slot 1 unchanged.
- **D-02:** Slot 2 (`fc1/temperature_2`, `fc1/humidity_2`) publishes SCD41 readings unconditionally and independently of slot 1 — never gated on SHT30 state.
- **D-03:** Only publish a slot when the underlying physical sensor has a fresh reading (don't fabricate, don't repeat stale values). Gaps on slot 2 are acceptable and expected.
- **D-04:** Offline threshold: **5 minutes** of no fresh readings from a given physical sensor triggers a Signal alert.
- **D-05:** Per-sensor granularity — SHT30 offline and SCD41 offline are distinct alerts.
- **D-06:** Recovery message fires when a sensor resumes publishing after an offline alert (symmetric with existing alerter behavior).

### Claude's Discretion

- Exact mechanism for offline detection (extend Pi-side `sensor_health` from Phase 16 to report per-sensor freshness, or alerter-side topic-silence watchdog, or both) — planner decides based on smallest diff to live code.
- Cooldown / dedup policy — reuse whatever the existing alerter (`src/agents/alerter`) already does for `pi_liveness` and `sensor_health` alerts; don't invent a parallel mechanism.
- Downstream consumer updates (Mission Control panels, farmer dashboard, FarmOS writer) — only update surfaces where slot 2 adds clear operator value; don't blanket-wire every consumer.

### Deferred Ideas (OUT OF SCOPE)

- Per-slot `sensor_source` telemetry flag so consumers can tell which physical sensor backed a slot 1 reading.
- Cross-sensor drift detection (flag when slot 1 and slot 2 diverge > X%).
- RH bias correction on SCD41 readings.
</user_constraints>

## Project Constraints (from CLAUDE.md)

- ROS2 Jazzy workspace, build with `colcon build --packages-select fc_core --symlink-install` for Python iteration.
- `simulation_mode` is split: `sensor_simulation_mode` and `actuator_simulation_mode` are independent params in `fc_config.yaml`. Phase 26 only touches the sensor side.
- Pi deploy is git via `fc1/prod` branch (per memory `feedback_deploy_method.md`); runtime fc1 is `fc1-ts` (100.96.239.75) per memory `feedback_ssh_tailscale.md`.
- Alerter container is `mushy-alerter` and rebuilds on elder-plops via `docker compose up -d --build alerter`.
- Naming: external-facing UI calls this "Mission Control" (memory `feedback_naming.md`).
- Gap-over-noise: prefer no-publish over stale republish (memory `feedback_gap_over_noise.md`) — already aligned with D-03.

## Summary

Phase 26 has two chunks: (1) a tiny refactor to `fc_sensors.py` that adds two more publishers and per-sensor freshness gating, and (2) a feature add to the alerter that detects per-physical-sensor silence and emits per-sensor problem/recovery messages reusing the existing OOB→PENDING→FIRING→RECOVERY state machine.

The sensor-side change is ~30 lines in one file. The alerter change is bigger because today's alerter has only **four** alert types (`rh`, `sensor`, `pi`, `humidifier`) and the existing `sensor` type is a *single-sensor binary* (driven by `sensor_health.level === 2`), not a multi-sensor freshness tracker. Per-sensor (SHT30 vs SCD41) granularity requires extending `ALERT_TYPES` and routing — discussed in detail below.

The research below recommends **Option C (hybrid: Pi-side freshness in `sensor_health.values` + alerter-side topic-silence watchdog as belt-and-braces)**. Pi-side gives the bridge/dashboard the "live status" the farmer wanted post-2026-04-11; alerter-side gives a real watchdog that survives `fc_controller` itself crashing.

**Primary recommendation:** Add SHT30/SCD41 freshness fields into `sensor_health.values` (one-line per sensor in `fc_controller._publish_sensor_health`), have `fc_sensors.py` publish slot 2 + the freshness signal it already implicitly tracks, and add `sht30` + `scd41` alert types to the alerter that watch WS message arrival timestamps for `temperature_2`/`humidity_2` (SCD41) and slot 1 vs `sensor_health.values.sht30_fresh` (SHT30).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Reading SHT30/SCD41 hardware | Pi / fc_sensors node | — | Already owns I2C handles; only place GPIO + adafruit libs run |
| Slot-1 fallback semantics | Pi / fc_sensors node | — | Locked unchanged by D-01; controller stays naive |
| Slot-2 unconditional publish | Pi / fc_sensors node | — | Producer must know which physical sensor backed each value |
| Per-sensor freshness signal | Pi / fc_controller (`sensor_health`) | Alerter (independent watchdog) | Pi has authoritative truth; alerter belt-and-braces if Pi crashes |
| Offline alert state machine | Alerter container | — | All other alert types live there; reusing `driveAlertType` |
| Signal delivery | Alerter / `signal.js` | — | Centralized client, hourly cap, snooze support already done |
| Bridge → WS forwarding (slot 2) | Mission Control bridge | — | Subscribes to ROS, broadcasts to WS clients |
| TimescaleDB ingestion (slot 2) | Mission Control bridge | — | Same `insertTelemetry` path; new topic IDs `fc.temperature_2` / `fc.humidity_2` |
| OpenMCT panel display | Mission Control frontend plugin | — | Add SENSORS entry; no new primitive |
| Daily report (`farmos-agent`) | farmos-agent | — | Out of scope for Phase 26; slot 1 still answers the daily report |

## Standard Stack

### Core (already present — nothing to install)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `rclpy` | ROS2 Jazzy | Pi-side node + publishers | Existing fc_core dep [VERIFIED: setup.py L23] |
| `adafruit-circuitpython-sht31d` | (installed) | SHT30 driver | Already used in `fc_sensors.py` L34 [VERIFIED: src grep] |
| `adafruit-circuitpython-scd4x` | (installed) | SCD41 driver | Already used in `fc_sensors.py` L43 [VERIFIED: src grep] |
| `diagnostic_msgs/DiagnosticStatus` | ROS2 std | `sensor_health` topic | Phase 16 contract [VERIFIED: fc_controller.py L104, bridge index.js L681] |
| `ws` | ^8.16.0 | Alerter WS client | `package.json` L12 [VERIFIED: src/agents/alerter/package.json] |
| `jest` | ^29.7.0 | Alerter test framework | `package.json` L16 [VERIFIED: same] |
| `pytest` | ament_python | fc_core test framework | `setup.py` L33 [VERIFIED: setup.py] |

**Nothing new to install.** Phase 26 is pure code changes against existing libraries.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Extending `sensor_health.values` | New per-sensor topic `fc1/sensor_freshness` | Splits the contract Phase 16 carefully unified into one DiagnosticStatus; bridge would need a second subscription. Rejected. |
| Adding `sht30`/`scd41` alert types | One generic `sensor_offline` type with `which: 'sht30'` ctx | Existing snooze command (`snooze sensor 4h`) already maps to *one* `sensor` type; doing per-sensor needs distinct types or a snooze-grammar break. Distinct types is the smaller diff. |

## Architecture Patterns

### System Architecture Diagram

```
                    ┌────────────────────────────────────────────────────┐
                    │  Pi (fc1) — fc_core ROS2 nodes                     │
                    │                                                     │
   ┌──────┐  I2C    │  ┌─────────────┐                                   │
   │ SHT30├────────►│  │ fc_sensors  │── fc1/temperature ───────────────┐│
   └──────┘         │  │   (timer    │   fc1/humidity                   ││
                    │  │   2 Hz)     │── fc1/co2                        ││
   ┌──────┐  I2C    │  │             │── fc1/temperature_2  [NEW]       ││
   │ SCD41├────────►│  │             │── fc1/humidity_2     [NEW]       ││
   └──────┘         │  └─────────────┘                                   ││
                    │         │                                          ││
                    │  ┌──────▼────────┐                                 ││
                    │  │ fc_controller │── fc1/actuators/humidifier     ││
                    │  │  (subscribes  │── fc1/sensor_health             ││
                    │  │   to slot 1)  │   (KeyValue: + sht30_fresh,    ││
                    │  │               │             + scd41_fresh)[NEW]││
                    │  └───────────────┘                                 ││
                    └─────────────────────────────────────────────────────┘
                                                                          │
                                                              ROS2 DDS (Tailscale CycloneDDS)
                                                                          │
                                                                          ▼
                    ┌────────────────────────────────────────────────────┐
                    │  elder-plops — Mission Control stack               │
                    │                                                     │
                    │  ┌─────────────┐                                    │
                    │  │   bridge    │── /health  (HTTP)                  │
                    │  │ rclnodejs   │── WS broadcast { temperature,      │
                    │  │             │     humidity, co2, humidifier,     │
                    │  │             │     sensor_health,                 │
                    │  │             │     temperature_2, humidity_2 }    │  [NEW]
                    │  │             │── INSERT INTO telemetry            │
                    │  │             │     (fc.temperature_2 /            │
                    │  │             │      fc.humidity_2)            [NEW]
                    │  └──────┬──────┘                                    │
                    │         │                                           │
                    │   ┌─────┴──────┬────────────┐                       │
                    │   ▼            ▼            ▼                       │
                    │ ┌────────┐ ┌─────────┐ ┌──────────┐                 │
                    │ │openmct │ │ alerter │ │timescale │                 │
                    │ │plugin  │ │container│ │   DB     │                 │
                    │ │ +slot2 │ │ +sht30  │ └──────────┘                 │
                    │ │  card? │ │ +scd41  │                              │
                    │ └────────┘ │ alerts  │                              │
                    │            │  ▼      │                              │
                    │            │ Signal  │                              │
                    │            │ via     │                              │
                    │            │ signal- │                              │
                    │            │ cli REST│                              │
                    │            └─────────┘                              │
                    └────────────────────────────────────────────────────┘
```

### Component Responsibilities

| File | Current Responsibility | Phase 26 Delta |
|------|------------------------|----------------|
| `src/chambers/fc-core/fc_core/fc_sensors.py` | Single-slot publisher (T/RH/CO2) | Add `temp_2_pub`, `humidity_2_pub`; track per-sensor `last_read_ts`; gate publishes on freshness |
| `src/chambers/fc-core/fc_core/fc_controller.py` | Publishes `sensor_health` on warm-up state change | Add `sht30_fresh` / `scd41_fresh` KeyValue fields driven by per-sensor staleness check (subscribe to slot 2, mirror existing slot-1 staleness pattern) |
| `src/chambers/fc-core/config/fc_config.yaml` | Sensor params | Optional: add `sensor_offline_min: 5` only if alerter doesn't already own this; recommend keeping it alerter-side via `ALERT_SENSOR_OFFLINE_MIN` env var to match the `ALERT_PI_OFFLINE_MIN=5` pattern |
| `src/mission-control/bridge/src/index.js` | Subscribes to slot 1, broadcasts + inserts | Add 2 subscriptions for `fc1/temperature_2` / `fc1/humidity_2`; broadcast as `{ temperature_2, humidity_2 }`; insert as `fc.temperature_2` / `fc.humidity_2` |
| `src/agents/alerter/src/state.js` | 4 alert types | Add `sht30` and `scd41` to `ALERT_TYPES` and `SEVERITY` (CRITICAL); add per-sensor `lastSeenMs` tracking on dispatch route |
| `src/agents/alerter/src/index.js` | Routes WS msgs to events | Add routes for `temperature_2` / `humidity_2` (SCD41 freshness) + parse `sensor_health.values.sht30_fresh` (SHT30 freshness) |
| `src/agents/alerter/src/rules.js` | Has `isPiOffline` | Add `isSensorSilent({ lastSeenMs, nowMs, config })` mirroring `isPiOffline` pattern |
| `src/agents/alerter/src/message.js` | `ALERT_TITLES` for 4 types | Add `sht30: 'SHT30 offline'`, `scd41: 'SCD41 offline'` |
| `src/agents/alerter/src/snooze.js` | Whitelist `rh\|sensor\|pi\|humidifier\|all` | Extend regex to include `sht30\|scd41` |
| `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` | 4 SENSORS entries | Optionally add `fc.temperature_2` and `fc.humidity_2` (deferred unless farmer wants overlay now — Phase 999.17 scopes this explicitly) |

### Pattern 1: Per-sensor freshness via reading-timestamp gate (Pi side)

**What:** Track `self._sht30_last_read_ms` and `self._scd41_last_read_ms` in `fc_sensors.py`, set them only on a successful read, and gate slot publishing on age.

**Example:**
```python
# Source: pattern derived from fc_sensors.py L67-95
def read_sensors(self):
    sht30_t, sht30_rh = None, None
    scd41_t, scd41_rh, scd41_co2 = None, None, None
    now = self.get_clock().now()

    if self.sht is not None:
        try:
            sht30_t = self.sht.temperature
            sht30_rh = self.sht.relative_humidity
            self._sht30_last_read_ns = now.nanoseconds
        except Exception as e:
            self.get_logger().warn(f'SHT30 read failed: {e}')  # leave _sht30_last_read_ns alone

    if self.scd is not None and self.scd.data_ready:
        try:
            scd41_t = self.scd.temperature
            scd41_rh = self.scd.relative_humidity
            scd41_co2 = self.scd.CO2
            self._scd41_last_read_ns = now.nanoseconds
        except Exception as e:
            self.get_logger().warn(f'SCD41 read failed: {e}')

    # Slot 1 — silent fallback (D-01 preserved exactly)
    slot1_t  = sht30_t  if sht30_t  is not None else scd41_t
    slot1_rh = sht30_rh if sht30_rh is not None else scd41_rh
    if slot1_t  is not None: publish(self.temp_pub, slot1_t)
    if slot1_rh is not None: publish(self.humidity_pub, slot1_rh)

    # Slot 2 — SCD41-only, gap when stale (D-02, D-03)
    if scd41_t  is not None: publish(self.temp_2_pub, scd41_t)
    if scd41_rh is not None: publish(self.humidity_2_pub, scd41_rh)

    # CO2 unchanged — protects v1.0 surprise-win publishing on fc1/co2
    if scd41_co2 is not None: publish(self.co2_pub, scd41_co2)
```

Critical: the `try/except` per-sensor matters. Today's code has *one* outer try/except at L67 — if SHT30 raises, the whole tick (including SCD41 read) is skipped. That's a pre-existing latent bug worth fixing as a side effect of this phase since the new freshness contract makes it visible.

### Pattern 2: Reuse `driveAlertType` for new sensor types (alerter side)

**What:** `state.js` L68 `driveAlertType(entry, alertType, oobNow, fields, now, config)` is the per-type state machine. It already handles cooldown, snooze, recovery — all you do is add new types and call it.

**Example:**
```javascript
// Source: pattern derived from state.js L268-307 (pi_liveness reuse)
case 'sensor_freshness': {
    const { sensor, lastSeenMs } = event;  // sensor: 'sht30' | 'scd41'
    next[`${sensor}LastSeenMs`] = lastSeenMs ?? now;

    // Skip during 60s startup grace (mirrors pi_liveness L291)
    if (now - next.bootedAtMs < 60000) break;

    const silent = isSensorSilent({
        lastSeenMs: next[`${sensor}LastSeenMs`],
        nowMs: now,
        config,  // config.sensorOfflineMin = 5 (env ALERT_SENSOR_OFFLINE_MIN)
    });
    const fields = { sensor, lastSeenMs: next[`${sensor}LastSeenMs`] };
    // sensor offline fires on first silent tick (oobN=1 like sensor ERROR — see state.js L218)
    const sensorCfg = { ...config, oobN: 1, oobWindowMin: 0 };
    const r = driveAlertType(next.perType[sensor], sensor, silent, fields, now, sensorCfg);
    next.perType[sensor] = r.next;
    actions.push(...r.actions);
    break;
}
```

The state machine emits `recovery` actions automatically when `oobNow` flips false (L132-148), so D-06 falls out for free. The `tick` event (state.js L309, fired every 30s by `index.js` L121) keeps re-evaluating during silence — this is critical because if no sensor messages arrive, no other event fires, so without a periodic tick the FIRING transition would never happen.

### Anti-Patterns to Avoid

- **Republishing stale slot 2 values during gap** — violates D-03; explicit anti-pattern in CONTEXT specifics line 70 ("skip publish when value unavailable").
- **Coupling SHT30 alert to slot 1 silence** — slot 1 silently falls back to SCD41 (D-01), so slot 1 going silent means *both* sensors are dead, not SHT30. SHT30-specific freshness must come from `sensor_health.values.sht30_fresh` or an alerter-side fact known independent of slot 1.
- **Using a single generic "sensor offline" alert type** — would force a snooze-grammar break or lose D-05 per-sensor granularity.
- **Adding a second `sensor_health` publisher in `fc_sensors.py`** — Phase 16 contract has `fc_controller` owning the topic (TRANSIENT_LOCAL on a well-known producer). Two publishers on one TRANSIENT_LOCAL topic creates QoS confusion; instead, route freshness from `fc_sensors` to `fc_controller` via the existing slot 2 subscription that `fc_controller` will need anyway (mirror of slot 1 subscription L86-90).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Topic-silence detection | New WS-listener service | Existing `tickTimer` (index.js L121) re-runs `isPiOffline`; mirror with `isSensorSilent` | 30s tick already exists; one new function, no plumbing |
| Per-sensor cooldown / dedup | New cooldown logic | `driveAlertType` (state.js L68) — already has PENDING→FIRING→RECOVERY + cooldown | Pre-tested; `criticalCooldownMin=60` env-controlled |
| Recovery message formatting | New formatter | `formatRecovery` (message.js L90) | Already uses `ALERT_TITLES[alertType]` lookup; just add titles for `sht30` / `scd41` |
| Snooze grammar | New parser | Extend regex at snooze.js L15 | One regex change + add to `VALID_ALERT_TYPES` L3 |
| Hourly send-rate cap | New rate limiter | `signal.js maxSendsPerHour` (config.js L40) | Already covers all alert types — `bypassCap` only used for heartbeats |
| Bridge WS subscription pattern | New broadcast path | Copy slot-1 block (bridge/src/index.js L606-630) | Identical msg type, identical `broadcast()` + `insertTelemetry()` calls |

**Key insight:** Every primitive Phase 26 needs already exists. The work is wiring + adding two strings to lists, plus the small Pi-side refactor. Resist the urge to invent a "freshness service" — the existing alerter state machine + tick loop is the freshness service.

## Runtime State Inventory

> Phase 26 is a feature add (new topics + new alert types), not a rename or migration. No existing runtime state needs renaming. The only stateful item the planner should be aware of:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | TimescaleDB `telemetry` table accepts arbitrary `topic` strings (bridge/src/index.js L584-587) — `fc.temperature_2` / `fc.humidity_2` will simply start appearing as new topic IDs once the bridge inserts them. No schema change. | None — verified by reading the INSERT pattern at L584. |
| Live service config | n8n / external dashboards: out of scope per memory `feedback_verify_runtime_compose.md` — none reference these topics today. | None. |
| OS-registered state | None. | None — verified by inspection (no systemd unit names / pm2 process names embed sensor topic strings). |
| Secrets/env vars | New env var on alerter container: `ALERT_SENSOR_OFFLINE_MIN=5`. Existing `ALERT_PI_OFFLINE_MIN=5` is the pattern. | Plan must update `docker-compose.yml` + `.env.sample` for alerter. |
| Build artifacts | `colcon build --packages-select fc_core --symlink-install` rebuilds Python entrypoints (setup.py L37). Symlink-install means edits to fc_sensors.py are picked up on node restart, no rebuild needed if symlinks are already in place. | Standard fc_core deploy via `fc1/prod` branch. |

## Common Pitfalls

### Pitfall 1: Single try/except wrapping both sensor reads
**What goes wrong:** `fc_sensors.py` L68 has one outer try/except for the whole tick. If SHT30 throws an I2C exception, SCD41 is never read that tick — both sensors look offline.
**Why it happens:** Original code assumed at most one sensor exists at a time; current dual-sensor code inherited the wrapper.
**How to avoid:** Per-sensor try/except in the refactor (see Pattern 1). Verify in test by injecting a fake `sht.temperature` raiser and asserting SCD41 still publishes.
**Warning signs:** A real-world SHT30 outage triggering both `sht30` and `scd41` alerts simultaneously — would have happened in the 2026-04-11 incident under this code.

### Pitfall 2: TRANSIENT_LOCAL durability on QoS-mismatched subscribers
**What goes wrong:** `sensor_health` is published with `DurabilityPolicy.TRANSIENT_LOCAL` (fc_controller.py L94-98). If the alerter watches slot 2 directly via the bridge WS, *the bridge's slot 2 subscription must NOT use TRANSIENT_LOCAL* — slot 2 publishes are gappy by design (D-03), and a TRANSIENT_LOCAL subscriber would report a stale "last value" to late-joining clients, defeating the gap-over-noise principle.
**Why it happens:** Bridge code copy-paste from `humidifier` / `sensor_health` blocks (which DO use TRANSIENT_LOCAL — bridge/src/index.js L645-679).
**How to avoid:** Slot 2 subscriptions in bridge use **default QoS (VOLATILE, KEEP_LAST 10)**, matching slot 1 (L607-617). Verify by reading the existing slot-1 block — it does NOT pass `{ qos: ... }`.
**Warning signs:** OpenMCT shows a phantom slot-2 reading on bridge restart even though SCD41 has been silent for hours.

### Pitfall 3: Heartbeat bypassing snooze (ok) vs sensor alert ignoring snooze (not ok)
**What goes wrong:** Heartbeats use `bypassCap: true` (index.js L52) and the heartbeat path bypasses ALL snoozes (state.js L380 comment). Per-sensor alerts must NOT bypass snooze — `snooze sht30 4h` should mute SHT30 offline messages without muting SCD41.
**Why it happens:** Tempting to follow heartbeat path because both are "system status" messages.
**How to avoid:** Route through `driveAlertType`, which checks `isSnoozed(next, now)` at L84 before pushing send actions. Don't introduce a parallel send path.
**Warning signs:** Snoozing one sensor type silences both.

### Pitfall 4: Breaking Phase 16 sensor_health KeyValue contract
**What goes wrong:** Bridge L685-687 flattens `msg.values` (KeyValue[]) into a plain object, then OpenMCT plugin reads it. Adding new keys (`sht30_fresh`, `scd41_fresh`) is safe — flattening is permissive — but renaming or removing existing keys (`warming_up`, `grace_elapsed_sec`, `grace_total_sec`, `buffer_full`) breaks the warm-up countdown card.
**Why it happens:** Refactor temptation when adding new fields.
**How to avoid:** Append-only changes to the KeyValue list at fc_controller.py L256-261. Run Phase 16's manual smoke (16-SMOKE-EVIDENCE.md) after the change.
**Warning signs:** Phase 15 grace countdown card goes grey or shows NaN.

### Pitfall 5: Startup grace window double-counting
**What goes wrong:** Alerter has a 60s startup grace (state.js L291). If sensor freshness is evaluated during this window, a fresh-after-boot Pi looks "offline" for 5min, fires an alert, then recovers — pure noise.
**How to avoid:** Mirror the L291 check exactly: `if (now - next.bootedAtMs < 60000) break;` before the offline detection fires. Plus: `lastSeenMs` should default to `bootedAtMs`, not `null`, so a never-seen sensor doesn't immediately trigger. (Consideration: a truly absent sensor — e.g., SHT30 unplugged at boot — should still alert after 5+1 = ~6 min, not be silent forever.)

### Pitfall 6: ROS2 publisher created at __init__ but never used in sim mode
**What goes wrong:** `fc_sensors.py` simulation mode (L86-95) generates fake values and publishes on slot 1. Adding slot 2 publishers but not feeding them in sim mode means simulation-mode tests can't exercise slot 2.
**How to avoid:** In sim mode, publish slot-2 values too (jitter the sim values slightly differently to mimic SCD41 ≠ SHT30 disagreement, e.g., `sim_temp_2 = sim_temp + 0.3 + jitter`). This makes simulation faithful to the dual-sensor reality, useful for headless testing.

## Code Examples

### Example A: Slot 2 publishers + freshness tracking (fc_sensors.py)

```python
# Source: refactor pattern based on fc_sensors.py L55-95
# In __init__:
self.temp_pub      = self.create_publisher(Temperature,      'fc1/temperature',     10)
self.humidity_pub  = self.create_publisher(RelativeHumidity, 'fc1/humidity',        10)
self.co2_pub       = self.create_publisher(Float32,          'fc1/co2',             10)
self.temp_2_pub    = self.create_publisher(Temperature,      'fc1/temperature_2',   10)  # NEW
self.humidity_2_pub= self.create_publisher(RelativeHumidity, 'fc1/humidity_2',      10)  # NEW
self._sht30_last_read_ns = None  # NEW: per-sensor freshness
self._scd41_last_read_ns = None  # NEW
```

### Example B: sensor_health KeyValue extension (fc_controller.py)

```python
# Source: append to fc_controller.py L256-261
# In _publish_sensor_health, add staleness flags. Threshold: sensor_stale_timeout (already 10s, fc_config.yaml L38).
# Requires fc_controller to subscribe to fc1/temperature_2 (mirror humidity_callback pattern L133-136).
sht30_fresh = self._sht30_age_sec() < self.get_parameter('sensor_stale_timeout').value
scd41_fresh = self._scd41_age_sec() < self.get_parameter('sensor_stale_timeout').value
msg.values = [
    KeyValue(key='warming_up',         value=str(warming_up).lower()),
    KeyValue(key='grace_elapsed_sec',  value=f'{elapsed:.1f}'),
    KeyValue(key='grace_total_sec',    value=f'{grace_period:.1f}'),
    KeyValue(key='buffer_full',        value=str(buffer_full).lower()),
    KeyValue(key='sht30_fresh',        value=str(sht30_fresh).lower()),  # NEW
    KeyValue(key='scd41_fresh',        value=str(scd41_fresh).lower()),  # NEW
]
```

NOTE: `_publish_sensor_health` is currently called only on warm-up state change (L262 — "Called on state CHANGE only"). Per-sensor freshness alerts need either (a) calling `_publish_sensor_health` periodically once warm-up is over, or (b) detecting freshness changes (sht30 fresh→stale or stale→fresh) and republishing only on change. Option (b) preserves the "quiet topic" property of Phase 16 and is cheaper. Recommend: track `_last_sht30_fresh` / `_last_scd41_fresh`, republish on flip.

### Example C: Add sht30/scd41 alert types (state.js)

```javascript
// Source: state.js L8-11
const ALERT_TYPES = ['rh', 'sensor', 'pi', 'humidifier', 'sht30', 'scd41'];  // EXTEND
const SEVERITY = {
    rh: 'WARN', sensor: 'CRITICAL', pi: 'CRITICAL', humidifier: 'WARN',
    sht30: 'CRITICAL',  // NEW
    scd41: 'CRITICAL',  // NEW
};
```

### Example D: Freshness watchdog rule (rules.js)

```javascript
// Source: pattern from rules.js L27-39
function isSensorSilent({ lastSeenMs, nowMs, config }) {
    if (lastSeenMs == null) return false;  // never seen — startup grace handles
    const thresholdMs = config.sensorOfflineMin * 60000;
    return nowMs - lastSeenMs > thresholdMs;
}
module.exports = { isRhOob, isSensorError, isPiOffline, isHumidifierStuck, isSensorSilent };
```

### Example E: Bridge slot 2 subscription (bridge/src/index.js)

```javascript
// Source: copy of L619-630 with topic + telemetry name swapped
node.createSubscription(
    'sensor_msgs/msg/Temperature',
    '/fc1/temperature_2',  // NEW
    async (msg) => {
        const value = msg.temperature;
        const ts = Date.now();
        latestTelemetry.temperature_2 = { value, timestamp: ts };
        broadcast({ temperature_2: value, timestamp: ts });
        await insertTelemetry('fc.temperature_2', value);  // NEW topic ID
    }
);
// Repeat for fc1/humidity_2 → fc.humidity_2
```

### Example F: Snooze grammar extension (snooze.js)

```javascript
// Source: snooze.js L3, L15
const VALID_ALERT_TYPES = ['rh', 'sensor', 'pi', 'humidifier', 'sht30', 'scd41', 'all'];
const STRICT = /^snooze\s+(rh|sensor|pi|humidifier|sht30|scd41|all)\s+(30m|1h|2h|4h|8h|24h)\s*$/i;
```

## Offline Detection Options

> This section evaluates the three approaches called out in Claude's Discretion. Recommendation: **Option C**.

### Option A: Pi-side only (extend `sensor_health.values`)

**How:** `fc_controller` subscribes to slot 2; tracks per-sensor `_last_*_age_sec()`; flips `sht30_fresh` / `scd41_fresh` KeyValue on staleness change → publishes new `sensor_health`. Alerter parses KeyValues and routes per-sensor.

**Pros:**
- Single source of truth (Pi knows authoritative I2C-level freshness).
- Reuses Phase 16 contract — no new topics.
- Bridge already forwards `sensor_health` to WS (Phase 16 Plan 01) — zero bridge changes.
- Mission Control panel can show per-sensor green/grey lights without alerter involvement.

**Cons:**
- If `fc_controller` itself crashes, no `sensor_health` updates flow → alerter has no signal that sensors went silent (the `pi` alert would catch it, but per-sensor granularity is lost).
- Slot-2 staleness in `fc_controller` requires it to subscribe to slot-2 topics — small additional plumbing.

### Option B: Alerter-side only (topic-silence watchdog)

**How:** Alerter tracks `sht30LastSeenMs` / `scd41LastSeenMs` from WS arrival timestamps. SCD41 freshness comes from `temperature_2`/`humidity_2` arrival (slot 2 = SCD41-only by D-02). SHT30 freshness comes from… nothing direct — slot 1 silently falls back, so slot 1 arrivals don't prove SHT30 is alive.

**Pros:**
- Decoupled — alerter is independent of Pi nodes' inner state.
- Survives `fc_controller` crashing.

**Cons:**
- **SHT30 freshness has no clean signal in Option B.** Slot 1 messages arrive whether SHT30 or SCD41 backed them. There is no alerter-visible fact that proves SHT30 is alive without `sensor_health.values.sht30_fresh`. **This is the killer.**
- Could work for SCD41 alone (slot 2 arrivals are sufficient), but the 2026-04-11 incident is *specifically about SHT30* — so half-coverage isn't acceptable.

### Option C: Hybrid (Pi-side authoritative + alerter-side independent watchdog) — RECOMMENDED

**How:**
- Pi side: `fc_controller` adds `sht30_fresh` / `scd41_fresh` to `sensor_health.values` (Example B above). Drives the dashboard "live status" lights and is the *primary* alert input.
- Alerter side: Routes `sensor_health.values.sht30_fresh === 'false'` → fires `sht30` offline state machine. Routes `temperature_2`/`humidity_2` arrival to refresh `scd41LastSeenMs` (belt-and-braces — if `sensor_health` itself stops flowing, the alerter still notices SCD41 silence from slot 2 silence).
- The `pi_liveness` alert continues to cover the catastrophic case (Pi totally offline) — no per-sensor confusion.

**Pros:**
- Per-sensor granularity (D-05) — covered.
- Recovery falls out of `driveAlertType` (D-06) — covered.
- 5-min threshold via env (D-04) — covered.
- Survives partial failures: `fc_controller` crash → Pi alert fires; SCD41 hardware crash → alerter sees slot 2 silence even if Pi-side `sensor_health` lags.
- All freshness calculations happen exactly once in fc_controller; alerter just consumes a flag. No clock-skew between Pi and elder-plops.

**Cons:**
- Slightly more code than pure Option A, but the alerter side is ~5 LOC for SCD41 timestamp tracking.

### Option Comparison

| Option | LOC est. | SHT30 covered | SCD41 covered | Survives fc_controller crash | Recommendation |
|--------|----------|---------------|---------------|------------------------------|----------------|
| A (Pi only) | ~40 | ✓ | ✓ | ✗ (granularity lost) | OK if Pi reliability is treated as solved |
| B (Alerter only) | ~30 | ✗ (no signal) | ✓ | ✓ | Insufficient — kills the use case |
| **C (Hybrid)** | **~60** | **✓** | **✓** | **✓** | **RECOMMENDED** |

**Confidence:** HIGH — all three options were sanity-checked against the actual code paths in `fc_controller.py`, `state.js`, and `bridge/src/index.js`. Option B's killer flaw (no SHT30-specific alerter-visible fact) is direct from D-01 (silent fallback).

## Existing Alerter Cooldown / Dedup Pattern

> Required reading for the planner — extends `driveAlertType` rather than reinventing.

| Location | Behavior | Reuse In Phase 26 |
|----------|----------|-------------------|
| `state.js` L11 `SEVERITY` map | `'CRITICAL'` → `criticalCooldownMin` (default 60min). `'WARN'` → `cooldownMin` (default 30min). | Add `sht30: 'CRITICAL'`, `scd41: 'CRITICAL'`. |
| `state.js` L49 `cooldownMs(alertType, config)` | Returns severity-mapped cooldown ms. | Used by `driveAlertType` automatically once SEVERITY[type] is set. |
| `state.js` L83-92 PENDING→FIRING transition | Requires `oobN` consecutive OOB samples within `oobWindowMin`. For per-sensor offline, set `oobN=1, oobWindowMin=0` (the same trick used at L218 for sensor ERROR). | Set `sensorCfg = { ...config, oobN: 1, oobWindowMin: 0 }` at the call site. |
| `state.js` L113 cooldown check | `now - lastFiredAt > cooldownMs(...)` before re-sending while FIRING. | Free reuse via `driveAlertType`. |
| `state.js` L132-148 in-band recovery | When `oobNow` flips false for `oobN` consecutive samples, emits `{ kind: 'recovery', ... }`. | This is exactly D-06; free reuse. |
| `state.js` L57 `isSnoozed(perTypeEntry, now)` | Per-type snooze with `snoozedUntil`. | New types `sht30`/`scd41` get per-type snooze for free once added to `ALERT_TYPES`. |
| `state.js` L347 `case 'snooze':` | Routes snooze events. | No change needed; iterates `ALERT_TYPES`. |
| `signal.js` `maxSendsPerHour` (config L40, default 20) | Hourly send cap shared across all alert types. | Phase 26 inherits — two extra alert types could under load push close to cap, but each fires at most once per cooldown (60min), so worst case is ~2 extra/hour. Negligible. |
| `index.js` L121 `setInterval` 30s tick | Re-evaluates `pi_liveness` and `humidifier_stuck` even without inbound events. | Same tick must re-evaluate `sht30`/`scd41` silence — add the freshness checks to `case 'tick':` at state.js L309. |
| `index.js` L86 `onLiveness` callback | Triggered by bridge `/health` poll, dispatches `pi_liveness` event with `wsConnected`/`rosConnected`. | Phase 26 doesn't need a new liveness path — uses WS-message arrival timestamps + existing `sensor_health` route. |

**Tests:** state.js patterns are exercised by `test/state.test.js` lines 170-258 (cooldown, severity cadence, warmup suppression, sensor ERROR firing during warmup). Phase 26 should add equivalent tests for `sht30` and `scd41` types — copy the `sensor_health` ERROR test (state.test.js L245-258) and the cooldown test (L180-192).

## Per-Consumer Impact Table for Slot 2

| Consumer | File | Current Slot 1 dependency | Slot 2 benefit | Recommended action this phase |
|----------|------|---------------------------|----------------|--------------------------------|
| `fc_controller` (control loop) | `src/chambers/fc-core/fc_core/fc_controller.py` L81-90 | Reads slot 1 for PID-less bang-bang RH control | None for control. **Yes** for freshness publishing — needs slot-2 subscription to populate `scd41_fresh` flag | **Subscribe to slot 2 (read-only)** to compute `scd41_fresh`. Do NOT change control logic — D-01 explicit. |
| `fc_telemetry` (legacy WS server) | `src/chambers/fc-core/fc_core/fc_telemetry.py` L17-26 | Subscribes to slot 1, runs its own WS on `localhost:8081` | Low — this is unused in production (Mission Control consumes via the elder-plops bridge, not Pi WS) | **Skip.** Legacy path; touching it adds risk without value. |
| `fc_display` (Pi log line) | `src/chambers/fc-core/fc_core/fc_display.py` L13-21 | Subscribes to slot 1 for log output | None — operator looks at Mission Control / Signal, not Pi journalctl | **Skip.** |
| Mission Control bridge — WS broadcast | `src/mission-control/bridge/src/index.js` L606-643 | Subscribes to T/RH/CO2 slot 1 + humidifier; broadcasts to OpenMCT WS clients | **High** — is the single chokepoint for browser + alerter; without this, slot 2 doesn't exist outside Pi DDS | **MUST DO.** Two new subscriptions, identical pattern to slot 1. |
| Mission Control bridge — TimescaleDB writer | `src/mission-control/bridge/src/index.js` L580-591 (`insertTelemetry`) | Inserts `fc.temperature` / `fc.humidity` / `fc.co2` / `fc.humidifier` | **High** — without this, slot 2 doesn't make it into history → no farmer "second opinion" trend chart | **MUST DO.** Identical INSERT pattern with new topic IDs `fc.temperature_2` / `fc.humidity_2`. |
| OpenMCT plugin (engineer dashboard) | `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` L15-57 | Renders 4 SENSORS entries via WS subscription | **Medium** — engineer-facing only; Phase 999.17 explicitly scopes overlay plots for SHT30 vs SCD41 | **Optional / minimal.** Add 2 SENSORS entries (`fc.temperature_2`, `fc.humidity_2`) with min/max from existing slot-1 entries. Defer overlay layout to 999.17. |
| Mission Control health panel (Phase 16) | same plugin file | Reads `sensor_health.level` for warm-up light | **High** — extending `sensor_health.values` with `sht30_fresh`/`scd41_fresh` enables per-sensor green/grey lights, the visceral fix for the 2026-04-11 incident | **Recommended.** Add 2 status lights ("SHT30", "SCD41") consuming `sensor_health.values.{sht30_fresh,scd41_fresh}`. Reuses Phase 14's `makeStatusLight` factory at plugin.js L70. |
| Alerter agent | `src/agents/alerter/src/*` | Subscribes via bridge WS to humidity / temperature / co2 / humidifier / sensor_health | **High** — implements Phase 26's offline alarms | **MUST DO.** All edits described above. |
| farmos-agent (daily report) | `src/farmos-agent/farmos_agent/telemetry_query.py` L12-15 | Queries `fc.humidity` / `fc.temperature` / `fc.co2` / `fc.humidifier` from TimescaleDB | None for daily report (slot 1 is the operating record); maybe adds confusion if also reporting slot 2 | **Skip.** Daily report stays slot-1. Cross-sensor drift is deferred (CONTEXT deferred ideas). |
| farmer dashboard (farmOS proxy) | (memory `project_phase18_22_farmos_proxy_architecture.md`) | Polls bridge endpoints | Future — once "second opinion" is wanted as a farmer surface | **Skip.** Memory note says farmOS owns UI; let farmer team pull slot 2 when they want it. Phase 26 ships the data. |

**Summary of "must do" surfaces:** bridge WS + DB writes, alerter, fc_controller subscription. **"Recommended":** OpenMCT health-panel lights for visceral 2026-04-11 fix. **"Skip":** legacy nodes, farmos-agent, farmer dashboard.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Pi-side framework | pytest (ament_python) — `setup.py` L33 declares `tests_require=['pytest']` |
| Pi-side config | `src/chambers/fc-core/fc_core/test/` directory; existing files `test_camera.py`, `test_controller.py`. **No `test_sensors.py` exists** — Wave 0 gap. |
| Alerter framework | jest ^29.7.0 — `package.json` L16 |
| Alerter config | `src/agents/alerter/jest.config.js`; tests in `test/` parallel to `src/` |
| Quick run command (Pi) | `cd src/chambers/fc-core && pytest fc_core/test/ -x` |
| Quick run command (alerter) | `cd src/agents/alerter && npm test` |
| Full suite (Pi) | `colcon test --packages-select fc_core` |
| Full suite (alerter) | `cd src/agents/alerter && npm test -- --coverage` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-01 | Slot 1 publishes SHT30 when SHT30 fresh | unit | `pytest fc_core/test/test_sensors.py::test_slot1_uses_sht30_when_present -x` | ❌ Wave 0 — `test_sensors.py` does not exist |
| D-01 | Slot 1 falls back to SCD41 when SHT30 absent | unit | `pytest fc_core/test/test_sensors.py::test_slot1_falls_back_to_scd41 -x` | ❌ Wave 0 |
| D-02 | Slot 2 publishes SCD41 unconditionally when SCD41 fresh | unit | `pytest fc_core/test/test_sensors.py::test_slot2_publishes_scd41 -x` | ❌ Wave 0 |
| D-02 | Slot 2 publishes regardless of SHT30 state | unit | `pytest fc_core/test/test_sensors.py::test_slot2_independent_of_sht30 -x` | ❌ Wave 0 |
| D-03 | No publish when underlying sensor stale | unit | `pytest fc_core/test/test_sensors.py::test_no_stale_publish -x` | ❌ Wave 0 |
| D-04 | sht30 alert fires after 5 min silence | unit | `cd src/agents/alerter && npx jest test/state.test.js -t "sht30 fires after sensorOfflineMin"` | ❌ Wave 0 — new test |
| D-04 | scd41 alert fires after 5 min silence | unit | `cd src/agents/alerter && npx jest test/state.test.js -t "scd41 fires after sensorOfflineMin"` | ❌ Wave 0 |
| D-05 | sht30 firing does not fire scd41 | unit | `cd src/agents/alerter && npx jest test/state.test.js -t "sht30 silence does not fire scd41"` | ❌ Wave 0 |
| D-06 | Recovery message on sensor resume | unit | `cd src/agents/alerter && npx jest test/state.test.js -t "sht30 recovery on freshness flip"` | ❌ Wave 0 |
| D-06 | Cooldown reuses criticalCooldownMin | unit | `cd src/agents/alerter && npx jest test/state.test.js -t "sht30 repeats after criticalCooldownMin"` | ❌ Wave 0 |
| Smoke | Slot 2 visible on bridge `/health` (or WS broadcast contains `temperature_2`) | smoke (manual) | `wscat -c ws://elder-plops-ts:8081 \| head -20` post-deploy; expect `{"temperature_2":...}` lines | manual |
| Smoke | sensor_health.values has sht30_fresh and scd41_fresh | smoke (manual) | `curl -s http://elder-plops-ts:8081/health` then `ros2 topic echo /fc1/sensor_health -n 1` on Pi | manual |

**Manual end-to-end (after Pi deploy + alerter rebuild):**
1. SSH to fc1-ts; physically pull SHT30 I2C wire (or `i2cset` to bad addr).
2. Wait 5 min; expect Signal "[PROBLEM · CRITICAL] FC-1 · SHT30 offline" message.
3. Reconnect SHT30; expect "[RECOVERY] FC-1 · SHT30 offline back" within ~30s (the tick interval).
4. Repeat for SCD41 (cover I2C 0x62 with tape or unplug Stemma cable).

### Sampling Rate
- **Per task commit:** Pi → `pytest fc_core/test/test_sensors.py -x` (when added). Alerter → `npm test`.
- **Per wave merge:** Pi → `colcon test --packages-select fc_core`. Alerter → `npm test`.
- **Phase gate:** Both green; manual end-to-end smoke captured in `26-SMOKE-EVIDENCE.md`.

### Wave 0 Gaps

- [ ] `src/chambers/fc-core/fc_core/test/test_sensors.py` — doesn't exist; create with simulation-mode-driven unit tests for slot 1/2 publish gating. Use `sensor_simulation_mode=true` so no GPIO needed; mock `self.sht` / `self.scd` to control which sensor "responds" each tick. Pattern: same `ros_context` fixture used in `test_controller.py` (it's set up in `conftest.py` if it exists, otherwise inherit from controller test setup).
- [ ] Extend `src/agents/alerter/test/state.test.js` with `describe('sht30_offline')` and `describe('scd41_offline')` blocks — copy structure from `describe('warmup_does_NOT_suppress_sensor_error')` at L245.
- [ ] No new framework install needed — pytest and jest already present.

## Security Domain

> Per Phase 16/17 lineage; security_enforcement is enabled by default.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new authenticated endpoints — Signal API auth and DB auth already in place |
| V3 Session Management | no | No sessions involved |
| V4 Access Control | no | Internal services on Tailscale tailnet |
| V5 Input Validation | yes | snooze.js regex L15 — extend strictly (don't broaden) when adding `sht30\|scd41` to alternation |
| V6 Cryptography | no | No new crypto |

### Known Threat Patterns for {ros2 + node alerter} stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Snooze command injection (Signal text) | Tampering | Anchored regex with explicit alternation (snooze.js L15); fallback to `fuzzyReply` for any non-match — already in place |
| Topic-name typo enabling silent failure | Information disclosure (operator misled) | Tests assert exact topic strings (`fc1/temperature_2`, `fc1/humidity_2`); bridge subscription string must match producer |
| Stale-value republish across container restart | Tampering (false readings) | TRANSIENT_LOCAL is **not** used on slot 2 (gap-over-noise; see Pitfall 2) |
| Signal flooding via bouncing freshness | DoS (operator burnout, hits hourly cap) | `cooldownMs` + `criticalCooldownMin=60` already gate repeat sends; PENDING→FIRING transition prevents flapping (state.js L96-109) |

## Sources

### Primary (HIGH confidence)
- `src/chambers/fc-core/fc_core/fc_sensors.py` — current single-slot publisher
- `src/chambers/fc-core/fc_core/fc_controller.py` L80-275 — `sensor_health` publisher contract + slot-1 staleness pattern
- `src/chambers/fc-core/config/fc_config.yaml` — `sensor_stale_timeout`, `sensor_simulation_mode`
- `src/chambers/fc-core/launch/fc.launch.py` — node startup order (sensors → controller → display → camera)
- `src/agents/alerter/src/state.js` — full state machine; ALERT_TYPES, SEVERITY, driveAlertType, transition (the spine of all alerting)
- `src/agents/alerter/src/rules.js` — predicates including `isPiOffline` (the template for `isSensorSilent`)
- `src/agents/alerter/src/index.js` — WS message routing, 30s tick scheduler
- `src/agents/alerter/src/message.js` — ALERT_TITLES, formatProblem, formatRecovery
- `src/agents/alerter/src/snooze.js` — snooze grammar
- `src/agents/alerter/src/config.js` — env var schema (where `sensorOfflineMin` would land)
- `src/mission-control/bridge/src/index.js` L580-700 — telemetry insertion + slot 1 + sensor_health forwarding
- `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` L1-100 — SENSORS layout + makeStatusLight primitive
- `.planning/phases/16-system-health-panel/16-01-SUMMARY.md` — sensor_health WS contract
- `.planning/phases/26-dual-sensor-publishing-offline-alarms-sht30-scd41-slot-topic/26-CONTEXT.md` — locked decisions
- `.planning/phases/999.11-farmer-app/FARMER-APP-NOTES-2026-04-11.md` L24-37 — incident motivation

### Secondary (MEDIUM confidence)
- ROADMAP.md L152-160 — Phase 26 entry
- STATE.md L68 — Phase 26 motivation summary

### Tertiary (LOW confidence)
- None — all claims sourced from repo files directly.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Snooze grammar should accept `sht30` / `scd41` as new types | Pattern F / snooze.js | If user expects `snooze sensor 4h` to mute both, they'll be confused. Mitigation: keep existing `sensor` type meaning unchanged (it gates the level=2 ERROR case) and document that `sht30`/`scd41` are sibling types. Could also add `snooze sensors all` as convenience. Worth a one-line confirmation from user before implementation. |
| A2 | 60s startup grace at state.js L291 is the right place to mirror for sensor freshness | Pitfall 5 | If sensors take longer than 60s to first-publish (unlikely on warm reboot), Phase 26 will fire spurious offline alerts on every boot. Mitigation: initialize `sht30LastSeenMs` / `scd41LastSeenMs` to `bootedAtMs`, not `null`. |
| A3 | TimescaleDB will accept `fc.temperature_2` / `fc.humidity_2` as new topic strings without schema changes | Per-Consumer Impact / Runtime State | VERIFIED via reading `INSERT INTO telemetry (time, topic, value)` at bridge L585 — `topic` is a free-form text column. Marking VERIFIED, demoting from assumption. |
| A4 | farmer team / 999.17 owns the overlay-plot Mission Control layout, so Phase 26 doesn't need to ship overlays | Per-Consumer Impact | Confirmed by ROADMAP L149 ("Phase 999.17: Mission Control overlay plots"). |
| A5 | sensor_simulation_mode is enough to test the dual-publisher logic without GPIO | Validation Architecture | Confirmed by reading fc_sensors.py L49-53; sim path is fully software, no hardware ever touched. |

## Open Questions (RESOLVED)

1. **Should `_publish_sensor_health` be called outside warm-up state changes once it gains freshness flags?**
   - What we know: Today it's called only on enter/exit of warm-up (fc_controller.py L268, L275). Plan 26 needs it to publish on `sht30_fresh` / `scd41_fresh` transitions too.
   - **RESOLVED — republish on flip only.** Track `_last_sht30_fresh` / `_last_scd41_fresh`, compare each `control_loop` tick, republish only on change. This preserves Phase 16's TRANSIENT_LOCAL "quiet topic" property — late joiners still receive the latest state via durability without per-tick noise on the wire.

2. **Does the alerter need an explicit `sensor_freshness` event type, or can it parse `sensor_health.values` inside the existing `sensor_health` route?**
   - **RESOLVED — parse inside the existing sensor_health route, plus a NEW `sensor_freshness` event ONLY for slot-2 WS arrivals (SCD41 belt-and-braces).** SHT30 freshness lives entirely inside the extended `sensor_health` case in `state.js` (reading `values.sht30_fresh`). SCD41 freshness has TWO entry points: (a) the same `sensor_health.values.scd41_fresh` parsed inside the route, and (b) a `sensor_freshness` event dispatched by `index.js` on `temperature_2`/`humidity_2` WS arrival. This keeps SHT30 derivation single-source while letting SCD41 survive an `fc_controller` crash.

3. **Should the SCD41 belt-and-braces watchdog (alerter-side WS arrival timestamp) override or supplement the Pi-side `scd41_fresh` flag?**
   - **RESOLVED — OR-gate.** Fire SCD41 alert if EITHER `scd41_fresh === 'false'` OR `nowMs - scd41LastSeenMs > thresholdMs`. Rationale: this favors silence detection over false-positive avoidance, which matches Phase 26's primary motivation (the 2026-04-11 incident was a 40-minute SHT30 outage that went unnoticed — under-detection is the worse failure mode). Documented as a deliberate tradeoff in Plan 03 must_haves.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest | fc_core unit tests | ✓ (declared in setup.py) | latest in ament_python | — |
| jest | alerter unit tests | ✓ | 29.7.0 | — |
| ros2 jazzy | colcon build | ✓ on dev + Pi | jazzy | — |
| docker compose | alerter rebuild | ✓ | v2 (per memory `project_compose_v2_upgrade.md` — actually dev still on 1.29; works on prod side) | — |
| signal-cli | alert delivery | ✓ existing service (link gotchas in memory `project_signal_cli_link_gotchas.md`) | linked already | — |
| Pi I2C bus | hardware testing | ✓ on fc1, ✗ on dev | — | Use `sensor_simulation_mode: true` for dev test runs |
| `wscat` (or curl + manual WS) | manual smoke for slot 2 broadcast | ✗ on dev (likely not installed) | — | `npm install -g wscat` once, or use a one-off node script |

**Missing dependencies with no fallback:** None — Phase 26 is fully testable in sim mode on dev, with real-hardware verification gated to Pi deploy.

**Missing dependencies with fallback:** `wscat` for manual smoke; trivially `npm install -g wscat` or use the existing alerter's `ws` package in a 5-line throwaway script.

## Validation Architecture (consolidated above)

See "Validation Architecture" section above (placed earlier per template requirements).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every library is already in tree and verified by reading manifests.
- Architecture: HIGH — extends a state machine that already handles 4 alert types identically; the new types follow the same pattern verbatim.
- Pitfalls: HIGH — Pitfall 1 (single try/except) was found by reading the actual code, not training data; Pitfall 2 (TRANSIENT_LOCAL on slot 2) is grounded in Phase 16's explicit QoS choices; Pitfalls 3-6 are likewise repo-grounded.
- Per-consumer table: HIGH — every consumer was opened and confirmed by grep + read.
- Recommendation (Option C): HIGH — Option B is provably insufficient (no SHT30 signal under D-01), Option A loses redundancy, hybrid is the same code as A plus a 5-line SCD41 timestamp tracker.

**Research date:** 2026-04-25
**Valid until:** 2026-05-25 (30-day window — codebase is fast-moving but the specific files researched are stable Phase 14-22 era).
