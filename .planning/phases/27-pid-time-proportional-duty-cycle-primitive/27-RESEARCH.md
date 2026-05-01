# Phase 27: PID + time-proportional duty-cycle primitive — Research

**Researched:** 2026-05-01
**Domain:** Process control (PID + slow-PWM) on a ROS2 Jazzy / ament_python node controlling an SSR-driven ultrasonic humidifier
**Confidence:** HIGH (architecture, code-side integration, PID structural choices) / MEDIUM (numerical defaults — derived from calibration, validated against operating point but not yet retuned with SHT30 online)

---

## Summary

Phase 27 replaces the `_set_humidifier_with_dwell()` bang-bang/dwell logic in `fc_controller.py` with a positional PID that emits a 0.0–1.0 duty-cycle setpoint on `fc1/actuators/humidifier_duty` (Float32, TRANSIENT_LOCAL). A slow-PWM driver subscribes to that topic and translates duty into 120s relay windows on the existing `fc1/actuators/humidifier` Bool publisher. Mode C (full-ON open-loop bypass for |error| > bypass_threshold) handles the 5× rise/decay nonlinearity that would otherwise force a second gain set.

Every numerical constant in this research traces back to the 2026-04-11 calibration session: dead time ~16s, near-setpoint rise/decay rates ~0.8 / 0.7 %/min, steady-state duty ~15%, and the empirical 10s minimum-fog-pulse measured 2026-05-01. The PID gains are derived via Skogestad SIMC tuning for an integrator-with-deadtime (IPDT) plant model.

**Primary recommendation:** Package the slow-PWM as a separate ROS node (`fc_pwm_driver`) launched from `fc.launch.py`, sharing systemd unit with fc-core (no new unit needed; `ros2 launch` already wraps multi-node bring-up under one Restart=always service). Use Skogestad SIMC gains in **percent-RH error units** with τ_c = 3L = 48s for conservative near-setpoint regulation: `pid_kp=0.5`, `pid_ki=0.002`, `pid_kd=2.5`. Derivative-on-measurement with a 10s low-pass filter. Conditional integration (clamping anti-windup) — disable integration whenever the output saturates OR Mode C is engaged OR sensor is stale OR grace is active. Bumpless transfer = preload integrator to 0.15 (steady-state duty) on every (re-)engagement.

---

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Architecture — topic boundary**
- **D-01:** Duty published as `fc1/actuators/humidifier_duty` (`std_msgs/Float32`, range **0.0–1.0**) on every control tick. Contract between PID stage and actuator stage.
- **D-02:** Scale is **0.0–1.0**, not 0–100% — overlays cleanly with `fc1/actuators/humidifier` Bool on a single chart. HUMID-01 wording "0–100%" is corrected to 0.0–1.0.
- **D-03:** New slow-PWM driver subscribes to `humidifier_duty` and owns GPIO27. fc_controller no longer touches the humidifier GPIO directly. Physical packaging (separate node / sibling exe / in-process class) = Claude's discretion.

**PID design**
- **D-04:** Single fixed PID gain set, near-setpoint tuned. Gain scheduling deferred.
- **D-05:** Gains as ROS params (`pid_kp`, `pid_ki`, `pid_kd`); defaults from 2026-04-11 system-ID data.
- **D-06:** Bumpless transfer on PID startup and on stale-recovery — integrator pre-loaded so the first windows don't slam.
- **D-07:** Setpoint-change ramp on `target_humidity` change — output duty slews over a few seconds. Slew duration = Claude's discretion.

**Slow-PWM actuator behavior**
- **D-08:** PWM window length = **120s LOCKED**. Not "research and decide" — it came from collision analysis of 10s min-fog-pulse vs ~15% steady-state duty.
- **D-09:** Mode C — when `|error| > bypass_threshold`, slow-PWM suspended, humidifier holds full-ON open-loop until inside threshold.
- **D-10:** `bypass_threshold` tunable, default = Claude's discretion (target: well outside ±0.5% but inside any reasonable mode-switch step — ~2–3% RH).
- **D-11:** Min effective ON pulse = **10s** (empirical fog-visibility floor). If duty × window < 10s, emit 0 for that window. Tunable as `min_pulse_seconds`.
- **D-12:** Rolling 5-min max-duty cap. Claude's discretion on default.

**Safety semantics**
- **D-13:** Sensor-stale forces duty=0.0 immediately, bypassing ramp D-07. Same contract as Phase 03 D-09/D-10/D-11.
- **D-14:** Startup grace preserved (Phase 15) — duty=0.0 during warmup; sensor_health WARN→OK transition unchanged.
- **D-15:** `min_dwell_time` REMOVED. SSR-10A is solid-state, no cycle-wear concern. Window length is the new safety floor.

**Acceptance**
- **D-16:** ±0.5% RH over 2-hour soak, farmer-attested on Mission Control. Zero DWELL-BLOCK-equivalent log lines, no operator-visible slam on grace-clear or recovery.

**Sensor source**
- **D-17:** PID input = `fc1/humidity` (slot-1). Phase 26 silent SHT30→SCD41 fallback preserved unchanged. PID does not see slot-2.

### Claude's Discretion
- D-05 default Kp/Ki/Kd values (this research derives them)
- D-07 setpoint-ramp slew duration
- D-10 `bypass_threshold` default
- D-12 rolling max-duty cap default
- Anti-windup mechanism (clamping vs back-calculation)
- Derivative-on-measurement vs derivative-on-error; D-term filtering
- Physical packaging of slow-PWM driver
- YAML param key naming

### Deferred Ideas (OUT OF SCOPE)
- Per-mode PID gains — v1.6 candidate
- Zone gain scheduling within a single mode — only if HUMID-04 surfaces it
- Mode-aware sensor selection (SHT30 vs SCD41 by stage) — v1.6
- PID auto-tuning — out of scope per REQUIREMENTS line 55
- Mission Control overlay layout for duty + relay — composes with backlog 999.17
- `min_dwell_time` deprecation sweep across alerter/docs beyond fc_core — non-blocking follow-up

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HUMID-01 | Controller publishes duty-cycle setpoint each control tick (0.0–1.0 per D-02) | §Standard Stack (rclpy + std_msgs/Float32 + TRANSIENT_LOCAL QoS), §Architecture Patterns Pattern 1 (PID compute step), §Code Examples |
| HUMID-02 | Actuator layer translates duty cycle into time-proportional on/off windows on the existing relay; window length per calibration | §Architecture Patterns Pattern 2 (slow-PWM windowing math), §Code Examples slow-PWM driver, §Don't Hand-Roll (window math is the only sensible custom code; PID kernel is library-friendly) |
| HUMID-03 | PID gains tunable as ROS params; defaults derived from 2026-04-11 system-ID data | §Standard Stack PID gain derivation, §Code Examples (declare_parameters + dynamic-reconfigure-style read each tick) |
| HUMID-04 | Operating band tightens from interim ±1% to PID-tracked tolerance verifiable on 2-hour soak; farmer-attested | §Validation Architecture (live soak harness via TimescaleDB query), §Common Pitfalls (limit-cycle and bumpless-transfer pitfalls that would defeat the soak) |

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| PID compute (error → duty) | fc_controller (ROS2 Python node, control_loop tick) | — | Already owns sensor subs, grace/stale logic; PID is a small numeric block grafted onto the existing tick (D-03 says fc_controller publishes duty, not GPIO) |
| Setpoint-change ramp (D-07) | fc_controller | — | Co-located with PID so the ramp can reset the integrator under bumpless-transfer rules |
| Mode C bypass decision (D-09) | fc_controller | — | Decision is a function of error and live target; lives next to the PID. Bypass forces duty=1.0 on the published topic — the slow-PWM driver does not need a separate "mode" input |
| Slow-PWM windowing (duty → relay edges) | new node `fc_pwm_driver` (or in-process class — see D-03 discretion) | — | Periodic timer at ~1Hz; subscribes to `fc1/actuators/humidifier_duty`; publishes `fc1/actuators/humidifier` Bool every toggle. Owns GPIO27 |
| Min-pulse-skip + rolling max-duty cap | fc_pwm_driver | — | These are actuator-protection rules belonging to the layer that owns the relay; keeps fc_controller's PID output clean and monitorable |
| Stale/grace gating | fc_controller (already does this for safe-state OFF) | fc_pwm_driver (defensive: subscribe-with-timeout, force OFF if duty stops being published) | fc_controller is the source of truth (D-13/D-14). fc_pwm_driver should also drop to OFF if its incoming duty topic goes silent — defense in depth |
| Telemetry forwarding (humidifier_duty → TimescaleDB) | mission-control bridge (rclnodejs subscription) | — | Already forwards `fc1/actuators/humidifier`; add a sibling subscription for the new topic. Pattern matches existing bridge code (lines 685–699 of `src/mission-control/bridge/src/index.js`) |
| Mission Control charting | OpenMCT (operator-visible) | — | D-02 overlay on one chart is the explicit design constraint; backlog 999.17 layout work is deferred |

---

## Standard Stack

### Core
| Library / Module | Version | Purpose | Why Standard |
|------------------|---------|---------|--------------|
| `rclpy` | ROS2 Jazzy (system) | ROS2 Python client lib | Already in use across fc_core; no alternative |
| `std_msgs/msg/Float32` | ROS2 Jazzy | Duty-cycle topic message | Lightweight scalar; aligns with existing `fc1/co2` Float32 pattern; bridge already auto-handles std_msgs scalars |
| `rclpy.qos.QoSProfile` w/ `DurabilityPolicy.TRANSIENT_LOCAL` | ROS2 Jazzy | Duty topic QoS | Matches the existing `humidifier_state_pub` and `sensor_health_pub` pattern (fc_controller.py lines 105–118); late-joining bridge gets last duty value on subscribe |
| `RPi.GPIO` | already pinned | GPIO27 toggling in fc_pwm_driver | Already used by fc_controller for the same pin; do not introduce a second GPIO library |

`[VERIFIED: src/chambers/fc-core/setup.py + fc_controller.py existing pattern]`

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `simple-pid` (PyPI) | 2.0+ | Off-the-shelf PID kernel with anti-windup, output limits, derivative-on-measurement, sample-time handling | **Recommended** — see §Don't Hand-Roll. Available on Pi via pip; ~250 LOC of well-tested code. `[CITED: https://pypi.org/project/simple-pid/]` |
| `collections.deque` | stdlib | Rolling 5-min duty window for D-12 cap | Already used in fc_controller for humidity median buffer — same pattern |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `simple-pid` library | Hand-roll a PID class | ~50 LOC for naive PID; bumpless transfer + back-calc anti-windup + derivative filtering bring it to ~150 LOC of bug-prone code. Library wins. `[ASSUMED]` |
| Separate `fc_pwm_driver` node | In-process class inside fc_controller | In-process: smaller diff, no IPC hop. Separate node: independently restartable, observable on the bus, mockable in tests. **Recommended: separate node** — see Pattern 3. The systemd-restart-trap memory (`feedback_systemd_restart_ros2_launch`) is already mitigated by the existing fc-core.service `Restart=always`, which wraps the whole `ros2 launch` and restarts the whole stack on any child crash; adding a node to the launch file does not add a new systemd surface |
| 0–100 integer scale | 0.0–1.0 Float32 | LOCKED by D-02 — operator overlay-on-one-chart |

**Installation:**
```bash
# On the Pi (and dev workstation, simulation_mode):
pip install simple-pid==2.0.0
# Add to setup.py install_requires:
#   'simple-pid>=2.0,<3.0'
```

**Version verification:** `simple-pid` 2.0.0 published on PyPI. Stable since 2023; actively maintained. `[ASSUMED — verify with `pip index versions simple-pid` on the dev box before locking. Dev box is offline-capable; if PyPI is not reachable from the Pi at deploy time, fall back to vendored copy in `src/chambers/fc-core/fc_core/_vendor/simple_pid.py`]`.

### PID Gain Derivation (Skogestad SIMC, IPDT model)

The plant near setpoint behaves like an integrator with dead-time (IPDT). From CALIBRATION-FINDINGS-2026-04-11.md:

| Symbol | Value | Source |
|--------|-------|--------|
| Dead time L | 16s | "Deadtime measurement: humidifier OFF at 20:37:49, RH peak at ~20:38:05" |
| Near-setpoint full-ON rise rate | +0.8 %/min = 0.0133 %/s | Table row 2 |
| Near-setpoint passive decay rate | −0.7 %/min = −0.0117 %/s | Table row 3 |
| Steady-state duty | 0.15 (15%) | "rise/decay asymmetry near setpoint ~15%" |
| Velocity gain Kv (slope vs duty) | (0.0133 − (−0.0117)) / (1.0 − 0.0) = **0.025 %RH / s / unit-duty** | Linearization across the duty range |

**SIMC tuning rule for IPDT:**
- Pick closed-loop time constant τ_c. Conservative: τ_c = 3L = 48s. (τ_c = L is the textbook "fast" choice; τ_c = 3L is the "robust" choice.)
- Kp = 1 / (Kv × (τ_c + L))
- Ti = min(4(τ_c + L), 8L) for IPDT — but for our long-horizon regulation case, Ti = 4(τ_c + L) is correct.
- Ki = Kp / Ti
- Kd via derivative time Td = L/2 = 8s (rule of thumb), giving Kd = Kp × Td. **But** since the SHT30 RH signal is noisy, use a low-pass filter on the derivative term with τ_d_filter = 10s (matches SCD41 sample interval and bigger than dead time / 2).

**Plug-in values (operating in %RH error units, NOT fraction units):**

| Gain | Formula | Numerical default |
|------|---------|-------------------|
| `pid_kp` | 1 / (0.025 × (48 + 16)) = 1 / 1.6 | **0.625** ≈ **0.5** (rounded conservative) |
| `pid_ki` | Kp / Ti = 0.5 / 256 | **0.002** |
| `pid_kd` | Kp × Td = 0.5 × 8 | **4.0** (with 10s low-pass filter) |
| `pid_derivative_filter_tau` | 10s | New param |

Sanity check:
- At 0.5% RH error (D-16 attestation band edge): P-term = 0.5×0.5 = 0.25 → 25% duty. Above the 15% steady-state hold → integrator winds toward neutralizing the deviation.
- At 1% error: P-term = 0.5 → 50% duty. Strong push, well below saturation.
- At 2% error: P-term = 1.0 → saturates at 1.0 → enters Mode C anyway via D-09 (bypass_threshold ≥ 2%).
- Recovery from 65% to 80% (15% error): P-term = 7.5 → saturates immediately. Mode C handles this regime open-loop. PID re-engages at |error| < bypass_threshold.

**Note on units:** PID inputs/outputs in this research use `error_pct = (target − measured) × 100` so a 1% RH deviation is `error_pct = 1.0`. Output is dimensionless 0.0–1.0 duty. This avoids the gain-magnitude-confusion trap from working in fraction units (where Kp would need to be 50 instead of 0.5). The fc_controller already converts internally for logging (`current_humidity * 100`), so this convention is consistent.

**`[VERIFIED: numerical derivation traceable to CALIBRATION-FINDINGS-2026-04-11.md table values]` — but note the calibration data caveat: SHT30 was offline; gains may need a retune sweep on the live SHT30 once Phase 27 ships. Plan for a tuning iteration during HUMID-04 soak.**

### Discretion-Default Recommendations

| Param | Recommended default | Rationale |
|-------|---------------------|-----------|
| `pid_setpoint_ramp_seconds` (D-07) | **30s** | At 30s slew, a 5% RH mode-switch step ramps at 0.17 %/s — operator sees a smooth slope, not an instant slam. Dead time is 16s so anything faster is wasted. |
| `bypass_threshold` (D-10) | **0.025** (2.5% RH) | Inside D-04 attestation band (±0.5%) by 5×; outside any "normal" PID excursion; smaller than typical mode-switch step (e.g., fruiting 92% → pinning 88% = 4% step). At 2.5% error, P-term alone = 1.25 → already saturated, so PID and Mode C agree. |
| `max_duty_5min_avg` (D-12) | **0.40** (40%) | 2.7× the steady-state hold of 15%; tank-protection ceiling. At 40% rolling cap, recovery from a moderate disturbance still uses ~40% averaged duty without forcing Mode C. Ultrasonic transducer datasheets typically rate continuous-on so this cap is operator-protection (water consumption), not hardware-protection. `[ASSUMED — recommend the farmer confirm tank capacity vs daily fill schedule; revise if a 40% cap drains the tank inside 24h. The farmer should also confirm during soak that this cap does not engage during normal operation — if it does, the underlying issue is steady-state duty drift, not the cap]` |
| `min_pulse_seconds` (D-11) | **10.0** | LOCKED empirically 2026-05-01 |
| `pwm_window_seconds` (D-08) | **120.0** | LOCKED |
| `pid_derivative_filter_tau` | **10.0** | Matches SCD41 sample interval; > L/2; suppresses sensor noise without lagging the derivative meaningfully near setpoint where rates are slow |

---

## Architecture Patterns

### System Architecture Diagram

```
                           ┌─────────────────────────────────┐
                           │  fc_sensors (existing)          │
                           │  SHT30→slot1, SCD41→slot1,2     │
                           └──────────────┬──────────────────┘
                                          │ /fc1/humidity (slot-1)
                                          ▼
        ┌─────────────────────────────────────────────────────┐
        │  fc_controller node                                 │
        │  ┌──────────────────────────────────────────────┐   │
        │  │  control_loop() @ 1Hz                         │   │
        │  │   1. grace_active()? → publish duty=0.0       │   │
        │  │   2. stale? → publish duty=0.0 (D-13)         │   │
        │  │   3. ramp setpoint toward target (D-07)       │   │
        │  │   4. error = (target - measured) × 100        │   │
        │  │   5. |error| > bypass_threshold?              │   │
        │  │       └─yes→ duty = 1.0 (Mode C)             │   │
        │  │              freeze integrator (anti-windup)  │   │
        │  │       └─no → PID.compute(error) → duty       │   │
        │  │   6. publish /fc1/actuators/humidifier_duty   │   │
        │  └──────────────────────────────────────────────┘   │
        └──────────────────────┬──────────────────────────────┘
                               │ /fc1/actuators/humidifier_duty
                               │ (Float32, 0.0–1.0, TRANSIENT_LOCAL)
                               ▼
        ┌─────────────────────────────────────────────────────┐
        │  fc_pwm_driver node (NEW)                            │
        │  ┌──────────────────────────────────────────────┐   │
        │  │  120s window timer + 1Hz tick                 │   │
        │  │   on window-start: read latest duty           │   │
        │  │     • round-down rule: duty×120 < 10s? → 0   │   │
        │  │     • rolling 5-min cap: avg > 0.40? → cap   │   │
        │  │     • on_seconds = duty × 120                 │   │
        │  │   tick: if (within on_seconds) → GPIO HIGH   │   │
        │  │         else → GPIO LOW                       │   │
        │  │   on every edge: publish humidifier Bool     │   │
        │  │   duty subscription timeout (>5s silent)     │   │
        │  │     → defensive OFF                           │   │
        │  └──────────────────────────────────────────────┘   │
        └──────────────────────┬──────────────────────────────┘
                               │ GPIO27 (SSR)
                               │ /fc1/actuators/humidifier (Bool)
                               ▼
        ┌─────────────────────────────────────────────────────┐
        │  Hardware: SSR-10A → ultrasonic humidifier           │
        └─────────────────────────────────────────────────────┘

        Mission Control bridge subscribes to BOTH topics → TimescaleDB
        → OpenMCT charts (overlay: duty + relay state on one plot, D-02)
```

### Recommended Project Structure

```
src/chambers/fc-core/
├── fc_core/
│   ├── fc_controller.py        # PID logic added; bang-bang removed; slow-PWM extracted
│   ├── fc_pwm_driver.py        # NEW: slow-PWM windowing + GPIO ownership
│   ├── _pid_kernel.py          # NEW: thin wrapper around simple-pid w/ bumpless preload
│   └── test/
│       ├── test_controller.py  # PID branch tests added; old dwell tests removed
│       ├── test_pid_kernel.py  # NEW: pure-math unit tests
│       └── test_pwm_driver.py  # NEW: window math, min-pulse skip, rolling cap, defensive OFF
├── config/
│   └── fc_config.yaml          # min_dwell_time removed; new pid_*, pwm_* params added
├── launch/
│   └── fc.launch.py            # +1 Node entry for fc_pwm_driver
└── setup.py                    # +1 entry_point: fc_pwm_driver = fc_core.fc_pwm_driver:main
                                # +1 install_requires: simple-pid>=2.0
```

### Pattern 1: PID compute step inside `control_loop()`

```python
# Source: simple-pid usage pattern + ROS2 Jazzy declare_parameters pattern (existing fc_controller)
from simple_pid import PID

# In __init__ (after declare_parameters adds pid_kp/pid_ki/pid_kd, etc.):
self._pid = PID(
    Kp=self.get_parameter('pid_kp').value,
    Ki=self.get_parameter('pid_ki').value,
    Kd=self.get_parameter('pid_kd').value,
    setpoint=0.0,                       # error-form: setpoint=0, input=error
    sample_time=None,                    # we drive sample_time manually via dt
    output_limits=(0.0, 1.0),
    auto_mode=False,                     # start disengaged; engage after grace
    proportional_on_measurement=False,   # P-on-error (standard form)
    differential_on_measurement=True,    # D-on-measurement (D-term filtering choice)
)
self._pid_engaged = False
self._duty_pub = self.create_publisher(Float32, 'fc1/actuators/humidifier_duty', actuator_qos)
self._effective_setpoint = self.get_parameter('target_humidity').value  # for D-07 ramp

# In control_loop():
if self._grace_active() or stale:
    self._publish_duty(0.0)
    self._disengage_pid()                # forces re-bumpless on next engage
    return

if not self._pid_engaged:
    self._engage_pid_bumplessly()         # preload integrator to 0.15

# D-07 ramp: slew effective_setpoint toward target_humidity over 30s
self._ramp_setpoint(dt)

error_pct = (self._effective_setpoint - self.current_humidity) * 100.0

if abs(error_pct) > self.get_parameter('bypass_threshold').value * 100.0:
    # Mode C: full ON open-loop, freeze integrator
    self._pid.set_auto_mode(False, last_output=self._pid._integral)
    self._publish_duty(1.0)
else:
    # Re-enable integration on Mode C exit, preloading from current open-loop output
    if not self._pid.auto_mode:
        self._pid.set_auto_mode(True, last_output=1.0)
    duty = self._pid(error_pct, dt=dt)
    self._publish_duty(duty)
```

Key decisions baked into Pattern 1:
- **Anti-windup = clamping (conditional integration)** via `simple-pid`'s built-in `output_limits` PLUS explicit `set_auto_mode(False, last_output=...)` on Mode C entry. Back-calculation was the alternative; clamping is simpler and `simple-pid` ships with output-limit-aware integration that already won't wind up against the 1.0 saturation. The Mode C path is the one that *would* wind up, so we explicitly disable integration there. `[CITED: simple-pid README §"Output limits"]`
- **Derivative-on-measurement** (`differential_on_measurement=True`) — standard practice for setpoint changes; avoids the "derivative kick" when target_humidity changes between modes. Combined with the D-07 ramp (which slews the *effective* setpoint anyway), this is double-protection. `[CITED: Åström & Hägglund, *Advanced PID Control* — D-on-measurement is the textbook recommendation for any system with externally-changeable setpoints]`
- **Bumpless transfer** = `set_auto_mode(True, last_output=0.15)` on every (re-)engagement; simple-pid back-computes the integrator state to make `pid()` return ~0.15 on the first call.

### Pattern 2: Slow-PWM windowing in `fc_pwm_driver`

```python
# Source: time-proportional control standard implementation
# (no library needed — window math is ~30 LOC, well-bounded)
class SlowPwmDriver(Node):
    def __init__(self):
        super().__init__('fc_pwm_driver')
        self.declare_parameters('', [
            ('humidifier_pin', 27),
            ('pwm_window_seconds', 120.0),
            ('min_pulse_seconds', 10.0),
            ('max_duty_5min_avg', 0.40),
            ('actuator_simulation_mode', False),
            ('duty_topic_timeout_seconds', 5.0),
        ])
        # ...GPIO init like fc_controller does today...

        actuator_qos = QoSProfile(
            depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST,
        )
        self._duty_sub = self.create_subscription(
            Float32, 'fc1/actuators/humidifier_duty',
            self._duty_callback, actuator_qos,
        )
        self._state_pub = self.create_publisher(
            Bool, 'fc1/actuators/humidifier', actuator_qos,
        )

        self._latest_duty = 0.0
        self._last_duty_msg_ts = None
        self._window_start_ts = self.get_clock().now()
        self._window_on_seconds = 0.0       # locked at window-start
        self._duty_history = deque(maxlen=int(300 / 1.0))  # 5min @ 1Hz tick
        self._current_state = False

        self._tick_timer = self.create_timer(1.0, self._tick)

    def _duty_callback(self, msg):
        # Clamp; record timestamp for staleness defense
        self._latest_duty = max(0.0, min(1.0, msg.data))
        self._last_duty_msg_ts = self.get_clock().now()

    def _tick(self):
        now = self.get_clock().now()
        elapsed = (now - self._window_start_ts).nanoseconds / 1e9
        window = self.get_parameter('pwm_window_seconds').value

        # Defensive: duty topic silent → force OFF
        if self._last_duty_msg_ts is None:
            self._set_relay(False); return
        silence = (now - self._last_duty_msg_ts).nanoseconds / 1e9
        if silence > self.get_parameter('duty_topic_timeout_seconds').value:
            self._set_relay(False); return

        if elapsed >= window:
            # New window: lock in duty, apply min-pulse skip + rolling cap
            duty = self._latest_duty

            # Rolling 5-min cap (D-12)
            if self._duty_history:
                avg = sum(self._duty_history) / len(self._duty_history)
                cap = self.get_parameter('max_duty_5min_avg').value
                if avg + (duty - avg) / len(self._duty_history) > cap:  # forecast
                    duty = max(0.0, cap * len(self._duty_history) - sum(self._duty_history))

            on_sec = duty * window
            min_pulse = self.get_parameter('min_pulse_seconds').value
            if 0.0 < on_sec < min_pulse:
                on_sec = 0.0  # round-down rule (D-11)

            self._window_on_seconds = on_sec
            self._window_start_ts = now
            self._duty_history.append(on_sec / window)
            elapsed = 0.0

        # Within window: relay HIGH for first on_sec, LOW thereafter
        target_state = elapsed < self._window_on_seconds
        self._set_relay(target_state)

    def _set_relay(self, state):
        if state == self._current_state:
            return
        # ...GPIO toggle...
        self._current_state = state
        msg = Bool(); msg.data = state
        self._state_pub.publish(msg)
```

### Pattern 3: Launch-file integration (no new systemd unit)

```python
# fc.launch.py — add one Node entry; fc-core.service already wraps the whole launch
Node(
    package='fc_core',
    executable='fc_pwm_driver',
    name='fc_pwm_driver',
    parameters=[LaunchConfiguration('config_file')],
    output='screen',
),
```

**Why no new systemd unit:** `fc-core.service` runs `ros2 launch fc_core fc.launch.py` under `Restart=always`. The systemd-restart-trap memory (`feedback_systemd_restart_ros2_launch`) was about avoiding `Restart=on-failure` with `ros2 launch`; `Restart=always` is already the active setting per `scripts/pi-deploy/fc-core.service` line 28. Adding a node to the launch file does not introduce a new systemd surface — the existing `Restart=always` covers it. **However:** a single child crash takes down the whole `ros2 launch` process and restarts everything — sensors, controller, PWM driver, camera. This is acceptable (it already happens for any node) but worth noting in the plan.

### Anti-Patterns to Avoid

- **Hand-rolling PID with naive integration:** `i += error * dt` without anti-windup will run away during Mode C and on cold start. Use simple-pid or its derivative form with explicit clamping.
- **Computing duty in fraction-RH error units with the same gains:** moving from `error_pct` to `error_fraction` requires Kp×100, Ki×100, Kd×100. Mixing is the most common PID-tuning mistake. **Pick percent units, document it, stick with it.**
- **Re-publishing duty unchanged on every tick at high rates:** the bridge writes one row per message to TimescaleDB. At 1Hz that's 86k rows/day, fine. At 10Hz it's a million. Stay at 1Hz publish rate, matching `control_interval`.
- **Letting fc_controller publish the relay Bool directly while also publishing duty:** double-publisher conflict on `fc1/actuators/humidifier`. fc_controller MUST stop publishing the relay Bool — fc_pwm_driver is now the only writer. Plan must include removing the existing `humidifier_state_pub` publish call from `control_loop()`.
- **Skipping the bumpless preload:** if the integrator starts at 0, the first window after grace will request 0% duty (P-term only, P-on-error with error≈0 at setpoint) — the system drifts down for ~10 minutes before integration accumulates the 15% steady-state hold. This *was* the behavior measured in calibration as "post-restart spike" was the recovery, not the slump. Preload `i = 0.15` to skip this.
- **Treating `min_pulse` as a min-OFF gap:** D-11 is a min ON-pulse rule — pulses < 10s round to 0. There is no min-OFF rule; OFF can be any duration including 0 (back-to-back ON windows when duty=1.0).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PID kernel (P + I + D + anti-windup + derivative-on-measurement + sample-time handling) | A custom PID class | `simple-pid` library | ~250 LOC of well-tested code; bumpless transfer via `set_auto_mode(True, last_output=...)` is built in; output-limit-aware integration prevents windup at saturation. Reinventing this is the #1 cause of subtle PID bugs in the literature. |
| Setpoint ramping (D-07) | Per-call interpolation | Simple linear interpolation in fc_controller (~10 LOC) | This IS the right thing to hand-roll — it's trivial and use-case-specific. Don't reach for a library. |
| Slow-PWM windowing | Look for a "PWM" PyPI library | Hand-roll ~30 LOC in fc_pwm_driver | Pattern 2 covers the entire algorithm. Generic PWM libraries assume hardware PWM, kHz frequencies, or pigpio-style daemons — none match our ~120s window use case. |
| Anti-windup mechanism | Implement back-calculation by hand | Use clamping (conditional integration) via simple-pid's output_limits + explicit `set_auto_mode(False)` on Mode C entry | Clamping is provably correct for this plant: output saturates at 1.0 only when error ≥ 2% (Mode C territory), and Mode C explicitly freezes the integrator anyway. Back-calculation adds a tuning parameter (Tt — back-calc time) for no benefit here. `[CITED: Åström, *Control System Design* §6.4 — clamping is sufficient when saturation only happens at large error and a separate "manual" path handles those regions]` |

**Key insight:** The PID kernel is library-friendly; the windowing math is project-specific. Split the responsibilities accordingly. The 30 LOC of windowing is what makes Phase 27 unique.

---

## Common Pitfalls

### Pitfall 1: Saturation-induced limit cycle at min-pulse boundary

**What goes wrong:** PID requests duty in the 5–8% range (just below `min_pulse_seconds / pwm_window_seconds = 10/120 = 8.3%`). Round-down rule emits 0 duty. Integrator winds up because RH falls; eventually duty crosses 8.3%, fires a 10s pulse, RH overshoots; integrator unwinds; back to 0; cycle repeats with ~5 minute period.

**Why it happens:** Discontinuous output at the round-down boundary creates a non-smooth control surface; integrator action against a non-smooth output → limit cycle.

**How to avoid:** **The 120s window choice already mitigates this** — at 120s window and ~15% steady-state operating point, the round-down floor (8.3%) sits comfortably below the operating duty. Limit cycle risk would only emerge if steady-state duty drifts below 8.3% (e.g., humid ambient, less evaporative loss). If HUMID-04 soak shows this happening: alternative is to use *delta-sigma rounding* — accumulate the rounded-off duty fraction into the next window, so 5% requested over two windows = 0% in window 1 + 10% in window 2.

**Warning signs:** Sawtooth pattern in duty time-series with ~5–10 min period; periodic 10s pulses at 5–10 min intervals; integrator value oscillating between 0 and saturation.

### Pitfall 2: Bumpless preload overshoots on cold-cold start

**What goes wrong:** First-ever boot at low ambient RH (60% in dry house). PID engages with integrator preloaded to 15%, but actual steady-state requirement might be 30% to overcome dry ambient. PID slowly winds toward 30% but operator sees a sluggish initial response.

**Why it happens:** 15% steady-state was measured at ~80% RH near-setpoint, NOT at recovery from dry. The IPDT model is linearized around steady-state.

**How to avoid:** Mode C handles this regime. From 60%→80% recovery, error = 20% which is way past `bypass_threshold` = 2.5% — Mode C engages, full ON open-loop until error < 2.5%, then PID re-engages with bumpless preload at exactly the right operating point (within 2.5% of setpoint, where 15% steady-state hold is correct).

**Warning signs:** Slow drift up after grace clears in dry conditions; this is the *expected* behavior if Mode C threshold is set too high. If the farmer reports it, lower bypass_threshold to 0.015 (1.5%).

### Pitfall 3: Setpoint ramp races sensor stale

**What goes wrong:** Operator sets new target_humidity. fc_controller starts ramping `effective_setpoint` from 80% toward 92% over 30s. At t=10s, sensor goes stale. D-13 forces duty=0.0 immediately, but the ramp continues running. Sensor recovers at t=20s. Effective_setpoint is now at 84% (mid-ramp), but error is computed against 84%, not 92%, so the controller is still mid-transition.

**Why it happens:** Ramp state and PID engagement state are independent.

**How to avoid:** On stale entry, **freeze** the effective_setpoint (don't reset, don't continue ramping). On stale exit, resume ramping from frozen value. Alternative: reset effective_setpoint to current measured RH on stale exit and re-ramp toward target — this is more conservative but introduces a discontinuity.

**Warning signs:** Mode-switch behavior is inconsistent between "switched while sensor was healthy" and "switched while sensor was stale".

### Pitfall 4: Double-publisher on `fc1/actuators/humidifier` Bool

**What goes wrong:** Plan adds fc_pwm_driver but forgets to remove the `humidifier_state_pub.publish(state_msg)` line at the end of `control_loop()` (fc_controller.py line 400). Both nodes publish to the same topic. Bridge sees alternating values (one based on PID's view of "what should be happening", one based on actual GPIO state).

**Why it happens:** The existing publish-on-every-tick was a "this is what I asked the GPIO to do" idiom. Now fc_controller doesn't touch the GPIO. The publish is now wrong but not obviously so.

**How to avoid:** Plan must explicitly delete fc_controller.py lines 397–400. Code review checklist item: "fc_controller no longer creates `humidifier_state_pub` and no longer publishes `fc1/actuators/humidifier` Bool". Plan-checker can verify by grep.

**Warning signs:** Mission Control humidifier plot shows two distinct trace patterns interleaved; TimescaleDB `fc.humidifier` column has 2× the expected row rate.

### Pitfall 5: Duty topic QoS mismatch for late-joining bridge

**What goes wrong:** fc_controller publishes duty with default VOLATILE QoS. Bridge starts later (compose restart). Bridge subscribes but sees no duty value until fc_controller's next 1Hz publish. For 1s the bridge thinks duty is 0 (no message yet) — but the operator might be looking at exactly that moment.

**Why it happens:** TRANSIENT_LOCAL on the publisher replays the last sample to late joiners; VOLATILE does not.

**How to avoid:** Use TRANSIENT_LOCAL on the duty publisher, matching the existing humidifier_state and sensor_health pattern. Bridge subscription must also be RELIABLE+TRANSIENT_LOCAL.

**Warning signs:** "Duty plot drops to 0 after bridge restart for ~1s." Resolved by QoS fix.

### Pitfall 6: simple-pid sample_time clamps PID computation

**What goes wrong:** `simple-pid`'s default `sample_time` is 0.01s. If you call `pid(error)` faster than that, it returns the previous output unchanged. If `control_interval=1.0` and you forget to set `sample_time=None`, the PID still works correctly *but* the integrator's dt is computed internally — fine. BUT if the timer fires faster than expected (sub-second jitter), output stays stale.

**Why it happens:** simple-pid is designed to be call-rate-tolerant by default.

**How to avoid:** Set `sample_time=None` and pass explicit `dt` to every `pid(error, dt=dt)` call. Compute dt as `(now - last_tick).nanoseconds / 1e9`. This makes the PID time-step-explicit and easy to test.

**Warning signs:** Unit tests where `pid()` returns the same value on consecutive calls.

### Pitfall 7: Sim mode forgets the slow-PWM driver path

**What goes wrong:** Existing fc_controller.py `set_humidifier(state)` method has a sim-mode branch that just sets `self.humidifier_state`. The new fc_pwm_driver needs the same sim-mode branch — and the existing test_controller.py tests rely on `node.humidifier_state` being readable. After Phase 27, that attribute lives on a different node.

**Why it happens:** Tests are coupled to the controller's GPIO ownership.

**How to avoid:** Plan must (a) port the sim-mode pattern to fc_pwm_driver verbatim, (b) update test_controller.py to assert against the published `humidifier_duty` topic value (capture published messages like Phase 16's test pattern, see test_controller.py lines 374–388), (c) move tests of "humidifier ON/OFF state" to `test_pwm_driver.py` where they test against the simulated GPIO state in fc_pwm_driver.

**Warning signs:** test_controller.py imports cease to make sense; tests assert against attributes that no longer exist.

---

## Code Examples

### Bumpless transfer engagement

```python
# Source: simple-pid set_auto_mode(True, last_output=...) pattern
def _engage_pid_bumplessly(self):
    """Re-engage PID with integrator preloaded to steady-state operating point."""
    steady_state_duty = 0.15  # from calibration findings table
    self._pid.set_auto_mode(True, last_output=steady_state_duty)
    self._pid_engaged = True
    self.get_logger().info(f'PID engaged with bumpless preload: duty={steady_state_duty}')

def _disengage_pid(self):
    """Disengage PID — integrator frozen at last value."""
    if self._pid_engaged:
        self._pid.set_auto_mode(False)
        self._pid_engaged = False
```

### Setpoint ramp (D-07)

```python
def _ramp_setpoint(self, dt):
    target = self.get_parameter('target_humidity').value
    ramp_seconds = self.get_parameter('pid_setpoint_ramp_seconds').value
    if ramp_seconds <= 0:
        self._effective_setpoint = target
        return
    delta = target - self._effective_setpoint
    if abs(delta) < 1e-6:
        self._effective_setpoint = target
        return
    max_step = abs(delta) * (dt / ramp_seconds)  # max fraction-RH per dt
    step = max(-max_step, min(max_step, delta))
    self._effective_setpoint += step
```

### Bridge subscription (mirror existing humidifier pattern)

```javascript
// Add to src/mission-control/bridge/src/index.js after the humidifier Bool subscription (~line 700)
// Source: existing pattern at lines 685–699 — same QoS profile
node.createSubscription(
    'std_msgs/msg/Float32',
    '/fc1/actuators/humidifier_duty',
    { qos: humidifierQos },          // reuse: TRANSIENT_LOCAL, RELIABLE, depth=1
    async (msg) => {
        const value = msg.data;       // 0.0–1.0
        const ts = Date.now();
        latestTelemetry.humidifier_duty = { value, timestamp: ts };
        broadcast({ humidifier_duty: value, timestamp: ts });
        await insertTelemetry('fc.humidifier_duty', value);
    }
);

// Also add 'fc.humidifier_duty' to ALLOWED_TOPICS at line 346.
```

---

## Runtime State Inventory

Phase 27 is a refactor with both code and config changes. State to address:

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | TimescaleDB `telemetry` hypertable will receive a new topic `fc.humidifier_duty`. Existing rows for `fc.humidifier` continue accumulating from fc_pwm_driver. No schema change needed (topic column is TEXT). No migration needed for old rows. | None — data layer is append-only and topic-agnostic by design |
| Live service config | None — fc1 and elder-plops both deploy from git via `fc-update.service` + `deploy.sh`. ROS params are loaded from `config/fc_config.yaml` at node start. Live param changes via `ros2 param set` do not persist (memory `feedback_humidity_runtime_param`); the YAML is the source of truth | Update `config/fc_config.yaml`: REMOVE `min_dwell_time` (D-15); ADD pid_kp, pid_ki, pid_kd, pid_setpoint_ramp_seconds, bypass_threshold, pwm_window_seconds, min_pulse_seconds, max_duty_5min_avg, duty_topic_timeout_seconds, pid_derivative_filter_tau |
| OS-registered state | `scripts/pi-deploy/fc-core.service` already runs `ros2 launch fc_core fc.launch.py` under `Restart=always`. New fc_pwm_driver runs inside that launch — no new systemd unit. **Verify**: diff `/etc/systemd/system/fc-core.service` on fc1 vs the repo before merge (memory `feedback_diff_repo_vs_pi_systemd`); if drift exists, reconcile before deploy | None for systemd; verify with diff |
| Secrets/env vars | None — Phase 27 is GPIO + ROS topics, no external services involved | None |
| Build artifacts / installed packages | `simple-pid` PyPI package needs `pip install` on fc1. Either (a) add to `setup.py` install_requires + colcon picks it up via rosdep, or (b) explicit `pip install simple-pid` in deploy script. Also: `colcon build --symlink-install --packages-select fc_core` after setup.py change. **Stale .egg-info risk**: existing `src/chambers/fc-core/fc_core.egg-info` directory will need rebuilding after entry_points change | Plan must include: pip install simple-pid; colcon clean+build; verify `ros2 run fc_core fc_pwm_driver` resolves on fc1 |

**`min_dwell_time` removal sweep — files needing edits beyond fc_controller.py:**

- `src/chambers/fc-core/config/fc_config.yaml:37` — remove
- `src/chambers/fc-core/fc_core/fc_controller.py:36` — remove from declare_parameters
- `src/chambers/fc-core/fc_core/fc_controller.py:198–226` — delete `_set_humidifier_with_dwell()` entirely
- `src/chambers/fc-core/fc_core/test/test_controller.py:155–267` — delete dwell-related tests (`test_new_params_declared`, `test_dwell_time_blocks_toggle`, `test_dwell_time_allows_toggle_after_wait`, `test_dwell_time_first_toggle_always_allowed`, `test_dwell_time_applies_both_directions`, `test_safe_state_updates_dwell_toggle`)
- `docs/OPERATIONS.md:47` — remove from operations table (defer per CONTEXT deferred section, but still recommend update in this phase since OPERATIONS.md will mislead operators)
- `docs/pi-setup/dev-workflow.md:135` — remove
- `.planning/research/ARCHITECTURE.md:73,77` and `.planning/milestones/v1.0-*` — historical docs, do NOT edit (they describe v1.0 state truthfully; let history stand)
- `.planning/phases/15-sensor-warmup-grace-period/15-01-PLAN.md:132` — historical, do not edit
- `.planning/phases/17-alert-engine-signal/17-RESEARCH.md:545` — alerter rule references min_dwell_time semantics; this is the deferred sweep item. The alerter's `ALERT_HUMIDIFIER_STUCK_MIN=30` minute heuristic still works post-Phase 27 (humidifier in continuous-ON for 30 min still indicates a stuck system) but its *justification* changes. Recommend a doc-only update in 17-RESEARCH.md noting the new justification, or defer to the alerter sweep follow-up

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| `simple-pid` (PyPI) | PID kernel | ✗ on fc1 (likely; not in setup.py install_requires today) | — | Vendor copy into `fc_core/_vendor/` if Pi internet is flaky (memory `project_fc1_only_link_weak_wifi`) |
| `RPi.GPIO` | fc_pwm_driver GPIO27 ownership | ✓ on fc1 (already used by fc_controller) | (system) | — |
| Python `collections.deque`, `time` | stdlib | ✓ everywhere | stdlib | — |
| ROS2 Jazzy `rclpy`, `std_msgs` | All nodes | ✓ on fc1 | system | — |
| `colcon` | Build | ✓ on fc1 | system | — |
| Internet from fc1 to PyPI | One-time pip install of simple-pid during deploy | ⚠ flaky over Tailscale CGNAT (memory `project_fc1_ssh_relay_unreliable`) | — | Vendor simple-pid into the repo (≤ 250 LOC, MIT licensed) — eliminates the network dependency entirely. **Recommended.** |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** simple-pid via vendoring. Given the Pi's flaky uplink, vendoring is the conservative choice and adds ~6KB to the repo. Plan should make this the default path.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Bang-bang + min_dwell_time | PID + slow-PWM time-proportional output | Phase 27 (this phase) | Resolves structural ±2% RH ceiling; closes HUMID-01..04 |
| Single fixed PID + gain scheduling for nonlinearity | Single fixed PID + Mode C open-loop bypass for far-from-setpoint | Phase 27 (D-09) | Simpler to attest, no second tune surface; trade-off is slightly slower recovery in some regimes |
| `min_dwell_time` as actuator-protection | `pwm_window_seconds` (window IS the safety floor) | Phase 27 (D-15) | Safety semantics shift from "edge-frequency limit" to "amplitude limit per window" |

**Deprecated/outdated:**
- `_set_humidifier_with_dwell()` and all its tests
- `min_dwell_time` ROS param
- DWELL-BLOCK log line (no longer emitted)

---

## Project Constraints (from CLAUDE.md)

- **Build system:** colcon with `--symlink-install` for Python development; rebuild after setup.py/entry_point changes
- **ROS2 distribution:** Jazzy
- **simulation_mode flag:** `actuator_simulation_mode` and `sensor_simulation_mode` are independent in `fc_config.yaml`. fc_pwm_driver MUST honor `actuator_simulation_mode` (no GPIO calls when true), mirroring existing fc_controller pattern (lines 42–78)
- **Linting:** `ament_flake8 src/chambers/fc-core/` and `ament_pep257` — new files must pass
- **Testing:** `colcon test --packages-select fc_core` plus `pytest src/chambers/fc-core/fc_core/test/`
- **Network:** ROS_DOMAIN_ID=69; CycloneDDS over Tailscale on fc1 — duty topic and humidifier topic both go over the bus to bridge on elder-plops; TRANSIENT_LOCAL is correct for both (matches Phase 04 ACTR-03 pattern)
- **No Co-Authored-By trailer on commits** (memory `feedback_no_coauthor`)
- **Pi deploy is git, branch fc1/prod** (memory `feedback_deploy_method`); plan must end with a "deploy via fc1/prod merge" step

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest` (existing); ROS2 ament-style test entry via `colcon test` |
| Config file | `src/chambers/fc-core/setup.py` (`tests_require=['pytest']`); no separate pytest.ini |
| Quick run command | `pytest src/chambers/fc-core/fc_core/test/test_pid_kernel.py -x` (pure-math unit tests, < 1s) |
| Full suite command | `colcon test --packages-select fc_core && colcon test-result --verbose` |
| Phase gate | Full suite green + 2-hour live soak on fc1 with farmer attestation (D-16) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| HUMID-01 | Controller publishes duty 0.0–1.0 on every tick | unit | `pytest test/test_controller.py::test_duty_published_each_tick -x` | ❌ Wave 0 |
| HUMID-01 | Duty topic uses TRANSIENT_LOCAL QoS | unit | `pytest test/test_controller.py::test_duty_qos_transient_local -x` | ❌ Wave 0 |
| HUMID-01 | Stale → duty=0.0 (D-13) | unit | `pytest test/test_controller.py::test_stale_forces_duty_zero -x` | ❌ Wave 0 |
| HUMID-01 | Grace → duty=0.0 (D-14) | unit | `pytest test/test_controller.py::test_grace_forces_duty_zero -x` | ❌ Wave 0 |
| HUMID-01 | Mode C entry: duty=1.0 when |error| > bypass_threshold (D-09) | unit | `pytest test/test_controller.py::test_mode_c_entry -x` | ❌ Wave 0 |
| HUMID-01 | Mode C exit: PID re-engages bumplessly | unit | `pytest test/test_controller.py::test_mode_c_exit_bumpless -x` | ❌ Wave 0 |
| HUMID-02 | Slow-PWM produces ON for first `duty * window` seconds | unit | `pytest test/test_pwm_driver.py::test_window_on_then_off -x` | ❌ Wave 0 |
| HUMID-02 | Min-pulse skip: duty < `min_pulse/window` → 0 emitted (D-11) | unit | `pytest test/test_pwm_driver.py::test_min_pulse_skip -x` | ❌ Wave 0 |
| HUMID-02 | Rolling 5-min cap clamps duty (D-12) | unit | `pytest test/test_pwm_driver.py::test_rolling_max_cap -x` | ❌ Wave 0 |
| HUMID-02 | Duty topic timeout → defensive OFF | unit | `pytest test/test_pwm_driver.py::test_duty_silence_forces_off -x` | ❌ Wave 0 |
| HUMID-02 | Bool published to `fc1/actuators/humidifier` on every edge | unit | `pytest test/test_pwm_driver.py::test_bool_published_on_edge -x` | ❌ Wave 0 |
| HUMID-03 | All pid_* params declared with calibration-derived defaults | unit | `pytest test/test_controller.py::test_pid_params_declared -x` | ❌ Wave 0 |
| HUMID-03 | PID gains read each tick (live-tunable) | unit | `pytest test/test_controller.py::test_pid_gains_live_reload -x` | ❌ Wave 0 |
| HUMID-03 | Bumpless preload to steady-state on engage (D-06) | unit | `pytest test/test_pid_kernel.py::test_bumpless_preload -x` | ❌ Wave 0 |
| HUMID-03 | Setpoint ramp slews effective setpoint over `pid_setpoint_ramp_seconds` (D-07) | unit | `pytest test/test_controller.py::test_setpoint_ramp -x` | ❌ Wave 0 |
| HUMID-04 | 2-hour soak on fc1 stays inside ±0.5% RH band | manual (live) | Farmer-attested via OpenMCT chart + TimescaleDB query: `SELECT MIN(value), MAX(value), AVG(value) FROM telemetry WHERE topic='fc.humidity' AND time > NOW() - INTERVAL '2 hours'` (PASS: max-min ≤ 0.01) | manual gate, no automation possible |
| HUMID-04 | Zero DWELL-BLOCK or saturation-cycle log lines | live + log-grep | `journalctl -u fc-core.service --since '2 hours ago' \| grep -E 'DWELL-BLOCK\|saturation\|limit-cycle'` returns nothing | manual gate |

### Sampling Rate

- **Per task commit:** `pytest src/chambers/fc-core/fc_core/test/test_pid_kernel.py src/chambers/fc-core/fc_core/test/test_controller.py src/chambers/fc-core/fc_core/test/test_pwm_driver.py -x`
- **Per wave merge:** `colcon build --packages-select fc_core --symlink-install && colcon test --packages-select fc_core --event-handlers console_direct+`
- **Phase gate:** Full suite green + 2-hour live soak with farmer attestation (HUMID-04 / D-16). Soak query in OpenMCT must visibly show duty + humidifier-state overlay (D-02) staying inside the band.

### Wave 0 Gaps

- [ ] `tests/test_pid_kernel.py` — pure-math unit tests; covers HUMID-03 and the bumpless-transfer + Mode C entry/exit math
- [ ] `tests/test_pwm_driver.py` — covers HUMID-02; mocked clock + GPIO; window-math, min-pulse-skip, rolling cap, defensive OFF
- [ ] `tests/test_controller.py` — refactor existing dwell-related tests into duty-publish tests; covers HUMID-01 and HUMID-03
- [ ] No new fixtures/conftest needed — `_mock_clock_at()` helper from existing test_controller.py is reusable
- [ ] Framework install: simple-pid pinned in setup.py; vendoring path documented

### Input space, output space, invariants, edge frequencies

**Input space:**
- Humidity readings: 0.50–1.00 fraction (50–100% RH); slot-1 only (D-17); arrival rate ~0.5–1.0 Hz from fc_sensors; spike-rejected via existing 5-deep median buffer
- target_humidity changes: 0.70–0.95 typical; arrival rate ~0 Hz nominal, ≤1/min on mode switches (Phase 28+)
- Sensor stale events: arrival rate ~0/day nominal; duration arbitrary
- Grace transitions: 1× on boot only

**Output space:**
- humidifier_duty: continuous 0.0–1.0; published at `control_interval = 1.0` Hz
- humidifier Bool: 0 or 1; published only on edges (transitions); expected rate ~1 edge per 120s window in steady state = ~720 transitions/day
- Mode C transitions: published implicitly via duty going to 1.0; rate near zero in steady state; bursts during recovery from disturbance

**Invariants (assert in tests):**
- `0.0 ≤ duty ≤ 1.0` always — clamp at publisher
- During grace OR stale: duty = 0.0 exactly (no slew, no compromise — D-13/D-14)
- During Mode C: duty = 1.0 exactly
- After Mode C exit, integrator value such that PID(error≈threshold) ≈ 1.0 (bumpless)
- After grace clear, integrator value such that PID(error≈0) ≈ 0.15 (bumpless preload)
- min-pulse rule: any window where requested on_seconds is in `(0, min_pulse_seconds)` → emitted 0
- rolling 5-min cap: average duty across last 300 samples ≤ max_duty_5min_avg
- humidifier Bool publication is monotonic per window (one OFF→ON edge at most, one ON→OFF edge at most, per 120s)

**Edge frequencies:**
- Control tick: 1 Hz (existing `control_interval=1.0`)
- PWM driver tick: 1 Hz (matches control tick — relay edge resolution of 1s is fine for 120s windows)
- Sensor publish rate: ~0.5 Hz (SHT30) / ~0.2 Hz (SCD41); both well above Nyquist for 0.025 %/s plant
- PWM window boundary: every 120s
- Sample rate adequacy: dead time = 16s, plant time constant near setpoint >> 60s; 1 Hz tick is 16× oversampled relative to dead time → comfortable

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `simple-pid` 2.0+ available on PyPI; vendoring path is feasible (≤250 LOC MIT) | Standard Stack | Low — alternative is hand-roll. If license differs, hand-roll. Plan must verify license before vendoring. |
| A2 | PID gains derived from SCD41-only calibration data are usable on the SHT30 (live) sensor without retuning | PID Gain Derivation | Medium — SHT30 has different noise spectrum and ±1.5% accuracy vs SCD41 ±6%. Plan must include a tuning iteration as part of HUMID-04 soak. Conservative gains (τ_c = 3L = 48s) reduce this risk but don't eliminate it. |
| A3 | `max_duty_5min_avg = 0.40` is the right tank-protection ceiling | Discretion-Default Recommendations | Low — pure operator-facing knob. Farmer can tune live via ROS param if 40% is wrong. Worst case is the cap engaging during normal operation, which would show up as duty plateaus — easy to spot in OpenMCT. |
| A4 | `bypass_threshold = 0.025` (2.5% RH) is the right Mode C entry point | Discretion-Default Recommendations | Medium — too low and Mode C engages on benign disturbances, defeating PID. Too high and recovery is sluggish. The 2.5% choice is justified by being just past the saturation point of the recommended Kp (where P-term alone already requests duty=1.0). If tuning iteration changes Kp, revisit this. |
| A5 | Removing `humidifier_state_pub` from fc_controller and adding it to fc_pwm_driver does not break any downstream consumer beyond the bridge | Pitfall 4 / Architectural Responsibility Map | Low — bridge is the only external subscriber per `grep humidifier` of the codebase. Late-joining QoS contract preserved. Plan-checker verifies. |
| A6 | The slow-PWM driver running inside the existing fc-core.service ros2 launch is sufficient (no new systemd unit needed) | Pattern 3 | Low — matches the existing pattern for fc_sensors, fc_display, fc_camera which all run under one launch under one systemd unit. |
| A7 | A 1 Hz control tick + 1 Hz PWM tick gives sufficient resolution for 120s windows + 10s min pulses | Validation Architecture | Low — 1s edge resolution against 10s minimum pulse is 10× oversampled. Plant dead time 16s makes faster ticks pointless. |
| A8 | `differential_on_measurement=True` (D-on-measurement) is correct given the D-07 setpoint ramp also smooths setpoint changes | Pattern 1 | Low — both decisions are independently defensive; the combination is over-defensive but cheap. If derivative is later found to do nothing useful (which is plausible at this plant time scale), Kd can be set to 0 via param without code change. |

---

## Open Questions

1. **Should the rolling 5-min cap (D-12) operate on requested duty or emitted duty?**
   - What we know: D-12 says "duty averaged over a 5-minute rolling window is capped." Ambiguous between (a) cap PID's request before publishing, or (b) cap fc_pwm_driver's emitted on-time after the min-pulse round-down.
   - What's unclear: which the operator means.
   - Recommendation: Cap in fc_pwm_driver on emitted on-time. This is the actuator-protection layer; conceptually D-12 is "don't run the humidifier wet for >40% of any 5-min window." If we cap in fc_controller, the slow-PWM round-down rule could push the actual emitted duty *above* the requested-cap (rare but possible). Plan should call this out and confirm with operator if ambiguous.

2. **Does the SHT30 noise floor allow Kd > 0 to do useful work?**
   - What we know: SHT30 ±1.5% accuracy; sample rate ~0.5 Hz; rates of change are ~0.01 %/s near setpoint.
   - What's unclear: whether D-term contribution (Kd × d(error)/dt with 10s low-pass) provides meaningful damping, or just noise injection.
   - Recommendation: Ship with `pid_kd = 4.0` and 10s filter. If HUMID-04 soak shows D-term oscillating against noise (visible as duty jitter at ~0.1Hz), set Kd=0 via param and re-soak. Don't tune Kd at design time; tune in the soak.

3. **Does fc_controller need to re-publish duty=0.0 every tick during stale, or just once on stale entry?**
   - What we know: D-13 forces duty=0.0 on stale.
   - What's unclear: TRANSIENT_LOCAL means a single publish persists for late joiners — so a single publish on stale-entry would be sufficient for new subscribers, but existing subscribers' last-received value would be stale.
   - Recommendation: Publish duty=0.0 every tick during stale (continuous declaration), matching the pattern used for the existing humidifier state. This is what the operator expects to see on the chart (duty drops to and stays at 0). Cost is one extra Float32 publish per second — negligible.

---

## Sources

### Primary (HIGH confidence)
- `.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md` — system-ID data, dead-time, rates, steady-state operating point. All numerical PID derivations trace here.
- `.planning/phases/27-pid-time-proportional-duty-cycle-primitive/27-CONTEXT.md` — locked decisions D-01..D-17.
- `.planning/REQUIREMENTS.md` — HUMID-01..04 contracts.
- `src/chambers/fc-core/fc_core/fc_controller.py` — current code; pattern source for ROS params, QoS, sensor stale, grace, sim mode, publish-on-change.
- `src/chambers/fc-core/fc_core/test/test_controller.py` — existing test patterns for clock mocking, publish capture.
- `src/mission-control/bridge/src/index.js` lines 685–699 — humidifier subscription + QoS; new duty subscription mirrors this verbatim.
- `scripts/pi-deploy/fc-core.service` — systemd unit; confirms `Restart=always` already in place.

### Secondary (MEDIUM confidence)
- Skogestad, "Simple analytic rules for model reduction and PID controller tuning" (J. Process Control 2003) — IMC/SIMC rules for IPDT plants. `[CITED]`
- Åström & Hägglund, *Advanced PID Control* (ISA, 2006) — standard reference for derivative-on-measurement, anti-windup taxonomy. `[CITED]`
- `simple-pid` PyPI package — README documents `set_auto_mode(True, last_output=...)` for bumpless transfer and `output_limits` for clamping anti-windup. `[CITED — verify license + version on the dev box before locking the dependency]`

### Tertiary (LOW confidence)
- General process-control folklore on time-proportional control with long windows for SSR-driven heaters/humidifiers. Sufficient as background; not a load-bearing source for any decision in this research.

---

## Metadata

**Confidence breakdown:**
- Architecture (topic boundary, packaging, QoS, integration with bridge): HIGH — every choice aligns with an existing in-repo pattern
- PID gain numerical defaults: MEDIUM — derived rigorously from calibration data, but the calibration data itself has the SHT30-offline caveat; expect a tuning iteration during HUMID-04 soak
- Anti-windup, derivative form, filter time constant: HIGH — standard process-control practice; conservative defaults; tunable as ROS params if soak surfaces issues
- Slow-PWM windowing math: HIGH — algorithm is well-bounded ~30 LOC and fully covered by Pattern 2
- Mode C boundary value (`bypass_threshold` default): MEDIUM — derivable from Kp choice but coupled, would change if Kp tuning shifts
- Rolling 5-min cap default: LOW — operator-facing tank-protection knob; depends on tank size and fill schedule that aren't in scope of this research
- Test strategy: HIGH — existing test_controller.py provides the patterns; only new test files needed are listed in Wave 0 Gaps

**Research date:** 2026-05-01
**Valid until:** 2026-05-30 (calibration data freshness; will need re-measurement once SHT30 is back online for any Kp/Ki retune)
