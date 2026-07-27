"""
farm_agent/boot.py -- single asyncio entrypoint (FND-01).

This is the ONLY module allowed to import across Foray package boundaries.
All other packages import only within their own package or from packages
lower in the dependency graph (D-03 / FND-05).

Boot sequence:
  1. Configure structured logging
  2. Load TenantConfig from env (tenancy.load)
  3. Open the psycopg3 async pool (persistence.build_pool)
  4. Run idempotent migrations (persistence.run_migrations)
  5. Build httpx.AsyncClient + SignalClient + transcribe_client + capture pipeline
  6. Start ReceiveLoop (dispatch=pipeline["handle"]) -- exactly ONE poller (T-58-03-05/A3)
  7. Start asyncio retention task (retention_loop)
  8. Log "boot complete in %.2fs" + "capture pipeline live"
  9. Idle on asyncio.Event waiting for SIGTERM / SIGINT
 10. Graceful shutdown: stop loop, cancel retention, close http + pool

T-56-06-01 (Information Disclosure): this module NEVER logs the config
object or any field that could contain a secret value. Only the elapsed
time and module-level lifecycle messages are emitted.
T-58-03-05: exactly ONE ReceiveLoop started on the farmer account (A3 dual-poller guard).
"""

import asyncio
import logging
import os
import signal
import time

import anthropic
import httpx

from farm_agent.tenancy.tenant import load as load_config
from farm_agent.persistence.pool import build_pool
from farm_agent.persistence.migrations import run_migrations
from farm_agent.signal_io.client import SignalClient
from farm_agent.signal_io.receive_loop import ReceiveLoop
from farm_agent.capture.transcribe_client import create_transcribe_client
from farm_agent.capture.pipeline import create_capture_pipeline
from farm_agent.capture.retention import retention_loop
from farm_agent.gate import create_event_gate
from farm_agent.gate.classifier import create_haiku_classifier

log = logging.getLogger(__name__)


async def main() -> None:
    """Wire the daemon: config -> pool -> migrations -> capture pipeline -> idle on SIGTERM.

    Designed to be called from __main__.py via asyncio.run(main()).
    Also used directly in tests (the test cancels the task after boot completes).
    """
    t0 = time.monotonic()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # FND-02: tenancy.load is the sole env reader; config object is NEVER logged.
    config = load_config(os.environ)

    # FND-03: open the shared async pool.
    pool = await build_pool(config)

    # FND-03: run idempotent additive-only migrations.
    await run_migrations(pool)

    # Phase 58: build HTTP client + signal client + transcribe client + capture pipeline.
    # T-58-03-05 / A3: exactly ONE ReceiveLoop is started on the farmer account.
    http = httpx.AsyncClient()
    signal_client = SignalClient(config=config, http=http)
    transcribe_client = create_transcribe_client(config.whisper_url, http)

    # Phase 59: shared AsyncAnthropic singleton + event-gate (one per daemon lifetime).
    # T-56-06-01: api_key flows only into the constructor and is NEVER logged.
    anthropic_client = anthropic.AsyncAnthropic(
        api_key=config.anthropic_api_key,
        max_retries=2,
    )
    gate = create_event_gate(
        haiku_classifier=create_haiku_classifier(client=anthropic_client),
        log=log,
    )

    pipeline = create_capture_pipeline(pool, signal_client, transcribe_client, config, gate=gate)

    # Start the inbound drain (Phase 57 deferred -- now live).
    # T-58-03-05: only one ReceiveLoop constructed and started here.
    receive_loop = ReceiveLoop(signal_client, dispatch=pipeline["handle"], config=config)
    await receive_loop.start()

    # Start daily retention task.
    retention_task = asyncio.create_task(retention_loop(pool, config))

    elapsed = time.monotonic() - t0
    # T-56-06-01: only elapsed time is logged -- no config fields, no secrets.
    log.info("boot complete in %.2fs", elapsed)
    # T-56-06-01: no config fields logged here (whisper_url etc. excluded).
    log.info("capture pipeline live")

    # Idle until SIGTERM or SIGINT.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()

    # Graceful shutdown: stop receive loop, cancel retention, close http + pool.
    await receive_loop.stop()
    retention_task.cancel()
    try:
        await retention_task
    except asyncio.CancelledError:
        pass
    await anthropic_client.close()
    await http.aclose()
    await pool.close()
