"""
farm_agent/__main__.py -- `python -m farm_agent` entry point (FND-01).

Thin wrapper: all logic lives in boot.main().
"""

import asyncio
import logging
import os
import sys
from collections.abc import Callable
from typing import Any, Coroutine

from farm_agent.boot import main

log = logging.getLogger(__name__)


def run_until_dead(
    coro_fn: Callable[[], Coroutine[Any, Any, None]] = main,
    exit_fn: Callable[[int], Any] = os._exit,
) -> None:
    """Run boot.main(), and guarantee the process dies if boot fails.

    MUSHY-106: this deliberately does NOT use asyncio.run(). asyncio.run()
    runs _cancel_all_tasks() and shutdown_default_executor() in its finally
    block BEFORE re-raising the boot exception, so an `except` wrapped around
    asyncio.run() is not reached when that cleanup is what hangs.

    On 2026-08-23 it hung: timescale was still in crash recovery after a host
    reboot, run_migrations hit its 30s deadline, and the cleanup blocked on
    psycopg_pool tasks mid-connect. No traceback printed, the process never
    exited, and `restart: unless-stopped` therefore never fired -- the
    container sat Up for minutes with no Signal intake, no chamber alerter and
    no watchdogs.

    run_until_complete() hands the exception straight back instead, so the
    handler below actually runs, and os._exit() cannot be blocked by a stuck
    event loop or a lingering executor thread. Exiting non-zero is what lets
    Docker's restart policy do the retrying -- the same mechanism that got
    farmos-agent and timelapse through the same boot race unattended.
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro_fn())
    except BaseException:
        log.exception("[boot] failed -- exiting so the restart policy can retry")
        # os._exit skips atexit and buffer flushing, so flush by hand first or
        # the reason for the exit is lost.
        sys.stdout.flush()
        sys.stderr.flush()
        exit_fn(1)


if __name__ == "__main__":
    run_until_dead()
