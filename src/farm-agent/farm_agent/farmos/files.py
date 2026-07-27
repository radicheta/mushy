"""
farm_agent/farmos/files.py -- Field-scoped octet-stream image upload for farmOS.

Port of src/agents/alerter/src/farmos/files.js (Phase 55B, 2026-06-14).

WARNING: The legacy /api/file/file route (uploadAttachment) is NOT ported here.
That route returns 415 on this farmOS (no Content-Type: application/octet-stream
routing). The ONLY working mechanism is the field-scoped binary route below:
  POST /api/{type}/{bundle}/{uuid}/{field}
This creates the file AND links it to the entity's field in ONE call.

Photos go on the 'image' field. The 'file' field rejects jpg/png with 422.
See memory project_farmos_image_upload_needs_field_scoped_route.

Provides:
  _extract_file_id          -- extract file UUID from array or object body
  upload_field_attachment   -- skip-on-missing single-file upload via field-scoped route
  upload_field_attachments  -- batch wrapper; collects file_ids/skipped/failed

ASCII-only. No em-dashes. Never-throws. No new pip packages (stdlib pathlib only).
"""

from __future__ import annotations

import os
from pathlib import Path


def _extract_file_id(body: dict | None) -> str | None:
    """Extract the file UUID from a farmOS field-upload response body.

    Port of _extractFileId() from files.js lines 61-68.

    Multi-value field uploads echo the full file list; the just-added file is last.
    Single-resource uploads echo one object.

    Args:
        body: Parsed JSON:API response body dict (or None).

    Returns:
        File UUID string, or None if not extractable.
    """
    if not body:
        return None
    d = body.get("data")
    if not d:
        return None
    if isinstance(d, list):
        return d[-1]["id"] if d else None
    if isinstance(d, dict):
        return d.get("id")
    return None


async def upload_field_attachment(
    client: dict,
    collection_path: str,
    uuid: str,
    field: str,
    abs_path: str,
    filename: str | None = None,
    opts: dict | None = None,
) -> dict:
    """POST octet-stream bytes to the field-scoped farmOS binary route.

    Port of uploadFieldAttachment() from files.js lines 70-94.

    Builds url = f"{collection_path}/{uuid}/{field}" and posts via
    client["post_binary"]. Creates file AND links to field in ONE call.

    Skip-on-missing: if abs_path does not exist, returns attachment_missing
    without calling the client (commit continues).

    Args:
        client:          farmOS client dict from create_farmos_client.
        collection_path: Resource collection path, e.g. '/api/asset/fungi'.
        uuid:            Asset UUID string.
        field:           Field name -- always 'image' for fungi/group (never 'file').
        abs_path:        Absolute path to the local file.
        filename:        Override filename for Content-Disposition; defaults to basename.
        opts:            Optional dict (reserved for future opts, not currently used).

    Returns:
        {"ok": True,  "file_id": str}                                   -- success
        {"ok": False, "reason": "attachment_missing", "skipped": True,
         "path": abs_path}                                               -- file not found
        {"ok": False, "reason": "read_failed", "error": str,
         "path": abs_path}                                               -- read error
        {"ok": False, "reason": "http_<status|network>",
         "http_status": int|None}                                        -- upload error
    """
    p = Path(abs_path)
    if not p.exists():
        return {
            "ok": False,
            "reason": "attachment_missing",
            "skipped": True,
            "path": abs_path,
        }
    try:
        data = p.read_bytes()
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "reason": "read_failed",
            "error": str(e),
            "path": abs_path,
        }
    fn = filename or p.name
    url = f"{collection_path}/{uuid}/{field}"
    r = await client["post_binary"](url, data, filename=fn, opts={"timeout_ms": 30000})
    if r["ok"]:
        return {"ok": True, "file_id": _extract_file_id(r.get("body"))}
    return {
        "ok": False,
        "reason": "http_" + (str(r.get("status")) if r.get("status") else "network"),
        "http_status": r.get("status"),
    }


async def upload_field_attachments(
    client: dict,
    collection_path: str,
    uuid: str,
    field: str,
    paths: list[str] | None,
    opts: dict | None = None,
) -> dict:
    """Batch upload multiple files via upload_field_attachment.

    Port of uploadFieldAttachments() from files.js lines 96-107.

    Args:
        client:          farmOS client dict.
        collection_path: Resource collection path, e.g. '/api/asset/fungi'.
        uuid:            Asset UUID string.
        field:           Field name ('image' for fungi assets).
        paths:           List of absolute file paths (or None/empty for no-op).
        opts:            Optional dict (passed through to each upload call).

    Returns:
        {
          "file_ids": list[str],                   -- UUIDs of uploaded files
          "skipped":  list[str],                   -- paths skipped (missing)
          "failed":   list[{"path": str, "reason": str}]  -- upload failures
        }
    """
    file_ids: list[str] = []
    skipped: list[str] = []
    failed: list[dict] = []
    for path in (paths or []):
        r = await upload_field_attachment(client, collection_path, uuid, field, path, None, opts)
        if r["ok"]:
            file_ids.append(r["file_id"])
        elif r.get("skipped"):
            skipped.append(path)
        else:
            failed.append({"path": path, "reason": r.get("reason", "unknown")})
    return {"file_ids": file_ids, "skipped": skipped, "failed": failed}
