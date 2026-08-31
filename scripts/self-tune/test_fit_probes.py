"""Run: PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q scripts/self-tune/test_fit_probes.py"""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location('fit_probes', Path(__file__).with_name('fit-probes.py'))
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)


def test_resample_holds_last_value_on_uniform_grid():
    rows = [(0.0, 90.0), (7.0, 90.5), (25.0, 91.0)]
    grid = fp.resample(rows, t0=0.0, t1=40.0, dt=10.0)
    assert grid == [90.0, 90.5, 90.5, 91.0]


def test_relay_edges_to_held_state():
    # Sample-and-hold reports the value AT each grid instant (t=0,10,20,30,40):
    # the t=10 sample predates the t=12 edge, so it still reads 0. The task
    # brief's own expected array here ([...,1.0,1.0,1.0,...]) does not match
    # its own resample() -- corrected to what plain hold-last-value produces.
    edges = [(0.0, 0.0), (12.0, 1.0), (33.0, 0.0)]
    assert fp.resample(edges, t0=0.0, t1=50.0, dt=10.0, initial=0.0) == [0.0, 0.0, 1.0, 1.0, 0.0]


def test_resample_empty_rows_raises_instead_of_indexerror():
    # A telemetry window with zero rows (e.g. dead sensor, empty date range)
    # used to hit `rows[0]` and raise IndexError -- indistinguishable from a
    # real bug. Now a clear ValueError (MUSHY-138 fix round 2).
    with pytest.raises(ValueError):
        fp.resample([], t0=0.0, t1=40.0, dt=10.0)


def test_resample_empty_rows_with_initial_holds_it():
    assert fp.resample([], t0=0.0, t1=30.0, dt=10.0, initial=0.0) == [0.0, 0.0, 0.0]


def test_weather_series_joins_topics_and_skips_incomplete_hours():
    h = 3600.0
    temp = [(0.0, 10.0), (h, 12.0), (2 * h, 14.0)]
    rh = [(0.0, 90.0), (2 * h, 80.0)]            # hour 1 missing
    precip = [(0.0, 0.0), (h, 0.5), (2 * h, 0.0)]
    amb = fp.weather_series(temp, rh, precip)
    assert amb.start.timestamp() == 0.0 and amb.end.timestamp() == 2 * h
    mid = amb.at(fp.datetime.fromtimestamp(h, tz=fp.timezone.utc))
    assert mid.temp_c == 12.0 and mid.rh_pct == 85.0      # interpolated over the gap
    with pytest.raises(ValueError):
        fp.weather_series([(0.0, 1.0)], [], [])


def test_weather_series_holds_last_hour_but_not_longer():
    h = 3600.0
    rows = [(0.0, 1.0), (h, 2.0)]
    held = fp.weather_series(rows, rows, rows, hold_until=h + 1800.0)
    assert held.end.timestamp() == h + 1800.0
    assert held.at(fp.datetime.fromtimestamp(h + 1000.0, tz=fp.timezone.utc)).temp_c == 2.0
    assert fp.weather_series(rows, rows, rows, hold_until=h + 2 * fp.HOLD_S).end.timestamp() == h
