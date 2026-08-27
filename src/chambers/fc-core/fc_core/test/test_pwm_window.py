"""PWM/relay simulator: min-pulse floor, rolling cap, pipe transit, wear.

The pipe-transit figure is farmer-measured on 2026-08-09: ~2 m of pipe between
the humidifier element and the chamber outlet, 5-7 s from relay-close to vapour
appearing. Every pulse loses its head to wetting pipe.
"""
import pytest

from fc_core.sim.pwm_window import PwmConfig, PwmSimulator


def _mean_delivered(sim, duty, seconds, dt=1.0):
    total = 0.0
    for _ in range(int(seconds / dt)):
        total += sim.step(duty, dt_s=dt) * dt
    return total / seconds


def test_min_pulse_discards_subthreshold_commands():
    """The core bug: 0.05 commanded against a 10s/120s floor delivers nothing."""
    sim = PwmSimulator(PwmConfig())
    assert _mean_delivered(sim, 0.05, 1200) == pytest.approx(0.0, abs=1e-9)
    assert sim.commanded_but_discarded_s > 0.0


def test_smallest_expressible_duty_without_accumulation():
    """min_pulse/window is the floor: 10/120 = 8.3 pct."""
    cfg = PwmConfig(min_pulse_s=10.0, window_s=120.0)
    assert cfg.min_pulse_s / cfg.window_s == pytest.approx(0.0833, abs=0.001)


def test_raising_the_floor_to_twenty_makes_it_worse():
    """Farmer's preferred 20s floor pushes the minimum above equilibrium demand."""
    cfg = PwmConfig(min_pulse_s=20.0, window_s=120.0)
    smallest = cfg.min_pulse_s / cfg.window_s
    assert smallest == pytest.approx(0.1667, abs=0.001)
    assert smallest > 0.10, 'must exceed the ~10 pct equilibrium duty'


def test_pipe_transit_eats_the_head_of_every_pulse():
    """A 10s pulse with 6s transit delivers only ~4s of vapour."""
    cfg = PwmConfig(window_s=120.0, min_pulse_s=10.0, pipe_transit_s=6.0)
    sim = PwmSimulator(cfg)
    delivered = _mean_delivered(sim, 10.0 / 120.0, 1200)
    assert delivered == pytest.approx(4.0 / 120.0, abs=0.006)


def test_longer_pulses_are_more_efficient():
    """Same commanded duty; fewer, longer pulses waste less on pipe wetting."""
    short = PwmSimulator(PwmConfig(window_s=120.0, pipe_transit_s=6.0))
    long_ = PwmSimulator(PwmConfig(window_s=600.0, pipe_transit_s=6.0))
    a = _mean_delivered(short, 0.25, 7200)
    b = _mean_delivered(long_, 0.25, 7200)
    assert b > a


def test_rolling_cap_throttles_sustained_high_commands():
    sim = PwmSimulator(PwmConfig())
    assert _mean_delivered(sim, 1.0, 3600) <= 0.42


def test_relay_cycles_are_counted():
    sim = PwmSimulator(PwmConfig())
    _mean_delivered(sim, 0.5, 1200)
    assert sim.relay_cycles >= 5


def test_zero_command_never_fires_the_relay():
    sim = PwmSimulator(PwmConfig())
    assert _mean_delivered(sim, 0.0, 1200) == 0.0
    assert sim.relay_cycles == 0


# -- accumulation ---------------------------------------------------------

def test_accumulation_delivers_subthreshold_demand_on_average():
    """0.05 commanded must arrive as occasional full pulses, not silence."""
    cfg = PwmConfig(accumulate=True, min_pulse_s=20.0, pipe_transit_s=6.0)
    sim = PwmSimulator(cfg)
    delivered = _mean_delivered(sim, 0.05, 14400)
    assert delivered > 0.0, 'accumulation must break the silence'
    # 20s pulses lose 6s each to pipe -> ~70 pct efficiency on the banked demand.
    assert delivered == pytest.approx(0.05 * 0.70, rel=0.35)


def test_accumulation_never_fires_a_short_pulse():
    cfg = PwmConfig(accumulate=True, min_pulse_s=20.0)
    sim = PwmSimulator(cfg)
    _mean_delivered(sim, 0.04, 14400)
    assert sim.pulse_lengths, 'expected at least one pulse'
    assert all(p >= 20.0 for p in sim.pulse_lengths)


def test_accumulation_is_a_noop_well_above_the_floor():
    a = PwmSimulator(PwmConfig(accumulate=False))
    b = PwmSimulator(PwmConfig(accumulate=True))
    assert _mean_delivered(a, 0.5, 3600) == pytest.approx(
        _mean_delivered(b, 0.5, 3600), abs=0.01)


def test_accumulation_discards_nothing():
    cfg = PwmConfig(accumulate=True, min_pulse_s=20.0)
    sim = PwmSimulator(cfg)
    _mean_delivered(sim, 0.05, 14400)
    assert sim.commanded_but_discarded_s == 0.0


def test_deployed_window_caps_relay_cycles_and_holds_ripple():
    """MUSHY-116: fc_config.yaml pwm_window_seconds 120 -> 480.

    Cycles/day are set by window length, not demand: one ON edge per window
    that carries a pulse. 480s caps the relay at 180/day (was 720). The cost
    is a longer OFF leg; at ~20 pct duty that is 6.4 min, and fc1's measured
    off-state decay of 0.15 %RH/min worst case keeps the ripple inside the
    +/-1.5 %RH fruiting band.
    """
    day = 86400
    cfg = PwmConfig(window_s=480.0, min_pulse_s=10.0, max_duty_5min_avg=0.90)
    sim = PwmSimulator(cfg)
    for _ in range(day):
        sim.step(0.20, dt_s=1.0)

    assert sim.relay_cycles <= day / cfg.window_s
    off_leg_min = (cfg.window_s - max(sim.pulse_lengths)) / 60.0
    assert off_leg_min * 0.15 < 1.5, 'worst-case ripple must stay inside the band'


def test_thirty_second_floor_without_banking_is_a_cliff_at_equilibrium():
    """MUSHY-116: why min_pulse 30 and accumulate_subthreshold are coupled.

    fc1's measured requirement is ~5% delivered duty. At a 480s window with
    ~6s pipe transit that needs a 30s pulse -- exactly the 30s floor. So the
    floor lands ON the operating point: a hair below it, the whole window is
    discarded and delivery is zero, not merely reduced. That discontinuity is
    a limit-cycle generator. Banking removes it.
    """
    cfg = dict(window_s=480.0, min_pulse_s=30.0, max_duty_5min_avg=0.90)
    just_below = 0.062          # 29.8s commanded -- under the 30s floor

    naive = _mean_delivered(PwmSimulator(PwmConfig(accumulate=False, **cfg)),
                            just_below, 86400)
    banked = _mean_delivered(PwmSimulator(PwmConfig(accumulate=True, **cfg)),
                             just_below, 86400)

    assert naive == pytest.approx(0.0, abs=1e-9), 'unbanked floor swallows the window whole'
    assert banked > 0.03, 'banking must keep delivery continuous below the floor'


def test_deployed_floor_beats_the_old_one_on_both_wear_and_efficiency():
    """The 10 -> 30 change only pays off with banking; check both claims."""
    def run(min_pulse, accumulate):
        sim = PwmSimulator(PwmConfig(window_s=480.0, min_pulse_s=min_pulse,
                                     max_duty_5min_avg=0.90, accumulate=accumulate))
        total = sum(sim.step(0.05, 1.0) for _ in range(86400))
        return sim.relay_cycles, total / 86400

    old_cycles, old_delivered = run(10.0, False)     # what fc1 runs today
    new_cycles, new_delivered = run(30.0, True)      # deployed config

    assert new_cycles < old_cycles, 'fewer, longer pulses'
    assert new_delivered > old_delivered, 'less of each pulse lost to pipe transit'
