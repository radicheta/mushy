"""
test_signal_ratecap.py -- Unit tests for asyncio.Lock-guarded rate-cap (SC#4 / D-04).

No DB required. Uses respx for httpx mocking.
"""

import asyncio

import httpx
import pytest

from tests.conftest import TEST_ENV


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(max_sends: int = 2, get_max_hook=None):
    """Build a SignalClient with a custom cap for rate-cap tests."""
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    env = {**TEST_ENV, "ALERT_MAX_SENDS_PER_HOUR": str(max_sends)}
    config = load_config(env)
    http_client = httpx.AsyncClient()
    return SignalClient(
        config=config,
        http=http_client,
        default_target="+10000000001",
        get_max_sends_per_hour=get_max_hook,
    )


# ---------------------------------------------------------------------------
# SC#4: Concurrent sends respect the cap (asyncio.Lock, reserve-before-await)
# ---------------------------------------------------------------------------


async def test_concurrent_sends_never_exceed_cap(respx_mock):
    """Two concurrent sends with cap=2: exactly 2 ok, 3rd is rate-cap."""
    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "111"})
    )
    client = _make_client(max_sends=2)
    async with client.http:
        results = await asyncio.gather(
            client.send("msg1"),
            client.send("msg2"),
            client.send("msg3"),
        )

    ok_count = sum(1 for r in results if r.get("ok") is True)
    cap_count = sum(1 for r in results if r.get("reason") == "rate-cap")
    assert ok_count == 2
    assert cap_count == 1


async def test_rate_cap_history_length_never_exceeds_cap(respx_mock):
    """In-memory history never grows beyond the cap."""
    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "222"})
    )
    client = _make_client(max_sends=3)
    async with client.http:
        await asyncio.gather(*[client.send(f"msg{i}") for i in range(5)])

    # prune (now still fresh) then check length
    import time
    client._prune_history(int(time.time() * 1000))
    assert len(client._send_history) <= 3


async def test_rate_cap_returns_ok_false_reason_rate_cap(respx_mock):
    """Dropped send returns {"ok": False, "reason": "rate-cap"}."""
    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "333"})
    )
    client = _make_client(max_sends=1)
    async with client.http:
        first = await client.send("first")
        second = await client.send("second")  # should be capped

    assert first["ok"] is True
    assert second == {"ok": False, "reason": "rate-cap"}


# ---------------------------------------------------------------------------
# Dynamic cap hook
# ---------------------------------------------------------------------------


async def test_dynamic_cap_hook_overrides_config(respx_mock):
    """get_max_sends_per_hour hook returning finite number is honoured."""
    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "444"})
    )

    # Config cap = 1 but hook returns 3
    def my_hook():
        return 3

    client = _make_client(max_sends=1, get_max_hook=my_hook)
    async with client.http:
        results = await asyncio.gather(
            client.send("a"), client.send("b"), client.send("c"), client.send("d")
        )

    ok_count = sum(1 for r in results if r.get("ok") is True)
    assert ok_count == 3


async def test_dynamic_cap_hook_raising_falls_back_to_config(respx_mock):
    """Hook that raises falls back to config.max_sends_per_hour."""
    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "555"})
    )

    def bad_hook():
        raise RuntimeError("hook failure")

    client = _make_client(max_sends=2, get_max_hook=bad_hook)
    async with client.http:
        results = await asyncio.gather(
            client.send("a"), client.send("b"), client.send("c")
        )

    ok_count = sum(1 for r in results if r.get("ok") is True)
    cap_count = sum(1 for r in results if r.get("reason") == "rate-cap")
    assert ok_count == 2
    assert cap_count == 1


# ---------------------------------------------------------------------------
# _prune_history
# ---------------------------------------------------------------------------


def test_prune_history_drops_old_timestamps():
    """_prune_history drops entries older than 3_600_000 ms before now."""
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    config = load_config(TEST_ENV)
    client = SignalClient(
        config=config,
        http=httpx.AsyncClient(),
        default_target="+10000000001",
    )
    import time
    now = int(time.time() * 1000)
    old = now - 4_000_000   # 4 hours ago, should be pruned
    recent = now - 1_000    # 1 second ago, should be kept

    client._send_history = [old, recent]
    client._prune_history(now)
    assert client._send_history == [recent]


def test_sends_this_hour_reflects_pruned_count():
    """sends_this_hour() returns count after pruning stale entries."""
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    config = load_config(TEST_ENV)
    client = SignalClient(
        config=config,
        http=httpx.AsyncClient(),
        default_target="+10000000001",
    )
    import time
    now = int(time.time() * 1000)
    # Mix of old and recent
    client._send_history = [now - 7_200_000, now - 500, now - 200]
    count = client.sends_this_hour()
    assert count == 2  # the one 2 hours ago is pruned
