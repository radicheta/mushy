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
    # theta from ONE isolated pulse is only a factor-2 quantity: the
    # (theta, tau) valley is flat under 0.1 %RH noise -- measured 43-148 s for
    # a true 50 s over seeds 0-4, at dt 2, 5 and 10 alike. What this test can
    # defend is that the grid search leaves theta somewhere the data chose
    # rather than pinned at the 360 s start (MUSHY-138 ruling 8). Closed-loop
    # windows, which carry the background pulse train as extra excitation, do
    # far better: median 42 s vs 50 s in test_two_twin_convergence.
    assert 20.0 < f.dead_time_s < 150.0
    assert f.rmse_pct < 0.2


def test_fit_dead_time_does_not_depend_on_the_starting_belief():
    """The regression ruling 8 fixed: dead_time enters ChamberModel through a
    dt-quantised arrival queue, so a default finite-difference Jacobian reads a
    zero gradient and theta stayed at whatever it started at."""
    w = synth_window(TRUE)
    thetas = [fit_window(w, replace(BASE, dead_time_s=t)).dead_time_s
              for t in (5.0, 30.0, 360.0, 900.0)]
    assert max(thetas) - min(thetas) < 5.0, thetas


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
    # a second pulse 20 min after the first is modelled input, not
    # contamination (ruling 12): the first window still opens.
    relay2 = list(w.relay)
    for i in range(n):
        if 600 + 1200 <= i * w.dt < 600 + 1200 + 60:
            relay2[i] = 1.0
    assert len(find_quasi_windows(w.dt, w.rh, w.temp, w.ambient_ah, relay2)) == 1
    assert len(find_quasi_windows(w.dt, w.rh, w.temp, w.ambient_ah, w.relay)) == 1


def test_find_quasi_windows_requires_idle_before_the_pulse():
    w = synth_window(TRUE)
    n, dt = len(w.rh), w.dt
    relay2 = [0.0] * n
    for i in range(n):
        t = i * dt
        if 600 <= t < 600 + 150:                          # qualifying pulse (900s idle before it)
            relay2[i] = 1.0
        if 600 + 150 + 300 <= t < 600 + 150 + 300 + 60:    # only 5 min OFF before this one -- not a window
            relay2[i] = 1.0
    windows = find_quasi_windows(dt, w.rh, w.temp, w.ambient_ah, relay2)
    assert len(windows) == 1
    assert windows[0].probe_start_idx == int(600 / dt)


def test_aggregate_rejects_a_median_sitting_on_a_fit_bound():
    """A fit that pins at a bound is a failed fit, not a measurement: the fit
    bounds are wider than the guard's plausibility box, so nothing downstream
    would notice it otherwise."""
    from fc_core.sim.probe_fit import BOUNDS_HI, WindowFit
    fits = [WindowFit(BOUNDS_HI[0], 1.0, 100.0, 600.0, 0.01) for _ in range(5)]
    a = aggregate(fits, BASE, [6.0] * 5)
    assert not a.valid and 'fill_g_per_h_at_bound' in a.reasons
