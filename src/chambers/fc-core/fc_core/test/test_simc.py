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
