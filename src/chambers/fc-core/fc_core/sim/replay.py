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
from dataclasses import dataclass, field
from math import exp
from typing import List, Optional

from fc_core.control_kernel import BandSpec, duty_bias_factor, project_error_pct
from fc_core.sim.chamber_model import ChamberModel, ChamberParams
from fc_core.sim.psychrometrics import absolute_humidity_g_m3
from fc_core.sim.pwm_window import PwmConfig, PwmSimulator
from fc_core.vendor.simple_pid import PID

# Live fc1 values, read from the running controller 2026-08-09.
DEFAULT_BAND = BandSpec(band_low=0.885, band_high=0.915, defend_side='both')
DEFAULT_TARGET = 0.90

# Baseline synthetic conditions, chosen to match the 2026-08-08 fidelity trace
# (999.33-04-DESIGN-absolute-moisture.md, design limitation 5):
#   - chamber and ambient run at nearly the same temperature in August
#     (monthly means 10.7 C in / 10.5-11.0 C out), so DEFAULT_TEMP_C is used
#     for both sides of the gradient rather than modelling a separate ambient
#     temperature.
#   - the measured August chamber-minus-ambient gradient is ~0.30 g/m3 (the
#     table's Aug row), which the design doc reads as roughly RH_in ~94% vs
#     RH_out ~86% at that temperature. DEFAULT_AMBIENT_AH_G_M3 is the chamber's
#     90%-RH absolute humidity at 10.7 C (8.84 g/m3) minus 0.30 g/m3, i.e.
#     8.54 g/m3 -- equivalent to ~87% RH at 10.7 C, consistent with that
#     reading.
DEFAULT_TEMP_C = 10.7
DEFAULT_AMBIENT_AH_G_M3 = absolute_humidity_g_m3(DEFAULT_TEMP_C, 90.0) - 0.30


@dataclass
class Gains:
    kp: float = 0.36
    ki: float = 0.001
    kd: float = 4.0
    derivative_filter_tau: float = 60.0
    integrator_decay_tau: float = 1800.0
    bypass_threshold: float = 0.05


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
    rh_series: List[float] = field(default_factory=list)
    duty_series: List[float] = field(default_factory=list)

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
                    dt: float = 1.0,
                    ambient_ah_g_m3: float = DEFAULT_AMBIENT_AH_G_M3,
                    temp_c: float = DEFAULT_TEMP_C) -> RunMetrics:
    params = params or ChamberParams()
    pwm_cfg = pwm_cfg or PwmConfig()

    chamber = ChamberModel(params, rh0_pct=rh0, temp_c=temp_c)
    pwm = PwmSimulator(pwm_cfg)
    pid = PID(gains.kp, gains.ki, gains.kd, setpoint=0.0, output_limits=(0.0, 1.0))
    d_filtered = 0.0
    last_duty = 0.0

    rh_series: List[float] = []
    duty_series: List[float] = []
    delivered_total = 0.0

    steps = int(hours * 3600.0 / dt)
    for _ in range(steps):
        rh_frac = chamber.rh / 100.0

        projected = project_error_pct(rh_frac, band)
        if projected is None:
            if pid.auto_mode:
                pid.set_auto_mode(False)
            duty = 0.0
        else:
            error_pct = projected

            # Mode C bypass: nearest defended edge (fc_controller ~line 1739).
            if band.defend_side == 'low':
                nearest = band.band_low
            elif band.defend_side == 'high':
                nearest = band.band_high
            else:
                nearest = band.band_low if rh_frac <= target else band.band_high
            edge_pct = abs(rh_frac - nearest) * 100.0
            bypass_pct = gains.bypass_threshold * 100.0

            if edge_pct > bypass_pct and rh_frac < nearest:
                if pid.auto_mode:
                    pid.set_auto_mode(False)
                duty = 1.0
            else:
                if not pid.auto_mode:
                    pid.set_auto_mode(True, last_output=1.0)
                    d_filtered = 0.0

                # 999.49 in-band integrator decay, applied BEFORE the PID call.
                if gains.integrator_decay_tau > 0 and dt > 0 and error_pct == 0.0:
                    pid._integral *= exp(-dt / gains.integrator_decay_tau)

                raw = pid(error_pct, dt=dt)

                # 999.32 external derivative low-pass.
                if gains.derivative_filter_tau > 0 and dt > 0:
                    p_term, i_term, d_raw = pid.components
                    alpha = dt / (gains.derivative_filter_tau + dt)
                    d_filtered = alpha * d_raw + (1 - alpha) * d_filtered
                    raw = max(0.0, min(1.0, p_term + i_term + d_filtered))
                duty = raw

                # Feedforward bias -- PID branch only, mirroring
                # fc_controller. The freeze and Mode C paths must not get it.
                # MUSHY-57: faded across the upper band so it can never floor
                # the output; a genuine zero-demand day still reaches duty 0.
                if duty_bias > 0.0:
                    duty = max(0.0, min(
                        1.0, duty + duty_bias * duty_bias_factor(rh_frac, band)))

        duty = apply_slew(duty, last_duty, dt, climb_seconds)
        last_duty = duty

        delivered = pwm.step(duty, dt_s=dt)
        chamber.step(delivered_duty=delivered, dt_s=dt, ambient_ah_g_m3=ambient_ah_g_m3)

        rh_series.append(chamber.rh)
        duty_series.append(duty)
        delivered_total += delivered * dt

    return _metrics(rh_series, duty_series, pwm, hours, delivered_total, dt)


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
