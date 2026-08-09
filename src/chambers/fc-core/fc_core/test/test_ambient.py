"""Tests for the offline ambient weather series (MUSHY-64).

No network: the loader is stdlib-only by design, and the test container runs
with --network none.
"""
from datetime import datetime, timedelta, timezone

import pytest

from fc_core.sim.ambient import AmbientSample, AmbientSeries

CSV = """time_utc,temp_c,rh_pct,precip_mm
2026-04-11T00:00:00+00:00,10.0,80.0,0.0
2026-04-11T01:00:00+00:00,12.0,70.0,0.5
2026-04-11T02:00:00+00:00,14.0,60.0,0.0
"""


@pytest.fixture
def series(tmp_path):
    p = tmp_path / 'ambient.csv'
    p.write_text(CSV)
    return AmbientSeries.from_csv(p)


def _t(hour, minute=0):
    return datetime(2026, 4, 11, hour, minute, tzinfo=timezone.utc)


def test_exact_sample_returns_that_row(series):
    assert series.at(_t(1)) == AmbientSample(temp_c=12.0, rh_pct=70.0, precip_mm=0.5)


def test_temperature_interpolates_linearly(series):
    assert series.at(_t(0, 30)).temp_c == pytest.approx(11.0)


def test_humidity_interpolates_linearly(series):
    assert series.at(_t(1, 30)).rh_pct == pytest.approx(65.0)


def test_precipitation_holds_the_containing_hour_not_interpolated(series):
    """Precip is an hourly accumulation. Interpolating it invents rain that
    did not fall in that minute."""
    assert series.at(_t(1, 30)).precip_mm == 0.5
    assert series.at(_t(0, 59)).precip_mm == 0.0


def test_start_and_end_report_coverage(series):
    assert series.start == _t(0)
    assert series.end == _t(2)


def test_before_coverage_raises(series):
    with pytest.raises(ValueError, match='outside'):
        series.at(_t(0) - timedelta(seconds=1))


def test_after_coverage_raises(series):
    """Silent extrapolation would let the model invent ambient it never had."""
    with pytest.raises(ValueError, match='outside'):
        series.at(_t(2) + timedelta(seconds=1))


def test_naive_timestamps_are_treated_as_utc(tmp_path):
    p = tmp_path / 'naive.csv'
    p.write_text(CSV.replace('+00:00', ''))
    s = AmbientSeries.from_csv(p)
    assert s.start == _t(0)


def test_empty_file_raises(tmp_path):
    p = tmp_path / 'empty.csv'
    p.write_text('time_utc,temp_c,rh_pct,precip_mm\n')
    with pytest.raises(ValueError, match='no rows'):
        AmbientSeries.from_csv(p)
