import dataclasses
from datetime import time

import pytest

from fc2_core.rule import (
    Decision, RuleParams, WeatherReading, decide, in_night, ramp_rate,
)

P = RuleParams()


def r(temp=20.0, precip=0.0, fetched=1000.0):
    return WeatherReading(temp, 60.0, 10.0, precip, 0.1, '2026-10-30T15:30', fetched)


def test_ramp_ends_and_middle():
    assert ramp_rate(10.0, P) == 1.0
    assert ramp_rate(15.0, P) == 1.0
    assert ramp_rate(28.0, P) == 6.0
    assert ramp_rate(40.0, P) == 6.0
    assert ramp_rate(21.5, P) == pytest.approx(3.5)


def test_raining_wins_over_heat():
    assert decide(r(temp=35, precip=0.1), 1000.0, None, P) == Decision('raining', 0.0)


def test_rain_field_is_not_used_only_precipitation():
    assert decide(r(precip=0.0), 1000.0, None, P).mode == 'weather'


def test_no_reading_is_fallback():
    assert decide(None, 0.0, None, P) == Decision('fallback', 1.0)


def test_stale_is_fallback_fresh_is_not():
    assert decide(r(fetched=0.0), 2700.0, None, P).mode == 'weather'
    assert decide(r(fetched=0.0), 2700.1, None, P).mode == 'fallback'


def test_staleness_ignores_slot_wall_time():
    old_slot = WeatherReading(20, 60, 10, 0, 0.1, '1970-01-01T00:00', 1000.0)
    assert decide(old_slot, 1001.0, None, P).mode == 'weather'


def test_night_only_when_enabled_and_clock_known():
    n = dataclasses.replace(P, night_enabled=True)
    assert decide(r(), 1000.0, time(23, 0), n) == Decision('night', 0.0)
    assert decide(r(), 1000.0, None, n).mode == 'weather'
    assert decide(r(), 1000.0, time(23, 0), P).mode == 'weather'
    assert decide(None, 0.0, time(23, 0), n).mode == 'night'


def test_in_night_wraps_midnight():
    assert in_night(time(20, 0), '20:00', '06:00')
    assert in_night(time(3, 0), '20:00', '06:00')
    assert not in_night(time(6, 0), '20:00', '06:00')
    assert not in_night(time(12, 0), '20:00', '06:00')
    assert in_night(time(13, 0), '12:00', '14:00')
