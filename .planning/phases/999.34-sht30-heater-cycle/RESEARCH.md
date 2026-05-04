# Phase 999.34: Periodic SHT30 Heater Cycle to Clear Membrane Condensation — Research

**Researched:** 2026-05-04
**Domain:** I2C sensor lifecycle management + ROS2 control-loop state machine + alerter/telemetry suppression
**Confidence:** HIGH on driver surface and state-machine design; MEDIUM on heater cadence/duration (live-test data trumps datasheet ranges); LOW on long-run condensation-clearing efficacy (only proven by 30-day soak).

## Summary

The SHT3x has a well-known "creep" failure mode at sustained RH > 90 %: the polymer dielectric absorbs water and the RH reading drifts high (slowly approaching 100 %). FC-1 lives in exactly this regime 24/7. Sensirion's recommended mitigation is periodic activation of the on-die heater, which raises the sensor die ~0.5–1.5 °C, evaporating absorbed water and any condensed droplets, then letting the membrane re-equilibrate to ambient.

The heater is already exposed by `adafruit_sht31d` as `self.sht.heater = True/False` — no driver work. The hard part is **everything around the heater**: the controller must NOT react to the synthetic RH dip; the alerter must NOT fire "sensor stale" or "RH low" during the recovery window; Mission Control charts must NOT render the corrupted readings as a real anomaly. The 2026-05-04 22:02 UTC live test proved that without a controller guard, the feature is **net-negative** — PID spiked duty 0 → ~0.85 in response to the synthetic dip.

**Primary recommendation:** Implement a single-source-of-truth `heater_state` machine in `fc_sensors.py` (NORMAL → HEATING → RECOVERING → NORMAL), publish `fc1/sensor_health.heater_active` + `heater_recovery_until` (TRANSIENT_LOCAL QoS so late-joiners snap to current state), and gate every downstream consumer (controller PID, alerter rules, derived telemetry, Timescale insert) on that flag. Ship together with 999.32 (derivative filter) — they compose, and 999.34 alone is net-negative until 999.32 lands or the controller-guard suppresses the PID step entirely.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Heater on/off + scheduling | `fc_sensors` (sensor node) | — | Single owner of the I2C device; only node that knows when readings are valid |
| Heater state telemetry | `fc_sensors` → `fc1/sensor_health` (or new `fc1/sensor/sht30_heater`) | bridge republish | Status fields go where freshness already lives (Phase 26 pattern) |
| Hold-last-duty during cycle | `fc_controller` | — | Controller already owns duty publishing; gating one tick is one if-statement |
| PID integrator/derivative reset | `fc_controller` | composes 999.32 | Avoids post-recovery spike from accumulated error during gap |
| Alert suppression during cycle | `alerter/rules.js` | — | Alerter is the only system that classifies "stale" / "OOB" as an alarm |
| Chart annotation / data-gap | bridge + Mission Control plugin | — | Chart UI concern, not a fc-core concern |
| Timescale write decision | bridge | — | Skip insert during heater + recovery window so derivations stay clean |

## Standard Stack

### Core (already present, no new deps)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `adafruit_sht31d` | ≥2.3 (already installed) | SHT30 driver — exposes `.heater` property | Vendor-blessed CircuitPython driver; reads/writes status register correctly [VERIFIED: github.com/adafruit/Adafruit_CircuitPython_SHT31D] |
| `rclpy` | jazzy | ROS2 Python client | Already used in fc_sensors / fc_controller |
| `rclpy.duration.Duration` | jazzy | ROS-time deadline arithmetic | Use for `heater_recovery_until` — not wall clock |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `diagnostic_msgs/DiagnosticStatus` | jazzy | Sensor health publishing | Already used in `fc1/sensor_health` (Phase 16/26) — extend with new KeyValue fields |
| `std_msgs/Bool` | jazzy | Boolean topic for heater_active | If we publish a dedicated topic for clean alerter/bridge subscription |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Reusing `fc1/sensor_health` (DiagnosticStatus) | New `fc1/sensor/sht30_heater_active` Bool topic | Bool topic is cleaner for alerter/bridge to subscribe ("only fires on transitions"); but adds another topic to QoS-tune. **Recommendation:** add KeyValues to `sensor_health` AND publish a dedicated `Bool` topic — DiagnosticStatus is for human-facing health UI (Phase 16), Bool is the machine-readable contract. |
| Schedule via ROS timer in fc_sensors | Schedule via separate node | Same node = one I2C lock holder; trivially safer. Keep it in fc_sensors. |
| Wall-clock cron (e.g., 03:00 UYT) | ROS-time interval ("every 4 h since boot") | Wall-clock keeps it predictable for the farmer ("nightly at 3am"); ROS-time is robust to clock skew. **Recommendation:** wall-clock for cadence (farmer-visible) + ROS-time for window deadlines (correctness). |

**Installation:** No new pip packages required.

**Version verification:** `adafruit_sht31d` heater property has been stable since v1.x [CITED: docs.circuitpython.org/projects/sht31d]. No version pin change needed.

## User Constraints

(No CONTEXT.md exists yet — this phase has not been through `/gsd-discuss-phase`. The ROADMAP entry provides design-question defaults. Treat the following as the strongest available constraints for the planner:)

### Locked Decisions (from ROADMAP entry + 2026-05-04 live test)
- **Controller guard is mandatory.** Heater feature shipped without controller-guard is net-negative (live-tested). Guard + heater must ship together.
- **Heater pulse duration: 1 s.** Datasheet allows 1–3 s; 1 s minimizes corruption window. Re-evaluate on production data only after first 30-day soak.
- **Hold-last-duty for full window.** Rejected alternatives: safe-state OFF (causes RH dip), continue-PID-on-stale-data (drifts).
- **Compose with 999.32.** Plan must call out 999.32 as a hard-or-immediately-after dependency. If 999.32 is not yet shipped, Wave 0 of 999.34 must include the same derivative-state reset semantics inline.
- **Do NOT failover to SCD41 during SHT30 heater window.** SCD41 RH clips at 100 %; in the regime where we run the heater (sustained > 94 %), SCD41 is worse than holding last-duty.

### Claude's Discretion
- Cadence: ROADMAP suggests nightly 03:00 UYT as default. Discretion on whether to additionally support a condition-trigger ("RH > 95 % sustained 24 h") in this phase or defer.
- Telemetry shape: KeyValues on `sensor_health` vs dedicated `Bool` topic vs both. **Recommend both** (see Alternatives Considered).
- Recovery-window length: live test measured ~150 s for RH; recommend a parameter `heater_recovery_seconds` defaulting to 180 s, runtime-tunable per farmer.

### Deferred Ideas (OUT OF SCOPE)
- Cross-sensor drift inference (compare SHT30 vs SCD41 RH) — separate backlog.
- Multi-SHT30 redundant-head setup (heater-cycle one while reading the other) — explicit multi-sensor design, not this phase.
- SCD41 self-calibration changes — explicitly out per ROADMAP.
- Mode-aware cadence (more aggressive heater in `fruiting`, dormant in `incubation`) — composes with Phase 28 mode primitive, not yet shipped.

## Phase Requirements

(Derived from ROADMAP acceptance criteria — planner should rename to formal REQ-IDs.)

| ID | Description | Research Support |
|----|-------------|------------------|
| HEAT-01 | Nightly heater pulse at 03:00 UYT, visible in Timescale as a marked gap | Wall-clock cadence + bridge-side write suppression |
| HEAT-02 | Mission Control RH chart shows annotation, not corrupt spike | bridge republish of `heater_active` + chart plugin |
| HEAT-03 | Controller duty stays at pre-cycle value through full window (heat + recovery) | State-machine guard in `control_loop` + PID integrator/derivative freeze |
| HEAT-04 | Alerter does NOT fire `sht30 sensor stale` / `rh oob` during heater window | Alerter rule guard reading `heater_active` |
| HEAT-05 | Post-window RH within 0.1 % of pre-window value (no drift introduction in non-condensed sensor) | Empirical validation metric (logged) |
| HEAT-06 | Over 30-day soak, observe SHT30↔SCD41 RH delta narrowing | Long-run validation (this is the only proof the heater is doing real work) |

## Architecture Patterns

### State Machine (canonical)

```
   [boot]
     │
     ▼
   NORMAL ──(scheduler triggers)──▶ HEATING (1 s)
     ▲                                  │
     │                                  ▼
     └──(recovery_until elapsed)── RECOVERING (180 s)
```

**Invariants:**
- On boot, state is always `NORMAL`. Mid-cycle restart loses the cycle (acceptable — heater_active=false, no harm).
- Only `fc_sensors` mutates state. Everyone else is a read-only consumer.
- Transition NORMAL→HEATING: set `self.sht.heater = True`, record `heat_start_ts`, publish `heater_active=true`.
- Transition HEATING→RECOVERING: set `self.sht.heater = False`, record `recovery_until = now + heater_recovery_seconds`, *keep* `heater_active=true` (consumers want one flag for "ignore readings").
- Transition RECOVERING→NORMAL: publish `heater_active=false`, log post-RH for HEAT-05 validation.

### Controller Guard Pattern

Insert in `fc_controller.control_loop` between staleness check and PID compute:

```python
# 999.34: heater-window guard
# Read heater_active from sensor_health KeyValue OR dedicated Bool topic.
# When set, hold last-published duty, freeze PID state, do NOT log "stale".
if self._heater_active:
    self._publish_duty(self._last_duty)        # republish to keep TRANSIENT_LOCAL fresh
    # Freeze integrator + derivative — composes with 999.32
    self._pid.set_auto_mode(False)             # auto_mode=False → no integration
    return                                     # skip PID step, skip ramp, skip telemetry
```

**On exit (heater_active flips false):**
- Re-engage PID with `set_auto_mode(True, last_output=self._last_duty)` (bumpless).
- **Discard 999.32 derivative filter state** (one filter time-constant of pre-window data is now stale). Recompute from first post-window sample.
- Reset `_last_humidity_timestamp` to `now` so the staleness guard doesn't fire on the first post-window reading.

### Alerter Guard Pattern

In `alerter/src/rules.js`, every rule that depends on SHT30 readings (`isRhOob`, `isSensorSilent` for sensor='sht30', `isSensorError`) gets a precondition:

```js
function isRhOob({ rh, target, band, heaterActive, recoveryUntilMs, nowMs, ... }) {
  if (heaterActive || (recoveryUntilMs && nowMs < recoveryUntilMs)) return false;
  // existing logic
}
```

The alerter subscribes to either the dedicated `Bool` topic or reads the KeyValue from `sensor_health`. **Recommendation:** dedicated Bool topic with TRANSIENT_LOCAL — alerter is JS via WS bridge, simpler than parsing DiagnosticStatus values.

### Recommended Telemetry Topics

```
fc1/sensor/sht30_heater_active : std_msgs/Bool   (TRANSIENT_LOCAL, KEEP_LAST 1)
  - true while heater on OR within recovery window
  - false otherwise
  - published on transition only (Phase 16 quiet-topic pattern)

fc1/sensor_health : diagnostic_msgs/DiagnosticStatus  (existing — extended)
  - new KeyValues: heater_active, heater_recovery_until_iso, last_heater_cycle_iso
```

### Anti-Patterns to Avoid
- **Polling `self.sht.heater` getter to determine state.** The getter reads I2C status register; it's slow and races with reads. State must be tracked in Python memory.
- **Mid-read heater toggle.** Calling `self.sht.heater = True` while a measurement command is in-flight on the same I2C transaction will likely return garbage. The scheduler must trigger between reads, not during.
- **Wall-clock-only scheduling without bounds check.** A long sleep/clock-skew event could trigger the heater multiple times. Use "next_heater_due_at" computed at last-cycle-end, not "every 24 h since now()".
- **Suppressing only `heater_active=true`, ignoring recovery window.** Live test showed RH recovery is 150 s — alerter/bridge must keep ignoring readings until `recovery_until`.
- **Relying on ROS time during recovery.** Recovery is a wall-clock duration in real seconds; ROS time is fine here, but if `use_sim_time` is ever flipped on, recovery deadline must use the same clock as the timer that fired it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Heater on/off | Direct I2C status-register manipulation | `adafruit_sht31d` `.heater` property | Vendor-tested; handles status-register read+modify+write atomically |
| Cadence scheduling | Custom thread + sleep loop | `rclpy` timer (one-shot or periodic) | Integrates with ROS shutdown, parameter reload, sim-time |
| Cron-style "nightly at 03:00 UYT" | New cron daemon | rclpy timer that wakes every minute and checks "is now within trigger window since last fire" | Single-process simplicity; no extra deploy artifact |
| Bumpless PID re-engage | Custom integrator preload math | `simple_pid.PID.set_auto_mode(True, last_output=...)` | Already used in fc_controller (line 253) — same call here |

**Key insight:** This phase has zero new libraries and zero new infrastructure. Every primitive — heater toggle, ROS timer, DiagnosticStatus, simple_pid bumpless transfer — is already in the codebase. The work is **wiring** and **state-machine discipline**, not new tech.

## Runtime State Inventory

> Rename/refactor section. This is a **feature-add**, not a rename, but several runtime systems carry assumed-truths that change:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Timescale `humidity` and `temperature` rows during heater windows would be poisoned values — must be either marked or skipped | bridge-side write gate; **decision needed**: skip-insert (gap) vs insert with `quality` column. **Recommend skip-insert** (no schema migration, gap is honest). |
| Live service config | Alerter `.env` has `SENSOR_OFFLINE_MIN`, `RH_TARGET`, `RH_BAND` (per memory `project_alerter_rh_two_source_bug` — known bug 999.22). These are env-pinned. Heater suppression must be runtime/code, NOT env. | Code change in alerter rules, no env change |
| OS-registered state | None — no systemd unit changes | Verified — fc-core unit unchanged |
| Secrets/env vars | None | — |
| Build artifacts | `fc_core` Python package — symlink-install picks up changes; no new wheel. Container rebuild needed for alerter (ESM + new rule code). | `colcon build --symlink-install --packages-select fc_core`; `docker compose up -d --build alerter` (or `bridge` if alerter is co-deployed) |

**Nothing found in category — verified by:** systemctl unit list grep (no new units); `.env.example` grep (no new keys required at minimum, optional knobs).

## Common Pitfalls

### Pitfall 1: Heater on at boot (factory default varies)
**What goes wrong:** Some SHT30 breakouts ship with heater enabled by default; a stale status register from a hung previous process can leave heater on across `rclpy` restart.
**Why it happens:** `adafruit_sht31d` initializes the device but does not unconditionally clear heater bit on `__init__` (CircuitPython library behavior).
**How to avoid:** In `fc_sensors.__init__`, explicitly set `self.sht.heater = False` after construction. Verify status. Log if it was on at startup (telemetry data).
**Warning signs:** SHT30 temperature readings 8 °C high relative to SCD41 [VERIFIED: github.com/esphome/issues/issues/1465].

### Pitfall 2: Synthetic RH dip triggers PID before guard takes effect
**What goes wrong:** Race between `self.sht.heater = True` and the controller's next `control_loop` tick. If the controller reads a poisoned `current_humidity` before the `heater_active` flag has been received via ROS topic, it acts on the dip.
**Why it happens:** Topic publication is asynchronous; the controller's local `_heater_active` flag updates only when the subscriber callback runs.
**How to avoid:** Publish `heater_active=true` BEFORE setting `self.sht.heater = True`. Wait one full `sensor_read_interval` (2 s) between the publish and the heater-on. Or, equivalently: in `fc_sensors`, suppress the *publish* of corrupted readings entirely while `heater_active` — controller never sees the dip. **Recommend the latter** — eliminates the race by construction.
**Warning signs:** Live-test 22:02 UTC PID spike 0 → 0.85 was exactly this race.

### Pitfall 3: Recovery window too short — post-recovery PID step kicks
**What goes wrong:** If `heater_recovery_seconds` < actual sensor recovery time, the first post-window reading is still slightly low, PID sees a step error, integrator + derivative both kick.
**Why it happens:** Recovery time depends on chamber bulk RH, airflow over the sensor, and *whether the membrane was actually condensed*. Live test on a non-condensed sensor showed ~150 s; a condensed sensor could be longer.
**How to avoid:** Default `heater_recovery_seconds = 180` (20 % margin over live-test 150 s). Make it a runtime ROS param. Long-term: condition-based exit ("post-pulse temp within 0.05 °C of pre-pulse AND |dRH/dt| < ε") instead of fixed timer. Defer condition-based to a follow-up phase if 180 s static works.
**Warning signs:** PID duty steps up >0.1 within 10 s of `heater_active` clearing.

### Pitfall 4: Alerter rule for "rh oob" trips on the synthetic dip
**What goes wrong:** Alerter receives the corrupt RH value (or the data gap) and fires "RH below target" SMS to farmer in the middle of the night.
**Why it happens:** Alerter rules don't yet read heater state.
**How to avoid:** Wire `heater_active` into every alerter rule precondition. Also: skip-insert at bridge means alerter receives gap, not value — but `isSensorSilent` would then fire for sensor-stale. Both rules need the guard.
**Warning signs:** Phase 999.34 ships, farmer gets a 03:01 UYT alert next morning.

### Pitfall 5: Controller restart mid-cycle leaves duty stuck high
**What goes wrong:** Controller dies during HEATING/RECOVERING, restarts. New controller has no memory of `_last_duty`; defaults to 0.0; humidifier turns off; RH dips for real.
**Why it happens:** `_last_duty` is in-process Python state.
**How to avoid:** On controller boot, NORMAL is the only safe initial state. Heater_active topic with TRANSIENT_LOCAL means the new controller will receive the *current* heater state on subscribe. If `heater_active=true` at boot: enter the controller's heater-guard branch, but with `_last_duty=0` (unknown). The chamber takes a small RH hit (recovery is 3 min max) — acceptable. Document this.
**Warning signs:** Restart soak test shows duty 0 → 1 oscillation post-restart.

### Pitfall 6: Heater state lost on `rclpy` shutdown — heater stuck on
**What goes wrong:** SIGTERM during HEATING leaves `self.sht.heater = True` in the I2C device. Next process boot reads inflated temperatures until it explicitly clears.
**Why it happens:** No `try/finally` around heater toggle.
**How to avoid:** `try/finally` in scheduler, plus the explicit `self.sht.heater = False` in `__init__` (Pitfall 1 mitigation). Belt and suspenders.
**Warning signs:** Cold-start temperature anomaly logged in journal.

## Code Examples

Verified patterns from existing codebase:

### Heater toggle (driver surface)
```python
# Source: github.com/adafruit/Adafruit_CircuitPython_SHT31D/blob/main/adafruit_sht31d.py
self.sht.heater = True   # writes _SHT31_HEATER_ENABLE (0x306D)
# read-back from status register:
if self.sht.heater:      # bit 0x2000 of status reg
    ...
self.sht.heater = False  # writes _SHT31_HEATER_DISABLE (0x3066)
```

### Bumpless PID re-engage (already in fc_controller line 252-256)
```python
def _engage_pid_bumplessly(self):
    self._pid.set_auto_mode(True, last_output=0.15)
    self._pid_engaged = True
```
Reuse with `last_output=self._last_duty`.

### TRANSIENT_LOCAL Bool publisher pattern (already in fc_controller line 105-115)
```python
actuator_qos = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)
self._heater_active_pub = self.create_publisher(
    Bool, 'fc1/sensor/sht30_heater_active', actuator_qos
)
```

### Quiet-topic state-change publish (Phase 16 pattern, already in fc_controller line 282-316)
Publish only when state transitions, not every tick. Cuts topic noise; TRANSIENT_LOCAL means late-joiners still see current value.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Treat SHT3x as fire-and-forget | Periodic heater for creep mitigation | Sensirion design guidance, well-established | Necessary for sustained > 90 % RH applications |
| Hand-rolled I2C heater command | `adafruit_sht31d.heater` property | CircuitPython 1.0+ (~2018) | One line, vendor-tested |
| SHT3x for high-RH apps | SHT4x for new designs | Transition guide 2023 [CITED: sensirion.com transition_sht3x_sht4x] | SHT4x has more powerful heater + condensation removal; **not relevant** here — we have SHT30 hardware in service, not designing new |

**Deprecated/outdated:**
- Continuous heater-on as creep mitigation: rejected — corrupts every reading. Periodic only.
- Cross-sensor majority-vote for sanity check during heat: speculative, defer to multi-sensor phase.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x (already in use; ament_python integration) |
| Config file | `src/chambers/fc-core/test/conftest.py` |
| Quick run command | `pytest src/chambers/fc-core/fc_core/test/test_sensors.py -x` |
| Full suite command | `colcon test --packages-select fc_core` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HEAT-01 | Heater fires on schedule | unit (mocked clock + mocked SHT) | `pytest .../test_sensors.py::test_heater_fires_at_scheduled_time -x` | ❌ Wave 0 |
| HEAT-01 | Heater state-machine transitions | unit | `pytest .../test_sensors.py::test_heater_state_machine -x` | ❌ Wave 0 |
| HEAT-03 | Controller holds last-duty during heater window | unit | `pytest .../test_controller.py::test_holds_duty_during_heater -x` | ❌ Wave 0 |
| HEAT-03 | PID integrator does NOT accumulate during window | unit | `pytest .../test_controller.py::test_pid_frozen_during_heater -x` | ❌ Wave 0 |
| HEAT-03 | Bumpless re-engage post-recovery | unit | `pytest .../test_controller.py::test_bumpless_re_engage_post_heater -x` | ❌ Wave 0 |
| HEAT-04 | Alerter rules suppress during window | unit (JS, vitest) | `npm test -- rules.heater.test.js` (alerter pkg) | ❌ Wave 0 |
| HEAT-05 | Synthetic dip → no PID spike (integration) | integration | manual replay of fixture from 2026-05-04 22:02 UTC | partial |
| HEAT-06 | 30-day soak SHT30↔SCD41 delta | manual / Timescale query | runbook only | manual-only |

### Sampling Rate
- **Per task commit:** `pytest src/chambers/fc-core/fc_core/test/test_sensors.py src/chambers/fc-core/fc_core/test/test_controller.py -x` (~10 s)
- **Per wave merge:** `colcon test --packages-select fc_core && (cd src/agents/alerter && npm test)` (~60 s)
- **Phase gate:** Full suite green + replay of 22:02 UTC live-test fixture showing duty stays flat through the synthetic dip.

### Wave 0 Gaps
- [ ] `src/chambers/fc-core/fc_core/test/test_sensors.py` — needs heater state-machine unit tests + mocked I2C
- [ ] `src/chambers/fc-core/fc_core/test/test_controller.py` — needs heater-guard branch tests
- [ ] `src/agents/alerter/test/rules.heater.test.js` — needs alerter-rule heater-suppression tests
- [ ] Test fixture: 22:02 UTC live-test capture (5-min Timescale slice around the synthetic pulse) saved as a replay file for HEAT-03 integration test
- [ ] Mocked-clock helper for ROS-time advancement (already exists in test_controller.py line 15-21 — reuse)

## Telemetry Contract

### Outgoing (from fc_sensors)
| Topic | Type | QoS | Semantics |
|-------|------|-----|-----------|
| `fc1/sensor/sht30_heater_active` | `std_msgs/Bool` | TRANSIENT_LOCAL, KEEP_LAST 1, RELIABLE | true while heater on OR recovery window; false otherwise. Published on transitions only. |
| `fc1/sensor_health` | `diagnostic_msgs/DiagnosticStatus` | existing | Adds KeyValues: `heater_active`, `heater_recovery_until_iso`, `last_heater_cycle_iso`, `last_heater_pre_rh`, `last_heater_post_rh` |

### Outgoing — what to suppress during window
| Topic | Action |
|-------|--------|
| `fc1/temperature` (slot-1, frame_id='sht30') | **Skip publish** during heater_active. Slot-1 falls through to SCD41 only if SCD41 is fresh — preserves Phase 26 fallback semantics, but fc_controller's heater guard fires first. |
| `fc1/humidity` (slot-1, frame_id='sht30') | **Skip publish** during heater_active. |
| `fc1/temperature_2`, `fc1/humidity_2` | Continue publishing — SCD41 unaffected by SHT30 heater. |

### Incoming (consumers)
| Consumer | Subscribes to | Behavior |
|----------|---------------|----------|
| `fc_controller` | `fc1/sensor/sht30_heater_active` | Hold last-duty, freeze PID, skip ramp/telemetry |
| alerter (via bridge) | same (via WS) | Skip rh-oob, sensor-silent (sht30), sensor-error rules |
| bridge → Timescale | same | Skip insert during window — chart shows gap |
| Mission Control plugin | bridge republish | Render vertical-line annotation at heater_start_ts |
| 999.27 derivations | same | VPD, dew_point, humidity_rate must skip the gap (no interpolation across) |

## Calibration / Validation Metric

The proof the heater is doing real work is **indirect** — there's no reference RH meter on FC-1. Two long-run signals:

1. **SHT30 ↔ SCD41 RH delta over time.**
   - Hypothesis: untreated SHT30 drifts positive (creep) over weeks; SCD41 doesn't.
   - With nightly heater: delta should stay flat or narrow.
   - Without heater (current state): delta should widen.
   - Query: `select date_trunc('day', ts), avg(sht30_rh - scd41_rh) from humidity_dual where ...`
   - Target: |delta| < 1 % sustained over 30 days.

2. **Pre-heat vs post-heat RH at the heater event itself.**
   - Log `last_heater_pre_rh` (RH 30 s before heat-on) and `last_heater_post_rh` (RH 30 s after recovery_until).
   - In a non-condensed sensor: pre ≈ post (within 0.1 %). HEAT-05.
   - In a condensed sensor: post < pre (heater removed real water). The drop magnitude is the "creep dose" being cleared each cycle.

Log both to `fc1/sensor_health` KeyValues + a dedicated long-running tag in Timescale (`heater_cycle_log` table or a tagged event).

## Sequencing with 999.32

Hard constraints:

- **999.32 + 999.34 must ship as a pair**, OR 999.34 must include inline derivative-state reset.
- The live-test 22:02 UTC failure mode was: synthetic falling RH → derivative term saw a large negative dRH/dt → P+I+D contributions stacked → duty 0 → 0.85.
- Even with the heater_active controller guard preventing the duty publish during the window, **post-window** the derivative term will see the RH "jump back up" as a transient and react. 999.32's filter (τ ≈ 10 s) was designed to dampen real RH transients; it would dampen this artifact too — but only after one filter time-constant. A clean recovery means *resetting* the filter state on heater_active falling edge, not just relying on filtering.

**If 999.32 is not yet shipped when 999.34 plans:** the plan must include a Wave that adds a manual derivative-reset hook (`self._pid._last_input = current_rh; self._pid._last_output = self._last_duty`) at the heater_active falling edge. Crude but correct.

**If 999.32 ships first:** 999.34's plan is simpler — call the 999.32 reset method on falling edge.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 03:00 UYT is "chamber quiet, low duty, no farmer attention" — best cycle time | Cadence default | Low — farmer can change schedule in config; first 30-day soak will validate |
| A2 | `heater_recovery_seconds = 180` is sufficient post-condensed-sensor (live test was on non-condensed sensor) | Pitfall 3 | Medium — first nightly cycle on production sensor may show longer recovery; param is runtime-tunable |
| A3 | RH delta SHT30↔SCD41 is the right long-run validation metric | Validation metric | Medium — SCD41 RH clips at 100 %, so the metric only works in the < 100 % regime; in saturating conditions, the comparison is uninformative |
| A4 | Skip-insert at bridge is preferable to insert-with-quality-flag in Timescale | Telemetry / Timescale | Low — gap is honest and matches Phase 26 freshness pattern; reversible decision |
| A5 | adafruit_sht31d `.heater` property persists across `__init__` if device wasn't power-cycled (i.e., heater could be on at boot from a prior crash) | Pitfall 1, 6 | Low — explicit `False` write at __init__ makes it irrelevant |
| A6 | Wall-clock cadence (cron-style "nightly at 03:00") is what the farmer wants vs interval-based ("every 24h since boot") | Discretion / cadence | Low — predictable schedule is operator-friendly; trivial to change |
| A7 | 1 s pulse is enough to clear membrane condensation in this regime | Heater duration | **Medium-HIGH** — Sensirion guidance is 1–3 s; live test was 3 s. If 1 s doesn't clear creep, validation metric A3 will show no narrowing of SHT30↔SCD41 delta over 30 days. Mitigation: param is runtime-tunable; bump to 2 s or 3 s if first soak shows no effect. |
| A8 | Existing fc-core test infrastructure (pytest + ament_python + mocked clock helper) accommodates I2C-mocking the SHT30 heater | Wave 0 gaps | Low — `test_sensors.py` already exists; pattern is `unittest.mock.patch` on the SHT object |

**Note:** A7 is the most material assumption. If the planner has any reason to think the membrane creep on FC-1 is severe (e.g., sensor has been at 95 % for months), bias toward **2 s default pulse** and re-evaluate after first cycle.

## Open Questions

1. **Should bridge skip Timescale insert or insert-with-quality-flag during heater window?**
   - What we know: skip-insert is simpler, preserves Phase 26 gap-over-noise principle (memory `feedback_gap_over_noise`).
   - What's unclear: whether 999.27 derivations or future analytics want to see "the corrupted readings" for diagnostics.
   - Recommendation: skip-insert. Log heater events to a separate `heater_cycle_log` table or as Mission Control event annotations; raw poisoned readings are not useful.

2. **Should we add a condition-trigger ("RH stuck > 95.5 % for > 24 h") in this phase or defer?**
   - What we know: nightly fixed schedule is the simple v1.
   - What's unclear: whether farmer wants the "if drift, fix it" behavior, or trusts the nightly schedule.
   - Recommendation: defer. Ship nightly first. Watch SHT30↔SCD41 delta. Add condition-trigger only if nightly is insufficient.

3. **Does the heater perturb adjacent SCD41 readings via I2C bus or thermal coupling?**
   - What we know: physically separate sensor packages; thermal coupling is bulk-air-mediated (negligible at 0.5–1.5 °C die rise on a sub-cm die for 1 s).
   - What's unclear: whether the farmer's mounting puts SHT30 and SCD41 in close enough proximity for radiative coupling.
   - Recommendation: log SCD41 readings during the window; first 30-day soak will reveal any anomaly.

4. **Failure mode if `self.sht.heater = True` raises (I2C glitch)?**
   - What we know: must catch and stay in NORMAL.
   - What's unclear: should we retry next minute, or wait for next scheduled cycle (24 h)?
   - Recommendation: log + retry next 10-min boundary, max 3 attempts, then wait for next nightly slot.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `adafruit_sht31d` | fc_sensors heater toggle | ✓ | already pinned in fc-core | — |
| `simple_pid` (vendored) | fc_controller bumpless re-engage | ✓ | `fc_core/vendor/simple_pid` | — |
| `rclpy` jazzy | timer + topics | ✓ | jazzy | — |
| pytest + ament_python | unit tests | ✓ | existing | — |
| Node + vitest (alerter) | alerter rule tests | ✓ | existing | — |
| fc1 hardware | live deploy | ✓ (per memory `feedback_ssh_tailscale` use 172.16.10.5) | — | — |

No missing dependencies, no fallbacks needed.

## Project Constraints (from CLAUDE.md)

- Build via colcon; symlink-install for Python dev. Plan must include `colcon build --symlink-install --packages-select fc_core` step.
- Tests via `colcon test --packages-select fc_core` and direct `pytest`. Both should pass.
- ROS_DOMAIN_ID=69 — no impact, but topic discovery test must run in the same domain.
- Pi deploy is git, branch `fc1/prod` (memory `feedback_deploy_method`). Plan's deploy wave must push to fc1/prod, then `deploy.sh` on fc1.
- Diff repo vs Pi systemd before changes (memory `feedback_diff_repo_vs_pi_systemd`). No systemd changes expected in this phase, but verify.
- Verify runtime compose, not plan target (memory `feedback_verify_runtime_compose`). Alerter rebuild applies to the live alerter container at repo root, NOT `src/docker-compose.yml`.
- Don't disable interfaces over SSH (memory `feedback_no_interface_down`). Not applicable; no network changes.
- Run verifications myself (memory `feedback_run_verifications_yourself`). Verify branch will run pytest, npm test, and Timescale queries directly.
- No co-author trailer on commits (memory `feedback_no_coauthor`).

## Sources

### Primary (HIGH confidence)
- `adafruit_sht31d` library source — github.com/adafruit/Adafruit_CircuitPython_SHT31D — heater property semantics
- Existing fc-core code — fc_sensors.py, fc_controller.py, fc_config.yaml — patterns reused verbatim
- Existing alerter code — `src/agents/alerter/src/rules.js` — rule guard insertion points
- ROADMAP.md entry 999.34 with live-test data (2026-05-04 22:02 UTC measurements)
- Existing test infrastructure — `src/chambers/fc-core/fc_core/test/test_controller.py` (mocked-clock pattern)

### Secondary (MEDIUM confidence)
- Sensirion SHT3x-DIS Datasheet v7 (Dec 2022): https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf — referenced but PDF not text-extracted in this session; quoted figures from web summaries
- Sensirion SHT3x ↔ SHT4x Transition Guide (Nov 2023): https://sensirion.com/resource/application_note/transition_sht3x_sht4x — confirms creep at sustained > 90 % RH and periodic-heater mitigation pattern

### Tertiary (LOW confidence)
- ESPHome issue #1465 — heater-on-by-default reports, anecdotal: https://github.com/esphome/issues/issues/1465
- Adafruit forum thread on heater use: https://forums.adafruit.com/viewtopic.php?t=184587 (403 on fetch)
- Various distributor wiki pages on SHT30 heater function (DFRobot, etc.) — corroborate creep description

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every primitive is already in the codebase; zero new dependencies.
- Architecture (state machine + controller guard + alerter guard): HIGH — patterns mirror Phase 16, Phase 26, Phase 27 exactly.
- Pitfalls: HIGH for #1, #2, #4, #5, #6 (all derived from observed FC-1 behavior or specific code-path analysis); MEDIUM for #3 (recovery duration is from one live test).
- Cadence default (nightly 03:00): MEDIUM — operator preference, easily changed.
- Heater pulse duration (1 s): MEDIUM — datasheet allows; live test was 3 s; A7 flagged as material.
- Long-run efficacy (HEAT-06): LOW — only proven by 30-day soak. This is a known unknown.

**Research date:** 2026-05-04
**Valid until:** 2026-06-04 (30 days; revisit if SHT30 driver upgrades or if Phase 28 mode primitive lands first)

Sources:
- [Sensirion SHT3x-DIS Datasheet](https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf)
- [Sensirion SHT3x → SHT4x Transition Guide](https://sensirion.com/resource/application_note/transition_sht3x_sht4x)
- [Adafruit_CircuitPython_SHT31D](https://github.com/adafruit/Adafruit_CircuitPython_SHT31D)
- [CircuitPython SHT31D API docs](https://docs.circuitpython.org/projects/sht31d/en/latest/api.html)
- [ESPHome heater-default issue #1465](https://github.com/esphome/issues/issues/1465)
- [Adafruit forum: SHT3x heater use](https://forums.adafruit.com/viewtopic.php?t=184587)
