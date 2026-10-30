import pytest

from fc2_core.scheduler import BurstScheduler, duty_pct


def run(s, t0, t1, rate, pulse=60.0, step=1.0):
    opened = []
    t = t0
    while t < t1:
        if s.tick(t, rate, pulse): opened.append(t)
        t += step
    return opened


def test_first_burst_waits_one_gap():
    s = BurstScheduler(0.0)
    assert not s.tick(0.0, 1.0, 60.0)
    assert not s.tick(3599.0, 1.0, 60.0)
    assert s.tick(3600.0, 1.0, 60.0)


def test_burst_lasts_pulse_sec():
    s = BurstScheduler(0.0)
    opened = run(s, 3600.0, 3800.0, 1.0)
    assert opened[0] == 3600.0 and opened[-1] == 3659.0 and len(opened) == 60


def test_six_per_hour_after_warmup():
    s = BurstScheduler(0.0)
    run(s, 0.0, 600.0, 6.0)
    starts = [t for t in range(600, 4200) if s.tick(float(t), 6.0, 60.0) and s.last_burst_start == t]
    assert len(starts) == 6


def test_rate_jump_gives_one_burst_not_a_storm():
    s = BurstScheduler(0.0)
    run(s, 0.0, 1800.0, 1.0)          # no burst yet, half a gap in
    opened = run(s, 1800.0, 2400.0, 6.0)
    assert opened[0] == 1800.0        # overdue under the new rate: one burst now
    assert len(opened) == 60          # and only that one inside this 10 min


def test_zero_rate_closes_mid_burst():
    s = BurstScheduler(0.0)
    assert s.tick(3600.0, 1.0, 60.0)
    assert not s.tick(3610.0, 0.0, 60.0)


def test_duty_pct_window_and_open_interval():
    assert duty_pct([(0.0, 60.0)], 3600.0) == pytest.approx(60 / 36)
    assert duty_pct([(0.0, 60.0)], 3660.0) == 0.0
    assert duty_pct([(3570.0, None)], 3600.0) == pytest.approx(30 / 36)
