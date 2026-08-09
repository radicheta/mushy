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

KNOWN FIDELITY LIMITS, RH-points model (measured 2026-08-09, not hidden):
  * Period runs ~40 % long: sim 2.90 h vs 1.82-2.10 h for daytime cycles. An
    RH-proportional leak was trialled to close this and REJECTED -- it behaved
    non-monotonically across floor values (86 -> no bursts, 84 -> 4.14 h),
    which is fragility rather than fidelity.
  * Sim under-represents the discarded band: 9.7 % vs 22.3 % of samples.
  * Sim never fires Mode C bypass; the real chamber hit duty 1.0 for 2.9 %.

MUSHY-60 UPDATE (2026-08-09): the moisture-balance model FAILS this gate at
the baseline fixture's physically-motivated conditions (temp_c=10.7,
ambient_ah_g_m3 giving the ~0.30 g/m3 August gradient -- see replay.py). Five
of the six assertions below fail: no oscillation develops (rh_p2p=1.09,
burst_count=0), mean commanded duty is 0.078 (target 0.142 +/- 0.05), and RH
never reaches the band edges (max 90.60, min 89.50). A parameter sweep over
ambient_ah_g_m3 (0.3-8.0 g/m3 gradient) at temp_c=10.7 found NO value that
satisfies all six assertions simultaneously: the p2p amplitude tops out
around 2.5-2.6 near gradient~1.2-1.3 g/m3 (duty already 0.32-0.37, well above
the 0.142+/-0.05 band by then) and rh_max never exceeds ~91.44 for any
gradient tried, so `rh_max > 91.5` cannot be satisfied at this temperature at
all. All six assertions pass only at an implausibly cold chamber temperature
(~5 C, versus the measured ~10.7 C August mean) -- i.e. only by picking
physically implausible conditions. Per the task-4 brief this is reported as a
finding, not tuned away: the moisture-balance model, at the conditions it
claims to model, does not reproduce the observed 2026-08-08 limit cycle.
See task-4-report.md for the full sweep.

So: use this model for RELATIVE comparison between control configurations,
which is what it is for. Do not quote its absolute numbers as predictions,
and do not trust its baseline to reproduce fc1's actual limit cycle.
"""
import pytest

from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.psychrometrics import absolute_humidity_g_m3
from fc_core.sim.pwm_window import PwmConfig
from fc_core.sim.replay import (DEFAULT_AMBIENT_AH_G_M3, DEFAULT_BAND,
                                DEFAULT_GAINS, DEFAULT_TEMP_C, run_closed_loop)

HOURS = 14.0

# ah_in for the equilibrium-duty checks below: the absolute humidity of the
# chamber holding exactly at the control target (90 % RH), at the same
# DEFAULT_TEMP_C the baseline run uses. Paired with DEFAULT_AMBIENT_AH_G_M3
# this reproduces the ~0.30 g/m3 August gradient (see replay.py).
BASELINE_AH_IN = absolute_humidity_g_m3(DEFAULT_TEMP_C, 90.0)


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
        ChamberParams().equilibrium_duty(BASELINE_AH_IN, DEFAULT_AMBIENT_AH_G_M3),
        abs=0.02)


# ---------------------------------------------------------------------------
# Fix evaluation. These assert the RELATIVE improvement the sweep found, which
# is what this model is qualified to say. They are not absolute predictions.
# ---------------------------------------------------------------------------

RECOMMENDED = PwmConfig(window_s=300.0, min_pulse_s=30.0, accumulate=True)
EQUILIBRIUM_BIAS = ChamberParams().equilibrium_duty(BASELINE_AH_IN, DEFAULT_AMBIENT_AH_G_M3)


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


# ---------------------------------------------------------------------------
# MUSHY-57: the bias must not become a duty floor.
#
# The high-ambient day is modelled with a genuine zero gradient: ambient
# absolute humidity set equal to the chamber's own starting absolute humidity,
# so the chamber holds its own RH and the correct standing duty is zero, not
# equilibrium_duty. A flat bias cannot express that: the humidifier only adds
# moisture, so the chamber would climb without limit.
# ---------------------------------------------------------------------------

HIGH_AMBIENT_RH0 = 92.0
HIGH_AMBIENT_AH_G_M3 = absolute_humidity_g_m3(DEFAULT_TEMP_C, HIGH_AMBIENT_RH0)


@pytest.fixture(scope='module')
def high_ambient():
    return run_closed_loop(hours=6.0, params=ChamberParams(), pwm_cfg=RECOMMENDED,
                           rh0=HIGH_AMBIENT_RH0, duty_bias=EQUILIBRIUM_BIAS,
                           ambient_ah_g_m3=HIGH_AMBIENT_AH_G_M3)


def test_high_ambient_day_reaches_zero_duty(high_ambient):
    """Above the band with nothing draining it, the bias must let go entirely."""
    last_hour = high_ambient.duty_series[-3600:]
    assert max(last_hour) == pytest.approx(0.0, abs=1e-12), (
        f'humidifier never turned off; min commandable duty was '
        f'{min(last_hour):.3f}')


def test_high_ambient_day_does_not_run_rh_away(high_ambient):
    """With a floored duty the chamber climbs ~2.25 pts/h forever."""
    assert high_ambient.rh_max < 92.5


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
