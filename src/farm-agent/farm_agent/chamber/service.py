"""
chamber/service.py -- composition root for the chamber alerter.

Composes the ports of three Node files:
  - index.js         the wiring (ws events -> FSM -> send)
  - state.js         the FSM itself (farm_agent.chamber.state)
  - bridge-client.js the WS transport (farm_agent.chamber.ws_client)

D-05 / T-58-03-05 / A3: this module constructs NO SignalClient, NO
httpx.AsyncClient and NO ReceiveLoop. All three are owned by boot.py and injected.
A second poller on the same Signal number silently double-drains the inbound queue
and messages vanish.

D-06: FSM state is in-memory and resets on restart, matching Node. Nothing here
touches the pool, and no alert state is persisted.
"""

from __future__ import annotations

import asyncio
import logging
import time

from farm_agent.chamber import heartbeat, snooze, state, ws_client
from farm_agent.chamber.frame_adapter import bridge_frame_to_event
from farm_agent.signal_io import router

logger = logging.getLogger(__name__)

# Node's periodic evaluation tick. Without it the FSM would never re-evaluate
# during prolonged silence, so sht30/scd41/pi could not reach FIRING when no
# events arrive at all (state.js relies on the same periodic tick).
EVAL_TICK_INTERVAL_S = 30.0


class ChamberService:
    """Drives the alert FSM from bridge events and sends via the SHARED client."""

    def __init__(self, *, config, signal_client, http, log=None, clock=None,
                 last_sent_day=None) -> None:
        self._config = config
        self._signal_client = signal_client
        self._http = http
        self._log = log or logger
        self._clock = clock or (lambda: int(time.time() * 1000))
        # MUSHY-98: async () -> 'YYYY-MM-DD' | None, so a restart after the
        # heartbeat hour does not re-send the day.
        self._last_sent_day = last_sent_day

        self.state = state.initial_state(self._clock())
        self._tasks: list[asyncio.Task] = []
        self._ws: ws_client.WsClient | None = None

    # -- FSM ---------------------------------------------------------------

    def handle_event(self, event: dict, now_ms: int | None = None) -> list[dict]:
        """Run one event through the FSM. Pure with respect to I/O."""
        now = self._clock() if now_ms is None else now_ms
        self.state, actions = state.transition(self.state, event, now, self._config)
        return actions

    async def perform(self, actions: list[dict]) -> None:
        """Send each action's body, SEQUENTIALLY.

        Never asyncio.gather: ordering is attribution-critical (a PROBLEM must
        reach the farmer before its RECOVERY). Each send is individually wrapped
        so a Signal outage cannot propagate into the ws loop or roll back the FSM
        state that has already advanced (T-63-17).
        """
        for action in actions:
            try:
                # MUSHY-98: label the send. Without an intent every chamber
                # message landed in signal_outbound as 'unknown', so heartbeats
                # and alerts could not be counted or audited after the fact.
                await self._signal_client.send(
                    action["body"], intent=action.get("kind")
                )
            except Exception as e:  # noqa: BLE001 -- fail-open by design
                self._log.warning(
                    "[chamber] send failed for %s: %s", action.get("kind"), e
                )

    async def on_event(self, event: dict, now_ms: int | None = None) -> None:
        await self.perform(self.handle_event(event, now_ms))

    def apply_snooze(self, parsed: dict) -> None:
        """Route a parsed snooze through the FSM rather than mutating per_type.

        One code path means the snooze semantics cannot drift from state.js.
        """
        self.handle_event({
            "type": "snooze",
            "alert_type": parsed.get("alert_type"),
            "until_ms": parsed.get("until_ms"),
        })

    def get_summary(self) -> dict:
        """The heartbeat summary. Keys match message.format_heartbeat (Plan 05)."""
        st = self.state
        # MUSHY-98: age against the last TELEMETRY FRAME, not the moment the
        # socket opened. ws_last_connected_ms is stamped once at connect and
        # never refreshed, so the healthier the connection the older fc1
        # appeared -- the live heartbeat said "Pi last seen: 899 seconds ago"
        # while frames were arriving every second. The connection time remains
        # the fallback for the window after a connect but before the first
        # frame, where it is the only thing known.
        last_seen_ms = st.fc1_last_msg_ts or st.ws_last_connected_ms
        pi_last_seen_sec = None
        if last_seen_ms is not None:
            pi_last_seen_sec = int((self._clock() - last_seen_ms) / 1000)
        return {
            "rh": st.current_rh,
            "temp": st.current_temp,
            "co2": st.current_co2,
            "humidifier": "ON" if st.humidifier_on_since_ms is not None else "OFF",
            "humidifier_cycles": st.humidifier_cycles_last_24h,
            "pi_last_seen_sec": pi_last_seen_sec,
        }

    # -- lifecycle ---------------------------------------------------------

    async def _on_ws_message(self, msg) -> None:
        """Translate a bridge frame into an FSM event, then apply it.

        MUSHY-97: this used to assume "a bridge frame is already the FSM's event
        shape" and drop anything without a `type`. The bridge sends
        measurement-keyed frames with no `type` at all, so EVERY frame was
        dropped and the chamber alerter was deaf. Node did the translation in
        index.js:229-257; the port lost it. See chamber/frame_adapter.py.
        """
        event = bridge_frame_to_event(msg, self._clock())
        if event is not None:
            await self.on_event(event)

    def _dispatch_ws_message(self, msg) -> None:
        self._tasks.append(asyncio.create_task(self._on_ws_message(msg)))

    def _dispatch_liveness(self, liveness: dict) -> None:
        event = {"type": "pi_liveness", **liveness}
        self._tasks.append(asyncio.create_task(self.on_event(event)))

    def _dispatch_heartbeat(self, event: dict) -> None:
        self._tasks.append(asyncio.create_task(self.on_event(event)))

    async def _eval_tick_loop(self) -> None:
        while True:
            await asyncio.sleep(EVAL_TICK_INTERVAL_S)
            try:
                await self.on_event({"type": "tick"})
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self._log.warning("[chamber] eval tick error: %s", e)

    async def start(self) -> None:
        """Start the ws reconnect loop, the heartbeat and the eval tick."""
        self._ws = ws_client.WsClient(
            config=self._config,
            http=self._http,
            on_message=self._dispatch_ws_message,
            on_liveness=self._dispatch_liveness,
            log=self._log,
        )
        self._tasks.append(asyncio.create_task(self._ws.run()))
        self._tasks.append(asyncio.create_task(
            heartbeat.heartbeat_loop(
                config=self._config,
                get_summary=self.get_summary,
                dispatch=self._dispatch_heartbeat,
                last_sent_day=self._last_sent_day,
                log=self._log,
            )
        ))
        self._tasks.append(asyncio.create_task(self._eval_tick_loop()))

    async def stop(self) -> None:
        """Cancel every task this service created (boot's shutdown stays flat)."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:  # noqa: BLE001
                self._log.warning("[chamber] task stopped with error: %s", e)
        self._tasks.clear()


def make_composite_dispatch(
    *, chamber_service, pipeline_handle, signal_client, config, log=None
):
    """D-05: route snooze commands to the chamber, everything else to capture.

    A standalone factory on purpose -- it makes the routing rule unit-testable
    without booting the daemon (boot needs a DB, this does not).

    V4: performs NO whitelist check, because ReceiveLoop.tick already whitelisted
    the sender before calling dispatch. The rule being protected is that this
    function opens no SECOND ingestion path, not that it re-checks.
    """
    log = log or logger

    async def dispatch(env: dict) -> None:
        try:
            classified = router.classify_envelope(env or {})
            text = (classified.get("dm") or {}).get("message") or ""
        except Exception:  # noqa: BLE001 -- a junk envelope is simply not a command
            text = ""

        parsed = snooze.parse_snooze_command(text, int(time.time() * 1000))

        if parsed.get("ok"):
            chamber_service.apply_snooze(parsed)
            ack = parsed.get("ack_text")
            if ack:
                try:
                    await signal_client.send(ack)
                except Exception as e:  # noqa: BLE001
                    log.warning("[chamber] snooze ack send failed: %s", e)
            return                       # consumed; do NOT fan out

        reply = parsed.get("reply")
        if reply:
            # snooze-shaped but malformed -> the help text, and stop here.
            try:
                await signal_client.send(reply)
            except Exception as e:  # noqa: BLE001
                log.warning("[chamber] snooze help send failed: %s", e)
            return

        await pipeline_handle(env)       # ordinary farmer speech

    return dispatch
