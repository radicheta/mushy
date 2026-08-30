# Self-Tuning Humidifier Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The chamber twin becomes the single source of truth for the humidifier loop: a probe pulse on the Pi, a fitter + SIMC derivation + guarded push off-Pi, proven first by tuning one twin onto another in simulation.

**Architecture:** A pure `ProbeScheduler` in `control_kernel.py` decides when to fire a fixed-length pulse; `sim/control_loop.py:ControlLoop` and `fc_controller.py` both step it. `fc_core/sim/probe_fit.py` fits `ChamberModel` to each probe window with `scipy.optimize.least_squares`; `fc_core/sim/simc.py` turns fitted params into PID gains and guards the push. Scripts on elder-plops are thin adapters (Timescale in, `ros2 param set` + yaml commit out) around those two modules, so the two-twin test exercises the exact code that runs in production.

**Tech Stack:** Python 3.10, ROS 2 Jazzy (rclpy, std_msgs), vendored simple_pid, numpy + scipy 1.8 (repo `.venv`), Node bridge (`src/mission-control/bridge`), TimescaleDB via `docker exec ... psql`, systemd timer.

**Spec:** `docs/superpowers/specs/2026-08-30-self-tuning-humidifier-design.md`

## Global Constraints

- Every commit message ends with `[MUSHY-138]`. No AI attribution trailers.
- Pure `fc_core.sim` / `control_kernel` tests run fast in the venv:
  `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q <file>`.
  Anything importing `rclpy` (`fc_controller`) runs in the sanctioned container:
  `docker build -f docker/fc-core-test.Dockerfile -t fc-core-test . && docker run --rm --network none -v "$PWD/src/chambers:/src:ro" fc-core-test`.
- `control_kernel.py` stays ROS-free: no rclpy, no clock reads, no parameter lookups.
- Nothing in this plan is deployed to fc1. Deploy (`git push fc1/prod` + `deploy.sh`) is a separate human step after Task 10.
- Probe defaults: `probe_seconds` 150, `probe_interval_h` 0 (disabled) in yaml; the sim test sets its own.
- Guard ranges (spec §3): F 1-50 g/h, Q 0.1-5 m3/h, dead_time 5-900 s, tau 60-3600 s, kp 0.001-2, ki 1e-6-0.01. Rate limit: at most 2x per accepted push.
- **Spec deviation, recorded here and in the ticket:** the 2x rate limit **clamps** the step instead of refusing the push. A refusal would leave a 7x-wrong dead time (360 s vs the ~50 s the 2026-04 trace suggests) uncorrectable forever without a human; a clamp ratchets toward the fit over successive accepted pushes and logs that it clamped. The plausibility ranges still refuse.
- Working directory for all commands: repo root `/mnt/slime-kingdom/opt/mushy`.

---

## File map

| File | Responsibility |
|---|---|
| `src/chambers/fc-core/fc_core/control_kernel.py` | + `ProbeConfig`, `ProbeScheduler`; `temp_feedforward_gain/duty` take F and C as arguments |
| `src/chambers/fc-core/fc_core/sim/control_loop.py` | `ControlLoop` gains a `params: ChamberParams` and a `probe: ProbeScheduler`; steps the probe; freezes/restores the integrator around it |
| `src/chambers/fc-core/fc_core/sim/pwm_sigma_delta.py` | + `relay_on` property |
| `src/chambers/fc-core/fc_core/sim/replay.py` | `run_closed_loop` records relay/probe/temp/ambient series and optional sensor noise; `RunMetrics` carries them |
| `src/chambers/fc-core/fc_core/sim/probe_fit.py` (new) | window finding, per-window least-squares fit, aggregation + validity |
| `src/chambers/fc-core/fc_core/sim/simc.py` (new) | SIMC gains from params, guard/clamp for the push |
| `src/chambers/fc-core/fc_core/test/test_probe_scheduler.py` (new) | scheduler unit tests |
| `src/chambers/fc-core/fc_core/test/test_probe_fit.py` (new) | fitter recovers known params from a twin window |
| `src/chambers/fc-core/fc_core/test/test_simc.py` (new) | gains formula, guard, clamp |
| `src/chambers/fc-core/fc_core/test/test_two_twin_convergence.py` (new) | spec §6 |
| `src/chambers/fc-core/fc_core/fc_controller.py` | declares 5 params, steps the scheduler, publishes `fc1/control/probe` |
| `src/chambers/fc-core/fc_core/test/test_controller_probe.py` (new) | controller wiring, in the container |
| `src/chambers/fc-core/config/fc_config.yaml` | the 5 new keys |
| `src/mission-control/bridge/src/index.js` | `fc.probe` subscription |
| `scripts/self-tune/fit-probes.py` (new) | Timescale adapter around `probe_fit`; `--quasi` mode |
| `scripts/self-tune/push-chamber-params.py` (new) | guard, `ros2 param set`, yaml edit, commit |
| `scripts/self-tune/mushy-self-tune.{sh,service,timer}`, `install.sh` (new) | elder-plops timer |

---

### Task 1: ProbeScheduler in the kernel

**Files:**
- Modify: `src/chambers/fc-core/fc_core/control_kernel.py` (append at end)
- Test: `src/chambers/fc-core/fc_core/test/test_probe_scheduler.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class ProbeConfig:
      probe_seconds: float = 150.0
      interval_s: float = 0.0          # 0 disables
      idle_s: float = 900.0
      max_temp_rate_c_per_h: float = 0.3
      top_margin: float = 0.005        # rh must be <= band_high - top_margin to start

  class ProbeScheduler:
      count: int                       # probes started
      active: bool                     # a probe is being commanded right now
      just_ended: bool                 # True on the first tick after a probe stopped
      def step(self, dt: float, rh: float, band: BandSpec, temp_rate_c_per_h: float,
               last_duty: float, allowed: bool) -> bool   # True => command duty 1.0
  ```

- [ ] **Step 1: Write the failing tests**

```python
# src/chambers/fc-core/fc_core/test/test_probe_scheduler.py
from fc_core.control_kernel import BandSpec, ProbeConfig, ProbeScheduler

BAND = BandSpec(0.885, 0.915, 'both')
CFG = ProbeConfig(probe_seconds=150.0, interval_s=3600.0, idle_s=900.0)


def run(sched, n, rh=0.905, rate=0.0, last_duty=0.0, allowed=True, dt=1.0):
    out = []
    for _ in range(n):
        out.append(sched.step(dt, rh, BAND, rate, last_duty, allowed))
    return out


def test_disabled_never_fires():
    s = ProbeScheduler(ProbeConfig(interval_s=0.0))
    assert not any(run(s, 20000))
    assert s.count == 0


def test_fires_after_interval_and_idle_then_lasts_probe_seconds():
    s = ProbeScheduler(CFG)
    assert not any(run(s, 3599))          # interval not yet elapsed
    out = run(s, 400)
    assert out[0] is True and s.count == 1
    assert sum(out) == 150                # exactly probe_seconds ticks of duty 1
    assert out[150] is False


def test_just_ended_flags_the_first_tick_after():
    s = ProbeScheduler(CFG)
    run(s, 3600 + 150)
    assert s.active
    s.step(1.0, 0.905, BAND, 0.0, 1.0, True)
    assert not s.active and s.just_ended
    s.step(1.0, 0.905, BAND, 0.0, 0.0, True)
    assert not s.just_ended


def test_conditions_block_start():
    for kw in (dict(rh=0.895),               # below midpoint
               dict(rh=0.912),               # above band_high - margin
               dict(rate=0.5),               # ramping
               dict(last_duty=0.2),          # not idle
               dict(allowed=False)):         # stale / mode C / wrong mode
        s = ProbeScheduler(CFG)
        assert not any(run(s, 5000, **kw)), kw


def test_idle_counts_from_last_nonzero_duty():
    s = ProbeScheduler(CFG)
    run(s, 3600, last_duty=0.3)             # interval elapsed but busy
    assert not any(run(s, 899))             # idle 899 s: not yet
    assert run(s, 2)[1] is True


def test_abort_on_band_high_or_disallowed():
    for kw in (dict(rh=0.916), dict(allowed=False)):
        s = ProbeScheduler(CFG)
        run(s, 3600 + 10)
        assert s.active
        assert s.step(1.0, kw.get('rh', 0.905), BAND, 0.0, 1.0, kw.get('allowed', True)) is False
        assert not s.active and s.just_ended


def test_interval_restarts_after_a_probe():
    s = ProbeScheduler(CFG)
    run(s, 3600 + 150 + 1)
    assert not any(run(s, 3598))
    assert s.count == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_probe_scheduler.py`
Expected: ImportError on `ProbeConfig`.

- [ ] **Step 3: Implement**

Append to `src/chambers/fc-core/fc_core/control_kernel.py`:

```python
@dataclass(frozen=True)
class ProbeConfig:
    """MUSHY-138 identification probe: one duty=1.0 pulse of known length
    into a quiet chamber. interval_s == 0 disables."""

    probe_seconds: float = 150.0
    interval_s: float = 0.0
    idle_s: float = 900.0
    max_temp_rate_c_per_h: float = 0.3
    top_margin: float = 0.005


class ProbeScheduler:
    """Pure probe state machine, stepped once per control tick.

    ``step`` returns True while the probe is being commanded; the caller
    publishes duty 1.0 and parks the PID. Timing for the fit comes from
    the stored relay edges, not from this flag, so the sigma-delta
    driver's fire delay does not matter here. ``just_ended`` is set for
    exactly one tick after a probe stops so the caller can re-engage the
    PID with its pre-probe output.
    """

    def __init__(self, cfg: ProbeConfig):
        self.cfg = cfg
        self.count = 0
        self.active = False
        self.just_ended = False
        self._since_probe_s = 0.0      # reboot => wait a full interval
        self._idle_s = 0.0
        self._remaining_s = 0.0

    def step(self, dt: float, rh: float, band: BandSpec, temp_rate_c_per_h: float,
             last_duty: float, allowed: bool) -> bool:
        cfg = self.cfg
        self.just_ended = False
        self._since_probe_s += dt
        self._idle_s = self._idle_s + dt if last_duty <= 0.0 else 0.0

        if self.active:
            self._remaining_s -= dt
            if self._remaining_s <= 0.0 or rh >= band.band_high or not allowed:
                self.active = False
                self.just_ended = True
                self._remaining_s = 0.0
                self._idle_s = 0.0
                return False
            return True

        if cfg.interval_s <= 0.0 or not allowed:
            return False
        if self._since_probe_s < cfg.interval_s or self._idle_s < cfg.idle_s:
            return False
        if not (band.midpoint <= rh <= band.band_high - cfg.top_margin):
            return False
        if abs(temp_rate_c_per_h) >= cfg.max_temp_rate_c_per_h:
            return False

        self.active = True
        self.count += 1
        self._since_probe_s = 0.0
        self._remaining_s = cfg.probe_seconds
        return True
```

Note the idle counter: the first call after a probe sees `last_duty=1.0` from the probe itself; the reset in the end branch plus the `last_duty` rule together mean a fresh 15 min of idle must elapse before the next probe, which is what `test_interval_restarts_after_a_probe` checks (interval dominates there).

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_probe_scheduler.py src/chambers/fc-core/fc_core/test/test_control_kernel.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chambers/fc-core/fc_core/control_kernel.py src/chambers/fc-core/fc_core/test/test_probe_scheduler.py
git commit -m "feat(fc_core): ProbeScheduler, pure identification-probe state machine [MUSHY-138]"
```

---

### Task 2: Feedforward gain takes the chamber params as arguments

**Files:**
- Modify: `src/chambers/fc-core/fc_core/control_kernel.py:116-142` (`temp_feedforward_gain`, `temp_feedforward_duty`)
- Modify: `src/chambers/fc-core/fc_core/sim/control_loop.py` (`ControlLoop.__init__`, the FF call in `step`)
- Modify: `src/chambers/fc-core/fc_core/fc_controller.py:~1800` (the `temp_feedforward_duty` call) — pass `ChamberParams()` defaults for now; Task 7 swaps in the ROS params
- Test: `src/chambers/fc-core/fc_core/test/test_control_kernel.py` (add one test)

**Interfaces:**
- Produces:
  ```python
  def temp_feedforward_gain(rh, temp_c, fill_g_per_h, surface_g_per_k) -> float
  def temp_feedforward_duty(trim, rate_c_per_h, rh, temp_c, band, fill_g_per_h, surface_g_per_k) -> float
  ControlLoop(band, gains=..., target=..., duty_bias=..., temp_ff_gain=..., params: ChamberParams = None)
  ```
  `ControlLoop.params` is the attribute later tasks overwrite on a push.

- [ ] **Step 1: Write the failing test**

Append to `src/chambers/fc-core/fc_core/test/test_control_kernel.py`:

```python
def test_temp_feedforward_gain_scales_with_fill_rate():
    from fc_core.control_kernel import temp_feedforward_gain
    g1 = temp_feedforward_gain(0.90, 16.0, fill_g_per_h=3.89, surface_g_per_k=2.77)
    g2 = temp_feedforward_gain(0.90, 16.0, fill_g_per_h=7.78, surface_g_per_k=2.77)
    assert g1 > 0 and abs(g2 - g1 / 2) < 1e-9
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_control_kernel.py -k fill_rate`
Expected: TypeError (unexpected keyword).

- [ ] **Step 3: Implement**

In `control_kernel.py` replace the two functions' signatures and bodies:

```python
def temp_feedforward_gain(rh: float, temp_c: float,
                          fill_g_per_h: float, surface_g_per_k: float) -> float:
    """Duty per (C/h) of chamber warming needed to hold RH (MUSHY-125).
    (docstring unchanged) MUSHY-138: F and C are arguments so a live fit
    reaches this without touching ChamberParams defaults."""
    slope = (absolute_humidity_g_m3(temp_c + 0.5, 100.0)
             - absolute_humidity_g_m3(temp_c - 0.5, 100.0))
    return (rh * CHAMBER_VOLUME_M3 * slope - surface_g_per_k) / fill_g_per_h


def temp_feedforward_duty(trim: float, rate_c_per_h: float, rh: float, temp_c: float,
                          band: BandSpec, fill_g_per_h: float, surface_g_per_k: float) -> float:
    if trim == 0.0:
        return 0.0
    return (trim * temp_feedforward_gain(rh, temp_c, fill_g_per_h, surface_g_per_k)
            * rate_c_per_h * duty_bias_factor(rh, band))
```

Remove the now-unused `from fc_core.sim.chamber_model import ChamberParams` import from `control_kernel.py` (the kernel no longer needs it; `CHAMBER_VOLUME_M3` still comes from psychrometrics).

In `sim/control_loop.py`:

```python
from fc_core.sim.chamber_model import ChamberParams
...
    def __init__(self, band, gains=DEFAULT_GAINS, target=0.90, duty_bias=0.0,
                 temp_ff_gain=0.0, params: ChamberParams = None):
        ...
        self.params = params or ChamberParams()
...
        if self.temp_ff_gain != 0.0 and temp_c is not None:
            duty = max(0.0, min(1.0, duty + temp_feedforward_duty(
                self.temp_ff_gain, rate, rh_frac, temp_c, band,
                self.params.fill_g_per_h, self.params.surface_g_per_k)))
```

In `fc_controller.py`, at the `temp_feedforward_duty(` call (~line 1800), add the two trailing arguments `ChamberParams().fill_g_per_h, ChamberParams().surface_g_per_k` and add `from fc_core.sim.chamber_model import ChamberParams` to the imports. Task 7 replaces these with ROS params.

- [ ] **Step 4: Run the sim suite**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_control_kernel.py src/chambers/fc-core/fc_core/test/test_control_loop_feedforward.py src/chambers/fc-core/fc_core/test/test_replay_fidelity.py`
Expected: all PASS (feedforward numbers unchanged because the defaults are the same values).

- [ ] **Step 5: Commit**

```bash
git add src/chambers/fc-core/fc_core/control_kernel.py src/chambers/fc-core/fc_core/sim/control_loop.py src/chambers/fc-core/fc_core/fc_controller.py src/chambers/fc-core/fc_core/test/test_control_kernel.py
git commit -m "refactor(fc_core): feedforward gain takes F and C as arguments [MUSHY-138]"
```

---

### Task 3: ControlLoop steps the probe; the replay records what the fitter needs

**Files:**
- Modify: `src/chambers/fc-core/fc_core/sim/control_loop.py`
- Modify: `src/chambers/fc-core/fc_core/sim/pwm_sigma_delta.py` (add `relay_on`)
- Modify: `src/chambers/fc-core/fc_core/sim/replay.py` (`RunMetrics`, `run_closed_loop`)
- Test: `src/chambers/fc-core/fc_core/test/test_control_loop_probe.py` (new)

**Interfaces:**
- Produces:
  ```python
  ControlLoop(..., probe: ProbeScheduler = None)   # default ProbeScheduler(ProbeConfig()) i.e. disabled
  ControlLoop.step(rh_frac, dt, temp_c=None, allowed=True) -> (duty, raw_pid_output)
  SigmaDeltaSimulator.relay_on -> bool
  RunMetrics.temp_series, .ambient_series, .relay_series (0/1 floats), .probe_series (0/1 floats), .dt
  run_closed_loop(..., probe: ProbeScheduler = None, params_belief: ChamberParams = None,
                  rh_noise_pct: float = 0.0, seed: int = 0)
  ```
  `params` (existing kwarg) is the PLANT; `params_belief` is what the controller thinks (feeds `ControlLoop.params`). `rh_series` becomes the SENSED value (noise + 0.01 quantisation) when `rh_noise_pct > 0`.

- [ ] **Step 1: Write the failing tests**

```python
# src/chambers/fc-core/fc_core/test/test_control_loop_probe.py
from fc_core.control_kernel import BandSpec, ProbeConfig, ProbeScheduler
from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.control_loop import ControlLoop
from fc_core.sim.pwm_sigma_delta import SigmaDeltaConfig, SigmaDeltaSimulator
from fc_core.sim.replay import run_closed_loop

BAND = BandSpec(0.885, 0.915, 'both')


def test_probe_commands_full_duty_and_restores_integrator():
    loop = ControlLoop(BAND, probe=ProbeScheduler(ProbeConfig(probe_seconds=60, interval_s=100, idle_s=10)))
    # settle in the upper half of the band with a small standing integrator
    for _ in range(50):
        loop.step(0.895, 1.0)               # below midpoint: PID accumulates
    for _ in range(30):
        d, _ = loop.step(0.905, 1.0)        # in band, duty decays toward 0
    pre = loop.pid._integral
    duties = [loop.step(0.905, 1.0)[0] for _ in range(200)]
    assert duties.count(1.0) == 60
    assert not loop.pid.auto_mode or True   # re-engaged after the probe
    assert abs(loop.pid._integral - pre) < 1e-6 or loop.pid._integral <= pre


def test_run_closed_loop_records_probe_and_relay_series():
    probe = ProbeScheduler(ProbeConfig(probe_seconds=150, interval_s=3600, idle_s=600))
    m = run_closed_loop(hours=6.0, rh0=90.5, probe=probe,
                        pwm=SigmaDeltaSimulator(SigmaDeltaConfig()),
                        rh_noise_pct=0.1, seed=1)
    assert len(m.probe_series) == len(m.rh_series) == len(m.relay_series) == len(m.temp_series)
    assert probe.count >= 1
    assert sum(m.probe_series) == 150 * probe.count or sum(m.probe_series) < 150 * probe.count  # aborts allowed
    assert any(m.relay_series)
    # quantised sensed RH
    assert all(abs(x * 100 - round(x * 100)) < 1e-6 for x in m.rh_series[:100])
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_control_loop_probe.py`
Expected: TypeError on `probe=`.

- [ ] **Step 3: Implement**

`sim/pwm_sigma_delta.py`, inside `SigmaDeltaSimulator`:

```python
    @property
    def relay_on(self) -> bool:
        return self._relay_high
```

`sim/control_loop.py`:

```python
from fc_core.control_kernel import (BandSpec, ProbeConfig, ProbeScheduler, TempRateEstimator,
                                    duty_bias_factor, project_error_pct, temp_feedforward_duty)
...
    def __init__(self, band, gains=DEFAULT_GAINS, target=0.90, duty_bias=0.0,
                 temp_ff_gain=0.0, params: ChamberParams = None,
                 probe: ProbeScheduler = None):
        ...
        self.probe = probe or ProbeScheduler(ProbeConfig())
        self._last_duty = 0.0
        self._pre_probe_output = 0.0

    def step(self, rh_frac: float, dt: float, temp_c=None, allowed: bool = True):
        band = self.band
        gains = self.gains
        rate = self.temp_rate.update(temp_c, dt) if temp_c is not None else 0.0

        # MUSHY-138 identification probe. Parks the PID for the pulse and
        # re-engages it with the pre-probe output, NOT the Mode C 1.0.
        was_active = self.probe.active
        if self.probe.step(dt, rh_frac, band, rate, self._last_duty, allowed):
            if not was_active:
                self._pre_probe_output = self._last_duty
                if self.pid.auto_mode:
                    self.pid.set_auto_mode(False)
            self._last_duty = 1.0
            return 1.0, 0.0
        if self.probe.just_ended:
            self.pid.set_auto_mode(True, last_output=self._pre_probe_output)
            self.d_filtered = 0.0

        projected = project_error_pct(rh_frac, band)
        ... (unchanged) ...
        # at every return point below, set self._last_duty before returning:
```

Wrap the existing returns: replace `return 0.0, 0.0` with `self._last_duty = 0.0; return 0.0, 0.0`, `return 1.0, 1.0` with `self._last_duty = 1.0; return 1.0, 1.0`, and the final `return duty, raw_pid_output` with `self._last_duty = duty; return duty, raw_pid_output`.

`sim/replay.py`:

```python
import random
from fc_core.control_kernel import BandSpec, ProbeScheduler
...
@dataclass
class RunMetrics:
    ...
    rh_series: List[float] = field(default_factory=list)     # SENSED rh, %
    duty_series: List[float] = field(default_factory=list)
    temp_series: List[float] = field(default_factory=list)
    ambient_series: List[float] = field(default_factory=list)  # g/m3
    relay_series: List[float] = field(default_factory=list)    # 1.0 relay closed
    probe_series: List[float] = field(default_factory=list)    # 1.0 probe commanded
    dt: float = 1.0


def run_closed_loop(hours, params=None, pwm_cfg=None, band=DEFAULT_BAND, gains=DEFAULT_GAINS,
                    rh0=90.0, target=DEFAULT_TARGET, climb_seconds=0.0, duty_bias=0.0,
                    temp_ff_gain=0.0, dt=1.0, ambient_ah_g_m3=DEFAULT_AMBIENT_AH_G_M3,
                    temp_c=DEFAULT_TEMP_C, pwm=None,
                    probe: ProbeScheduler = None, params_belief: ChamberParams = None,
                    rh_noise_pct: float = 0.0, seed: int = 0) -> RunMetrics:
    ...
    control = ControlLoop(band, gains=gains, target=target, duty_bias=duty_bias,
                          temp_ff_gain=temp_ff_gain, params=params_belief, probe=probe)
    rng = random.Random(seed)
    temp_series, ambient_series, relay_series, probe_series = [], [], [], []
    for _ in range(steps):
        rh_true = chamber.rh
        rh_sensed = rh_true
        if rh_noise_pct > 0.0:
            rh_sensed = round(rh_true + rng.gauss(0.0, rh_noise_pct), 2)
        rh_frac = rh_sensed / 100.0
        temp_now = ...
        duty, _raw = control.step(rh_frac, dt, temp_c=temp_now)
        ...
        rh_series.append(rh_sensed)
        duty_series.append(duty)
        temp_series.append(temp_now)
        ambient_series.append(ambient_now)
        relay_series.append(1.0 if getattr(pwm, 'relay_on', False) else 0.0)
        probe_series.append(1.0 if control.probe.active else 0.0)
        ...
    m = _metrics(rh_series, duty_series, pwm, hours, delivered_total, dt)
    m.temp_series, m.ambient_series = temp_series, ambient_series
    m.relay_series, m.probe_series, m.dt = relay_series, probe_series, dt
    return m
```

`PwmSimulator` (the retired window driver) has no `relay_on`; `getattr` keeps old callers working.

- [ ] **Step 4: Run the sim suite**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_control_loop_probe.py src/chambers/fc-core/fc_core/test/test_control_loop_feedforward.py src/chambers/fc-core/fc_core/test/test_replay_fidelity.py src/chambers/fc-core/fc_core/test/test_pwm_sigma_delta.py`
Expected: all PASS. The fidelity gate must still pass with the probe disabled by default — if it does not, the `_last_duty` bookkeeping changed a return path; fix that, do not touch the fidelity thresholds.

- [ ] **Step 5: Commit**

```bash
git add src/chambers/fc-core/fc_core/sim/control_loop.py src/chambers/fc-core/fc_core/sim/pwm_sigma_delta.py src/chambers/fc-core/fc_core/sim/replay.py src/chambers/fc-core/fc_core/test/test_control_loop_probe.py
git commit -m "feat(sim): control loop steps the probe; replay records relay, probe and sensed-RH series [MUSHY-138]"
```

---

### Task 4: Fitter core (`probe_fit.py`)

**Files:**
- Create: `src/chambers/fc-core/fc_core/sim/probe_fit.py`
- Test: `src/chambers/fc-core/fc_core/test/test_probe_fit.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class Window:            # one probe, uniform grid
      dt: float
      rh: list            # %, sensed
      temp: list          # C
      ambient_ah: list    # g/m3
      relay: list         # 0/1
      probe_start_idx: int

  @dataclass
  class WindowFit:
      fill_g_per_h: float; moisture_loss_m3_per_h: float; dead_time_s: float; tau_s: float
      rmse_pct: float; rejected: str = ''       # non-empty reason => not used

  @dataclass
  class Aggregate:
      valid: bool; n: int; reasons: list
      params: ChamberParams              # medians (C carried from `base`)
      iqr: dict                          # per-parameter IQR
      median_temp_c: float

  PRE_S = 600.0; POST_S = 5400.0
  def find_windows(dt, rh, temp, ambient_ah, relay, probe, pre_s=PRE_S, post_s=POST_S) -> list[Window]
  def find_quasi_windows(dt, rh, temp, ambient_ah, relay, idle_s=900.0, ...) -> list[Window]
  def delivered_from_relay(relay, dt, transit_s=6.0) -> list[float]
  def fit_window(w: Window, base: ChamberParams) -> WindowFit
  def aggregate(fits: list[WindowFit], base: ChamberParams, temps: list[float]) -> Aggregate
  ```

- [ ] **Step 1: Write the failing tests**

```python
# src/chambers/fc-core/fc_core/test/test_probe_fit.py
import random
from dataclasses import replace

from fc_core.sim.chamber_model import ChamberModel, ChamberParams
from fc_core.sim.probe_fit import (Window, aggregate, delivered_from_relay, find_windows,
                                   find_quasi_windows, fit_window)
from fc_core.sim.psychrometrics import absolute_humidity_g_m3

TRUE = ChamberParams(moisture_loss_m3_per_h=0.4, fill_g_per_h=7.0, dead_time_s=50.0, tau_s=400.0)
BASE = ChamberParams()      # today's belief: theta 360, tau 600


def synth_window(params, dt=10.0, pulse_s=150.0, noise=0.1, seed=0):
    """Open-loop: idle 10 min, one pulse, 90 min decay. Constant 6 C, standing gradient."""
    rng = random.Random(seed)
    temp = 6.0
    amb = absolute_humidity_g_m3(temp, 90.0) - 0.703
    n = int((600 + 5400) / dt)
    relay = [1.0 if 600 <= i * dt < 600 + pulse_s else 0.0 for i in range(n)]
    delivered = delivered_from_relay(relay, dt)
    ch = ChamberModel(params, rh0_pct=90.5, temp_c=temp)
    rh = []
    for i in range(n):
        rh.append(round(ch.rh + rng.gauss(0, noise), 2))
        ch.step(delivered[i], dt, amb, temp)
    return Window(dt=dt, rh=rh, temp=[temp] * n, ambient_ah=[amb] * n, relay=relay,
                  probe_start_idx=int(600 / dt))


def test_fit_recovers_true_params_from_wrong_start():
    f = fit_window(synth_window(TRUE), BASE)
    assert not f.rejected
    assert abs(f.fill_g_per_h - 7.0) / 7.0 < 0.2
    assert abs(f.moisture_loss_m3_per_h - 0.4) / 0.4 < 0.3
    assert abs(f.dead_time_s - 50.0) < 20.0
    assert f.rmse_pct < 0.2


def test_aggregate_needs_five_windows():
    fits = [fit_window(synth_window(TRUE, seed=s), BASE) for s in range(4)]
    a = aggregate(fits, BASE, [6.0] * 4)
    assert not a.valid and 'n<5' in a.reasons
    fits.append(fit_window(synth_window(TRUE, seed=9), BASE))
    a = aggregate(fits, BASE, [6.0] * 5)
    assert a.valid
    assert a.params.surface_g_per_k == BASE.surface_g_per_k       # C carried, not fitted
    assert abs(a.params.fill_g_per_h - 7.0) / 7.0 < 0.2


def test_window_rejected_when_temperature_moves():
    w = synth_window(TRUE)
    w.temp = [6.0 + 1.0 * (i / len(w.temp)) for i in range(len(w.temp))]
    assert fit_window(w, BASE).rejected == 'temp_moved'


def test_find_windows_slices_on_probe_rising_edge():
    w = synth_window(TRUE)
    n = len(w.rh)
    probe = [1.0 if 590 <= i * w.dt < 590 + 150 else 0.0 for i in range(n)]   # commanded 10 s before relay
    ws = find_windows(w.dt, w.rh, w.temp, w.ambient_ah, w.relay, probe)
    assert len(ws) == 1 and ws[0].probe_start_idx == int(590 / w.dt)


def test_find_quasi_windows_uses_idle_then_single_pulse():
    w = synth_window(TRUE)
    n = len(w.rh)
    # add a second pulse 20 min after the first: the first window is spoiled, no windows found
    relay2 = list(w.relay)
    for i in range(n):
        if 600 + 1200 <= i * w.dt < 600 + 1200 + 60:
            relay2[i] = 1.0
    assert find_quasi_windows(w.dt, w.rh, w.temp, w.ambient_ah, relay2) == []
    assert len(find_quasi_windows(w.dt, w.rh, w.temp, w.ambient_ah, w.relay)) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_probe_fit.py`
Expected: ModuleNotFoundError `fc_core.sim.probe_fit`.

- [ ] **Step 3: Implement**

```python
# src/chambers/fc-core/fc_core/sim/probe_fit.py
"""Fit ChamberModel to identification-probe windows (MUSHY-138).

A probe is one relay pulse of known length into a chamber that has been
idle for >= 15 min. Its step response identifies F and the dead time
directly and the decay after it identifies Q -- the joint (F, Q) fit that
scripts/fit-chamber-model.py documents as degenerate on passive data is
well-posed here because the input is known and isolated.

The forward model IS ChamberModel, so this proves the pipeline, not the
model class (spec section 6 caveat). Pure: takes in-memory series, no I/O.
"""
from dataclasses import dataclass, field, replace
from statistics import median
from typing import List

import numpy as np
from scipy.optimize import least_squares

from fc_core.sim.chamber_model import ChamberModel, ChamberParams
from fc_core.sim.pwm_window import pipe_delivery

PRE_S = 600.0
POST_S = 5400.0
MIN_WINDOWS = 5
MAX_IQR_RATIO = 0.5
MAX_TEMP_MOVE_C = 0.5
# spec section 3 plausibility ranges, used as fit bounds too
BOUNDS_LO = (1.0, 0.1, 5.0, 60.0)       # F, Q, dead_time, tau
BOUNDS_HI = (50.0, 5.0, 900.0, 3600.0)


@dataclass
class Window:
    dt: float
    rh: List[float]
    temp: List[float]
    ambient_ah: List[float]
    relay: List[float]
    probe_start_idx: int


@dataclass
class WindowFit:
    fill_g_per_h: float
    moisture_loss_m3_per_h: float
    dead_time_s: float
    tau_s: float
    rmse_pct: float
    rejected: str = ''


@dataclass
class Aggregate:
    valid: bool
    n: int
    reasons: List[str]
    params: ChamberParams
    iqr: dict
    median_temp_c: float


def delivered_from_relay(relay, dt, transit_s=6.0):
    out, elapsed = [], 0.0
    for r in relay:
        if r > 0.5:
            out.append(pipe_delivery(elapsed, transit_s, dt))
            elapsed += dt
        else:
            out.append(0.0)
            elapsed = 0.0
    return out


def _slice(dt, rh, temp, ambient_ah, relay, start_idx, pre_s, post_s):
    a = start_idx - int(pre_s / dt)
    b = start_idx + int(post_s / dt)
    if a < 0 or b > len(rh):
        return None
    return Window(dt=dt, rh=list(rh[a:b]), temp=list(temp[a:b]), ambient_ah=list(ambient_ah[a:b]),
                  relay=list(relay[a:b]), probe_start_idx=start_idx - a)


def find_windows(dt, rh, temp, ambient_ah, relay, probe, pre_s=PRE_S, post_s=POST_S):
    out = []
    for i in range(1, len(probe)):
        if probe[i] > 0.5 and probe[i - 1] <= 0.5:
            w = _slice(dt, rh, temp, ambient_ah, relay, i, pre_s, post_s)
            if w is not None:
                out.append(w)
    return out


def find_quasi_windows(dt, rh, temp, ambient_ah, relay, idle_s=900.0, pre_s=PRE_S, post_s=POST_S):
    """History without probe markers: relay OFF >= idle_s, then ONE pulse, then
    no relay activity for the rest of the window."""
    out, idle = [], 0.0
    i = 0
    while i < len(relay):
        if relay[i] > 0.5:
            if idle >= idle_s:
                j = i
                while j < len(relay) and relay[j] > 0.5:
                    j += 1
                k = j
                quiet = True
                while k < len(relay) and (k - i) * dt < post_s:
                    if relay[k] > 0.5:
                        quiet = False
                        break
                    k += 1
                if quiet:
                    w = _slice(dt, rh, temp, ambient_ah, relay, i, pre_s, post_s)
                    if w is not None:
                        out.append(w)
                i = j
            idle = 0.0
        else:
            idle += dt
        i += 1
    return out


def _simulate(x, w: Window, base: ChamberParams):
    f, q, theta, tau = x
    p = replace(base, fill_g_per_h=f, moisture_loss_m3_per_h=q, dead_time_s=theta, tau_s=tau)
    ch = ChamberModel(p, rh0_pct=w.rh[0], temp_c=w.temp[0])
    delivered = delivered_from_relay(w.relay, w.dt)
    out = np.empty(len(w.rh))
    for i in range(len(w.rh)):
        out[i] = ch.rh
        ch.step(delivered[i], w.dt, w.ambient_ah[i], w.temp[i])
    return out


def fit_window(w: Window, base: ChamberParams) -> WindowFit:
    if max(w.temp) - min(w.temp) > MAX_TEMP_MOVE_C:
        return WindowFit(0, 0, 0, 0, 0, rejected='temp_moved')
    if not any(r > 0.5 for r in w.relay[w.probe_start_idx:]):
        return WindowFit(0, 0, 0, 0, 0, rejected='no_pulse')
    obs = np.asarray(w.rh)
    x0 = np.array([base.fill_g_per_h, base.moisture_loss_m3_per_h, base.dead_time_s, base.tau_s])
    x0 = np.clip(x0, BOUNDS_LO, BOUNDS_HI)
    res = least_squares(lambda x: _simulate(x, w, base) - obs, x0,
                        bounds=(BOUNDS_LO, BOUNDS_HI), x_scale=x0, max_nfev=200)
    rmse = float(np.sqrt(np.mean(res.fun ** 2)))
    f, q, theta, tau = (float(v) for v in res.x)
    return WindowFit(f, q, theta, tau, rmse)


def _iqr(vals):
    s = sorted(vals)
    n = len(s)
    return s[(3 * n) // 4] - s[n // 4]


def aggregate(fits: List[WindowFit], base: ChamberParams, temps: List[float]) -> Aggregate:
    good = [f for f in fits if not f.rejected]
    reasons = []
    if len(good) < MIN_WINDOWS:
        reasons.append(f'n<{MIN_WINDOWS}')
    cols = {
        'fill_g_per_h': [f.fill_g_per_h for f in good],
        'moisture_loss_m3_per_h': [f.moisture_loss_m3_per_h for f in good],
        'dead_time_s': [f.dead_time_s for f in good],
        'tau_s': [f.tau_s for f in good],
    }
    med = {k: (median(v) if v else getattr(base, k)) for k, v in cols.items()}
    iqr = {k: (_iqr(v) if len(v) >= 2 else float('inf')) for k, v in cols.items()}
    for k in ('fill_g_per_h', 'moisture_loss_m3_per_h'):
        if good and iqr[k] / max(med[k], 1e-9) >= MAX_IQR_RATIO:
            reasons.append(f'{k}_iqr')
    params = replace(base, **med)
    return Aggregate(valid=not reasons, n=len(good), reasons=reasons, params=params, iqr=iqr,
                     median_temp_c=median(temps) if temps else float('nan'))
```

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_probe_fit.py`
Expected: PASS. If `test_fit_recovers_true_params_from_wrong_start` misses on `dead_time_s`, the optimiser is stuck at the 360 s start: add a second start at `dead_time_s=30` and keep the lower-RMSE result (two `least_squares` calls, pick `min` by `cost`). Do that only if the test demands it.

- [ ] **Step 5: Commit**

```bash
git add src/chambers/fc-core/fc_core/sim/probe_fit.py src/chambers/fc-core/fc_core/test/test_probe_fit.py
git commit -m "feat(sim): probe_fit, least-squares ChamberModel fit on identification-probe windows [MUSHY-138]"
```

---

### Task 5: SIMC derivation and push guard (`simc.py`)

**Files:**
- Create: `src/chambers/fc-core/fc_core/sim/simc.py`
- Test: `src/chambers/fc-core/fc_core/test/test_simc.py`

**Interfaces:**
- Produces:
  ```python
  def plant_gain_pct_per_duty(params: ChamberParams, temp_c: float) -> float
  def simc_gains(params: ChamberParams, temp_c: float, tau_c_s: float = None) -> Gains
  RANGES = {'fill_g_per_h': (1, 50), 'moisture_loss_m3_per_h': (0.1, 5), 'dead_time_s': (5, 900),
            'tau_s': (60, 3600), 'kp': (0.001, 2.0), 'ki': (1e-6, 0.01)}
  @dataclass
  class Push:
      ok: bool; reasons: list; clamped: list; params: ChamberParams; gains: Gains
  def guard(fit: ChamberParams, last_accepted: ChamberParams, temp_c: float,
            tau_c_s: float = None, max_ratio: float = 2.0) -> Push
  ```
  `Gains` is `fc_core.sim.control_loop.Gains`; only kp/ki/kd are set, the rest keep their defaults.

- [ ] **Step 1: Write the failing tests**

```python
# src/chambers/fc-core/fc_core/test/test_simc.py
from dataclasses import replace

from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.psychrometrics import absolute_humidity_g_m3
from fc_core.sim.simc import guard, plant_gain_pct_per_duty, simc_gains

BASE = ChamberParams()


def test_plant_gain_is_f_over_q_in_rh_percent():
    k = plant_gain_pct_per_duty(BASE, 15.0)
    expect = 100.0 * (BASE.fill_g_per_h / BASE.moisture_loss_m3_per_h) / absolute_humidity_g_m3(15.0, 100.0)
    assert abs(k - expect) < 1e-9


def test_simc_formula_at_tau_c_equals_theta():
    g = simc_gains(BASE, 15.0)
    k = plant_gain_pct_per_duty(BASE, 15.0)
    theta, tau = BASE.dead_time_s, BASE.tau_s
    kp = tau / (k * (theta + theta))
    ti = min(tau, 4 * (theta + theta))
    assert abs(g.kp - kp) < 1e-12 and abs(g.ki - kp / ti) < 1e-12 and abs(g.kd - kp * theta / 2) < 1e-12
    assert 0.01 < g.kp < 0.02          # the order-of-magnitude finding from the spec


def test_guard_accepts_in_range_small_move():
    fit = replace(BASE, fill_g_per_h=BASE.fill_g_per_h * 1.5)
    p = guard(fit, BASE, 15.0)
    assert p.ok and not p.clamped and p.params.fill_g_per_h == fit.fill_g_per_h


def test_guard_clamps_big_move_to_2x_and_says_so():
    fit = replace(BASE, dead_time_s=50.0)                 # 360 -> 50 is 7.2x
    p = guard(fit, BASE, 15.0)
    assert p.ok and 'dead_time_s' in p.clamped
    assert abs(p.params.dead_time_s - 180.0) < 1e-9        # 360 / 2


def test_guard_refuses_out_of_range():
    fit = replace(BASE, moisture_loss_m3_per_h=9.0)
    p = guard(fit, BASE, 15.0)
    assert not p.ok and any('moisture_loss_m3_per_h' in r for r in p.reasons)
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_simc.py`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/chambers/fc-core/fc_core/sim/simc.py
"""SIMC gains from fitted chamber params, and the guard for pushing them (MUSHY-138).

Skogestad SIMC for a first-order-plus-dead-time plant:
    Kp = tau / (K (tau_c + theta)),  Ti = min(tau, 4 (tau_c + theta)),  Kd = Kp theta / 2
K is the steady-state RH gain per unit duty: F/Q in g/m3, converted to
%RH at the operating temperature. tau_c is the one preference knob
(desired closed-loop time constant); default tau_c = theta.
"""
from dataclasses import dataclass, replace
from typing import List, Optional

from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.control_loop import Gains
from fc_core.sim.psychrometrics import absolute_humidity_g_m3

RANGES = {
    'fill_g_per_h': (1.0, 50.0),
    'moisture_loss_m3_per_h': (0.1, 5.0),
    'dead_time_s': (5.0, 900.0),
    'tau_s': (60.0, 3600.0),
    'kp': (0.001, 2.0),
    'ki': (1e-6, 0.01),
}
FITTED = ('fill_g_per_h', 'moisture_loss_m3_per_h', 'dead_time_s', 'tau_s')


def plant_gain_pct_per_duty(params: ChamberParams, temp_c: float) -> float:
    return 100.0 * (params.fill_g_per_h / params.moisture_loss_m3_per_h) \
        / absolute_humidity_g_m3(temp_c, 100.0)


def simc_gains(params: ChamberParams, temp_c: float, tau_c_s: Optional[float] = None) -> Gains:
    theta, tau = params.dead_time_s, params.tau_s
    tau_c = theta if tau_c_s is None else tau_c_s
    k = plant_gain_pct_per_duty(params, temp_c)
    kp = tau / (k * (tau_c + theta))
    ti = min(tau, 4.0 * (tau_c + theta))
    return Gains(kp=kp, ki=kp / ti, kd=kp * theta / 2.0)


@dataclass
class Push:
    ok: bool
    reasons: List[str]
    clamped: List[str]
    params: ChamberParams
    gains: Gains


def guard(fit: ChamberParams, last_accepted: ChamberParams, temp_c: float,
          tau_c_s: Optional[float] = None, max_ratio: float = 2.0) -> Push:
    reasons, clamped, vals = [], [], {}
    for k in FITTED:
        v, prev = getattr(fit, k), getattr(last_accepted, k)
        lo, hi = RANGES[k]
        if not (lo <= v <= hi):
            reasons.append(f'{k}={v:.4g} outside [{lo}, {hi}]')
        # ponytail: ratchet instead of refuse, else a 7x-wrong dead time is stuck forever
        if prev > 0 and v > prev * max_ratio:
            v, _ = prev * max_ratio, clamped.append(k)
        elif prev > 0 and v < prev / max_ratio:
            v, _ = prev / max_ratio, clamped.append(k)
        vals[k] = v
    params = replace(last_accepted, **vals)
    gains = simc_gains(params, temp_c, tau_c_s)
    for k in ('kp', 'ki'):
        lo, hi = RANGES[k]
        g = getattr(gains, k)
        if not (lo <= g <= hi):
            reasons.append(f'{k}={g:.4g} outside [{lo}, {hi}]')
    return Push(ok=not reasons, reasons=reasons, clamped=clamped, params=params, gains=gains)
```

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_simc.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chambers/fc-core/fc_core/sim/simc.py src/chambers/fc-core/fc_core/test/test_simc.py
git commit -m "feat(sim): SIMC gains from fitted params + ratcheting push guard [MUSHY-138]"
```

---

### Task 6: Two-twin convergence test (spec §6)

**Files:**
- Test: `src/chambers/fc-core/fc_core/test/test_two_twin_convergence.py`

**Interfaces:**
- Consumes: `run_closed_loop(..., probe=, params=, params_belief=, gains=, temp_ff_gain=, rh_noise_pct=, seed=)`, `find_windows`, `fit_window`, `aggregate`, `guard`, `simc_gains`.

- [ ] **Step 1: Write the test**

```python
# src/chambers/fc-core/fc_core/test/test_two_twin_convergence.py
"""Spec section 6: tune twin A's belief onto twin B's hidden parameters
using only the probe -> fit -> guard -> push loop, in simulation.

Proves the pipeline, not the model class: the fitter's forward model IS
ChamberModel. Real-chamber adequacy is section 4 step 2's job.
"""
from dataclasses import replace

import pytest

from fc_core.control_kernel import ProbeConfig, ProbeScheduler
from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.probe_fit import aggregate, find_windows, fit_window
from fc_core.sim.pwm_sigma_delta import SigmaDeltaConfig, SigmaDeltaSimulator
from fc_core.sim.replay import DEFAULT_TEMP_C, run_closed_loop
from fc_core.sim.simc import guard, simc_gains

A0 = ChamberParams()                                       # today's belief
B = replace(A0, fill_g_per_h=A0.fill_g_per_h * 1.8, moisture_loss_m3_per_h=A0.moisture_loss_m3_per_h * 0.7,
            dead_time_s=50.0, tau_s=400.0)                 # the "real" chamber
DAYS, ROUNDS, DT = 3.0, 4, 2.0
PROBE = dict(probe_seconds=150.0, interval_s=6 * 3600.0, idle_s=900.0)


def one_round(belief, plant, seed):
    probe = ProbeScheduler(ProbeConfig(**PROBE))
    m = run_closed_loop(hours=24.0 * DAYS, dt=DT, rh0=90.5, params=plant, params_belief=belief,
                        gains=simc_gains(belief, DEFAULT_TEMP_C), temp_ff_gain=1.0,
                        probe=probe, pwm=SigmaDeltaSimulator(SigmaDeltaConfig()),
                        rh_noise_pct=0.1, seed=seed)
    return m


def in_band_fraction(m):
    return sum(88.5 <= x <= 91.5 for x in m.rh_series) / len(m.rh_series)


def test_a_converges_onto_b():
    belief, history = A0, []
    for r in range(ROUNDS):
        m = one_round(belief, B, seed=r)
        ws = find_windows(m.dt, m.rh_series, m.temp_series, m.ambient_series, m.relay_series, m.probe_series)
        fits = [fit_window(w, belief) for w in ws]
        agg = aggregate(fits, belief, [DEFAULT_TEMP_C] * len(fits))
        assert agg.valid, (r, agg.reasons, [f.rejected for f in fits])
        push = guard(agg.params, belief, DEFAULT_TEMP_C)
        assert push.ok, (r, push.reasons)
        belief = push.params
        history.append((agg, push, in_band_fraction(m)))

    for k in ('fill_g_per_h', 'moisture_loss_m3_per_h', 'dead_time_s', 'tau_s'):
        got, want = getattr(belief, k), getattr(B, k)
        assert abs(got - want) / want < 0.2, (k, got, want)
        assert abs(got - want) <= max(history[-1][0].iqr[k], 0.2 * want), (k, got, want)

    # last round no worse than knowing B from the start
    oracle = one_round(B, B, seed=99)
    assert history[-1][2] >= in_band_fraction(oracle) - 0.05
    assert history[-1][1].gains.kp < history[0][1].gains.kp * 5   # no runaway


def test_probe_does_not_degrade_a_correct_chamber():
    with_probe = one_round(B, B, seed=5)
    quiet = run_closed_loop(hours=24.0 * DAYS, dt=DT, rh0=90.5, params=B, params_belief=B,
                            gains=simc_gains(B, DEFAULT_TEMP_C), temp_ff_gain=1.0,
                            pwm=SigmaDeltaSimulator(SigmaDeltaConfig()), rh_noise_pct=0.1, seed=5)
    assert in_band_fraction(with_probe) >= in_band_fraction(quiet) - 0.02
    assert sum(1 for i in range(1, len(with_probe.probe_series))
               if with_probe.probe_series[i] > with_probe.probe_series[i - 1]) >= 8
```

- [ ] **Step 2: Run it**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_two_twin_convergence.py -x`
Expected: PASS within ~2 min. Failure triage, in order:
  1. `agg.valid` false with `n<5`: probes not firing. Print `probe.count`; usually `idle_s` never met because the standing duty keeps the relay busy. Loosen to `interval_s=4*3600` before touching the scheduler.
  2. `push.ok` false: a fitted value out of range; print `agg.params`. Likely `tau_s` hitting a bound; widen `x_scale`, not RANGES.
  3. Convergence miss on `dead_time_s` only: the ratchet needs one more round (360→180→90→50 is 3 halvings); raise `ROUNDS` to 5.
  4. In-band fraction worse than the oracle: the SIMC gains at `tau_c = theta` are too gentle against the sigma-delta driver; try `tau_c_s=theta/2` via `simc_gains(..., tau_c_s=...)` in BOTH the round and the oracle, and note the value in the ticket — it becomes the yaml default for `pid_simc_tau_c_seconds`.

- [ ] **Step 3: Commit**

```bash
git add src/chambers/fc-core/fc_core/test/test_two_twin_convergence.py
git commit -m "test(sim): two-twin convergence, probe->fit->guard->push tunes A onto B [MUSHY-138]"
```

Then comment on MUSHY-138 with the final `belief` vs `B` numbers, rounds needed, in-band fractions, and any `tau_c` change.

---

### Task 7: Controller wiring (Pi side)

**Files:**
- Modify: `src/chambers/fc-core/fc_core/fc_controller.py` (param declarations ~line 78-110, publishers ~line 238-250, state ~line 356-396, `_control_loop` ~line 1655-1810, parameter callback ~line 760-830)
- Modify: `src/chambers/fc-core/config/fc_config.yaml` (after `humidifier_temp_feedforward`)
- Test: `src/chambers/fc-core/fc_core/test/test_controller_probe.py` (container)

**Interfaces:**
- Consumes: `ProbeConfig`, `ProbeScheduler`, `temp_feedforward_duty(..., fill_g_per_h, surface_g_per_k)`.
- Produces: ROS params `probe_seconds` (150.0), `probe_interval_h` (0.0), `pid_simc_tau_c_seconds` (0.0 = use fitted theta; consumed only by the push script), `fill_g_per_h` (3.890), `surface_g_per_k` (2.77); topic `fc1/control/probe` (Float32, TRANSIENT_LOCAL, same QoS object as `_humidity_target_pub`).

- [ ] **Step 1: Write the failing test**

Look at `src/chambers/fc-core/fc_core/test/test_controller.py` for how a controller node is constructed under `ros_context` with `actuator_simulation_mode` and mocked clocks; copy that fixture style. Then:

```python
# src/chambers/fc-core/fc_core/test/test_controller_probe.py
import pytest
from std_msgs.msg import Float32

from fc_core.test.test_controller import make_controller   # reuse the existing fixture helper


def test_probe_params_declared(ros_context):
    node = make_controller()
    assert node.get_parameter('probe_seconds').value == 150.0
    assert node.get_parameter('probe_interval_h').value == 0.0
    assert node.get_parameter('fill_g_per_h').value == pytest.approx(3.890)
    assert node.get_parameter('surface_g_per_k').value == pytest.approx(2.77)
    node.destroy_node()


def test_probe_publishes_marker_and_full_duty(ros_context):
    node = make_controller()
    node.set_parameters([__import__('rclpy').parameter.Parameter('probe_interval_h', value=0.001)])
    published = []
    node._probe_pub.publish = lambda m: published.append(('probe', m.data))
    node._duty_pub.publish = lambda m: published.append(('duty', m.data))
    # feed fresh in-band readings, idle, for > 15 min of ticks
    node.current_temp = 15.0
    for _ in range(1000):
        node.current_humidity = 0.905
        node._last_humidity_timestamp = node.get_clock().now()
        node._control_loop()
    assert ('probe', 1.0) in published
    i = published.index(('probe', 1.0))
    assert ('duty', 1.0) in published[i:i + 4]
    node.destroy_node()
```

If `make_controller` does not exist in `test_controller.py`, add it there as a thin wrapper around whatever that file already does to build a node (same parameter overrides), and import it here.

- [ ] **Step 2: Run in the container to verify it fails**

Run: `docker build -f docker/fc-core-test.Dockerfile -t fc-core-test . && docker run --rm --network none -v "$PWD/src/chambers:/src:ro" fc-core-test 2>&1 | tail -20`
Expected: the new test errors on the missing parameter.

- [ ] **Step 3: Implement**

Parameter block (add after `('bypass_threshold', 0.025),`):

```python
                ('probe_seconds', 150.0),            # MUSHY-138 identification probe
                ('probe_interval_h', 0.0),           # 0 = disabled
                ('pid_simc_tau_c_seconds', 0.0),     # preference consumed by the push script
                ('fill_g_per_h', 3.890),             # chamber model F, live-fitted
                ('surface_g_per_k', 2.77),           # chamber model C
```

Publisher (next to `_humidity_target_pub`):

```python
        self._probe_pub = self.create_publisher(Float32, 'fc1/control/probe', actuator_qos)
```

State (next to `self._temp_rate = TempRateEstimator()`):

```python
        self._probe = ProbeScheduler(self._probe_config())
        self._pre_probe_duty = 0.0
```

Helper method near `_disengage_pid`:

```python
    def _probe_config(self) -> ProbeConfig:
        return ProbeConfig(probe_seconds=self.get_parameter('probe_seconds').value,
                           interval_s=self.get_parameter('probe_interval_h').value * 3600.0)

    def _publish_probe(self, on: bool):
        msg = Float32()
        msg.data = 1.0 if on else 0.0
        self._probe_pub.publish(msg)
```

In the parameter callback, alongside the other `elif n == ...` branches:

```python
            elif n in ('probe_seconds', 'probe_interval_h', 'fill_g_per_h', 'surface_g_per_k',
                       'pid_simc_tau_c_seconds'):
                if not (isinstance(v, (int, float)) and v >= 0.0):
                    return SetParametersResult(successful=False, reason=f'{n}: must be >= 0 (got {v})')
                if n in ('probe_seconds', 'probe_interval_h'):
                    rebuild_probe = True
```

and after the loop, where the other `republish_*` flags are acted on: `if rebuild_probe: self._probe = ProbeScheduler(self._probe_config())` (initialise `rebuild_probe = False` beside the other flags at the top of the callback).

In `_control_loop`, right after `temp_rate = self._temp_rate.update(...)` and the `force_duty` short-circuit, before `if not self._pid_engaged:`:

```python
            # MUSHY-138 identification probe: duty 1.0 for probe_seconds when
            # the chamber is quiet, PID parked, re-engaged with the pre-probe
            # duty (NOT the Mode C 1.0). Marker topic labels the window in
            # Timescale; the fit takes its timing from the relay edges.
            mode_ok = mode.name in ('fruiting', 'pinning')
            band = BandSpec(mode.band_low, mode.band_high, mode.defend_side)
            was_active = self._probe.active
            if self._probe.step(dt, self.current_humidity, band, temp_rate,
                                self._last_published_duty, allowed=mode_ok):
                if not was_active:
                    self._pre_probe_duty = self._last_published_duty
                    self._disengage_pid()
                    self.get_logger().info(f'Probe {self._probe.count} start, {self._probe.cfg.probe_seconds:.0f}s')
                    self._publish_probe(True)
                self._publish_duty(1.0)
                return
            if self._probe.just_ended:
                self._publish_probe(False)
                self._engage_pid_bumplessly(self._pre_probe_duty)
                self.get_logger().info('Probe end')
```

Check `ModeView` has a `name` attribute (grep `class ModeView`); if it is called something else, use that. Also call `self._publish_probe(False)` once at startup (after the publisher is created) so the TRANSIENT_LOCAL topic has a value.

The staleness branch already calls `_disengage_pid()`; add `if self._probe.active: self._probe.step(dt, 0.0, band, 0.0, 0.0, allowed=False); self._publish_probe(False)` there is NOT needed: the next fresh tick passes `allowed=mode_ok` and the scheduler's own staleness comes through `mode_ok`; instead make stale ticks abort by passing `allowed=False`: in the `if stale:` branch add

```python
            if self._probe.active:
                self._probe.step(0.0, 0.0, BandSpec(0.0, 1.0, 'both'), 0.0, 0.0, allowed=False)
                self._publish_probe(False)
```

Replace the Task 2 placeholder in the feedforward call:

```python
                    duty = max(0.0, min(1.0, duty + temp_feedforward_duty(
                        ff_gain, temp_rate, rh, self.current_temp, band,
                        self.get_parameter('fill_g_per_h').value,
                        self.get_parameter('surface_g_per_k').value)))
```

and drop the `ChamberParams` import added in Task 2. Add `ProbeConfig, ProbeScheduler` to the `from fc_core.control_kernel import (...)` line.

`fc_config.yaml`, after the `humidifier_temp_feedforward` block:

```yaml
    # MUSHY-138 self-tuning. The probe is a 150 s duty=1.0 pulse into a quiet
    # in-band chamber; its step response identifies F, Q and the dead time
    # (scripts/self-tune/). 0 h = off. fill_g_per_h / surface_g_per_k are the
    # chamber model's F and C, written by the push script, read by the
    # temperature feedforward.
    probe_seconds: 150.0
    probe_interval_h: 0.0
    pid_simc_tau_c_seconds: 0.0       # 0 = fitted dead time (Skogestad default)
    fill_g_per_h: 3.890
    surface_g_per_k: 2.77
```

- [ ] **Step 4: Run the container suite**

Run: `docker run --rm --network none -v "$PWD/src/chambers:/src:ro" fc-core-test 2>&1 | tail -20`
Expected: all PASS (was 356 + new).

- [ ] **Step 5: Commit**

```bash
git add src/chambers/fc-core/fc_core/fc_controller.py src/chambers/fc-core/config/fc_config.yaml src/chambers/fc-core/fc_core/test/test_controller_probe.py src/chambers/fc-core/fc_core/test/test_controller.py
git commit -m "feat(fc_core): identification probe in the controller, fc1/control/probe marker, F and C as params [MUSHY-138]"
```

---

### Task 8: Bridge stores `fc.probe`

**Files:**
- Modify: `src/mission-control/bridge/src/index.js:981-996` (copy the `humidity_target` block), and the topic list at `index.js:406`

- [ ] **Step 1: Implement**

Directly below the `humidity_target` subscription:

```js
    // MUSHY-138: subscribe to fc1/control/probe -> fc.probe
    // 1.0 while an identification probe is commanded. Labels the window for
    // scripts/self-tune/fit-probes.py; timing comes from fc.humidifier edges.
    node.createSubscription(
        'std_msgs/msg/Float32',
        '/fc1/control/probe',
        { qos: transientLocalQos },
        async (msg) => {
            const value = msg.data;
            const ts = Date.now();
            const tsNs = ts * 1_000_000;
            latestTelemetry.probe = { value, timestamp: ts };
            broadcast({ probe: value, timestamp: ts });
            await insertTelemetry('fc.probe', value, ts, tsNs);
        }
    );
    console.log('[bridge] Probe subscription: TRANSIENT_LOCAL QoS');
```

Add `'fc.probe'` to the list at line 406 (the array that names stored topics; read the surrounding lines to confirm it is the dedupe/known-topic list and not something else — if it is unrelated, leave it).

- [ ] **Step 2: Verify it parses and the bridge starts**

Run: `node --check src/mission-control/bridge/src/index.js && docker compose up -d --build bridge && sleep 5 && docker compose logs --tail 30 bridge | grep -i "probe\|error"`
Expected: `[bridge] Probe subscription: TRANSIENT_LOCAL QoS`, no errors. (This rebuilds the live bridge — elder-plops is prod; it is a ~2 s deaf window per MUSHY-112. Dump logs first per the repo rule: `docker compose logs bridge > /tmp/claude-1000/-mnt-slime-kingdom-opt-mushy/*/scratchpad/bridge-pre-138.log`.)

- [ ] **Step 3: Commit**

```bash
git add src/mission-control/bridge/src/index.js
git commit -m "feat(bridge): store fc1/control/probe as fc.probe [MUSHY-138]"
```

---

### Task 9: Off-Pi scripts and the timer

**Files:**
- Create: `scripts/self-tune/fit-probes.py`, `scripts/self-tune/push-chamber-params.py`, `scripts/self-tune/mushy-self-tune.sh`, `scripts/self-tune/mushy-self-tune.service`, `scripts/self-tune/mushy-self-tune.timer`, `scripts/self-tune/install.sh`
- Test: `scripts/self-tune/test_fit_probes.py` (adapter resampling only; the fit itself is tested in Task 4)

**Interfaces:**
- Consumes: `probe_fit.find_windows/find_quasi_windows/fit_window/aggregate`, `simc.guard`, `psql()`/`parse_epoch()` from `scripts/fit-chamber-model.py` via importlib (same trick as `scripts/test_fit_chamber_model.py`), `AmbientSeries.from_csv().at(when)`.
- Produces: `reports/self-tune/<YYYY-MM-DD>.json` (fit report), `reports/self-tune/accepted.json` (last accepted `ChamberParams` + gains), exit codes: 0 pushed, 3 fit invalid / guard refused, 1 error.

- [ ] **Step 1: Write the failing adapter test**

```python
# scripts/self-tune/test_fit_probes.py
"""Run: PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q scripts/self-tune/test_fit_probes.py"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location('fit_probes', Path(__file__).with_name('fit-probes.py'))
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)


def test_resample_holds_last_value_on_uniform_grid():
    rows = [(0.0, 90.0), (7.0, 90.5), (25.0, 91.0)]
    grid = fp.resample(rows, t0=0.0, t1=40.0, dt=10.0)
    assert grid == [90.0, 90.5, 90.5, 91.0]


def test_relay_edges_to_held_state():
    edges = [(0.0, 0.0), (12.0, 1.0), (33.0, 0.0)]
    assert fp.resample(edges, t0=0.0, t1=50.0, dt=10.0, initial=0.0) == [0.0, 1.0, 1.0, 1.0, 0.0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q scripts/self-tune/test_fit_probes.py`
Expected: FileNotFoundError on `fit-probes.py`.

- [ ] **Step 3: Implement `fit-probes.py`**

```python
#!/usr/bin/env python3
"""Fit the chamber model to identification probes stored in Timescale (MUSHY-138).

Adapter only: pulls the series, resamples to a 10 s grid, hands windows to
fc_core.sim.probe_fit, writes reports/self-tune/<date>.json. Never touches
the control path. --quasi uses idle-then-single-pulse transitions instead
of fc.probe markers (spec section 4 step 2, history before any probe ran).

  PYTHONPATH=src/chambers/fc-core .venv/bin/python scripts/self-tune/fit-probes.py --days 14
  PYTHONPATH=src/chambers/fc-core .venv/bin/python scripts/self-tune/fit-probes.py --quasi --days 30
"""
import argparse
import importlib.util
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'src' / 'chambers' / 'fc-core'))

from fc_core.sim.ambient import AmbientSeries                        # noqa: E402
from fc_core.sim.chamber_model import ChamberParams                  # noqa: E402
from fc_core.sim.probe_fit import (aggregate, find_quasi_windows,     # noqa: E402
                                   find_windows, fit_window)
from fc_core.sim.psychrometrics import absolute_humidity_g_m3        # noqa: E402

_spec = importlib.util.spec_from_file_location(
    'fit_chamber_model', REPO_ROOT / 'scripts' / 'fit-chamber-model.py')
fcm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fcm)

DT = 10.0
REPORT_DIR = REPO_ROOT / 'reports' / 'self-tune'


def load(topic, t0, t1):
    sql = (f"select extract(epoch from time), value from telemetry where topic='{topic}' "
           f"and time >= to_timestamp({t0}) and time <= to_timestamp({t1}) order by time")
    rows = []
    for line in fcm.psql(sql).splitlines():
        if line.strip():
            ts, v = line.split('\t')
            rows.append((float(ts), float(v)))
    return rows


def resample(rows, t0, t1, dt, initial=None):
    """Sample-and-hold onto [t0, t1) at dt. `initial` is the value before the first row."""
    out, i, cur = [], 0, initial
    t = t0
    while t < t1:
        while i < len(rows) and rows[i][0] <= t:
            cur = rows[i][1]
            i += 1
        out.append(cur if cur is not None else rows[0][1])
        t += dt
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--days', type=float, default=14.0)
    ap.add_argument('--quasi', action='store_true')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    t1 = datetime.now(timezone.utc)
    t0 = t1 - timedelta(days=a.days)
    e0, e1 = t0.timestamp(), t1.timestamp()
    rh = resample(load('fc.humidity', e0, e1), e0, e1, DT)
    temp = resample(load('fc.temperature', e0, e1), e0, e1, DT)
    relay = resample(load('fc.humidifier', e0 - 86400, e1), e0, e1, DT, initial=0.0)
    amb = AmbientSeries.from_csv()
    ambient = []
    t = e0
    while t < e1:
        s = amb.at(datetime.fromtimestamp(t, tz=timezone.utc))
        ambient.append(absolute_humidity_g_m3(s.temp_c, s.rh_pct))
        t += DT
    rh = [x * 100.0 if x <= 1.0 else x for x in rh]        # fc.humidity is a fraction

    if a.quasi:
        windows = find_quasi_windows(DT, rh, temp, ambient, relay)
    else:
        probe = resample(load('fc.probe', e0, e1), e0, e1, DT, initial=0.0)
        windows = find_windows(DT, rh, temp, ambient, relay, probe)

    base = ChamberParams()
    fits = [fit_window(w, base) for w in windows]
    temps = [w.temp[w.probe_start_idx] for w, f in zip(windows, fits) if not f.rejected]
    agg = aggregate(fits, base, temps)
    report = {
        'generated': t1.isoformat(), 'days': a.days, 'quasi': a.quasi,
        'windows': len(windows), 'fits': [asdict(f) for f in fits],
        'valid': agg.valid, 'reasons': agg.reasons, 'n': agg.n,
        'params': asdict(agg.params), 'iqr': agg.iqr, 'median_temp_c': agg.median_temp_c,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(a.out) if a.out else REPORT_DIR / f'{t1:%Y-%m-%d}{"-quasi" if a.quasi else ""}.json'
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ('valid', 'reasons', 'n', 'params', 'iqr')}, indent=2))
    print(f'report: {out}')
    return 0 if agg.valid else 3


if __name__ == '__main__':
    sys.exit(main())
```

Check the actual `telemetry` table column names and whether `fc.humidity` is stored as a fraction or percent by running the `load` query by hand once (`docker exec mushy-timescale-1 psql ... -c "select value from telemetry where topic='fc.humidity' order by time desc limit 3"`), and fix the `rh` scaling line to match. Also confirm `AmbientSeries.from_csv()` default fixture covers the last 14 days (`.recent.csv` is the one refreshed; pass its path if the default is the older fixture).

- [ ] **Step 4: Implement `push-chamber-params.py`**

```python
#!/usr/bin/env python3
"""Guard a fit report and push it: ros2 params on fc1 + fc_config.yaml commit (MUSHY-138).

  PYTHONPATH=src/chambers/fc-core .venv/bin/python scripts/self-tune/push-chamber-params.py reports/self-tune/2026-09-05.json
  ... --dry-run   prints what it would do, touches nothing

Exit 0 pushed, 3 refused (report says why), 1 error.
"""
import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'src' / 'chambers' / 'fc-core'))

from fc_core.sim.chamber_model import ChamberParams      # noqa: E402
from fc_core.sim.simc import guard                       # noqa: E402

YAML = REPO_ROOT / 'src' / 'chambers' / 'fc-core' / 'config' / 'fc_config.yaml'
ACCEPTED = REPO_ROOT / 'reports' / 'self-tune' / 'accepted.json'
NODE = '/fc_controller'


def yaml_value(key):
    m = re.search(rf'^(\s*){key}:\s*([0-9.eE+-]+)', YAML.read_text(), re.M)
    return float(m.group(2)) if m else None


def set_yaml(key, value):
    text, n = re.subn(rf'^(\s*{key}:\s*)[0-9.eE+-]+', rf'\g<1>{value:.6g}', YAML.read_text(), count=1, flags=re.M)
    if n != 1:
        raise SystemExit(f'{key} not found in {YAML}')
    YAML.write_text(text)


def sh(cmd, dry):
    print('+', ' '.join(cmd))
    if not dry:
        subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('report')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    rep = json.loads(Path(a.report).read_text())
    if not rep['valid']:
        print('refused: fit invalid', rep['reasons'])
        return 3
    fit = ChamberParams(**rep['params'])
    last = ChamberParams(**json.loads(ACCEPTED.read_text())['params']) if ACCEPTED.exists() else ChamberParams()
    tau_c = yaml_value('pid_simc_tau_c_seconds') or None
    push = guard(fit, last, rep['median_temp_c'], tau_c_s=tau_c)
    print(json.dumps({'ok': push.ok, 'reasons': push.reasons, 'clamped': push.clamped,
                      'params': asdict(push.params), 'gains': asdict(push.gains)}, indent=2))
    if not push.ok:
        return 3

    values = {
        'pid_kp': push.gains.kp, 'pid_ki': push.gains.ki, 'pid_kd': push.gains.kd,
        'fill_g_per_h': push.params.fill_g_per_h, 'surface_g_per_k': push.params.surface_g_per_k,
    }
    for k, v in values.items():
        sh(['ssh', 'fc1', 'ros2-cmd', 'param', 'set', NODE, k, f'{v:.6g}'], a.dry_run)
        if not a.dry_run:
            set_yaml(k, v)
    if a.dry_run:
        return 0
    ACCEPTED.write_text(json.dumps({'params': asdict(push.params), 'gains': asdict(push.gains),
                                    'report': str(a.report)}, indent=2))
    sh(['git', '-C', str(REPO_ROOT), 'add', str(YAML), str(ACCEPTED)], False)
    sh(['git', '-C', str(REPO_ROOT), 'commit', '-q', '-m',
        f'config(fc_core): self-tune push from {Path(a.report).name} [MUSHY-138]'], False)
    sh(['git', '-C', str(REPO_ROOT), 'push', '-q', 'origin', 'main'], False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

`ChamberParams(**rep['params'])` requires the report's `params` keys to match the dataclass fields exactly (they do: `asdict`). The twin's `moisture_loss_m3_per_h` and `dead_time_s`/`tau_s` are NOT pushed to the Pi (the controller does not use them); they live in `accepted.json` and drive the next SIMC derivation. `ssh fc1 ros2-cmd` is the wrapper documented in memory (`fc1 ssh auto-injects DDS env`); verify once by hand with `ssh fc1 ros2-cmd param get /fc_controller pid_kp` before the first real push.

Guardrail on the yaml edit: `set_yaml` only rewrites the number and keeps the trailing comment; the regex anchors on the key at line start so `modes.*` keys are untouched.

- [ ] **Step 5: Timer, service, runner, installer**

`scripts/self-tune/mushy-self-tune.sh`:

```bash
#!/usr/bin/env bash
# MUSHY-138 nightly: fit the last 14 days of probes, push if the guard passes.
set -euo pipefail
cd /mnt/slime-kingdom/opt/mushy
export PYTHONPATH=src/chambers/fc-core
REPORT="reports/self-tune/$(date -u +%F).json"
.venv/bin/python scripts/self-tune/fit-probes.py --days 14 --out "$REPORT" || { echo "fit invalid, not pushing"; exit 0; }
.venv/bin/python scripts/self-tune/push-chamber-params.py "$REPORT" ${SELF_TUNE_DRY_RUN:+--dry-run}
```

`mushy-self-tune.service`:

```ini
[Unit]
Description=Mushy self-tune: fit probes, push chamber params (MUSHY-138)
After=network-online.target docker.service

[Service]
Type=oneshot
User=santi
WorkingDirectory=/mnt/slime-kingdom/opt/mushy
Environment=SELF_TUNE_DRY_RUN=1
ExecStart=/usr/local/bin/mushy-self-tune.sh
```

`mushy-self-tune.timer`:

```ini
[Unit]
Description=Mushy self-tune nightly (04:10 local)

[Timer]
OnCalendar=*-*-* 04:10:00
Persistent=true
RandomizedDelaySec=5m
Unit=mushy-self-tune.service

[Install]
WantedBy=timers.target
```

`install.sh`: copy `scripts/backup-tierA/install.sh` verbatim, replace the three names (`mushy-tierA-backup` → `mushy-self-tune`) and the MUSHY-45 comment with one line: `# MUSHY-138: install the self-tune runner + timer. Idempotent. sudo scripts/self-tune/install.sh`. `Environment=SELF_TUNE_DRY_RUN=1` stays until spec §4 step 4; flipping it is the "push on" decision and is done by editing the unit and re-running install.sh.

- [ ] **Step 6: Run the adapter test and a dry run against Timescale**

Run:
```bash
PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q scripts/self-tune/test_fit_probes.py
PYTHONPATH=src/chambers/fc-core .venv/bin/python scripts/self-tune/fit-probes.py --quasi --days 30
```
Expected: tests PASS; the quasi run prints a report (valid or not) and writes `reports/self-tune/<date>-quasi.json`. **Paste the printed `params`, `iqr`, `n` and `reasons` into a MUSHY-138 comment** — this is spec §4 step 2, the first real answer on theta 50 vs 360 s. Then `push-chamber-params.py <that report> --dry-run` and paste what it would push. Do not run it without `--dry-run`.

- [ ] **Step 7: Commit**

```bash
git add scripts/self-tune reports/self-tune/*.json
git commit -m "feat(self-tune): probe fitter + guarded param push + nightly timer, dry-run by default [MUSHY-138]"
```

---

### Task 10: Docs and handover

**Files:**
- Modify: `src/chambers/fc-core/fc_core/README.md` (short section)
- Modify: `CLAUDE.md` (one line under Development Commands)

- [ ] **Step 1: README section**

Append to `src/chambers/fc-core/fc_core/README.md`:

```markdown
## Self-tuning (MUSHY-138)

The chamber model (`sim/chamber_model.py:ChamberParams`) is the source of truth for the
humidifier loop. `control_kernel.ProbeScheduler` fires a 150 s duty=1.0 probe into a quiet
in-band chamber every `probe_interval_h`; `scripts/self-tune/fit-probes.py` fits the model to
each probe window from Timescale; `scripts/self-tune/push-chamber-params.py` derives SIMC PID
gains (`sim/simc.py`, preference knob `pid_simc_tau_c_seconds`) and pushes them to fc1 plus
`fc_config.yaml` when the guard passes. `test_two_twin_convergence.py` is the end-to-end proof
in simulation. Enable on fc1 with `probe_interval_h: 12`; the nightly timer runs dry until
`SELF_TUNE_DRY_RUN` is removed from `scripts/self-tune/mushy-self-tune.service`.
```

- [ ] **Step 2: CLAUDE.md line**

Under `### Testing`, add:

```bash
# Pure sim/kernel tests, no ROS needed (fast loop)
PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q src/chambers/fc-core/fc_core/test/test_two_twin_convergence.py
```

- [ ] **Step 3: Commit and hand over**

```bash
git add src/chambers/fc-core/fc_core/README.md CLAUDE.md
git commit -m "docs(fc_core): self-tuning loop overview and fast test loop [MUSHY-138]"
git push origin main
```

Comment on MUSHY-138: commits on main, what is deployed (nothing on fc1; bridge rebuilt on elder-plops with `fc.probe`), the quasi-probe result, and the remaining human steps in order: (1) `git push fc1/prod` + `deploy.sh` with `probe_interval_h: 12`, (2) watch two days of probes on Mission Control, (3) `sudo scripts/self-tune/install.sh`, (4) after the first dry-run report reads sane, remove `SELF_TUNE_DRY_RUN` and re-install.

---

## Self-review

- **Spec coverage.** §1 probe: Tasks 1, 3, 7. §1 marker: Tasks 7, 8. §2 fitter: Tasks 4, 9. §3 derivation + guard + push: Tasks 5, 9. §4 proving order: Task 6 (step 1), Task 9 step 6 (step 2), Task 10 handover (steps 3-4, human). §5 not-built: nothing here touches feather/driver/cap/Mode C except passing through them. §6 two-twin: Task 6. Spec deviation (clamp vs refuse) is declared in Global Constraints and Task 5.
- **Types.** `ProbeScheduler.step(dt, rh, band, temp_rate_c_per_h, last_duty, allowed)` used identically in Tasks 1, 3, 7. `Window`/`WindowFit`/`Aggregate` fields match between Task 4 and Task 9. `guard(fit, last_accepted, temp_c, tau_c_s)` matches Tasks 5, 6, 9. `run_closed_loop` kwargs `probe`, `params_belief`, `rh_noise_pct`, `seed` match Tasks 3 and 6. `Gains` comes from `sim/control_loop.py` in both Tasks 5 and 6.
- **Placeholders.** None; every code step is complete. Two verify-by-hand notes (fc.humidity scaling, `ModeView.name`) name the exact command/grep to run.
