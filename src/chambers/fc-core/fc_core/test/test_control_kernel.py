"""Tests for the extracted band/feather error projection.

Pure Python — no rclpy, so these run in a vanilla venv on any host.
Expected values are hand-derived from the fc1/prod feather arithmetic with
the live fruiting band [0.885, 0.915]: midpoint 0.900, w = 1.5 pct.
"""
import pytest

from fc_core.control_kernel import BandSpec, duty_bias_factor, project_error_pct

FRUITING = BandSpec(band_low=0.885, band_high=0.915, defend_side='both')


def test_zero_error_at_midpoint():
    assert project_error_pct(0.900, FRUITING) == pytest.approx(0.0)


def test_quadratic_feather_below_midpoint():
    # s = 1.0 pct below midpoint, w = 1.5 -> -s^2/(2w) = -1/3
    assert project_error_pct(0.890, FRUITING) == pytest.approx(-1.0 / 3.0, abs=1e-9)


def test_feather_value_at_band_low():
    # s = w = 1.5 -> -w/2 = -0.75
    assert project_error_pct(0.885, FRUITING) == pytest.approx(-0.75, abs=1e-9)


def test_linear_below_band_low():
    # s = 2.0 > w -> -(s - w/2) = -1.25
    assert project_error_pct(0.880, FRUITING) == pytest.approx(-1.25, abs=1e-9)


def test_c1_value_continuity_at_the_join():
    """Both branches must agree exactly at s == w, or there is a step to kick on.

    At s == w the quadratic gives -w^2/(2w) = -w/2 and the linear gives
    -(w - w/2) = -w/2. Compare the analytic limits, not two offset samples --
    samples either side of the join legitimately differ by slope * spacing.
    """
    w = FRUITING.half_width_pct
    at_join = project_error_pct(FRUITING.band_low, FRUITING)   # s == w, quadratic branch
    assert at_join == pytest.approx(-w / 2.0, abs=1e-12)
    # Linear branch evaluated at the same s, reached from just below the floor.
    eps = 1e-9
    from_below = project_error_pct(FRUITING.band_low - eps, FRUITING)
    assert from_below == pytest.approx(-w / 2.0, abs=1e-6)


def test_c1_slope_continuity_at_the_join():
    """Slopes must match too. Both branches have d(err)/ds == -1 at s == w."""
    # Step must be small enough that the quadratic branch's own curvature
    # (slope = s/w, so it drifts across any finite interval) stays below the
    # tolerance. h = 1e-6 fraction -> 1e-4 pct -> ~7e-5 relative slope drift.
    h = 1e-6                       # RH fraction; same spacing both sides
    lo = FRUITING.band_low
    slope_quadratic = (project_error_pct(lo + 2 * h, FRUITING)
                       - project_error_pct(lo + h, FRUITING)) / (h * 100.0)
    slope_linear = (project_error_pct(lo - h, FRUITING)
                    - project_error_pct(lo - 2 * h, FRUITING)) / (h * 100.0)
    assert slope_quadratic == pytest.approx(slope_linear, rel=1e-3)
    assert slope_linear == pytest.approx(1.0, rel=1e-3)


def test_no_kink_second_difference_is_small():
    """A kink at the floor would show up as a large second difference."""
    h = 1e-5
    lo = FRUITING.band_low
    f = lambda x: project_error_pct(x, FRUITING)
    second = (f(lo + h) - 2 * f(lo) + f(lo - h)) / ((h * 100.0) ** 2)
    # Curvature of the quadratic branch is 1/w = 0.667; a genuine kink would be
    # orders of magnitude larger than that.
    assert abs(second) < 10.0


def test_zero_in_upper_half_of_band():
    """Feather is one-sided: no forcing between midpoint and band_high."""
    assert project_error_pct(0.910, FRUITING) == pytest.approx(0.0)


def test_positive_error_above_band_high_when_defending():
    assert project_error_pct(0.925, FRUITING) == pytest.approx(1.0, abs=1e-9)


def test_none_above_band_high_when_defend_low_only():
    band = BandSpec(band_low=0.885, band_high=0.915, defend_side='low')
    assert project_error_pct(0.925, band) is None


def test_degenerates_to_linear_when_band_has_zero_width():
    """w <= 0 must not divide by zero; falls through to the linear branch."""
    band = BandSpec(band_low=0.900, band_high=0.900, defend_side='both')
    assert project_error_pct(0.890, band) == pytest.approx(-1.0, abs=1e-9)


@pytest.mark.parametrize('rh', [0.870, 0.880, 0.885, 0.890, 0.895, 0.900])
def test_error_is_monotonic_nonincreasing_as_rh_falls(rh):
    """Drier air must never produce a weaker humidify command."""
    assert project_error_pct(rh, FRUITING) <= project_error_pct(rh + 0.001, FRUITING) + 1e-12


# ---------------------------------------------------------------------------
# MUSHY-57: the feedforward duty bias must never impose a floor on the output.
#
# The bias is added after the PID's own (0,1) clamp, so a flat bias makes the
# bias itself the minimum commandable duty. On a high-ambient day, when the
# chamber should idle, the humidifier could then never turn off -- and it can
# only ADD moisture. The factor fades the bias out across the upper half of
# the band so a genuine zero-demand condition still reaches duty 0.
# ---------------------------------------------------------------------------

def test_bias_factor_is_full_at_the_midpoint():
    """The midpoint is where the feather zeroes the error and the standing
    duty is needed most. Bias must be undiminished there."""
    assert duty_bias_factor(0.900, FRUITING) == pytest.approx(1.0)


@pytest.mark.parametrize('rh', [0.870, 0.885, 0.895])
def test_bias_factor_is_full_below_the_midpoint(rh):
    assert duty_bias_factor(rh, FRUITING) == pytest.approx(1.0)


def test_bias_factor_is_zero_at_band_high():
    """The whole point: at the top of the band the bias must be gone, so the
    controller can command a true zero."""
    assert duty_bias_factor(0.915, FRUITING) == pytest.approx(0.0)


@pytest.mark.parametrize('rh', [0.916, 0.930, 1.0])
def test_bias_factor_stays_zero_above_band_high(rh):
    assert duty_bias_factor(rh, FRUITING) == pytest.approx(0.0)


def test_bias_factor_ramps_linearly_across_the_upper_band():
    # Midpoint 0.900, band_high 0.915 -> 0.9075 is exactly halfway.
    assert duty_bias_factor(0.9075, FRUITING) == pytest.approx(0.5, abs=1e-9)
    assert duty_bias_factor(0.9037, FRUITING) == pytest.approx(
        (0.915 - 0.9037) / 0.015, abs=1e-9)


def test_bias_factor_is_continuous_at_the_midpoint():
    """A step here would inject a `bias`-sized jump into commanded duty every
    time RH crossed the midpoint -- the discard-zone chatter we are avoiding."""
    eps = 1e-9
    below = duty_bias_factor(0.900 - eps, FRUITING)
    above = duty_bias_factor(0.900 + eps, FRUITING)
    assert below == pytest.approx(above, abs=1e-6)


@pytest.mark.parametrize('rh', [0.880, 0.890, 0.900, 0.905, 0.910, 0.915, 0.920])
def test_bias_factor_is_monotonic_nonincreasing_as_rh_rises(rh):
    """Wetter air must never earn MORE standing duty."""
    assert duty_bias_factor(rh + 0.001, FRUITING) <= duty_bias_factor(rh, FRUITING) + 1e-12


def test_bias_factor_handles_zero_width_band_without_dividing_by_zero():
    band = BandSpec(band_low=0.900, band_high=0.900, defend_side='both')
    assert duty_bias_factor(0.890, band) == pytest.approx(1.0)
    assert duty_bias_factor(0.900, band) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Refactor parity gate.
#
# fc_controller's error-projection block was replaced by a call into
# control_kernel. elder-plops has no ROS, and running the rclpy suite on fc1
# would spawn nodes on domain 69 -- the LIVE chamber's domain -- where a test
# publisher could drive the real humidifier. So parity is proven here instead,
# against a verbatim copy of the pre-refactor inline arithmetic.
# ---------------------------------------------------------------------------

def _legacy_inline_projection(rh, band):
    """Verbatim copy of fc_controller.py lines 1710-1737 before the extraction.

    Kept deliberately un-refactored -- it is a fixture, not production code.
    """
    midpoint = (band.band_low + band.band_high) / 2.0
    w = (band.band_high - band.band_low) / 2.0 * 100.0
    if rh < midpoint:
        s = (midpoint - rh) * 100.0
        if w > 0 and s <= w:
            error_pct = -(s * s) / (2.0 * w)
        else:
            error_pct = -(s - w / 2.0)
    elif rh > band.band_high:
        if band.defend_side in ('high', 'both'):
            error_pct = (rh - band.band_high) * 100.0
        else:
            return None          # the freeze/return branch
    else:
        error_pct = 0.0
    return error_pct


_BANDS = [
    BandSpec(0.885, 0.915, 'both'),      # live fruiting
    BandSpec(0.945, 0.975, 'both'),      # pre-06-27 fruiting
    BandSpec(0.900, 0.950, 'low'),       # pinning-ish, defend low only
    BandSpec(0.900, 0.950, 'high'),
    BandSpec(0.900, 0.900, 'both'),      # degenerate zero-width
    BandSpec(0.0, 1.0, 'both'),          # force-condensation
]


@pytest.mark.parametrize('band', _BANDS)
def test_kernel_matches_legacy_inline_projection(band):
    """Bit-for-bit parity across the full RH domain at 0.1 pct resolution."""
    for i in range(700, 1001):
        rh = i / 1000.0
        new = project_error_pct(rh, band)
        old = _legacy_inline_projection(rh, band)
        if old is None:
            assert new is None, f'rh={rh} band={band}: freeze branch diverged'
        else:
            assert new == old, f'rh={rh} band={band}: {new!r} != {old!r}'
