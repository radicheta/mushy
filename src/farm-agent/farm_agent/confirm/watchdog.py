"""
confirm/watchdog.py -- Async confirm-loop watchdog (nudge + expire).

Port of src/agents/alerter/src/confirm/watchdog.js.
Mirrors the farm_agent/capture/retention.py immediate-then-sleep never-throws loop shape.

Provides:
  tick_once(pool, signal_client, config, *, lock=None, repo=None) -> None
  confirm_watchdog_loop(pool, signal_client, config) -> None  (coroutine, run until cancelled)

Design:
  - Ticks IMMEDIATELY on boot (restart-safe), then every draft_watchdog_interval_ms.
  - never-throws: swallow Exception + log WARNING + continue; re-raise CancelledError.
  - asyncio.Lock around tick_once prevents tick overlap (belt-and-suspenders;
    the SQL guards in confirm_repo are the correctness mechanism for races).
  - Nudge at round(draft_pending_timeout_min * draft_nudge_fraction) minutes.
  - Expire at draft_pending_timeout_min minutes.
  - Per-row Signal send routed DM vs group via reply_target_kind.
  - PII: mask_number() for any sender_e164 in logs (T-61-13).

Launched from boot.py as asyncio.create_task(confirm_watchdog_loop(pool, signal_client, config)).
Cancelled via confirm_task.cancel() on shutdown (CancelledError swallowed in boot.py).

T-61-11 (DoS -- tick error kills loop): never-throws + WARNING + continue.
T-61-13 (PII -- e164 in logs): mask_number applied.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import farm_agent.confirm.confirm_repo as _real_repo
from farm_agent.confirm.preview import build_expired_note, build_nudge
from farm_agent.tenancy.tenant import mask_number

log = logging.getLogger(__name__)


def _route_target(row: dict):
    """Return Signal routing target (DM string or group dict) for a candidate row."""
    if row.get("reply_target_kind") == "group" and row.get("group_id"):
        return {"groupId": row["group_id"]}
    return row.get("sender_e164")


def _minutes_remaining(row: dict, timeout_min: int) -> int:
    """Compute minutes remaining until expiry from row['updated_at']."""
    updated_at = row.get("updated_at")
    if updated_at is None:
        return 0
    now = datetime.now(timezone.utc)
    elapsed_min = (now - updated_at).total_seconds() / 60
    return max(0, round(timeout_min - elapsed_min))


async def tick_once(
    pool,
    signal_client,
    config,
    *,
    lock: asyncio.Lock | None = None,
    repo=None,
) -> None:
    """One watchdog tick: find nudge/expire candidates, dispatch SQL-guarded side effects.

    Parameters
    ----------
    pool:
        psycopg3 AsyncConnectionPool (or fake in tests).
    signal_client:
        SignalClient instance (or fake in tests).
    config:
        TenantConfig or config-like object. Must have:
          draft_pending_timeout_min, draft_nudge_fraction.
    lock:
        asyncio.Lock to prevent concurrent tick overlap. If None, creates a temporary one
        for this call (single-call use; normally the loop passes its own persistent lock).
    repo:
        Injected confirm_repo module or fake; defaults to the real confirm_repo.
        Used for dependency injection in tests.

    Per RESEARCH / Pitfall 2: the Lock is belt-and-suspenders (intra-process).
    The SQL WHERE guards (mark_nudge_sent, expire_draft) are the cross-process
    correctness mechanism.
    """
    if repo is None:
        repo = _real_repo
    if lock is None:
        lock = asyncio.Lock()

    timeout_min = config.draft_pending_timeout_min
    nudge_min = round(timeout_min * config.draft_nudge_fraction)

    async with lock:
        # -- Nudge candidates --
        nudge_rows = await repo.find_nudge_candidates(pool, nudge_min)
        for row in nudge_rows:
            draft_id = row["id"]
            try:
                result = await repo.mark_nudge_sent(pool, draft_id)
                if result.get("rowcount") == 1:
                    # Won the SQL race -- send nudge
                    mins_left = _minutes_remaining(row, timeout_min)
                    to = _route_target(row)
                    # D-2: unlike Node (watchdog.js:31), which sends only
                    # minutesRemaining, we pass the draft's preview through so
                    # the farmer knows which draft is nudging them.
                    msg = build_nudge(
                        minutes_remaining=mins_left,
                        preview_summary=row.get("farmer_facing_preview"),
                    )
                    try:
                        await signal_client.send(
                            msg,
                            to=to,
                            related_draft_id=draft_id,
                            intent="nudge",
                        )
                    except Exception as e:  # noqa: BLE001
                        log.warning(
                            "[watchdog] nudge send failed draft_id=%s sender=%s: %s",
                            draft_id,
                            mask_number(row.get("sender_e164", "")),
                            e,
                        )
                    await repo.append_event_via_pool(
                        pool,
                        draft_id,
                        "nudge_sent",
                        {"mins_remaining": mins_left},
                    )
                else:
                    # rowcount==0: another tick already sent nudge (race lost -- skip)
                    log.info(
                        "[watchdog] nudge race lost (already nudged) draft_id=%s", draft_id
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "[watchdog] nudge processing failed draft_id=%s sender=%s: %s",
                    draft_id,
                    mask_number(row.get("sender_e164", "")),
                    e,
                )

        # -- Expire candidates --
        expire_rows = await repo.find_expire_candidates(pool, timeout_min)
        for row in expire_rows:
            draft_id = row["id"]
            try:
                result = await repo.expire_draft(pool, draft_id, "timeout_expired")
                if result.get("rowcount") == 1:
                    # Won the SQL race -- send expired note
                    to = _route_target(row)
                    msg = build_expired_note()
                    try:
                        await signal_client.send(
                            msg,
                            to=to,
                            related_draft_id=draft_id,
                            intent="expired_note",
                        )
                    except Exception as e:  # noqa: BLE001
                        log.warning(
                            "[watchdog] expire send failed draft_id=%s sender=%s: %s",
                            draft_id,
                            mask_number(row.get("sender_e164", "")),
                            e,
                        )
                else:
                    # rowcount==0: already expired (race lost -- skip)
                    log.info(
                        "[watchdog] expire race lost (already expired) draft_id=%s", draft_id
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "[watchdog] expire processing failed draft_id=%s sender=%s: %s",
                    draft_id,
                    mask_number(row.get("sender_e164", "")),
                    e,
                )


async def confirm_watchdog_loop(pool, signal_client, config) -> None:
    """Async confirm-loop watchdog task.

    Mirrors the retention_loop immediate-then-sleep pattern (retention.py):
      1. Tick immediately on boot (restart-safe: catches any rows that aged during restart).
      2. Log result.
      3. Swallow any Exception from tick with a WARNING -- loop continues.
      4. Sleep draft_watchdog_interval_ms / 1000 seconds.
      5. Repeat.
      6. asyncio.CancelledError re-raises (clean shutdown via boot.py cancel).

    Port of watchdog.js start() + setInterval pattern.
    """
    lock = asyncio.Lock()
    interval = config.draft_watchdog_interval_ms / 1000
    nudge_min = round(config.draft_pending_timeout_min * config.draft_nudge_fraction)
    log.info(
        "[watchdog] started: timeout=%dmin nudge=%dmin interval=%.0fms",
        config.draft_pending_timeout_min,
        nudge_min,
        config.draft_watchdog_interval_ms,
    )

    # Immediate tick on boot (restart-safe)
    try:
        await tick_once(pool, signal_client, config, lock=lock)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("[watchdog] initial tick failed: %s", e)

    # Interval loop
    while True:
        try:
            await asyncio.sleep(interval)
            await tick_once(pool, signal_client, config, lock=lock)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("[watchdog] tick error: %s", e)
