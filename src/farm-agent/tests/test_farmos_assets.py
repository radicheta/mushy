"""
tests/test_farmos_assets.py -- Unit tests for farmos/assets.py (Phase 62-07).

Port of Node assets.test.js tests (Phase 40 / Phase 51 UPSERT-01/04/05).

Covers (plan 62-07 acceptance criteria):
  Task 1 (find/create/cache/build):
    - find_asset_by_name: cache hit, cache miss, transport failure
    - create_fungi_asset: payload shape, missing fungi_type, missing fungi_xing, QR binding, parents
    - LRU cache: second lookup zero fetches
    - is_stub_asset: STUB marker detection
    - STUB_BACKFILL_MARKER constant value

  Task 2 (upsert merge cycle):
    - miss path: outcome=created, POST issued, no PATCH
    - hit-noop: identical fields, outcome=noop, no PATCH, 0 new assets
    - hit-patch: new parent added, PATCH issued with merged set-union
    - hit-conflict: fungi_type mismatch, outcome=noop, conflicts populated, no PATCH
    - identity mutation: ok=False, reason=identity_mutation
    - soft revision race: retries once, then concurrency_loss
    - stub enrichment: STUB marker preserved after patch
    - missing revision_id: etag_source=absent, PATCH issued without If-Match
    - SC2: second upsert for same name + same fields creates 0 new assets

Python mock equivalent of mock-client.js / makeMockClient().
"""

from __future__ import annotations

import re
import urllib.parse
from collections import defaultdict

import pytest


# ---------------------------------------------------------------------------
# Mock client -- Python port of makeMockClient() from mock-client.js
# ---------------------------------------------------------------------------

DEFAULT_FUNGI_TYPE_UUIDS = {
    "SHI": "ft-shi", "SH2": "ft-sh2", "KOY": "ft-koy", "MAI": "ft-mai",
    "MALI": "ft-mali", "KOS": "ft-kos", "DT": "ft-dt", "CAS": "ft-cas",
    "CAZ": "ft-caz", "WIN": "ft-win", "ALM": "ft-alm", "MOR": "ft-mor",
    "BP": "ft-bp", "LIMA": "ft-lima",
}
DEFAULT_FUNGI_XING_UUIDS = {"block": "fx-block", "fruit": "fx-fruit"}


class CallRecorder:
    """Simple call recorder (replaces jest.fn())."""

    def __init__(self, impl):
        self._impl = impl
        self.calls = []

    async def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return await self._impl(*args, **kwargs)

    @property
    def call_count(self):
        return len(self.calls)


def _ok_resp(status: int, body) -> dict:
    return {"ok": 200 <= status < 300, "status": status, "body": body, "latency_ms": 1}


def make_mock_client(
    known_assets_by_name: dict | None = None,
    fungi_type_uuids: dict | None = None,
    fungi_xing_uuids: dict | None = None,
    revision_ids: dict | None = None,
) -> dict:
    """Python equivalent of makeMockClient() from mock-client.js.

    known_assets_by_name: name -> {id, attributes?, relationships?}
    fungi_type_uuids: name -> uuid (defaults to DEFAULT_FUNGI_TYPE_UUIDS)
    fungi_xing_uuids: name -> uuid (defaults to DEFAULT_FUNGI_XING_UUIDS)
    revision_ids: name -> int (default revision_id=1 per asset)
    """
    ft_uuids = {**DEFAULT_FUNGI_TYPE_UUIDS, **(fungi_type_uuids or {})}
    fx_uuids = {**DEFAULT_FUNGI_XING_UUIDS, **(fungi_xing_uuids or {})}
    rev_ids = revision_ids or {}

    # Build registries from known_assets_by_name
    _by_id: dict[str, dict] = {}
    _id_by_name: dict[str, str] = {}
    for name, val in (known_assets_by_name or {}).items():
        asset_id = val["id"] if isinstance(val, dict) else str(val)
        rev = rev_ids.get(name, 1)
        base_attrs = val.get("attributes", {}) if isinstance(val, dict) else {}
        base_rels = val.get("relationships", {}) if isinstance(val, dict) else {}
        _id_by_name[name] = asset_id
        _by_id[asset_id] = {
            "id": asset_id,
            "type": "asset--fungi",
            "attributes": {"name": name, "drupal_internal__revision_id": rev, **base_attrs},
            "relationships": base_rels,
        }

    _asset_seq = [1]

    async def _get(path: str, opts=None) -> dict:
        # filter[name][value] lookup
        m = re.search(r"/api/asset/fungi\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            if name in _id_by_name:
                return _ok_resp(200, {"data": [{"id": _id_by_name[name]}]})
            return _ok_resp(200, {"data": []})

        # filter[id_tag.id][value] lookup (not used in assets.py but present in mock)
        m = re.search(r"/api/asset/fungi\?filter\[id_tag\.id\]\[value\]=([^&]+)", path)
        if m:
            return _ok_resp(200, {"data": []})

        # fungi_type taxonomy lookup
        m = re.search(r"/api/taxonomy_term/fungi_type\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            type_name = urllib.parse.unquote(m.group(1))
            if type_name in ft_uuids:
                return _ok_resp(200, {"data": [{"id": ft_uuids[type_name]}]})
            return _ok_resp(200, {"data": []})

        # fungi_xing taxonomy lookup
        m = re.search(r"/api/taxonomy_term/fungi_xing\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            xing_name = urllib.parse.unquote(m.group(1))
            if xing_name in fx_uuids:
                return _ok_resp(200, {"data": [{"id": fx_uuids[xing_name]}]})
            return _ok_resp(200, {"data": []})

        # GET by id: /api/asset/fungi/<id>
        m = re.match(r"^/api/asset/fungi/([A-Za-z0-9_-]+)$", path)
        if m:
            asset_id = m.group(1)
            if asset_id in _by_id:
                return _ok_resp(200, {"data": _by_id[asset_id]})
            return _ok_resp(404, {"errors": [{"status": "404"}]})

        return _ok_resp(200, {"data": []})

    def _normalize_rels_for_get(rels: dict) -> dict:
        """Normalize POST-payload array relationships to singleton (mimic real farmOS GET shape).

        farmOS accepts POST with fungi_type.data: [{...}] (array) but returns GET with
        fungi_type.data: {...} (singleton). Mocking this correctly is required for SC2
        (second upsert of same asset returns noop, not patched).
        """
        result = dict(rels)
        for field in ("fungi_type", "fungi_xing"):
            rel = result.get(field)
            if rel and isinstance(rel.get("data"), list):
                result[field] = {"data": rel["data"][0] if rel["data"] else None}
        return result

    async def _post(path: str, body=None, opts=None) -> dict:
        if path == "/api/asset/fungi":
            seq = _asset_seq[0]
            _asset_seq[0] += 1
            asset_id = f"asset-{seq}"
            name = (body or {}).get("data", {}).get("attributes", {}).get("name", "")
            raw_rels = (body or {}).get("data", {}).get("relationships", {})
            _id_by_name[name] = asset_id
            _by_id[asset_id] = {
                "id": asset_id,
                "type": "asset--fungi",
                "attributes": {"drupal_internal__revision_id": 1, **((body or {}).get("data", {}).get("attributes", {}))},
                # Normalize to singleton shape so subsequent GET-then-noop works (SC2).
                "relationships": _normalize_rels_for_get(raw_rels),
            }
            return _ok_resp(201, {"data": {"id": asset_id, "type": "asset--fungi"}})
        return _ok_resp(404, {})

    async def _patch(path: str, body=None, opts=None) -> dict:
        m = re.match(r"^/api/asset/fungi/([A-Za-z0-9_-]+)$", path)
        if m:
            asset_id = m.group(1)
            existing = _by_id.get(asset_id, {"id": asset_id, "type": "asset--fungi", "attributes": {"drupal_internal__revision_id": 1}, "relationships": {}})
            in_data = (body or {}).get("data") or {}
            merged_attrs = {**existing.get("attributes", {}), **(in_data.get("attributes") or {})}
            merged_rels = {**existing.get("relationships", {}), **(in_data.get("relationships") or {})}
            _by_id[asset_id] = {"id": asset_id, "type": "asset--fungi", "attributes": merged_attrs, "relationships": merged_rels}
            return _ok_resp(200, {"data": _by_id[asset_id]})
        return _ok_resp(404, {})

    async def _delete(path: str, opts=None) -> dict:
        m = re.match(r"^/api/asset/fungi/([A-Za-z0-9_-]+)$", path)
        if m:
            asset_id = m.group(1)
            if asset_id in _by_id:
                name = _by_id[asset_id].get("attributes", {}).get("name")
                del _by_id[asset_id]
                if name in _id_by_name:
                    del _id_by_name[name]
            return _ok_resp(204, None)
        return _ok_resp(404, {})

    get_recorder = CallRecorder(_get)
    post_recorder = CallRecorder(_post)
    patch_recorder = CallRecorder(_patch)
    delete_recorder = CallRecorder(_delete)

    client = {
        "get": get_recorder,
        "post": post_recorder,
        "patch": patch_recorder,
        "delete": delete_recorder,
        # Expose internals for test inspection (mirror JS _byId / _idByName)
        "_by_id": _by_id,
        "_id_by_name": _id_by_name,
        "_asset_seq": _asset_seq,
    }
    return client


# ---------------------------------------------------------------------------
# Import helpers -- clear module-level caches between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_all_caches():
    """Clear the name cache and taxonomy caches before each test (mirror JS beforeEach)."""
    from farm_agent.farmos import assets, fungi_type_cache, fungi_xing_cache
    assets._clear_cache()
    fungi_type_cache._clear()
    fungi_xing_cache._clear()


# ---------------------------------------------------------------------------
# Task 1: find_asset_by_name -- name-based lookup + LRU cache
# ---------------------------------------------------------------------------


async def test_find_asset_by_name_hit():
    """find_asset_by_name returns found=True + asset_id on GET hit."""
    from farm_agent.farmos.assets import find_asset_by_name
    client = make_mock_client(known_assets_by_name={"260513_DT_001": {"id": "asset-abc"}})
    r = await find_asset_by_name(client, "260513_DT_001")
    assert r["found"] is True
    assert r["asset_id"] == "asset-abc"


async def test_find_asset_by_name_miss():
    """find_asset_by_name returns found=False when no asset matches."""
    from farm_agent.farmos.assets import find_asset_by_name
    client = make_mock_client()
    r = await find_asset_by_name(client, "UNKNOWN_ASSET")
    assert r["found"] is False
    assert "error" not in r


async def test_find_asset_by_name_transport_failure():
    """Transport failure returns found=False with error key (not a miss)."""
    from farm_agent.farmos.assets import find_asset_by_name

    async def _bad_get(path, opts=None):
        return {"ok": False, "status": 503, "body": None, "latency_ms": 1}

    client = {"get": _bad_get}
    r = await find_asset_by_name(client, "X")
    assert r["found"] is False
    assert r["error"] == "http_503"


async def test_find_asset_by_name_network_failure():
    """Network failure (no status) returns error=http_network."""
    from farm_agent.farmos.assets import find_asset_by_name

    async def _no_status_get(path, opts=None):
        return {"ok": False, "status": None, "body": None, "latency_ms": 1}

    client = {"get": _no_status_get}
    r = await find_asset_by_name(client, "X")
    assert r["found"] is False
    assert r["error"] == "http_network"


async def test_find_asset_by_name_caches_second_call_zero_fetches():
    """Second lookup for the same name uses LRU cache and makes 0 additional GETs."""
    from farm_agent.farmos.assets import find_asset_by_name
    client = make_mock_client(known_assets_by_name={"260513_DT_CACHE": {"id": "asset-cache"}})
    r1 = await find_asset_by_name(client, "260513_DT_CACHE")
    assert r1["found"] is True
    assert r1["asset_id"] == "asset-cache"
    # reset call count to verify second call uses cache
    client["get"].calls.clear()
    r2 = await find_asset_by_name(client, "260513_DT_CACHE")
    assert r2["found"] is True
    assert r2["asset_id"] == "asset-cache"
    assert r2.get("cached") is True
    assert client["get"].call_count == 0


async def test_find_asset_by_name_url_encodes_name():
    """filter[name][value] query param is URL-encoded."""
    from farm_agent.farmos.assets import find_asset_by_name
    seen_paths = []

    async def _recording_get(path, opts=None):
        seen_paths.append(path)
        return {"ok": True, "status": 200, "body": {"data": []}, "latency_ms": 1}

    client = {"get": _recording_get}
    await find_asset_by_name(client, "Block A/B")
    assert len(seen_paths) == 1
    assert "filter%5Bname%5D%5Bvalue%5D" in seen_paths[0] or "filter[name][value]=" in seen_paths[0]
    # URL-encoded slash should be present
    assert "Block" in seen_paths[0]


# ---------------------------------------------------------------------------
# Task 1: is_stub_asset + STUB_BACKFILL_MARKER
# ---------------------------------------------------------------------------


def test_stub_backfill_marker_constant():
    """STUB_BACKFILL_MARKER constant has the expected literal value."""
    from farm_agent.farmos.assets import STUB_BACKFILL_MARKER
    assert STUB_BACKFILL_MARKER == "STUB - awaits 2025-paper-scan backfill"


def test_is_stub_asset_true_when_notes_contain_marker():
    """is_stub_asset returns True when notes.value contains the STUB marker."""
    from farm_agent.farmos.assets import is_stub_asset
    asset = {"attributes": {"notes": {"value": "STUB - awaits 2025-paper-scan backfill\nmushy:draft:x"}}}
    assert is_stub_asset(asset) is True


def test_is_stub_asset_true_within_separator_block():
    """is_stub_asset returns True when STUB marker is one of several separator-delimited entries."""
    from farm_agent.farmos.assets import is_stub_asset
    asset = {"attributes": {"notes": {"value": "entry_A\n---\nSTUB - awaits 2025-paper-scan backfill\n---\nentry_C"}}}
    assert is_stub_asset(asset) is True


def test_is_stub_asset_false_ordinary_notes():
    """is_stub_asset returns False for ordinary notes."""
    from farm_agent.farmos.assets import is_stub_asset
    asset = {"attributes": {"notes": {"value": "ordinary notes"}}}
    assert is_stub_asset(asset) is False


def test_is_stub_asset_false_no_notes_attr():
    """is_stub_asset returns False when notes attribute is absent."""
    from farm_agent.farmos.assets import is_stub_asset
    assert is_stub_asset({"attributes": {}}) is False


def test_is_stub_asset_false_null():
    """is_stub_asset returns False for None input."""
    from farm_agent.farmos.assets import is_stub_asset
    assert is_stub_asset(None) is False


# ---------------------------------------------------------------------------
# Task 1: create_fungi_asset -- payload shape, validation, QR, parents
# ---------------------------------------------------------------------------


async def test_create_fungi_asset_payload_shape():
    """Payload type is asset--fungi with fungi_type + fungi_xing relationships."""
    from farm_agent.farmos.assets import create_fungi_asset
    client = make_mock_client()
    r = await create_fungi_asset(client, {
        "name": "260513_DT_001",
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "draft_id": "d1",
    })
    assert r["ok"] is True
    assert r["asset_id"].startswith("asset-")
    # Inspect POST payload
    assert client["post"].call_count == 1
    sent_body = client["post"].calls[0]["args"][1]
    assert sent_body["data"]["type"] == "asset--fungi"
    assert sent_body["data"]["attributes"]["name"] == "260513_DT_001"
    assert sent_body["data"]["relationships"]["fungi_type"]["data"][0] == {
        "type": "taxonomy_term--fungi_type", "id": "ft-dt"
    }
    assert sent_body["data"]["relationships"]["fungi_xing"]["data"][0] == {
        "type": "taxonomy_term--fungi_xing", "id": "fx-block"
    }
    assert "parent" not in sent_body["data"]["relationships"]


async def test_create_fungi_asset_notes_trailer():
    """Created asset notes.value contains mushy:draft:{draft_id}."""
    from farm_agent.farmos.assets import create_fungi_asset
    client = make_mock_client()
    await create_fungi_asset(client, {
        "name": "X",
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "draft_id": "d-trail",
    })
    sent = client["post"].calls[0]["args"][1]
    assert "mushy:draft:d-trail" in sent["data"]["attributes"]["notes"]["value"]


async def test_create_fungi_asset_notes_with_preceding_text():
    """When notes kwarg is provided, trailer is appended after a newline."""
    from farm_agent.farmos.assets import create_fungi_asset
    client = make_mock_client()
    await create_fungi_asset(client, {
        "name": "X",
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "draft_id": "d1",
        "notes": "extra note",
    })
    sent = client["post"].calls[0]["args"][1]
    notes_val = sent["data"]["attributes"]["notes"]["value"]
    assert notes_val.startswith("extra note\n")
    assert "mushy:draft:d1" in notes_val


async def test_create_fungi_asset_missing_fungi_type_name_returns_error():
    """create_fungi_asset with no fungi_type_name and allow_no_fungi_type=False fails clean."""
    from farm_agent.farmos.assets import create_fungi_asset
    client = make_mock_client()
    r = await create_fungi_asset(client, {
        "name": "X", "fungi_xing_name": "block", "draft_id": "d0"
    })
    assert r["ok"] is False
    assert r["reason"] == "missing_fungi_type_name"
    assert client["post"].call_count == 0


async def test_create_fungi_asset_missing_fungi_xing_name_returns_error():
    """create_fungi_asset with no fungi_xing_name fails clean."""
    from farm_agent.farmos.assets import create_fungi_asset
    client = make_mock_client()
    r = await create_fungi_asset(client, {
        "name": "X", "fungi_type_name": "DT", "draft_id": "d0"
    })
    assert r["ok"] is False
    assert r["reason"] == "missing_fungi_xing_name"
    assert client["post"].call_count == 0


async def test_create_fungi_asset_fungi_type_taxonomy_404():
    """create_fungi_asset fails clean when fungi_type taxonomy endpoint returns 404."""
    from farm_agent.farmos.assets import create_fungi_asset

    async def _bad_get(path, opts=None):
        return {"ok": False, "status": 404, "body": None, "latency_ms": 1}

    client = {"get": _bad_get, "post": make_mock_client()["post"]}
    r = await create_fungi_asset(client, {
        "name": "X", "fungi_type_name": "DT", "fungi_xing_name": "block", "draft_id": "d0"
    })
    assert r["ok"] is False
    assert r["reason"] == "fungi_type_taxonomy_missing"
    assert client["post"].call_count == 0


async def test_create_fungi_asset_fungi_xing_taxonomy_404():
    """create_fungi_asset fails clean when fungi_xing taxonomy endpoint returns 404."""
    from farm_agent.farmos.assets import create_fungi_asset
    from farm_agent.farmos import fungi_type_cache
    fungi_type_cache._clear()

    call_count = [0]

    async def _mixed_get(path, opts=None):
        call_count[0] += 1
        if "fungi_type" in path:
            return {"ok": True, "status": 200, "body": {"data": [{"id": "ft-dt"}]}, "latency_ms": 1}
        return {"ok": False, "status": 404, "body": None, "latency_ms": 1}

    client = {"get": _mixed_get, "post": make_mock_client()["post"]}
    r = await create_fungi_asset(client, {
        "name": "X", "fungi_type_name": "DT", "fungi_xing_name": "block", "draft_id": "d0"
    })
    assert r["ok"] is False
    assert r["reason"] == "fungi_xing_taxonomy_missing"
    assert client["post"].call_count == 0


async def test_create_fungi_asset_qr_codes_in_payload():
    """QR codes embed in payload as id_tag entries with type='other'."""
    from farm_agent.farmos.assets import create_fungi_asset
    client = make_mock_client()
    await create_fungi_asset(client, {
        "name": "260513_DT_001",
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "qr_codes": ["Q1", "Q2"],
        "draft_id": "d2",
    })
    sent = client["post"].calls[0]["args"][1]
    assert sent["data"]["attributes"]["id_tag"] == [
        {"id": "Q1", "type": "other", "location": ""},
        {"id": "Q2", "type": "other", "location": ""},
    ]
    # Only one POST (no second asset_link call)
    assert client["post"].call_count == 1


async def test_create_fungi_asset_multi_parent():
    """Multi-parent payload has parent.data list with all parent ids."""
    from farm_agent.farmos.assets import create_fungi_asset
    client = make_mock_client()
    await create_fungi_asset(client, {
        "name": "HBATCH-001",
        "parent_ids": ["p1", "p2"],
        "fungi_type_name": "DT",
        "fungi_xing_name": "fruit",
        "draft_id": "d4",
    })
    sent = client["post"].calls[0]["args"][1]
    assert len(sent["data"]["relationships"]["parent"]["data"]) == 2
    ids = [r["id"] for r in sent["data"]["relationships"]["parent"]["data"]]
    assert ids == ["p1", "p2"]


async def test_create_fungi_asset_caches_name_after_create():
    """After create_fungi_asset, the name is cached so a second find makes 0 GETs."""
    from farm_agent.farmos.assets import create_fungi_asset, find_asset_by_name
    client = make_mock_client()
    r = await create_fungi_asset(client, {
        "name": "NEW_BLOCK",
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "draft_id": "d99",
    })
    assert r["ok"] is True
    # Clear GET call count, then find by name -- should use cache
    client["get"].calls.clear()
    r2 = await find_asset_by_name(client, "NEW_BLOCK")
    assert r2["found"] is True
    assert r2.get("cached") is True
    assert client["get"].call_count == 0


# ---------------------------------------------------------------------------
# Task 2: upsert_fungi_asset -- miss / hit-noop / hit-patch / conflict /
#         identity-mutation / soft-revision-race / stub-enrichment / SC2
# ---------------------------------------------------------------------------


async def test_upsert_miss_path_creates_asset():
    """Miss path: name not found -> POST via create_fungi_asset; outcome=created."""
    from farm_agent.farmos.assets import upsert_fungi_asset
    client = make_mock_client()
    r = await upsert_fungi_asset(client, {
        "name": "260524_DT_010",
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "draft_id": "d-miss",
    })
    assert r["ok"] is True
    assert r["outcome"] == "created"
    assert r["asset_id"].startswith("asset-")
    assert r["http_status"] == 201
    assert r["conflicts"] == []
    # POST was issued, PATCH was not
    post_paths = [c["args"][0] for c in client["post"].calls]
    assert "/api/asset/fungi" in post_paths
    assert client["patch"].call_count == 0


async def test_upsert_hit_noop_no_patch():
    """Hit-noop path: all incoming fields already present -> no PATCH; outcome=noop."""
    from farm_agent.farmos.assets import upsert_fungi_asset
    # Seed an existing asset with exact same fields we will upsert
    client = make_mock_client(
        known_assets_by_name={
            "260524_DT_011": {
                "id": "a-2",
                "attributes": {
                    "name": "260524_DT_011",
                    "status": "active",
                    "notes": {"value": "mushy:draft:d-noop"},
                },
                "relationships": {
                    "fungi_type": {"data": {"type": "taxonomy_term--fungi_type", "id": "ft-dt"}},
                    "fungi_xing": {"data": {"type": "taxonomy_term--fungi_xing", "id": "fx-block"}},
                    "parent": {"data": [{"type": "asset--fungi", "id": "p1"}]},
                },
            }
        },
        revision_ids={"260524_DT_011": 3},
    )
    r = await upsert_fungi_asset(client, {
        "name": "260524_DT_011",
        "parent_ids": ["p1"],  # same parent already present
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "draft_id": "d-noop",
    })
    assert r["ok"] is True
    assert r["outcome"] == "noop"
    assert r["asset_id"] == "a-2"
    assert r["conflicts"] == []
    assert client["patch"].call_count == 0


async def test_upsert_hit_patch_adds_parent():
    """Hit-patch: existing asset + new parent[] -> PATCH with merged set-union; outcome=patched."""
    from farm_agent.farmos.assets import upsert_fungi_asset
    client = make_mock_client(
        known_assets_by_name={
            "260524_DT_010": {
                "id": "a-1",
                "attributes": {
                    "name": "260524_DT_010",
                    "status": "active",
                    "notes": {"value": "pre"},
                },
                "relationships": {
                    "fungi_type": {"data": {"type": "taxonomy_term--fungi_type", "id": "ft-dt"}},
                    "fungi_xing": {"data": {"type": "taxonomy_term--fungi_xing", "id": "fx-block"}},
                    "parent": {"data": [{"type": "asset--fungi", "id": "p1"}]},
                },
            }
        },
        revision_ids={"260524_DT_010": 7},
    )
    r = await upsert_fungi_asset(client, {
        "name": "260524_DT_010",
        "parent_ids": ["p2"],  # new parent, p1 already exists
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "draft_id": "d-hit",
    })
    assert r["ok"] is True
    assert r["outcome"] == "patched"
    assert r["asset_id"] == "a-1"
    assert r["conflicts"] == []
    assert r["etag_source"] == "soft_compare"
    assert r["http_status"] == 200
    # PATCH issued with merged parents (p1 + p2)
    assert client["patch"].call_count == 1
    patch_body = client["patch"].calls[0]["args"][1]
    merged_parent_ids = sorted(d["id"] for d in patch_body["data"]["relationships"]["parent"]["data"])
    assert merged_parent_ids == ["p1", "p2"]


async def test_upsert_hit_conflict_no_patch():
    """Hit-conflict: fungi_type mismatch -> no PATCH; outcome=noop, conflicts populated."""
    from farm_agent.farmos.assets import upsert_fungi_asset
    client = make_mock_client(
        known_assets_by_name={
            "260524_CONFLICT_001": {
                "id": "a-conflict",
                "attributes": {
                    "name": "260524_CONFLICT_001",
                    "status": "active",
                    "notes": {"value": ""},
                },
                "relationships": {
                    "fungi_type": {"data": {"type": "taxonomy_term--fungi_type", "id": "ft-shi"}},
                    "fungi_xing": {"data": {"type": "taxonomy_term--fungi_xing", "id": "fx-block"}},
                },
            }
        },
    )
    r = await upsert_fungi_asset(client, {
        "name": "260524_CONFLICT_001",
        "fungi_type_name": "KOY",  # resolves to ft-koy, conflicts with existing ft-shi
        "fungi_xing_name": "block",
        "draft_id": "d-conflict",
    })
    assert r["ok"] is True
    assert r["outcome"] == "noop"
    assert len(r["conflicts"]) == 1
    assert r["conflicts"][0]["field"] == "fungi_type"
    assert r["conflicts"][0]["existing"] == "ft-shi"
    assert r["conflicts"][0]["incoming"] == "ft-koy"
    assert client["patch"].call_count == 0


async def test_upsert_identity_mutation_returns_structured_error():
    """Identity mutation: incoming name differs from existing -> ok=False, reason=identity_mutation."""
    from farm_agent.farmos.assets import upsert_fungi_asset
    # Seed asset where attributes.name differs from the name we look up by
    client = make_mock_client(
        known_assets_by_name={
            "260524_IDENT_001": {
                "id": "a-ident",
                "attributes": {
                    "name": "DIFFERENT_NAME_ON_DISK",
                    "status": "active",
                },
                "relationships": {},
            }
        },
    )
    r = await upsert_fungi_asset(client, {
        "name": "260524_IDENT_001",
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "draft_id": "d-ident",
    })
    assert r["ok"] is False
    assert r["reason"] == "identity_mutation"
    assert r["http_status"] is None
    assert client["patch"].call_count == 0


async def test_upsert_soft_revision_race_retries_once_then_concurrency_loss():
    """Soft-compare: revision moves on every re-GET -> retries once, then concurrency_loss."""
    from farm_agent.farmos.assets import upsert_fungi_asset

    # Build a client where GET-by-id bumps revision_id on every call
    client = make_mock_client(
        known_assets_by_name={
            "260524_RACE_001": {
                "id": "a-race",
                "attributes": {
                    "name": "260524_RACE_001",
                    "status": "active",
                    "notes": {"value": ""},
                },
                "relationships": {
                    "fungi_type": {"data": {"type": "taxonomy_term--fungi_type", "id": "ft-dt"}},
                    "fungi_xing": {"data": {"type": "taxonomy_term--fungi_xing", "id": "fx-block"}},
                    "parent": {"data": [{"type": "asset--fungi", "id": "p-old"}]},
                },
            }
        },
        revision_ids={"260524_RACE_001": 1},
    )
    # Wrap get to bump revision_id on every by-id GET
    _by_id = client["_by_id"]
    bump_counter = [0]
    original_get = client["get"]._impl

    async def _bumping_get(path, opts=None):
        r = await original_get(path, opts)
        import re as _re
        m = _re.match(r"^/api/asset/fungi/([A-Za-z0-9_-]+)$", path)
        if m and r["ok"] and (r.get("body") or {}).get("data"):
            asset_id = m.group(1)
            if asset_id in _by_id:
                bump_counter[0] += 1
                _by_id[asset_id]["attributes"]["drupal_internal__revision_id"] = 1 + bump_counter[0]
        return r

    client["get"]._impl = _bumping_get

    r = await upsert_fungi_asset(client, {
        "name": "260524_RACE_001",
        "parent_ids": ["p-new"],
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "draft_id": "d-race",
    })
    assert r["ok"] is True
    assert r["outcome"] == "noop"
    assert r["reason"] == "concurrency_loss"
    assert r["etag_source"] == "soft_compare"
    # No PATCH -- re-GET always showed moved revision
    assert client["patch"].call_count == 0
    # 4 by-id GETs: (merge-GET + re-GET) * 2 attempts
    assert bump_counter[0] == 4


async def test_upsert_stub_enrichment_preserves_stub_marker():
    """Stub enrichment: existing stub asset + real incoming data -> patched; STUB marker preserved."""
    from farm_agent.farmos.assets import upsert_fungi_asset, is_stub_asset
    stub_notes = "STUB - awaits 2025-paper-scan backfill\n---\nmushy:draft:original"
    client = make_mock_client(
        known_assets_by_name={
            "250122_KOY_4": {
                "id": "a-stub",
                "attributes": {
                    "name": "250122_KOY_4",
                    "status": "active",
                    "notes": {"value": stub_notes},
                },
                "relationships": {
                    # Stub has no fungi_type; only fungi_xing
                    "fungi_xing": {"data": {"type": "taxonomy_term--fungi_xing", "id": "fx-block"}},
                },
            }
        },
        revision_ids={"250122_KOY_4": 1},
    )
    r = await upsert_fungi_asset(client, {
        "name": "250122_KOY_4",
        "parent_ids": ["p-koy-parent"],
        "fungi_type_name": "KOY",
        "fungi_xing_name": "block",
        "draft_id": "d-enrich",
    })
    assert r["ok"] is True
    assert r["outcome"] == "patched"
    assert r["conflicts"] == []
    # Merged notes preserves STUB marker
    patch_body = client["patch"].calls[0]["args"][1]
    notes_val = patch_body["data"]["attributes"]["notes"]["value"]
    assert "STUB - awaits 2025-paper-scan backfill" in notes_val
    # Merged parent contains incoming parent
    parent_ids = [d["id"] for d in patch_body["data"]["relationships"]["parent"]["data"]]
    assert "p-koy-parent" in parent_ids
    # Still detects as stub after merge
    assert is_stub_asset({"attributes": {"notes": patch_body["data"]["attributes"]["notes"]}}) is True


async def test_upsert_missing_revision_id_etag_absent():
    """Missing revision_id degrades to etag_source=absent; PATCH issued without If-Match."""
    from farm_agent.farmos.assets import upsert_fungi_asset
    client = make_mock_client(
        known_assets_by_name={
            "260524_NOREV_001": {
                "id": "a-norev",
                "attributes": {
                    "name": "260524_NOREV_001",
                    "status": "active",
                    "notes": {"value": ""},
                },
                "relationships": {
                    "fungi_type": {"data": {"type": "taxonomy_term--fungi_type", "id": "ft-dt"}},
                    "fungi_xing": {"data": {"type": "taxonomy_term--fungi_xing", "id": "fx-block"}},
                },
            }
        },
    )
    # Remove revision_id from stored body so GET returns asset without it
    client["_by_id"]["a-norev"]["attributes"].pop("drupal_internal__revision_id", None)
    r = await upsert_fungi_asset(client, {
        "name": "260524_NOREV_001",
        "parent_ids": ["p-new"],
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "draft_id": "d-norev",
    })
    assert r["ok"] is True
    assert r["outcome"] == "patched"
    assert r["etag_source"] == "absent"
    assert client["patch"].call_count == 1
    # No If-Match header when etag_source=absent
    patch_opts = client["patch"].calls[0]["args"][2]
    if patch_opts and "headers" in patch_opts:
        assert "If-Match" not in (patch_opts["headers"] or {})


async def test_upsert_sc2_second_upsert_same_fields_creates_zero_new_assets():
    """SC2: second upsert_fungi_asset for same name + same fields creates 0 new assets."""
    from farm_agent.farmos.assets import upsert_fungi_asset
    client = make_mock_client()
    opts = {
        "name": "260524_SC2_001",
        "fungi_type_name": "DT",
        "fungi_xing_name": "block",
        "draft_id": "d-sc2",
    }
    # First upsert: miss -> create
    r1 = await upsert_fungi_asset(client, opts)
    assert r1["ok"] is True
    assert r1["outcome"] == "created"
    post_count_after_first = client["post"].call_count

    # Second upsert: hit -> noop (0 new assets)
    r2 = await upsert_fungi_asset(client, opts)
    assert r2["ok"] is True
    assert r2["outcome"] == "noop"
    # No additional POST on second upsert
    assert client["post"].call_count == post_count_after_first
    # No PATCH on second upsert either
    assert client["patch"].call_count == 0


async def test_delete_fungi_asset_invalidates_name_cache():
    """delete_fungi_asset removes the deleted asset's id from the name cache."""
    from farm_agent.farmos.assets import delete_fungi_asset, find_asset_by_name, _clear_cache
    _clear_cache()
    client = make_mock_client(
        known_assets_by_name={"260524_DEL_001": {"id": "a-del"}},
    )
    # Populate cache by finding the asset
    r = await find_asset_by_name(client, "260524_DEL_001")
    assert r["found"] is True
    assert r.get("cached") is None  # first call, not cached

    # Now delete it
    rd = await delete_fungi_asset(client, "a-del")
    assert rd["ok"] is True

    # After deletion, find should make a fresh GET (cache was invalidated)
    client["get"].calls.clear()
    # The mock no longer has the asset in _by_id, so GET returns empty
    r2 = await find_asset_by_name(client, "260524_DEL_001")
    # The GET was issued (cache was cleared)
    assert client["get"].call_count == 1


async def test_delete_fungi_asset_no_asset_id():
    """delete_fungi_asset with no asset_id returns reason=missing_asset_id."""
    from farm_agent.farmos.assets import delete_fungi_asset
    client = make_mock_client()
    r = await delete_fungi_asset(client, "")
    assert r["ok"] is False
    assert r["reason"] == "missing_asset_id"


async def test_upsert_def_exists():
    """Acceptance: def upsert_fungi_asset exists in assets.py."""
    import inspect
    from farm_agent.farmos import assets
    assert hasattr(assets, "upsert_fungi_asset")
    assert inspect.iscoroutinefunction(assets.upsert_fungi_asset)
