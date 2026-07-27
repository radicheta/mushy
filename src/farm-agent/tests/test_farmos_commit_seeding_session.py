"""Tests for commit_seeding_session.py (Phase 62-09).

Port of src/agents/alerter/test/farmos/commit-seeding-session.test.js.

Fixture: May-22 inoc session (5 groups, 11 children).
Expected happy-path counts:
  - 1 asset--group (session)
  - 5 asset--fungi source blocks
  - 11 asset--fungi child blocks
  = 17 asset POSTs total
  - 1 log--activity (membership, is_group_assignment=True)
  - 11 log--seeding (one per child)
  = 12 logs total

All external I/O is mocked. No real network or DB calls.
"""
from __future__ import annotations

import os
import re
import tempfile
import urllib.parse

import pytest

from farm_agent.farmos import assets as assets_mod
from farm_agent.farmos import fungi_type_cache, fungi_xing_cache
from farm_agent.farmos import group_assets as group_assets_mod
from farm_agent.farmos.commits.commit_seeding_session import commit_seeding_session

# ---------------------------------------------------------------------------
# May-22 fixture (inlined from expected-draft.json)
# ---------------------------------------------------------------------------

MAY22_FIXTURE = {
    "type": "seeding_session",
    "event_date": "2026-05-22",
    "groups": [
        {
            "parent": {"value": "260304_SHI_5", "confidence": 0.95, "sources": ["audio"]},
            "species": {"value": "SHI", "confidence": 0.98, "sources": ["audio"]},
            "qty": {"value": 1, "confidence": 0.98, "sources": ["audio"]},
            "child_block_names": {"value": ["260522_SHI_1"], "confidence": 0.95, "sources": ["audio"]},
        },
        {
            "parent": {"value": "260118_SHI_23", "confidence": 0.9, "sources": ["audio"]},
            "species": {"value": "SHI", "confidence": 0.98, "sources": ["audio"]},
            "qty": {"value": 1, "confidence": 0.98, "sources": ["audio"]},
            "child_block_names": {"value": ["260522_SHI_2"], "confidence": 0.95, "sources": ["audio"]},
        },
        {
            "parent": {"value": "260118_SHI_26", "confidence": 0.9, "sources": ["audio"]},
            "species": {"value": "SHI", "confidence": 0.98, "sources": ["audio"]},
            "qty": {"value": 1, "confidence": 0.98, "sources": ["audio"]},
            "child_block_names": {"value": ["260522_SHI_3"], "confidence": 0.95, "sources": ["audio"]},
        },
        {
            "parent": {"value": "260118_KOY_12", "confidence": 0.85, "sources": ["audio"]},
            "species": {"value": "KOY", "confidence": 0.98, "sources": ["audio"]},
            "qty": {"value": 4, "confidence": 0.95, "sources": ["audio"]},
            "child_block_names": {
                "value": ["260522_KOY_4", "260522_KOY_5", "260522_KOY_6", "260522_KOY_7"],
                "confidence": 0.95, "sources": ["audio"],
            },
        },
        {
            "parent": {"value": "260425_KOY_4", "confidence": 0.9, "sources": ["audio"]},
            "species": {"value": "KOY", "confidence": 0.98, "sources": ["audio"]},
            "qty": {"value": 4, "confidence": 0.95, "sources": ["audio"]},
            "child_block_names": {
                "value": ["260522_KOY_8", "260522_KOY_9", "260522_KOY_10", "260522_KOY_11"],
                "confidence": 0.95, "sources": ["audio"],
            },
        },
    ],
    "notes": "May 22 2026 inoc session: 11 sawdust bags across 5 parents, 2 species.",
}

# ---------------------------------------------------------------------------
# Mock client constants
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


# ---------------------------------------------------------------------------
# Session mock client
# ---------------------------------------------------------------------------

def make_session_mock_client(
    known_assets_by_name: dict | None = None,
    known_groups_by_name: dict | None = None,
    fail_log_index: int = -1,   # 1-based seeding log POST to fail; -1 = never
    fail_log_status: int = 422,
    fail_activity_log: bool = False,
    delete_response=None,       # callable(path) -> dict, or None for ok
) -> dict:
    """Mock client for commit_seeding_session tests.

    Mirrors makeSessionMockClient() from commit-seeding-session.test.js.
    """
    ft_uuids = DEFAULT_FUNGI_TYPE_UUIDS
    fx_uuids = DEFAULT_FUNGI_XING_UUIDS
    by_name_init = dict(known_assets_by_name or {})
    groups_by_name: dict = dict(known_groups_by_name or {})

    created: dict = {"assets": [], "logs": [], "groups": [], "activity_logs": []}
    by_id: dict = {}
    id_by_name: dict = dict(by_name_init)
    group_by_id: dict = {}
    group_id_by_name: dict = {}
    logs_by_asset_id: dict = {}
    deletes: list = []
    asset_seq = [1]
    log_seq = [1]
    group_seq = [1]
    file_seq = [1]
    seeding_log_post_count = [0]

    # Pre-seed known groups
    for name, val in groups_by_name.items():
        gid = val["id"] if isinstance(val, dict) else val
        group_id_by_name[name] = gid
        attrs = val.get("attributes", {}) if isinstance(val, dict) else {}
        group_by_id[gid] = {
            "id": gid,
            "type": "asset--group",
            "attributes": {"name": name, **attrs},
            "relationships": {},
        }

    async def _get(path: str) -> dict:
        # Fungi QR lookup
        m = re.search(r"/api/asset/fungi\?filter\[id_tag\.id\]\[value\]=([^&]+)", path)
        if m:
            return _ok(200, {"data": []})

        # Fungi name lookup
        m = re.search(r"/api/asset/fungi\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            if name in id_by_name:
                return _ok(200, {"data": [{"id": id_by_name[name]}]})
            return _ok(200, {"data": []})

        # Fungi type
        m = re.search(r"/api/taxonomy_term/fungi_type\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            if name in ft_uuids:
                return _ok(200, {"data": [{"id": ft_uuids[name]}]})
            return _ok(200, {"data": []})

        # Fungi xing
        m = re.search(r"/api/taxonomy_term/fungi_xing\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            if name in fx_uuids:
                return _ok(200, {"data": [{"id": fx_uuids[name]}]})
            return _ok(200, {"data": []})

        # GET fungi by id
        m = re.search(r"^/api/asset/fungi/([A-Za-z0-9_-]+)$", path)
        if m:
            aid = m.group(1)
            if aid in by_id:
                return _ok(200, {"data": by_id[aid]})
            return _ok(404, {"errors": [{"status": "404"}]})

        # Group name lookup
        m = re.search(r"/api/asset/group\?filter\[name\]\[value\]=([^&]+)", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            if name in group_id_by_name:
                return _ok(200, {"data": [{"id": group_id_by_name[name]}]})
            return _ok(200, {"data": []})

        # GET group by id (for notes-trailer check in _resolve_session_name)
        m = re.search(r"^/api/asset/group/([A-Za-z0-9_-]+)$", path)
        if m:
            gid = m.group(1)
            if gid in group_by_id:
                return _ok(200, {"data": group_by_id[gid]})
            return _ok(404, {"errors": [{"status": "404"}]})

        # Seeding log stable-key
        m = re.search(r"/api/log/seeding\?filter\[asset\.id\]\[value\]=([^&]+)", path)
        if m:
            aid = urllib.parse.unquote(m.group(1))
            if aid in logs_by_asset_id:
                lg = logs_by_asset_id[aid]
                return _ok(200, {"data": [{
                    "id": lg["id"],
                    "type": "log--seeding",
                    "attributes": {"created": "2026-05-22T00:00:00Z", **lg.get("attributes", {})},
                    "relationships": lg.get("relationships", {}),
                }]})
            return _ok(200, {"data": []})

        # GET seeding log by id
        m = re.search(r"^/api/log/seeding/([A-Za-z0-9_-]+)$", path)
        if m:
            lid = m.group(1)
            for al in logs_by_asset_id.values():
                if al["id"] == lid:
                    return _ok(200, {"data": {
                        "id": lid,
                        "type": "log--seeding",
                        "attributes": {"drupal_internal__revision_id": 1, **al.get("attributes", {})},
                        "relationships": al.get("relationships", {}),
                    }})
            return _ok(404, {"errors": [{"status": "404"}]})

        return _ok(200, {"data": []})

    async def _post(path: str, body: dict, opts=None) -> dict:
        if path == "/api/asset/group":
            new_id = "group-" + str(group_seq[0])
            group_seq[0] += 1
            name = (body.get("data") or {}).get("attributes", {}).get("name", "")
            attrs = (body.get("data") or {}).get("attributes") or {}
            entry = {"id": new_id, "name": name, "payload": body}
            created["groups"].append(entry)
            group_id_by_name[name] = new_id
            group_by_id[new_id] = {
                "id": new_id,
                "type": "asset--group",
                "attributes": {"name": name, **attrs},
                "relationships": {},
            }
            return _ok(201, {"data": {"id": new_id, "type": "asset--group"}})

        if path == "/api/log/activity":
            if fail_activity_log:
                return _ok(fail_log_status, {"errors": [{"detail": "validation"}]})
            new_id = "alog-" + str(log_seq[0])
            log_seq[0] += 1
            entry = {"id": new_id, "type": "activity", "payload": body}
            created["activity_logs"].append(entry)
            return _ok(201, {"data": {"id": new_id, "type": "log--activity"}})

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
            seeding_log_post_count[0] += 1
            if fail_log_index > 0 and seeding_log_post_count[0] == fail_log_index:
                return _ok(fail_log_status, {"errors": [{"detail": "validation"}]})
            new_id = "log-" + str(log_seq[0])
            log_seq[0] += 1
            asset_data = (
                ((body.get("data") or {}).get("relationships") or {})
                .get("asset", {}).get("data") or []
            )
            attrs = (body.get("data") or {}).get("attributes") or {}
            entry = {"id": new_id, "type": "seeding", "payload": body}
            created["logs"].append(entry)
            for ref in asset_data:
                aid = ref.get("id")
                if aid:
                    logs_by_asset_id[aid] = {
                        "id": new_id,
                        "attributes": {"drupal_internal__revision_id": 1, **attrs},
                        "relationships": {"asset": {"data": asset_data}},
                    }
            return _ok(201, {"data": {"id": new_id, "type": "log--seeding"}})

        return _ok(404, {})

    async def _patch(path: str, body: dict, opts=None) -> dict:
        return _ok(200, {"data": {}})

    async def _delete(path: str, opts=None) -> dict:
        deletes.append(path)
        if delete_response is not None:
            return delete_response(path)
        return _ok(204, None)

    async def _post_binary(path: str, data: bytes, filename: str | None = None,
                           opts=None) -> dict:
        new_id = "file-" + str(file_seq[0])
        file_seq[0] += 1
        return _ok(201, {"data": {"id": new_id, "type": "file--file"}})

    client = {
        "get": _get,
        "post": _post,
        "patch": _patch,
        "delete": _delete,
        "post_binary": _post_binary,
        "_created": created,
        "_deletes": deletes,
    }
    return client


def make_audit_ctx() -> tuple[dict, list]:
    calls: list = []

    async def _log_commit(event: str, draft: dict, result: dict) -> None:
        calls.append({
            "event": event,
            "draft_id": (draft or {}).get("id"),
            "result": result,
        })

    ctx = {"audit_logger": {"log_commit": _log_commit}}
    return ctx, calls


def _draft_for(dj: dict, draft_id: str = "d-session-1") -> dict:
    return {"id": draft_id, "log_type": "seeding_session", "draft_json": dj}


@pytest.fixture(autouse=True)
def clear_caches():
    assets_mod._clear_cache()
    group_assets_mod._clear_cache()
    fungi_type_cache._clear()
    fungi_xing_cache._clear()
    yield
    assets_mod._clear_cache()
    group_assets_mod._clear_cache()
    fungi_type_cache._clear()
    fungi_xing_cache._clear()


class TestCommitSeedingSession:

    async def test_a_happy_path_may22_full_counts(self):
        """17 assets (1 group + 5 source + 11 children), 12 logs, child parent=[source] ONLY."""
        client = make_session_mock_client()
        ctx, _ = make_audit_ctx()
        r = await commit_seeding_session(client, _draft_for(MAY22_FIXTURE), ctx)

        assert r["ok"] is True

        assert len(client["_created"]["groups"]) == 1
        assert len(client["_created"]["assets"]) == 16  # 5 source + 11 children
        assert len(client["_created"]["activity_logs"]) == 1
        seeding_logs = [l for l in client["_created"]["logs"] if l["type"] == "seeding"]
        assert len(seeding_logs) == 11

        # Return shape
        session_group_id = client["_created"]["groups"][0]["id"]
        assert r["asset_ids"][0] == session_group_id
        assert len(r["asset_ids"]) == 17
        assert len(r["log_ids"]) == 12
        membership_log_id = client["_created"]["activity_logs"][0]["id"]
        assert r["log_ids"][0] == membership_log_id

        # Activity log payload
        activity_body = client["_created"]["activity_logs"][0]["payload"]
        assert activity_body["data"]["type"] == "log--activity"
        assert activity_body["data"]["attributes"]["is_group_assignment"] is True
        assert len(activity_body["data"]["relationships"]["asset"]["data"]) == 11
        for ref in activity_body["data"]["relationships"]["asset"]["data"]:
            assert ref["type"] == "asset--fungi"
        assert activity_body["data"]["relationships"]["group"]["data"] == [
            {"type": "asset--group", "id": session_group_id}
        ]

    async def test_child_parent_is_source_block_only_not_session_group(self):
        """Children carry parent=[sourceBlock] ONLY -- NO session group id on children."""
        client = make_session_mock_client()
        ctx, _ = make_audit_ctx()
        r = await commit_seeding_session(client, _draft_for(MAY22_FIXTURE), ctx)
        assert r["ok"] is True

        session_group_id = client["_created"]["groups"][0]["id"]
        child_assets = [a for a in client["_created"]["assets"]
                        if a["name"].startswith("260522_")]
        assert len(child_assets) == 11
        for c in child_assets:
            parents = c["payload"]["data"]["relationships"]["parent"]["data"]
            assert len(parents) == 1
            for p in parents:
                assert p["type"] == "asset--fungi"
                assert p["id"] != session_group_id

    async def test_c_single_parent_session(self):
        """1 session group + 1 source + 5 children + 1 activity log + 5 seeding logs."""
        dj = {
            "type": "seeding_session",
            "event_date": "2026-05-22",
            "groups": [{
                "parent": {"value": "260118_KOY_12", "confidence": 0.9, "sources": ["audio"]},
                "species": {"value": "KOY", "confidence": 0.99, "sources": ["audio"]},
                "qty": {"value": 5, "confidence": 0.99, "sources": ["audio"]},
                "child_block_names": {
                    "value": ["260522_KOY_1", "260522_KOY_2", "260522_KOY_3",
                              "260522_KOY_4", "260522_KOY_5"],
                    "confidence": 0.95, "sources": ["audio"],
                },
            }],
        }
        client = make_session_mock_client()
        r = await commit_seeding_session(client, _draft_for(dj, "d-single-parent"), {})
        assert r["ok"] is True
        assert len(client["_created"]["groups"]) == 1
        assert len(client["_created"]["assets"]) == 6  # 1 source + 5 children
        assert len(client["_created"]["activity_logs"]) == 1
        seeding_logs = [l for l in client["_created"]["logs"] if l["type"] == "seeding"]
        assert len(seeding_logs) == 5
        source_id = client["_created"]["assets"][0]["id"]
        child_assets = [a for a in client["_created"]["assets"]
                        if a["name"].startswith("260522_")]
        for c in child_assets:
            parents = [p["id"] for p in c["payload"]["data"]["relationships"]["parent"]["data"]]
            assert parents == [source_id]

    async def test_d_no_parent_children_have_no_parent_rel(self):
        """Children with NO_PARENT have no parent relationship."""
        dj = {
            "type": "seeding_session",
            "event_date": "2026-05-22",
            "groups": [{
                "parent": {"value": "NO_PARENT", "confidence": 0.99, "sources": ["audio"]},
                "species": {"value": "SHI", "confidence": 0.99, "sources": ["audio"]},
                "qty": {"value": 2, "confidence": 0.99, "sources": ["audio"]},
                "child_block_names": {
                    "value": ["260522_SHI_X1", "260522_SHI_X2"],
                    "confidence": 0.99, "sources": ["audio"],
                },
            }],
        }
        client = make_session_mock_client()
        r = await commit_seeding_session(client, _draft_for(dj, "d-no-parent"), {})
        assert r["ok"] is True
        assert len(client["_created"]["groups"]) == 1
        assert len(client["_created"]["assets"]) == 2
        assert len(client["_created"]["activity_logs"]) == 1
        child_assets = [a for a in client["_created"]["assets"]
                        if a["name"].startswith("260522_SHI_X")]
        for c in child_assets:
            assert "parent" not in c["payload"]["data"]["relationships"]

    async def test_e_partial_failure_seeding_log_triggers_reverse_rollback(self):
        """Seeding log #4 fails -> reverse-order DELETE; session group LAST."""
        # failLogIndex=4: 1 group + ~8 assets created before failure
        client = make_session_mock_client(fail_log_index=4)
        ctx, audit_calls = make_audit_ctx()
        r = await commit_seeding_session(client, _draft_for(MAY22_FIXTURE), ctx)

        assert r["ok"] is False
        assert r["reason"] == "partial_commit_failed"
        assert r["farmos_response"]["failed_at_child_index"] == 3
        assert r["asset_ids"] == []
        assert r["log_ids"] == []

        # Session group was created
        assert len(client["_created"]["groups"]) == 1
        assert len(client["_created"]["activity_logs"]) == 0  # never reached

        # DELETEs: 8 fungi + 1 session group = 9 total
        assert len(client["_deletes"]) == 9
        assert r["farmos_response"]["orphan_attempted_count"] == 9
        assert r["farmos_response"]["orphan_cleanup_failed_count"] == 0

        # Session group DELETE is LAST
        session_group_id = client["_created"]["groups"][0]["id"]
        assert client["_deletes"][-1] == "/api/asset/group/" + session_group_id

        # First DELETE is the LAST-created fungi (reverse order)
        last_fungi_id = client["_created"]["assets"][-1]["id"]
        assert client["_deletes"][0] == "/api/asset/fungi/" + last_fungi_id

        # No orphan_cleanup_failed audit calls
        orphan_calls = [c for c in audit_calls if c["event"] == "orphan_cleanup_failed"]
        assert len(orphan_calls) == 0

    async def test_f_orphan_cleanup_itself_fails_audit_called(self):
        """When DELETEs fail, orphan_cleanup_failed is emitted for each."""
        client = make_session_mock_client(
            fail_log_index=4,
            delete_response=lambda p: _ok(500, None),
        )
        ctx, audit_calls = make_audit_ctx()
        r = await commit_seeding_session(client, _draft_for(MAY22_FIXTURE), ctx)

        assert r["ok"] is False
        assert r["reason"] == "partial_commit_failed"
        assert len(client["_deletes"]) == 9
        assert r["farmos_response"]["orphan_cleanup_failed_count"] == 9
        assert len(r["farmos_response"]["orphan_cleanup_failed_ids"]) == 9

        orphan_calls = [c for c in audit_calls if c["event"] == "orphan_cleanup_failed"]
        assert len(orphan_calls) == 9
        for c in orphan_calls:
            assert len(c["result"]["asset_ids"]) == 1
            assert c["draft_id"] == "d-session-1"

    async def test_e2_membership_log_failure_rollback_covers_all(self):
        """Activity log POST fails -> rollback covers session group + all 16 assets."""
        client = make_session_mock_client(fail_activity_log=True)
        ctx, _ = make_audit_ctx()
        r = await commit_seeding_session(client, _draft_for(MAY22_FIXTURE), ctx)

        assert r["ok"] is False
        assert r["reason"] == "partial_commit_failed"
        assert r["farmos_response"]["original_reason"] == "membership_log_create_failed"
        assert r["asset_ids"] == []
        assert r["log_ids"] == []

        assert len(client["_created"]["groups"]) == 1
        assert len(client["_created"]["assets"]) == 16  # 5 source + 11 children
        seeding_logs = [l for l in client["_created"]["logs"] if l["type"] == "seeding"]
        assert len(seeding_logs) == 11
        assert len(client["_created"]["activity_logs"]) == 0

        session_group_id = client["_created"]["groups"][0]["id"]
        child_asset_ids = [a["id"] for a in client["_created"]["assets"]
                           if a["name"].startswith("260522_")]

        # Rollback: 16 fungi DELETEs + 1 session group DELETE = 17
        assert len(client["_deletes"]) == 17

        # Session group DELETE is last
        assert "/api/asset/group/" + session_group_id in client["_deletes"]
        assert client["_deletes"][-1] == "/api/asset/group/" + session_group_id

        # All 11 children appear in DELETE list
        for cid in child_asset_ids:
            assert "/api/asset/fungi/" + cid in client["_deletes"]

        # Session group comes after all fungi
        group_delete_idx = client["_deletes"].index("/api/asset/group/" + session_group_id)
        assert group_delete_idx > 0

    async def test_f2_same_day_collision_advances_to_hash_2(self):
        """Existing group with foreign draft id -> handler creates 'inoc 2026-05-22 #2'."""
        client = make_session_mock_client(
            known_groups_by_name={
                "inoc 2026-05-22": {
                    "id": "group-foreign",
                    "attributes": {
                        "name": "inoc 2026-05-22",
                        "notes": {"value": "mushy:draft:OTHER_DRAFT", "format": "plain_text"},
                    },
                },
            }
        )
        r = await commit_seeding_session(
            client, _draft_for(MAY22_FIXTURE, "d-collision"), {}
        )
        assert r["ok"] is True

        # Exactly 1 new group POST (foreign was pre-seeded, not POSTed)
        assert len(client["_created"]["groups"]) == 1
        assert client["_created"]["groups"][0]["name"] == "inoc 2026-05-22 #2"
        assert (
            client["_created"]["groups"][0]["payload"]["data"]["attributes"]["name"]
            == "inoc 2026-05-22 #2"
        )

        # asset_ids[0] is the new session group, not the foreign one
        assert r["asset_ids"][0] == client["_created"]["groups"][0]["id"]
        assert r["asset_ids"][0] != "group-foreign"

    async def test_h_idempotency_replay_reuses_group_and_assets(self):
        """Replay of same draft reuses session group + assets + seeding logs; activity log re-posted."""
        client = make_session_mock_client()
        r1 = await commit_seeding_session(client, _draft_for(MAY22_FIXTURE), {})
        assert r1["ok"] is True
        groups_after_first = len(client["_created"]["groups"])         # 1
        assets_after_first = len(client["_created"]["assets"])         # 16
        seeding_after_first = len(
            [l for l in client["_created"]["logs"] if l["type"] == "seeding"]
        )  # 11
        activity_after_first = len(client["_created"]["activity_logs"])  # 1

        r2 = await commit_seeding_session(client, _draft_for(MAY22_FIXTURE), {})
        assert r2["ok"] is True

        # No new group POST (reused via draft-id trailer match)
        assert len(client["_created"]["groups"]) == groups_after_first
        # No new fungi POSTs
        assert len(client["_created"]["assets"]) == assets_after_first
        # No new seeding log POSTs
        assert len(
            [l for l in client["_created"]["logs"] if l["type"] == "seeding"]
        ) == seeding_after_first
        # BUT activity log is creation-only -> one new POST
        assert len(client["_created"]["activity_logs"]) == activity_after_first + 1

        # r2.asset_ids does not include session group (outcome=reused)
        assert r2["asset_ids"] == []
        # log_ids: membership log + 11 seeding log ids
        assert len(r2["log_ids"]) == 12

    async def test_invalid_session_missing_event_date(self):
        dj = {"groups": [{"parent": {"value": "X"}, "species": {"value": "SHI"},
                          "qty": {"value": 1}}]}
        client = make_session_mock_client()
        r = await commit_seeding_session(client, _draft_for(dj), {})
        assert r["ok"] is False
        assert r["reason"] == "invalid_seeding_session"

    async def test_invalid_session_empty_groups(self):
        dj = {"event_date": "2026-05-22", "groups": []}
        client = make_session_mock_client()
        r = await commit_seeding_session(client, _draft_for(dj), {})
        assert r["ok"] is False
        assert r["reason"] == "invalid_seeding_session"


class TestCommitSeedingSessionImageAttach:
    """Page-image attach via field-scoped binary route (D-03 / Phase 55B)."""

    async def test_image_upload_targets_group_image_field_route(self):
        """postBinary called with /api/asset/group/{sessionGroupId}/image."""
        client = make_session_mock_client()
        post_binary_calls: list = []

        async def _post_binary_spy(path: str, data: bytes, filename=None, opts=None) -> dict:
            post_binary_calls.append(path)
            return _ok(200, {"data": {"id": "file-uuid-img-1", "type": "file--file"}})

        client["post_binary"] = _post_binary_spy

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8")
            real_page_path = f.name
        try:
            ctx = {"session_page_paths": [real_page_path]}
            r = await commit_seeding_session(
                client, _draft_for(MAY22_FIXTURE, "d-img-1"), ctx
            )
            assert r["ok"] is True
            assert len(post_binary_calls) == 1
            session_group_id = client["_created"]["groups"][0]["id"]
            assert post_binary_calls[0] == f"/api/asset/group/{session_group_id}/image"
        finally:
            os.unlink(real_page_path)

    async def test_image_upload_failure_is_non_fatal(self):
        """Upload failure leaves ok=True and populates attachments_failed."""
        client = make_session_mock_client()

        async def _post_binary_fail(path: str, data: bytes, filename=None, opts=None) -> dict:
            return _ok(500, {"errors": [{"status": "500"}]})

        client["post_binary"] = _post_binary_fail

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8")
            real_page_path = f.name
        try:
            ctx = {"session_page_paths": [real_page_path]}
            r = await commit_seeding_session(
                client, _draft_for(MAY22_FIXTURE, "d-img-3"), ctx
            )
            assert r["ok"] is True
            assert isinstance(r.get("attachments_failed"), list)
            assert len(r["attachments_failed"]) >= 1
        finally:
            os.unlink(real_page_path)

    async def test_image_no_legacy_patch_for_file_relationship(self):
        """Field-scoped upload must NOT trigger a relationships.file PATCH."""
        client = make_session_mock_client()
        patch_calls: list = []

        orig_patch = client["patch"]

        async def _patch_spy(path: str, body: dict, opts=None) -> dict:
            patch_calls.append((path, body))
            return await orig_patch(path, body, opts)

        client["patch"] = _patch_spy

        async def _post_binary_ok(path: str, data: bytes, filename=None, opts=None) -> dict:
            return _ok(200, {"data": {"id": "file-uuid-img-2"}})

        client["post_binary"] = _post_binary_ok

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8")
            real_page_path = f.name
        try:
            ctx = {"session_page_paths": [real_page_path]}
            await commit_seeding_session(client, _draft_for(MAY22_FIXTURE, "d-img-2"), ctx)
            # Verify no PATCH to the group with relationships.file
            patched_group_file = any(
                re.search(r"/api/asset/group/", p)
                and b.get("data", {}).get("relationships", {}).get("file")
                for p, b in patch_calls
            )
            assert patched_group_file is False
        finally:
            os.unlink(real_page_path)

    async def test_image_upload_file_id_in_result(self):
        """Successful upload populates file_ids in result."""
        client = make_session_mock_client()

        async def _post_binary_ok(path: str, data: bytes, filename=None, opts=None) -> dict:
            return _ok(200, {"data": {"id": "file-uuid-success"}})

        client["post_binary"] = _post_binary_ok

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8")
            real_page_path = f.name
        try:
            ctx = {"session_page_paths": [real_page_path]}
            r = await commit_seeding_session(
                client, _draft_for(MAY22_FIXTURE, "d-img-4"), ctx
            )
            assert r["ok"] is True
            assert "file-uuid-success" in r["file_ids"]
        finally:
            os.unlink(real_page_path)


# ---------------------------------------------------------------------------
# Acceptance: /api/asset/group route is present in commit_seeding_session.py
# ---------------------------------------------------------------------------

def test_group_image_route_in_commit_seeding_session():
    """Verify field-scoped group image route is referenced in the module."""
    import subprocess
    result = subprocess.run(
        ["grep", "-c", "/api/asset/group", "farm_agent/farmos/commits/commit_seeding_session.py"],
        capture_output=True,
        text=True,
        cwd="/mnt/slime-kingdom/opt/mushy/src/farm-agent",
    )
    count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
    assert count >= 1, "Expected /api/asset/group reference in commit_seeding_session.py"
