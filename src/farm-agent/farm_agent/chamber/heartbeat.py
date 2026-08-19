"""
chamber/heartbeat.py -- daily heartbeat scheduler. Port of heartbeat.js.

Structure follows capture/retention.py's run-once-then-sleep asyncio task, with
one deliberate difference: the sleep is a SHORT retry interval (default 15 min,
matching Node's setInterval), not a fixed 86_400. Pitfall 10 -- the day is only
marked done when the summary actually carries telemetry, so a deferred day has
to be retried within the same day.

TZ-aware day/hour extraction uses ZoneInfo(config.timezone), replacing Node's
Intl.DateTimeFormat('en-CA'). The 'en-CA' locale was chosen there purely because
it yields YYYY-MM-DD; strftime gives that directly.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# MUSHY-96: deferrals before the log escalates from INFO to WARNING. At the
# 15-minute tick this is an hour of silence, which is well past a cold start and
# squarely a fault.
DEFERRALS_BEFORE_ALARM = 4


@dataclass
class HeartbeatState:
    """In-memory scheduler state. Resets on restart, matching Node (D-06)."""

    last_fired_day: str | None = None

    # MUSHY-96: how many times TODAY the heartbeat has deferred on an empty
    # summary. A permanently flapping bridge deferred every 15 minutes at INFO
    # level and burned the whole day without anyone noticing.
    deferrals_today: int = 0
    deferring_day: str | None = None


def tick(*, state: HeartbeatState, config, now_ms: int, get_summary, dispatch, log=None) -> None:
    """One scheduler check. Port of heartbeat.js:42-72.

    Fires {type: 'heartbeat_tick', summary} at most once per LOCAL day, once the
    local hour has reached config.heartbeat_hour.

    Pitfall 10: when the summary is empty (bridge has not replayed telemetry yet,
    e.g. right after a restart) the event is DEFERRED -- last_fired_day is left
    alone so the next tick retries. Consuming the day there would either silence
    it entirely or send 'RH: ? · Temp: ? · CO2: ?'.

    Never raises: a failure in get_summary or dispatch is logged and the day is
    left unconsumed.
    """
    log = log or logger
    try:
        local = datetime.fromtimestamp(now_ms / 1000, tz=ZoneInfo(config.timezone))
        day = local.strftime("%Y-%m-%d")
        hour = local.hour

        # heartbeat.js:54 uses >=, not ==, so a restart after the hour still fires today.
        if hour >= config.heartbeat_hour and day != state.last_fired_day:
            summary = get_summary()
            if summary is not None and any(
                summary.get(k) is not None for k in ("rh", "temp", "co2")
            ):
                state.last_fired_day = day
                dispatch({"type": "heartbeat_tick", "summary": summary})
                log.info("[heartbeat] fired for %s", day)
            else:
                if state.deferring_day != day:
                    state.deferring_day = day
                    state.deferrals_today = 0
                state.deferrals_today += 1
                # Escalate rather than repeat: a couple of deferrals is a normal
                # cold start, a sustained run means the bridge is not delivering
                # telemetry at all and the day is being lost.
                if state.deferrals_today >= DEFERRALS_BEFORE_ALARM:
                    log.warning(
                        "[heartbeat] STILL deferred for %s after %d attempts -- the "
                        "bridge has delivered no telemetry; today's heartbeat is "
                        "being lost", day, state.deferrals_today,
                    )
                else:
                    log.info(
                        "[heartbeat] deferred for %s -- bridge summary empty, will retry",
                        day,
                    )
    except Exception as e:  # noqa: BLE001 -- defense in depth; the loop must survive
        log.warning("[heartbeat] tick error: %s", e)


async def heartbeat_loop(
    *,
    config,
    get_summary,
    dispatch,
    clock=None,
    interval_s: float = 900.0,
    log=None,
) -> None:
    """Run tick() every interval_s forever. Port of heartbeat.js:75-78.

    Checks immediately on start (Node calls tick() before setInterval), then every
    interval_s. 15 min by default: short enough that a deferred day retries
    promptly, long enough to be free.

    Cancelled via task.cancel() from boot.py; CancelledError propagates so the
    caller's `except asyncio.CancelledError: pass` sees it.
    """
    import time

    clock = clock or (lambda: int(time.time() * 1000))
    state = HeartbeatState()
    while True:
        tick(
            state=state,
            config=config,
            now_ms=clock(),
            get_summary=get_summary,
            dispatch=dispatch,
            log=log,
        )
        await asyncio.sleep(interval_s)
