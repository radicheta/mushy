"""
persistence/pool.py -- shared psycopg3 async connection pool (FND-03).

Receives TenantConfig by injection (FND-02: config module is the sole env reader).
open=False + await pool.open() is mandatory for async-safe init (PITFALL 4 / RESEARCH FND-03).
options=-c timezone=UTC enforces UTC at connection level (T-56-05-02 mitigation).

psycopg.conninfo.make_conninfo() is used instead of a raw f-string to correctly
quote values containing spaces, backslashes, or single-quotes (libpq connection
string format requires quoting such values -- CR-03 fix).
"""

from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool

from farm_agent.tenancy.tenant import TenantConfig


async def build_pool(config: TenantConfig) -> AsyncConnectionPool:
    """Build and open an AsyncConnectionPool from the injected TenantConfig.

    Pool parameters: min_size=1, max_size=5 (appropriate for single-process
    event-driven alerter; same posture as Node pg.Pool defaults).

    timescale_host may include a port suffix (e.g. "localhost:5434") for
    non-standard-port test environments. When a port is present it is split out
    and placed in the separate 'port' conninfo key so psycopg parses it cleanly.

    Returns an already-opened pool ready for use.
    """
    host = config.timescale_host
    kwargs: dict = dict(
        host=host,
        dbname=config.timescale_db,
        user=config.timescale_user,
        password=config.timescale_password,
        options="-c timezone=UTC",
    )
    if ":" in host:
        host, port_str = host.rsplit(":", 1)
        kwargs["host"] = host
        kwargs["port"] = int(port_str)

    conninfo = make_conninfo(**kwargs)
    pool = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=5,
        open=False,  # REQUIRED: defer open() until event loop is running (PITFALL 4)
    )
    await pool.open()
    return pool
