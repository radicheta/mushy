"""Tests for the offline ambient weather series (MUSHY-64).

No network: the loader is stdlib-only by design, and the test container runs
with --network none.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from fc_core.sim.ambient import AmbientSample, AmbientSeries, DEFAULT_FIXTURE

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


# ---------------------------------------------------------------------------
# The committed fixture itself. These assert the artifact is fit for fitting,
# not that the loader works -- that is covered above.
# ---------------------------------------------------------------------------

TELEMETRY_START = datetime(2026, 4, 11, tzinfo=timezone.utc)


@pytest.fixture(scope='module')
def real():
    return AmbientSeries.from_csv(DEFAULT_FIXTURE)


def test_fixture_covers_the_telemetry_window(real):
    assert real.start <= TELEMETRY_START
    assert real.end >= datetime(2026, 8, 3, tzinfo=timezone.utc)


def test_fixture_is_hourly_with_no_gaps(real):
    """A gap would silently become a long linear interpolation across it."""
    gaps = [(real._times[i] - real._times[i - 1]).total_seconds()
            for i in range(1, len(real._times))]
    assert set(gaps) == {3600.0}, f'non-hourly spacing present: {sorted(set(gaps))[:5]}'


def test_fixture_values_are_physically_plausible(real):
    for ts in (real.start, TELEMETRY_START, real.end):
        s = real.at(ts)
        assert -15.0 < s.temp_c < 50.0
        assert 0.0 <= s.rh_pct <= 100.0
        assert s.precip_mm >= 0.0


def test_fixture_shows_austral_winter_cooling(real):
    """April is autumn, June is midwinter. If this fails the window or the
    hemisphere is wrong."""
    april = real.at(datetime(2026, 4, 15, 12, tzinfo=timezone.utc)).temp_c
    june = real.at(datetime(2026, 6, 22, 12, tzinfo=timezone.utc)).temp_c
    assert june < april


def test_fixture_matches_its_checksum_sidecar():
    """Open-Meteo serves preliminary ERA5T values for recent days and later
    replaces them with final ERA5 -- different values, same timestamps. A
    re-run of the fetch script months from now could silently alter historic
    rows while every other test here (coverage, spacing, bounds, seasonal
    ordering) keeps passing. The sha256 in the meta sidecar turns that silent
    drift into a loud failure."""
    meta_path = DEFAULT_FIXTURE.with_name(DEFAULT_FIXTURE.stem + '.meta.json')
    meta = json.loads(meta_path.read_text())
    actual = hashlib.sha256(DEFAULT_FIXTURE.read_bytes()).hexdigest()
    assert actual == meta['sha256'], (
        'fixture bytes do not match the recorded checksum -- the CSV changed '
        'without regenerating the meta sidecar')
