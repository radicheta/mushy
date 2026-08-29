"""Sigma-delta driver (MUSHY-129): same steady state as the 480s window,
but a demand step fires within one min-pulse instead of one window."""
import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fc_core.sim.pwm_sigma_delta import SigmaDeltaConfig, SigmaDeltaSimulator
from fc_core.sim.pwm_window import PwmConfig, PwmSimulator

DEPLOYED = dict(min_pulse_s=30.0, max_duty_5min_avg=0.90, pipe_transit_s=6.0)


def window():
    return PwmSimulator(PwmConfig(window_s=480.0, accumulate=True, **DEPLOYED))


def sigma():
    return SigmaDeltaSimulator(SigmaDeltaConfig(period_s=480.0, **DEPLOYED))


def run(sim, duty, seconds):
    total = sum(sim.step(duty, 1.0) for _ in range(int(seconds)))
    return total / seconds


@pytest.mark.parametrize('duty', [0.02, 0.0625, 0.20, 0.50, 0.70, 1.0])
def test_steady_state_matches_the_window(duty):
    """Same edges/day and delivered duty as the deployed window driver."""
    w, s = window(), sigma()
    dw, ds = run(w, duty, 86400), run(s, duty, 86400)
    assert s.relay_cycles == pytest.approx(w.relay_cycles, rel=0.10, abs=2)
    assert ds == pytest.approx(dw, abs=0.02)


def test_step_fires_within_one_min_pulse():
    """The 2026-08-29 shape: quiet, then a step. Window waits ~480s; we don't."""
    w, s = window(), sigma()
    for _ in range(100):                     # 100s into a window at duty 0.03
        w.step(0.03, 1.0); s.step(0.03, 1.0)
    first = {}
    for name, sim in (('window', w), ('sigma', s)):
        for t in range(600):
            sim.step(0.8, 1.0)
            if sim.relay_cycles and name not in first:
                first[name] = t
    assert first['sigma'] <= 40
    assert first['window'] >= 300


def test_never_emits_a_short_pulse():
    s = sigma()
    for duty in (0.02, 0.05, 0.3, 0.9, 0.0):
        run(s, duty, 3600)
    assert s.pulse_lengths and min(s.pulse_lengths) >= 30.0


def test_cap_bounds_sustained_full_demand():
    w, s = window(), sigma()
    assert run(s, 1.0, 3600) <= 0.90 + 0.02
    run(w, 1.0, 3600)
    assert s.relay_cycles <= w.relay_cycles + 1


def test_zero_never_fires():
    s = sigma()
    assert run(s, 0.0, 3600) == 0.0 and s.relay_cycles == 0


def test_demand_drop_does_not_over_deliver():
    """Bank is clamped: after a long cap-limited crash recovery, dropping the
    command to 0 must end the pulse within one max-hysteresis (120s)."""
    s = sigma()
    run(s, 1.0, 1800)
    on_after = sum(s.step(0.0, 1.0) for _ in range(600))
    assert on_after <= 120.0


# -- real fixture: fc1, 2026-08-29 20:13:53Z .. 20:40Z, 1 Hz commanded duty ----

FIXTURE = Path(__file__).resolve().parents[1] / 'sim' / 'data' / 'duty_2026-08-29_2013Z.csv'
T0 = datetime(2026, 8, 29, 20, 13, 53, tzinfo=timezone.utc)   # a window rollover
RECORDED_RELAY_ON = datetime(2026, 8, 29, 20, 29, 49, tzinfo=timezone.utc)


def _fixture():
    with FIXTURE.open() as f:
        return [(datetime.fromisoformat(t.replace('Z', '+00:00')), float(d)) for t, d in csv.reader(f)]


def _first_on(sim, rows):
    for t, duty in rows:
        sim.step(duty, 1.0)
        if sim.relay_cycles:
            return t
    return None


def test_window_sim_reproduces_the_recorded_miss():
    """Sanity: fed the recorded command, the window sim fires when fc1 did."""
    rows = _fixture()
    assert rows[0][0] == T0
    t = _first_on(window(), rows)
    assert abs((t - RECORDED_RELAY_ON).total_seconds()) <= 10


def test_sigma_delta_fires_within_a_minute_of_the_ramp():
    rows = _fixture()
    t = _first_on(sigma(), rows)
    ramp_start = datetime(2026, 8, 29, 20, 22, 0, tzinfo=timezone.utc)
    assert t is not None
    # The PID ramps slowly (0.04 -> 0.2 over the first 90s), so the driver
    # cannot fire before one min-pulse of demand has accrued. It must fire
    # the moment it has.
    banked, due = 0.0, None
    for ts, duty in rows:
        banked += duty
        if banked >= 30.0:
            due = ts
            break
    assert due is not None and (t - due).total_seconds() <= 2
    assert (RECORDED_RELAY_ON - t).total_seconds() >= 300, 'must beat fc1 by 5+ min'
