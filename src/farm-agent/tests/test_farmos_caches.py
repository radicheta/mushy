"""
tests/test_farmos_caches.py -- Unit tests for farmos/fungi_type_cache.py and
farmos/fungi_xing_cache.py.

Port of Node farmos/fungi-type-cache.js and farmos/fungi-xing-cache.js.

Covers (plan 62-05 acceptance criteria):
  - get_fungi_type_uuid hit caches name->uuid; second call returns cached=True without GET
  - get_fungi_type_uuid on 404 returns fungi_type_taxonomy_missing
  - get_fungi_type_uuid on empty data returns fungi_type_not_found
  - ensure_fungi_type_uuid create=False on not_found: passes through not_found
  - ensure_fungi_type_uuid create=True on not_found: POSTs and returns created uuid
  - get_fungi_xing_uuid mirrors fungi_type but with fungi_xing_not_found reason
  - LRU eviction: cap-16 for fungi_type, cap-4 for fungi_xing
  - Reason strings match Node verbatim
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fake client helpers
# ---------------------------------------------------------------------------


def _ok_resp(data: list | dict) -> dict:
    return {"ok": True, "status": 200, "body": {"data": data}, "latency_ms": 5}


def _not_found_resp() -> dict:
    return {"ok": True, "status": 200, "body": {"data": []}, "latency_ms": 5}


def _http_404_resp() -> dict:
    return {"ok": False, "status": 404, "body": None, "latency_ms": 5}


def _http_503_resp() -> dict:
    return {"ok": False, "status": 503, "body": None, "latency_ms": 5}


def _post_ok_resp(uuid: str) -> dict:
    return {
        "ok": True,
        "status": 201,
        "body": {"data": {"id": uuid}},
        "latency_ms": 5,
    }


def _make_recording_client(get_seq: list[dict], post_seq: list[dict] | None = None) -> tuple[dict, list, list]:
    """Return (client, get_calls, post_calls)."""
    get_calls: list[str] = []
    post_calls: list[dict] = []
    gets = list(get_seq)
    posts = list(post_seq or [])

    async def fake_get(path: str, opts=None) -> dict:
        get_calls.append(path)
        return gets.pop(0)

    async def fake_post(path: str, body=None, opts=None) -> dict:
        post_calls.append({"path": path, "body": body})
        return posts.pop(0)

    return {"get": fake_get, "post": fake_post}, get_calls, post_calls


# ---------------------------------------------------------------------------
# fungi_type_cache tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear LRU caches before each test for isolation."""
    from farm_agent.farmos import fungi_type_cache, fungi_xing_cache

    fungi_type_cache._clear()
    fungi_xing_cache._clear()
    yield
    fungi_type_cache._clear()
    fungi_xing_cache._clear()


@pytest.mark.asyncio
async def test_get_fungi_type_uuid_hit():
    """Resolved uuid returned with ok:True."""
    from farm_agent.farmos.fungi_type_cache import get_fungi_type_uuid

    client, get_calls, _ = _make_recording_client([_ok_resp([{"id": "uuid-koy"}])])
    r = await get_fungi_type_uuid(client, "KOY")

    assert r["ok"] is True
    assert r["uuid"] == "uuid-koy"
    assert len(get_calls) == 1


@pytest.mark.asyncio
async def test_get_fungi_type_uuid_cached_no_second_get():
    """Second call for same name uses cache, makes NO second GET."""
    from farm_agent.farmos.fungi_type_cache import get_fungi_type_uuid

    client, get_calls, _ = _make_recording_client([_ok_resp([{"id": "uuid-koy"}])])
    r1 = await get_fungi_type_uuid(client, "KOY")
    r2 = await get_fungi_type_uuid(client, "KOY")

    assert r1["ok"] is True
    assert r2["ok"] is True
    assert r2.get("cached") is True
    # Only ONE GET was made across two calls
    assert len(get_calls) == 1


@pytest.mark.asyncio
async def test_get_fungi_type_uuid_404_taxonomy_missing():
    """404 response returns fungi_type_taxonomy_missing reason."""
    from farm_agent.farmos.fungi_type_cache import get_fungi_type_uuid

    client, get_calls, _ = _make_recording_client([_http_404_resp()])
    r = await get_fungi_type_uuid(client, "GHOST")

    assert r["ok"] is False
    assert r["reason"] == "fungi_type_taxonomy_missing"


@pytest.mark.asyncio
async def test_get_fungi_type_uuid_empty_data_not_found():
    """Empty data array returns fungi_type_not_found reason."""
    from farm_agent.farmos.fungi_type_cache import get_fungi_type_uuid

    client, get_calls, _ = _make_recording_client([_not_found_resp()])
    r = await get_fungi_type_uuid(client, "NEWSTRAIN")

    assert r["ok"] is False
    assert r["reason"] == "fungi_type_not_found"


@pytest.mark.asyncio
async def test_get_fungi_type_uuid_http_error():
    """Non-404 HTTP error returns http_<status> reason."""
    from farm_agent.farmos.fungi_type_cache import get_fungi_type_uuid

    client, get_calls, _ = _make_recording_client([_http_503_resp()])
    r = await get_fungi_type_uuid(client, "KOY")

    assert r["ok"] is False
    assert r["reason"] == "http_503"


@pytest.mark.asyncio
async def test_ensure_fungi_type_uuid_create_false_passes_not_found():
    """create=False on not_found -> passes through not_found without POST."""
    from farm_agent.farmos.fungi_type_cache import ensure_fungi_type_uuid

    client, get_calls, post_calls = _make_recording_client(
        [_not_found_resp()], post_seq=[]
    )
    r = await ensure_fungi_type_uuid(client, "NEWSTRAIN", create=False)

    assert r["ok"] is False
    assert r["reason"] == "fungi_type_not_found"
    assert len(post_calls) == 0  # must NOT POST


@pytest.mark.asyncio
async def test_ensure_fungi_type_uuid_create_true_posts_and_returns_uuid():
    """create=True on not_found -> POSTs taxonomy_term/fungi_type and returns uuid."""
    from farm_agent.farmos.fungi_type_cache import ensure_fungi_type_uuid

    client, get_calls, post_calls = _make_recording_client(
        [_not_found_resp()],
        post_seq=[_post_ok_resp("new-uuid-123")],
    )
    r = await ensure_fungi_type_uuid(client, "BRAND_NEW", create=True)

    assert r["ok"] is True
    assert r["uuid"] == "new-uuid-123"
    assert r.get("created") is True
    assert len(post_calls) == 1
    assert "fungi_type" in post_calls[0]["path"]


@pytest.mark.asyncio
async def test_ensure_fungi_type_uuid_create_true_taxonomy_missing_passes_through():
    """create=True on taxonomy_missing (404) -> passes through (infrastructure error)."""
    from farm_agent.farmos.fungi_type_cache import ensure_fungi_type_uuid

    client, get_calls, post_calls = _make_recording_client([_http_404_resp()])
    r = await ensure_fungi_type_uuid(client, "KOY", create=True)

    assert r["ok"] is False
    assert r["reason"] == "fungi_type_taxonomy_missing"
    assert len(post_calls) == 0


@pytest.mark.asyncio
async def test_ensure_fungi_type_uuid_existing_hit_no_post():
    """ensure on existing term -> returns existing uuid without POST."""
    from farm_agent.farmos.fungi_type_cache import ensure_fungi_type_uuid

    client, get_calls, post_calls = _make_recording_client(
        [_ok_resp([{"id": "existing-uuid"}])]
    )
    r = await ensure_fungi_type_uuid(client, "KOY", create=True)

    assert r["ok"] is True
    assert r["uuid"] == "existing-uuid"
    assert len(post_calls) == 0


# ---------------------------------------------------------------------------
# fungi_xing_cache tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_fungi_xing_uuid_hit():
    """Resolved uuid returned with ok:True."""
    from farm_agent.farmos.fungi_xing_cache import get_fungi_xing_uuid

    client, get_calls, _ = _make_recording_client([_ok_resp([{"id": "uuid-block"}])])
    r = await get_fungi_xing_uuid(client, "block")

    assert r["ok"] is True
    assert r["uuid"] == "uuid-block"


@pytest.mark.asyncio
async def test_get_fungi_xing_uuid_cached_no_second_get():
    """Second call uses cache, no second GET."""
    from farm_agent.farmos.fungi_xing_cache import get_fungi_xing_uuid

    client, get_calls, _ = _make_recording_client([_ok_resp([{"id": "uuid-block"}])])
    await get_fungi_xing_uuid(client, "block")
    r2 = await get_fungi_xing_uuid(client, "block")

    assert r2["ok"] is True
    assert r2.get("cached") is True
    assert len(get_calls) == 1


@pytest.mark.asyncio
async def test_get_fungi_xing_uuid_not_found():
    """Empty data returns fungi_xing_not_found reason (verbatim Node reason string)."""
    from farm_agent.farmos.fungi_xing_cache import get_fungi_xing_uuid

    client, get_calls, _ = _make_recording_client([_not_found_resp()])
    r = await get_fungi_xing_uuid(client, "unknown")

    assert r["ok"] is False
    assert r["reason"] == "fungi_xing_not_found"


@pytest.mark.asyncio
async def test_get_fungi_xing_uuid_taxonomy_missing():
    """404 returns fungi_xing_taxonomy_missing reason."""
    from farm_agent.farmos.fungi_xing_cache import get_fungi_xing_uuid

    client, get_calls, _ = _make_recording_client([_http_404_resp()])
    r = await get_fungi_xing_uuid(client, "block")

    assert r["ok"] is False
    assert r["reason"] == "fungi_xing_taxonomy_missing"


# ---------------------------------------------------------------------------
# LRU eviction tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fungi_type_lru_eviction_cap_16():
    """fungi_type cache evicts oldest when size exceeds cap 16."""
    from farm_agent.farmos.fungi_type_cache import _clear, _cache_size, get_fungi_type_uuid

    _clear()
    # Insert 17 distinct entries
    for i in range(17):
        client, _, _ = _make_recording_client([_ok_resp([{"id": f"uuid-{i}"}])])
        await get_fungi_type_uuid(client, f"STRAIN{i}")

    # Cache size must not exceed 16
    assert _cache_size() <= 16


@pytest.mark.asyncio
async def test_fungi_xing_lru_eviction_cap_4():
    """fungi_xing cache evicts oldest when size exceeds cap 4."""
    from farm_agent.farmos.fungi_xing_cache import _clear, _cache_size, get_fungi_xing_uuid

    _clear()
    for i in range(5):
        client, _, _ = _make_recording_client([_ok_resp([{"id": f"uuid-{i}"}])])
        await get_fungi_xing_uuid(client, f"xing{i}")

    assert _cache_size() <= 4
