"""
scripts/live_fire_57.py -- Phase 57 live-fire harness for SC#1 + SC#3.

Self-send bot->bot round-trip: sends a plain message + a quote-threaded message
from the bot to itself, then asserts signal_outbound.signal_msg_ts is non-null
bigint for both rows.

Usage (from repo root, with real env sourced):
    cd src/farm-agent && uv run python scripts/live_fire_57.py

Safety guards:
  T-57-04-03: Refuses to run if default_target != signal_sender (self-send-only).
  T-57-04-01: No /v1/receive poller started (no dual-poller hazard, RESEARCH A3).

SC#1 acceptance:
    SELECT signal_msg_ts, pg_typeof(signal_msg_ts)
    FROM signal_outbound
    WHERE intent='live_fire_57'
    ORDER BY sent_at DESC LIMIT 2;
    -> both rows: non-null bigint

SC#3 acceptance:
    Operator visually confirms the second message renders as a native quote
    bubble on the bot's own Signal client device.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import httpx

from farm_agent.persistence import outbound_repo
from farm_agent.persistence.pool import build_pool
from farm_agent.tenancy.tenant import load as load_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


async def main() -> None:
    # Load config from real env (secrets.env must be in-process)
    config = load_config()

    # T-57-04-03: self-send guard
    # The harness MUST only run bot->bot. Refuse if the effective default_target
    # (config.signal_sender) is not the same as the sender.
    # This is enforced by passing default_target=config.signal_sender to SignalClient,
    # but we assert it explicitly here so the guard is visible at the top level.
    if not config.signal_sender:
        log.error("ABORT: SIGNAL_SENDER is not set in env.")
        sys.exit(1)

    bot_number = config.signal_sender

    # SC#3 render-visibility override: a self-send lands in the bot account's
    # Note-to-Self, which the operator may not have a client for. Setting
    # LIVE_FIRE_TARGET re-points the OUTBOUND target to a phone the operator can
    # see (e.g. the farmer's own number) so the native quote bubble renders where
    # it can be visually confirmed. Sender + quote.author stay the bot, so msg 2
    # still quotes msg 1. Unset => original bot->bot self-send.
    target = os.getenv("LIVE_FIRE_TARGET") or bot_number

    if target == bot_number:
        log.info("Live-fire harness starting — self-send bot->bot to %s", bot_number)
    else:
        log.info(
            "Live-fire harness starting — SC#3 render mode: bot %s -> target %s",
            bot_number,
            target,
        )
    log.info("No /v1/receive poller started (T-57-04-01: no dual-poller hazard).")

    async with httpx.AsyncClient() as http:
        # Import here to avoid circular at module level (scripts sit outside the package)
        from farm_agent.signal_io.client import SignalClient

        client = SignalClient(
            config=config,
            http=http,
            outbound_repo=outbound_repo,
            pool=None,                    # Pool opened below; injected after
            default_target=target,       # bot->bot self-send, or LIVE_FIRE_TARGET override
            tenant_id=config.tenant_id,
        )

        # Open the real pool now (requires event loop to be running)
        pool = await build_pool(config)
        client._pool = pool              # inject after open() per pool.py PITFALL 4

        try:
            # ------------------------------------------------------------------
            # Step 1: plain message (SC#1 baseline)
            # ------------------------------------------------------------------
            log.info("[Step 1] Sending plain message (intent=live_fire_57) ...")
            result1 = await client.send(
                "Phase 57 live-fire: plain message (Step 1 of 2)",
                intent="live_fire_57",
                source_module="live_fire_57",
            )
            if not result1.get("ok"):
                log.error("ABORT: Step 1 send failed: %s", result1)
                sys.exit(1)

            ts1 = result1["timestamp"]
            log.info("[Step 1] SENT  timestamp=%s", ts1)

            # ------------------------------------------------------------------
            # Step 2: quote-threaded message (SC#3 native quote bubble)
            # ------------------------------------------------------------------
            log.info("[Step 2] Sending quote-threaded message (quotes Step 1) ...")
            # quote.timestamp passed as a STRING to exercise int(str(ts)) coercion path
            # (RESEARCH Pitfall 3 / D-05 / SIG-04).
            quote_payload = {
                "timestamp": str(ts1),         # string form -- exercises coercion
                "author": bot_number,
                "message": "round-trip",
            }
            result2 = await client.send(
                "Phase 57 live-fire: quote-threaded message (Step 2 of 2)",
                intent="live_fire_57",
                source_module="live_fire_57",
                quote=quote_payload,
            )
            if not result2.get("ok"):
                log.error("ABORT: Step 2 send failed: %s", result2)
                sys.exit(1)

            ts2 = result2["timestamp"]
            log.info("[Step 2] SENT  timestamp=%s", ts2)

            # ------------------------------------------------------------------
            # Step 3: SELECT + assert signal_msg_ts non-null bigint (SC#1)
            # ------------------------------------------------------------------
            log.info("[Step 3] Querying signal_outbound for both rows ...")
            rows = await _select_live_fire_rows(pool)

            print("\n--- signal_outbound rows (intent='live_fire_57', latest 2) ---")
            print(f"{'id':>6}  {'signal_msg_ts':>15}  {'pg_typeof':>10}  intent")
            print("-" * 60)

            sc1_pass = True
            if not rows:
                log.error("SELECT returned 0 rows -- DB insert may have failed.")
                sc1_pass = False
            for row in rows:
                row_id, sig_ts, pg_type, intent_val = row
                is_ok = sig_ts is not None and isinstance(sig_ts, int) and pg_type == "bigint"
                marker = "OK" if is_ok else "FAIL"
                print(f"{str(row_id):>6}  {str(sig_ts):>15}  {str(pg_type):>10}  {intent_val}  [{marker}]")
                if not is_ok:
                    sc1_pass = False

            print()
            if sc1_pass and len(rows) == 2:
                print("SC#1 PASS: signal_msg_ts is non-null bigint for both rows.")
            else:
                print(f"SC#1 FAIL: expected 2 rows with non-null bigint, got {len(rows)} rows.")
                sys.exit(1)

            print()
            print("SC#3 MANUAL: On the bot's Signal client (+59891840205 device or linked viewer),")
            print("  confirm the SECOND message renders as a NATIVE QUOTE BUBBLE quoting the first.")
            print("  Compare to 50-LIVE-FIRE_ack-quote.jpg. Screenshot and attach to 57-LIVE-FIRE.md.")
            print()
            print("If the quote does NOT render natively (RESEARCH A2 risk on 0.200-dev),")
            print("  capture the /v2/send response payload and flag a shape-drift finding.")

        finally:
            await pool.close()


async def _select_live_fire_rows(pool) -> list:
    """SELECT the 2 most-recent signal_outbound rows for intent='live_fire_57'.

    Returns list of (id, signal_msg_ts, pg_typeof, intent) tuples.
    """
    sql = """
    SELECT id, signal_msg_ts, pg_typeof(signal_msg_ts)::text, intent
    FROM signal_outbound
    WHERE intent = 'live_fire_57'
    ORDER BY sent_at DESC
    LIMIT 2
    """
    try:
        async with pool.connection() as conn:
            cursor = await conn.execute(sql)
            rows = await cursor.fetchall()
        return list(rows)
    except Exception as e:
        log.error("SELECT failed: %s", e)
        return []


if __name__ == "__main__":
    asyncio.run(main())
