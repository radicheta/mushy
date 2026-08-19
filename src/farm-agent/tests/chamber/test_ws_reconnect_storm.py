"""MUSHY-96: a busy bridge must not turn into a reconnect storm.

Observed live 2026-08-19. The bridge went from 1-2 client connects an hour to
8-9 per ten minutes, telemetry ingestion stalled, /health went from 90ms to
timing out, and the alerter processed not one telemetry frame in an hour -- so
the daily heartbeat deferred all day with `bridge summary empty` at INFO level,
where nobody saw it.

Three faults compounded, and the loop is self-amplifying like MUSHY-89's:

  1. `connect()` took the websockets default ping_timeout (20s). A bridge busy
     replaying a backlog cannot answer a ping in time, so the CLIENT kills a
     perfectly good socket with 1011 keepalive ping timeout.
  2. The backoff reset on a successful OPEN (js:49 parity), not on a healthy
     connection. A socket that opens and dies one second later therefore reset
     the schedule to 1s, so the retry rate never decayed.
  3. Every reconnect makes the bridge replay its buffer again from scratch, so
     each cycle leaves the bridge busier and the next ping likelier to time out.
     Replays grew 138 -> 375 -> 1222 rows while this ran.

Fault 2 is the amplifier and the one fixed here: back off when a connection is
not proving itself, regardless of why it died.

ASCII-only. No em-dashes.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from farm_agent.chamber import ws_client



class _FakeSocket:
    """Advances the clock as it CLOSES, so the connection has a lifetime.

    Advancing at connect time instead would make every connection look 0ms
    long, which is what the code under test is measuring.
    """

    def __init__(self, frames, clock=None, held_ms=0):
        self.frames = list(frames)
        self._clock = clock
        self._held_ms = held_ms

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.frames:
            if self._clock is not None:
                self._clock.now += self._held_ms
            raise StopAsyncIteration
        return self.frames.pop(0)


class _Clock:
    """Milliseconds. Advances only when a test says so."""

    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


class _FakeConnect:
    """Scripted connect. Each outcome may advance the clock to simulate a
    connection that stayed open for a while before dying."""

    def __init__(self, outcomes, clock=None, held_ms=0):
        self.outcomes = list(outcomes)
        self.attempts = 0
        self.kwargs: list[dict] = []
        self._clock = clock
        self._held_ms = held_ms

    async def __call__(self, url, **kwargs):
        self.attempts += 1
        self.kwargs.append(kwargs)
        outcome = self.outcomes.pop(0) if self.outcomes else OSError("exhausted")
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeSocket(outcome, clock=self._clock, held_ms=self._held_ms)


def _make(chamber_config, connect, clock=None, **over):
    slept = []

    async def fake_sleep(sec):
        slept.append(sec)
        if len(slept) > 10:
            raise asyncio.CancelledError

    kwargs = dict(
        config=chamber_config(),
        http=httpx.AsyncClient(),
        on_message=lambda m: None,
        on_liveness=lambda e: None,
        connect=connect,
        sleep=fake_sleep,
    )
    if clock is not None:
        kwargs["clock"] = clock
    kwargs.update(over)
    return ws_client.WsClient(**kwargs), slept


@pytest.mark.asyncio
class TestBackoffSurvivesAFlappingBridge:
    async def test_a_connection_that_dies_at_once_does_not_reset_the_backoff(
        self, chamber_config
    ):
        """THE STORM. Opening is not success; staying open is.

        Previously each of these reset the schedule to 1s, so the client
        reconnected every second forever and drove the bridge further under.
        """
        clock = _Clock()
        connect = _FakeConnect([[], [], [], []], clock=clock, held_ms=0)
        client, slept = _make(chamber_config, connect, clock=clock)
        with pytest.raises(asyncio.CancelledError):
            await client.run()
        assert slept[:4] == [1.0, 2.0, 4.0, 8.0], (
            f"a connect-then-die loop must decay, got {slept[:4]}"
        )

    async def test_a_connection_that_held_resets_the_backoff(self, chamber_config):
        """A genuine blip after a healthy hour should reconnect fast, not slowly."""
        clock = _Clock()
        connect = _FakeConnect(
            [OSError("refused"), OSError("refused"), [], OSError("refused")],
            clock=clock,
            held_ms=ws_client.HEALTHY_CONNECTION_MS + 1,
        )
        client, slept = _make(chamber_config, connect, clock=clock)
        with pytest.raises(asyncio.CancelledError):
            await client.run()
        assert slept[0] == 1.0
        assert slept[1] == 2.0
        assert slept[2] == 1.0, "a connection that proved itself resets the schedule"

    async def test_the_storm_decays_to_the_cap_instead_of_hammering(self, chamber_config):
        clock = _Clock()
        connect = _FakeConnect([[]] * 9, clock=clock, held_ms=0)
        client, slept = _make(chamber_config, connect, clock=clock)
        with pytest.raises(asyncio.CancelledError):
            await client.run()
        assert slept[-1] == ws_client.MAX_BACKOFF_MS / 1000
        assert sum(slept) > 30, "nine failed cycles must not all happen inside a minute"


@pytest.mark.asyncio
class TestKeepaliveToleratesABusyBridge:
    async def test_connect_is_given_a_ping_timeout_that_survives_a_replay(
        self, chamber_config
    ):
        """The default 20s killed sockets while the bridge replayed a backlog."""
        connect = _FakeConnect([[]])
        client, _ = _make(chamber_config, connect)
        with pytest.raises(asyncio.CancelledError):
            await client.run()
        kw = connect.kwargs[0]
        assert kw.get("ping_timeout") is not None
        assert kw["ping_timeout"] >= 60, (
            "a bridge replaying its buffer needs longer than the 20s default"
        )

    async def test_pings_are_still_sent_so_a_dead_socket_is_detected(self, chamber_config):
        """Disabling keepalive entirely would hide a genuinely dead bridge."""
        connect = _FakeConnect([[]])
        client, _ = _make(chamber_config, connect)
        with pytest.raises(asyncio.CancelledError):
            await client.run()
        assert connect.kwargs[0].get("ping_interval"), "keepalive must stay on"


@pytest.mark.asyncio
class TestHealthPollNamesItsFailure:
    async def test_the_exception_type_is_logged(self, chamber_config, caplog):
        """MUSHY-88's lesson: httpx timeouts stringify to "", so the log read
        `/health poll failed: ` and named nothing."""
        import logging

        class Boom:
            async def get(self, *a, **kw):
                raise httpx.ReadTimeout("")

        client, _ = _make(chamber_config, _FakeConnect([[]]), http=Boom())
        with caplog.at_level(logging.WARNING):
            await client.poll_health()
        assert any("ReadTimeout" in r.getMessage() for r in caplog.records), (
            f"failure must name its type, got: {[r.getMessage() for r in caplog.records]}"
        )


# ---------------------------------------------------------------------------
# The silent half: a deferral that lasts all day must stop being invisible.
# ---------------------------------------------------------------------------

class TestHeartbeatDeferralBecomesVisible:
    def _cfg(self, chamber_config):
        return chamber_config(ALERT_HEARTBEAT_HOUR="8", TZ="America/Montevideo")

    def _at(self, hour):
        """now_ms for today at a given local hour."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        dt = datetime(2026, 8, 19, hour, 0, tzinfo=ZoneInfo("America/Montevideo"))
        return int(dt.timestamp() * 1000)

    def test_a_cold_start_deferral_stays_quiet(self, chamber_config, caplog):
        import logging
        from farm_agent.chamber import heartbeat
        st = heartbeat.HeartbeatState()
        with caplog.at_level(logging.INFO):
            heartbeat.tick(state=st, config=self._cfg(chamber_config),
                           now_ms=self._at(9), get_summary=lambda: {}, dispatch=lambda e: None)
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_a_sustained_deferral_escalates_to_a_warning(self, chamber_config, caplog):
        """The live failure: deferring every 15 min all day at INFO."""
        import logging
        from farm_agent.chamber import heartbeat
        st = heartbeat.HeartbeatState()
        cfg = self._cfg(chamber_config)
        with caplog.at_level(logging.INFO):
            for _ in range(heartbeat.DEFERRALS_BEFORE_ALARM):
                heartbeat.tick(state=st, config=cfg, now_ms=self._at(9),
                               get_summary=lambda: {}, dispatch=lambda e: None)
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "an all-day deferral must not stay at INFO"
        assert "being lost" in warnings[-1].getMessage()

    def test_the_day_is_still_never_consumed_by_a_deferral(self, chamber_config):
        """Pitfall 10 must survive: deferring must not silence the day."""
        from farm_agent.chamber import heartbeat
        st = heartbeat.HeartbeatState()
        cfg = self._cfg(chamber_config)
        for _ in range(6):
            heartbeat.tick(state=st, config=cfg, now_ms=self._at(9),
                           get_summary=lambda: {}, dispatch=lambda e: None)
        assert st.last_fired_day is None

        sent = []
        heartbeat.tick(state=st, config=cfg, now_ms=self._at(9),
                       get_summary=lambda: {"rh": 0.9}, dispatch=sent.append)
        assert len(sent) == 1, "once telemetry arrives the day must still fire"
