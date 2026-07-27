"""
test_persistence.py -- FND-03 integration tests for pool.py + migrations.py.

DB-dependent tests (test_pool_roundtrip, test_migrations_idempotent,
test_migrations_create_expected_tables) are skipped when no test DB is
reachable; they require a Postgres on TEST_TIMESCALE_HOST:5432 (default
localhost:5434 via the conftest TEST_ENV, overridable via TEST_TIMESCALE_*
env vars).

test_migrations_additive_only is a PURE SOURCE GREP -- DB-independent.
It MUST ALWAYS run and pass. It protects the shared live Node TimescaleDB
from destructive DDL (T-56-05-01).
"""

import os
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MIGRATIONS_SRC = (
    Path(__file__).parent.parent / "farm_agent" / "persistence" / "migrations.py"
)

# Whitelist: the two known text->text no-op ALTER COLUMN TYPE statements
# ported verbatim from outbound-db.js (RESEARCH FND-03 / PITFALL 3).
_WHITELISTED_ALTER_TYPE_RE = re.compile(
    r"ALTER\s+COLUMN\s+(related_capture_id|related_draft_id)\s+TYPE\s+text",
    re.IGNORECASE,
)


def _db_reachable() -> bool:
    """True when the throwaway test postgres on TEST_TIMESCALE_PORT can be TCP-connected to.

    Default port is 5434 (the throwaway postgres:14 container), NOT 5432
    (which may be a production postgres on this host -- we never want to
    accidentally run migrations against prod).
    """
    import socket
    host = os.environ.get("TEST_TIMESCALE_HOST", "localhost")
    port_str = os.environ.get("TEST_TIMESCALE_PORT", "5434")
    try:
        with socket.create_connection((host, int(port_str)), timeout=2):
            return True
    except OSError:
        return False


_NO_DB_REASON = "no test DB reachable -- set TEST_TIMESCALE_HOST/TEST_TIMESCALE_PORT or start postgres:14 on :5434"
_requires_db = pytest.mark.skipif(not _db_reachable(), reason=_NO_DB_REASON)

# ---------------------------------------------------------------------------
# CR-03: make_conninfo correctly quotes special-character passwords (DB-independent)
# ---------------------------------------------------------------------------


def test_make_conninfo_quotes_special_password():
    """make_conninfo() correctly quotes passwords with spaces or backslashes.

    A raw f-string 'password=p@ss w0rd' becomes password=p@ss with unknown
    keyword w0rd. psycopg.conninfo.make_conninfo(**kwargs) handles quoting.
    """
    from psycopg.conninfo import make_conninfo  # noqa: PLC0415

    # Password with a space -- would break a raw f-string conninfo
    result = make_conninfo(
        host="localhost",
        dbname="testdb",
        user="testuser",
        password="p@ss w0rd",
    )
    # libpq quoting: value with space is wrapped in single quotes
    assert "password='p@ss w0rd'" in result, (
        f"Expected quoted password in conninfo, got: {result!r}"
    )

    # Password with a backslash
    result2 = make_conninfo(
        host="localhost",
        dbname="testdb",
        user="testuser",
        password="p@ss\\w0rd",
    )
    # Backslash must be escaped or quoted; either way must be parseable
    assert "password=" in result2, f"conninfo missing password key: {result2!r}"


# ---------------------------------------------------------------------------
# Task 1: pool roundtrip
# ---------------------------------------------------------------------------


@_requires_db
async def test_pool_roundtrip(pool):
    """SELECT 1 roundtrip through the async pool returns 1; timezone is UTC."""
    async with pool.connection() as conn:
        row = await conn.execute("SELECT 1")
        result = await row.fetchone()
        assert result[0] == 1, "SELECT 1 must return 1"

        tz_row = await conn.execute("SHOW timezone")
        tz = (await tz_row.fetchone())[0]
        assert tz.upper() == "UTC", f"connection timezone must be UTC, got {tz!r}"


# ---------------------------------------------------------------------------
# Task 2: idempotent migrations
# ---------------------------------------------------------------------------


@_requires_db
async def test_migrations_idempotent(pool):
    """Running run_migrations twice raises no error and changes nothing."""
    from farm_agent.persistence.migrations import run_migrations  # noqa: PLC0415

    # First run already happened in conftest (pool fixture calls run_migrations).
    # Run again -- must be a no-op.
    await run_migrations(pool)


@_requires_db
async def test_migrations_create_expected_tables(pool):
    """Three live tables + pgcrypto extension + v_llm_cost_daily view exist after migration.

    Spot-checks representative column types to guard against column-type drift.
    """
    async with pool.connection() as conn:
        # --- Tables exist ---
        tables_row = await conn.execute(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename IN (
                'signal_capture','signal_draft','signal_outbound','signal_draft_event'
              )
            ORDER BY tablename
            """
        )
        tables = {r[0] for r in await tables_row.fetchall()}
        assert tables == {
            "signal_capture",
            "signal_draft",
            "signal_draft_event",
            "signal_outbound",
        }, f"Expected four tables, got {tables}"

        # --- pgcrypto extension ---
        ext_row = await conn.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'pgcrypto'"
        )
        exts = [r[0] for r in await ext_row.fetchall()]
        assert "pgcrypto" in exts, "pgcrypto extension must be present"

        # --- v_llm_cost_daily view ---
        view_row = await conn.execute(
            "SELECT viewname FROM pg_views WHERE viewname = 'v_llm_cost_daily'"
        )
        views = [r[0] for r in await view_row.fetchall()]
        assert "v_llm_cost_daily" in views, "v_llm_cost_daily view must exist"

        # --- Representative column types ---
        # signal_capture.id must be text (ULID)
        col_row = await conn.execute(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name='signal_capture' AND column_name='id'
            """
        )
        sc_id_type = (await col_row.fetchone())[0]
        assert sc_id_type == "text", f"signal_capture.id must be text, got {sc_id_type!r}"

        # signal_draft.id must be text (hex SHA-256)
        col_row = await conn.execute(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name='signal_draft' AND column_name='id'
            """
        )
        sd_id_type = (await col_row.fetchone())[0]
        assert sd_id_type == "text", f"signal_draft.id must be text, got {sd_id_type!r}"

        # signal_outbound.id must be uuid (gen_random_uuid)
        col_row = await conn.execute(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name='signal_outbound' AND column_name='id'
            """
        )
        so_id_type = (await col_row.fetchone())[0]
        assert so_id_type == "uuid", f"signal_outbound.id must be uuid, got {so_id_type!r}"

        # signal_outbound.related_capture_id must be text (NOT uuid -- hotfix)
        col_row = await conn.execute(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name='signal_outbound' AND column_name='related_capture_id'
            """
        )
        rci_type = (await col_row.fetchone())[0]
        assert rci_type == "text", (
            f"signal_outbound.related_capture_id must be text (hotfix), got {rci_type!r}"
        )

        # signal_outbound.related_draft_id must be text (NOT uuid -- hotfix)
        col_row = await conn.execute(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name='signal_outbound' AND column_name='related_draft_id'
            """
        )
        rdi_type = (await col_row.fetchone())[0]
        assert rdi_type == "text", (
            f"signal_outbound.related_draft_id must be text (hotfix), got {rdi_type!r}"
        )

        # signal_capture.signal_msg_ts must be bigint (Phase 50)
        col_row = await conn.execute(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name='signal_capture' AND column_name='signal_msg_ts'
            """
        )
        smt_type = (await col_row.fetchone())[0]
        assert smt_type == "bigint", (
            f"signal_capture.signal_msg_ts must be bigint, got {smt_type!r}"
        )


# ---------------------------------------------------------------------------
# Task 2: additive-only source guard (DB-INDEPENDENT -- MUST ALWAYS RUN)
# ---------------------------------------------------------------------------


def test_migrations_additive_only():
    """Source-level guard: migrations.py contains no destructive DDL.

    Asserts that the SQL strings executed by migrations.py contain:
    - No DROP statements
    - No TRUNCATE statements
    - No ALTER COLUMN ... TYPE other than the two whitelisted text->text no-ops
      (related_capture_id / related_draft_id on signal_outbound, ported verbatim
      from outbound-db.js as idempotent compat for hosts that ran the old uuid schema)

    This test is DB-INDEPENDENT and MUST NEVER be marked skipif. It runs in CI
    even when no Postgres is reachable. Failure = destructive DDL slipped in and
    would break the live Node alerter reading the shared TimescaleDB (T-56-05-01).

    Implementation: we extract only the actual SQL strings passed to conn.execute()
    by looking at string literal lines (lines inside triple-quoted strings or
    single-quoted strings passed to conn.execute). We skip pure Python comment /
    docstring lines that describe what the code does.
    """
    import ast  # noqa: PLC0415

    assert _MIGRATIONS_SRC.exists(), f"migrations.py not found at {_MIGRATIONS_SRC}"
    src = _MIGRATIONS_SRC.read_text()

    # Parse the AST and collect all string literals in the source.
    # String literals in function calls to conn.execute() are the SQL statements.
    # Python docstrings are also string literals, but they appear as the first
    # expression of a function/module body. We exclude those by walking Call nodes.
    tree = ast.parse(src)

    # Collect all string constants that are arguments to conn.execute() calls.
    sql_strings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # Match conn.execute(...) or any *.execute(...) call
            is_execute = (
                isinstance(func, ast.Attribute) and func.attr == "execute"
            )
            if is_execute:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        sql_strings.append(arg.value)

    assert sql_strings, "No SQL strings found in migrations.py -- check conn.execute() calls"

    all_sql = "\n".join(sql_strings)

    # --- No DROP (any form) in SQL ---
    drop_matches = [
        s.strip()
        for s in re.findall(r"[^\n]*\bDROP\b[^\n]*", all_sql, re.IGNORECASE)
    ]
    assert not drop_matches, (
        f"migrations.py SQL contains DROP statements (forbidden -- additive-only): {drop_matches}"
    )

    # --- No TRUNCATE in SQL ---
    trunc_matches = [
        s.strip()
        for s in re.findall(r"[^\n]*\bTRUNCATE\b[^\n]*", all_sql, re.IGNORECASE)
    ]
    assert not trunc_matches, (
        f"migrations.py SQL contains TRUNCATE statements (forbidden): {trunc_matches}"
    )

    # --- No ALTER COLUMN ... TYPE except the two whitelisted text->text no-ops ---
    alter_type_lines = [
        s.strip()
        for s in re.findall(
            r"[^\n]*ALTER\s+COLUMN\s+\w+\s+TYPE[^\n]*", all_sql, re.IGNORECASE
        )
    ]
    non_whitelisted = [
        line for line in alter_type_lines
        if not _WHITELISTED_ALTER_TYPE_RE.search(line)
    ]
    assert not non_whitelisted, (
        f"migrations.py SQL contains non-whitelisted ALTER COLUMN ... TYPE statements: "
        f"{non_whitelisted}. Only the two text->text no-op hotfixes for "
        f"signal_outbound.related_capture_id and related_draft_id are allowed."
    )
