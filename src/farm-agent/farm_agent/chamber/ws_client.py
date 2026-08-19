"""
chamber/ws_client.py -- ROS-bridge WS client. Port of bridge-client.js.

Two decisions worth stating:

1. The backoff is HAND-ROLLED, not delegated to the websockets library's
   reconnect iterator. SC1 (pi-offline fires within the configured window)
   depends on reconnect timing, and Phase 64 replays real traffic against both
   stacks -- so the schedule has to be Node's 1s->30s doubling exactly, not
   whatever the library defaults to this release.

2. The backoff schedule and the liveness payload are pure functions, so the
   parity-critical behaviour is testable without a socket.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import websockets

logger = logging.getLogger(__name__)

# bridge-client.js:56 -- keep state.fc1_last_msg_ts warm. WS frames never carry
# fc1.last_msg_ts (it is a /health aggregate), so without this poll the alerter
# would snapshot it once at ws_open and stale out. 10s matches the chamber-dark
# trigger granularity.
HEALTH_POLL_INTERVAL_S = 10.0

# bridge-client.js:11-12 (minBackoffMs / maxBackoffMs defaults)
MIN_BACKOFF_MS = 1_000
MAX_BACKOFF_MS = 30_000

# MUSHY-96: a connection must EARN a backoff reset by staying open. Node reset
# on a successful open (js:49), so a socket that opened and died a second later
# reset the schedule to 1s -- the client then reconnected every second, and
# every reconnect made the bridge replay its buffer again, which made the next
# ping likelier to time out. Self-amplifying, like MUSHY-89's receipt loop.
HEALTHY_CONNECTION_MS = 30_000

# Keepalive tuned for a peer that goes busy, not one that goes away. The
# websockets default ping_timeout of 20s killed good sockets while the bridge
# replayed a backlog (observed: replays growing 138 -> 375 -> 1222 rows).
# Pings stay ON so a genuinely dead bridge is still detected, just not one that
# is merely slow.
PING_INTERVAL_S = 20
PING_TIMEOUT_S = 90


def next_backoff_ms(current_ms: int) -> int:
    """Double the backoff, capped. Port of bridge-client.js:80.

    Node waits the CURRENT value and then advances, so the wait sequence from a
    fresh client is 1s, 2s, 4s, 8s, 16s, 30s, 30s, ... (32s clamps to 30s).
    """
    return min(current_ms * 2, MAX_BACKOFF_MS)


def _dig(payload: dict, key: str, field: str):
    """Safely read payload[key][field]; None if absent or the wrong shape."""
    block = payload.get(key)
    if not isinstance(block, dict):
        return None
    return block.get(field)


def parse_health(payload: dict | None, now_ms: int, ws_connected: bool = True) -> dict:
    """Build a liveness event from a /health body. Port of bridge-client.js:27-38, 70-77.

    Three cases:
      - payload present, ws_connected=True  -> a successful poll
      - payload None                        -> a FAILED poll: ws stays True (the
        socket is fine, only the health data is unknown), everything else falls
        back to False/None
      - ws_connected=False                  -> the socket closed; the caller
        passes the last CACHED payload so the FSM keeps the fc1 timestamp it
        needs to judge chamber-dark

    Never raises, whatever the bridge sends (T-63-10).
    """
    if not isinstance(payload, dict):
        return {
            "ws_connected": ws_connected,
            "ros_connected": False,
            "humidifier_last_msg_ts": None,
            "fc1_last_msg_ts": None,
            "now_ms": now_ms,
        }
    return {
        "ws_connected": ws_connected,
        "ros_connected": bool(_dig(payload, "ros", "connected")),
        "humidifier_last_msg_ts": _dig(payload, "humidifier", "last_msg_ts"),
        # Phase 46 D-02: null when /health has no fc1 block (old bridge) --
        # graceful degradation, consumed downstream as "no signal", never "dark".
        "fc1_last_msg_ts": _dig(payload, "fc1", "last_msg_ts"),
        "now_ms": now_ms,
    }


class WsClient:
    """Bridge WS client with Node-parity reconnect. Port of bridge-client.js:42-98.

    Everything external is injected -- `connect`, `sleep` and `clock` -- so the
    reconnect schedule, frame dispatch and liveness transitions are all testable
    without a socket or a real wait. The httpx client is the caller's shared
    instance (boot.py owns it); this class never constructs one and never reads
    the environment.

    websockets API pinned against the installed 16.1.1 (Task 2 Step 0, RESEARCH
    Q2/A1 was unverified): `websockets.connect` re-exports
    `websockets.asyncio.client.connect`, which supports BOTH `await connect(url)`
    -> ClientConnection and `async with connect(url)`. ClientConnection is itself
    an async context manager and an async iterator whose iteration ends cleanly
    on a normal close. We use `sock = await connect(url)` then
    `async with sock: async for raw in sock:` -- the one idiom that works for the
    real client and for a plain injected fake alike.
    """

    def __init__(
        self,
        *,
        config,
        http,
        on_message,
        on_liveness,
        log=None,
        connect=None,
        sleep=None,
        clock=None,
    ) -> None:
        self._config = config
        self._http = http
        self._on_message = on_message
        self._on_liveness = on_liveness
        self._log = log or logger
        self._connect = connect or websockets.connect
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or (lambda: int(time.time() * 1000))

        self._ws_connected = False
        self._ws_last_connected_ms: int | None = None
        self._last_health: dict | None = None

    @property
    def ws_connected(self) -> bool:
        return self._ws_connected

    @property
    def ws_last_connected_ms(self) -> int | None:
        return self._ws_last_connected_ms

    async def poll_health(self) -> None:
        """GET /health and emit a liveness event. Port of bridge-client.js:21-40.

        Fail-open: ANY failure logs a warning and emits `parse_health(None, ...)`,
        which keeps ws_connected=True -- the socket is fine, only the health data
        is unknown. Raising here would kill the reconnect loop and leave the
        chamber silently unmonitored, the exact failure Phase 46 existed to stop.
        """
        try:
            res = await self._http.get(self._config.bridge_health_url)
            res.raise_for_status()
            body = res.json()
            self._last_health = body
            self._on_liveness(parse_health(body, self._clock()))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 -- fail-open by design
            # MUSHY-88 again: httpx timeouts stringify to "".
            self._log.warning(
                "[bridge-client] /health poll failed: %s: %s", type(e).__name__, e
            )
            self._on_liveness(parse_health(None, self._clock()))

    async def _health_loop(self) -> None:
        """Poll /health every 10s while the socket is open (bridge-client.js:56).

        Uses asyncio.sleep rather than the injected sleep on purpose: the injected
        sleep carries the parity-critical BACKOFF schedule, and mixing this fixed
        cadence into it would corrupt that signal. The task is always cancelled on
        close, so it never actually elapses in tests.
        """
        while True:
            await asyncio.sleep(HEALTH_POLL_INTERVAL_S)
            await self.poll_health()

    async def run(self) -> None:
        """Reconnect forever. Cancel the task to stop.

        The wait ordering is load-bearing: sleep the CURRENT backoff, THEN
        advance it (bridge-client.js:79-80). Advancing first would skip the 1s
        wait and desync the whole schedule from Node.
        """
        backoff = MIN_BACKOFF_MS
        while True:
            opened_at_ms = None
            try:
                sock = await self._connect(
                    self._config.bridge_ws_url,
                    ping_interval=PING_INTERVAL_S,
                    ping_timeout=PING_TIMEOUT_S,
                )
                async with sock:
                    self._ws_connected = True
                    self._ws_last_connected_ms = self._clock()
                    opened_at_ms = self._clock()
                    self._log.info("[bridge-client] ws_open")
                    await self.poll_health()
                    health_task = asyncio.create_task(self._health_loop())
                    try:
                        async for raw in sock:
                            try:
                                self._on_message(json.loads(raw))
                            except asyncio.CancelledError:
                                raise
                            except Exception as e:  # noqa: BLE001
                                self._log.warning(
                                    "[bridge-client] parse error: %s", e
                                )
                    finally:
                        health_task.cancel()
                        try:
                            await health_task
                        except (asyncio.CancelledError, Exception):  # noqa: BLE001
                            pass
            except asyncio.CancelledError:
                raise                              # shutdown must propagate
            except Exception as e:  # noqa: BLE001
                # MUSHY-88's lesson: an httpx/websockets timeout stringifies to
                # "", so name the type or the log identifies nothing.
                self._log.warning(
                    "[bridge-client] connect failed: %s: %s", type(e).__name__, e
                )

            # Closed or failed: report liveness from the CACHED health snapshot,
            # so the FSM keeps the fc1 timestamp it needs to judge chamber-dark.
            self._ws_connected = False
            self._on_liveness(
                parse_health(self._last_health, self._clock(), ws_connected=False)
            )

            # MUSHY-96: reset only if this connection PROVED itself. Opening is
            # not success. A socket that dies immediately leaves the schedule
            # climbing, so a flapping bridge is backed away from instead of
            # hammered.
            if opened_at_ms is not None:
                held_ms = self._clock() - opened_at_ms
                if held_ms >= HEALTHY_CONNECTION_MS:
                    backoff = MIN_BACKOFF_MS
                else:
                    self._log.warning(
                        "[bridge-client] connection held only %dms; backing off %dms",
                        held_ms, backoff,
                    )

            await self._sleep(backoff / 1000)
            backoff = next_backoff_ms(backoff)
