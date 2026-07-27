"""
tests/test_farmos_client.py -- Unit tests for farmos/client.py.

Port of Node farmOS client (src/agents/alerter/src/farmos/client.js) to Python httpx.

Covers (plan 62-02 acceptance criteria):
  - Auth: POST /user/login?_format=json stores cookie + csrf_token (grep assertion)
  - GET success: returns {ok:True, status:200, body:dict, latency_ms:int} envelope
  - 401 then 200: reauths exactly once (login called twice total, assert login called 2x)
  - Second 401 returns ok=False without infinite loop
  - 5xx then 200: retries with injected sleep spy; backoff order is (1000, 4000, 16000)
  - Timeout (httpx.TimeoutException): {ok:False, status:None, error:str} never raises
  - ConnectError: {ok:False, status:None, error:str} never raises
  - post_binary: sets Content-Type application/octet-stream + Content-Disposition header
  - X-CSRF-Token header is sent on authenticated requests (grep assertion)

Thread model: T-62-04 (no password/cookie in logs), T-62-05 (reauth on 401), T-62-06 (timeout)
respx.mock patches httpx globally -- do NOT pass MockRouter as transport.
Mirror test_transcribe_client.py pattern.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

FARMOS_URL = "http://test-farmos:18080"
LOGIN_URL = f"{FARMOS_URL}/user/login?_format=json"
TEST_COOKIE = "SESS_abc123"
TEST_CSRF = "csrf_token_value"


def _auth_response() -> httpx.Response:
    """Canned successful auth response with Set-Cookie and csrf_token."""
    return httpx.Response(
        200,
        json={"csrf_token": TEST_CSRF, "current_user": {"uid": 1}},
        headers={"Set-Cookie": f"{TEST_COOKIE}; Path=/; HttpOnly"},
    )


def _make_client(http: httpx.AsyncClient, sleep_spy=None) -> dict:
    """Create a farmos client with optional injectable sleep spy."""
    from farm_agent.farmos.client import create_farmos_client

    kwargs: dict = {
        "farmos_url": FARMOS_URL,
        "username": "test-user",
        "password": "test-pass",
        "http": http,
        "backoff_ms": (1000, 4000, 16000),
        "timeout_ms": 5000,
        "retry_max": 3,
    }
    if sleep_spy is not None:
        kwargs["_sleep"] = sleep_spy
    return create_farmos_client(**kwargs)


# ---------------------------------------------------------------------------
# Test: GET success -- happy path envelope
# ---------------------------------------------------------------------------


async def test_get_success_envelope():
    """GET /api/resource -> {ok:True, status:200, body:dict, latency_ms:int}."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.get(f"{FARMOS_URL}/api/asset/fungi").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "uuid-1"}]})
        )
        http = httpx.AsyncClient()
        client = _make_client(http)
        result = await client["get"]("/api/asset/fungi")

    assert result["ok"] is True
    assert result["status"] == 200
    assert isinstance(result["body"], dict)
    assert "latency_ms" in result
    assert isinstance(result["latency_ms"], int)


# ---------------------------------------------------------------------------
# Test: Auth stores cookie + csrf (session population)
# ---------------------------------------------------------------------------


async def test_auth_stores_cookie_and_csrf():
    """After first request, _session["cookie"] and _session["csrf"] are populated."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.get(f"{FARMOS_URL}/api/ping").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        http = httpx.AsyncClient()
        client = _make_client(http)
        await client["get"]("/api/ping")

    session = client["_session"]
    assert session["cookie"] == TEST_COOKIE, "cookie must be first Set-Cookie segment before ';'"
    assert session["csrf"] == TEST_CSRF, "csrf must be body csrf_token"


# ---------------------------------------------------------------------------
# Test: 401 then 200 -> reauths exactly once; login called twice total
# ---------------------------------------------------------------------------


async def test_reauth_on_401_calls_login_twice():
    """A 401 response triggers exactly one re-auth; total login calls = 2."""
    login_call_count = 0

    def login_side_effect(request):
        nonlocal login_call_count
        login_call_count += 1
        return _auth_response()

    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(side_effect=login_side_effect)
        # First GET: 401 (triggers reauth) then 200
        call_count = 0

        def get_side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(401)
            return httpx.Response(200, json={"data": []})

        mock.get(f"{FARMOS_URL}/api/asset/fungi").mock(side_effect=get_side_effect)
        http = httpx.AsyncClient()
        client = _make_client(http)
        result = await client["get"]("/api/asset/fungi")

    # Initial auth (lazy on first request) + one reauth = 2
    assert login_call_count == 2, f"Expected 2 login calls, got {login_call_count}"
    assert result["ok"] is True
    assert result["status"] == 200


# ---------------------------------------------------------------------------
# Test: Second 401 returns ok=False without infinite loop
# ---------------------------------------------------------------------------


async def test_second_401_returns_ok_false_no_loop():
    """After reauth, a second 401 returns ok=False immediately -- no infinite loop."""
    login_call_count = 0

    def login_side_effect(request):
        nonlocal login_call_count
        login_call_count += 1
        return _auth_response()

    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(side_effect=login_side_effect)
        mock.get(f"{FARMOS_URL}/api/asset/fungi").mock(
            return_value=httpx.Response(401)
        )
        http = httpx.AsyncClient()
        client = _make_client(http)
        result = await client["get"]("/api/asset/fungi")

    assert result["ok"] is False
    assert result["status"] == 401
    # Initial auth + one reauth; no more
    assert login_call_count == 2, f"Expected 2 login calls, got {login_call_count}"


# ---------------------------------------------------------------------------
# Test: 5xx retry with backoff sleep spy
# ---------------------------------------------------------------------------


async def test_5xx_retry_calls_sleep_with_backoff_1000_first():
    """A 500 then 200 retries once; sleep called with backoff_ms[0]=1000."""
    sleep_calls: list[int] = []

    async def fake_sleep(ms: int) -> None:
        sleep_calls.append(ms)

    get_call_count = 0

    def get_side_effect(request):
        nonlocal get_call_count
        get_call_count += 1
        if get_call_count == 1:
            return httpx.Response(500, text="internal server error")
        return httpx.Response(200, json={"data": []})

    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.get(f"{FARMOS_URL}/api/asset/fungi").mock(side_effect=get_side_effect)
        http = httpx.AsyncClient()
        client = _make_client(http, sleep_spy=fake_sleep)
        result = await client["get"]("/api/asset/fungi")

    assert result["ok"] is True
    assert result["status"] == 200
    assert sleep_calls == [1000], f"Expected sleep([1000]), got {sleep_calls}"


async def test_5xx_backoff_sequence_uses_increasing_waits():
    """Two 500s then 200: sleep called twice with [1000, 4000] (indices 0, 1)."""
    sleep_calls: list[int] = []

    async def fake_sleep(ms: int) -> None:
        sleep_calls.append(ms)

    get_call_count = 0

    def get_side_effect(request):
        nonlocal get_call_count
        get_call_count += 1
        if get_call_count <= 2:
            return httpx.Response(500, text="server error")
        return httpx.Response(200, json={"data": []})

    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.get(f"{FARMOS_URL}/api/asset/fungi").mock(side_effect=get_side_effect)
        http = httpx.AsyncClient()
        client = _make_client(http, sleep_spy=fake_sleep)
        result = await client["get"]("/api/asset/fungi")

    assert result["ok"] is True
    assert sleep_calls == [1000, 4000], f"Expected [1000, 4000], got {sleep_calls}"


# ---------------------------------------------------------------------------
# Test: 5xx exhaustion returns ok=False (retry_max=3 means max 2 sleeps)
# ---------------------------------------------------------------------------


async def test_5xx_exhausted_retries_returns_ok_false():
    """Three 500s (retry_max=3): returns ok=False after exhausting retries."""
    sleep_calls: list[int] = []

    async def fake_sleep(ms: int) -> None:
        sleep_calls.append(ms)

    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.get(f"{FARMOS_URL}/api/asset/fungi").mock(
            return_value=httpx.Response(500, text="server error")
        )
        http = httpx.AsyncClient()
        client = _make_client(http, sleep_spy=fake_sleep)
        result = await client["get"]("/api/asset/fungi")

    assert result["ok"] is False
    # 2 sleeps (attempt 0->1 and 1->2); attempt 2 fails and exits
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == 1000
    assert sleep_calls[1] == 4000


# ---------------------------------------------------------------------------
# Test: Timeout never raises -- {ok:False, status:None, error:str}
# ---------------------------------------------------------------------------


async def test_timeout_never_raises():
    """httpx.TimeoutException -> {ok:False, status:None, error:str}; never propagates."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.get(f"{FARMOS_URL}/api/ping").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        http = httpx.AsyncClient()
        client = _make_client(http)
        result = await client["get"]("/api/ping")

    assert result["ok"] is False
    assert result["status"] is None
    assert "error" in result
    assert result["error"]  # non-empty error string


# ---------------------------------------------------------------------------
# Test: ConnectError never raises
# ---------------------------------------------------------------------------


async def test_connect_error_never_raises():
    """httpx.ConnectError -> {ok:False, status:None, error:str}; never propagates."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.get(f"{FARMOS_URL}/api/ping").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        http = httpx.AsyncClient()
        client = _make_client(http)
        result = await client["get"]("/api/ping")

    assert result["ok"] is False
    assert result["status"] is None
    assert "error" in result


# ---------------------------------------------------------------------------
# Test: post_binary sends octet-stream + Content-Disposition
# ---------------------------------------------------------------------------


async def test_post_binary_sends_octet_stream_and_content_disposition():
    """post_binary sets Content-Type application/octet-stream + Content-Disposition."""
    captured_request = {}

    def capture_side_effect(request):
        captured_request["content_type"] = request.headers.get("content-type", "")
        captured_request["content_disposition"] = request.headers.get(
            "content-disposition", ""
        )
        return httpx.Response(201, json={"data": {"id": "file-uuid"}})

    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.post(f"{FARMOS_URL}/api/asset/fungi/my-uuid/image").mock(
            side_effect=capture_side_effect
        )
        http = httpx.AsyncClient()
        client = _make_client(http)
        result = await client["post_binary"](
            "/api/asset/fungi/my-uuid/image",
            b"fake-image-bytes",
            filename="photo.jpg",
        )

    assert result["ok"] is True
    assert "application/octet-stream" in captured_request["content_type"]
    assert "photo.jpg" in captured_request["content_disposition"]
    assert "file" in captured_request["content_disposition"]


# ---------------------------------------------------------------------------
# Test: X-CSRF-Token is sent on authenticated requests
# ---------------------------------------------------------------------------


async def test_x_csrf_token_sent_on_requests():
    """Authenticated requests include X-CSRF-Token header with the stored csrf value."""
    captured_csrf = {}

    def capture_side_effect(request):
        captured_csrf["value"] = request.headers.get("x-csrf-token", "")
        return httpx.Response(200, json={"data": []})

    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.get(f"{FARMOS_URL}/api/asset/fungi").mock(side_effect=capture_side_effect)
        http = httpx.AsyncClient()
        client = _make_client(http)
        await client["get"]("/api/asset/fungi")

    assert captured_csrf["value"] == TEST_CSRF, (
        f"Expected X-CSRF-Token={TEST_CSRF!r}, got {captured_csrf['value']!r}"
    )


# ---------------------------------------------------------------------------
# Test: Network error on auth (login failure) never raises
# ---------------------------------------------------------------------------


async def test_auth_network_error_never_raises():
    """If login itself throws a network error, the outer request returns ok=False."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(
            side_effect=httpx.ConnectError("cannot connect to farmOS")
        )
        http = httpx.AsyncClient()
        client = _make_client(http)
        result = await client["get"]("/api/asset/fungi")

    assert result["ok"] is False
    assert result["status"] is None


# ---------------------------------------------------------------------------
# Test: 4xx (client error) is final -- no retry
# ---------------------------------------------------------------------------


async def test_4xx_no_retry():
    """A 404 response is returned immediately (not retried)."""
    call_count = 0

    def get_side_effect(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(404, json={"error": "not found"})

    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.get(f"{FARMOS_URL}/api/asset/fungi/nonexistent").mock(
            side_effect=get_side_effect
        )
        http = httpx.AsyncClient()
        client = _make_client(http)
        result = await client["get"]("/api/asset/fungi/nonexistent")

    assert result["ok"] is False
    assert result["status"] == 404
    assert call_count == 1, "4xx must not be retried"


# ---------------------------------------------------------------------------
# Test: post, patch, delete wrappers available
# ---------------------------------------------------------------------------


async def test_post_json_available():
    """post() sends JSON body and returns envelope."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.post(f"{FARMOS_URL}/api/asset/fungi").mock(
            return_value=httpx.Response(201, json={"data": {"id": "new-uuid"}})
        )
        http = httpx.AsyncClient()
        client = _make_client(http)
        result = await client["post"]("/api/asset/fungi", {"data": {"type": "asset--fungi"}})

    assert result["ok"] is True
    assert result["status"] == 201


async def test_delete_available():
    """delete() sends DELETE; 204 no-body is ok=True."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(LOGIN_URL).mock(return_value=_auth_response())
        mock.delete(f"{FARMOS_URL}/api/asset/fungi/my-uuid").mock(
            return_value=httpx.Response(204)
        )
        http = httpx.AsyncClient()
        client = _make_client(http)
        result = await client["delete"]("/api/asset/fungi/my-uuid")

    assert result["ok"] is True
    assert result["status"] == 204
