"""
test_signal_groups.py -- Unit tests for group-ID translation (SC#2).

Tests the lazy /v1/groups cache and internal_id→id-b64 translation.
No DB required.
"""

import httpx
import pytest

from tests.conftest import TEST_ENV


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client():
    from farm_agent.signal_io.client import SignalClient  # noqa: PLC0415
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    config = load_config(TEST_ENV)
    http_client = httpx.AsyncClient()
    return SignalClient(config=config, http=http_client, default_target="+10000000001")


GROUPS_RESPONSE = [
    {
        "id": "group.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
        "internal_id": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB==",
        "name": "Test Group",
    }
]


# ---------------------------------------------------------------------------
# SC#2: Group internal_id→id-b64 translation
# ---------------------------------------------------------------------------


async def test_group_send_translates_internal_id(respx_mock):
    """A group target with internal_id is translated to id-b64 via /v1/groups cache."""
    # Mock /v1/groups to return our test group
    respx_mock.get("http://signal-cli:8080/v1/groups/%2B10000000000").mock(
        return_value=httpx.Response(200, json=GROUPS_RESPONSE)
    )
    # Mock /v2/send to capture the recipients
    send_mock = respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "999"})
    )

    client = _make_client()
    async with client.http:
        result = await client.send(
            "group msg",
            to={"groupId": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=="},
        )

    assert result["ok"] is True
    import json
    body = json.loads(send_mock.calls.last.request.content)
    # Should have translated internal_id to id-b64 form
    assert body["recipients"] == ["group.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="]


async def test_group_send_passthrough_on_cache_miss(respx_mock):
    """A groupId not in the cache passes through as recipients=['group.<groupId>']."""
    # Mock /v1/groups to return empty (cache miss)
    respx_mock.get("http://signal-cli:8080/v1/groups/%2B10000000000").mock(
        return_value=httpx.Response(200, json=[])
    )
    send_mock = respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "888"})
    )

    client = _make_client()
    unknown_id = "UNKNOWNUNKNOWNUNKNOWNUNKNOWNUNKNOWNUNKNOWNUNK=="
    async with client.http:
        result = await client.send("msg", to={"groupId": unknown_id})

    assert result["ok"] is True
    import json
    body = json.loads(send_mock.calls.last.request.content)
    # Pass-through: uses the groupId as-is
    assert body["recipients"] == [f"group.{unknown_id}"]


async def test_groups_list_failure_does_not_raise(respx_mock):
    """If /v1/groups fails, send still proceeds (fail-open, warn logged)."""
    respx_mock.get("http://signal-cli:8080/v1/groups/%2B10000000000").mock(
        return_value=httpx.Response(500, text="server error")
    )
    respx_mock.post("http://signal-cli:8080/v2/send").mock(
        return_value=httpx.Response(201, json={"timestamp": "777"})
    )

    client = _make_client()
    async with client.http:
        # Should NOT raise despite groups list failure
        result = await client.send("msg", to={"groupId": "somegroupid=="})

    assert result["ok"] is True


async def test_ensure_groups_loaded_populates_map(respx_mock):
    """ensure_groups_loaded populates the group_id_map correctly."""
    respx_mock.get("http://signal-cli:8080/v1/groups/%2B10000000000").mock(
        return_value=httpx.Response(200, json=GROUPS_RESPONSE)
    )

    client = _make_client()
    async with client.http:
        await client.ensure_groups_loaded()

    assert client._groups_loaded is True
    assert (
        client._group_id_map.get("BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB==")
        == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
    )


async def test_ensure_groups_loaded_skips_if_already_loaded(respx_mock):
    """ensure_groups_loaded is a no-op when already loaded (and force=False)."""
    # Register but don't expect it to be called
    groups_route = respx_mock.get("http://signal-cli:8080/v1/groups/%2B10000000000").mock(
        return_value=httpx.Response(200, json=GROUPS_RESPONSE)
    )

    client = _make_client()
    client._groups_loaded = True  # pre-mark as loaded
    async with client.http:
        await client.ensure_groups_loaded(force=False)

    # Should NOT have called the groups endpoint
    assert groups_route.called is False


async def test_ensure_groups_loaded_strips_group_prefix(respx_mock):
    """Group ids with 'group.' prefix are stripped in the map."""
    respx_mock.get("http://signal-cli:8080/v1/groups/%2B10000000000").mock(
        return_value=httpx.Response(200, json=[
            {
                "id": "group.ABC123==",
                "internal_id": "INTERNAL==",
            }
        ])
    )

    client = _make_client()
    async with client.http:
        await client.ensure_groups_loaded()

    assert client._group_id_map.get("INTERNAL==") == "ABC123=="
