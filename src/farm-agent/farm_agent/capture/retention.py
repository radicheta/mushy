"""
capture/retention.py -- Daily soft-expiry asyncio task for signal_capture rows.

Port of src/agents/alerter/src/capture-retention.js createRetentionJob().

Provides:
  retention_loop(pool, config) -> None  (coroutine, runs until cancelled)

Design:
  - Run-once-then-sleep: mark_expired_older_than is called IMMEDIATELY on startup
    (run-once for outage catch-up per Q2 resolution in 58-RESEARCH.md), then
    awaits asyncio.sleep(86400) before the next run.
  - Errors from mark_expired_older_than are swallowed with a WARNING; the loop
    continues to sleep and retry the next day.
  - Launched from boot.py as asyncio.create_task(retention_loop(pool, config)).
  - Cancelled via retention_task.cancel() on shutdown (CancelledError swallowed in boot.py).

Python asyncio replaces node-cron -- no new dependency needed.

CAP-01/CAP-02 (Phase 59+ data lifecycle): soft-expire old rows; never deletes.
"""

from __future__ import annotations

import asyncio
import logging

from psycopg_pool import AsyncConnectionPool

from farm_agent.capture.capture_repo import mark_expired_older_than
from farm_agent.tenancy.tenant import TenantConfig

logger = logging.getLogger(__name__)


async def retention_loop(pool: AsyncConnectionPool, config: TenantConfig) -> None:
    """Daily soft-expiry of signal_capture rows older than capture_retention_days.

    Implements the run-once-then-sleep pattern (Q2 resolution):
      1. Run mark_expired_older_than immediately (catches up after a long outage).
      2. Log the result.
      3. Swallow any exception with a WARNING.
      4. Sleep 86400 seconds (1 day).
      5. Repeat.

    Port of createRetentionJob.run() + cron.schedule in capture-retention.js.
    """
    while True:
        try:
            age_seconds = config.capture_retention_days * 86_400
            count = await mark_expired_older_than(pool, age_seconds)
            logger.info(
                "[retention] flagged %d rows expired (>%dd)",
                count,
                config.capture_retention_days,
            )
        except Exception as e:  # noqa: BLE001 -- defense-in-depth: callee is fail-open but guard here in case its contract changes
            logger.warning("[retention] mark_expired_older_than failed: %s", e)

        await asyncio.sleep(86_400)
