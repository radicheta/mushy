"""Tests for commit_activity, commit_input, commit_observation, commit_harvest
(Phase 62-08).

Port of commit-activity.test.js, commit-input.test.js, commit-observation.test.js,
commit-harvest.test.js.

All external I/O is mocked via a Python equivalent of makeMockClient(). No real
network or DB calls.
"""
from __future__ import annotations

import os
import tempfile
import re
import urllib.parse
from unittest.mock import AsyncMock

import pytest

# asyncio_mode = "auto" in pyproject.toml -- no @pytest.mark.asyncio needed

from farm_agent.farmos.commits.commit_activity import commit_activity
from farm_agent.farmos.commits.commit_input import commit_input
from farm_agent.farmos.commits.commit_observation import commit_observation
from farm_agent.farmos.commits.commit_harvest import commit_harvest
from farm_agent.farmos import assets as assets_mod


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------

DEFAULT_FUNGI_TYPE_UUIDS = {
    "SHI": "ft-shi", "SH2": "ft-sh2", "KOY": "ft-koy", "MAI": "ft-mai",
    "MALI": "ft-mali", "KOS": "ft-kos", "DT": "ft-dt", "CAS": "ft-cas",
    "CAZ": "ft-caz", "WIN": "ft-win", "ALM": "ft-alm", "MOR": "ft-mor",
    "BP": "ft-bp", "LIMA": "ft-lima",
}
DEFAULT_FUNGI_XING_UUIDS = {"block": "fx-block", "fruit": "fx-fruit"}


def _ok_resp(status: int, body) -> dict:
    return {"ok": 200 <= status < 300, "status": status, "body": body, "latency_ms": 1}


def make_mock_client(
    known_assets_by_qr: dict | None = None,
    known_assets_by_name: dict | None = None,
    fungi_type_uuids: dict | None = None,
    fungi_xing_uuids: dict | None = None,
    post_binary_ok: bool = True,
) -> dict:
    """Python equivalent of makeMockClient() from mock-client.js.

    Supports:
      - GET /api/asset/fungi?filter[id_tag.id][value]=<qr>
      - GET /api/asset/fungi?filter[name][value]=<name>
      - GET /api/taxonomy_term/fungi_type?filter[name][value]=<name>
      - GET /api/taxonomy_term/fungi_xing?filter[name][value]=<name>
      - GET /api/asset/fungi/<id> (by id)
      - POST /api/asset/fungi
      - POST /api/log/<type>
      - post_binary  (for file upload)
      - PATCH (pass-through)
    """
    by_qr = dict(known_assets_by_qr or {})
    by_name = dict(known_assets_by_name or {})
    ft_uuids = {**DEFAULT_FUNGI_TYPE_UUIDS, **(fungi_type_uuids or {})}
    fx_uuids = {**DEFAULT_FUNGI_XING_UUIDS, **(fungi_xing_uuids or {})}

    created = {"assets": [], "logs": [], "files": []}
    by_id: dict = {}
    id_by_name: dict = dict(by_name)
    asset_seq = [1]
    log_seq = [1]
    file_seq = [1]

    async def _get(path: str) -> dict:
        # id_tag (qr) lookup
        m = re.search(r"/api/asset/fungi\?filter\[id_tag\.id\]\[value\]=([^&]+)", path)
        if m:
            qr = urllib.parse.unquote(m.group(1))
            if qr in by_qr:
                return _ok_resp(200, {"data": [{"id": by_qr[qr]}]})
            # fall through to name lookup (D-06 handled in qr.py)
            return _ok_resp(200, {"data": []})

        # name filter (fungi)
        m = re.search(r"/api/asset/fungi\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            if name in id_by_name:
                return _ok_resp(200, {"data": [{"id": id_by_name[name]}]})
            return _ok_resp(200, {"data": []})

        # fungi_type taxonomy
        m = re.search(r"/api/taxonomy_term/fungi_type\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            if name in ft_uuids:
                return _ok_resp(200, {"data": [{"id": ft_uuids[name]}]})
            return _ok_resp(200, {"data": []})

        # fungi_xing taxonomy
        m = re.search(r"/api/taxonomy_term/fungi_xing\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            if name in fx_uuids:
                return _ok_resp(200, {"data": [{"id": fx_uuids[name]}]})
            return _ok_resp(200, {"data": []})

        # GET by id
        m = re.search(r"^/api/asset/fungi/([A-Za-z0-9-]+)$", path)
        if m:
            asset_id = m.group(1)
            if asset_id in by_id:
                return _ok_resp(200, {"data": by_id[asset_id]})
            return _ok_resp(404, {"errors": [{"status": "404"}]})

        return _ok_resp(200, {"data": []})

    async def _post(path: str, body: dict, opts: dict | None = None) -> dict:
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
            return _ok_resp(201, {"data": {"id": new_id, "type": "asset--fungi"}})

        if path.startswith("/api/log/"):
            new_id = "log-" + str(log_seq[0])
            log_seq[0] += 1
            log_type = path.split("/")[-1]
            entry = {"id": new_id, "type": log_type, "payload": body}
            created["logs"].append(entry)
            return _ok_resp(201, {"data": {"id": new_id, "type": "log--" + log_type}})

        return _ok_resp(404, {})

    async def _post_binary(path: str, data: bytes, filename: str | None = None,
                           opts: dict | None = None) -> dict:
        if not post_binary_ok:
            return _ok_resp(500, {"errors": [{"status": "500"}]})
        new_id = "file-" + str(file_seq[0])
        file_seq[0] += 1
        created["files"].append({"id": new_id})
        return _ok_resp(201, {"data": {"id": new_id}})

    async def _patch(path: str, body: dict, opts: dict | None = None) -> dict:
        return _ok_resp(200, {"data": {}})

    client = {
        "get": _get,
        "post": _post,
        "post_binary": _post_binary,
        "patch": _patch,
        "_created": created,
    }
    return client


# ---------------------------------------------------------------------------
# commit_activity
# ---------------------------------------------------------------------------

class TestCommitActivity:
    async def test_resolved_qr_becomes_log_asset(self):
        client = make_mock_client(known_assets_by_qr={"Q1": "asset-1"})
        r = await commit_activity(client, {
            "id": "d1", "log_type": "activity",
            "draft_json": {"activity_subtype": "water", "qr_codes": ["Q1"], "timestamp": 1700000000},
        })
        assert r["ok"] is True
        log_payload = client["_created"]["logs"][0]["payload"]
        asset_data = log_payload["data"]["relationships"]["asset"]["data"]
        assert asset_data[0]["id"] == "asset-1"

    async def test_zero_resolved_qrs_returns_no_target_reason(self):
        client = make_mock_client()
        r = await commit_activity(client, {
            "id": "d1", "log_type": "activity",
            "draft_json": {"activity_subtype": "water", "qr_codes": [], "timestamp": 1700000000},
        })
        assert r["ok"] is False
        assert r["reason"] == "no_target_asset_for_activity"
        assert len(client["_created"]["logs"]) == 0

    async def test_log_name_leads_with_activity_subtype(self):
        client = make_mock_client(known_assets_by_qr={"Q": "a"})
        await commit_activity(client, {
            "id": "d1", "log_type": "activity",
            "draft_json": {"activity_subtype": "sterilize", "qr_codes": ["Q"], "timestamp": 1700000000},
        })
        name = client["_created"]["logs"][0]["payload"]["data"]["attributes"]["name"]
        assert name.startswith("sterilize ")

    async def test_multi_qr_multi_asset(self):
        client = make_mock_client(known_assets_by_qr={"Q1": "a1", "Q2": "a2"})
        await commit_activity(client, {
            "id": "d1", "log_type": "activity",
            "draft_json": {"activity_subtype": "relocate", "qr_codes": ["Q1", "Q2"], "timestamp": 1700000000},
        })
        ids = [a["id"] for a in client["_created"]["logs"][0]["payload"]["data"]["relationships"]["asset"]["data"]]
        assert ids == ["a1", "a2"]

    async def test_result_envelope_keys(self):
        client = make_mock_client(known_assets_by_qr={"Q1": "a1"})
        r = await commit_activity(client, {
            "id": "d1", "log_type": "activity",
            "draft_json": {"activity_subtype": "water", "qr_codes": ["Q1"], "timestamp": 1700000000},
        })
        assert "asset_ids" in r
        assert "log_ids" in r
        assert "file_ids" in r
        assert r["ok"] is True


# ---------------------------------------------------------------------------
# commit_input
# ---------------------------------------------------------------------------

class TestCommitInput:
    async def test_zero_qrs_returns_no_target_reason(self):
        client = make_mock_client()
        r = await commit_input(client, {
            "id": "d1", "log_type": "input",
            "draft_json": {"qr_codes": [], "input_ingredients": ["oats"], "timestamp": 1700000000},
        })
        assert r["ok"] is False
        assert r["reason"] == "no_target_asset_for_activity"

    async def test_ingredient_list_serialized_in_notes(self):
        client = make_mock_client(known_assets_by_qr={"Q": "a"})
        await commit_input(client, {
            "id": "d1", "log_type": "input",
            "draft_json": {
                "qr_codes": ["Q"], "timestamp": 1700000000,
                "input_ingredients": ["oat 1kg", "gypsum 50g"],
            },
        })
        notes_val = client["_created"]["logs"][0]["payload"]["data"]["attributes"]["notes"]["value"]
        assert "Ingredients:\n- oat 1kg\n- gypsum 50g" in notes_val

    async def test_empty_ingredients_still_creates_log(self):
        client = make_mock_client(known_assets_by_qr={"Q": "a"})
        r = await commit_input(client, {
            "id": "d1", "log_type": "input",
            "draft_json": {"qr_codes": ["Q"], "input_ingredients": [], "timestamp": 1700000000},
        })
        assert r["ok"] is True
        assert len(client["_created"]["logs"]) == 1

    async def test_result_envelope_keys(self):
        client = make_mock_client(known_assets_by_qr={"Q": "a"})
        r = await commit_input(client, {
            "id": "d1", "log_type": "input",
            "draft_json": {"qr_codes": ["Q"], "input_ingredients": [], "timestamp": 1700000000},
        })
        assert "asset_ids" in r
        assert "log_ids" in r
        assert "file_ids" in r


# ---------------------------------------------------------------------------
# commit_observation
# ---------------------------------------------------------------------------

class TestCommitObservation:
    async def test_no_qr_target_returns_observation_requires_target(self):
        client = make_mock_client()
        r = await commit_observation(client, {
            "id": "d3", "log_type": "observation", "source_capture_ids": [],
            "draft_json": {"qr_codes": [], "timestamp": 1700000000},
        })
        assert r["ok"] is False
        assert r["reason"] == "observation_requires_target"

    async def test_zero_attachments_log_posted_without_file_rel(self):
        client = make_mock_client(known_assets_by_qr={"Q": "a"})
        r = await commit_observation(client, {
            "id": "d2", "log_type": "observation", "source_capture_ids": [],
            "draft_json": {"qr_codes": ["Q"], "timestamp": 1700000000},
        })
        assert r["ok"] is True
        log_payload = client["_created"]["logs"][0]["payload"]
        assert "file" not in (log_payload["data"].get("relationships") or {})

    async def test_attachment_upload_failure_does_not_flip_ok(self):
        # Force post_binary to fail
        client = make_mock_client(known_assets_by_qr={"Q": "a"}, post_binary_ok=False)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff")
            tmp_path = f.name
        try:
            warnings_logged = []

            async def capture_paths(ids):
                return [tmp_path]

            ctx = {
                "capturePathsFor": capture_paths,
                "logger": {"warn": lambda m: warnings_logged.append(m)},
            }
            r = await commit_observation(client, {
                "id": "d4", "log_type": "observation", "source_capture_ids": ["cap-1"],
                "draft_json": {"qr_codes": ["Q"], "timestamp": 1700000000},
            }, ctx)
            # Best-effort: failed photo does not block the commit
            assert r["ok"] is True
            assert len(r["file_ids"]) == 0
            assert len(r["attachments_failed"]) >= 1
            # Failure reason should be http_ something
            assert r["attachments_failed"][0]["reason"].startswith("http_")
            assert len(warnings_logged) >= 1
        finally:
            os.unlink(tmp_path)

    async def test_valid_attachment_uploaded_and_file_id_returned(self):
        client = make_mock_client(known_assets_by_qr={"Q": "a"})
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff")
            tmp_path = f.name
        try:
            async def capture_paths(ids):
                return [tmp_path]

            ctx = {"capturePathsFor": capture_paths}
            r = await commit_observation(client, {
                "id": "d5", "log_type": "observation", "source_capture_ids": ["cap-1"],
                "draft_json": {"qr_codes": ["Q"], "timestamp": 1700000000},
            }, ctx)
            assert r["ok"] is True
            assert len(r["file_ids"]) == 1
        finally:
            os.unlink(tmp_path)

    async def test_result_envelope_keys(self):
        client = make_mock_client(known_assets_by_qr={"Q": "a"})
        r = await commit_observation(client, {
            "id": "d6", "log_type": "observation", "source_capture_ids": [],
            "draft_json": {"qr_codes": ["Q"], "timestamp": 1700000000},
        })
        assert "asset_ids" in r
        assert "log_ids" in r
        assert "file_ids" in r
        assert "attachments_failed" in r


# ---------------------------------------------------------------------------
# commit_harvest
# ---------------------------------------------------------------------------

class TestCommitHarvest:
    def setup_method(self):
        # Clear module-level LRU caches between tests (mirrors beforeEach() in JS)
        assets_mod._clear_cache()

    def _draft(self, extra: dict | None = None) -> dict:
        d = {
            "id": "d-harv-1",
            "log_type": "harvest",
            "draft_json": {
                "source_qr_codes": ["SRC1", "SRC2"],
                "harvest_batch_name": "HBATCH-2026-05-13-DT-001",
                "bags": [
                    {"qr_code": "BAG1", "weight_grams": 250},
                    {"qr_code": "BAG2", "weight_grams": 230},
                    {"qr_code": "BAG3", "weight_grams": 260},
                ],
                "timestamp": 1700000000,
            },
        }
        if extra:
            d.update(extra)
        return d

    async def test_missing_source_block_aborts_before_any_asset_post(self):
        client = make_mock_client(known_assets_by_qr={"SRC1": "src-a"})  # SRC2 missing
        r = await commit_harvest(client, self._draft())
        assert r["ok"] is False
        assert r["reason"] == "missing_source_block"
        assert len(client["_created"]["assets"]) == 0
        assert len(client["_created"]["logs"]) == 0

    async def test_n2_sources_m3_bags_3_bag_assets_no_batch_1_log(self):
        client = make_mock_client(known_assets_by_qr={"SRC1": "src-a", "SRC2": "src-b"})
        r = await commit_harvest(client, self._draft())
        assert r["ok"] is True
        assert len(client["_created"]["assets"]) == 3  # bags only, no batch
        assert len(client["_created"]["logs"]) == 1

        # Verify bag asset shape
        bag_payload = client["_created"]["assets"][0]["payload"]
        ft_data = bag_payload["data"]["relationships"]["fungi_type"]["data"]
        fx_data = bag_payload["data"]["relationships"]["fungi_xing"]["data"]
        parent_data = bag_payload["data"]["relationships"]["parent"]["data"]
        assert ft_data[0]["id"] == "ft-dt"
        assert fx_data[0]["id"] == "fx-fruit"
        parent_ids = [p["id"] for p in parent_data]
        assert parent_ids == ["src-a", "src-b"]

    async def test_strain_resolved_from_harvest_batch_name(self):
        client = make_mock_client(known_assets_by_qr={"SRC1": "src-a", "SRC2": "src-b"})
        await commit_harvest(client, self._draft())
        bag_payload = client["_created"]["assets"][0]["payload"]
        ft_data = bag_payload["data"]["relationships"]["fungi_type"]["data"]
        assert ft_data[0]["id"] == "ft-dt"

    async def test_missing_strain_returns_missing_strain(self):
        client = make_mock_client(known_assets_by_qr={"SRC1": "src-a", "SRC2": "src-b"})
        d = self._draft()
        del d["draft_json"]["harvest_batch_name"]
        r = await commit_harvest(client, d)
        assert r["ok"] is False
        assert r["reason"] == "missing_strain"
        assert len(client["_created"]["assets"]) == 0

    async def test_log_asset_ids_order_sources_then_bags(self):
        client = make_mock_client(known_assets_by_qr={"SRC1": "src-a", "SRC2": "src-b"})
        await commit_harvest(client, self._draft())
        ids = [a["id"] for a in client["_created"]["logs"][0]["payload"]["data"]["relationships"]["asset"]["data"]]
        assert ids[0] == "src-a"
        assert ids[1] == "src-b"
        assert len(ids) == 5  # 2 sources + 3 bags

    async def test_harvest_log_notes_carry_batch_lineage(self):
        client = make_mock_client(known_assets_by_qr={"SRC1": "src-a", "SRC2": "src-b"})
        await commit_harvest(client, self._draft())
        notes_val = client["_created"]["logs"][0]["payload"]["data"]["attributes"]["notes"]["value"]
        assert "harvest_batch: HBATCH-2026-05-13-DT-001" in notes_val
        assert "bag1: 250g" in notes_val

    async def test_qr_already_bound_for_bag_fails(self):
        client = make_mock_client(known_assets_by_qr={
            "SRC1": "src-a", "SRC2": "src-b", "BAG2": "someone-else",
        })
        r = await commit_harvest(client, self._draft())
        assert r["ok"] is False
        assert r["reason"] == "qr_already_bound_for_bag"
        assert len(client["_created"]["assets"]) == 0

    async def test_result_envelope_shape(self):
        client = make_mock_client(known_assets_by_qr={"SRC1": "a", "SRC2": "b"})
        r = await commit_harvest(client, self._draft())
        assert r["ok"] is True
        assert "asset_ids" in r
        assert "log_ids" in r
        assert "file_ids" in r
        assert r["file_ids"] == []
        assert len(r["asset_ids"]) == 3  # 3 bags


# ---------------------------------------------------------------------------
# Acceptance: no /api/file/file usage
# ---------------------------------------------------------------------------

def test_no_legacy_file_file_route_in_commits():
    """Verify the legacy 415-route is not used in any commit handler."""
    import subprocess
    result = subprocess.run(
        ["grep", "-r", "/api/file/file", "farm_agent/farmos/commits/"],
        capture_output=True,
        text=True,
        cwd="/mnt/slime-kingdom/opt/mushy/src/farm-agent",
    )
    assert result.stdout.strip() == "", f"Legacy /api/file/file route found: {result.stdout}"


# ---------------------------------------------------------------------------
# commit_activity: minting an absent block (MUSHY-126)
# ---------------------------------------------------------------------------

class TestCommitActivityMintsAbsentBlock:
    """The confirmation says "New in farmOS, will be created". This is the code
    that has to keep that promise.

    Draft 91a9c622b3 (2026-08-29): a relocate onto 260519_WIN_4, a block farmOS
    had never heard of. The handler resolved only, so the commit could never
    succeed no matter how many times it was retried.
    """

    @pytest.fixture(autouse=True)
    def _clear_name_cache(self):
        """assets._NAME_CACHE is module-level and nothing else in this suite
        clears it, so a block minted by one test is "found" by the next."""
        assets_mod._NAME_CACHE.clear()
        yield
        assets_mod._NAME_CACHE.clear()

    _DRAFT = {
        "id": "d-mushy126", "log_type": "activity",
        "draft_json": {
            "activity_subtype": "relocate",
            "qr_codes": ["260519_WIN_4"],
            "notes": "Moved into FC1.",
            "timestamp": 1700000000,
        },
    }

    async def test_absent_block_is_created_and_logged(self):
        client = make_mock_client()
        r = await commit_activity(client, self._DRAFT)
        assert r["ok"] is True, r
        created = client["_created"]["assets"]
        assert len(created) == 1, "the absent block should have been minted"
        assert created[0]["payload"]["data"]["attributes"]["name"] == "260519_WIN_4"
        assert len(client["_created"]["logs"]) == 1

    async def test_strain_comes_from_the_block_name(self):
        """260519_WIN_4 carries its own fungi_type. Nothing else on the draft does."""
        client = make_mock_client()
        await commit_activity(client, self._DRAFT)
        rels = client["_created"]["assets"][0]["payload"]["data"]["relationships"]
        assert rels["fungi_type"]["data"][0]["id"] == "ft-win"

    async def test_an_existing_block_is_still_never_minted(self):
        client = make_mock_client(known_assets_by_name={"260519_WIN_4": "asset-existing"})
        r = await commit_activity(client, self._DRAFT)
        assert r["ok"] is True
        assert client["_created"]["assets"] == [], "resolved refs must not be re-created"

    async def test_a_ref_that_is_not_a_block_name_is_not_invented(self):
        """A bare QR sticker says nothing about strain. Guessing one would put a
        junk asset in the farm record, so this still fails honestly."""
        client = make_mock_client()
        r = await commit_activity(client, {
            "id": "d1", "log_type": "activity",
            "draft_json": {"activity_subtype": "water", "qr_codes": ["Q-UNKNOWN"], "timestamp": 1700000000},
        })
        assert r["ok"] is False
        assert r["reason"] == "no_target_asset_for_activity"
        assert client["_created"]["assets"] == []

    async def test_an_unknown_strain_fails_instead_of_minting_a_taxonomy_term(self):
        """create_missing_fungi_type is off by default, and stays off here."""
        client = make_mock_client()
        r = await commit_activity(client, {
            "id": "d1", "log_type": "activity",
            "draft_json": {"activity_subtype": "relocate", "qr_codes": ["260519_ZZZ_4"], "timestamp": 1700000000},
        })
        assert r["ok"] is False
        assert r["reason"] == "fungi_type_not_found"
        assert client["_created"]["assets"] == []

    async def test_an_unreachable_lookup_never_mints(self):
        """A lookup that could not reach farmOS is not a miss (qr.py D-06).
        Treating it as one would duplicate a block that is already there."""
        import farm_agent.farmos.commits.commit_activity as mod
        client = make_mock_client()
        broken = AsyncMock(return_value={"found": False, "error": "http_network", "path": "id_tag"})
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(mod, "resolve_qr", broken)
            r = await commit_activity(client, self._DRAFT)
        assert r["ok"] is False
        assert r["reason"] == "http_network"
        assert client["_created"]["assets"] == [], "must not mint on an unanswered lookup"

    async def test_a_500_on_lookup_carries_its_status_through(self):
        """So the watchdog can tell a retryable 500 from a terminal 403."""
        import farm_agent.farmos.commits.commit_activity as mod
        client = make_mock_client()
        broken = AsyncMock(return_value={"found": False, "error": "http_500", "path": "id_tag"})
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(mod, "resolve_qr", broken)
            r = await commit_activity(client, self._DRAFT)
        assert r["http_status"] == 500


# ---------------------------------------------------------------------------
# commit_activity: photo upload (MUSHY-131)
# ---------------------------------------------------------------------------

class TestCommitActivityUploadsPhotos:
    """A photo sent with an activity used to be captured, stored, referenced by
    the draft, and then dropped at commit without a word, while the farmer was
    told "Saved to farmOS".

    Observed 2026-08-29 on draft 0d322e92cd: capture 01M17MEKG6B5WVB6FWR2BA9GSK
    was message_type=image with a 182KB jpg on disk, and log 308 landed with no
    photo anywhere in farmOS.
    """

    @pytest.fixture(autouse=True)
    def _clear_name_cache(self):
        assets_mod._NAME_CACHE.clear()
        yield
        assets_mod._NAME_CACHE.clear()

    def _draft(self, capture_ids=("cap-1",)):
        return {
            "id": "d-mushy131", "log_type": "activity",
            "source_capture_ids": list(capture_ids),
            "draft_json": {
                "activity_subtype": "relocate",
                "qr_codes": ["Q1"],
                "notes": "Moved into FC1.",
                "timestamp": 1700000000,
            },
        }

    @pytest.fixture
    def jpg(self):
        """A real file on disk: upload_field_attachments reads the path, so a
        made-up one is reported as skipped rather than uploaded."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0 jpeg bytes")
            path = f.name
        yield path
        os.unlink(path)

    def _ctx(self, paths):
        return {"capturePathsFor": AsyncMock(return_value=list(paths))}

    async def test_the_photo_is_uploaded(self, jpg):
        client = make_mock_client(known_assets_by_qr={"Q1": "asset-1"})
        r = await commit_activity(client, self._draft(), self._ctx([jpg]))
        assert r["ok"] is True
        assert r["file_ids"], "the photo should have produced a file id"

    async def test_the_log_references_the_uploaded_file(self, jpg):
        """Without this the photo exists in farmOS but not on the log."""
        client = make_mock_client(known_assets_by_qr={"Q1": "asset-1"})
        r = await commit_activity(client, self._draft(), self._ctx([jpg]))
        rels = client["_created"]["logs"][0]["payload"]["data"]["relationships"]
        assert "file" in rels
        assert [f["id"] for f in rels["file"]["data"]] == r["file_ids"]

    async def test_a_draft_with_no_photo_still_commits(self):
        client = make_mock_client(known_assets_by_qr={"Q1": "asset-1"})
        r = await commit_activity(client, self._draft(capture_ids=()), self._ctx([]))
        assert r["ok"] is True
        assert r["file_ids"] == []

    async def test_no_ctx_is_not_a_crash(self):
        """The commit router may dispatch with ctx=None."""
        client = make_mock_client(known_assets_by_qr={"Q1": "asset-1"})
        r = await commit_activity(client, self._draft(), None)
        assert r["ok"] is True

    async def test_a_failed_upload_does_not_unwind_the_log(self, jpg):
        """Best-effort is load-bearing: the log is correct even if the photo is not."""
        client = make_mock_client(known_assets_by_qr={"Q1": "asset-1"}, post_binary_ok=False)
        r = await commit_activity(client, self._draft(), self._ctx([jpg]))
        assert r["ok"] is True, "a photo failure must not fail the activity"
        assert r["attachments_failed"], "but it must be surfaced, not swallowed"
        assert len(client["_created"]["logs"]) == 1

    async def test_a_thrown_path_lookup_does_not_unwind_the_log(self):
        client = make_mock_client(known_assets_by_qr={"Q1": "asset-1"})
        ctx = {"capturePathsFor": AsyncMock(side_effect=RuntimeError("capture db down"))}
        r = await commit_activity(client, self._draft(), ctx)
        assert r["ok"] is True
        assert r["file_ids"] == []

    async def test_the_photo_hangs_off_the_minted_block(self, jpg):
        """MUSHY-126 + MUSHY-131 together: mint the block, then attach to it."""
        client = make_mock_client()
        draft = self._draft()
        draft["draft_json"]["qr_codes"] = ["260519_WIN_4"]
        r = await commit_activity(client, draft, self._ctx([jpg]))
        assert r["ok"] is True
        assert len(client["_created"]["assets"]) == 1
        assert r["file_ids"], "the photo should attach to the freshly minted block"
