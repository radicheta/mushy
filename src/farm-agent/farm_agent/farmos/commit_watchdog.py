"""
farmos/commit_watchdog.py -- Async commit drain loop (FWR-04 / FWR-01 / FWR-03).

Port of src/agents/alerter/src/farmos/commit-watchdog.js (Phase 40 D-07/D-07a/D-07b).
Mirrors confirm/watchdog.py immediate-then-sleep never-throws loop shape exactly.

Provides:
  tick_once(pool, farmos_client, config, *, lock=None, db=None, router=None, csv_rows=None) -> None
  commit_watchdog_loop(pool, farmos_client, config) -> None  (coroutine, run until cancelled)
  _is_transient(result) -> bool

Design:
  - Ticks IMMEDIATELY on boot (restart-safe), then every commit_watchdog_interval_ms.
  - never-throws: swallow Exception + log WARNING + continue; re-raise CancelledError.
  - asyncio.Lock around tick_once prevents tick overlap (belt-and-suspenders;
    the SQL guards in commit_db are the correctness mechanism for races).
  - Origin guard: drains ONLY origin='python' confirmed drafts (D-01 / T-62-32).
  - Fidelity gate runs BEFORE the farmOS commit call (D-06 / T-62-30).
  - A draft failing the CSV fidelity gate is held as 'fidelity_cross_check_unverified'
    and the farmOS commit is NEVER made for that row.

Launched from boot.py as asyncio.create_task(commit_watchdog_loop(pool, farmos_client, config)).
Cancelled via commit_watchdog_task.cancel() on shutdown (CancelledError swallowed in boot.py).

T-62-30 (Tampering -- commit mismatch): fidelity gate blocks the farmOS write.
T-62-31 (DoS -- tick error kills loop): never-throws loop (WARNING + continue).
T-62-32 (Elevation of Privilege -- wrong poller): exactly one task; origin='python' guard.
T-62-33 (Information Disclosure): no config fields/secrets logged (T-56-06-01).

No em-dashes in source artifacts. No new pip packages.
"""

from __future__ import annotations

import asyncio
import logging
import re

import farm_agent.farmos.commit_db as _real_db
import farm_agent.farmos.commits.commit_router as _real_router
from farm_agent.farmos.fidelity_gate import check_fidelity, load_fidelity_csv

log = logging.getLogger(__name__)

# Regex for transient reason strings (port of commit-watchdog.js _isTransient lines 12-13)
_TRANSIENT_PATTERN = re.compile(r"timeout|abort|econnreset|econnrefused", re.IGNORECASE)


def _is_transient(result: dict | None) -> bool:
    """Classify a commit result as transient (retryable) or terminal.

    Port of commit-watchdog.js _isTransient() lines 8-14.

    Transient when:
      - result is None/falsy (network abort before response)
      - http_status is None (no response received)
      - http_status >= 500 (server error)
      - reason matches timeout|abort|econnreset|econnrefused (network/abort pattern)
    """
    if not result:
        return True
    http_status = result.get("http_status")
    if http_status is None:
        return True
    if http_status >= 500:
        return True
    reason = str(result.get("reason") or "")
    return bool(_TRANSIENT_PATTERN.search(reason))


async def tick_once(
    pool,
    farmos_client: dict,
    config,
    *,
    lock: asyncio.Lock | None = None,
    db=None,
    router=None,
    csv_rows: list | None = None,
) -> None:
    """One commit watchdog tick: release stale locks, drain confirmed Python-owned drafts.

    Sequence per tick:
      1. release_stale_locks (reclaim stuck 'committing' rows)
      2. find_confirmed_candidates(origin='python', batch_cap)
      3. Per row:
         a. acquire_commit_lock (CAS: confirmed -> committing); skip if rowcount != 1
         b. check_fidelity gate BEFORE any farmOS call (D-06 / T-62-30)
            - strain_mismatch: hold_for_fidelity, dispatch ask-back (best-effort), skip commit
            - block_not_in_csv: pass-through (D-07)
            - pass: proceed
         c. commit_router.commit(farmos_client, row)
         d. ok: mark_committed; transient+<max: requeue_for_retry; else: mark_failed
      - per-row exceptions caught (WARNING + continue) -- never-throws (T-62-31)

    Parameters
    ----------
    pool:
        psycopg3 AsyncConnectionPool (or fake in tests).
    farmos_client:
        Dict of async callables from create_farmos_client().
    config:
        TenantConfig. Uses commit_watchdog_batch_cap and commit_retry_max.
    lock:
        asyncio.Lock (belt-and-suspenders, intra-process). Created per-call if None.
    db:
        Injected commit_db module (defaults to real commit_db). For testing.
    router:
        Injected commit_router module (defaults to real commit_router). For testing.
    csv_rows:
        Pre-loaded fidelity CSV rows from load_fidelity_csv(). Defaults to [] (gate no-op).
    """
    if db is None:
        db = _real_db
    if router is None:
        router = _real_router
    if lock is None:
        lock = asyncio.Lock()
    if csv_rows is None:
        csv_rows = []

    batch_cap = getattr(config, "commit_watchdog_batch_cap", 10)
    retry_max = getattr(config, "commit_retry_max", 3)

    async with lock:
        # Step 1: release stale committing locks
        await db.release_stale_locks(pool)

        # Step 2: find confirmed candidates owned by Python (origin='python' guard is in SQL)
        rows = await db.find_confirmed_candidates(pool, batch_cap)

        for row in (rows or []):
            draft_id = row.get("id")
            try:
                # Step 3a: acquire per-row lock (CAS: confirmed -> committing)
                acq = await db.acquire_commit_lock(pool, draft_id)
                if not acq.get("ok") or acq.get("rowcount", 0) != 1:
                    continue  # race lost or row already in a terminal state

                # locked_row is the original row (acquire increments count in DB;
                # we read the pre-lock count from the candidate row)
                locked_row = row

                # Step 3b: fidelity gate BEFORE farmOS call (D-06 / T-62-30)
                gate = check_fidelity(locked_row, csv_rows)
                if gate.get("reason") == "strain_mismatch":
                    # Hold draft -- commit_router.commit MUST NOT be called (T-62-30)
                    await db.hold_for_fidelity(pool, draft_id)
                    # Dispatch ask-back best-effort (best-effort: log so the operator sees it)
                    ask_back_msg = gate.get("ask_back_msg", "")
                    log.warning(
                        "[commit_watchdog] fidelity hold draft_id=%s "
                        "draft_strain=%s csv_strain=%s ask_back=%r",
                        draft_id,
                        gate.get("draft_strain"),
                        gate.get("csv_strain"),
                        ask_back_msg,
                    )
                    continue  # skip commit_router.commit

                # Step 3c: commit to farmOS via router
                result = await router.commit(farmos_client, locked_row)

                if result.get("ok"):
                    # Step 3d (success): mark committed
                    await db.mark_committed(pool, draft_id, {
                        "asset_ids": result.get("asset_ids"),
                        "log_ids": result.get("log_ids"),
                        "file_ids": result.get("file_ids"),
                        "http_status": result.get("http_status"),
                        "latency_ms": result.get("latency_ms"),
                    })
                    continue

                # Step 3d (failure): transient + attempt < max -> requeue; else -> mark_failed
                attempt = locked_row.get("commit_attempt_count") or 0
                if _is_transient(result) and attempt < retry_max:
                    await db.requeue_for_retry(pool, draft_id)
                else:
                    await db.mark_failed(pool, draft_id, result.get("reason") or "unknown")

            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("[commit_watchdog] row %s threw: %s", draft_id, e)


async def commit_watchdog_loop(pool, farmos_client: dict, config) -> None:
    """Async commit drain loop.

    Mirrors confirm_watchdog_loop (confirm/watchdog.py): immediate-then-sleep,
    never-throws, CancelledError re-raises.

    Interval: config.commit_watchdog_interval_ms / 1000
    (mirrors Node COMMIT_WATCHDOG_INTERVAL_MS=30000 default).

    CSV rows loaded once at call time from config.fidelity_csv_path (D-07:
    missing/bad CSV returns [] so absent rows pass through).

    Launched from boot.py via asyncio.create_task(commit_watchdog_loop(...)).
    Cancelled via commit_watchdog_task.cancel() on shutdown (CancelledError swallowed).
    """
    lock = asyncio.Lock()
    interval = config.commit_watchdog_interval_ms / 1000
    csv_path = getattr(config, "fidelity_csv_path", "") or ""
    csv_rows = load_fidelity_csv(csv_path) if csv_path else []

    log.info(
        "[commit_watchdog] started: interval=%.0fms batch_cap=%d retry_max=%d csv_rows=%d",
        config.commit_watchdog_interval_ms,
        getattr(config, "commit_watchdog_batch_cap", 10),
        getattr(config, "commit_retry_max", 3),
        len(csv_rows),
    )

    # Immediate tick on boot (restart-safe: catches rows that aged during restart)
    try:
        await tick_once(pool, farmos_client, config, lock=lock, csv_rows=csv_rows)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("[commit_watchdog] initial tick failed: %s", e)

    # Interval loop
    while True:
        try:
            await asyncio.sleep(interval)
            await tick_once(pool, farmos_client, config, lock=lock, csv_rows=csv_rows)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("[commit_watchdog] tick error: %s", e)
