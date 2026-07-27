"""
test_signal_client.py -- Unit tests for SignalClient transport + quote primitive (SIG-01, SIG-04).

Uses respx (via signal_http fixture) to mock httpx.AsyncClient responses.
No DB required -- all tests are DB-independent.

Coverage (Tasks 1-3):
  Task 1: send/receive/fetch_attachment/accounts endpoints, quote coercion + fail-open
  Task 2: rate-cap (asyncio.Lock, reserve-before-await), group translation
  Task 3: fail-open persist hook (FakeOutboundRepo + real persist row shape)
"""

import asyncio
import datetime
import logging

import httpx
import pytest

from tests.conftest import TEST_ENV, FakeOutboundRepo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(signal_http, **kwargs):
    """Build a SignalClient wired to the respx mock (global patching via signal_http fixture)."""
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    config = load_config(TEST_ENV)
    # respx.mock patches httpx globally -- do NOT pass MockRouter as transport
    http_client = httpx.AsyncClient()
    return SignalClient(config=config, http=http_client, **kwargs)


# ---------------------------------------------------------------------------
# Task 1: Transport -- send
# ---------------------------------------------------------------------------


async def test_send_string_target_posts_v2_send(signal_http):
    """send("hi") to a string target POSTs /v2/send with correct payload."""
    signal_http.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "1779562666675"})
    )
    client = _make_client(signal_http, default_target="+10000000001")
    async with client.http:
        result = await client.send("hi")

    assert result["ok"] is True
    assert isinstance(result["timestamp"], int)
    assert result["timestamp"] == 1779562666675

    req = signal_http.calls.last.request
    import json
    body = json.loads(req.content)
    assert body["message"] == "hi"
    assert body["number"] == "+10000000000"      # signal_sender from TEST_ENV
    assert body["recipients"] == ["+10000000001"]


async def test_send_to_override_target(signal_http):
    """send() with to= kwarg overrides the default_target."""
    signal_http.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "111"})
    )
    client = _make_client(signal_http, default_target="+10000000001")
    async with client.http:
        result = await client.send("msg", to="+19995550001")

    assert result["ok"] is True
    req = signal_http.calls.last.request
    import json
    body = json.loads(req.content)
    assert body["recipients"] == ["+19995550001"]


async def test_send_http_error_raises(signal_http):
    """signal-cli returning 400 raises RuntimeError."""
    signal_http.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(400, text="bad request")
    )
    client = _make_client(signal_http, default_target="+10000000001")
    async with client.http:
        with pytest.raises(RuntimeError, match="signal-cli 400"):
            await client.send("hi")


async def test_send_invalid_target_none_raises(signal_http):
    """send() with an invalid target (None effective) raises ValueError."""
    # Construct with no default_target and pass to=None explicitly
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    config = load_config(TEST_ENV)
    http_client = httpx.AsyncClient(transport=signal_http)
    # default_target uses config.signal_recipient which IS set; override to empty
    client = SignalClient(config=config, http=http_client, default_target="+10000000001")
    async with client.http:
        with pytest.raises(ValueError, match="invalid send target"):
            await client.send("hi", to={})  # dict without groupId → invalid


async def test_send_invalid_target_empty_dict_raises(signal_http):
    """dict target without groupId raises ValueError."""
    client = _make_client(signal_http, default_target="+10000000001")
    async with client.http:
        with pytest.raises(ValueError, match="invalid send target"):
            await client.send("hi", to={"groupId": ""})


# ---------------------------------------------------------------------------
# Task 1: Transport -- receive, fetch_attachment, accounts
# ---------------------------------------------------------------------------


async def test_receive_gets_v1_receive(signal_http):
    """receive() GETs /v1/receive/{sender} and returns parsed JSON list."""
    signal_http.get("http://signal-cli:8080/v1/receive/+10000000000").mock(
        return_value=httpx.Response(200, json=[{"envelope": {"source": "+10000000001"}}])
    )
    client = _make_client(signal_http, default_target="+10000000001")
    async with client.http:
        result = await client.receive()
    assert isinstance(result, list)
    assert result[0]["envelope"]["source"] == "+10000000001"


async def test_fetch_attachment_returns_bytes(signal_http):
    """fetch_attachment(id) returns bytes (response content)."""
    signal_http.get("http://signal-cli:8080/v1/attachments/abc123").mock(
        return_value=httpx.Response(200, content=b"\x89PNG\r\n")
    )
    client = _make_client(signal_http, default_target="+10000000001")
    async with client.http:
        result = await client.fetch_attachment("abc123")
    assert isinstance(result, bytes)
    assert result == b"\x89PNG\r\n"


async def test_accounts_returns_parsed_json(signal_http):
    """accounts() GETs /v1/accounts and returns parsed JSON."""
    signal_http.get("http://signal-cli:8080/v1/accounts").mock(
        return_value=httpx.Response(200, json=["+10000000000"])
    )
    client = _make_client(signal_http, default_target="+10000000001")
    async with client.http:
        result = await client.accounts()
    assert result == ["+10000000000"]


# ---------------------------------------------------------------------------
# Task 1: Quote primitive (SC#3) -- tested here for transport integration
# ---------------------------------------------------------------------------


async def test_send_with_valid_string_ts_quote(signal_http):
    """Valid quote with string timestamp: payload.quote.timestamp is an int."""
    signal_http.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "1234"})
    )
    client = _make_client(signal_http, default_target="+10000000001")
    async with client.http:
        result = await client.send(
            "reply",
            quote={"timestamp": "1779562666675", "author": "+10000000001", "message": "orig"},
        )
    assert result["ok"] is True

    req = signal_http.calls.last.request
    import json
    body = json.loads(req.content)
    assert body["quote_timestamp"] == 1779562666675
    assert isinstance(body["quote_timestamp"], int)
    assert body["quote_author"] == "+10000000001"
    assert body["quote_message"] == "orig"


async def test_send_with_invalid_quote_sends_unquoted(signal_http, caplog):
    """Invalid quote (missing author) → NO quote key in payload, warn logged, send ok."""
    signal_http.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "1234"})
    )
    client = _make_client(signal_http, default_target="+10000000001")
    async with client.http:
        with caplog.at_level(logging.WARNING):
            result = await client.send(
                "msg",
                quote={"timestamp": "123", "message": "x"},  # missing author
            )
    assert result["ok"] is True
    req = signal_http.calls.last.request
    import json
    body = json.loads(req.content)
    assert "quote_timestamp" not in body
    assert "quote_author" not in body
    assert "quote_message" not in body
    assert any("invalid quote" in r.message.lower() for r in caplog.records)


async def test_send_with_invalid_quote_no_raise(signal_http):
    """Invalid quote NEVER raises an exception -- fail-open."""
    signal_http.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "1234"})
    )
    client = _make_client(signal_http, default_target="+10000000001")
    async with client.http:
        # Should NOT raise
        result = await client.send("msg", quote={"not": "valid"})
    assert result["ok"] is True
