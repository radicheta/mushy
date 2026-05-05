# Phase 999.33: Digital twin / simulation of FC chamber for offline control development — Research

**Researched:** 2026-05-04
**Domain:** Process-control simulation, ODE integration, ROS2 simulation patterns, system identification
**Confidence:** MEDIUM-HIGH (HIGH on physics + integration; MEDIUM on validation thresholds; LOW on second-order lag interpretation)

## Summary

The 2026-05-04 PID calibration session 2 produced six substantive control artifacts in one day, each gated on real chamber + live grow + ambient-temp swing + farmer presence. Iteration cadence is ~1 design idea per real day. A digital twin breaks this rate-limit by exercising controller code against a physics model at wall-clock-independent speed, enabling reproducible regression of historical incidents and CI-gated tuning experiments.

The recommended shape is a **headless Python ODE plant** living in `fc_core/sim/` with **two consumption points**:
1. **Pure-offline replay tool** (`fc_core/sim/run_replay.py`) that imports the same `simple_pid` kernel `fc_controller` uses, runs it against the ODE in a tight `for`-loop, no ROS — the primary tuning surface and CI gate.
2. **ROS2 sensor-stub upgrade** — replace the `random.uniform`-jitter block in `fc_sensors.read_sensors()` (lines 112-132) with a model that ingests duty from the existing `fc1/actuators/humidifier_duty` topic and publishes physically realistic RH/T. This makes `simulation_mode: true` actually faithful for end-to-end node tests but is the **secondary** integration; the primary value lives in the offline replay tool.

A 4-hour **incident replay** of the 2026-05-04 13:32–14:47 UYT temp-peak slice (clean rising-T → peak-T → falling-T pattern, both overshoot flavors visible, integrator-driven 28-min limit cycle) becomes the **canonical fidelity test**: feed historical actuator commands + measured T(t), compare model RH(t) to measured RH(t) within ±2% RMS. If the sim reproduces today's failure modes (PID let-go at setpoint step, plateau-undershoot, integrator limit cycle) it is fit for purpose.

**Primary recommendation:** Build shape (a) in three increments — (1) ODE module + analytical unit tests, (2) replay tool + 2026-05-04 incident fixture passing fidelity gate, (3) ROS2 sim-mode integration. Defer Gazebo (shape b) until multi-chamber or vision testing become hot. Keep the ODE library-agnostic (no ROS imports) so it composes into both shapes.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Physics model (RH/T ODE) | `fc_core.sim.chamber_model` (pure Python) | — | Library code, zero ROS deps, importable from tests + replay tool + sim sensors |
| Numerical integration | `fc_core.sim.chamber_model` | — | Owned by the model — caller passes dt + state, gets next state |
| Disturbance source (T(t)) | `fc_core.sim.disturbance` | — | Pluggable: synthetic curve, Timescale replay, constant — model is agnostic |
| Offline replay loop | `fc_core.sim.run_replay` (CLI) | — | Tight loop: model + simple_pid kernel + duty-cycle simulation; no rclpy |
| ROS2 integration | `fc_sensors.py` sim branch | — | Existing `simulation_mode: true` path is the natural seam; subscribes to `humidifier_duty`, integrates model, publishes T/RH |
| Historical fixture | `test/fixtures/incident_2026_05_04.csv` | Timescale (origin) | Frozen CSV checked into repo for reproducibility; Timescale used to *generate* it |
| CI gate | `colcon test` / pytest unit | — | Fast (< 60 s) synthetic + < 30 s incident replay; full 24h sim runs as opt-in marker |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | ≥1.24 [VERIFIED: shipped in ROS2 Jazzy base] | Vector math for ODE state, exogenous traces | Already a transitive dep via rclpy/sensor_msgs; ubiquitous |
| scipy | ≥1.10 [CITED: scipy.integrate.solve_ivp docs] | Optional reference integrator (RK45/LSODA) for validation only | Adaptive-step gold standard for cross-checking custom Euler |
| pytest | already in `tests_require` (`setup.py:32`) [VERIFIED: read setup.py] | Test runner | Existing fc_core convention |
| `fc_core.vendor.simple_pid` | v2.0.0 vendored [VERIFIED: read pid.py:23] | Controller-under-test | Keep sim and prod tuning the same kernel — the entire point of the sim |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| psycopg2-binary | optional | Generate Timescale fixture CSVs | One-off fixture extraction; not a runtime dep |
| matplotlib | optional | Local plotting of replay results during development | Developer ergonomics; never imported in tests |

**Recommendation: avoid scipy as a hard dependency.** A forward-Euler integrator at dt=1s (matching `control_interval: 1.0`) is sufficient for this plant — chamber τ = 600 s, dead time θ = 50 s, so dt=1 s gives 600× resolution on the slowest mode. Use scipy.integrate only inside an opt-in `tests/test_integrator_reference.py` that cross-checks the Euler implementation against RK45 on a closed-form case (exponential decay, dRH/dt = -L/m·(RH-RH_in)).

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom forward-Euler | scipy `solve_ivp` (RK45) | RK45 is adaptive + accurate but adds dependency; for τ/θ ratio 12 it's overkill |
| Custom forward-Euler | numba-jitted Euler | Speed gain trivial here (24 h × 1 Hz = 86,400 ticks ≈ 1 s wall-time in pure Python); not worth complexity |
| ODE-in-Python | Gazebo with custom thermal/humidity plugin | Weeks vs days; multi-chamber/vision unlocked but no immediate use case [CITED: ROADMAP 999.33 shape (b)] |
| ODE-in-Python | Modelica / OpenModelica | Faithful multi-physics but a separate runtime + interop pain |
| Replace simple_pid | python-control / scipy.signal | Tempting for Smith predictor / MPC, but breaks the "sim runs same kernel as prod" contract |

**Installation:** none — numpy + pytest are already available; no new package dependencies for shape (a).

**Version verification:** `python3 -c "import numpy, scipy; print(numpy.__version__, scipy.__version__)"` on elder-plops to confirm; if scipy missing, mark scipy-using tests as `@pytest.mark.skipif`.

## Architecture Patterns

### System Architecture Diagram

```
                     ┌─────────────────────────────────────────────────────┐
                     │          fc_core.sim.chamber_model                  │
                     │                                                     │
   exogenous T(t) ──►│  step(state, duty, T_amb, dt) -> next_state         │
                     │                                                     │
                     │   state: (RH, m_water, last_pulse_age_s)            │
                     │   physics: dm/dt = M·duty − L(T,RH)                 │
                     │   dead-time queue: 50s FIFO of (duty, ts)           │
                     └─────────────────────────────────────────────────────┘
                            ▲                                ▲
                            │                                │
       ┌────────────────────┴──────────┐    ┌────────────────┴──────────────────┐
       │  fc_core.sim.run_replay (CLI) │    │  fc_sensors.py (sim_mode branch)  │
       │                               │    │                                   │
       │  for tick in trace:           │    │  on humidifier_duty msg:          │
       │     duty = pid(error)         │    │     buffer duty                   │
       │     duty = pwm.window(duty)   │    │  on read_sensors timer:           │
       │     state = model.step(...)   │    │     state = model.step(state,     │
       │     csv.write(state)          │    │         buffered_duty, T_amb,dt)  │
       │                               │    │     publish RelativeHumidity/Temp │
       │  no ROS, no threads           │    │  exogenous T from synthetic curve │
       └───────────────────────────────┘    └───────────────────────────────────┘
                            │                                │
                            ▼                                ▼
                ┌───────────────────────┐         ┌──────────────────────────┐
                │  test_replay_fidelity │         │  fc_controller (unchanged│
                │  asserts ≤ ±2% RMS vs │         │  closes loop on real     │
                │  measured incident    │         │  fc1/humidity topic)     │
                └───────────────────────┘         └──────────────────────────┘
```

The model is the **single physics oracle**. Both consumers (replay CLI, ROS sensor stub) treat it as a pure function — caller manages time, holds state, drives disturbances.

### Recommended Project Structure

```
src/chambers/fc-core/fc_core/sim/
├── __init__.py
├── chamber_model.py       # ODE + dead-time queue (zero ROS deps)
├── disturbance.py         # T(t) sources: synthetic curve, replay-from-csv
├── pwm_window.py          # Pure-Python mirror of fc_pwm_driver duty→relay logic
└── run_replay.py          # CLI entry point: --gains --duration --disturbance --output

src/chambers/fc-core/fc_core/test/
├── test_chamber_model.py   # Analytical unit tests (decay, equilibrium, gain)
├── test_replay_fidelity.py # ±2% RMS gate against incident fixture
└── fixtures/
    ├── incident_2026_05_04.csv  # T, RH, duty, target — 13:32–17:00 UYT slice
    └── synthetic_24h.py          # Generator for CI 24h grow gate
```

### Pattern 1: Stateless `step()` interface

**What:** Model exposes `step(state, inputs, dt) -> new_state` — no internal time, no clock, no threading.
**When to use:** Always. The caller (replay loop, ROS timer) owns the clock; the model is pure data transformation.
**Example:**
```python
# fc_core/sim/chamber_model.py
import math
from collections import deque
from dataclasses import dataclass, field

@dataclass
class ChamberState:
    rh: float                    # fraction (0.94 = 94%)
    m_water_g: float             # current water mass in chamber air (g)
    duty_queue: deque = field(default_factory=lambda: deque(maxlen=200))  # 50s @ 4Hz

@dataclass(frozen=True)
class ChamberParams:
    # System ID values from docs/pid_calibration_notes.md "Chamber Dynamics"
    volume_m3: float = 5.76
    air_mass_kg: float = 7.0
    mister_rate_g_per_min: float = 6.0
    leakage_cold_g_per_min: float = 1.4   # 8.8°C, 94% RH
    leakage_hot_g_per_min: float = 5.0    # 17.5°C, 95% RH
    dead_time_s: float = 50.0
    tau_s: float = 600.0                  # ~10 min approach time
    sensor_noise_std_pct: float = 0.04    # SHT30 jitter, observed

def saturation_pressure_pa(t_c: float) -> float:
    """Tetens approximation, water over liquid surface."""
    return 610.78 * math.exp(17.27 * t_c / (t_c + 237.3))

def step(state: ChamberState, params: ChamberParams,
         duty: float, t_amb_c: float, dt_s: float) -> ChamberState:
    # 1) Push current duty into dead-time queue, pop the one that landed θ ago
    state.duty_queue.append((duty, dt_s))
    cumulative = 0.0
    effective_duty = 0.0
    for d, dur in reversed(state.duty_queue):
        cumulative += dur
        if cumulative >= params.dead_time_s:
            effective_duty = d
            break

    # 2) Mass balance: water in − water out
    m_in_g = (params.mister_rate_g_per_min / 60.0) * effective_duty * dt_s
    # Leakage scales with saturation-pressure differential (cold/hot envelope)
    p_sat_in  = saturation_pressure_pa(t_amb_c)
    p_sat_ref = saturation_pressure_pa(13.0)  # midpoint of measured envelope
    leak_g_per_min = params.leakage_cold_g_per_min * (p_sat_in / p_sat_ref) ** 1.3
    m_out_g = (leak_g_per_min / 60.0) * dt_s * (state.rh / 0.95)
    state.m_water_g = max(0.0, state.m_water_g + m_in_g - m_out_g)

    # 3) Convert water mass back to RH at current temperature
    # mixing ratio w = m_water / m_air;  RH = w · P / ((0.622+w)·P_sat)
    w = state.m_water_g / (params.air_mass_kg * 1000.0)
    p_air = 101_325.0
    rh_target = w * p_air / ((0.622 + w) * p_sat_in)
    # 4) First-order lag on top of dead-time (sensor + mass-transfer τ)
    alpha = dt_s / (params.tau_s + dt_s)
    state.rh = state.rh + alpha * (rh_target - state.rh)
    return state
```

**Source:** Mass-balance + Tetens saturation pressure are textbook (any HVAC / psychrometrics reference). Numerical values come from `docs/pid_calibration_notes.md` "Chamber Dynamics — first-pass system identification (2026-05-04)" — `[VERIFIED: read docs file]`. The `(p_sat/p_sat_ref)^1.3` exponent is `[ASSUMED]` — picked to interpolate measured 1.4 → 5.0 g/min over 8.8 → 17.5 °C; calibrate via fidelity test, not theory.

### Pattern 2: Replay loop using the production PID kernel

**What:** Drive `fc_core.vendor.simple_pid.PID` with the same gains and same logic as `fc_controller.control_loop()` — no ROS, just a `for` loop.
**When to use:** Every offline tuning experiment, every CI gate, every bug-replay.
**Example:**
```python
# fc_core/sim/run_replay.py
from fc_core.vendor.simple_pid import PID
from fc_core.sim.chamber_model import ChamberState, ChamberParams, step
from fc_core.sim.pwm_window import PwmWindow

def run(gains, duration_s, disturbance_fn, target_fn, dt=1.0):
    pid = PID(*gains, setpoint=0.0, sample_time=None,
              output_limits=(0.0, 1.0), auto_mode=False,
              differential_on_measurement=True)
    pid.set_auto_mode(True, last_output=0.15)  # bumpless preload — mirror controller line 253
    state = ChamberState(rh=0.94, m_water_g=70.0)  # cold-morning init
    pwm = PwmWindow(window_s=120.0, min_pulse_s=10.0, max_avg=0.90)
    rows = []
    for tick in range(int(duration_s / dt)):
        t = tick * dt
        target = target_fn(t)
        t_amb = disturbance_fn(t)
        error_pct = (state.rh - target) * 100.0
        if abs(error_pct) > 2.5:                        # mirror Mode C bypass
            duty = 1.0
            if pid.auto_mode: pid.set_auto_mode(False)
        else:
            if not pid.auto_mode: pid.set_auto_mode(True, last_output=1.0)
            duty = pid(error_pct, dt=dt)
        relay_state = pwm.tick(duty, dt)                # pure-Python duty→relay
        state = step(state, ChamberParams(), float(relay_state), t_amb, dt)
        rows.append((t, state.rh, target, duty, t_amb, *pid.components))
    return rows
```

**Critical:** the replay loop must mirror the **whole controller loop** — Mode C bypass at `|error|>2.5%`, bumpless preload, setpoint ramp, anti-windup (already in simple_pid). Otherwise the sim diverges from prod and stops being useful for tuning. Refactor the relevant parts of `fc_controller.control_loop()` (lines 425–441) into a pure helper `compute_duty(pid, current_humidity, effective_setpoint, ...)` that both `fc_controller` and `run_replay` call. **This refactor is a prerequisite plan, not a "nice to have"** — without it, sim and prod will drift apart on every controller change.

### Anti-Patterns to Avoid

- **Threading the model into `rclpy.spin()` directly.** The model is pure; the threading model belongs to whoever drives it. Wrap, don't entangle.
- **Letting `simple_pid.PID` see wall-clock time in sim.** simple_pid has a `time_fn` param (`vendor/simple_pid/pid.py:68`); pass `time_fn=lambda: sim_time` OR always pass explicit `dt=` (controller already does — `fc_controller.py:438`). Verify in tests that `pid._last_time` is never `time.monotonic()` during sim runs.
- **Coupling the disturbance source to ROS.** `disturbance.py` returns plain floats given `t`; never imports rclpy.
- **Hand-writing a 2nd-order model on day one.** The 19-min sustained-disturbance lag is real but the underlying mechanism is uncertain (see Open Questions). Start 1st-order; add 2nd-order only if the 4-h fidelity test fails to reproduce it.
- **Validating against synthetic-only data.** A model that passes synthetic step-response tests but fails the 2026-05-04 incident replay is a model that fits its tests, not the chamber.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PID kernel for sim | New PID implementation | `fc_core.vendor.simple_pid` (already vendored) | Sim and prod must use identical kernel — the entire reason sim is useful for tuning |
| Slow-PWM relay logic | Re-derive duty→relay translation | Pure-Python port of `fc_pwm_driver._tick()` (lines 94–140) | Min-pulse round-down, rolling cap, defensive-OFF semantics must match prod or sim under-models reality |
| Saturation pressure | Polynomial fit | Tetens approximation (single line) | 0.1% accuracy in 0–40 °C, sufficient for ±2% RMS fidelity target |
| RK4 integrator | Hand-roll RK4 | scipy.integrate.solve_ivp (validation only) OR forward-Euler at dt=1s | At τ/dt=600 the solver choice doesn't matter for engineering-grade RH(t) |
| 24-hour temperature curve | Random walks | Saved Timescale CSV from a real day | Real ambient curves carry diurnal asymmetry, cloud transients, clipping; synthetic curves are too smooth and let the controller cheat |

**Key insight:** the simulator's value is **fidelity to today's controller behavior under today's chamber dynamics**. Any component where sim diverges from prod (PID kernel, PWM logic, control flow) becomes an excuse for the sim to lie. Reuse production code wherever physically possible; isolate the divergent surface to the model itself.

## Common Pitfalls

### Pitfall 1: simple_pid's wall-clock leak

**What goes wrong:** `simple_pid.PID.__call__` reads `self.time_fn()` (default `time.monotonic`) on every call to populate `_last_time`. In a 100× real-time replay this gives nonsensical dt values *if* `dt=` is omitted on any call.
**Why it happens:** Optional `dt=` parameter; easy to forget in test code.
**How to avoid:** Always pass `dt=` explicitly in sim runs; add a unit test `test_sim_pid_isolation_from_wallclock` that monkeypatches `time.monotonic` to assert it's never called in a replay loop.
**Warning signs:** Replay results that change between runs of the same input; `pid.components` values that depend on whether the test machine is loaded.
**Cite:** `fc_core/vendor/simple_pid/pid.py:136-141` `[VERIFIED]`.

### Pitfall 2: Dead-time queue overflows under variable dt

**What goes wrong:** The 50 s dead-time FIFO assumes a steady tick rate. If dt fluctuates (which won't happen in pure-Python sim but will in ROS2 sim_mode under load), the queue's effective depth varies.
**Why it happens:** Treating queue depth as a proxy for time.
**How to avoid:** Store `(duty, dt)` pairs in the queue (as the example code above does) and accumulate `dt` until ≥ 50 s — never use `maxlen` as a time proxy. The deque's `maxlen=200` in the example is a memory bound, not a time bound.
**Warning signs:** Sim under high system load behaves differently than under low load.

### Pitfall 3: Median filter lag in production isn't modeled

**What goes wrong:** `fc_controller` smooths humidity through a `deque(maxlen=5)` with `median()` (line 134, 182). The sim's controller wrapper must do the same, or it sees a cleaner signal than prod and tunes to a different plant.
**Why it happens:** Sim sees raw model output; prod sees median-of-5 last samples.
**How to avoid:** In the replay tool, run the model output through the same `deque(maxlen=5) + median()` before feeding to the PID. Add a sensor-noise term to the model output (~ ±0.04 % normal noise per `pid_calibration_notes.md` "Per-pulse RH amplitude 0.13 % is below the sensor noise floor for SHT30 (~0.1 % typical)") so the median has work to do.
**Warning signs:** Sim is "too clean" — no jitter on `pid_output` even with Kd=4.0 and noise off.

### Pitfall 4: Modeling 999.32 (derivative filter unwired) in the sim

**What goes wrong:** Today's prod runs with the derivative filter param declared but never applied (see ROADMAP 999.32). If the sim implements the filter "correctly" before 999.32 ships, sim and prod don't match.
**Why it happens:** Easy to read the param, wire it up in the new code, and miss that prod doesn't use it.
**How to avoid:** Make the sim mirror prod's *current* state — derivative filter unwired. Add an experiment knob (`apply_d_filter: bool`) that lets you flip it on for "what would 999.32 fix?" comparisons without touching the default behavior. The sim becomes a tool for *justifying* 999.32, not for over-running it.
**Warning signs:** Sim's `pid_output` is dramatically smoother than the live trace from `fc.pid_output`.

### Pitfall 5: Replaying historical actuator commands AND closing the loop is a category error

**What goes wrong:** Two distinct replay modes and people mix them.
**Why it happens:** Both are called "replay."
**How to avoid:** Be explicit about two modes:
- **Open-loop replay (model fidelity test):** feed historical T(t) AND historical duty(t) to the model; ignore the PID; compare model RH(t) to measured RH(t). This validates the *plant model*.
- **Closed-loop replay (controller experiment):** feed historical T(t) only; let the PID compute duty from model RH; compare to measured RH(t). This validates the *controller against the modeled plant*.
The fidelity gate is open-loop. The "would Ki=0.001 fix the limit cycle?" experiment is closed-loop. Different CSVs, different acceptance criteria.

### Pitfall 6: ROS2 sim_time and the existing simulation_mode are NOT the same thing

**What goes wrong:** `simulation_mode: true` in `fc_config.yaml` is a per-subsystem boolean (`sensor_simulation_mode`, `actuator_simulation_mode`) — has nothing to do with ROS2's `use_sim_time` parameter or `/clock` topic.
**Why it happens:** Same word, different concepts.
**How to avoid:** Keep using the existing `sensor_simulation_mode` flag. The sim sensor publishes at the configured `sensor_read_interval` driven by `rclpy.create_timer` on the real wallclock; **that's fine** because the `dt=` passed to model.step() comes from `now - last_tick`, so 100× speed (if ever needed in ROS) requires a separate sim_time bridge — explicitly out of scope. For 100× replay use the offline tool, NOT a ROS-based sim.
**Warning signs:** Anybody asking how to make `ros2 launch fc_core fc.launch.py` run faster than wall-clock — that's the wrong question, point them at `run_replay.py`.

### Pitfall 7: SHT30 sensor lag bundled into the chamber τ

**What goes wrong:** The "10 min τ" measured in `pid_calibration_notes.md` includes everything between mister-on and SHT30-reading-changes — chamber air mixing + mass transfer to wet surfaces + sensor's own response. The sim collapses these into one τ. That's fine for control-loop tuning but makes the sim lie about *sensor placement* questions.
**Why it happens:** Empirical τ is what you can measure end-to-end.
**How to avoid:** Document this scope explicitly. If anyone asks "what if we move the SHT30 closer to the mister?" the answer is "shape (b) Gazebo, not shape (a)."

### Pitfall 8: 19-min sustained-disturbance lag — what won't the model catch

**What goes wrong:** Per `pid_calibration_notes.md`: temp peak at 13:55 → RH peak at 14:14, 19-min lag. This is *not* the 50-s impulse dead time — it's the chamber's effective second-order response to a sustained driver shift. A 1st-order ODE will under-estimate this lag.
**Why it happens:** Sustained-disturbance lag is dominated by integrator windup + chamber's slow approach to a new equilibrium, NOT just dead time + τ.
**How to avoid:** Document explicitly that the 1st-order model under-reports the 19-min lag. The fidelity test will *show* this — that's good information. If the gap is < 5 min the 1st-order is good enough; if > 10 min, add a 2nd-order layer (cascaded τ for sensor + chamber, or explicit wall-condensation buffer).
**Warning signs:** Replay's modeled RH(t) leads measured RH(t) by ≥ 10 minutes during the 13:55 temp peak.

## Runtime State Inventory

This phase is a greenfield code addition (new `fc_core/sim/` package), not a rename or migration. Section omitted per researcher protocol.

## Code Examples

### Synthetic 24-h disturbance (CI gate)

```python
# fc_core/sim/disturbance.py
import math

def synthetic_uruguay_autumn(t_s: float) -> float:
    """24-h ambient T curve modeled on Uruguay autumn: 8 °C dawn, 18 °C peak, sinusoidal."""
    h = (t_s / 3600.0) % 24.0
    return 13.0 + 5.0 * math.sin(math.pi * (h - 4.0) / 12.0)

def replay_from_csv(path: str):
    """Returns (t_s -> T_amb_c) interpolating linearly between rows."""
    import csv, bisect
    times, temps = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            times.append(float(row['t_s']))
            temps.append(float(row['t_amb_c']))
    def fn(t):
        i = bisect.bisect_right(times, t) - 1
        if i < 0: return temps[0]
        if i >= len(times) - 1: return temps[-1]
        frac = (t - times[i]) / (times[i+1] - times[i])
        return temps[i] + frac * (temps[i+1] - temps[i])
    return fn
```

### Pure-Python PWM window

```python
# fc_core/sim/pwm_window.py — mirrors fc_pwm_driver.py:94-140
class PwmWindow:
    def __init__(self, window_s=120.0, min_pulse_s=10.0, max_avg=0.90):
        self.window_s, self.min_pulse_s, self.max_avg = window_s, min_pulse_s, max_avg
        self._elapsed = window_s + 1.0  # force lock-in at t=0
        self._on_seconds = 0.0
        self._history = []
        self._latest_duty = 0.0

    def set_duty(self, duty: float):
        self._latest_duty = max(0.0, min(1.0, duty))

    def tick(self, duty: float, dt: float) -> bool:
        self.set_duty(duty)
        self._elapsed += dt
        if self._elapsed >= self.window_s:
            d = self._latest_duty
            if self._history:
                n = len(self._history); s = sum(self._history)
                if (s + d) / (n + 1) > self.max_avg:
                    d = max(0.0, self.max_avg * (n + 1) - s)
            d = max(0.0, min(1.0, d))
            on_sec = d * self.window_s
            if 0.0 < on_sec < self.min_pulse_s:
                on_sec = 0.0
            self._on_seconds = on_sec
            self._history.append(on_sec / self.window_s)
            if len(self._history) > 300: self._history.pop(0)
            self._elapsed = 0.0
        return self._elapsed < self._on_seconds
```

### Fidelity test against incident fixture

```python
# test/test_replay_fidelity.py
import csv, math, pytest
from fc_core.sim.chamber_model import ChamberState, ChamberParams, step
from pathlib import Path

FIXTURE = Path(__file__).parent / 'fixtures' / 'incident_2026_05_04.csv'

def test_open_loop_fidelity_2026_05_04_temp_peak():
    """Feed measured duty(t) + measured T_amb(t); model RH(t) must track measured RH(t) within ±2% RMS."""
    if not FIXTURE.exists():
        pytest.skip('fixture missing — extract via scripts/extract_incident.py')
    with FIXTURE.open() as f:
        rows = list(csv.DictReader(f))
    state = ChamberState(rh=float(rows[0]['rh']), m_water_g=70.0)
    params = ChamberParams()
    sq_err = 0.0
    n = 0
    for i, row in enumerate(rows[1:], 1):
        dt = float(row['t_s']) - float(rows[i-1]['t_s'])
        if dt <= 0: continue
        state = step(state, params,
                     duty=float(row['duty']),
                     t_amb_c=float(row['t_amb_c']),
                     dt_s=dt)
        sq_err += (state.rh - float(row['rh'])) ** 2
        n += 1
    rms = math.sqrt(sq_err / n)
    assert rms < 0.02, f'fidelity gate: RMS error {rms:.4f} > 0.02 (2 % RH)'
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Canned-value sim (`random.uniform` in `fc_sensors.py:115-120`) | Physics-driven ODE | This phase | Controller tests exercise actual closed-loop dynamics, not random walks |
| Live-only PID tuning (gated on weather + farmer presence) | Replay-driven tuning | This phase | Iteration cadence: 1 idea/day → 1 idea/minute |
| simple_pid v2.0.0 | Same — keep vendored | No change | Sim/prod kernel parity is non-negotiable |

**Deprecated/outdated:** None — this is greenfield within `fc_core`. The existing `simulation_mode: true` path (`fc_sensors.py:50-53, 112-132`) is the seam to upgrade, not deprecate.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Forward-Euler at dt=1s is sufficient (no need for RK45) | Standard Stack | Medium — if integrator is stiff at low duty, RH drifts; mitigation: scipy cross-check test |
| A2 | Leakage scales as `(p_sat/p_sat_ref)^1.3` | Code Examples (chamber_model.py) | Medium — if exponent is wrong, mid-range temps mis-fit; calibrate via fidelity gate |
| A3 | 1st-order ODE adequately captures 19-min sustained-disturbance lag | Pitfalls #8, Open Questions | High — may force 2nd-order rebuild after Wave 1; budget contingency in plan |
| A4 | ±2% RMS RH is the right fidelity threshold | Validation | Medium — too loose = sim doesn't reproduce limit cycles; too tight = unattainable; revisit after first replay |
| A5 | Sensor noise floor ±0.04 % normal is realistic for SHT30 | Pitfalls #3 | Low — conservative; match measured tick-to-tick variance from `fc.humidity` series |
| A6 | A pure-Python replay of 24h × 1 Hz finishes in < 60 s (CI budget) | CI Gate | Low — 86,400 ticks of arithmetic is sub-second in CPython; verify in Wave 0 |
| A7 | Shape (b) Gazebo is deferable indefinitely | Summary | Low — multi-chamber + Phase 24 vision are the trigger; not on near-term roadmap |
| A8 | Refactoring `fc_controller.control_loop()` to expose a pure `compute_duty()` helper is acceptable | Pattern 2 | Medium — touches prod hot path; needs careful test coverage in same plan |

## Open Questions

1. **What causes the 19-min sustained-disturbance lag?**
   - What we know: temp peaked 13:55, RH peaked 14:14 → 19-min lag, *not* the 50-s impulse dead time.
   - What's unclear: sensor lag stack? mass transfer to wet surfaces? integrator's continued push past natural peak (controller artifact, not chamber)?
   - Recommendation: build 1st-order model first, run open-loop fidelity test. If RH peak lag in sim is ~10 min (just τ), add an explicit sensor lag (~3-min cascaded τ for SHT30 polymer membrane response). If still wrong, add wall-condensation buffer (water mass coupled by 2nd τ_wall ≈ 5-7 min). Don't speculate — measure.

2. **How accurate is the 6 g/min mister estimate at extreme operating points?**
   - What we know: triangulated from 3 operating points; consistent within ~20 %.
   - What's unclear: temperature dependence of ultrasonic output (literature says ~independent, but unverified for this specific transducer).
   - Recommendation: add `mister_rate_g_per_min` as a `ChamberParams` field; run sensitivity analysis (5, 6, 7 g/min) on incident-replay fidelity to bound uncertainty.

3. **Does the bridge's median-filter (Phase 999.16 downsampling) affect what the sim should compare against?**
   - What we know: bridge writes raw points; chart downsampling happens at query time.
   - What's unclear: when extracting the incident CSV from Timescale, do we want raw 5 Hz points or some aggregation?
   - Recommendation: extract raw points (`SELECT time, value FROM telemetry WHERE topic='fc.humidity' AND time BETWEEN ... ORDER BY time`); resample to 1 Hz in Python by linear interpolation; document the choice.

4. **Should `fc_controller` be refactored to expose `compute_duty()` as a pure helper (used by both prod and sim)?**
   - What we know: today's `control_loop()` is a 100-line method that mixes ROS state mutation with control math.
   - What's unclear: scope creep risk — refactor could touch hot path.
   - Recommendation: yes, but as a **non-functional refactor** with full coverage (the existing `test_pid_kernel.py` + new `test_compute_duty.py` exhaustive over all three modes — Mode A normal, Mode C bypass, Mode A→C and C→A transitions). Sequence: refactor first plan, sim consumes the helper second plan.

5. **CI gate budget — can a "24h synthetic grow" assertion run in colcon's per-plan time limit?**
   - What we know: the existing `test/` suite is fast (<10 s based on file count). 86,400 × ~5 µs operations = ~0.4 s for the model alone; PID call adds ~10 µs each = ~0.9 s total.
   - What's unclear: pytest discovery overhead, fixture loading.
   - Recommendation: target < 5 s for the 24h CI gate; if it exceeds, split into smoke (1h) on every commit + nightly 24h.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3 | All sim code | ✓ | 3.12 (ROS Jazzy) `[VERIFIED: ROS Jazzy bundles Python 3.12]` | — |
| numpy | model math (light use) | ✓ | shipped with rclpy `[VERIFIED]` | — |
| scipy | reference integrator (validation only) | unknown — check on elder-plops | — | mark scipy tests `@pytest.mark.skipif(not has_scipy)` |
| pytest | tests | ✓ | per `setup.py:32` `[VERIFIED: read setup.py]` | — |
| Timescale (read) | Generate incident fixture once | ✓ | running on elder-plops `[VERIFIED: bridge schema]` | — |
| Timescale (read at runtime) | Tests reading live DB | n/a — fixtures are checked-in CSVs | — | by design |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** scipy (reference-integrator cross-check) — skip the cross-check test if scipy missing.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (per `setup.py:32` and existing `fc_core/test/`) |
| Config file | `src/chambers/fc-core/setup.cfg` (existing) |
| Quick run command | `pytest src/chambers/fc-core/fc_core/test/test_chamber_model.py -x` |
| Full suite command | `colcon test --packages-select fc_core && colcon test-result --verbose` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIM-01 | Model conserves mass at duty=0 (decay only) | unit | `pytest test_chamber_model.py::test_decay_to_equilibrium -x` | ❌ Wave 0 |
| SIM-02 | Dead time θ ≈ 50s on impulse duty pulse | unit | `pytest test_chamber_model.py::test_dead_time_impulse -x` | ❌ Wave 0 |
| SIM-03 | Steady-state duty matches measured at cold operating point (1.4/6.0 ≈ 0.23) | unit | `pytest test_chamber_model.py::test_steady_state_cold -x` | ❌ Wave 0 |
| SIM-04 | Steady-state duty matches measured at hot operating point (5.0/6.0 ≈ 0.83) | unit | `pytest test_chamber_model.py::test_steady_state_hot -x` | ❌ Wave 0 |
| SIM-05 | Open-loop fidelity vs 2026-05-04 incident: RMS < 2% RH | integration | `pytest test_replay_fidelity.py -x` | ❌ Wave 0 |
| SIM-06 | Closed-loop replay reproduces 28-min integrator limit cycle (Ki=0.002) | integration | `pytest test_replay_fidelity.py::test_reproduces_limit_cycle -x` | ❌ Wave 0 |
| SIM-07 | Closed-loop replay shows limit cycle gone at Ki=0.001 (validates today's fix) | integration | `pytest test_replay_fidelity.py::test_ki_halving_kills_cycle -x` | ❌ Wave 0 |
| SIM-08 | 24h synthetic grow: RH stays within ±1% of target | integration / CI gate | `pytest test_synthetic_grow.py::test_24h_within_band -x` | ❌ Wave 0 |
| SIM-09 | PID called with explicit `dt=` everywhere in sim (no wall-clock leak) | unit | `pytest test_chamber_model.py::test_no_wallclock_in_sim -x` | ❌ Wave 0 |
| SIM-10 | `fc_sensors.py` sim branch publishes physically-consistent RH/T at runtime | smoke | `pytest test/test_sensors.py::test_sim_mode_uses_chamber_model` | ❌ Wave 0 (extension) |

### Sampling Rate

- **Per task commit:** `pytest src/chambers/fc-core/fc_core/test/test_chamber_model.py -x` (~2s)
- **Per wave merge:** `colcon test --packages-select fc_core` (full suite, ~30s with new tests)
- **Phase gate:** Full suite green + manual review of replay plot against measured trace

### Wave 0 Gaps

- [ ] `fc_core/sim/__init__.py` — package marker
- [ ] `fc_core/sim/chamber_model.py` — ODE module (no test yet)
- [ ] `fc_core/sim/pwm_window.py` — pure-Python PWM port
- [ ] `fc_core/sim/disturbance.py` — T(t) sources
- [ ] `fc_core/sim/run_replay.py` — CLI loop
- [ ] `fc_core/test/test_chamber_model.py` — covers SIM-01..04, SIM-09
- [ ] `fc_core/test/test_replay_fidelity.py` — covers SIM-05, SIM-06, SIM-07
- [ ] `fc_core/test/test_synthetic_grow.py` — covers SIM-08
- [ ] `fc_core/test/fixtures/incident_2026_05_04.csv` — 4-hour slice from Timescale
- [ ] `scripts/extract_incident.py` — one-off Timescale → CSV exporter (lives outside test/)

## Project Constraints (from CLAUDE.md)

The project's CLAUDE.md is brief on coding rules; key directives extracted:
- **Build:** `colcon build --symlink-install` for Python development; `colcon test --packages-select fc_core` for testing. New `sim/` subpackage must be added to `setup.py:packages` list.
- **Linting:** `ament_flake8` and `ament_pep257` apply; new files must pass.
- **Hardware vs sim flag:** `simulation_mode` parameters in `fc_config.yaml` are the authoritative seam; new code must honor `sensor_simulation_mode` (currently `false` on prod) without breaking real-hardware path.
- **No co-author trailer on commits** (user memory).
- **Karpathy directives apply:** simplicity first (start with 1st-order ODE), surgical changes (sim/ is greenfield, no edits to fc_controller until sim consumer-side is ready), goal-driven (fidelity gate + limit-cycle reproduction are the success criteria).

## Sources

### Primary (HIGH confidence)
- `[VERIFIED: read]` `docs/pid_calibration_notes.md` — system ID values, observed limit cycles, 19-min lag, 50-s dead time, mister output, leakage scaling
- `[VERIFIED: read]` `src/chambers/fc-core/fc_core/fc_controller.py` lines 11, 134, 151-161, 252-260, 342-460 — controller loop structure, PID integration, Mode C bypass, bumpless transfer
- `[VERIFIED: read]` `src/chambers/fc-core/fc_core/fc_sensors.py` lines 49-53, 112-132 — existing `simulation_mode` seam
- `[VERIFIED: read]` `src/chambers/fc-core/fc_core/fc_pwm_driver.py` lines 94-140 — duty→relay logic to mirror in pure Python
- `[VERIFIED: read]` `src/chambers/fc-core/fc_core/vendor/simple_pid/pid.py` v2.0.0 — kernel that sim must reuse; `time_fn` and `dt=` mechanics
- `[VERIFIED: read]` `src/chambers/fc-core/fc_core/test/test_pid_kernel.py` — existing test pattern for new tests
- `[VERIFIED: read]` `src/chambers/fc-core/setup.py` — package layout for adding `fc_core.sim`
- `[VERIFIED: read]` `src/mission-control/bridge/src/index.js` lines 207-220, 357-358 — Timescale schema (`telemetry(time, topic, value)`) for incident-fixture extraction
- `[VERIFIED: read]` `.planning/ROADMAP.md` 999.27 / 999.29 / 999.32 entries — composes-with relationships

### Secondary (MEDIUM confidence)
- `[CITED: docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html]` solve_ivp RK45/LSODA semantics — used only for cross-check
- `[CITED: textbook]` Tetens approximation for saturation pressure (any HVAC reference)
- `[CITED: textbook]` First-order plant + dead-time = "FOPDT" model — Skogestad SIMC tuning rules already used in `pid_calibration_notes.md` line 173

### Tertiary (LOW confidence)
- `[ASSUMED]` `(p_sat/p_sat_ref)^1.3` exponent for leakage temperature scaling — picked to fit 1.4 g/min at 8.8°C and 5.0 g/min at 17.5°C; calibrate empirically in fidelity test, don't trust the form
- `[ASSUMED]` 1st-order ODE adequately captures 19-min sustained-disturbance lag — mark as Wave 1 risk; contingency for 2nd-order rebuild

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — numpy + pytest are already-shipped; scipy optional with fallback
- Architecture: HIGH — pattern matches the codebase's existing layering; `simulation_mode` seam is already there
- Physics model: MEDIUM — system-ID values are first-pass empirical; 19-min lag mechanism unresolved
- Pitfalls: HIGH — derived from concrete reading of every prod file involved
- Validation: MEDIUM — ±2% RMS threshold is an educated guess until first replay runs

**Research date:** 2026-05-04
**Valid until:** 2026-06-03 (30 days; chamber-physics + ROS Jazzy environment are stable; longer-lived than typical web-stack research)

## Appendix: Stretch shape (b) — Gazebo full digital twin

Out of scope for this phase; documented for later reference.

**Trigger conditions** (any one):
- 999.6 multi-chamber lifts off — sim must run N parallel chambers with shared environment
- Phase 24 ML vision lifts off — vision pipeline needs synthetic camera frames with controllable lighting/condensation
- 999.7 rover lifts off — physical sim dominates the value

**Approach when triggered:**
1. Stand up Gazebo (Harmonic, ROS2 Jazzy compatible) with a simple box geometry matching the 2.4×1.2×2.0 m grow tent.
2. Reuse `fc_core.sim.chamber_model` as the physics core — wrap it in a custom Gazebo SystemPlugin that drives sensor topics via the `gz_ros_bridge`.
3. SHT30 / SCD41 sensor models with realistic noise (use the same `sensor_noise_std_pct` from `ChamberParams`).
4. Camera plugin via stock `gz::sensors::CameraSensor` plus a condensation-overlay shader (the Phase 24 / 999.26 angle).

**Cost estimate:** 2-3 weeks of Gazebo plugin work; depends heavily on whether the user already has a working Gazebo + ROS2 Jazzy bridge (none observed in current `src/` — `simulation` service in docker-compose was for a *different* purpose, not chamber thermal sim).

**Re-evaluate:** when the first multi-chamber or vision phase enters discuss-phase, check whether shape (a) is genuinely insufficient before opening this can.
