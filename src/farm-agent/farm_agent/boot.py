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
  5. Log "boot complete in %.2fs"
  6. Idle on asyncio.Event waiting for SIGTERM / SIGINT
  7. Close the pool on shutdown

T-56-06-01 (Information Disclosure): this module NEVER logs the config
object or any field that could contain a secret value. Only the elapsed
time and module-level lifecycle messages are emitted.
"""

import asyncio
import logging
import os
import signal
import time

from farm_agent.tenancy.tenant import load as load_config
from farm_agent.persistence.pool import build_pool
from farm_agent.persistence.migrations import run_migrations

log = logging.getLogger(__name__)


async def main() -> None:
    """Wire the daemon: config -> pool -> migrations -> idle on SIGTERM.

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

    elapsed = time.monotonic() - t0
    # T-56-06-01: only elapsed time is logged -- no config fields, no secrets.
    log.info("boot complete in %.2fs", elapsed)

    # Idle until SIGTERM or SIGINT (Phase 57+ will add real tasks here).
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()

    # Graceful shutdown: close the pool cleanly.
    await pool.close()
