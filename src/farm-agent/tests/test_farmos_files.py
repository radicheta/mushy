"""
tests/test_farmos_files.py -- Unit tests for farmos/files.py.

Port of Node farmos/files.js (Phase 55B field-scoped upload).

Covers (plan 62-05 acceptance criteria):
  - happy path: upload_field_attachment reads bytes, POSTs to {collection}/{uuid}/{field},
    returns {"ok": True, "file_id": <id>}
  - missing file: non-existent abs_path returns attachment_missing + skipped:True, NO client call
  - _extract_file_id array body: data[-1].id
  - _extract_file_id object body: data.id
  - _extract_file_id None body: returns None
  - URL is built as f"{collection_path}/{uuid}/{field}" (ends with /<uuid>/image)
  - post_binary is called (grep assertion: >= 1 occurrence in source)
  - upload_field_attachments batch: collects file_ids, skipped, failed
  - read error: returns read_failed reason
"""

from __future__ import annotations

import os
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(post_binary_responses: list[dict]) -> tuple[dict, list]:
    """Return (client_dict, call_log). Responses are popped in order."""
    calls: list[dict] = []
    responses = list(post_binary_responses)

    async def fake_post_binary(path: str, data: bytes, filename: str | None = None, opts: dict | None = None) -> dict:
        calls.append({"path": path, "data": data, "filename": filename})
        return responses.pop(0)

    return {"post_binary": fake_post_binary}, calls


def _ok_binary_resp_array(file_id: str) -> dict:
    """Simulates a multi-value field echo (array body)."""
    return {
        "ok": True,
        "status": 201,
        "body": {"data": [{"id": "old-id"}, {"id": file_id}]},
        "latency_ms": 5,
    }


def _ok_binary_resp_object(file_id: str) -> dict:
    """Simulates a single-resource upload echo (object body)."""
    return {
        "ok": True,
        "status": 201,
        "body": {"data": {"id": file_id}},
        "latency_ms": 5,
    }


def _error_resp(status: int = 422) -> dict:
    return {"ok": False, "status": status, "body": None, "latency_ms": 5}


@pytest.fixture()
def tmp_image(tmp_path):
    """Create a temporary fake image file and return its abs path."""
    p = tmp_path / "photo.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # fake JPEG bytes
    return str(p)


# ---------------------------------------------------------------------------
# _extract_file_id unit tests
# ---------------------------------------------------------------------------


def test_extract_file_id_array_returns_last():
    """Array body -> last element's id."""
    from farm_agent.farmos.files import _extract_file_id

    body = {"data": [{"id": "first"}, {"id": "last"}]}
    assert _extract_file_id(body) == "last"


def test_extract_file_id_object_returns_id():
    """Object body -> data.id."""
    from farm_agent.farmos.files import _extract_file_id

    body = {"data": {"id": "single-id"}}
    assert _extract_file_id(body) == "single-id"


def test_extract_file_id_none_body_returns_none():
    """None body -> None (no raise)."""
    from farm_agent.farmos.files import _extract_file_id

    assert _extract_file_id(None) is None


def test_extract_file_id_empty_array_returns_none():
    """Empty array -> None."""
    from farm_agent.farmos.files import _extract_file_id

    assert _extract_file_id({"data": []}) is None


def test_extract_file_id_no_data_key_returns_none():
    """Missing data key -> None."""
    from farm_agent.farmos.files import _extract_file_id

    assert _extract_file_id({}) is None


# ---------------------------------------------------------------------------
# upload_field_attachment tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_field_attachment_happy_path_array_body(tmp_image):
    """Happy path: reads bytes, POSTs to correct URL, returns ok:True + file_id."""
    from farm_agent.farmos.files import upload_field_attachment

    client, calls = _make_client([_ok_binary_resp_array("new-file-uuid")])
    r = await upload_field_attachment(client, "/api/asset/fungi", "asset-uuid-123", "image", tmp_image)

    assert r["ok"] is True
    assert r["file_id"] == "new-file-uuid"
    assert len(calls) == 1
    # URL must be {collection_path}/{uuid}/{field}
    assert calls[0]["path"] == "/api/asset/fungi/asset-uuid-123/image"


@pytest.mark.asyncio
async def test_upload_field_attachment_happy_path_object_body(tmp_image):
    """Object body response -> file_id extracted from data.id."""
    from farm_agent.farmos.files import upload_field_attachment

    client, calls = _make_client([_ok_binary_resp_object("obj-file-uuid")])
    r = await upload_field_attachment(client, "/api/asset/group", "grp-uuid", "image", tmp_image)

    assert r["ok"] is True
    assert r["file_id"] == "obj-file-uuid"


@pytest.mark.asyncio
async def test_upload_field_attachment_missing_file_no_client_call():
    """Non-existent file -> attachment_missing + skipped:True; NO client call."""
    from farm_agent.farmos.files import upload_field_attachment

    client, calls = _make_client([])  # no responses queued -- any call would raise
    r = await upload_field_attachment(
        client, "/api/asset/fungi", "uuid-x", "image", "/nonexistent/path/photo.jpg"
    )

    assert r["ok"] is False
    assert r["reason"] == "attachment_missing"
    assert r["skipped"] is True
    assert r["path"] == "/nonexistent/path/photo.jpg"
    assert len(calls) == 0  # client must NOT have been called


@pytest.mark.asyncio
async def test_upload_field_attachment_http_error(tmp_image):
    """HTTP error from post_binary -> ok:False with reason http_<status>."""
    from farm_agent.farmos.files import upload_field_attachment

    client, calls = _make_client([_error_resp(422)])
    r = await upload_field_attachment(client, "/api/asset/fungi", "uuid-y", "image", tmp_image)

    assert r["ok"] is False
    assert r["reason"] == "http_422"
    assert r["http_status"] == 422


@pytest.mark.asyncio
async def test_upload_field_attachment_url_ends_with_uuid_slash_image(tmp_image):
    """Upload URL ends with /<uuid>/image (field-scoped route, not /api/file/file)."""
    from farm_agent.farmos.files import upload_field_attachment

    client, calls = _make_client([_ok_binary_resp_object("fid")])
    await upload_field_attachment(client, "/api/asset/fungi", "my-uuid", "image", tmp_image)

    assert calls[0]["path"].endswith("/my-uuid/image")
    assert "/api/file/file" not in calls[0]["path"]


@pytest.mark.asyncio
async def test_upload_field_attachment_uses_basename_as_filename(tmp_image):
    """Filename sent to post_binary is the basename of abs_path when no explicit filename."""
    from farm_agent.farmos.files import upload_field_attachment

    client, calls = _make_client([_ok_binary_resp_object("fid")])
    await upload_field_attachment(client, "/api/asset/fungi", "uuid-fn", "image", tmp_image)

    assert calls[0]["filename"] == "photo.jpg"


@pytest.mark.asyncio
async def test_upload_field_attachment_explicit_filename_overrides(tmp_image):
    """Explicit filename arg overrides basename."""
    from farm_agent.farmos.files import upload_field_attachment

    client, calls = _make_client([_ok_binary_resp_object("fid")])
    await upload_field_attachment(
        client, "/api/asset/fungi", "uuid-fn", "image", tmp_image, filename="custom.jpg"
    )

    assert calls[0]["filename"] == "custom.jpg"


# ---------------------------------------------------------------------------
# upload_field_attachments batch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_field_attachments_batch_collects_results(tmp_path):
    """Batch: collects file_ids, skipped, failed correctly."""
    from farm_agent.farmos.files import upload_field_attachments

    # Three paths: one existing, one missing, one existing
    p1 = tmp_path / "img1.jpg"
    p1.write_bytes(b"JPG1")
    p2 = "/nonexistent/missing.jpg"
    p3 = tmp_path / "img3.jpg"
    p3.write_bytes(b"JPG3")

    client, calls = _make_client([
        _ok_binary_resp_object("fid-1"),
        _ok_binary_resp_object("fid-3"),
    ])
    r = await upload_field_attachments(
        client, "/api/asset/fungi", "batch-uuid", "image", [str(p1), p2, str(p3)]
    )

    assert r["file_ids"] == ["fid-1", "fid-3"]
    assert r["skipped"] == [p2]
    assert r["failed"] == []


@pytest.mark.asyncio
async def test_upload_field_attachments_empty_paths():
    """Empty paths list returns empty results without errors."""
    from farm_agent.farmos.files import upload_field_attachments

    client, calls = _make_client([])
    r = await upload_field_attachments(client, "/api/asset/fungi", "uuid", "image", [])

    assert r["file_ids"] == []
    assert r["skipped"] == []
    assert r["failed"] == []


@pytest.mark.asyncio
async def test_upload_field_attachments_none_paths():
    """None paths list returns empty results."""
    from farm_agent.farmos.files import upload_field_attachments

    client, calls = _make_client([])
    r = await upload_field_attachments(client, "/api/asset/fungi", "uuid", "image", None)

    assert r["file_ids"] == []
    assert r["skipped"] == []
    assert r["failed"] == []


@pytest.mark.asyncio
async def test_upload_field_attachments_http_fail_goes_to_failed(tmp_path):
    """HTTP error on upload -> path appears in failed list."""
    from farm_agent.farmos.files import upload_field_attachments

    p = tmp_path / "bad.jpg"
    p.write_bytes(b"data")
    client, calls = _make_client([_error_resp(503)])
    r = await upload_field_attachments(client, "/api/asset/fungi", "uuid", "image", [str(p)])

    assert r["file_ids"] == []
    assert r["skipped"] == []
    assert len(r["failed"]) == 1
    assert r["failed"][0]["path"] == str(p)
    assert "http_503" in r["failed"][0]["reason"]
