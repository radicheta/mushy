"""Tests for group_assets.py (Phase 62-09).

Port of src/agents/alerter/test/farmos/groupAssets.test.js.

All external I/O is mocked. No real network or DB calls.
"""
from __future__ import annotations

import urllib.parse

import pytest

from farm_agent.farmos.group_assets import (
    find_group_asset_by_name,
    upsert_group_asset,
    delete_group_asset,
    _clear_cache,
)


def _ok(status: int, body) -> dict:
    return {"ok": 200 <= status < 300, "status": status, "body": body}


def make_group_client(
    get_impl=None,
    post_impl=None,
    delete_impl=None,
) -> dict:
    """Minimal mock client for group asset tests."""
    calls: dict = {"get": [], "post": [], "delete": []}

    async def _get(path: str) -> dict:
        calls["get"].append(path)
        return get_impl(path) if get_impl else _ok(200, {"data": []})

    async def _post(path: str, body: dict, opts=None) -> dict:
        calls["post"].append((path, body))
        return post_impl(path, body) if post_impl else _ok(201, {"data": {"id": "group-new"}})

    async def _delete(path: str, opts=None) -> dict:
        calls["delete"].append(path)
        return delete_impl(path) if delete_impl else _ok(204, None)

    return {"get": _get, "post": _post, "delete": _delete, "_calls": calls}


@pytest.fixture(autouse=True)
def clear_cache():
    _clear_cache()
    yield
    _clear_cache()


class TestFindGroupAssetByName:
    async def test_miss_returns_found_false(self):
        client = make_group_client()
        r = await find_group_asset_by_name(client, "inoc 2026-05-22")
        assert r["found"] is False

    async def test_hit_returns_asset_id(self):
        client = make_group_client(
            get_impl=lambda p: _ok(200, {"data": [{"id": "group-abc"}]})
        )
        r = await find_group_asset_by_name(client, "inoc 2026-05-22")
        assert r["found"] is True
        assert r["asset_id"] == "group-abc"

    async def test_uses_filter_name_value_query(self):
        client = make_group_client()
        await find_group_asset_by_name(client, "inoc 2026-05-22 #2")
        path = client["_calls"]["get"][0]
        expected = (
            "/api/asset/group?filter[name][value]="
            + urllib.parse.quote("inoc 2026-05-22 #2", safe="")
        )
        assert path == expected

    async def test_caches_subsequent_lookups(self):
        get_call_count = [0]

        def _get_impl(path: str) -> dict:
            get_call_count[0] += 1
            return _ok(200, {"data": [{"id": "group-cached"}]})

        client = make_group_client(get_impl=_get_impl)
        r1 = await find_group_asset_by_name(client, "inoc 2026-05-22")
        assert r1["found"] is True
        r2 = await find_group_asset_by_name(client, "inoc 2026-05-22")
        assert r2["found"] is True
        assert r2.get("cached") is True
        assert get_call_count[0] == 1  # only one GET to the network

    async def test_http_error_returns_found_false_with_error(self):
        client = make_group_client(
            get_impl=lambda p: _ok(500, None)
        )
        r = await find_group_asset_by_name(client, "inoc 2026-05-22")
        assert r["found"] is False
        assert "error" in r


class TestUpsertGroupAsset:
    async def test_miss_posts_to_api_asset_group_and_returns_created(self):
        client = make_group_client()
        r = await upsert_group_asset(client, {
            "name": "inoc 2026-05-22",
            "draft_id": "draft-xyz",
        })
        assert r["ok"] is True
        assert r["outcome"] == "created"
        assert r["asset_id"] == "group-new"
        assert r["http_status"] == 201
        assert len(client["_calls"]["post"]) == 1
        path, body = client["_calls"]["post"][0]
        assert path == "/api/asset/group"
        assert body["data"]["type"] == "asset--group"
        assert body["data"]["attributes"]["name"] == "inoc 2026-05-22"
        assert body["data"]["attributes"]["status"] == "active"
        assert "mushy:draft:draft-xyz" in body["data"]["attributes"]["notes"]["value"]
        assert body["data"]["attributes"]["notes"]["format"] == "plain_text"
        assert "relationships" not in body["data"]

    async def test_hit_returns_reused_without_post(self):
        client = make_group_client(
            get_impl=lambda p: _ok(200, {"data": [{"id": "group-existing"}]})
        )
        r = await upsert_group_asset(client, {
            "name": "inoc 2026-05-22",
            "draft_id": "draft-replay",
        })
        assert r["ok"] is True
        assert r["outcome"] == "reused"
        assert r["asset_id"] == "group-existing"
        assert len(client["_calls"]["post"]) == 0

    async def test_post_4xx_returns_http_reason(self):
        client = make_group_client(
            post_impl=lambda p, b: _ok(422, {"errors": [{}]})
        )
        r = await upsert_group_asset(client, {"name": "inoc 2026-05-22", "draft_id": "d"})
        assert r["ok"] is False
        assert r["reason"] == "http_422"
        assert r["http_status"] == 422

    async def test_post_5xx_returns_http_reason(self):
        client = make_group_client(
            post_impl=lambda p, b: _ok(500, None)
        )
        r = await upsert_group_asset(client, {"name": "inoc 2026-05-22", "draft_id": "d"})
        assert r["ok"] is False
        assert r["reason"] == "http_500"
        assert r["http_status"] == 500

    async def test_notes_trailer_with_notes_opt(self):
        client = make_group_client()
        await upsert_group_asset(client, {
            "name": "inoc 2026-05-22",
            "draft_id": "d1",
            "notes": "session preflight",
        })
        _, body = client["_calls"]["post"][0]
        assert body["data"]["attributes"]["notes"]["value"] == "session preflight\nmushy:draft:d1"

    async def test_notes_trailer_without_notes_opt(self):
        client = make_group_client()
        await upsert_group_asset(client, {"name": "inoc 2026-05-22", "draft_id": "d2"})
        _, body = client["_calls"]["post"][0]
        assert body["data"]["attributes"]["notes"]["value"] == "mushy:draft:d2"


class TestDeleteGroupAsset:
    async def test_delete_ok_returns_http_status(self):
        client = make_group_client()
        r = await delete_group_asset(client, "group-123")
        assert r["ok"] is True
        assert r["http_status"] == 204
        assert client["_calls"]["delete"][0] == "/api/asset/group/group-123"

    async def test_delete_failure_returns_http_reason(self):
        client = make_group_client(
            delete_impl=lambda p: _ok(404, {"errors": [{}]})
        )
        r = await delete_group_asset(client, "group-gone")
        assert r["ok"] is False
        assert r["reason"] == "http_404"
        assert r["http_status"] == 404

    async def test_delete_invalidates_name_cache(self):
        get_call_count = [0]

        def _get_impl(path: str) -> dict:
            get_call_count[0] += 1
            if get_call_count[0] == 1:
                return _ok(200, {"data": [{"id": "group-zzz"}]})
            return _ok(200, {"data": []})

        client = make_group_client(get_impl=_get_impl)
        r1 = await find_group_asset_by_name(client, "inoc 2026-05-22")
        assert r1["asset_id"] == "group-zzz"
        # Delete it
        await delete_group_asset(client, "group-zzz")
        # Subsequent lookup must re-fetch (cache evicted)
        r2 = await find_group_asset_by_name(client, "inoc 2026-05-22")
        assert r2["found"] is False
        assert get_call_count[0] == 2

    async def test_missing_asset_id_returns_error(self):
        client = make_group_client()
        r = await delete_group_asset(client, "")
        assert r["ok"] is False
        assert r["reason"] == "missing_asset_id"

    async def test_no_delete_method_returns_error(self):
        client = {"get": make_group_client()["get"], "post": make_group_client()["post"]}
        r = await delete_group_asset(client, "group-xyz")
        assert r["ok"] is False
        assert r["reason"] == "client_delete_unavailable"
