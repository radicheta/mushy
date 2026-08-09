# Chamber Sim + Duty Shaping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline chamber simulator that reproduces FC-1's observed ~2 h humidity limit cycle, then use it to develop and validate two control fixes (sub-threshold pulse accumulation and an output slew limiter) without touching the live grow.

**Architecture:** Extract the live control law from `fc_controller` into a pure, ROS-free kernel. Add a `fc_core.sim` package holding an empirically-fitted first-order-plus-dead-time chamber model, a faithful PWM/relay simulator including the humidifier's pipe transport delay, and a replay harness driven by a real 26 h Timescale trace. Develop both fixes test-first against that harness and report before/after metrics.

**Tech Stack:** Python 3.12, pytest, `simple_pid`, numpy-free (stdlib maths only, so `fc_core.sim` imports in a vanilla venv with no rclpy/RPi.GPIO).

## Global Constraints

- `fc_core.sim` MUST import cleanly with zero `rclpy` / `RPi.GPIO` dependencies.
- Every PID call in sim paths MUST pass explicit `dt=` — never let `simple_pid` read the wall clock.
- The real-hardware code path in `fc_pwm_driver` stays behaviourally unchanged unless a task explicitly changes it, and any change is parameter-gated with the current values as defaults.
- No deployment to fc1 in this plan. Nothing merges to `main` without review.
- Branch: `feat/chamber-sim-duty-shaping`, based on `main` with `fc1/prod` forward-ported.
- Ticket refs: sim work is **MUSHY-52** / ROADMAP 999.33; the control fixes get a new ticket created in Task 9.
- No `Co-Authored-By` or AI-attribution trailers in any commit.

## Measured Ground Truth (2026-08-08, 26 h trace, fc1 fruiting)

These are the numbers the model must reproduce. Source: `.planning/notes/2026-08-09-pid-limit-cycle/`.

| Quantity | Value |
|---|---|
| Resolved mode | fruiting, target 0.900, band [0.885, 0.915], defend both |
| Gains | `Kp=0.36`, `Ki=0.001`, `Kd=4.0`, `decay_tau=1800` |
| RH decay, duty = 0 | −2.24 pts/h |
| RH rise, duty commanded high (delivered ≤0.40) | +6.76 pts/h |
| Implied gross fill at duty=1.0 | ~22.5 pts/h |
| Implied equilibrium duty | ~0.10 |
| Observed cycle period | 1.82 / 1.87 / 2.10 h |
| Observed RH span | 87.33 – 92.59 (5.26 pts) |
| Duty at ~0 | 52.6% of minutes |
| Duty commanded in (0, 0.083) and discarded | 22.3% of minutes |
| Burst onset RH | 88.2 – 88.8 |
| RH peak after onset | 92.0 – 92.6, at +43 to +63 min |

**Farmer-supplied physical constraints (2026-08-09):**
- ~2 m of pipe between humidifier element and chamber outlet.
- **5–7 s from relay-on to vapour actually leaving the outlet.** Every pulse spends that time wetting pipe and delivers nothing.
- `min_pulse_seconds` exists for relay wear *and* because sub-transit pulses do nothing useful.
- Farmer's judgement: **minimum useful run is ~20 s**, not the current 10 s.

**Consequence that drives the whole design:** raising the floor to 20 s against a 120 s window makes the minimum deliverable duty 16.7%, while equilibrium demand is ~10%. Without accumulation the controller *cannot* express its steady-state operating point at all.

---

### Task 0: Branch and forward-port the live control law

`fc1/prod` carries three commits `main` has never seen. They are the control law actually running the chamber. All sim work must model *these*, not `main`'s stale version.

**Files:**
- Modify: `src/chambers/fc-core/fc_core/fc_controller.py` (feather block, ~line 1697)
- Modify: `src/chambers/fc-core/config/fc_config.yaml` (band + target)

**Interfaces:**
- Produces: a branch whose `fc_controller.py` error-projection block is byte-identical to fc1's running copy.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/chamber-sim-duty-shaping main
```

- [ ] **Step 2: Cherry-pick the three prod commits**

```bash
git cherry-pick b4f18e4 30534ff c758319
```

- [ ] **Step 3: Verify the result matches what fc1 is running**

```bash
ssh fc1 'sed -n "1697,1740p" ~/mushroom_farm_ws/src/chambers/fc-core/fc_core/fc_controller.py' > /tmp/fc1_feather.txt
sed -n '1697,1740p' src/chambers/fc-core/fc_core/fc_controller.py | diff /tmp/fc1_feather.txt -
```

Expected: no diff. If the line numbers have shifted, diff the feather block by content, not offset.

- [ ] **Step 4: Run the existing suite to confirm the port didn't break anything**

```bash
cd src/chambers/fc-core && python -m pytest fc_core/test/ -q 2>&1 | tail -15
```

Expected: the 3 known-failing tests from the 06-22 session (`test_current_mode_late_subscribe`, `test_current_mode_published_at_startup`, `test_scheduler_gap_keeps_current_mode`) may still fail. Record the exact pass/fail counts as the baseline. Any *new* failure is a port error and must be fixed before continuing.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "chore(fc-core): forward-port fc1/prod feather + band config onto main"
```

---

### Task 1: Extract the control law into a pure kernel

**Files:**
- Create: `src/chambers/fc-core/fc_core/control_kernel.py`
- Modify: `src/chambers/fc-core/fc_core/fc_controller.py` (replace the error-projection block with a call)
- Test: `src/chambers/fc-core/fc_core/test/test_control_kernel.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class BandSpec:
      band_low: float      # fraction, e.g. 0.885
      band_high: float     # fraction, e.g. 0.915
      defend_side: str     # 'low' | 'high' | 'both'

  def project_error_pct(rh: float, band: BandSpec) -> float | None
  ```
  Returns error in **percentage points**, negative below midpoint. Returns `None` for the `defend_side='low'` freeze case, which the caller handles by publishing duty 0 and disengaging the PID.

- [ ] **Step 1: Write the failing tests**

```python
# src/chambers/fc-core/fc_core/test/test_control_kernel.py
import pytest
from fc_core.control_kernel import BandSpec, project_error_pct

FRUITING = BandSpec(band_low=0.885, band_high=0.915, defend_side='both')

def test_zero_error_at_midpoint():
    assert project_error_pct(0.900, FRUITING) == pytest.approx(0.0)

def test_quadratic_feather_below_midpoint():
    # s = 1.0 pct below midpoint, w = 1.5 -> -s^2/(2w) = -1/3
    assert project_error_pct(0.890, FRUITING) == pytest.approx(-1.0 / 3.0, abs=1e-9)

def test_feather_value_at_band_low():
    # s = w = 1.5 -> -w/2 = -0.75
    assert project_error_pct(0.885, FRUITING) == pytest.approx(-0.75, abs=1e-9)

def test_linear_below_band_low():
    # s = 2.0 > w -> -(s - w/2) = -1.25
    assert project_error_pct(0.880, FRUITING) == pytest.approx(-1.25, abs=1e-9)

def test_c1_continuity_at_the_join():
    """Value and slope must match across s == w, or the derivative kick returns."""
    eps = 1e-6
    below = project_error_pct(0.885 + eps, FRUITING)
    above = project_error_pct(0.885 - eps, FRUITING)
    assert below == pytest.approx(above, abs=1e-5)
    d1 = (project_error_pct(0.885 + 2 * eps, FRUITING) - below) / eps
    d2 = (above - project_error_pct(0.885 - 2 * eps, FRUITING)) / eps
    assert d1 == pytest.approx(d2, rel=1e-3)

def test_zero_in_upper_half_of_band():
    """Feather is one-sided: no forcing between midpoint and band_high."""
    assert project_error_pct(0.910, FRUITING) == pytest.approx(0.0)

def test_positive_error_above_band_high_when_defending():
    assert project_error_pct(0.925, FRUITING) == pytest.approx(1.0, abs=1e-9)

def test_none_above_band_high_when_defend_low_only():
    band = BandSpec(band_low=0.885, band_high=0.915, defend_side='low')
    assert project_error_pct(0.925, band) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd src/chambers/fc-core && python -m pytest fc_core/test/test_control_kernel.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'fc_core.control_kernel'`

- [ ] **Step 3: Implement the kernel**

```python
# src/chambers/fc-core/fc_core/control_kernel.py
"""Pure, ROS-free control-law kernel.

Lifted verbatim from fc_controller.py's error-projection block (fc1/prod
commits b4f18e4 + 30534ff) so the simulator and the live controller can never
drift apart. No rclpy, no clock reads, no parameter lookups.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class BandSpec:
    band_low: float
    band_high: float
    defend_side: str


def project_error_pct(rh: float, band: BandSpec):
    """Band-aware error projection with the quadratic low-side feather.

    Returns error in percentage points (negative drives duty up), or None for
    the defend_side='low' freeze case the caller must handle by zeroing duty.
    """
    midpoint = (band.band_low + band.band_high) / 2.0
    w = (band.band_high - band.band_low) / 2.0 * 100.0

    if rh < midpoint:
        s = (midpoint - rh) * 100.0
        if w > 0 and s <= w:
            return -(s * s) / (2.0 * w)
        return -(s - w / 2.0)

    if rh > band.band_high:
        if band.defend_side in ('high', 'both'):
            return (rh - band.band_high) * 100.0
        return None

    return 0.0
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd src/chambers/fc-core && python -m pytest fc_core/test/test_control_kernel.py -q`
Expected: 8 passed

- [ ] **Step 5: Replace the inline block in fc_controller with a call**

In `fc_controller.py`, replace the error-projection block (the `midpoint = ...` through `else: error_pct = 0.0` region, ~lines 1710-1736) with:

```python
            from fc_core.control_kernel import BandSpec, project_error_pct
            _projected = project_error_pct(
                rh, BandSpec(mode.band_low, mode.band_high, mode.defend_side)
            )
            if _projected is None:
                if self._pid.auto_mode:
                    self._pid.set_auto_mode(False)
                self._publish_duty(0.0)
                ht_msg = Float32()
                ht_msg.data = float(self._effective_setpoint)
                self._humidity_target_pub.publish(ht_msg)
                po_msg = Float32()
                po_msg.data = 0.0
                self._pid_output_pub.publish(po_msg)
                return
            error_pct = _projected
```

Move the import to the module top alongside the other `fc_core` imports.

- [ ] **Step 6: Run the full controller suite for parity**

Run: `cd src/chambers/fc-core && python -m pytest fc_core/test/test_controller.py fc_core/test/test_controller_modes.py -q 2>&1 | tail -10`
Expected: same pass/fail counts as the Task 0 Step 4 baseline. No new failures.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "refactor(fc-core): extract band/feather error projection into pure control_kernel"
```

---

### Task 2: Chamber model fitted to the real trace

The prior 999.33 plan specified a first-principles air-mass model (`air_mass_kg=7.0`, `mister_rate_g_per_min=6.0`). **That model is wrong by ~40x** against measured data: 6 g/min into 5.76 m³ would move RH far faster than the observed 22.5 pts/h, because a fruiting chamber's wet substrate is a moisture buffer orders of magnitude larger than the air. Fit empirically instead.

**Files:**
- Create: `src/chambers/fc-core/fc_core/sim/__init__.py`
- Create: `src/chambers/fc-core/fc_core/sim/chamber_model.py`
- Test: `src/chambers/fc-core/fc_core/test/test_chamber_model.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class ChamberParams:
      fill_pts_per_hour: float = 22.5   # gross RH rise at delivered duty 1.0
      leak_pts_per_hour: float = 2.24   # RH fall at duty 0
      dead_time_s: float = 360.0        # transport + mixing lag
      tau_s: float = 600.0              # first-order mixing time constant

  class ChamberModel:
      def __init__(self, params: ChamberParams, rh0: float): ...
      def step(self, delivered_duty: float, dt_s: float) -> float
      @property
      def rh(self) -> float          # percent, e.g. 90.44
  ```

- [ ] **Step 1: Write the failing tests**

```python
# src/chambers/fc-core/fc_core/test/test_chamber_model.py
import pytest
from fc_core.sim.chamber_model import ChamberModel, ChamberParams

P = ChamberParams()

def test_decays_at_measured_leak_rate_when_off():
    m = ChamberModel(P, rh0=90.0)
    for _ in range(3600):
        m.step(delivered_duty=0.0, dt_s=1.0)
    assert m.rh == pytest.approx(90.0 - 2.24, abs=0.05)

def test_rises_at_measured_rate_at_forty_percent_duty():
    """Matches the observed +6.76 pts/h while the 0.40 cap was binding."""
    m = ChamberModel(P, rh0=90.0)
    for _ in range(3600 + int(P.dead_time_s)):
        m.step(delivered_duty=0.40, dt_s=1.0)
    net = (m.rh - 90.0)
    assert net == pytest.approx(6.76, abs=0.4)

def test_equilibrium_duty_is_about_ten_percent():
    m = ChamberModel(P, rh0=90.0)
    u = P.leak_pts_per_hour / P.fill_pts_per_hour
    for _ in range(6 * 3600):
        m.step(delivered_duty=u, dt_s=1.0)
    assert m.rh == pytest.approx(90.0, abs=0.15)

def test_dead_time_delays_the_response():
    m = ChamberModel(P, rh0=90.0)
    for _ in range(int(P.dead_time_s) - 30):
        m.step(delivered_duty=1.0, dt_s=1.0)
    assert m.rh < 90.0, "RH must still be falling before dead time elapses"

def test_step_is_dt_invariant():
    a = ChamberModel(P, rh0=90.0)
    b = ChamberModel(P, rh0=90.0)
    for _ in range(1800):
        a.step(0.3, dt_s=1.0)
    for _ in range(180):
        b.step(0.3, dt_s=10.0)
    assert a.rh == pytest.approx(b.rh, abs=0.05)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd src/chambers/fc-core && python -m pytest fc_core/test/test_chamber_model.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'fc_core.sim'`

- [ ] **Step 3: Implement the model**

```python
# src/chambers/fc-core/fc_core/sim/__init__.py
"""Offline chamber simulation. Imports must stay free of rclpy and RPi.GPIO."""
```

```python
# src/chambers/fc-core/fc_core/sim/chamber_model.py
"""Empirically-fitted FOPDT model of FC-1's humidity response.

Parameters are fitted to the 2026-08-08 26 h trace, NOT derived from air mass.
First-principles air-only models are off by ~40x because the substrate is a
far larger moisture buffer than the air volume.
"""
from collections import deque
from dataclasses import dataclass


@dataclass
class ChamberParams:
    fill_pts_per_hour: float = 22.5
    leak_pts_per_hour: float = 2.24
    dead_time_s: float = 360.0
    tau_s: float = 600.0


class ChamberModel:
    def __init__(self, params: ChamberParams, rh0: float):
        self.p = params
        self._rh = float(rh0)
        self._applied = 0.0          # duty after first-order mixing lag
        self._pipeline: deque = deque()
        self._pending_s = 0.0

    @property
    def rh(self) -> float:
        return self._rh

    def step(self, delivered_duty: float, dt_s: float) -> float:
        # Transport delay: duty entering now takes dead_time_s to have effect.
        self._pipeline.append((delivered_duty, dt_s))
        self._pending_s += dt_s
        effective = 0.0
        while self._pending_s > self.p.dead_time_s and self._pipeline:
            effective, used = self._pipeline.popleft()
            self._pending_s -= used

        # First-order mixing toward the delayed command.
        alpha = dt_s / max(self.p.tau_s, 1e-9)
        if alpha > 1.0:
            alpha = 1.0
        self._applied += alpha * (effective - self._applied)

        hours = dt_s / 3600.0
        self._rh += (self._applied * self.p.fill_pts_per_hour
                     - self.p.leak_pts_per_hour) * hours
        return self._rh
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd src/chambers/fc-core && python -m pytest fc_core/test/test_chamber_model.py -q`
Expected: 5 passed. If `test_rises_at_measured_rate_at_forty_percent_duty` is outside tolerance, adjust `tau_s` — do not adjust `fill_pts_per_hour` or `leak_pts_per_hour`, those are measured.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(sim): FOPDT chamber model fitted to the 2026-08-08 trace"
```

---

### Task 3: PWM/relay simulator with pipe transport loss

Mirrors `fc_pwm_driver._tick()` exactly, then adds the physical pipe behaviour the real driver is blind to.

**Files:**
- Create: `src/chambers/fc-core/fc_core/sim/pwm_window.py`
- Test: `src/chambers/fc-core/fc_core/test/test_pwm_window.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class PwmConfig:
      window_s: float = 120.0
      min_pulse_s: float = 10.0
      max_duty_5min_avg: float = 0.40
      pipe_transit_s: float = 6.0
      accumulate: bool = False      # Task 6 switches this on

  class PwmSimulator:
      def step(self, commanded_duty: float, dt_s: float) -> float
      # returns DELIVERED duty for this dt (vapour actually leaving the outlet)
      @property
      def relay_cycles(self) -> int
      @property
      def commanded_but_discarded_s(self) -> float
  ```

- [ ] **Step 1: Write the failing tests**

```python
# src/chambers/fc-core/fc_core/test/test_pwm_window.py
import pytest
from fc_core.sim.pwm_window import PwmConfig, PwmSimulator

def _run(sim, duty, seconds):
    total = 0.0
    for _ in range(int(seconds)):
        total += sim.step(duty, dt_s=1.0)
    return total / seconds

def test_min_pulse_discards_subthreshold_commands():
    """The bug: 0.05 commanded against a 10s/120s floor delivers nothing."""
    sim = PwmSimulator(PwmConfig())
    assert _run(sim, 0.05, 600) == pytest.approx(0.0, abs=1e-9)
    assert sim.commanded_but_discarded_s > 0

def test_pipe_transit_eats_the_head_of_every_pulse():
    """A 10s pulse with 6s transit delivers only 4s of vapour."""
    cfg = PwmConfig(window_s=120.0, min_pulse_s=10.0, pipe_transit_s=6.0)
    sim = PwmSimulator(cfg)
    delivered = _run(sim, 10.0 / 120.0, 120)
    assert delivered == pytest.approx(4.0 / 120.0, abs=0.005)

def test_longer_pulses_are_more_efficient():
    """Same commanded duty, fewer+longer pulses deliver more water."""
    short = PwmSimulator(PwmConfig(window_s=120.0, pipe_transit_s=6.0))
    long_ = PwmSimulator(PwmConfig(window_s=600.0, pipe_transit_s=6.0))
    a = _run(short, 0.25, 3600)
    b = _run(long_, 0.25, 3600)
    assert b > a

def test_rolling_cap_throttles_sustained_high_commands():
    sim = PwmSimulator(PwmConfig())
    assert _run(sim, 1.0, 1800) <= 0.42

def test_relay_cycles_are_counted():
    sim = PwmSimulator(PwmConfig())
    _run(sim, 0.5, 1200)
    assert sim.relay_cycles >= 8
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd src/chambers/fc-core && python -m pytest fc_core/test/test_pwm_window.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Mirror `fc_pwm_driver._tick()`: accumulate elapsed time, and on window rollover lock in `duty`, apply the rolling 5-min cap by back-solving `cap*(n+1) - current_sum`, then apply min-pulse round-down. Track `_window_on_seconds`. Within a window the relay is HIGH for the first `on_sec`.

Delivered duty for a given second is 1.0 only when the relay is HIGH **and** at least `pipe_transit_s` has elapsed since that pulse's rising edge; otherwise 0.0. Increment `relay_cycles` on each rising edge. When a command is rounded down to zero, add `commanded_duty * window_s` to `commanded_but_discarded_s`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd src/chambers/fc-core && python -m pytest fc_core/test/test_pwm_window.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(sim): PWM/relay simulator with pipe transit loss and wear counters"
```

---

### Task 4: Replay harness and baseline fidelity gate

**Files:**
- Create: `src/chambers/fc-core/fc_core/sim/replay.py`
- Create: `src/chambers/fc-core/fc_core/test/fixtures/trace_2026_08_08.csv`
- Create: `scripts/extract_trace.py`
- Test: `src/chambers/fc-core/fc_core/test/test_replay_fidelity.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class RunMetrics:
      rh_min: float; rh_max: float; rh_p2p: float; rh_mean: float
      duty_mean: float; relay_cycles: int; discarded_s: float
      cycle_period_h: float | None; water_units: float

  def run_closed_loop(hours, params, pwm_cfg, band, gains, rh0, slew=None) -> RunMetrics
  ```

- [ ] **Step 1: Export the fixture**

Write `scripts/extract_trace.py` to dump 1-minute buckets of `fc.humidity`, `fc.humidifier_duty`, `fc.temperature` for `2026-08-07 22:00` .. `2026-08-09 00:02` UYT from Timescale into the fixture CSV. Run it once and commit the CSV.

- [ ] **Step 2: Write the failing fidelity tests**

```python
# src/chambers/fc-core/fc_core/test/test_replay_fidelity.py
import pytest
from fc_core.sim.replay import run_closed_loop, DEFAULT_BAND, DEFAULT_GAINS
from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.pwm_window import PwmConfig

def test_baseline_reproduces_the_observed_limit_cycle():
    """Sim must show the ~2h cycle before we are allowed to claim we fixed it."""
    m = run_closed_loop(hours=12, params=ChamberParams(), pwm_cfg=PwmConfig(),
                        band=DEFAULT_BAND, gains=DEFAULT_GAINS, rh0=90.0)
    assert m.cycle_period_h == pytest.approx(2.0, abs=0.6)
    assert m.rh_p2p > 3.0, "baseline must oscillate, else the model is wrong"

def test_baseline_discards_a_large_share_of_commanded_duty():
    m = run_closed_loop(hours=12, params=ChamberParams(), pwm_cfg=PwmConfig(),
                        band=DEFAULT_BAND, gains=DEFAULT_GAINS, rh0=90.0)
    assert m.discarded_s > 0.10 * 12 * 3600 * 0.05
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd src/chambers/fc-core && python -m pytest fc_core/test/test_replay_fidelity.py -q`
Expected: FAIL, `ModuleNotFoundError: fc_core.sim.replay`

- [ ] **Step 4: Implement the harness**

Wire `project_error_pct` → `simple_pid.PID(Kp, Ki, Kd, output_limits=(0,1))` with explicit `dt` → `PwmSimulator.step` → `ChamberModel.step`, one second per tick. Detect cycle period by finding duty rising edges past 0.5 separated by ≥15 min of quiet, mirroring the analysis that produced the ground-truth table.

- [ ] **Step 5: Run and tune until the baseline gate passes**

Run: `cd src/chambers/fc-core && python -m pytest fc_core/test/test_replay_fidelity.py -q`
Expected: 2 passed. **If the sim does not oscillate, stop and fix the model — every later result is worthless without this gate.** Tune only `dead_time_s` and `tau_s`; `fill`/`leak` are measured.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(sim): closed-loop replay harness + baseline limit-cycle fidelity gate"
```

---

### Task 5: Fix A — sub-threshold pulse accumulation

Bank commanded-but-undeliverable duty across windows; fire one full-length pulse when a pulse's worth has accrued. Preserves mean duty without ever firing a pulse shorter than the floor.

**Files:**
- Modify: `src/chambers/fc-core/fc_core/sim/pwm_window.py`
- Modify: `src/chambers/fc-core/fc_core/fc_pwm_driver.py`
- Test: `src/chambers/fc-core/fc_core/test/test_pwm_window.py`, `test_pwm_driver.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_accumulation_delivers_subthreshold_demand_on_average():
    """0.05 commanded must arrive as occasional full pulses, not silence."""
    cfg = PwmConfig(accumulate=True, min_pulse_s=20.0, pipe_transit_s=6.0)
    sim = PwmSimulator(cfg)
    delivered = _run(sim, 0.05, 7200)
    # 0.05 commanded, minus 6s transit loss on each 20s pulse -> ~70% efficiency
    assert delivered == pytest.approx(0.05 * 0.70, rel=0.30)
    assert delivered > 0.0

def test_accumulation_never_fires_a_short_pulse():
    cfg = PwmConfig(accumulate=True, min_pulse_s=20.0)
    sim = PwmSimulator(cfg)
    _run(sim, 0.04, 7200)
    assert all(p >= 20.0 for p in sim.pulse_lengths)

def test_accumulation_is_a_noop_above_the_floor():
    a = PwmSimulator(PwmConfig(accumulate=False))
    b = PwmSimulator(PwmConfig(accumulate=True))
    assert _run(a, 0.5, 3600) == pytest.approx(_run(b, 0.5, 3600), abs=0.01)
```

- [ ] **Step 2: Run to verify it fails** — `pytest fc_core/test/test_pwm_window.py -q`, expect FAIL on the three new tests.

- [ ] **Step 3: Implement in the simulator**, then port the identical logic to `fc_pwm_driver.py` behind a new `accumulate_subthreshold` parameter defaulting to **False** so the live default is unchanged.

- [ ] **Step 4: Run both suites** — `pytest fc_core/test/test_pwm_window.py fc_core/test/test_pwm_driver.py -q`. Expected: all pass, no regression in existing driver tests.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(fc-core): sub-threshold pulse accumulation, parameter-gated off by default"
```

---

### Task 6: Fix B — output slew limiter

The farmer's twice-asked "ramp it up more slowly". Deferred since 2026-06-22.

**Files:**
- Modify: `src/chambers/fc-core/fc_core/sim/replay.py`
- Modify: `src/chambers/fc-core/fc_core/fc_controller.py`
- Test: `src/chambers/fc-core/fc_core/test/test_controller.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_slew_limiter_caps_the_climb_rate():
    """With climb_seconds=180, duty cannot go 0 -> 1 faster than ~180s."""
    from fc_core.sim.replay import apply_slew
    duty, last = 1.0, 0.0
    ticks = 0
    while last < 0.99:
        last = apply_slew(desired=duty, last=last, dt=1.0, climb_seconds=180.0)
        ticks += 1
    assert 170 <= ticks <= 190

def test_slew_limiter_does_not_restrict_falling():
    from fc_core.sim.replay import apply_slew
    assert apply_slew(desired=0.0, last=1.0, dt=1.0, climb_seconds=180.0) == 0.0

def test_slew_limiter_disabled_when_climb_seconds_is_zero():
    from fc_core.sim.replay import apply_slew
    assert apply_slew(desired=1.0, last=0.0, dt=1.0, climb_seconds=0.0) == 1.0
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement** `apply_slew` in the sim, then wire it into `fc_controller` as `self._pid.output_limits = (0.0, min(1.0, last_duty + dt / climb_seconds))` each tick, behind a new `humidifier_climb_seconds` parameter defaulting to **0.0** (disabled) so live behaviour is unchanged. Reusing `output_limits` gets `simple_pid`'s anti-windup for free.

- [ ] **Step 4: Run the controller suite.** Expected: no new failures vs the Task 0 baseline.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(fc-core): humidifier output slew limiter, disabled by default"
```

---

### Task 7: Sweep and report

**Files:**
- Create: `src/chambers/fc-core/fc_core/sim/sweep.py`
- Create: `.planning/notes/2026-08-09-pid-limit-cycle/sim-results.md`

- [ ] **Step 1: Write the sweep**

Run 12 simulated hours for each configuration and tabulate `RunMetrics`:

| Config | window | min_pulse | accumulate | climb_s |
|---|---|---|---|---|
| baseline (as-live) | 120 | 10 | off | 0 |
| min_pulse raised only | 120 | 20 | off | 0 |
| accumulation only | 120 | 20 | on | 0 |
| slew only | 120 | 10 | off | 180 |
| both fixes | 120 | 20 | on | 180 |
| both + longer window | 300 | 20 | on | 180 |

- [ ] **Step 2: Run it and write the results file**

Report per config: RH peak-to-peak, cycle period, mean duty, **relay cycles/hour**, total water delivered, and discarded-command seconds. Call out explicitly whether any config trades a wear increase for stability.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "docs(sim): baseline vs fix sweep results"
```

---

### Task 8: Ticket and PR

- [ ] **Step 1: Create the Plane ticket** for the control fixes via the REST path (`/api/v1/workspaces/mossrock/...`, key in `~/.claude.json`), goal-titled, with the evergreen scope in the description and tonight's findings as a comment. Link it from the ROADMAP 999.33 entry and from MUSHY-52.

- [ ] **Step 2: Update ROADMAP 999.33** noting shape (a) is built, and correct the first-principles model numbers that were off by ~40x.

- [ ] **Step 3: Open the PR**

```bash
git push -u origin feat/chamber-sim-duty-shaping
gh pr create --title "Offline chamber sim + duty shaping (accumulation + slew limiter)" --body "<summary, sweep table, both fixes default-off, no fc1 deploy>"
```

- [ ] **Step 4: Commit any remaining docs.**

---

## Self-Review

**Spec coverage:** sim built (Tasks 2–4), calibrated against the real trace (Task 4), both fixes developed against it (Tasks 5–6), branch + PR deliverable (Task 8), feather forward-port unblocked (Task 0). Farmer's pipe-transit and 20 s-minimum constraints are modelled in Task 3 and exercised in Task 5.

**Placeholders:** none — every code step carries real code; the only prose-only steps are the sweep table and PR body, which are data-dependent by nature.

**Type consistency:** `BandSpec`/`project_error_pct` (Task 1) consumed by Task 4's harness; `ChamberParams`/`ChamberModel.step` (Task 2) and `PwmConfig`/`PwmSimulator.step` (Task 3) consumed by Task 4; `apply_slew` (Task 6) consumed by Task 7's sweep. `PwmSimulator.pulse_lengths` is introduced in Task 5's tests — it must be added to the class in Task 3's implementation step alongside `relay_cycles`.

**Risk:** Task 4's baseline gate is the load-bearing check. If the sim will not reproduce the observed cycle, every downstream conclusion is void and the correct action is to report that honestly rather than tune until the fixes look good.
