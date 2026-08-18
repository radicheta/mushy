"""
signal_io/receive_loop.py — async poll loop with sequential dispatch seam (SIG-03).

Ports the createReceiveLoop skeleton from receive-loop.js:47-70, 130-156.

Key invariants:
  - NEVER asyncio.gather() over envelopes — sequential for-loop preserves send
    attribution (RESEARCH PITFALLS #5/#6 / [[feedback_verify_signal_send_attribution]]).
  - loop-never-dies: a per-envelope try/except plus a per-tick outer try/except
    ensure one bad envelope or receive() error only logs a warning; next tick proceeds.
  - The dispatch seam is the Phase-58+ capture-pipeline entry point. This file does
    NOT implement capture/confirm — it exposes only the gated dispatch(envelope) call.

async lifecycle mirrors farm_agent/persistence/pool.py (build/open ↔ start/stop).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from farm_agent.signal_io import router as _router
from farm_agent.tenancy.tenant import TenantConfig

_LOG = logging.getLogger(__name__)


class ReceiveLoop:
    """Async poll loop that gates and dispatches inbound Signal envelopes.

    Parameters
    ----------
    signal_client:
        Duck-typed client with an async ``receive(timeout_sec, ignore_attachments)``
        method returning a list of envelope dicts. Injected; this module does NOT
        import client.py (avoids circular imports and eases unit-testing).
    dispatch:
        Async callable ``dispatch(envelope: dict) -> None``. Called once per
        whitelisted envelope, sequentially (no concurrent dispatch).
    config:
        Injected TenantConfig. config is the sole env-reader (FND-02).
    logger:
        Optional logger; defaults to the module logger.
    poll_sec:
        Seconds to sleep between ticks. Defaults to config.receive_poll_sec.
    """

    def __init__(
        self,
        signal_client: Any,
        dispatch: Callable[[dict], Awaitable[None]],
        config: TenantConfig,
        logger: logging.Logger | None = None,
        poll_sec: int | float | None = None,
    ) -> None:
        self._client = signal_client
        self._dispatch = dispatch
        self._config = config
        self._logger = logger or _LOG
        self._poll_sec = poll_sec if poll_sec is not None else config.receive_poll_sec
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Internal: one poll tick
    # ------------------------------------------------------------------

    async def tick(self) -> None:
        """Execute one receive-and-dispatch cycle.

        Mirrors receive-loop.js:130-156 (tick function):
        1. receive() envelopes
        2. for each envelope (SEQUENTIAL — never asyncio.gather):
           a. extract source; skip if absent
           b. whitelist gate; log warning + continue if rejected
           c. wrap dispatch in per-envelope try/except (loop-never-dies, Pitfall 4)
        3. any receive() exception is caught at the outer level; warning logged.
        """
        try:
            envelopes = await self._client.receive(timeout_sec=1)
        except Exception as exc:  # noqa: BLE001
            # MUSHY-88: log the TYPE, not just str(exc). httpx timeout exceptions
            # stringify to "", so this line read "[receive] receive() error: " and
            # said nothing -- while /v1/receive had already dequeued the farmer's
            # messages. The one failure that silently destroys farmer data was the
            # one the log could not name.
            self._logger.warning(
                "[receive] receive() error: %s: %s",
                type(exc).__name__,
                exc or "(no message)",
            )
            return

        # Sequential for-loop — NEVER asyncio.gather (attribution-critical)
        for env in envelopes:
            source = _router.extract_source(env)
            if not source:
                continue

            # Whitelist gate BEFORE any branch (T-57-03-01 / V4 / R7)
            if not _router.is_whitelisted(source, self._config):
                self._logger.warning(
                    "[receive] rejected sender (not in whitelist): %s",
                    _router.mask_number(source),
                )
                continue

            # Per-envelope try/except — one bad envelope must not kill the tick
            try:
                await self._dispatch(env)
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "[receive] dispatch error for %s: %s",
                    _router.mask_number(source),
                    exc,
                )

    # ------------------------------------------------------------------
    # Lifecycle (mirrors pool.py open/close pattern)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background poll task.

        The task runs ``while True: await tick(); await sleep(poll_sec)``.
        Mirrors Node's setInterval(tick, poll_sec * 1000).
        """
        if self._task is not None:
            return  # already running

        async def _loop() -> None:
            while True:
                await self.tick()
                await asyncio.sleep(self._poll_sec)

        self._task = asyncio.create_task(_loop())

    async def stop(self) -> None:
        """Cancel and await the poll task (swallow CancelledError).

        Mirrors Node's clearInterval(timer).
        """
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
