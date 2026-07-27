"""Tests for commit_seeding.py (Phase 62-09).

Port of src/agents/alerter/test/farmos/commit-seeding.test.js.

All external I/O is mocked. No real network or DB calls.
"""
from __future__ import annotations

import re
import urllib.parse

import pytest

from farm_agent.farmos import assets as assets_mod
from farm_agent.farmos import fungi_type_cache, fungi_xing_cache
from farm_agent.farmos.commits.commit_seeding import commit_seeding

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

DEFAULT_FUNGI_TYPE_UUIDS = {
    "SHI": "ft-shi", "SH2": "ft-sh2", "KOY": "ft-koy", "MAI": "ft-mai",
    "MALI": "ft-mali", "KOS": "ft-kos", "DT": "ft-dt", "CAS": "ft-cas",
    "CAZ": "ft-caz", "WIN": "ft-win", "ALM": "ft-alm", "MOR": "ft-mor",
    "BP": "ft-bp", "LIMA": "ft-lima",
}
DEFAULT_FUNGI_XING_UUIDS = {"block": "fx-block", "fruit": "fx-fruit"}


def _ok(status: int, body) -> dict:
    return {"ok": 200 <= status < 300, "status": status, "body": body}


def make_seeding_mock_client(
    known_assets_by_qr: dict | None = None,
    known_assets_by_name: dict | None = None,
    fungi_type_uuids: dict | None = None,
    fungi_xing_uuids: dict | None = None,
) -> dict:
    """Mock client for commit_seeding tests.

    Supports:
    - QR lookup: GET /api/asset/fungi?filter[id_tag.id][value]=<qr>
    - Name lookup: GET /api/asset/fungi?filter[name][value]=<name>
    - Fungi type: GET /api/taxonomy_term/fungi_type?filter[name][value]=<name>
    - Fungi xing: GET /api/taxonomy_term/fungi_xing?filter[name][value]=<name>
    - GET /api/asset/fungi/<id>  (for upsert merge)
    - GET /api/log/seeding?filter[asset.id][value]=<id>  (stable key)
    - GET /api/log/seeding/<id>  (full log body for merge)
    - POST /api/asset/fungi
    - POST /api/log/seeding
    - PATCH /api/log/seeding/<id>
    """
    by_qr = dict(known_assets_by_qr or {})
    by_name_init = dict(known_assets_by_name or {})
    # None -> use defaults; {} -> empty (no strains resolve)
    ft_uuids = DEFAULT_FUNGI_TYPE_UUIDS if fungi_type_uuids is None else fungi_type_uuids
    fx_uuids = DEFAULT_FUNGI_XING_UUIDS if fungi_xing_uuids is None else fungi_xing_uuids

    created = {"assets": [], "logs": []}
    by_id: dict = {}
    id_by_name: dict = dict(by_name_init)
    asset_seq = [1]
    log_seq = [1]
    logs_by_asset_id: dict = {}  # asset_id -> {"id", "type", body}

    async def _get(path: str) -> dict:
        # QR tag lookup
        m = re.search(r"/api/asset/fungi\?filter\[id_tag\.id\]\[value\]=([^&]+)", path)
        if m:
            qr = urllib.parse.unquote(m.group(1))
            if qr in by_qr:
                return _ok(200, {"data": [{"id": by_qr[qr]}]})
            return _ok(200, {"data": []})

        # Fungi name lookup
        m = re.search(r"/api/asset/fungi\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            if name in id_by_name:
                return _ok(200, {"data": [{"id": id_by_name[name]}]})
            return _ok(200, {"data": []})

        # Fungi type taxonomy
        m = re.search(r"/api/taxonomy_term/fungi_type\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            if name in ft_uuids:
                return _ok(200, {"data": [{"id": ft_uuids[name]}]})
            return _ok(200, {"data": []})

        # Fungi xing taxonomy
        m = re.search(r"/api/taxonomy_term/fungi_xing\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            if name in fx_uuids:
                return _ok(200, {"data": [{"id": fx_uuids[name]}]})
            return _ok(200, {"data": []})

        # GET fungi asset by id
        m = re.search(r"^/api/asset/fungi/([A-Za-z0-9_-]+)$", path)
        if m:
            asset_id = m.group(1)
            if asset_id in by_id:
                return _ok(200, {"data": by_id[asset_id]})
            return _ok(404, {"errors": [{"status": "404"}]})

        # GET seeding log stable-key (filter by asset id)
        m = re.search(r"/api/log/seeding\?filter\[asset\.id\]\[value\]=([^&]+)", path)
        if m:
            asset_id = urllib.parse.unquote(m.group(1))
            if asset_id in logs_by_asset_id:
                lg = logs_by_asset_id[asset_id]
                return _ok(200, {"data": [{"id": lg["id"], "type": "log--seeding",
                                            "attributes": {"created": "2026-05-22T00:00:00Z",
                                                           **lg.get("attributes", {})},
                                            "relationships": lg.get("relationships", {})}]})
            return _ok(200, {"data": []})

        # GET seeding log by id (full body for merge)
        m = re.search(r"^/api/log/seeding/([A-Za-z0-9_-]+)$", path)
        if m:
            log_id = m.group(1)
            # find it
            for al in logs_by_asset_id.values():
                if al["id"] == log_id:
                    return _ok(200, {"data": {
                        "id": log_id,
                        "type": "log--seeding",
                        "attributes": {
                            "drupal_internal__revision_id": 1,
                            **al.get("attributes", {}),
                        },
                        "relationships": al.get("relationships", {}),
                    }})
            return _ok(404, {"errors": [{"status": "404"}]})

        return _ok(200, {"data": []})

    async def _post(path: str, body: dict, opts=None) -> dict:
        if path == "/api/asset/fungi":
            new_id = "asset-" + str(asset_seq[0])
            asset_seq[0] += 1
            name = (body.get("data") or {}).get("attributes", {}).get("name", "")
            entry = {"id": new_id, "name": name, "payload": body}
            created["assets"].append(entry)
            id_by_name[name] = new_id
            by_id[new_id] = {
                "id": new_id,
                "type": "asset--fungi",
                "attributes": {
                    "drupal_internal__revision_id": 1,
                    **((body.get("data") or {}).get("attributes") or {}),
                },
                "relationships": (body.get("data") or {}).get("relationships") or {},
            }
            return _ok(201, {"data": {"id": new_id, "type": "asset--fungi"}})

        if path == "/api/log/seeding":
            new_id = "log-" + str(log_seq[0])
            log_seq[0] += 1
            asset_data = (
                ((body.get("data") or {}).get("relationships") or {})
                .get("asset", {}).get("data") or []
            )
            entry = {"id": new_id, "type": "seeding", "payload": body}
            created["logs"].append(entry)
            # Record in stable-key map
            for ref in asset_data:
                aid = ref.get("id")
                if aid:
                    attrs = (body.get("data") or {}).get("attributes") or {}
                    logs_by_asset_id[aid] = {
                        "id": new_id,
                        "attributes": {"drupal_internal__revision_id": 1, **attrs},
                        "relationships": {"asset": {"data": asset_data}},
                    }
            return _ok(201, {"data": {"id": new_id, "type": "log--seeding"}})

        return _ok(404, {})

    async def _patch(path: str, body: dict, opts=None) -> dict:
        return _ok(200, {"data": {}})

    client = {
        "get": _get,
        "post": _post,
        "patch": _patch,
        "_created": created,
    }
    return client


def _make_draft(extra: dict | None = None) -> dict:
    d = {
        "id": "d-seed-1",
        "log_type": "seeding",
        "draft_json": {
            "batch_name": "BATCH-2026-05-13-001",
            "block_name": "260513_DT_001",
            "species_code": "DT",
            "qr_codes": ["QR-A"],
            "timestamp": 1700000000,
            "notes": "inoc test",
        },
    }
    if extra:
        import copy
        d = copy.deepcopy(d)
        d.update(extra)
    return d


@pytest.fixture(autouse=True)
def clear_caches():
    assets_mod._clear_cache()
    fungi_type_cache._clear()
    fungi_xing_cache._clear()
    yield
    assets_mod._clear_cache()
    fungi_type_cache._clear()
    fungi_xing_cache._clear()


class TestCommitSeeding:
    async def test_happy_path_creates_block_and_seeding_log(self):
        client = make_seeding_mock_client()
        r = await commit_seeding(client, _make_draft(), {})
        assert r["ok"] is True
        assert len(client["_created"]["assets"]) == 1  # only block
        assert len(client["_created"]["logs"]) == 1
        assert len(r["asset_ids"]) == 1
        block_payload = client["_created"]["assets"][0]["payload"]
        ft_id = block_payload["data"]["relationships"]["fungi_type"]["data"][0]["id"]
        fx_id = block_payload["data"]["relationships"]["fungi_xing"]["data"][0]["id"]
        assert ft_id == "ft-dt"
        assert fx_id == "fx-block"

    async def test_seeding_log_notes_carry_sterilization_batch(self):
        client = make_seeding_mock_client()
        await commit_seeding(client, _make_draft(), {})
        log_payload = client["_created"]["logs"][0]["payload"]
        notes_val = log_payload["data"]["attributes"]["notes"]["value"]
        assert "sterilization_batch: BATCH-2026-05-13-001" in notes_val

    async def test_path_b_qr_resolves_zero_asset_post(self):
        client = make_seeding_mock_client(known_assets_by_qr={"QR-A": "block-existing"})
        r = await commit_seeding(client, _make_draft(), {})
        assert r["ok"] is True
        assert len(client["_created"]["assets"]) == 0
        assert len(client["_created"]["logs"]) == 1
        # Log references the resolved existing block
        log_payload = client["_created"]["logs"][0]["payload"]
        asset_ids = [a["id"] for a in log_payload["data"]["relationships"]["asset"]["data"]]
        assert asset_ids == ["block-existing"]

    async def test_missing_strain_short_circuits_before_block_creation(self):
        client = make_seeding_mock_client()
        d = _make_draft()
        del d["draft_json"]["species_code"]
        r = await commit_seeding(client, d, {})
        assert r["ok"] is False
        assert r["reason"] == "missing_strain"
        assert len(client["_created"]["assets"]) == 0

    async def test_unknown_strain_returns_fungi_type_not_found(self):
        # Empty fungi_type_uuids means no strain resolves
        client = make_seeding_mock_client(fungi_type_uuids={})
        r = await commit_seeding(client, _make_draft(), {})
        assert r["ok"] is False
        assert r["reason"] == "fungi_type_not_found"

    async def test_ambiguous_qr_seeding_when_2_qrs_resolve(self):
        client = make_seeding_mock_client(
            known_assets_by_qr={"QR-A": "block-1", "QR-B": "block-2"}
        )
        d = _make_draft()
        d["draft_json"]["qr_codes"] = ["QR-A", "QR-B"]
        r = await commit_seeding(client, d, {})
        assert r["ok"] is False
        assert r["reason"] == "ambiguous_qr_seeding"

    async def test_idempotency_replay_produces_no_duplicate(self):
        client = make_seeding_mock_client()
        r1 = await commit_seeding(client, _make_draft(), {})
        assert r1["ok"] is True
        a1 = len(client["_created"]["assets"])
        l1 = len(client["_created"]["logs"])
        r2 = await commit_seeding(client, _make_draft(), {})
        assert r2["ok"] is True
        # Second run: name lookup hits existing asset; stable-key lookup hits seeding log.
        assert len(client["_created"]["assets"]) == a1
        assert len(client["_created"]["logs"]) == l1
        # First run created 1 asset; second run upsert noop/patched -> asset_ids empty.
        assert r2["asset_ids"] == []
        assert len(r2["log_ids"]) == 1

    async def test_result_envelope_shape_path_a(self):
        client = make_seeding_mock_client()
        r = await commit_seeding(client, _make_draft(), {})
        assert r["ok"] is True
        assert isinstance(r["asset_ids"], list)
        assert isinstance(r["log_ids"], list)
        assert r["file_ids"] == []
        assert "http_status" in r

    async def test_path_b_asset_ids_empty_created_only(self):
        # Path B: existing block, so asset_ids must be empty (created-only tracking)
        client = make_seeding_mock_client(known_assets_by_qr={"QR-A": "block-existing"})
        r = await commit_seeding(client, _make_draft(), {})
        assert r["ok"] is True
        assert r["asset_ids"] == []

    async def test_missing_block_name_returns_missing_block_name(self):
        client = make_seeding_mock_client()
        d = _make_draft()
        del d["draft_json"]["block_name"]
        r = await commit_seeding(client, d, {})
        assert r["ok"] is False
        assert r["reason"] == "missing_block_name"
