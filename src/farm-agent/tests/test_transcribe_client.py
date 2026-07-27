"""
tests/test_transcribe_client.py -- Unit tests for capture/transcribe_client.py.

Covers:
  - 200 OK: {ok:True, text, duration_ms, language}
  - Dual-arg: string path and {audio_path} dict behave identically
  - Missing audio_path (None, {}, empty string): {ok:False, reason:"missing audio_path"}
  - 5xx: {ok:False, reason starts "whisper 500:"}; never raises
  - timeout: httpx.TimeoutException -> {ok:False, reason:"timeout"}; never raises
  - Off-loop (D-02/D-03): transcribe is async def (assert via inspect.iscoroutinefunction)

respx.mock patches httpx globally when used via the whisper_http fixture.
Do NOT pass MockRouter as transport -- create a plain httpx.AsyncClient() and
the mock intercepts the requests. Mirror test_signal_client.py:34 pattern.
"""

import inspect

import httpx
import pytest

WHISPER_URL = "http://host.docker.internal:8090"


def _make_client():
    """Create a transcribe client with a fresh httpx.AsyncClient.

    respx.mock patches httpx globally -- do NOT pass MockRouter as transport.
    Mirror the pattern in test_signal_client.py:34.
    """
    from farm_agent.capture.transcribe_client import create_transcribe_client

    http = httpx.AsyncClient()
    return create_transcribe_client(WHISPER_URL, http=http, timeout_ms=5_000)


# ---------------------------------------------------------------------------
# Test: 200 OK path
# ---------------------------------------------------------------------------


async def test_ok_string_path(whisper_http):
    """transcribe('/path/to/x.ogg') -> {ok:True, text, duration_ms, language}."""
    whisper_http.post(f"{WHISPER_URL}/transcribe").mock(
        return_value=httpx.Response(
            200,
            json={"text": "hola", "duration_ms": 1500, "language": "es"},
        )
    )
    client = _make_client()
    result = await client["transcribe"]("/data/signal-capture/x.ogg")

    assert result["ok"] is True
    assert result["text"] == "hola"
    assert result["duration_ms"] == 1500
    assert result["language"] == "es"


# ---------------------------------------------------------------------------
# Test: dual-arg symmetry
# ---------------------------------------------------------------------------


async def test_dual_arg_dict_same_as_string(whisper_http):
    """transcribe({'audio_path': '/p.ogg'}) behaves identically to transcribe('/p.ogg')."""
    whisper_http.post(f"{WHISPER_URL}/transcribe").mock(
        return_value=httpx.Response(
            200,
            json={"text": "hola", "duration_ms": 1500, "language": "es"},
        )
    )
    client = _make_client()
    result = await client["transcribe"]({"audio_path": "/p.ogg"})

    assert result["ok"] is True
    assert result["text"] == "hola"


# ---------------------------------------------------------------------------
# Test: missing audio_path -- no HTTP call should be made
# ---------------------------------------------------------------------------


async def test_missing_none_no_http(whisper_http):
    """transcribe(None) -> {ok:False, reason:'missing audio_path'}, no HTTP call."""
    client = _make_client()
    result = await client["transcribe"](None)

    assert result["ok"] is False
    assert result["reason"] == "missing audio_path"
    # No HTTP call made
    assert whisper_http.calls.call_count == 0


async def test_missing_empty_dict_no_http(whisper_http):
    """transcribe({}) -> {ok:False, reason:'missing audio_path'}, no HTTP call."""
    client = _make_client()
    result = await client["transcribe"]({})

    assert result["ok"] is False
    assert result["reason"] == "missing audio_path"
    assert whisper_http.calls.call_count == 0


# ---------------------------------------------------------------------------
# Test: 5xx response -- never raises
# ---------------------------------------------------------------------------


async def test_5xx_returns_error_never_raises(whisper_http):
    """Whisper 500 -> {ok:False, reason starts 'whisper 500:'}; never raises."""
    whisper_http.post(f"{WHISPER_URL}/transcribe").mock(
        return_value=httpx.Response(500, text="internal server error")
    )
    client = _make_client()
    result = await client["transcribe"]("/data/signal-capture/x.ogg")

    assert result["ok"] is False
    assert result["reason"].startswith("whisper 500:")


# ---------------------------------------------------------------------------
# Test: timeout -- never raises
# ---------------------------------------------------------------------------


async def test_timeout_never_raises(whisper_http):
    """httpx.TimeoutException -> {ok:False, reason:'timeout'}; never raises."""
    whisper_http.post(f"{WHISPER_URL}/transcribe").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    client = _make_client()
    result = await client["transcribe"]("/data/signal-capture/x.ogg")

    assert result["ok"] is False
    assert result["reason"] == "timeout"


# ---------------------------------------------------------------------------
# Test: off-loop / D-02/D-03 -- transcribe is async def
# ---------------------------------------------------------------------------


def test_transcribe_is_async_def():
    """transcribe returned from factory is an async def (D-02/D-03 off-loop assertion)."""
    from farm_agent.capture.transcribe_client import create_transcribe_client

    http = httpx.AsyncClient()
    client = create_transcribe_client(WHISPER_URL, http=http, timeout_ms=5_000)
    transcribe_fn = client["transcribe"]
    assert inspect.iscoroutinefunction(transcribe_fn), (
        "transcribe must be an async def so that await yields the event loop (D-02/D-03)"
    )
