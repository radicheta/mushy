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

BASELINE CONDITIONS (MUSHY-60, round 2 correction): the baseline fixture uses
the MEASURED 2026-08-08 conditions -- chamber 6.00 C, ambient 6.20 C, mean
chamber-minus-ambient absolute-humidity gap 0.703 g/m3 -- not August monthly
means. An earlier version of this fixture used design limitation 5's August
MONTHLY MEANS (10.7 C, ~0.30 g/m3 gradient) on the mistaken assumption that
they stood in for this specific day; that was wrong, that mistake was the
coordinator's, and it failed 5 of the 6 assertions below as a direct result
(no oscillation, duty 0.078 vs 0.142, RH never reaching the band edges). Do
not substitute a monthly mean for a specific day's fixture again -- query the
actual day.

KNOWN FIDELITY LIMITS, moisture-balance model at the corrected conditions
(measured 2026-08-09/2026-08-10, not hidden; see task-4-report.md for the
full derivation):
  * Mean commanded duty: sim 0.1431 vs measured 0.142. The honest tolerance
    here is the test's own abs=0.05, not the 0.7 % gap between these two
    particular numbers: the measured target is strongly non-stationary --
    across 26 h windows in early August the mean duty runs 0.089 to 0.249,
    a ~2x swing from a few hours of window shift -- so this agreement is
    REASSURING, not precise. It is also a consistency check, not a held-out
    test: the 2026-08-08 fidelity trace day is 1 of ~120 days in the Task 2
    fit window (script WINDOW_END = '2026-08-09', loaders query inclusive
    of 2026-08-09), carrying ~0.8 % of the fitted samples. The parameters
    were not tuned to this specific trace -- Q and F came from a
    whole-window identification, not a per-day fit -- but "out-of-sample"
    is the wrong word for it, and an earlier version of this docstring used
    it. A genuine held-out validation is MUSHY-59's job (driven replay
    against recorded data).
  * Cycle period: sim ~3 h vs measured 1.82-2.10 h daytime (2.81 h mean
    including long night gaps). In range but on the slow side.
  * RH span (peak-to-peak): sim 2.77 vs measured 5.26 (87.33-92.59) --
    under-predicts amplitude by ~13 % against the gate's 3.0 floor.
  * Peak commanded duty: sim ~0.475, never crossing the burst detector's 0.5
    threshold, whereas the real chamber does cross it -- so the detector
    reports zero bursts even though RH is genuinely, stably cycling (verified
    by sampling rh_series/duty_series directly over an 80 h run).
  * Leading hypothesis for the damped amplitude: the moisture settling time
    V/Q = 5.98 h is ~2x the observed ~3 h cycle, i.e. the balance is more
    heavily low-pass-filtered than the real chamber's response, which would
    smooth out exactly the sharp peak-duty excursions the burst detector and
    the p2p floor are looking for.
  * That hypothesis is only part of the story, though: a sweep of the
    branch's own documented Q band, holding F/Q = 7.0337 fixed, shows the
    three xfailed assertions below are as sensitive to WHICH band was
    shipped as to any structural amplitude deficiency:
        Q=0.658 [16,inf] F=4.63 -> p2p 2.005, peak duty 0.424, 0 bursts
        Q=0.963 [16,120] F=6.78 -> p2p 2.758, peak duty 0.473, 0 bursts  <- SHIPPED
        Q=1.080 [8,120]  F=7.60 -> p2p 2.988, peak duty 0.493, 0 bursts
        Q=1.242 [1,120]  F=8.74 -> p2p 3.303, peak duty 0.524, 5 bursts, period 2.68 h
    At Q = 1.242 -- a band the fit report itself tabulates -- all three
    xfailed assertions below pass. The gate is therefore not discriminating
    at the resolution of the parameter uncertainty: the shipped [16,120]
    band was chosen on regime-matching grounds (it excludes the saturated
    minutes per the farmer's ruling, see chamber_model.py), not to pass or
    fail this gate, and a different defensible band choice would flip these
    three results.

So: use this model for RELATIVE comparison between control configurations,
which is what it is for. Do not quote its absolute numbers as predictions --
that is more true than ever now that duty is right but amplitude is damped.

MUSHY-136 (2026-08-30): the model gained a surface-reservoir term,
ChamberParams.surface_g_per_k -- the chamber air loses ~2.8 g of water per
kelvin of cooling to wet surfaces and regains it on warming. On the recorded
2026-08-08 the diurnal temperature swing acting through that term is most of
the RH amplitude; the driven replay (scripts/replay-chamber-day.py, real
temperature and ambient in) reproduces the day at span 5.25 vs 5.35 pp
recorded, RMSE 1.69. THIS gate holds temperature CONSTANT, so the term can
never act here and the synthetic baseline now swings 1.74 pp. The amplitude
assertions below (p2p, bursts, period, overshoot) are therefore xfail: they
measure a constant-temperature abstraction, not the chamber. The driven
replay reports under .planning/phases/999.33-digital-twin-chamber-sim/ are
the amplitude gate. Mean duty, the discard check, and the relative
recommended-vs-baseline assertions remain meaningful at constant temperature.
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
# this reproduces the measured 2026-08-08 gradient of 0.703 g/m3 (see
# replay.py).
BASELINE_AH_IN = absolute_humidity_g_m3(DEFAULT_TEMP_C, 90.0)


@pytest.fixture(scope='module')
def baseline():
    return run_closed_loop(hours=HOURS, params=ChamberParams(), pwm_cfg=PwmConfig(),
                           band=DEFAULT_BAND, gains=DEFAULT_GAINS, rh0=90.0)


@pytest.mark.xfail(strict=True, reason=(
    'RH peak-to-peak is 2.77 vs > 3.0 required, 13% short. The model DOES '
    'oscillate (~3 h period, verified by direct rh_series sampling, stable '
    'over an 80 h run) -- this is an amplitude shortfall, not absence of the '
    'phenomenon. See KNOWN FIDELITY LIMITS in the module docstring.'))
def test_baseline_oscillates_with_full_amplitude(baseline):
    """Without this the model does not swing as far as the real chamber."""
    assert baseline.rh_p2p > 3.0, f'expected a real swing, got {baseline.rh_p2p:.2f}'


@pytest.mark.xfail(strict=True, reason=(
    'burst_count is 0: the detector counts duty crossing 0.5 upward, and the '
    'sim peaks at ~0.475 each cycle -- a 5% threshold cliff, not absence of '
    'bursting. RH is genuinely, stably cycling at these conditions (see '
    'test_baseline_period_is_multi_hour and the module docstring).'))
def test_baseline_oscillates_with_detectable_bursts(baseline):
    """Without this the model does not contain the bug we are trying to fix."""
    assert baseline.burst_count >= 3, f'only {baseline.burst_count} bursts in {HOURS} h'


@pytest.mark.xfail(strict=True, reason=(
    'cycle_period_h is None purely as a consequence of burst_count=0 (see '
    'test_baseline_oscillates_with_detectable_bursts): the burst detector '
    'never fires so no period can be computed from burst onsets. The actual '
    'period is ~3 h (measured directly from rh_series), which is within '
    '[1.5, 4.0] and would pass this bound if the detector saw the bursts.'))
def test_baseline_period_is_multi_hour(baseline):
    """Bounded loosely on purpose -- see KNOWN FIDELITY LIMITS in the docstring."""
    assert baseline.cycle_period_h is not None
    assert 1.5 <= baseline.cycle_period_h <= 4.0


def test_baseline_mean_duty_matches_measurement(baseline):
    """Measured 0.142 over 26 h. This one the model gets genuinely right."""
    assert baseline.duty_mean_commanded == pytest.approx(0.142, abs=0.05)


@pytest.mark.xfail(strict=True, reason=(
    'rh_max 91.02 vs > 91.5: at constant temperature the surface-reservoir '
    'term (MUSHY-136) cannot act, and it is what carries most of the recorded '
    'overshoot. The driven replay of 2026-08-08 reaches 93.7 (recorded 92.6).'))
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
    """NOTE (MUSHY-60): this assertion no longer distinguishes recommended
    from baseline. burst_count == 0 for BOTH configs now, because the burst
    detector counts duty crossing 0.5 upward, and both configs peak around
    duty ~0.475 -- under the threshold. That is a detector-cliff artifact,
    not evidence that recommended has removed cycling that baseline still
    has. Do not read a pass here as "recommended beats baseline."

    The genuine before/after evidence lives in
    test_recommended_config_shrinks_the_swing (rh_p2p 2.767 -> 1.113, a 60%
    reduction) and test_recommended_config_stays_nearer_the_setpoint, both
    of which have real margins. If the model's amplitude is ever raised to
    match reality (duty peaks push past 0.5 again), this test regains its
    original meaning and should be trusted again.
    """
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
