"""MUSHY-75: prove the recovery pass is wired, without writing anything.

Runs find_transport_parked + recover_transport_parked against the live DB with a
probe that always reports "not found". Nothing is requeued because nothing is
flagged transport yet: pre-existing commit_failed rows have
commit_failed_transport NULL, so validation failures stay parked, which is the
intended default.

  docker exec mushy-alerter-py-1 /app/.venv/bin/python /tmp/mushy75/probe.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, "/app")

import farm_agent.farmos.commit_db as db  # noqa: E402
from farm_agent.farmos.commit_recovery import recover_transport_parked  # noqa: E402
from farm_agent.tenancy.tenant import load as load_config  # noqa: E402


async def _never_found(_name):
    return {"found": False}


async def main() -> None:
    config = load_config(os.environ)
    from psycopg_pool import AsyncConnectionPool

    dsn = (
        f"host={config.timescale_host} dbname={config.timescale_db} "
        f"user={config.timescale_user} password={config.timescale_password}"
    )
    async with AsyncConnectionPool(dsn, open=False) as pool:
        await pool.open()
        parked = await db.find_transport_parked(pool)
        print("transport-parked drafts found :", len(parked))
        n = await recover_transport_parked(pool, _never_found, db, None)
        print("requeued this pass            :", n)
        async with pool.connection() as conn:
            cur = await conn.execute(
                "select count(*) from signal_draft where status='commit_failed'")
            print("validation failures untouched :", (await cur.fetchone())[0])
            cur = await conn.execute(
                "select count(*) from signal_draft where commit_failed_transport is not null")
            print("rows carrying the new flag    :", (await cur.fetchone())[0])


asyncio.run(main())
