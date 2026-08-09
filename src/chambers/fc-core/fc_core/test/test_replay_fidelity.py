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
