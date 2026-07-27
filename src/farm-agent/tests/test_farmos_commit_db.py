"""Tests for commit_db.py (Phase 62-10, Task 2).

Port of commit-db.js behavioral assertions with origin='python' guard.

Tests split into two sections:
  1. DB-independent (always run): never-throws on fake raising pool, SQL
     text inspection via a capture pool, origin guard assertion.
  2. DB-gated (@_requires_db): ephemeral :5434 DB, real SQL round-trips,
     CAS race guard (acquire returns rowcount=0 on dup).

Key invariant: find_confirmed_candidates SELECTs origin='python'
               acquire_commit_lock, mark_committed, requeue_for_retry all SET origin='python'

NEVER uses :5432 (prod). Tests skip gracefully if :5434 is not reachable.
"""
from __future__ import annotations

import json
import os
import socket
import uuid
import datetime

import pytest

# ---------------------------------------------------------------------------
# DB reachability gate
# ---------------------------------------------------------------------------

def _db_reachable() -> bool:
    host = os.environ.get("TEST_TIMESCALE_HOST", "localhost")
    port_str = os.environ.get("TEST_TIMESCALE_PORT", "5434")
    try:
        with socket.create_connection((host, int(port_str)), timeout=2):
            return True
    except OSError:
        return False


_NO_DB_REASON = "no test DB reachable -- start postgres:14 on :5434"
_requires_db = pytest.mark.skipif(not _db_reachable(), reason=_NO_DB_REASON)


# ---------------------------------------------------------------------------
# Fake pools (no DB required)
# ---------------------------------------------------------------------------

class _FakeConn:
    """Psycopg3-shaped connection that records SQL and raises on demand."""
    def __init__(self, should_raise: bool = False, rowcount: int = 0, rows: list | None = None):
        self.should_raise = should_raise
        self._rowcount = rowcount
        self._rows = rows or []
        self.last_sql: str = ""
        self.last_params: tuple = ()

    class _FakeTx:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    def transaction(self):
        return self._FakeTx()

    async def execute(self, sql, params=()):
        self.last_sql = sql
        self.last_params = params
        if self.should_raise:
            raise RuntimeError("simulated DB error")
        self._result = _FakeResult(self._rowcount, self._rows)
        return self._result

    async def fetchall(self):
        return self._rows


class _FakeResult:
    def __init__(self, rowcount: int, rows: list):
        self.rowcount = rowcount
        self._rows = rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return self._rows


class _FakePoolCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_):
        pass


class FakePool:
    """Fake pool whose connection() yields a pre-configured FakeConn."""

    def __init__(self, should_raise: bool = False, rowcount: int = 0, rows: list | None = None):
        self._conn = _FakeConn(should_raise=should_raise, rowcount=rowcount, rows=rows)

    def connection(self):
        return _FakePoolCtx(self._conn)

    @property
    def last_sql(self):
        return self._conn.last_sql

    @property
    def last_params(self):
        return self._conn.last_params


# ---------------------------------------------------------------------------
# DB-independent: never-throws on DB error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_confirmed_candidates_never_throws_on_db_error():
    from farm_agent.farmos.commit_db import find_confirmed_candidates
    pool = FakePool(should_raise=True)
    result = await find_confirmed_candidates(pool)
    assert result == []


@pytest.mark.asyncio
async def test_acquire_commit_lock_never_throws_on_db_error():
    from farm_agent.farmos.commit_db import acquire_commit_lock
    pool = FakePool(should_raise=True)
    result = await acquire_commit_lock(pool, "draft-1")
    assert result["ok"] is False
    assert "reason" in result


@pytest.mark.asyncio
async def test_mark_committed_never_throws_on_db_error():
    from farm_agent.farmos.commit_db import mark_committed
    pool = FakePool(should_raise=True)
    result = await mark_committed(pool, "draft-1", {"some": "response"})
    assert result["ok"] is False
    assert "reason" in result


@pytest.mark.asyncio
async def test_mark_failed_never_throws_on_db_error():
    from farm_agent.farmos.commit_db import mark_failed
    pool = FakePool(should_raise=True)
    result = await mark_failed(pool, "draft-1", "some_reason")
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_requeue_for_retry_never_throws_on_db_error():
    from farm_agent.farmos.commit_db import requeue_for_retry
    pool = FakePool(should_raise=True)
    result = await requeue_for_retry(pool, "draft-1")
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_release_stale_locks_never_throws_on_db_error():
    from farm_agent.farmos.commit_db import release_stale_locks
    pool = FakePool(should_raise=True)
    result = await release_stale_locks(pool, stale_min=15)
    assert result["ok"] is False
    assert result.get("released_ids") == []


# ---------------------------------------------------------------------------
# DB-independent: SQL text contains origin guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_confirmed_candidates_sql_contains_origin_python():
    """find_confirmed_candidates SELECT must filter on origin='python'."""
    from farm_agent.farmos.commit_db import find_confirmed_candidates
    pool = FakePool(rowcount=0, rows=[])
    await find_confirmed_candidates(pool)
    sql = pool.last_sql
    assert "origin='python'" in sql or 'origin = \'python\'' in sql or "origin='python'" in sql.replace(" ", ""), \
        f"find_confirmed_candidates SQL missing origin='python' guard: {sql!r}"


@pytest.mark.asyncio
async def test_find_confirmed_candidates_sql_contains_status_confirmed():
    """find_confirmed_candidates SELECT must filter on status='confirmed'."""
    from farm_agent.farmos.commit_db import find_confirmed_candidates
    pool = FakePool(rowcount=0, rows=[])
    await find_confirmed_candidates(pool)
    sql = pool.last_sql
    assert "status='confirmed'" in sql or "status = 'confirmed'" in sql, \
        f"find_confirmed_candidates SQL missing status='confirmed': {sql!r}"


@pytest.mark.asyncio
async def test_acquire_commit_lock_sql_sets_origin_python():
    """acquire_commit_lock UPDATE must SET origin='python'."""
    from farm_agent.farmos.commit_db import acquire_commit_lock
    pool = FakePool(rowcount=1, rows=[("draft-id",)])
    await acquire_commit_lock(pool, "draft-1")
    sql = pool.last_sql
    assert "origin='python'" in sql or "origin = 'python'" in sql, \
        f"acquire_commit_lock SQL missing origin='python': {sql!r}"


@pytest.mark.asyncio
async def test_mark_committed_sql_sets_origin_python():
    """mark_committed UPDATE must SET origin='python'."""
    from farm_agent.farmos.commit_db import mark_committed
    pool = FakePool(rowcount=1)
    await mark_committed(pool, "draft-1", {"ok": True})
    sql = pool.last_sql
    assert "origin='python'" in sql or "origin = 'python'" in sql, \
        f"mark_committed SQL missing origin='python': {sql!r}"


@pytest.mark.asyncio
async def test_requeue_for_retry_sql_sets_origin_python():
    """requeue_for_retry UPDATE must SET origin='python'."""
    from farm_agent.farmos.commit_db import requeue_for_retry
    pool = FakePool(rowcount=1)
    await requeue_for_retry(pool, "draft-1")
    sql = pool.last_sql
    assert "origin='python'" in sql or "origin = 'python'" in sql, \
        f"requeue_for_retry SQL missing origin='python': {sql!r}"


# ---------------------------------------------------------------------------
# DB-independent: return shapes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_commit_lock_returns_rowcount():
    from farm_agent.farmos.commit_db import acquire_commit_lock
    pool = FakePool(rowcount=1, rows=[("draft-id",)])
    result = await acquire_commit_lock(pool, "draft-1")
    assert result["ok"] is True
    assert result["rowcount"] == 1


@pytest.mark.asyncio
async def test_acquire_commit_lock_race_lost_rowcount_zero():
    """Second acquire on the same draft returns rowcount=0 (CAS collapsed)."""
    from farm_agent.farmos.commit_db import acquire_commit_lock
    pool = FakePool(rowcount=0, rows=[])
    result = await acquire_commit_lock(pool, "draft-1")
    assert result["ok"] is True
    assert result["rowcount"] == 0


@pytest.mark.asyncio
async def test_mark_committed_rowcount():
    from farm_agent.farmos.commit_db import mark_committed
    pool = FakePool(rowcount=1)
    result = await mark_committed(pool, "draft-1", {"ok": True})
    assert result["ok"] is True
    assert result["rowcount"] == 1


@pytest.mark.asyncio
async def test_mark_committed_cas_not_committing_rowcount_zero():
    """mark_committed WHERE status='committing': rowcount=0 when already committed."""
    from farm_agent.farmos.commit_db import mark_committed
    pool = FakePool(rowcount=0)
    result = await mark_committed(pool, "draft-1", None)
    assert result["ok"] is True
    assert result["rowcount"] == 0


@pytest.mark.asyncio
async def test_mark_failed_rowcount():
    from farm_agent.farmos.commit_db import mark_failed
    pool = FakePool(rowcount=1)
    result = await mark_failed(pool, "draft-1", "some error")
    assert result["ok"] is True
    assert result["rowcount"] == 1


@pytest.mark.asyncio
async def test_release_stale_locks_returns_released_ids():
    from farm_agent.farmos.commit_db import release_stale_locks
    pool = FakePool(rowcount=2, rows=[("id-1",), ("id-2",)])
    result = await release_stale_locks(pool, stale_min=15)
    assert result["ok"] is True
    assert set(result["released_ids"]) == {"id-1", "id-2"}


# ---------------------------------------------------------------------------
# DB-gated: real SQL round-trips on ephemeral :5434
# ---------------------------------------------------------------------------

@_requires_db
@pytest.mark.asyncio
async def test_db_find_confirmed_candidates_only_returns_python_rows(pool):
    """Only rows with origin='python' + status='confirmed' are returned."""
    from farm_agent.farmos.commit_db import find_confirmed_candidates

    async with pool.connection() as conn:
        async with conn.transaction():
            # Insert a python-origin confirmed row
            py_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO signal_draft (id, status, origin, sender_e164, draft_json, log_type,
                                          farmer_facing_preview, confirmed_at, created_at, updated_at)
                VALUES (%s, 'confirmed', 'python', '+1test', '{}'::jsonb, 'observation',
                        'test', NOW(), NOW(), NOW())
                """,
                (py_id,),
            )
            # Insert a node-origin confirmed row (should NOT appear)
            node_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO signal_draft (id, status, origin, sender_e164, draft_json, log_type,
                                          farmer_facing_preview, confirmed_at, created_at, updated_at)
                VALUES (%s, 'confirmed', 'node', '+1test', '{}'::jsonb, 'observation',
                        'test', NOW(), NOW(), NOW())
                """,
                (node_id,),
            )

    try:
        rows = await find_confirmed_candidates(pool, batch_cap=100)
        ids = [r["id"] for r in rows]
        assert py_id in ids, "python-origin row not returned"
        assert node_id not in ids, "node-origin row should NOT be returned by Python side"
    finally:
        async with pool.connection() as conn:
            await conn.execute(
                "DELETE FROM signal_draft WHERE id = ANY(%s)", ([py_id, node_id],)
            )


@_requires_db
@pytest.mark.asyncio
async def test_db_acquire_commit_lock_cas_race(pool):
    """Second acquire_commit_lock on same row returns rowcount=0 (CAS guard)."""
    from farm_agent.farmos.commit_db import acquire_commit_lock

    draft_id = str(uuid.uuid4())
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO signal_draft (id, status, origin, sender_e164, draft_json, log_type,
                                      farmer_facing_preview, confirmed_at, created_at, updated_at)
            VALUES (%s, 'confirmed', 'python', '+1test', '{}'::jsonb, 'observation',
                    'test', NOW(), NOW(), NOW())
            """,
            (draft_id,),
        )

    try:
        # First acquire should win
        r1 = await acquire_commit_lock(pool, draft_id)
        assert r1["ok"] is True
        assert r1["rowcount"] == 1

        # Second acquire must lose (row is now 'committing')
        r2 = await acquire_commit_lock(pool, draft_id)
        assert r2["ok"] is True
        assert r2["rowcount"] == 0
    finally:
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM signal_draft WHERE id = %s", (draft_id,))


@_requires_db
@pytest.mark.asyncio
async def test_db_mark_committed_sets_status(pool):
    """mark_committed transitions status to 'committed' with farmos_response."""
    from farm_agent.farmos.commit_db import acquire_commit_lock, mark_committed

    draft_id = str(uuid.uuid4())
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO signal_draft (id, status, origin, sender_e164, draft_json, log_type,
                                      farmer_facing_preview, confirmed_at, created_at, updated_at)
            VALUES (%s, 'confirmed', 'python', '+1test', '{}'::jsonb, 'observation',
                    'test', NOW(), NOW(), NOW())
            """,
            (draft_id,),
        )

    try:
        await acquire_commit_lock(pool, draft_id)
        r = await mark_committed(pool, draft_id, {"asset_ids": ["a1"]})
        assert r["ok"] is True
        assert r["rowcount"] == 1

        # Verify status in DB
        async with pool.connection() as conn:
            result = await conn.execute(
                "SELECT status, farmos_response FROM signal_draft WHERE id = %s", (draft_id,)
            )
            row = await result.fetchone()
        assert row[0] == "committed"
        assert row[1] is not None  # farmos_response stored
    finally:
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM signal_draft WHERE id = %s", (draft_id,))


@_requires_db
@pytest.mark.asyncio
async def test_db_mark_failed_sets_status(pool):
    """mark_failed transitions status to 'commit_failed'."""
    from farm_agent.farmos.commit_db import acquire_commit_lock, mark_failed

    draft_id = str(uuid.uuid4())
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO signal_draft (id, status, origin, sender_e164, draft_json, log_type,
                                      farmer_facing_preview, confirmed_at, created_at, updated_at)
            VALUES (%s, 'confirmed', 'python', '+1test', '{}'::jsonb, 'observation',
                    'test', NOW(), NOW(), NOW())
            """,
            (draft_id,),
        )

    try:
        await acquire_commit_lock(pool, draft_id)
        r = await mark_failed(pool, draft_id, "farmOS 500")
        assert r["ok"] is True
        assert r["rowcount"] == 1

        async with pool.connection() as conn:
            result = await conn.execute(
                "SELECT status, commit_failed_reason FROM signal_draft WHERE id = %s", (draft_id,)
            )
            row = await result.fetchone()
        assert row[0] == "commit_failed"
        assert row[1] == "farmOS 500"
    finally:
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM signal_draft WHERE id = %s", (draft_id,))


@_requires_db
@pytest.mark.asyncio
async def test_db_requeue_for_retry_sets_origin_python(pool):
    """requeue_for_retry sets status='confirmed' AND origin='python'."""
    from farm_agent.farmos.commit_db import acquire_commit_lock, requeue_for_retry

    draft_id = str(uuid.uuid4())
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO signal_draft (id, status, origin, sender_e164, draft_json, log_type,
                                      farmer_facing_preview, confirmed_at, created_at, updated_at)
            VALUES (%s, 'confirmed', 'python', '+1test', '{}'::jsonb, 'observation',
                    'test', NOW(), NOW(), NOW())
            """,
            (draft_id,),
        )

    try:
        await acquire_commit_lock(pool, draft_id)  # -> 'committing'
        r = await requeue_for_retry(pool, draft_id)
        assert r["ok"] is True
        assert r["rowcount"] == 1

        async with pool.connection() as conn:
            result = await conn.execute(
                "SELECT status, origin FROM signal_draft WHERE id = %s", (draft_id,)
            )
            row = await result.fetchone()
        assert row[0] == "confirmed"
        assert row[1] == "python"
    finally:
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM signal_draft WHERE id = %s", (draft_id,))


@_requires_db
@pytest.mark.asyncio
async def test_db_release_stale_locks(pool):
    """release_stale_locks reclaims locks older than stale_min."""
    from farm_agent.farmos.commit_db import release_stale_locks

    draft_id = str(uuid.uuid4())
    # Insert a row that's already 'committing' with a very old committed_at_attempt
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO signal_draft (id, status, origin, sender_e164, draft_json, log_type,
                                      farmer_facing_preview, confirmed_at, committed_at_attempt,
                                      created_at, updated_at)
            VALUES (%s, 'committing', 'python', '+1test', '{}'::jsonb, 'observation',
                    'test', NOW(), NOW() - INTERVAL '60 minutes', NOW(), NOW())
            """,
            (draft_id,),
        )

    try:
        r = await release_stale_locks(pool, stale_min=30)
        assert r["ok"] is True
        assert draft_id in r["released_ids"]
    finally:
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM signal_draft WHERE id = %s", (draft_id,))
