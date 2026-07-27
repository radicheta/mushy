"""
test_signal_persist.py -- Tests for farm_agent.persistence.outbound_repo AND
  SignalClient fail-open persist hook (SIG-02, SC#1).

Part 1 (DB-independent): outbound_repo try/except wrapper -- swallows exceptions.
Part 2 (DB-gated): real INSERT writes all 11 columns; signal_msg_ts roundtrips as int (bigint).
Part 3 (DB-independent): SignalClient fail-open hook -- raising repo never affects send.
Part 4 (DB-independent): SignalClient persist row shape -- signal_msg_ts is int, tz-aware sent_at.
"""

import datetime
import os
import socket

import httpx
import pytest
import pytest_asyncio

from tests.conftest import TEST_ENV, FakeOutboundRepo


# ---------------------------------------------------------------------------
# DB reachability gate (mirrors test_persistence.py pattern)
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
# Helpers
# ---------------------------------------------------------------------------

def _row(**overrides):
    """Minimal valid outbound row with test defaults."""
    base = {
        "tenant_id": "test",
        "sent_at": datetime.datetime.now(tz=datetime.timezone.utc),
        "recipient_e164": "+10000000001",
        "intent": "test_intent",
        "body": "hello",
        "attachments": None,
        "source_module": "signal_io",
        "source_line": None,
        "related_capture_id": None,
        "related_draft_id": None,
        "signal_msg_ts": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Part 1: DB-independent -- outbound_repo fail-open
# ---------------------------------------------------------------------------


class FakeRaisingPool:
    """Fake pool whose .connection() raises on enter (simulates DB error)."""

    class _FakeConn:
        async def execute(self, *_a, **_kw):
            raise RuntimeError("simulated DB error")

    class _AsyncCtx:
        async def __aenter__(self):
            return FakeRaisingPool._FakeConn()

        async def __aexit__(self, *_a):
            pass

    def connection(self):
        return self._AsyncCtx()


@pytest.mark.asyncio
async def test_insert_outbound_fail_open_never_throws():
    """Fail-open: any exception from pool is caught, returns {ok:false, reason:...}."""
    from farm_agent.persistence.outbound_repo import insert_outbound  # noqa: PLC0415

    result = await insert_outbound(FakeRaisingPool(), _row())
    assert result["ok"] is False
    assert "reason" in result
    assert isinstance(result["reason"], str)
    assert len(result["reason"]) > 0


@pytest.mark.asyncio
async def test_insert_outbound_result_is_dict_not_exception():
    """insert_outbound never propagates exceptions — always returns a dict."""
    from farm_agent.persistence.outbound_repo import insert_outbound  # noqa: PLC0415

    result = await insert_outbound(FakeRaisingPool(), _row())
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Part 2: DB-gated -- real INSERT and column contract
# ---------------------------------------------------------------------------


@_requires_db
@pytest.mark.asyncio
async def test_insert_outbound_success(pool):
    """insert_outbound returns {ok:True} on successful insert."""
    from farm_agent.persistence.outbound_repo import insert_outbound  # noqa: PLC0415

    result = await insert_outbound(pool, _row())
    assert result == {"ok": True}


@_requires_db
@pytest.mark.asyncio
async def test_insert_outbound_signal_msg_ts_roundtrips_as_int(pool):
    """signal_msg_ts stored as bigint roundtrips as int, not float."""
    from farm_agent.persistence.outbound_repo import insert_outbound  # noqa: PLC0415

    ts = 1700000000123  # ms-since-epoch; a large int
    row = _row(signal_msg_ts=ts, recipient_e164="+10000000002")
    result = await insert_outbound(pool, row)
    assert result == {"ok": True}

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT signal_msg_ts FROM signal_outbound WHERE recipient_e164 = %s ORDER BY sent_at DESC LIMIT 1",
            ("+10000000002",),
        )
        fetched = await cur.fetchone()

    assert fetched is not None
    stored_ts = fetched[0]
    assert isinstance(stored_ts, int), f"Expected int, got {type(stored_ts)}: {stored_ts!r}"
    assert stored_ts == ts


@_requires_db
@pytest.mark.asyncio
async def test_insert_outbound_group_recipient(pool):
    """group:<id> form in recipient_e164 inserts cleanly."""
    from farm_agent.persistence.outbound_repo import insert_outbound  # noqa: PLC0415

    result = await insert_outbound(pool, _row(recipient_e164="group:abc123base64=="))
    assert result == {"ok": True}


@_requires_db
@pytest.mark.asyncio
async def test_insert_outbound_omit_signal_msg_ts_stores_null(pool):
    """Omitting signal_msg_ts (or None) stores NULL in the DB."""
    from farm_agent.persistence.outbound_repo import insert_outbound  # noqa: PLC0415

    sentinel_e164 = "+10000000003"
    result = await insert_outbound(pool, _row(recipient_e164=sentinel_e164, signal_msg_ts=None))
    assert result == {"ok": True}

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT signal_msg_ts FROM signal_outbound WHERE recipient_e164 = %s ORDER BY sent_at DESC LIMIT 1",
            (sentinel_e164,),
        )
        fetched = await cur.fetchone()

    assert fetched is not None
    assert fetched[0] is None


@_requires_db
@pytest.mark.asyncio
async def test_insert_outbound_default_source_module(pool):
    """Omitting source_module defaults to 'signal_io' (column is NOT NULL)."""
    from farm_agent.persistence.outbound_repo import insert_outbound  # noqa: PLC0415

    sentinel_e164 = "+10000000004"
    row = _row(recipient_e164=sentinel_e164)
    del row["source_module"]  # must default to "signal_io"

    result = await insert_outbound(pool, row)
    assert result == {"ok": True}

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT source_module FROM signal_outbound WHERE recipient_e164 = %s ORDER BY sent_at DESC LIMIT 1",
            (sentinel_e164,),
        )
        fetched = await cur.fetchone()

    assert fetched is not None
    assert fetched[0] == "signal_io"


# ---------------------------------------------------------------------------
# Part 3: SignalClient fail-open hook -- raising repo never affects send (SIG-02)
# ---------------------------------------------------------------------------


async def test_send_raising_repo_still_returns_ok(respx_mock):
    """FakeOutboundRepo that raises: send() still returns {"ok": True}."""
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "1234567890"})
    )

    config = load_config(TEST_ENV)
    repo = FakeOutboundRepo(should_raise=True)
    client = SignalClient(
        config=config,
        http=httpx.AsyncClient(),
        outbound_repo=repo,
        pool=object(),   # non-None placeholder
        default_target="+10000000001",
    )
    async with client.http:
        result = await client.send("test body", intent="test")

    assert result["ok"] is True
    # Repo was called (1 call attempted)
    assert len(repo.calls) == 1


async def test_send_raising_repo_logs_warn(respx_mock, caplog):
    """Raising repo causes a warning log, not an exception."""
    import logging
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "999"})
    )

    config = load_config(TEST_ENV)
    repo = FakeOutboundRepo(should_raise=True)
    client = SignalClient(
        config=config,
        http=httpx.AsyncClient(),
        outbound_repo=repo,
        pool=object(),
        default_target="+10000000001",
    )
    async with client.http:
        with caplog.at_level(logging.WARNING):
            await client.send("body", intent="test")

    assert any("fail-open" in r.message.lower() or "persist" in r.message.lower()
               for r in caplog.records)


# ---------------------------------------------------------------------------
# Part 4: Persist row shape (SC#1) -- signal_msg_ts is int, sent_at tz-aware
# ---------------------------------------------------------------------------


async def test_send_persist_signal_msg_ts_is_int(respx_mock):
    """On successful send, persist hook called with signal_msg_ts == int(response ts), not float."""
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    ts_str = "1779562666675"
    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": ts_str})
    )

    config = load_config(TEST_ENV)
    repo = FakeOutboundRepo()
    client = SignalClient(
        config=config,
        http=httpx.AsyncClient(),
        outbound_repo=repo,
        pool=object(),
        default_target="+10000000001",
    )
    async with client.http:
        await client.send("hi", intent="test")

    assert len(repo.calls) == 1
    row = repo.calls[0]
    assert isinstance(row["signal_msg_ts"], int)
    assert row["signal_msg_ts"] == int(ts_str)
    # must NOT be a float
    assert not isinstance(row["signal_msg_ts"], float)


async def test_send_persist_recipient_e164_is_string_target(respx_mock):
    """String target send: recipient_e164 in row is the +e164 phone number."""
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "111"})
    )

    config = load_config(TEST_ENV)
    repo = FakeOutboundRepo()
    client = SignalClient(
        config=config,
        http=httpx.AsyncClient(),
        outbound_repo=repo,
        pool=object(),
        default_target="+10000000001",
    )
    async with client.http:
        await client.send("body", to="+19995550001", intent="test")

    row = repo.calls[0]
    assert row["recipient_e164"] == "+19995550001"


async def test_send_persist_sent_at_is_tz_aware(respx_mock):
    """sent_at in the persist row is a timezone-aware UTC datetime."""
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "222"})
    )

    config = load_config(TEST_ENV)
    repo = FakeOutboundRepo()
    client = SignalClient(
        config=config,
        http=httpx.AsyncClient(),
        outbound_repo=repo,
        pool=object(),
        default_target="+10000000001",
    )
    async with client.http:
        await client.send("body", intent="test")

    row = repo.calls[0]
    sent_at = row["sent_at"]
    assert isinstance(sent_at, datetime.datetime)
    assert sent_at.tzinfo is not None   # must be tz-aware (PITFALLS #7)


async def test_send_persist_group_recipient_path_b_encoding(respx_mock):
    """Group send: recipient_e164 is 'group:<resolved_id-b64>' (path-b encoding)."""
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    group_id = "IIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIII=="
    respx_mock.get("http://signal-cli:8080/v1/groups/%2B10000000000").mock(
        return_value=httpx.Response(200, json=[])  # no translation, pass-through
    )
    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "333"})
    )

    config = load_config(TEST_ENV)
    repo = FakeOutboundRepo()
    client = SignalClient(
        config=config,
        http=httpx.AsyncClient(),
        outbound_repo=repo,
        pool=object(),
        default_target="+10000000001",
    )
    async with client.http:
        await client.send("group body", to={"groupId": group_id}, intent="test")

    row = repo.calls[0]
    # Path-b: 'group:<id-b64>' prefix
    assert row["recipient_e164"].startswith("group:")
    assert group_id in row["recipient_e164"]


async def test_send_no_intent_defaults_to_unknown(respx_mock, caplog):
    """send() with intent=None defaults to 'unknown' and logs a warning."""
    import logging
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "444"})
    )

    config = load_config(TEST_ENV)
    repo = FakeOutboundRepo()
    client = SignalClient(
        config=config,
        http=httpx.AsyncClient(),
        outbound_repo=repo,
        pool=object(),
        default_target="+10000000001",
    )
    async with client.http:
        with caplog.at_level(logging.WARNING):
            await client.send("body")  # no intent

    row = repo.calls[0]
    assert row["intent"] == "unknown"
    assert any("intent" in r.message.lower() or "unknown" in r.message.lower()
               for r in caplog.records)
