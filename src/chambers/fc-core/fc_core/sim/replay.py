"""Closed-loop replay harness: control law + PWM/relay + chamber, offline.

Mirrors ``fc_controller._control_loop()`` faithfully, including the parts that
are easy to forget and that dominate the observed behaviour:

* the band/feather projection (shared code, ``fc_core.control_kernel``)
* Mode C open-loop bypass below a defended floor, with integrator freeze
* bumpless re-engage from Mode C (``last_output=1.0``) and D-filter reset
* 999.49 in-band integrator exponential decay
* 999.32 external low-pass filter on the derivative term

Uses the VENDORED simple_pid, the same one the Pi runs. `dt` is always passed
explicitly so the PID never reads a wall clock.
"""
import random
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Union

TimeVarying = Union[float, Callable[[float], float]]

from fc_core.control_kernel import BandSpec, ProbeScheduler
from fc_core.sim.chamber_model import ChamberModel, ChamberParams
from fc_core.sim.control_loop import ControlLoop, Gains
from fc_core.sim.psychrometrics import absolute_humidity_g_m3
from fc_core.sim.pwm_window import PwmConfig, PwmSimulator

# Live fc1 values, read from the running controller 2026-08-09.
DEFAULT_BAND = BandSpec(band_low=0.885, band_high=0.915, defend_side='both')
DEFAULT_TARGET = 0.90

# Baseline synthetic conditions: the MEASURED conditions of the 2026-08-08
# fidelity trace itself (queried directly), NOT August monthly means:
#   chamber temperature              6.00 C
#   ambient temperature              6.20 C
#   chamber RH                       90.51 %
#   chamber-minus-ambient AH gap     mean 0.703 g/m3 (min -0.296, max 2.641)
#
# An earlier version of this file used the August MONTHLY means from
# 999.33-04-DESIGN-absolute-moisture.md design limitation 5 (10.7 C, ~0.30
# g/m3 gradient) on the mistaken assumption that they stood in for the
# specific day. They do not: 2026-08-08 ran 4.7 C colder than the monthly
# mean with a 2.3x larger gradient, and the fidelity gate FAILED at the
# monthly-mean conditions as a direct result (see task-4-report.md). Do not
# repeat that substitution -- if this fixture is ever revisited, query the
# actual day's numbers again rather than reaching for a monthly table.
DEFAULT_TEMP_C = 6.0
DEFAULT_AMBIENT_AH_G_M3 = absolute_humidity_g_m3(DEFAULT_TEMP_C, 90.0) - 0.703


# Gains lives in fc_core.sim.control_loop now (MUSHY-59); re-exported here
# for backward compatibility with existing imports of DEFAULT_GAINS.
DEFAULT_GAINS = Gains()


@dataclass
class RunMetrics:
    rh_min: float = 0.0
    rh_max: float = 0.0
    rh_p2p: float = 0.0
    rh_mean: float = 0.0
    duty_mean_commanded: float = 0.0
    duty_mean_delivered: float = 0.0
    relay_cycles: int = 0
    relay_cycles_per_hour: float = 0.0
    discarded_s: float = 0.0
    cycle_period_h: Optional[float] = None
    burst_count: int = 0
    water_units: float = 0.0
    rh_series: List[float] = field(default_factory=list)     # SENSED rh, %
    duty_series: List[float] = field(default_factory=list)
    temp_series: List[float] = field(default_factory=list)
    ambient_series: List[float] = field(default_factory=list)  # g/m3
    relay_series: List[float] = field(default_factory=list)    # 1.0 relay closed
    probe_series: List[float] = field(default_factory=list)    # 1.0 probe commanded
    dt: float = 1.0

    def summary(self) -> str:
        period = f'{self.cycle_period_h:.2f} h' if self.cycle_period_h else 'none'
        return (f'RH {self.rh_min:.2f}-{self.rh_max:.2f} (p2p {self.rh_p2p:.2f})  '
                f'period {period}  duty_cmd {self.duty_mean_commanded:.3f}  '
                f'delivered {self.duty_mean_delivered:.3f}  '
                f'relay {self.relay_cycles_per_hour:.1f}/h  '
                f'discarded {self.discarded_s:.0f}s')


def apply_slew(desired: float, last: float, dt: float, climb_seconds: float) -> float:
    """Rate-limit the RISE of duty. Falling is never restricted.

    climb_seconds is the time a full 0 -> 1 sweep must take. 0 disables.
    """
    if climb_seconds <= 0.0:
        return desired
    ceiling = last + dt / climb_seconds
    return min(desired, ceiling)


def run_closed_loop(hours: float,
                    params: ChamberParams = None,
                    pwm_cfg: PwmConfig = None,
                    band: BandSpec = DEFAULT_BAND,
                    gains: Gains = DEFAULT_GAINS,
                    rh0: float = 90.0,
                    target: float = DEFAULT_TARGET,
                    climb_seconds: float = 0.0,
                    duty_bias: float = 0.0,
                    temp_ff_gain: float = 0.0,
                    dt: float = 1.0,
                    ambient_ah_g_m3: TimeVarying = DEFAULT_AMBIENT_AH_G_M3,
                    temp_c: TimeVarying = DEFAULT_TEMP_C,
                    pwm=None,
                    probe: ProbeScheduler = None,
                    params_belief: ChamberParams = None,
                    rh_noise_pct: float = 0.0,
                    seed: int = 0) -> RunMetrics:
    """``ambient_ah_g_m3`` and ``temp_c`` may each be a constant float (held for
    the whole run, the original behaviour) or a callable ``elapsed_s -> value``
    for a driven replay against real recorded/ambient conditions.

    ``pwm`` is the actuator simulator. It defaults to ``PwmSimulator`` (the
    retired fixed-window driver) so existing callers are unchanged; pass a
    ``SigmaDeltaSimulator`` to replay against what fc1 has actually run since
    2026-08-29 21:08Z (MUSHY-129). Both expose ``step(commanded, dt_s)`` plus
    the ``relay_cycles``/``commanded_but_discarded_s`` fields ``_metrics``
    reads, so they are interchangeable here. ``pwm_cfg`` is ignored when
    ``pwm`` is supplied.

    ``params`` is the PLANT; ``params_belief`` (MUSHY-138) is what the
    controller thinks, feeding ``ControlLoop.params`` -- defaults to
    ``params`` for backward compatibility. ``rh_noise_pct > 0`` makes
    ``rh_series`` the SENSED value (gaussian noise + 0.01 quantisation)
    rather than the true chamber RH."""
    params = params or ChamberParams()
    pwm_cfg = pwm_cfg or PwmConfig()

    temp_c0 = temp_c(0.0) if callable(temp_c) else temp_c
    chamber = ChamberModel(params, rh0_pct=rh0, temp_c=temp_c0)
    pwm = pwm if pwm is not None else PwmSimulator(pwm_cfg)
    assert probe is None or hasattr(pwm, 'relay_on'), (
        f'{type(pwm).__name__} has no .relay_on: the probe fit reads relay edges, and '
        'the getattr default below would hand it an all-zero relay series')
    control = ControlLoop(band, gains=gains, target=target, duty_bias=duty_bias,
                          temp_ff_gain=temp_ff_gain, params=params_belief, probe=probe)
    last_duty = 0.0
    rng = random.Random(seed)

    rh_series: List[float] = []
    duty_series: List[float] = []
    temp_series: List[float] = []
    ambient_series: List[float] = []
    relay_series: List[float] = []
    probe_series: List[float] = []
    delivered_total = 0.0

    steps = int(hours * 3600.0 / dt)
    elapsed = 0.0
    for _ in range(steps):
        rh_true = chamber.rh
        rh_sensed = rh_true
        if rh_noise_pct > 0.0:
            rh_sensed = round(rh_true + rng.gauss(0.0, rh_noise_pct), 2)
        rh_frac = rh_sensed / 100.0
        temp_now = temp_c(elapsed) if callable(temp_c) else temp_c

        duty, _raw_pid_output = control.step(rh_frac, dt, temp_c=temp_now)

        duty = apply_slew(duty, last_duty, dt, climb_seconds)
        last_duty = duty

        delivered = pwm.step(duty, dt_s=dt)
        ambient_now = ambient_ah_g_m3(elapsed) if callable(ambient_ah_g_m3) else ambient_ah_g_m3
        chamber.step(delivered_duty=delivered, dt_s=dt, ambient_ah_g_m3=ambient_now, temp_c=temp_now)

        rh_series.append(rh_sensed)
        duty_series.append(duty)
        temp_series.append(temp_now)
        ambient_series.append(ambient_now)
        relay_series.append(1.0 if getattr(pwm, 'relay_on', False) else 0.0)
        probe_series.append(1.0 if control.probe.active else 0.0)
        delivered_total += delivered * dt
        elapsed += dt

    m = _metrics(rh_series, duty_series, pwm, hours, delivered_total, dt)
    m.temp_series, m.ambient_series = temp_series, ambient_series
    m.relay_series, m.probe_series, m.dt = relay_series, probe_series, dt
    return m


def _metrics(rh_series, duty_series, pwm, hours, delivered_total, dt) -> RunMetrics:
    m = RunMetrics()
    m.rh_min = min(rh_series)
    m.rh_max = max(rh_series)
    m.rh_p2p = m.rh_max - m.rh_min
    m.rh_mean = sum(rh_series) / len(rh_series)
    m.duty_mean_commanded = sum(duty_series) / len(duty_series)
    m.duty_mean_delivered = delivered_total / (hours * 3600.0)
    m.relay_cycles = pwm.relay_cycles
    m.relay_cycles_per_hour = pwm.relay_cycles / hours
    m.discarded_s = pwm.commanded_but_discarded_s
    m.water_units = delivered_total
    m.rh_series = rh_series
    m.duty_series = duty_series

    # Burst detection mirrors the Timescale analysis that produced the ground
    # truth: duty crossing 0.5 upward after >= 15 min of quiet.
    per_min = max(1, int(60.0 / dt))
    quiet_needed = 15 * per_min
    onsets, quiet = [], 0
    for i in range(1, len(duty_series)):
        if duty_series[i - 1] < 0.5 <= duty_series[i] and quiet >= quiet_needed:
            onsets.append(i)
        quiet = quiet + 1 if duty_series[i] < 0.5 else 0
    m.burst_count = len(onsets)
    if len(onsets) > 1:
        gaps = [(onsets[k] - onsets[k - 1]) * dt / 3600.0
                for k in range(1, len(onsets))]
        m.cycle_period_h = sum(gaps) / len(gaps)
    return m
