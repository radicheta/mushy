"""
tests/test_farmos_qr.py -- Unit tests for farmos/qr.py.

Port of Node farmos/qr.js (Phase 40 D-04 / D-06).

Covers (plan 62-05 acceptance criteria):
  - resolve_qr id_tag hit: returns {found:True, asset_id:str, path:'id_tag'}
  - resolve_qr id_tag ok but empty -> fallback to name: returns {found:True, asset_id:str, path:'name'}
  - resolve_qr id_tag transport failure: returns {found:False, error:'http_<status|network>', path:'id_tag'}
    and does NOT call name lookup (no second GET)
  - resolve_qr both lookups empty: returns {found:False, path:'name'}
  - bind_qr_on_create: writes id_tag list on payload.data.attributes
  - bind_qr_on_create: no-op on empty qr_codes
  - filter[id_tag.id][value] appears in the id_tag GET path (acceptance grep: 1 occurrence in source)
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fake client helpers
# ---------------------------------------------------------------------------


def _make_client(get_responses: list[dict]) -> tuple[dict, list]:
    """Return (client_dict, call_log) where get_responses are popped in order."""
    calls: list[dict] = []
    responses = list(get_responses)

    async def fake_get(path: str, opts=None) -> dict:
        calls.append({"method": "GET", "path": path})
        return responses.pop(0)

    async def fake_post(path: str, body=None, opts=None) -> dict:
        calls.append({"method": "POST", "path": path})
        return {"ok": False, "status": 500, "body": None}

    return {"get": fake_get, "post": fake_post}, calls


def _asset_resp(asset_id: str) -> dict:
    return {"ok": True, "status": 200, "body": {"data": [{"id": asset_id}]}, "latency_ms": 5}


def _empty_resp() -> dict:
    return {"ok": True, "status": 200, "body": {"data": []}, "latency_ms": 5}


def _error_resp(status: int = 503) -> dict:
    return {"ok": False, "status": status, "body": None, "latency_ms": 5}


# ---------------------------------------------------------------------------
# resolve_qr tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_qr_id_tag_hit():
    """id_tag lookup returns asset -> found:True, path='id_tag'."""
    from farm_agent.farmos.qr import resolve_qr

    client, calls = _make_client([_asset_resp("uuid-abc")])
    r = await resolve_qr(client, "QR-001")

    assert r["found"] is True
    assert r["asset_id"] == "uuid-abc"
    assert r["path"] == "id_tag"
    # Only one GET was made (no name fallback needed)
    assert len(calls) == 1
    assert "filter[id_tag.id][value]" in calls[0]["path"]


@pytest.mark.asyncio
async def test_resolve_qr_name_fallback_on_empty_id_tag():
    """id_tag ok but empty -> name fallback returns found:True, path='name'."""
    from farm_agent.farmos.qr import resolve_qr

    client, calls = _make_client([_empty_resp(), _asset_resp("uuid-name")])
    r = await resolve_qr(client, "BLOCK-99")

    assert r["found"] is True
    assert r["asset_id"] == "uuid-name"
    assert r["path"] == "name"
    assert len(calls) == 2
    assert "filter[id_tag.id][value]" in calls[0]["path"]
    assert "filter[name][value]" in calls[1]["path"]


@pytest.mark.asyncio
async def test_resolve_qr_transport_failure_not_a_miss():
    """id_tag call ok=False -> found:False, error set, path='id_tag', NO name call."""
    from farm_agent.farmos.qr import resolve_qr

    client, calls = _make_client([_error_resp(503)])
    r = await resolve_qr(client, "QR-ERR")

    assert r["found"] is False
    assert r["path"] == "id_tag"
    assert "http_" in r["error"]
    # No second GET call (name fallback must NOT be made on transport failure)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_resolve_qr_both_empty_returns_not_found():
    """Both id_tag and name return empty arrays -> found:False, path='name'."""
    from farm_agent.farmos.qr import resolve_qr

    client, calls = _make_client([_empty_resp(), _empty_resp()])
    r = await resolve_qr(client, "GHOST")

    assert r["found"] is False
    assert r["path"] == "name"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_resolve_qr_exception_returns_found_false():
    """Exception in GET -> found:False with error field (no raise)."""
    from farm_agent.farmos.qr import resolve_qr

    async def raising_get(path: str, opts=None) -> dict:
        raise ConnectionError("network gone")

    client = {"get": raising_get, "post": None}
    r = await resolve_qr(client, "QR-BOOM")

    assert r["found"] is False
    assert "error" in r


@pytest.mark.asyncio
async def test_resolve_qr_url_encodes_qr_code():
    """QR code with special chars is URL-encoded in the filter query."""
    from farm_agent.farmos.qr import resolve_qr

    client, calls = _make_client([_empty_resp(), _empty_resp()])
    await resolve_qr(client, "A B+C")

    # space -> %20 or +; + -> %2B in the path
    assert "A" in calls[0]["path"]
    # URL encoding must be applied (raw space must not appear in path)
    assert " " not in calls[0]["path"]


# ---------------------------------------------------------------------------
# bind_qr_on_create tests
# ---------------------------------------------------------------------------


def test_bind_qr_on_create_writes_id_tag():
    """bind_qr_on_create sets payload.data.attributes.id_tag list."""
    from farm_agent.farmos.qr import ID_TAG_TYPE, bind_qr_on_create

    payload = {"data": {"attributes": {}}}
    result = bind_qr_on_create(payload, ["QR-A", "QR-B"])

    tags = result["data"]["attributes"]["id_tag"]
    assert len(tags) == 2
    assert tags[0] == {"id": "QR-A", "type": ID_TAG_TYPE, "location": ""}
    assert tags[1] == {"id": "QR-B", "type": ID_TAG_TYPE, "location": ""}


def test_bind_qr_on_create_noop_on_empty():
    """bind_qr_on_create with empty list leaves payload unchanged."""
    from farm_agent.farmos.qr import bind_qr_on_create

    payload = {"data": {"attributes": {}}}
    result = bind_qr_on_create(payload, [])
    assert "id_tag" not in result["data"]["attributes"]


def test_bind_qr_on_create_noop_on_none():
    """bind_qr_on_create with None qr_codes leaves payload unchanged."""
    from farm_agent.farmos.qr import bind_qr_on_create

    payload = {"data": {"attributes": {}}}
    result = bind_qr_on_create(payload, None)
    assert "id_tag" not in result["data"]["attributes"]


def test_id_tag_type_is_other():
    """ID_TAG_TYPE constant must be 'other' (prod farmOS constraint)."""
    from farm_agent.farmos.qr import ID_TAG_TYPE

    assert ID_TAG_TYPE == "other"
