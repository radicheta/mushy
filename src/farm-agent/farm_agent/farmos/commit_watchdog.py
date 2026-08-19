"""
farmos/commit_watchdog.py -- Async commit drain loop (FWR-04 / FWR-01 / FWR-03).

Port of src/agents/alerter/src/farmos/commit-watchdog.js (Phase 40 D-07/D-07a/D-07b).
Mirrors confirm/watchdog.py immediate-then-sleep never-throws loop shape exactly.

Provides:
  tick_once(pool, farmos_client, config, *, lock=None, db=None, router=None, csv_rows=None) -> None
  commit_watchdog_loop(pool, farmos_client, config) -> None  (coroutine, run until cancelled)
  _is_transient(result) -> bool
  build_failure_ack(result) -> str

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

import farm_agent.farmos.commit_recovery as _recover
import farm_agent.farmos.commit_db as _real_db
import farm_agent.farmos.commits.commit_router as _real_router
from farm_agent.farmos.assets import find_asset_by_name as _find_asset_by_name
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


# MUSHY-75: farmOS reason codes are internal. A farmer reading
# "observation_requires_target" learns nothing they can act on, and that code is
# the single most common commit failure on prod. Only reasons actually seen are
# translated; anything else falls through verbatim, because an untranslated code
# is still better than swallowing the cause -- which was the original bug.
_REASON_IN_PLAIN_WORDS = {
    "observation_requires_target": "I could not tell which bag or block it was about",
    "no_target_asset_for_activity": "I could not tell which bag or block it was about",
    "missing_source_block": "I could not find the source block it came from",
    "fungi_type_not_found": "that strain is not set up in farmOS yet",
    "partial_commit_failed": "only part of it saved",
}


def build_failure_ack(result: dict | None) -> str:
    """Farmer-facing text for a terminal commit failure (MUSHY-75).

    Transport and validation failures need opposite responses:

      transport  -> farmOS was unreachable. The entry is correct. Asking the
                    farmer to fix it sends them hunting for a mistake that is
                    not there, which is what happened on 2026-08-16.
      validation -> farmOS answered and refused. The entry does need fixing.

    _is_transient already draws that line; before this the wording discarded it
    and every failure ended "Reply EDIT to fix it".

    Deliberately promises no automatic retry. A draft reaching this point is at
    the attempt cap and the watchdog will not pick it up again on its own, so
    "it will be retried" would be false.
    """
    reason = str((result or {}).get("reason") or "unknown")

    if _is_transient(result):
        return (
            "Couldn't save that to farmOS: the server was unreachable. "
            "Nothing is wrong with your entry, so there is nothing to fix. "
            "It is flagged and held here."
        )

    cause = _REASON_IN_PLAIN_WORDS.get(reason, reason)
    return (
        f"Couldn't save that to farmOS: {cause}. "
        "Reply EDIT to fix it, or leave it and it stays flagged for review."
    )


async def _send_farmer(signal_client, row: dict, body: str, intent: str) -> None:
    """Best-effort farmer send from the commit watchdog (MUSHY-38).

    DM-only, matching the Node original: an outcome ack is per-farmer and never
    goes to a group (outbound-confirm.js send_commit_outcome_ack).

    NEVER raises. A dead signal-cli must not unwind a commit that already
    succeeded, and must not abort the drain of the remaining rows -- but it MUST
    leave a WARNING so the operator can see the farmer was not reached.
    """
    if signal_client is None:
        log.warning(
            "[commit_watchdog] no signal_client wired; farmer NOT told (%s) draft_id=%s",
            intent, row.get("id"),
        )
        return
    to = row.get("sender_e164")
    if not to:
        log.warning(
            "[commit_watchdog] no DM target; farmer NOT told (%s) draft_id=%s",
            intent, row.get("id"),
        )
        return
    try:
        await signal_client.send(body, to=to, related_draft_id=row.get("id"), intent=intent)
    except Exception as e:  # noqa: BLE001
        log.warning(
            "[commit_watchdog] outcome ack send failed draft_id=%s intent=%s: %s",
            row.get("id"), intent, e,
        )


async def tick_once(
    pool,
    farmos_client: dict,
    config,
    *,
    lock: asyncio.Lock | None = None,
    db=None,
    router=None,
    csv_rows: list | None = None,
    signal_client=None,
) -> None:
    """One commit watchdog tick: release stale locks, drain confirmed Python-owned drafts.

    Sequence per tick:
      0. recover_transport_parked (MUSHY-75: un-park drafts farmOS says are absent)
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
        # Step 0 (MUSHY-75): give transport-parked drafts another chance, but only
        # where farmOS confirms their blocks are absent. Runs BEFORE the drain so
        # anything requeued commits on this same tick. Never raises.
        await _recover.recover_transport_parked(
            pool,
            lambda name: _find_asset_by_name(farmos_client, name),
            db,
            signal_client,
        )

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
                    # MUSHY-38: the ask-back used to be rendered and then only
                    # LOGGED, so the farmer was never actually asked and the draft
                    # sat held forever. Send it.
                    ask_back_msg = gate.get("ask_back_msg", "")
                    log.warning(
                        "[commit_watchdog] fidelity hold draft_id=%s "
                        "draft_strain=%s csv_strain=%s ask_back=%r",
                        draft_id,
                        gate.get("draft_strain"),
                        gate.get("csv_strain"),
                        ask_back_msg,
                    )
                    if ask_back_msg:
                        await _send_farmer(
                            signal_client, locked_row, ask_back_msg, "fidelity_ask_back",
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
                    # MUSHY-38 / Node T4 parity: tell the farmer it actually landed.
                    # Sent AFTER mark_committed so a crash in between drops the ack
                    # rather than double-acking (same <=1-dropped-ack trade-off the
                    # Node original takes with its tryMarkOutcomeAckSent CAS claim).
                    await _send_farmer(
                        signal_client, locked_row,
                        "Saved to farmOS.",
                        "commit_outcome_ack",
                    )
                    continue

                # Step 3d (failure): transient + attempt < max -> requeue; else -> mark_failed
                attempt = locked_row.get("commit_attempt_count") or 0
                if _is_transient(result) and attempt < retry_max:
                    # Still retrying -- stay quiet. The farmer only hears about an
                    # outcome once it is terminal.
                    await db.requeue_for_retry(pool, draft_id)
                else:
                    reason = result.get("reason") or "unknown"
                    await db.mark_failed(pool, draft_id, reason, _is_transient(result))
                    # MUSHY-38 / Node T6 parity. THIS is the CRIT path: dispatch already
                    # told the farmer "Got it! Your entry was recorded." at YES time, so
                    # without this they are left believing a failed write succeeded.
                    # MUSHY-75: and it must name the real cause -- a transport
                    # failure is not the farmer's entry being wrong.
                    await _send_farmer(
                        signal_client, locked_row,
                        build_failure_ack(result),
                        "commit_outcome_ack",
                    )

            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("[commit_watchdog] row %s threw: %s", draft_id, e)


async def commit_watchdog_loop(pool, farmos_client: dict, config, signal_client=None) -> None:
    """Async commit drain loop.

    Mirrors confirm_watchdog_loop (confirm/watchdog.py): immediate-then-sleep,
    never-throws, CancelledError re-raises.

    Interval: config.commit_watchdog_interval_ms / 1000
    (mirrors Node COMMIT_WATCHDOG_INTERVAL_MS=30000 default).

    CSV rows loaded once at call time from config.fidelity_csv_path (D-07:
    missing/bad CSV returns [] so absent rows pass through).

    Launched from boot.py via asyncio.create_task(commit_watchdog_loop(...)).
    Cancelled via commit_watchdog_task.cancel() on shutdown (CancelledError swallowed).

    signal_client is REQUIRED in production (MUSHY-38): without it every terminal
    outcome of this drain is silent to the farmer, who was already told "Got it!
    Your entry was recorded." at YES time. It stays optional in the signature only
    so existing tests can call the loop without one; a missing client is logged
    loudly at WARNING per send.
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
        await tick_once(pool, farmos_client, config, lock=lock, csv_rows=csv_rows,
                        signal_client=signal_client)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("[commit_watchdog] initial tick failed: %s", e)

    # Interval loop
    while True:
        try:
            await asyncio.sleep(interval)
            await tick_once(pool, farmos_client, config, lock=lock, csv_rows=csv_rows,
                        signal_client=signal_client)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("[commit_watchdog] tick error: %s", e)
