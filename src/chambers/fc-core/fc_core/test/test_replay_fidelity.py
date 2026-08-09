"""Fidelity gate: the sim must reproduce the observed limit cycle.

This is the load-bearing test of the whole simulation effort. If the baseline
config does NOT oscillate here, every downstream claim about the fixes is
worthless, because we would be fixing a bug the model does not contain.

Ground truth, fc1 2026-08-08, 26 h, fruiting band [0.885, 0.915]:
    cycle period       1.82 / 1.87 / 2.10 h (2.81 h mean incl. long night gaps)
    RH span            87.33 - 92.59
    mean commanded duty 0.142
    duty at ~0          52.6 % of minutes
    duty in (0, 0.083)  22.3 % of minutes -- commanded then discarded

KNOWN FIDELITY LIMITS (measured 2026-08-09, not hidden):
  * Period runs ~40 % long: sim 2.90 h vs 1.82-2.10 h for daytime cycles. An
    RH-proportional leak was trialled to close this and REJECTED -- it behaved
    non-monotonically across floor values (86 -> no bursts, 84 -> 4.14 h),
    which is fragility rather than fidelity.
  * Sim under-represents the discarded band: 9.7 % vs 22.3 % of samples.
  * Sim never fires Mode C bypass; the real chamber hit duty 1.0 for 2.9 %.
So: use this model for RELATIVE comparison between control configurations,
which is what it is for. Do not quote its absolute numbers as predictions.
"""
import pytest

from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.pwm_window import PwmConfig
from fc_core.sim.replay import DEFAULT_BAND, DEFAULT_GAINS, run_closed_loop

HOURS = 14.0


@pytest.fixture(scope='module')
def baseline():
    return run_closed_loop(hours=HOURS, params=ChamberParams(), pwm_cfg=PwmConfig(),
                           band=DEFAULT_BAND, gains=DEFAULT_GAINS, rh0=90.0)


def test_baseline_oscillates(baseline):
    """Without this the model does not contain the bug we are trying to fix."""
    assert baseline.rh_p2p > 3.0, f'expected a real swing, got {baseline.rh_p2p:.2f}'
    assert baseline.burst_count >= 3, f'only {baseline.burst_count} bursts in {HOURS} h'


def test_baseline_period_is_multi_hour(baseline):
    """Bounded loosely on purpose -- see KNOWN FIDELITY LIMITS in the docstring."""
    assert baseline.cycle_period_h is not None
    assert 1.5 <= baseline.cycle_period_h <= 4.0


def test_baseline_mean_duty_matches_measurement(baseline):
    """Measured 0.142 over 26 h. This one the model gets genuinely right."""
    assert baseline.duty_mean_commanded == pytest.approx(0.142, abs=0.05)


def test_baseline_overshoots_above_the_band(baseline):
    """RH must sail past band_high, which is what forces the long dead stretch."""
    assert baseline.rh_max > 91.5


def test_baseline_sags_below_the_midpoint(baseline):
    assert baseline.rh_min < 89.5


def test_baseline_discards_commanded_duty(baseline):
    """The min-pulse floor must be observably throwing away real demand."""
    assert baseline.discarded_s > 0.0


def test_delivered_duty_sits_near_equilibrium(baseline):
    """Averaged over a cycle the chamber can only be holding at equilibrium."""
    assert baseline.duty_mean_delivered == pytest.approx(
        ChamberParams().equilibrium_duty, abs=0.02)


# ---------------------------------------------------------------------------
# Fix evaluation. These assert the RELATIVE improvement the sweep found, which
# is what this model is qualified to say. They are not absolute predictions.
# ---------------------------------------------------------------------------

RECOMMENDED = PwmConfig(window_s=300.0, min_pulse_s=30.0, accumulate=True)
EQUILIBRIUM_BIAS = ChamberParams().equilibrium_duty


@pytest.fixture(scope='module')
def recommended():
    return run_closed_loop(hours=20.0, pwm_cfg=RECOMMENDED, rh0=90.0,
                           duty_bias=EQUILIBRIUM_BIAS)


def test_recommended_config_removes_the_limit_cycle(recommended):
    assert recommended.burst_count == 0, (
        f'expected no bursts, got {recommended.burst_count}')


def test_recommended_config_shrinks_the_swing(recommended, baseline):
    assert recommended.rh_p2p < baseline.rh_p2p * 0.75


def test_recommended_config_stays_nearer_the_setpoint(recommended):
    assert recommended.rh_min > 89.0
    assert recommended.rh_max < 92.2


def test_recommended_config_does_not_blow_up_relay_wear(recommended, baseline):
    """Farmer flagged relay wear as a real cost. Guard it explicitly."""
    assert recommended.relay_cycles_per_hour < baseline.relay_cycles_per_hour * 1.5


def test_recommended_config_discards_nothing(recommended):
    assert recommended.discarded_s == 0.0


def test_slew_limiter_cannot_bind_and_is_therefore_not_shipped():
    """Documents a NEGATIVE result so nobody re-proposes it from intuition.

    A slew limiter was requested twice. The commanded duty already rises at
    most 0.00046/s -- 12x slower than a 180 s limiter's 0.00556/s ceiling --
    so the limiter never engages. The apparent 'slam to 100%' on the charts is
    the PWM relay toggling, not the duty command.
    """
    without = run_closed_loop(hours=14.0, rh0=90.0, climb_seconds=0.0)
    with_slew = run_closed_loop(hours=14.0, rh0=90.0, climb_seconds=180.0)
    assert with_slew.rh_p2p == pytest.approx(without.rh_p2p, abs=1e-9)
    assert with_slew.duty_mean_commanded == pytest.approx(
        without.duty_mean_commanded, abs=1e-9)
    rises = [without.duty_series[i] - without.duty_series[i - 1]
             for i in range(1, len(without.duty_series))]
    assert max(rises) < 1.0 / 180.0
