"""
tests/chamber/test_heartbeat.py -- daily heartbeat scheduler (port of heartbeat.js).

Driven by an injected clock and a list-appending dispatch, so no test sleeps.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from farm_agent.chamber import heartbeat


def _ms(y, mo, d, h, mi=0, tz="America/Montevideo") -> int:
    """Epoch ms for a LOCAL wall-clock time in the given zone."""
    return int(datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz)).timestamp() * 1000)


FULL_SUMMARY = {
    "rh": 91.0, "temp": 21.0, "co2": 800,
    "humidifier": "OFF", "humidifier_cycles": 4, "pi_last_seen_sec": 3,
}
EMPTY_SUMMARY = {
    "rh": None, "temp": None, "co2": None,
    "humidifier": "OFF", "humidifier_cycles": 0, "pi_last_seen_sec": None,
}


def _run_ticks(cfg, times, summaries):
    """Drive tick() over a list of instants; return the dispatched events."""
    fired = []
    state = heartbeat.HeartbeatState()
    for now_ms, summary in zip(times, summaries):
        heartbeat.tick(
            state=state,
            config=cfg,
            now_ms=now_ms,
            get_summary=lambda s=summary: s,
            dispatch=fired.append,
        )
    return fired, state


def test_fires_once_at_heartbeat_hour(chamber_config):
    cfg = chamber_config(ALERT_HEARTBEAT_HOUR="8")
    times = [_ms(2026, 7, 13, 8, 0), _ms(2026, 7, 13, 8, 15), _ms(2026, 7, 13, 9, 0)]
    fired, _ = _run_ticks(cfg, times, [FULL_SUMMARY] * 3)
    assert len(fired) == 1
    assert fired[0]["type"] == "heartbeat_tick"
    assert fired[0]["summary"] == FULL_SUMMARY


def test_does_not_fire_before_heartbeat_hour(chamber_config):
    cfg = chamber_config(ALERT_HEARTBEAT_HOUR="8")
    fired, _ = _run_ticks(cfg, [_ms(2026, 7, 13, 7, 45)], [FULL_SUMMARY])
    assert fired == []


def test_fires_again_the_next_day(chamber_config):
    cfg = chamber_config(ALERT_HEARTBEAT_HOUR="8")
    times = [_ms(2026, 7, 13, 8, 0), _ms(2026, 7, 14, 8, 0)]
    fired, _ = _run_ticks(cfg, times, [FULL_SUMMARY] * 2)
    assert len(fired) == 2


def test_defers_on_empty_summary_then_fires(chamber_config):
    """Pitfall 10: an empty summary must NOT consume the day.

    Post-boot race: a restart at 08:00 with heartbeat_hour=8 reaches the hour
    before the bridge has replayed any telemetry. Marking the day done there
    would either silence the day or send 'RH: ? · Temp: ? · CO2: ?'.
    """
    cfg = chamber_config(ALERT_HEARTBEAT_HOUR="8")
    times = [_ms(2026, 7, 13, 8, 0), _ms(2026, 7, 13, 8, 15)]
    fired, state = _run_ticks(cfg, times, [EMPTY_SUMMARY, FULL_SUMMARY])
    assert len(fired) == 1
    assert fired[0]["summary"] == FULL_SUMMARY
    assert state.last_fired_day == "2026-07-13"


def test_partial_summary_is_enough_to_fire(chamber_config):
    """heartbeat.js:61 -- ANY one of rh/temp/co2 non-None fires."""
    cfg = chamber_config(ALERT_HEARTBEAT_HOUR="8")
    partial = {**EMPTY_SUMMARY, "co2": 800}
    fired, _ = _run_ticks(cfg, [_ms(2026, 7, 13, 8, 0)], [partial])
    assert len(fired) == 1


def test_day_boundary_uses_configured_zone_not_utc(chamber_config):
    """23:30 local on the 13th is 02:30 UTC on the 14th -- the day key must be local.

    With heartbeat_hour=23, a UTC day key would roll over mid-evening and allow a
    second fire the same local night.
    """
    cfg = chamber_config(ALERT_HEARTBEAT_HOUR="23")
    times = [_ms(2026, 7, 13, 23, 15), _ms(2026, 7, 13, 23, 45)]
    fired, state = _run_ticks(cfg, times, [FULL_SUMMARY] * 2)
    assert len(fired) == 1
    assert state.last_fired_day == "2026-07-13"


def test_tick_swallows_get_summary_errors(chamber_config):
    """A raising get_summary must not kill the loop (retention_loop discipline)."""
    cfg = chamber_config(ALERT_HEARTBEAT_HOUR="8")
    fired = []
    state = heartbeat.HeartbeatState()

    def boom():
        raise RuntimeError("bridge state exploded")

    heartbeat.tick(
        state=state, config=cfg, now_ms=_ms(2026, 7, 13, 8, 0),
        get_summary=boom, dispatch=fired.append,
    )
    assert fired == []
    assert state.last_fired_day is None    # not consumed -- next tick retries


async def test_heartbeat_loop_is_cancellable(chamber_config):
    """The loop must exit cleanly on cancel (boot.py shutdown symmetry)."""
    import asyncio

    cfg = chamber_config(ALERT_HEARTBEAT_HOUR="8")
    task = asyncio.create_task(
        heartbeat.heartbeat_loop(
            config=cfg,
            get_summary=lambda: EMPTY_SUMMARY,
            dispatch=lambda e: None,
            interval_s=0.01,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
