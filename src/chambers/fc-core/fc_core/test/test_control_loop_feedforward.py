"""MUSHY-125: the extracted control law carries the temperature feedforward
exactly as fc_controller does -- after the PID clamp, faded like the bias."""
import pytest

from fc_core.control_kernel import temp_feedforward_gain
from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.control_loop import ControlLoop
from fc_core.sim.psychrometrics import absolute_humidity_g_m3
from fc_core.sim.pwm_sigma_delta import SigmaDeltaConfig, SigmaDeltaSimulator
from fc_core.sim.replay import (DEFAULT_AMBIENT_AH_G_M3, DEFAULT_BAND, DEFAULT_TEMP_C,
                                run_closed_loop)


def _settle(loop, rh, temp, seconds):
    duty = 0.0
    for _ in range(seconds):
        duty, _ = loop.step(rh, 1.0, temp_c=temp)
    return duty


def test_no_temperature_means_no_feedforward():
    loop = ControlLoop(DEFAULT_BAND, temp_ff_gain=0.2)
    off = ControlLoop(DEFAULT_BAND)
    for _ in range(100):
        a, _ = loop.step(0.895, 1.0)
        b, _ = off.step(0.895, 1.0)
    assert a == b


def test_warming_ramp_adds_duty_below_the_midpoint():
    ff = ControlLoop(DEFAULT_BAND, temp_ff_gain=1.0)
    off = ControlLoop(DEFAULT_BAND)
    t = 12.0
    p = ChamberParams()
    for _ in range(3600):
        t += 0.5 / 3600.0                          # +0.5 C/h
        d_ff, raw_ff = ff.step(0.895, 1.0, temp_c=t)
        d_off, raw_off = off.step(0.895, 1.0, temp_c=t)
    assert raw_ff == raw_off                        # PID untouched, telemetry unchanged
    assert d_ff == pytest.approx(d_off + 0.5 * temp_feedforward_gain(0.895, t, p.fill_g_per_h, p.surface_g_per_k), abs=0.01)
    assert d_ff > d_off + 0.05                      # and it is a real contribution


def test_feedforward_never_pushes_above_band_high():
    ff = ControlLoop(DEFAULT_BAND, temp_ff_gain=2.0)
    t = 14.0
    for _ in range(3600):
        t += 3.0 / 3600.0
        d, _ = ff.step(0.916, 1.0, temp_c=t)
    assert d == 0.0


def test_synthetic_dawn_ramp_holds_rh_nearer_the_setpoint():
    """The whole point: through a warming ramp saturation runs away from a
    fixed water content, RH drops, and the reactive loop only learns of it
    after the fact (and then overshoots once the ramp ends).

    Ambient AH tracks the chamber temperature here so the gradient stays at
    the baseline 0.703 g/m3 and the ONLY disturbance is the saturation
    slope. Sigma-delta driver + equilibrium bias so the baseline is not
    limit-cycling (that swing is bigger than the ramp signal). Trim 1.0 =
    the model's own gain, (rh * V * dAH_sat/dT - C) / F, ~0.1 here.
    """
    def temp(t_s):                                  # 4 h flat, +2 C/h for 3 h, flat
        h = t_s / 3600.0
        return 6.0 + 2.0 * min(max(h - 4.0, 0.0), 3.0)

    def ambient(t_s):
        return absolute_humidity_g_m3(temp(t_s), 90.0) - 0.703

    bias = ChamberParams().equilibrium_duty(
        absolute_humidity_g_m3(DEFAULT_TEMP_C, 90.0), DEFAULT_AMBIENT_AH_G_M3)

    def rms_from_setpoint(gain):
        m = run_closed_loop(hours=12.0, rh0=90.0, temp_c=temp, ambient_ah_g_m3=ambient,
                            duty_bias=bias, temp_ff_gain=gain,
                            pwm=SigmaDeltaSimulator(SigmaDeltaConfig()))
        window = m.rh_series[4 * 3600:9 * 3600]     # ramp + 2 h of aftermath
        return (sum((x - 90.0) ** 2 for x in window) / len(window)) ** 0.5

    base, with_ff = rms_from_setpoint(0.0), rms_from_setpoint(1.0)
    assert with_ff < 0.6 * base, (base, with_ff)
