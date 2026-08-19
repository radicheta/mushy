"""
tests/chamber/test_service_wiring.py -- ChamberService composition + D-05 routing.

SC1 (bridge disconnect -> pi-offline alert) is proven here against a real FSM and
a fake SignalClient. The live send to a real phone remains a manual leg.
"""

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
