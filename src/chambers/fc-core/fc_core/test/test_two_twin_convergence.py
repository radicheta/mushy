# src/chambers/fc-core/fc_core/test/test_two_twin_convergence.py
"""Spec section 6: tune twin A's belief onto twin B's hidden parameters
using only the probe -> fit -> guard -> push loop, in simulation.

Proves the pipeline, not the model class: the fitter's forward model IS
ChamberModel. Real-chamber adequacy is section 4 step 2's job.
"""
from dataclasses import replace

from fc_core.control_kernel import ProbeConfig, ProbeScheduler
from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.probe_fit import aggregate, find_windows, fit_window
from fc_core.sim.pwm_sigma_delta import SigmaDeltaConfig, SigmaDeltaSimulator
from fc_core.sim.replay import DEFAULT_TEMP_C, run_closed_loop
from fc_core.sim.simc import guard, simc_gains

A0 = ChamberParams()                                       # today's belief
B = replace(A0, fill_g_per_h=A0.fill_g_per_h * 1.8, moisture_loss_m3_per_h=A0.moisture_loss_m3_per_h * 0.7,
            dead_time_s=50.0, tau_s=400.0)                 # the "real" chamber
DAYS, ROUNDS, DT = 3.0, 5, 2.0                             # ruling 10: 5 rounds allowed
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
        if 'dead_time_held' in agg.reasons:
            assert push.params.dead_time_s == belief.dead_time_s, (r, push.params.dead_time_s)
        belief = push.params
        history.append((agg, push, in_band_fraction(m)))

    for k in ('fill_g_per_h', 'moisture_loss_m3_per_h', 'tau_s'):
        got, want = getattr(belief, k), getattr(B, k)
        assert abs(got - want) / want < 0.2, (k, got, want)
        assert abs(got - want) <= max(history[-1][0].iqr[k], 0.2 * want), (k, got, want)

    # Dead time is deliberately NOT asserted to converge (MUSHY-138 ruling 15):
    # most closed-loop windows pin theta at the low fit bound, so aggregate()
    # holds the prior and flags 'dead_time_held' (asserted in-loop above). An
    # earlier version of this test appeared to converge theta only because the
    # fitter handed the guard the bound every round and the 2x ratchet walked
    # the belief 360 -> 45 s; that was the ratchet, not identification. What is
    # required now is only that theta stays plausible and never takes the bound.
    assert any('dead_time_held' in a.reasons for a, _, _ in history)
    assert 5.0 <= belief.dead_time_s <= 900.0, belief.dead_time_s

    # last round no worse than knowing B from the start
    oracle = one_round(B, B, seed=99)
    assert history[-1][2] >= in_band_fraction(oracle) - 0.05
    ratio = history[-1][1].gains.kp / simc_gains(B, DEFAULT_TEMP_C).kp
    # Lower bound relaxed 0.5 -> 0.35 with ruling 15: holding the prior dead
    # time (360 -> 90 s here, true 50 s) detunes SIMC by roughly theta_true /
    # theta_belief, and a too-slow loop is the safe direction -- the in-band
    # assertion above is what proves it is still good enough. The upper bound
    # stays 2.0: over-tuning is the dangerous side and must not be relaxed.
    assert 0.35 < ratio < 2.0, ratio


def test_probe_does_not_degrade_a_correct_chamber():
    with_probe = one_round(B, B, seed=5)
    quiet = run_closed_loop(hours=24.0 * DAYS, dt=DT, rh0=90.5, params=B, params_belief=B,
                            gains=simc_gains(B, DEFAULT_TEMP_C), temp_ff_gain=1.0,
                            pwm=SigmaDeltaSimulator(SigmaDeltaConfig()), rh_noise_pct=0.1, seed=5)
    assert in_band_fraction(with_probe) >= in_band_fraction(quiet) - 0.02
    assert sum(1 for i in range(1, len(with_probe.probe_series))
               if with_probe.probe_series[i] > with_probe.probe_series[i - 1]) >= 8
