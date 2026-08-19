"""
tests/chamber/test_ws_client.py -- bridge WS client (port of bridge-client.js).

The reconnect schedule and the liveness payload are pure functions, tested here
without a socket. Task 2 adds the loop-level tests on top.
"""

import asyncio
import json

import httpx
import pytest

from farm_agent.chamber import ws_client


# ---------------------------------------------------------------------------
# Backoff schedule -- bridge-client.js:15, 49, 79-80
# ---------------------------------------------------------------------------


def test_backoff_constants_match_node():
    assert ws_client.MIN_BACKOFF_MS == 1_000
    assert ws_client.MAX_BACKOFF_MS == 30_000


def test_backoff_doubles_then_caps_at_30s():
    """The exact wait sequence across consecutive failures.

    Node: wait the current value, THEN double it capped at 30s. 16s doubles to
    32s, which clamps to 30s -- so 30 appears once by clamping and then repeats.
    """
    waits = []
    b = ws_client.MIN_BACKOFF_MS
    for _ in range(8):
        waits.append(b)
        b = ws_client.next_backoff_ms(b)
    assert waits == [1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000, 30_000]


def test_backoff_never_exceeds_cap():
    assert ws_client.next_backoff_ms(30_000) == 30_000
    assert ws_client.next_backoff_ms(29_000) == 30_000   # 58000 clamps


# ---------------------------------------------------------------------------
# Health payload parsing -- bridge-client.js:21-40, 67-77
# ---------------------------------------------------------------------------

NOW = 1_700_000_000_000

HEALTH_OK = {
    "ros": {"connected": True},
    "humidifier": {"last_msg_ts": NOW - 5_000},
    "fc1": {"last_msg_ts": NOW - 2_000},
}


def test_parse_health_extracts_all_fields():
    out = ws_client.parse_health(HEALTH_OK, NOW)
    assert out == {
        "ws_connected": True,
        "ros_connected": True,
        "humidifier_last_msg_ts": NOW - 5_000,
        "fc1_last_msg_ts": NOW - 2_000,
        "now_ms": NOW,
    }


def test_parse_health_missing_fc1_block_degrades_to_none():
    """An older bridge has no fc1 block. None means 'no signal', not 'dark'."""
    out = ws_client.parse_health({"ros": {"connected": True}}, NOW)
    assert out["fc1_last_msg_ts"] is None
    assert out["humidifier_last_msg_ts"] is None


def test_parse_health_ros_disconnected():
    out = ws_client.parse_health({"ros": {"connected": False}}, NOW)
    assert out["ros_connected"] is False


def test_parse_health_none_payload_keeps_ws_connected():
    """PARITY: a FAILED health poll still reports ws_connected=True.

    bridge-client.js:38 -- the socket is fine, only the health data is unknown.
    Reporting False here would trip the pi-offline ws branch on a transient
    health blip and page the farmer for nothing.
    """
    out = ws_client.parse_health(None, NOW)
    assert out["ws_connected"] is True
    assert out["ros_connected"] is False
    assert out["fc1_last_msg_ts"] is None


def test_parse_health_on_close_uses_cached_snapshot():
    """On ws close, liveness comes from the LAST health snapshot (bridge-client.js:70-77).

    Losing the socket does not mean losing what we last knew -- the FSM still
    needs the cached fc1 timestamp to decide whether the chamber is dark.
    """
    out = ws_client.parse_health(HEALTH_OK, NOW, ws_connected=False)
    assert out["ws_connected"] is False
    assert out["fc1_last_msg_ts"] == NOW - 2_000       # preserved, not nulled
    assert out["ros_connected"] is True


@pytest.mark.parametrize(
    "malformed",
    [{}, {"fc1": None}, {"fc1": {}}, {"ros": "yes"}, {"humidifier": []}, {"fc1": {"last_msg_ts": None}}],
)
def test_parse_health_never_raises_on_malformed(malformed):
    """T-63-10: a malformed /health body must not kill the poll loop."""
    out = ws_client.parse_health(malformed, NOW)
    assert isinstance(out, dict)
    assert out["now_ms"] == NOW


# ---------------------------------------------------------------------------
# Reconnect loop -- injected connect/sleep, no sockets and no real waiting
# ---------------------------------------------------------------------------


class _FakeSocket:
    def __init__(self, frames):
        self.frames = list(frames)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.frames:
            raise StopAsyncIteration
        return self.frames.pop(0)


class _FakeConnect:
    """Scripted stand-in for websockets.connect.

    outcomes: list of either an exception (connect fails) or a list of frames to
    yield before the connection closes.
    """

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.attempts = 0

    async def __call__(self, url, **kwargs):
        # MUSHY-96 passes keepalive params; accept and ignore them here.
        self.attempts += 1
        self.kwargs = kwargs
        outcome = self.outcomes.pop(0) if self.outcomes else OSError("exhausted")
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeSocket(outcome)


def _make_client(chamber_config, connect, **over):
    slept = []

    async def fake_sleep(sec):
        slept.append(sec)
        if len(slept) > 10:            # loop guard for the test
            raise asyncio.CancelledError

    kwargs = dict(
        config=chamber_config(),
        http=httpx.AsyncClient(),
        on_message=lambda m: None,
        on_liveness=lambda e: None,
        connect=connect,
        sleep=fake_sleep,
    )
    kwargs.update(over)
    client = ws_client.WsClient(**kwargs)
    return client, slept


async def test_reconnect_waits_follow_the_node_schedule(chamber_config):
    """Consecutive connect failures back off 1s, 2s, 4s, ... (in seconds)."""
    connect = _FakeConnect([OSError("refused")] * 6)
    client, slept = _make_client(chamber_config, connect)
    with pytest.raises(asyncio.CancelledError):
        await client.run()
    assert slept[:5] == [1.0, 2.0, 4.0, 8.0, 16.0]


async def test_opening_alone_no_longer_resets_the_backoff(chamber_config):
    """MUSHY-96 -- REPLACES test_successful_connect_resets_backoff.

    js:49 reset the schedule on a good OPEN. This test used to assert that,
    with a connection that "connects, closes immediately" -- which is exactly
    the live failure: a bridge under load accepted the socket, the client's
    keepalive killed it seconds later, the backoff reset to 1s, and the client
    reconnected every second while every reconnect made the bridge replay its
    buffer again.

    Opening is not success. Staying open is. A connection that proves itself
    still resets the schedule -- see
    tests/chamber/test_ws_reconnect_storm.py::test_a_connection_that_held_resets_the_backoff.
    """
    connect = _FakeConnect([
        OSError("refused"), OSError("refused"),       # backoff climbs to 4s
        [],                                            # connects, closes immediately
        OSError("refused"),
    ])
    client, slept = _make_client(chamber_config, connect)
    with pytest.raises(asyncio.CancelledError):
        await client.run()
    assert slept[0] == 1.0
    assert slept[1] == 2.0
    assert slept[2] == 4.0, "a connect-then-die must NOT reset the schedule"


async def test_messages_are_dispatched(chamber_config):
    got = []
    connect = _FakeConnect([[json.dumps({"type": "humidity", "value": 91.2})]])
    client, _ = _make_client(chamber_config, connect, on_message=got.append)
    with pytest.raises(asyncio.CancelledError):
        await client.run()
    assert got == [{"type": "humidity", "value": 91.2}]


async def test_malformed_frame_does_not_kill_the_loop(chamber_config):
    """T-63-10: a bad frame is logged and skipped; the good one still arrives."""
    got = []
    connect = _FakeConnect([["}{not json", json.dumps({"type": "co2", "value": 800})]])
    client, _ = _make_client(chamber_config, connect, on_message=got.append)
    with pytest.raises(asyncio.CancelledError):
        await client.run()
    assert got == [{"type": "co2", "value": 800}]


async def test_ws_liveness_state_tracks_connect_and_close(chamber_config):
    connect = _FakeConnect([[]])
    client, _ = _make_client(chamber_config, connect, clock=lambda: 12_345)
    assert client.ws_connected is False
    with pytest.raises(asyncio.CancelledError):
        await client.run()
    assert client.ws_last_connected_ms == 12_345
    assert client.ws_connected is False       # closed again by the end


async def test_health_poll_failure_is_fail_open(chamber_config, respx_mock):
    """A 500 from /health logs and yields None downstream -- never raises."""
    cfg = chamber_config()
    respx_mock.get(cfg.bridge_health_url).mock(return_value=httpx.Response(500))

    events = []
    async with httpx.AsyncClient() as http:
        client = ws_client.WsClient(
            config=cfg, http=http,
            on_message=lambda m: None, on_liveness=events.append,
            connect=_FakeConnect([]), clock=lambda: 999,
        )
        await client.poll_health()

    assert events[0]["fc1_last_msg_ts"] is None
    assert events[0]["ws_connected"] is True     # socket unaffected by a health blip


async def test_health_poll_success_emits_fc1_timestamp(chamber_config, respx_mock):
    cfg = chamber_config()
    respx_mock.get(cfg.bridge_health_url).mock(
        return_value=httpx.Response(200, json={"ros": {"connected": True},
                                               "fc1": {"last_msg_ts": 777}})
    )
    events = []
    async with httpx.AsyncClient() as http:
        client = ws_client.WsClient(
            config=cfg, http=http,
            on_message=lambda m: None, on_liveness=events.append,
            connect=_FakeConnect([]), clock=lambda: 999,
        )
        await client.poll_health()

    assert events[0]["fc1_last_msg_ts"] == 777
    assert events[0]["ros_connected"] is True
