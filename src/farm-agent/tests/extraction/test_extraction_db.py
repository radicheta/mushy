"""DAO tests for signal_draft. Port parity: extraction-db.js."""

import hashlib

from farm_agent.extraction import extraction_db as db


def test_compute_draft_id_matches_node_single():
    # Node: sha256(sorted(ids).join('|')); index 0 and None are NOT suffixed.
    ids = ["01JB", "01JA"]
    expected = hashlib.sha256("01JA|01JB".encode()).hexdigest()
    assert db.compute_draft_id(ids) == expected
    assert db.compute_draft_id(ids, 0) == expected


def test_compute_draft_id_indexed_is_suffixed():
    ids = ["01JA"]
    expected = hashlib.sha256("01JA#2".encode()).hexdigest()
    assert db.compute_draft_id(ids, 2) == expected


def test_compute_draft_id_does_not_mutate_input():
    ids = ["c", "a", "b"]
    db.compute_draft_id(ids)
    assert ids == ["c", "a", "b"]


class FakePool:
    """Minimal async pool double: records executed SQL, optionally raises."""

    def __init__(self, raises=None, rowcount=1, rows=None):
        self.raises = raises
        self.rowcount = rowcount
        self.rows = rows if rows is not None else []
        self.calls = []

    def connection(self):
        return _FakeConnCtx(self)


class _FakeConnCtx:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        return _FakeConn(self.pool)

    async def __aexit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, pool):
        self.pool = pool

    async def execute(self, sql, params=None):
        self.pool.calls.append((sql, params))
        if self.pool.raises is not None:
            raise self.pool.raises
        return _FakeCursor(self.pool)


class _FakeCursor:
    def __init__(self, pool):
        self.rowcount = pool.rowcount
        self._rows = pool.rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return self._rows


class FakeUniqueViolation(Exception):
    sqlstate = "23505"


async def test_insert_draft_stamps_origin_python():
    pool = FakePool()
    res = await db.insert_draft(pool, {
        "id": "d1", "sender_e164": "+100", "source_capture_ids": ["c1"],
        "status": "pending", "draft_json": {"type": "harvest"},
    })
    assert res["ok"] is True
    sql, params = pool.calls[0]
    assert "origin" in sql
    assert "python" in params


async def test_insert_draft_in_flight_conflict_on_23505():
    pool = FakePool(raises=FakeUniqueViolation())
    res = await db.insert_draft(pool, {
        "id": "d1", "sender_e164": "+100", "source_capture_ids": ["c1"], "status": "pending",
    })
    assert res == {"ok": False, "reason": "in_flight_conflict"}


async def test_insert_draft_other_error_returns_reason():
    pool = FakePool(raises=RuntimeError("boom"))
    res = await db.insert_draft(pool, {
        "id": "d1", "sender_e164": "+100", "source_capture_ids": ["c1"], "status": "pending",
    })
    assert res["ok"] is False
    assert res["reason"] == "boom"


async def test_update_draft_status_ignores_unwhitelisted_keys():
    pool = FakePool()
    res = await db.update_draft_status(pool, "d1", "needs_review", {
        "needs_review_reason": "askback_cap_exceeded",
        "status; DROP TABLE signal_draft": "evil",
        "origin": "node",
    })
    assert res["ok"] is True
    sql, params = pool.calls[0]
    assert "needs_review_reason" in sql
    assert "DROP TABLE" not in sql
    assert "origin" not in sql.split("SET", 1)[1].split("WHERE", 1)[0]
    assert "node" not in params


async def test_get_in_flight_for_sender_returns_row():
    row = {"id": "d1", "status": "pending"}
    pool = FakePool(rows=[row])
    res = await db.get_in_flight_for_sender(pool, "+100")
    assert res == row


async def test_get_in_flight_for_sender_returns_none_when_absent():
    pool = FakePool(rows=[])
    res = await db.get_in_flight_for_sender(pool, "+100")
    assert res is None


async def test_get_in_flight_for_sender_returns_none_on_error():
    pool = FakePool(raises=RuntimeError("boom"))
    res = await db.get_in_flight_for_sender(pool, "+100")
    assert res is None


async def test_advance_askback_turn_returns_new_value():
    pool = FakePool(rows=[{"askback_turns": 3}])
    res = await db.advance_askback_turn(pool, "d1")
    assert res == {"ok": True, "askback_turns": 3}


async def test_advance_askback_turn_error_returns_reason():
    pool = FakePool(raises=RuntimeError("boom"))
    res = await db.advance_askback_turn(pool, "d1")
    assert res == {"ok": False, "reason": "boom"}


async def test_expire_idle_returns_rowcount():
    pool = FakePool(rowcount=2)
    res = await db.expire_idle(pool, 30)
    assert res == {"ok": True, "rowcount": 2}


async def test_expire_idle_error_returns_reason():
    pool = FakePool(raises=RuntimeError("boom"))
    res = await db.expire_idle(pool, 30)
    assert res == {"ok": False, "reason": "boom"}


async def test_get_drafts_for_capture_returns_rows():
    rows = [{"id": "d1"}, {"id": "d2"}]
    pool = FakePool(rows=rows)
    res = await db.get_drafts_for_capture(pool, "c1")
    assert res == rows


async def test_get_drafts_for_capture_returns_empty_on_error():
    pool = FakePool(raises=RuntimeError("boom"))
    res = await db.get_drafts_for_capture(pool, "c1")
    assert res == []


async def test_get_draft_by_id_returns_row():
    row = {"id": "d1"}
    pool = FakePool(rows=[row])
    res = await db.get_draft_by_id(pool, "d1")
    assert res == row


async def test_get_draft_by_id_returns_none_on_error():
    pool = FakePool(raises=RuntimeError("boom"))
    res = await db.get_draft_by_id(pool, "d1")
    assert res is None
