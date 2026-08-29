"""Tests for farm_agent.farmos.logs (Phase 62-06).

Mirrors logs.test.js: create_log, LOG_STABLE_KEYS table, and upsert_log.
All external I/O is mocked; no real network or DB calls.
"""
from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from farm_agent.farmos.logs import (
    LOG_STABLE_KEYS,
    LOG_TYPES,
    NATIVE_LOG_TYPES,
    LogIdentityCollision,
    UnsupportedLogTypeError,
    create_log,
    upsert_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def mock_post_client(log_id="log-1", status=201):
    """Client with only a post() that succeeds."""
    client = {
        "post": AsyncMock(
            return_value={"ok": True, "status": status, "body": {"data": {"id": log_id}}}
        ),
    }
    return client


def rich_mock(
    seed_logs=None,
    logs_by_id=None,
    patch_fails_412_once=None,
    create_log_id_seq="log-new-1",
):
    """Mirrors richMock() in logs.test.js.

    Args:
        seed_logs: list of minimal log bodies returned by the filter GET.
        logs_by_id: dict {id: full_body} returned by GET /api/log/seeding/<id>.
        patch_fails_412_once: set of log ids whose first PATCH returns 412.
        create_log_id_seq: prefix used to generate post response ids.
    """
    if seed_logs is None:
        seed_logs = []
    if logs_by_id is None:
        logs_by_id = {}
    if patch_fails_412_once is None:
        patch_fails_412_once = set()

    force412 = set(patch_fails_412_once)
    seq = {"n": 1}

    async def _get(path, opts=None):
        import re

        m = re.match(r"^/api/log/seeding\?filter\[asset\.id\]\[value\]=(.+)$", path)
        if m:
            return {"ok": True, "status": 200, "body": {"data": seed_logs}}
        m = re.match(r"^/api/log/seeding/([A-Za-z0-9_-]+)$", path)
        if m:
            lid = m.group(1)
            if lid in logs_by_id:
                return {"ok": True, "status": 200, "body": {"data": logs_by_id[lid]}}
            return {"ok": False, "status": 404, "body": {}}
        return {"ok": True, "status": 200, "body": {"data": []}}

    async def _post(path, body=None, opts=None):
        lid = f"{create_log_id_seq}-{seq['n']}"
        seq["n"] += 1
        return {"ok": True, "status": 201, "body": {"data": {"id": lid, "type": "log--seeding"}}}

    async def _patch(path, body=None, opts=None):
        import re

        m = re.match(r"^/api/log/[a-z_]+/([A-Za-z0-9_-]+)$", path)
        lid = m.group(1) if m else None
        if lid and lid in force412:
            force412.discard(lid)
            return {"ok": False, "status": 412, "body": {"errors": [{"status": "412"}]}}
        return {
            "ok": True,
            "status": 200,
            "body": {
                "data": {
                    "id": lid,
                    "type": "log--seeding",
                    "attributes": {"drupal_internal__revision_id": 2},
                }
            },
        }

    get_mock = AsyncMock(side_effect=_get)
    post_mock = AsyncMock(side_effect=_post)
    patch_mock = AsyncMock(side_effect=_patch)

    return {
        "get": get_mock,
        "post": post_mock,
        "patch": patch_mock,
    }


# ===========================================================================
# Task 1: create_log + LOG_STABLE_KEYS + helpers
# ===========================================================================


class TestCreateLog:
    @pytest.mark.parametrize("log_type", NATIVE_LOG_TYPES)
    @pytest.mark.asyncio
    async def test_posts_to_correct_url_with_correct_payload(self, log_type):
        """create_log <type> posts to /api/log/<type> with correct payload shape."""
        client = mock_post_client()
        await create_log(
            client,
            log_type,
            {
                "name": f"{log_type} test",
                "timestamp": 1700000000.7,
                "asset_ids": ["a1"],
                "notes": "hi",
                "draft_id": "d1",
            },
        )
        client["post"].assert_called_once()
        url, body = client["post"].call_args.args
        assert url == f"/api/log/{log_type}"
        assert body["data"]["type"] == f"log--{log_type}"
        assert body["data"]["attributes"]["timestamp"] == 1700000000  # math.floor
        assert "mushy:draft:d1" in body["data"]["attributes"]["notes"]["value"]
        assert body["data"]["relationships"]["asset"]["data"][0]["id"] == "a1"

    @pytest.mark.asyncio
    async def test_unsupported_log_type_raises_before_fetch(self):
        """create_log 'garbage' raises UnsupportedLogTypeError without calling post."""
        client = mock_post_client()
        with pytest.raises(UnsupportedLogTypeError, match="unsupported_log_type"):
            await create_log(client, "garbage", {"name": "x", "timestamp": 0, "draft_id": "d"})
        client["post"].assert_not_called()

    @pytest.mark.asyncio
    async def test_seeding_session_raises_unsupported(self):
        """seeding_session is router-only; create_log rejects it."""
        client = mock_post_client()
        with pytest.raises(UnsupportedLogTypeError):
            await create_log(client, "seeding_session", {"name": "x", "timestamp": 0, "draft_id": "d"})
        client["post"].assert_not_called()

    @pytest.mark.asyncio
    async def test_file_ids_embedded_in_relationships(self):
        """fileIds present -> relationships.file.data list of file--file."""
        client = mock_post_client()
        await create_log(
            client,
            "observation",
            {
                "name": "obs",
                "timestamp": 1000,
                "asset_ids": ["a1"],
                "file_ids": ["f1", "f2"],
                "draft_id": "d",
            },
        )
        _, body = client["post"].call_args.args
        file_ids = [d["id"] for d in body["data"]["relationships"]["image"]["data"]]
        assert file_ids == ["f1", "f2"]
        assert all(d["type"] == "file--file" for d in body["data"]["relationships"]["image"]["data"])

    @pytest.mark.asyncio
    async def test_no_file_relationship_when_no_file_ids(self):
        """No file_ids -> no relationships.file key in payload."""
        client = mock_post_client()
        await create_log(
            client,
            "seeding",
            {"name": "x", "timestamp": 1000, "asset_ids": ["a1"], "draft_id": "d"},
        )
        _, body = client["post"].call_args.args
        assert "image" not in body["data"]["relationships"]

    @pytest.mark.asyncio
    async def test_timestamp_floored(self):
        """timestamp is math.floor'd in the payload."""
        client = mock_post_client()
        await create_log(
            client,
            "seeding",
            {"name": "x", "timestamp": 1700000000.999, "asset_ids": [], "draft_id": "d"},
        )
        _, body = client["post"].call_args.args
        assert body["data"]["attributes"]["timestamp"] == 1700000000

    @pytest.mark.asyncio
    async def test_notes_marker_appended(self):
        """mushy:draft:<id> marker is always in notes value."""
        client = mock_post_client()
        await create_log(
            client,
            "seeding",
            {"name": "x", "timestamp": 0, "asset_ids": [], "notes": "some notes", "draft_id": "d42"},
        )
        _, body = client["post"].call_args.args
        notes_value = body["data"]["attributes"]["notes"]["value"]
        assert "mushy:draft:d42" in notes_value
        assert "some notes" in notes_value

    @pytest.mark.asyncio
    async def test_ok_false_on_http_error(self):
        """Non-2xx response from farmOS -> returns ok:False envelope."""
        client = {
            "post": AsyncMock(return_value={"ok": False, "status": 500, "body": None})
        }
        r = await create_log(
            client, "seeding", {"name": "x", "timestamp": 0, "asset_ids": [], "draft_id": "d"}
        )
        assert r["ok"] is False
        assert r["reason"] == "http_500"

    @pytest.mark.asyncio
    async def test_ok_true_returns_log_id(self):
        """Successful POST returns ok:True with logId."""
        client = mock_post_client(log_id="log-abc", status=201)
        r = await create_log(
            client, "seeding", {"name": "x", "timestamp": 0, "asset_ids": [], "draft_id": "d"}
        )
        assert r["ok"] is True
        assert r["log_id"] == "log-abc"
        assert r["http_status"] == 201

    @pytest.mark.asyncio
    async def test_status_is_done(self):
        """Log body always has status='done'."""
        client = mock_post_client()
        await create_log(
            client,
            "harvest",
            {"name": "hv", "timestamp": 1000, "asset_ids": [], "draft_id": "d"},
        )
        _, body = client["post"].call_args.args
        assert body["data"]["attributes"]["status"] == "done"


class TestLogStableKeys:
    def test_seeding_is_callable(self):
        assert callable(LOG_STABLE_KEYS["seeding"])

    def test_seeding_builds_filter_path(self):
        k = LOG_STABLE_KEYS["seeding"]({"asset_ids": ["a1"]})
        assert k == {"path": "/api/log/seeding?filter[asset.id][value]=a1"}

    def test_seeding_empty_asset_ids_returns_none(self):
        assert LOG_STABLE_KEYS["seeding"]({"asset_ids": []}) is None
        assert LOG_STABLE_KEYS["seeding"]({}) is None

    def test_seeding_url_encodes_asset_id(self):
        k = LOG_STABLE_KEYS["seeding"]({"asset_ids": ["a/b c"]})
        from urllib.parse import quote

        assert k["path"] == "/api/log/seeding?filter[asset.id][value]=" + quote("a/b c")

    def test_activity_is_none(self):
        assert LOG_STABLE_KEYS["activity"] is None

    def test_input_is_none(self):
        assert LOG_STABLE_KEYS["input"] is None

    def test_observation_is_none(self):
        assert LOG_STABLE_KEYS["observation"] is None

    def test_harvest_is_none(self):
        assert LOG_STABLE_KEYS["harvest"] is None


class TestLogTypeConstants:
    def test_native_log_types_list(self):
        assert NATIVE_LOG_TYPES == ["seeding", "activity", "input", "observation", "harvest"]

    def test_log_types_includes_seeding_session(self):
        assert "seeding_session" in LOG_TYPES
        for t in NATIVE_LOG_TYPES:
            assert t in LOG_TYPES


class TestUnsupportedLogTypeError:
    def test_error_attributes(self):
        err = UnsupportedLogTypeError("bogus")
        assert err.log_type == "bogus"
        assert "unsupported_log_type" in str(err)
        assert err.name == "UnsupportedLogTypeError"


class TestLogIdentityCollision:
    def test_error_attributes(self):
        err = LogIdentityCollision("seeding", "a1", ["L1", "L2"])
        assert err.name == "LogIdentityCollision"
        assert err.log_type == "seeding"
        assert err.asset_id == "a1"
        assert err.matched_ids == ["L1", "L2"]


# ===========================================================================
# Task 2: upsert_log
# ===========================================================================


class TestUpsertLog:
    @pytest.mark.asyncio
    async def test_seeding_miss_creates_new_log(self):
        """seeding miss: no existing log -> POST via create_log, outcome=created."""
        client = rich_mock(seed_logs=[])
        r = await upsert_log(
            client,
            "seeding",
            {"name": "inoc", "timestamp": 1700000000, "asset_ids": ["a1"], "draft_id": "d1"},
        )
        assert r["ok"] is True
        assert r["outcome"] == "created"
        assert r["conflicts"] == []
        assert r["etag_source"] is None
        assert r["http_status"] == 201
        client["post"].assert_called_once()
        client["patch"].assert_not_called()
        # Lookup happened
        get_calls = [c.args[0] for c in client["get"].call_args_list]
        assert any("filter[asset.id][value]=a1" in p for p in get_calls)

    @pytest.mark.asyncio
    async def test_seeding_hit_new_file_ids_patch(self):
        """seeding hit: incoming adds a file id -> PATCH merges file set-union, outcome=patched."""
        existing = {
            "id": "L1",
            "type": "log--seeding",
            "attributes": {
                "name": "inoc",
                "timestamp": 1700000000,
                "status": "done",
                "notes": {"value": "mushy:draft:d_old", "format": "plain_text"},
                "created": "2026-05-22T10:00:00+00:00",
                "drupal_internal__revision_id": 7,
            },
            "relationships": {
                "asset": {"data": [{"type": "asset--fungi", "id": "a1"}]},
                "image": {"data": []},
            },
        }
        client = rich_mock(
            seed_logs=[{"id": "L1", "attributes": {"created": existing["attributes"]["created"]}}],
            logs_by_id={"L1": existing},
        )
        r = await upsert_log(
            client,
            "seeding",
            {
                "name": "inoc",
                "timestamp": 1700000000,
                "asset_ids": ["a1"],
                "file_ids": ["f1"],
                "notes": "",
                "draft_id": "d_new",
            },
        )
        assert r["ok"] is True
        assert r["outcome"] == "patched"
        assert r["log_id"] == "L1"
        assert r["conflicts"] == []
        assert r["etag_source"] == "soft_compare"
        assert r["http_status"] == 200
        client["patch"].assert_called_once()
        patch_path, patch_body = client["patch"].call_args.args[:2]
        assert patch_path == "/api/log/seeding/L1"
        file_ids = sorted(d["id"] for d in patch_body["data"]["relationships"]["image"]["data"])
        assert file_ids == ["f1"]
        assert patch_body["data"]["relationships"]["image"]["data"][0] == {"type": "file--file", "id": "f1"}

    @pytest.mark.asyncio
    async def test_seeding_noop_no_new_fields(self):
        """seeding hit noop: incoming brings no new fields -> outcome=noop, no PATCH."""
        existing = {
            "id": "L1",
            "type": "log--seeding",
            "attributes": {
                "name": "inoc",
                "timestamp": 1700000000,
                "status": "done",
                "notes": {"value": "mushy:draft:d_old", "format": "plain_text"},
                "created": "2026-05-22T10:00:00+00:00",
                "drupal_internal__revision_id": 7,
            },
            "relationships": {
                "asset": {"data": [{"type": "asset--fungi", "id": "a1"}]},
                "image": {"data": [{"type": "file--file", "id": "f1"}]},
            },
        }
        client = rich_mock(
            seed_logs=[{"id": "L1", "attributes": {"created": existing["attributes"]["created"]}}],
            logs_by_id={"L1": existing},
        )
        r = await upsert_log(
            client,
            "seeding",
            {
                "name": "inoc",
                "timestamp": 1700000000,
                "asset_ids": ["a1"],
                "file_ids": ["f1"],
                "notes": "",
                "draft_id": "d_old",  # same trailer -> notes already present
            },
        )
        assert r["ok"] is True
        assert r["outcome"] == "noop"
        assert r["log_id"] == "L1"
        assert r["conflicts"] == []
        client["patch"].assert_not_called()
        client["post"].assert_not_called()

    @pytest.mark.asyncio
    async def test_seeding_collision_picks_oldest(self):
        """seeding collision (>1 match): picks oldest by created, emits LogIdentityCollision warning."""
        older_id = "L_OLDER"
        newer_id = "L_NEWER"
        older_body = {
            "id": older_id,
            "type": "log--seeding",
            "attributes": {
                "name": "inoc",
                "timestamp": 1700000000,
                "status": "done",
                "notes": {"value": "", "format": "plain_text"},
                "created": "2026-05-22T10:00:00+00:00",
                "drupal_internal__revision_id": 1,
            },
            "relationships": {
                "asset": {"data": [{"type": "asset--fungi", "id": "a1"}]},
                "image": {"data": []},
            },
        }
        newer_body = dict(older_body, id=newer_id, attributes=dict(older_body["attributes"], created="2026-05-22T11:00:00+00:00"))
        seed_logs = [
            {"id": newer_id, "attributes": {"created": newer_body["attributes"]["created"]}},
            {"id": older_id, "attributes": {"created": older_body["attributes"]["created"]}},
        ]

        audit_calls = []

        async def audit_log_commit(event, payload):
            audit_calls.append((event, payload))

        audit_logger = {"log_commit": audit_log_commit}

        client = rich_mock(
            seed_logs=seed_logs,
            logs_by_id={older_id: older_body, newer_id: newer_body},
        )
        r = await upsert_log(
            client,
            "seeding",
            {
                "name": "inoc",
                "timestamp": 1700000000,
                "asset_ids": ["a1"],
                "file_ids": ["f_new"],
                "notes": "",
                "draft_id": "d1",
                "audit_logger": audit_logger,
            },
        )
        assert r["ok"] is True
        assert r["log_id"] == older_id  # older wins
        assert any("LogIdentityCollision" in w for w in r["warnings"])
        client["patch"].assert_called_once()
        patch_path = client["patch"].call_args.args[0]
        assert patch_path == f"/api/log/seeding/{older_id}"
        # audit logger received the collision event
        collision_calls = [c for c in audit_calls if c[0] == "log_identity_collision"]
        assert collision_calls
        assert collision_calls[0][1]["log_type"] == "seeding"
        assert collision_calls[0][1]["asset_id"] == "a1"
        assert older_id in collision_calls[0][1]["matched_ids"]
        assert newer_id in collision_calls[0][1]["matched_ids"]

    @pytest.mark.asyncio
    async def test_seeding_collision_tiebreak_lexicographic(self):
        """same created -> lexicographic by id ASC."""
        id_a = "L_A"
        id_b = "L_B"
        created = "2026-05-22T10:00:00+00:00"
        body_a = {
            "id": id_a, "type": "log--seeding",
            "attributes": {"name": "inoc", "timestamp": 1700000000, "status": "done",
                           "notes": {"value": "", "format": "plain_text"},
                           "created": created, "drupal_internal__revision_id": 1},
            "relationships": {
                "asset": {"data": [{"type": "asset--fungi", "id": "a1"}]},
                "image": {"data": []},
            },
        }
        body_b = dict(body_a, id=id_b)
        client = rich_mock(
            seed_logs=[
                {"id": id_b, "attributes": {"created": created}},
                {"id": id_a, "attributes": {"created": created}},
            ],
            logs_by_id={id_a: body_a, id_b: body_b},
        )
        r = await upsert_log(
            client,
            "seeding",
            {"name": "inoc", "timestamp": 1700000000, "asset_ids": ["a1"], "file_ids": ["f_new"], "draft_id": "d1"},
        )
        assert r["log_id"] == id_a  # lexicographic ASC -> L_A wins

    @pytest.mark.asyncio
    async def test_seeding_412_retry_once(self):
        """412 on first PATCH -> soft-compare retry succeeds once."""
        existing = {
            "id": "L1", "type": "log--seeding",
            "attributes": {
                "name": "inoc", "timestamp": 1700000000, "status": "done",
                "notes": {"value": "", "format": "plain_text"},
                "created": "2026-05-22T10:00:00+00:00",
                "drupal_internal__revision_id": 7,
            },
            "relationships": {
                "asset": {"data": [{"type": "asset--fungi", "id": "a1"}]},
                "image": {"data": []},
            },
        }
        client = rich_mock(
            seed_logs=[{"id": "L1", "attributes": {"created": existing["attributes"]["created"]}}],
            logs_by_id={"L1": existing},
            patch_fails_412_once={"L1"},
        )
        r = await upsert_log(
            client,
            "seeding",
            {"name": "inoc", "timestamp": 1700000000, "asset_ids": ["a1"], "file_ids": ["f1"], "draft_id": "d1"},
        )
        assert r["ok"] is True
        assert r["outcome"] == "patched"
        # 2 PATCHes (1st fails 412, 2nd succeeds)
        assert client["patch"].call_count == 2

    @pytest.mark.asyncio
    async def test_seeding_identity_mismatch(self):
        """incoming assetIds differ from existing -> ok:False reason log_identity_mismatch."""
        existing = {
            "id": "L1", "type": "log--seeding",
            "attributes": {"name": "inoc", "timestamp": 1700000000, "status": "done",
                           "notes": {"value": "", "format": "plain_text"},
                           "created": "2026-05-22T10:00:00+00:00",
                           "drupal_internal__revision_id": 1},
            "relationships": {
                "asset": {"data": [{"type": "asset--fungi", "id": "a1"},
                                   {"type": "asset--fungi", "id": "a2"}]},
                "image": {"data": []},
            },
        }
        client = rich_mock(
            seed_logs=[{"id": "L1", "attributes": {"created": existing["attributes"]["created"]}}],
            logs_by_id={"L1": existing},
        )
        r = await upsert_log(
            client,
            "seeding",
            {"name": "inoc", "timestamp": 1700000000, "asset_ids": ["a1"], "draft_id": "d1"},  # missing a2
        )
        assert r["ok"] is False
        assert r["reason"] == "log_identity_mismatch"

    @pytest.mark.asyncio
    async def test_seeding_without_asset_ids_missing_stable_key(self):
        """seeding without assetIds: returns ok:False reason missing_stable_key."""
        client = rich_mock()
        r = await upsert_log(
            client,
            "seeding",
            {"name": "inoc", "timestamp": 1700000000, "asset_ids": [], "draft_id": "d1"},
        )
        assert r["ok"] is False
        assert r["reason"] == "missing_stable_key"
        client["get"].assert_not_called()
        client["post"].assert_not_called()

    @pytest.mark.asyncio
    async def test_non_seeding_pass_through_activity(self):
        """activity delegates to create_log (POST), no lookup."""
        client = rich_mock()
        r = await upsert_log(
            client,
            "activity",
            {"name": "act", "timestamp": 1700000000, "asset_ids": ["a1"], "draft_id": "d1"},
        )
        assert r["ok"] is True
        assert r["outcome"] == "created"
        assert r["conflicts"] == []
        assert r["etag_source"] is None
        client["post"].assert_called_once()
        assert client["post"].call_args.args[0] == "/api/log/activity"
        # No filter GET for activity
        get_calls = [c.args[0] for c in client["get"].call_args_list]
        assert not any("/api/log/activity?" in p for p in get_calls)

    @pytest.mark.asyncio
    async def test_non_seeding_pass_through_harvest(self):
        """harvest delegates to create_log (POST)."""
        client = rich_mock()
        r = await upsert_log(
            client,
            "harvest",
            {"name": "hv", "timestamp": 1700000000, "asset_ids": ["a1"], "draft_id": "d1"},
        )
        assert r["ok"] is True
        assert r["outcome"] == "created"
        client["post"].assert_called_once()
        assert client["post"].call_args.args[0] == "/api/log/harvest"

    @pytest.mark.asyncio
    async def test_non_native_type_raises(self):
        """non-native type: upsert_log raises UnsupportedLogTypeError."""
        client = rich_mock()
        with pytest.raises(UnsupportedLogTypeError, match="unsupported_log_type"):
            await upsert_log(client, "bogus", {"name": "x", "timestamp": 0, "draft_id": "d"})
        client["post"].assert_not_called()
        client["patch"].assert_not_called()

    @pytest.mark.asyncio
    async def test_re_run_idempotency(self):
        """Re-run: two upsert_log for the same (seeding, asset_id) -> at most one seeding log."""
        existing = {
            "id": "L1", "type": "log--seeding",
            "attributes": {
                "name": "inoc", "timestamp": 1700000000, "status": "done",
                "notes": {"value": "mushy:draft:d1", "format": "plain_text"},
                "created": "2026-05-22T10:00:00+00:00",
                "drupal_internal__revision_id": 7,
            },
            "relationships": {
                "asset": {"data": [{"type": "asset--fungi", "id": "a1"}]},
                "image": {"data": []},
            },
        }
        client = rich_mock(
            seed_logs=[{"id": "L1", "attributes": {"created": existing["attributes"]["created"]}}],
            logs_by_id={"L1": existing},
        )
        opts = {"name": "inoc", "timestamp": 1700000000, "asset_ids": ["a1"], "draft_id": "d1"}
        r1 = await upsert_log(client, "seeding", opts)
        r2 = await upsert_log(client, "seeding", opts)
        # No duplicate POST; second call is noop or patched
        assert client["post"].call_count == 0  # first call is a hit too (log already existed)
        assert r1["outcome"] in ("noop", "patched")
        assert r2["outcome"] in ("noop", "patched")
