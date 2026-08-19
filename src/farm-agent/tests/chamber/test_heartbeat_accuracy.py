"""MUSHY-98: the heartbeat tells the truth, once a day.

Three defects on the first heartbeat that ever reached the farmer from the
Python agent (2026-08-19 20:02 local):

  1. "Pi last seen: 899 seconds ago" while fc1 was streaming every second. The
     age was measured from ws_last_connected_ms -- the moment the SOCKET opened,
     stamped once and never refreshed -- so the healthier the connection, the
     older the Pi appeared. This is the one line telling the farmer whether the
     chamber is being watched, and it read as alarming precisely when all was
     well.
  2. The row landed in signal_outbound with intent 'unknown', because
     ChamberService.perform sent bodies with no intent at all. Heartbeats could
     therefore not be counted or audited, which is what made "has a heartbeat
     ever reached the farmer" harder to answer than it should have been.
  3. heartbeat_loop builds a fresh HeartbeatState on every boot (D-06 Node
     parity), so a restart after heartbeat_hour re-sends the day's heartbeat.
     Harmless while the heartbeat never fired; live the moment MUSHY-97 let
     telemetry through, and deploys cluster.

ASCII-only. No em-dashes.
"""
from __future__ import annotations

import pytest

from farm_agent.chamber import heartbeat, service

BOOT = 1_700_000_000_000
MIN = 60_000


class FakeSignalClient:
    def __init__(self) -> None:
        self.sends: list[dict] = []

    async def send(self, body, **kwargs):
        self.sends.append({"body": body, **kwargs})
        return {"ok": True, "timestamp": 1}


@pytest.fixture
def svc(chamber_config):
    def _make(now_ms=BOOT, **over):
        client = FakeSignalClient()
        s = service.ChamberService(
            config=chamber_config(**over), signal_client=client, http=None,
            clock=lambda: now_ms,
        )
        return s, client
    return _make


class TestPiLastSeenMeasuresTelemetry:
    def test_a_streaming_pi_reads_as_just_seen(self, svc):
        """The live bug: 899s reported while frames arrived every second."""
        now = BOOT + 60 * MIN
        s, _ = svc(now_ms=now)
        s.state.ws_last_connected_ms = BOOT          # socket opened an hour ago
        s.state.fc1_last_msg_ts = now - 2_000        # but a frame arrived 2s ago
        assert s.get_summary()["pi_last_seen_sec"] == 2

    def test_a_quiet_pi_still_reads_as_quiet(self, svc):
        """Fixing the false alarm must not hide a real one."""
        now = BOOT + 60 * MIN
        s, _ = svc(now_ms=now)
        s.state.ws_last_connected_ms = now           # socket healthy
        s.state.fc1_last_msg_ts = now - 30 * MIN     # nothing for 30 min
        assert s.get_summary()["pi_last_seen_sec"] == 30 * 60

    def test_falls_back_to_the_connection_when_no_frame_has_arrived(self, svc):
        """Right after a connect there is no frame yet; report something."""
        now = BOOT + 10 * MIN
        s, _ = svc(now_ms=now)
        s.state.ws_last_connected_ms = BOOT
        s.state.fc1_last_msg_ts = None
        assert s.get_summary()["pi_last_seen_sec"] == 10 * 60

    def test_none_when_nothing_is_known(self, svc):
        s, _ = svc()
        s.state.ws_last_connected_ms = None
        s.state.fc1_last_msg_ts = None
        assert s.get_summary()["pi_last_seen_sec"] is None


class TestSendsCarryTheirIntent:
    @pytest.mark.asyncio
    async def test_a_heartbeat_is_labelled_a_heartbeat(self, svc):
        s, client = svc()
        await s.perform([{"kind": "heartbeat", "body": "[HEARTBEAT] ..."}])
        assert client.sends[0]["intent"] == "heartbeat"

    @pytest.mark.asyncio
    async def test_an_alert_and_a_recovery_are_distinguishable(self, svc):
        s, client = svc()
        await s.perform([
            {"kind": "alert", "alert_type": "rh", "body": "RH out of band"},
            {"kind": "recovery", "alert_type": "rh", "body": "RH back"},
        ])
        assert [x["intent"] for x in client.sends] == ["alert", "recovery"]

    @pytest.mark.asyncio
    async def test_a_send_with_no_kind_still_goes_out(self, svc):
        """Labelling is a nice-to-have; delivering the message is not."""
        s, client = svc()
        await s.perform([{"body": "something"}])
        assert len(client.sends) == 1


class TestOneHeartbeatPerDayAcrossRestarts:
    def test_a_restart_after_the_hour_does_not_resend(self):
        """The live case: fired 20:02, redeployed 20:03, would fire again 20:18."""
        state = heartbeat.HeartbeatState()
        heartbeat.seed_from_history(state, already_sent_day="2026-08-19")

        sent = []
        heartbeat.tick(
            state=state, config=_cfg(), now_ms=_at(20),
            get_summary=lambda: {"rh": 0.94}, dispatch=sent.append,
        )
        assert sent == [], "the day was already sent before this restart"

    def test_the_next_day_still_fires(self):
        state = heartbeat.HeartbeatState()
        heartbeat.seed_from_history(state, already_sent_day="2026-08-18")

        sent = []
        heartbeat.tick(
            state=state, config=_cfg(), now_ms=_at(20),
            get_summary=lambda: {"rh": 0.94}, dispatch=sent.append,
        )
        assert len(sent) == 1

    def test_no_history_is_not_treated_as_already_sent(self):
        """A DB that cannot answer must not silence the heartbeat."""
        state = heartbeat.HeartbeatState()
        heartbeat.seed_from_history(state, already_sent_day=None)

        sent = []
        heartbeat.tick(
            state=state, config=_cfg(), now_ms=_at(20),
            get_summary=lambda: {"rh": 0.94}, dispatch=sent.append,
        )
        assert len(sent) == 1


# -- helpers ---------------------------------------------------------------

def _cfg():
    class C:
        timezone = "America/Montevideo"
        heartbeat_hour = 17
    return C()


def _at(hour: int) -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    dt = datetime(2026, 8, 19, hour, 5, tzinfo=ZoneInfo("America/Montevideo"))
    return int(dt.timestamp() * 1000)


class TestTheGuardIsActuallyWired:
    """MUSHY-97's lesson: the pieces were fine, the join was missing.

    seed_from_history being correct proves nothing unless heartbeat_loop calls
    it, so these drive the loop itself rather than the helper.
    """

    @pytest.mark.asyncio
    async def test_the_loop_seeds_itself_from_history(self):
        import asyncio

        sent = []

        async def one_pass(_s):
            raise asyncio.CancelledError

        async def already_today():
            return "2026-08-19"

        with pytest.raises(asyncio.CancelledError):
            await heartbeat.heartbeat_loop(
                config=_cfg(), get_summary=lambda: {"rh": 0.94},
                dispatch=sent.append, clock=lambda: _at(20),
                last_sent_day=already_today, sleep=one_pass,
            )
        assert sent == [], "a restart after the hour must not re-send the day"

    @pytest.mark.asyncio
    async def test_the_loop_still_fires_when_history_is_empty(self):
        import asyncio

        sent = []

        async def one_pass(_s):
            raise asyncio.CancelledError

        async def nothing_yet():
            return None

        with pytest.raises(asyncio.CancelledError):
            await heartbeat.heartbeat_loop(
                config=_cfg(), get_summary=lambda: {"rh": 0.94},
                dispatch=sent.append, clock=lambda: _at(20),
                last_sent_day=nothing_yet, sleep=one_pass,
            )
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_a_failing_history_lookup_does_not_silence_the_heartbeat(self):
        """A missing heartbeat is the failure this path exists to prevent."""
        import asyncio

        sent = []

        async def one_pass(_s):
            raise asyncio.CancelledError

        async def boom():
            raise RuntimeError("db down")

        with pytest.raises(asyncio.CancelledError):
            await heartbeat.heartbeat_loop(
                config=_cfg(), get_summary=lambda: {"rh": 0.94},
                dispatch=sent.append, clock=lambda: _at(20),
                last_sent_day=boom, sleep=one_pass,
            )
        assert len(sent) == 1
