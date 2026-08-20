"""
tests/chamber/test_service_wiring.py -- ChamberService composition + D-05 routing.

SC1 (bridge disconnect -> pi-offline alert) is proven here against a real FSM and
a fake SignalClient. The live send to a real phone remains a manual leg.
"""

import asyncio
import pytest

from farm_agent.chamber import service, state

MIN = 60_000
BOOT = 1_700_000_000_000


class FakeSignalClient:
    """Records sends. Mirrors SignalClient.send's return contract."""

    def __init__(self):
        self.sent: list[str] = []

    async def send(self, body, **kwargs):
        self.sent.append(body)
        return {"ok": True, "timestamp": 1}


@pytest.fixture
def svc(chamber_config):
    def _make(**over):
        cfg = chamber_config(**over)
        client = FakeSignalClient()
        s = service.ChamberService(
            config=cfg, signal_client=client, http=None, clock=lambda: BOOT
        )
        return s, client
    return _make


# ---------------------------------------------------------------------------
# SC1 -- bridge disconnect fires a pi-offline alert
# ---------------------------------------------------------------------------


async def test_bridge_disconnect_fires_pi_alert(svc):
    """SC1: fc1 goes dark -> the farmer is told the chamber is uncontrolled.

    Uses the fc1-dark path (the Phase 46 signal): a health poll reports an fc1
    timestamp older than the hardcoded 3-minute threshold, on the pi_liveness
    call site that fast-fires.
    """
    s, client = svc(ALERT_PI_OFFLINE_MIN="5")
    s.state = state.initial_state(BOOT)
    now = BOOT + 90 * MIN                       # past the 60s startup grace

    await s.on_event(
        {
            "type": "pi_liveness",
            "ws_connected": True,
            "ros_connected": True,
            "fc1_last_msg_ts": now - 4 * MIN,   # dark for 4 min > 3 min threshold
        },
        now_ms=now,
    )

    assert s.state.per_type["pi"].state == "FIRING"
    assert len(client.sent) == 1
    assert "FC-1" in client.sent[0]
    assert "chamber uncontrolled" in client.sent[0]


async def test_no_alert_while_healthy(svc):
    s, client = svc()
    s.state = state.initial_state(BOOT)
    now = BOOT + 90 * MIN

    await s.on_event(
        {"type": "pi_liveness", "ws_connected": True, "ros_connected": True,
         "fc1_last_msg_ts": now - 10_000},
        now_ms=now,
    )
    assert client.sent == []


async def test_recovery_is_sent_after_the_alert(svc):
    """The farmer who got the PROBLEM must get the RECOVERY."""
    s, client = svc(ALERT_PI_OFFLINE_MIN="5")
    s.state = state.initial_state(BOOT)
    now = BOOT + 90 * MIN

    await s.on_event(
        {"type": "pi_liveness", "ws_connected": True, "ros_connected": True,
         "fc1_last_msg_ts": now - 4 * MIN}, now_ms=now,
    )
    assert len(client.sent) == 1

    await s.on_event(
        {"type": "pi_liveness", "ws_connected": True, "ros_connected": True,
         "fc1_last_msg_ts": now + MIN}, now_ms=now + MIN,
    )
    assert len(client.sent) == 2
    assert "RECOVERY" in client.sent[1]


async def test_send_failure_does_not_break_the_fsm(svc):
    """A Signal outage must not corrupt alert state or raise into the ws loop."""
    s, client = svc(ALERT_PI_OFFLINE_MIN="5")
    s.state = state.initial_state(BOOT)
    now = BOOT + 90 * MIN

    async def boom(body, **kw):
        raise RuntimeError("signal-cli down")

    client.send = boom
    await s.on_event(
        {"type": "pi_liveness", "ws_connected": True, "ros_connected": True,
         "fc1_last_msg_ts": now - 4 * MIN}, now_ms=now,
    )
    assert s.state.per_type["pi"].state == "FIRING"   # FSM advanced regardless


# ---------------------------------------------------------------------------
# apply_snooze + get_summary
# ---------------------------------------------------------------------------


def test_apply_snooze_all_mutes_every_type(svc):
    s, _ = svc()
    s.state = state.initial_state(BOOT)
    s.apply_snooze({"ok": True, "alert_type": "all", "until_ms": BOOT + 24 * 60 * MIN})
    assert all(
        s.state.per_type[t].snoozed_until == BOOT + 24 * 60 * MIN
        for t in state.ALERT_TYPES
    )


async def test_snoozed_type_suppresses_the_send(svc):
    s, client = svc(ALERT_PI_OFFLINE_MIN="5")
    s.state = state.initial_state(BOOT)
    now = BOOT + 90 * MIN
    s.apply_snooze({"ok": True, "alert_type": "pi", "until_ms": now + 60 * MIN})

    await s.on_event(
        {"type": "pi_liveness", "ws_connected": True, "ros_connected": True,
         "fc1_last_msg_ts": now - 4 * MIN}, now_ms=now,
    )
    assert s.state.per_type["pi"].state == "FIRING"   # FSM advances
    assert client.sent == []                           # but nothing is sent


def test_get_summary_shape_matches_format_heartbeat(svc):
    s, _ = svc()
    s.state = state.initial_state(BOOT)
    s.state.current_rh = 91.2
    s.state.current_temp = 21.4
    s.state.current_co2 = 800
    summary = s.get_summary()
    for key in ("rh", "temp", "co2", "humidifier", "humidifier_cycles"):
        assert key in summary
    assert summary["rh"] == 91.2


# ---------------------------------------------------------------------------
# D-05 composite dispatch
# ---------------------------------------------------------------------------


def _envelope(text: str, source: str = "+59899111111") -> dict:
    """Minimal signal-cli envelope shape. Match router.classify_envelope's reader."""
    return {
        "envelope": {
            "source": source,
            "sourceNumber": source,
            "timestamp": BOOT,
            "dataMessage": {"message": text, "timestamp": BOOT},
        }
    }


@pytest.fixture
def dispatch_pair(svc, chamber_config):
    def _make():
        s, client = svc()
        s.state = state.initial_state(BOOT)
        handled = []

        async def pipeline_handle(env):
            handled.append(env)

        dispatch = service.make_composite_dispatch(
            chamber_service=s,
            pipeline_handle=pipeline_handle,
            signal_client=client,
            config=chamber_config(),
        )
        return dispatch, s, client, handled
    return _make


async def test_snooze_text_routes_to_chamber_not_pipeline(dispatch_pair):
    dispatch, s, client, handled = dispatch_pair()
    await dispatch(_envelope("snooze rh 4h"))

    assert s.state.per_type["rh"].snoozed_until is not None
    assert handled == [], "a snooze command must not reach the capture pipeline"


async def test_bare_mute_routes_to_chamber_and_acks(dispatch_pair):
    dispatch, s, client, handled = dispatch_pair()
    await dispatch(_envelope("mute"))

    assert all(s.state.per_type[t].snoozed_until is not None for t in state.ALERT_TYPES)
    assert any("muted for 24h" in b for b in client.sent)
    assert handled == []


async def test_ordinary_text_falls_through_to_the_pipeline(dispatch_pair):
    """The capture pipeline still gets everything that is not a command."""
    dispatch, s, client, handled = dispatch_pair()
    env = _envelope("harvested 3 bags of shiitake today")
    await dispatch(env)

    assert handled == [env]
    assert client.sent == []


async def test_malformed_snooze_replies_with_help_and_stops(dispatch_pair):
    """snooze-prefixed but unparseable: send the help text, do not fan out."""
    dispatch, s, client, handled = dispatch_pair()
    await dispatch(_envelope("snooze co2 4h"))

    assert any("Valid alert types" in b for b in client.sent)
    assert handled == []


async def test_dispatch_never_raises_on_a_junk_envelope(dispatch_pair):
    """ReceiveLoop wraps dispatch in try/except, but do not rely on it."""
    dispatch, s, client, handled = dispatch_pair()
    for junk in ({}, {"envelope": {}}, {"envelope": {"dataMessage": None}}):
        await dispatch(junk)     # must not raise


# ---------------------------------------------------------------------------
# boot.py wiring -- asserted by source inspection + import, so these run
# without a DB (test_boot.py's live-boot tests already cover the DB path)
# ---------------------------------------------------------------------------

import inspect
import re


def _boot_source() -> str:
    from farm_agent import boot  # noqa: PLC0415

    return inspect.getsource(boot)


def test_boot_constructs_exactly_one_receive_loop():
    """D-05 / T-58-03-05 / A3: a second poller silently eats inbound messages."""
    src = _boot_source()
    assert len(re.findall(r"\bReceiveLoop\(", src)) == 1
    assert len(re.findall(r"\bSignalClient\(", src)) == 1


def test_boot_wires_the_rate_cap_hook():
    """Pitfall 9's other half: Plan 03 removed the config field, boot supplies the value."""
    src = _boot_source()
    assert "get_max_sends_per_hour" in src
    assert "max_sends_per_hour" in src


def test_boot_uses_the_composite_dispatch_not_the_bare_pipeline():
    src = _boot_source()
    assert "make_composite_dispatch" in src
    assert not re.search(r"ReceiveLoop\([^)]*dispatch=pipeline\[", src), (
        "ReceiveLoop must receive the composite dispatcher, not pipeline['handle'] directly"
    )


def test_boot_cancels_chamber_tasks_on_shutdown():
    """Shutdown symmetry: every create_task needs a matching cancel (boot.py:134-154)."""
    src = _boot_source()
    created = len(re.findall(r"asyncio\.create_task\(", src))
    cancelled = len(re.findall(r"\.cancel\(\)", src))
    assert cancelled >= created, (
        f"{created} tasks created but only {cancelled} cancels found -- "
        "a leaked task survives shutdown"
    )
    assert "chamber" in src.lower()


def test_boot_does_not_log_chamber_config_fields():
    """T-56-06-01: lifecycle-only log lines."""
    src = _boot_source()
    for line in re.findall(r"log\.info\((.*?)\)", src, re.S):
        assert "chamber_config." not in line
        assert "signal_sender" not in line


# ---------------------------------------------------------------------------
# MUSHY-97 -- the wiring seam itself
#
# The adapter and the FSM were both fine in isolation; the glue between them was
# missing and the alerter was deaf for a day and a half. A unit test of either
# side passes either way, so this drives a RAW BRIDGE FRAME through the service
# the way the socket does, and asserts the FSM actually moved.
# ---------------------------------------------------------------------------


async def test_a_raw_bridge_frame_reaches_the_fsm(svc):
    """The exact shape sniffed off prod: no `type` key anywhere."""
    s, _ = svc()
    await s._on_ws_message({"humidity": 0.913, "timestamp": 1787179328207})
    assert s.state.current_rh == 0.913, "a real bridge frame must move the FSM"


async def test_a_raw_frame_fills_the_heartbeat_summary(svc):
    """The farmer-visible consequence: an empty summary defers the heartbeat."""
    s, _ = svc()
    assert s.get_summary()["rh"] is None
    for frame in (
        {"humidity": 0.91, "timestamp": 1},
        {"temperature": 19.4, "timestamp": 2},
        {"co2": 812, "timestamp": 3},
    ):
        await s._on_ws_message(frame)
    summary = s.get_summary()
    assert (summary["rh"], summary["temp"], summary["co2"]) == (0.91, 19.4, 812)


async def test_mission_control_only_frames_are_still_ignored(svc):
    """Most live traffic is not the alerter's business and must not throw."""
    s, _ = svc()
    for frame in (
        {"humidifier_duty": 0, "timestamp": 1},
        {"humidity_target": 0.915, "timestamp": 2},
        {"pid_output": 0, "timestamp": 3},
        {"vpd": 0.3, "water_vapor": 8.1, "timestamp": 4},
    ):
        await s._on_ws_message(frame)
    assert s.state.current_rh is None


# ---------------------------------------------------------------------------
# MUSHY-54 -- the two-stage split, guarded at the JOIN
#
# The heartbeat reached the farmer on ~12% of days because its two stages
# disagreed about the hour: heartbeat.js:54 dispatched at `hour >=
# heartbeat_hour` and consumed the day on dispatch, while state.js:662 only
# emitted at `hour === heartbeat_hour`. Any dispatch outside the exact hour was
# dropped AFTER the day was already spent -- no error, no retry, and
# `[heartbeat] fired` in the log meaning "dispatched", not "sent".
#
# Both sides are unit-tested for `>=` separately, and both passed throughout the
# outage. Only the join tells the truth, so these drive the real scheduler tick
# into the real reducer through the real dispatch and assert a body reached the
# farmer.
# ---------------------------------------------------------------------------

from farm_agent.chamber import heartbeat  # noqa: E402

HOUR = 3_600_000
UTC_17 = 1_700_067_600_000     # 2026-11-15 17:00:00Z, on the heartbeat hour


def _served(clock_ms, chamber_config):
    """A service with telemetry in hand, wired exactly as start() wires it."""
    cfg = chamber_config(TZ="UTC", ALERT_HEARTBEAT_HOUR="17")
    client = FakeSignalClient()
    s = service.ChamberService(
        config=cfg, signal_client=client, http=None, clock=lambda: clock_ms[0]
    )
    s.state = state.initial_state(clock_ms[0])
    s.state.current_rh = 0.91
    s.state.current_temp = 19.4
    s.state.current_co2 = 812
    s.state.last_telemetry_at_ms = clock_ms[0]
    return s, client


async def _tick(s, hb_state, clock_ms):
    heartbeat.tick(
        state=hb_state, config=s._config, now_ms=clock_ms[0],
        get_summary=s.get_summary, dispatch=s._dispatch_heartbeat,
    )
    for _ in range(4):          # let _dispatch_heartbeat's task actually run
        await asyncio.sleep(0)


async def test_a_scheduler_tick_reaches_the_farmer(chamber_config):
    """The baseline: on the hour, a dispatch becomes a real message."""
    clock = [UTC_17]
    s, client = _served(clock, chamber_config)
    await _tick(s, heartbeat.HeartbeatState(), clock)
    assert len(client.sent) == 1
    assert "[HEARTBEAT]" in client.sent[0]


async def test_a_tick_an_hour_late_still_reaches_the_farmer(chamber_config):
    """MUSHY-54 itself: the scheduler fires at `hour >=`, so the reducer must
    too. With `==` on the reducer side the day is consumed and nothing sends."""
    clock = [UTC_17 + HOUR]
    s, client = _served(clock, chamber_config)
    await _tick(s, heartbeat.HeartbeatState(), clock)
    assert len(client.sent) == 1, "a late tick must not be silently dropped"


async def test_a_tick_six_hours_late_still_reaches_the_farmer(chamber_config):
    """A restart late in the evening is the common way this happened."""
    clock = [UTC_17 + 6 * HOUR]
    s, client = _served(clock, chamber_config)
    await _tick(s, heartbeat.HeartbeatState(), clock)
    assert len(client.sent) == 1


async def test_a_tick_before_the_hour_sends_nothing(chamber_config):
    """The fix must not turn into 'send whenever'."""
    clock = [UTC_17 - HOUR]
    s, client = _served(clock, chamber_config)
    await _tick(s, heartbeat.HeartbeatState(), clock)
    assert client.sent == []


async def test_repeated_ticks_send_one_heartbeat_a_day(chamber_config):
    """Both stages consume the day, so neither may double-send."""
    clock = [UTC_17]
    s, client = _served(clock, chamber_config)
    hb = heartbeat.HeartbeatState()
    for _ in range(4):
        await _tick(s, hb, clock)
        clock[0] += 900_000
    assert len(client.sent) == 1


async def test_a_tier_c_hour_cannot_make_the_scheduler_burn_the_day(chamber_config):
    """Root cause 2: the scheduler read the globals-shadowed effective config
    (`getEffective().heartbeatHour`) while the reducer read bootstrap env. A
    `globals.heartbeat_hour` LOWER than env -- 8 is exactly what
    fc_controller.py declares as its default -- makes the scheduler dispatch and
    consume the day at 08:00 while the reducer still waits for 17. The heartbeat
    is then lost every single day, which is the leading explanation for the
    07-14..07-18 losses.

    Both stages take the same config object now. The proof is behavioural: an
    early tick must leave the day UNSPENT, so the real hour still sends."""
    clock = [UTC_17 - 9 * HOUR]        # 08:00, the globals hour
    s, client = _served(clock, chamber_config)
    s.state.alerter_globals = {"heartbeat_hour": 8}
    hb = heartbeat.HeartbeatState()

    await _tick(s, hb, clock)
    assert client.sent == [], "08:00 is not the heartbeat hour"

    clock[0] = UTC_17                  # the real hour, same local day
    await _tick(s, hb, clock)
    assert len(client.sent) == 1, "the early tick must not have spent the day"
