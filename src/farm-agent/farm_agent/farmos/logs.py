"""farm_agent/farmos/logs.py -- Faithful Python port of the Node farmOS log layer.

Source-of-truth: src/agents/alerter/src/farmos/logs.js

Phase 40 D-03 / D-03c: B7 log creation. Native types only (C5):
seeding | activity | input | observation | harvest. Any other log_type
raises UnsupportedLogTypeError BEFORE any farmOS call.

Phase 48 Plan 01: 'seeding_session' is a COMPOSITE log_type recognized by the
commit-router (so the guard does not bounce it) but NOT a native farmOS log
type. create_log rejects it -- the seeding_session handler writes one asset +
N child seeding logs by calling create_log(client, 'seeding', ...).
NATIVE_LOG_TYPES is the create_log allow-list; LOG_TYPES is the router guard.

Phase 51 UPSERT-02: upsert_log(client, type, opts) -- lookup-by-stable-key
then PATCH-merge-or-POST-create. Only 'seeding' migrates this phase (B5
invariant: one seeding log per child asset makes (type='seeding',
asset.id == assetIds[0]) an unambiguous stable key). All other log types
map to None in LOG_STABLE_KEYS and fall through to create_log POST behavior.

No em-dashes in source artifacts.
"""
from __future__ import annotations

import math
from urllib.parse import quote as _url_quote

from farm_agent.farmos.merge import STABLE_NOTES_SEPARATOR

NATIVE_LOG_TYPES = ["seeding", "activity", "input", "observation", "harvest"]
LOG_TYPES = [*NATIVE_LOG_TYPES, "seeding_session"]


class UnsupportedLogTypeError(Exception):
    """Raised when a log_type is not in NATIVE_LOG_TYPES."""

    def __init__(self, log_type: str):
        super().__init__("unsupported_log_type:" + log_type)
        self.name = "UnsupportedLogTypeError"
        self.log_type = log_type


class LogIdentityCollision(Exception):
    """Raised (or surfaced as warning) when >1 log matches the stable key."""

    def __init__(self, log_type: str, asset_id: str, matched_ids: list):
        super().__init__("log_identity_collision:" + log_type + ":" + asset_id)
        self.name = "LogIdentityCollision"
        self.log_type = log_type
        self.asset_id = asset_id
        self.matched_ids = matched_ids


# Phase 51 UPSERT-02: per-type stable-key resolvers. Only 'seeding' migrates
# to upsert in this phase (B5 invariant: one seeding log per child asset).
# Other types map to None -> POST-only path preserved.
def _seeding_stable_key(opts):
    asset_ids = (opts or {}).get("asset_ids") or []
    if not asset_ids:
        return None
    return {"path": "/api/log/seeding?filter[asset.id][value]=" + _url_quote(str(asset_ids[0]))}


LOG_STABLE_KEYS = {
    "seeding": _seeding_stable_key,
    "activity": None,
    "input": None,
    "observation": None,
    "harvest": None,
}


def _build_note_value(notes: str, draft_id: str) -> str:
    """Append mushy:draft:<id> marker. Mirrors _buildNoteValue()."""
    return (notes + "\n" if notes else "") + "mushy:draft:" + draft_id


def _build_log_body(log_type: str, opts: dict) -> dict:
    """Build the JSON:API payload for a log. Mirrors _buildLogBody()."""
    name = opts.get("name")
    timestamp = opts.get("timestamp", 0)
    asset_ids = opts.get("asset_ids") or []
    file_ids = opts.get("file_ids") or []
    notes = opts.get("notes") or ""
    draft_id = opts.get("draft_id", "")

    payload: dict = {
        "data": {
            "type": "log--" + log_type,
            "attributes": {
                "name": name,
                "timestamp": math.floor(timestamp),
                "status": "done",
                "notes": {
                    "value": _build_note_value(notes, draft_id),
                    "format": "plain_text",
                },
            },
            "relationships": {
                "asset": {
                    "data": [{"type": "asset--fungi", "id": aid} for aid in asset_ids]
                },
            },
        }
    }
    if file_ids:
        # MUSHY-131: 'image', NOT 'file'. farmOS answers 422 to a jpg on the
        # file relationship, which would have failed the ENTIRE log creation,
        # not just the photo. This never fired in prod only because ctx was
        # None and file_ids was therefore always empty (commit_watchdog.py).
        # Settled on dev 2026-08-29: file rel -> 422, image rel -> 201.
        payload["data"]["relationships"]["image"] = {
            "data": [{"type": "file--file", "id": fid} for fid in file_ids]
        }
    return payload


async def create_log(client: dict, log_type: str, opts: dict) -> dict:
    """POST a new log to farmOS. Mirrors createLog().

    Returns {"ok", "log_id", "http_status"} on success, or
    {"ok": False, "reason": "http_<status|network>"} on failure.
    Raises UnsupportedLogTypeError for non-native types (before any call).
    """
    if log_type not in NATIVE_LOG_TYPES:
        raise UnsupportedLogTypeError(log_type)

    payload = _build_log_body(log_type, opts)
    r = await client["post"]("/api/log/" + log_type, payload)
    if not r.get("ok"):
        status = r.get("status")
        return {
            "ok": False,
            "reason": "http_" + (str(status) if status is not None else "network"),
            "http_status": status,
        }
    log_id = None
    body = r.get("body")
    if body and body.get("data"):
        log_id = body["data"].get("id")
    return {"ok": True, "log_id": log_id, "http_status": r.get("status")}


# ---- Phase 51 UPSERT-02 helpers ----


def _set_union_refs(existing_arr, incoming_arr):
    """Set-union of JSON:API ref objects by id. Mirrors _setUnionRefs()."""
    existing = existing_arr if isinstance(existing_arr, list) else []
    incoming = incoming_arr if isinstance(incoming_arr, list) else []
    by_id = {}
    for ref in existing:
        if ref and ref.get("id") is not None and ref["id"] not in by_id:
            by_id[ref["id"]] = ref
    for ref in incoming:
        if ref and ref.get("id") is not None and ref["id"] not in by_id:
            by_id[ref["id"]] = ref
    return list(by_id.values())


def _merge_notes(existing_notes, incoming_notes):
    """Split-dedup-join on STABLE_NOTES_SEPARATOR. Mirrors _mergeNotes()."""
    ev = (existing_notes or {}).get("value") or ""
    iv = (incoming_notes or {}).get("value") or ""
    sep = STABLE_NOTES_SEPARATOR
    entries = [s.strip() for s in ev.split(sep) if s.strip()]
    for e in (s.strip() for s in iv.split(sep) if s.strip()):
        if e not in entries:
            entries.append(e)
    return {"value": sep.join(entries), "format": "plain_text"}


def _arrays_equal_by_id(a, b):
    """True iff both arrays contain the same set of ids. Mirrors _arraysEqualById()."""
    aa = a if isinstance(a, list) else []
    bb = b if isinstance(b, list) else []
    if len(aa) != len(bb):
        return False
    a_ids = sorted(r.get("id") for r in aa if r)
    b_ids = sorted(r.get("id") for r in bb if r)
    return a_ids == b_ids


def _sort_matches(matches):
    """Sort log stubs oldest-first by attributes.created, then id. Mirrors _sortMatches()."""
    def _key(m):
        created = (m.get("attributes") or {}).get("created") or ""
        return (created, m.get("id") or "")
    return sorted(matches, key=_key)


async def _emit_audit(audit_logger, event, payload):
    """Non-fatal audit call. Mirrors _emitAudit()."""
    if audit_logger and callable(audit_logger.get("log_commit")):
        try:
            await audit_logger["log_commit"](event, payload)
        except Exception:
            pass


async def upsert_log(client: dict, log_type: str, opts: dict) -> dict:
    """Lookup-by-stable-key then PATCH-merge-or-POST-create. Mirrors upsertLog().

    Returns a result dict with keys:
      ok, log_id, outcome, conflicts, etag_source, http_status, warnings, reason

    Raises UnsupportedLogTypeError for non-native types (before any call).
    """
    if log_type not in NATIVE_LOG_TYPES:
        raise UnsupportedLogTypeError(log_type)

    key_fn = LOG_STABLE_KEYS[log_type]

    # Pass-through: types with None stable key go straight to POST.
    if key_fn is None:
        r = await create_log(client, log_type, opts)
        if r.get("ok"):
            return {**r, "outcome": "created", "conflicts": [], "etag_source": None}
        return r

    key = key_fn(opts)
    if key is None:
        return {"ok": False, "reason": "missing_stable_key", "http_status": None}

    # Lookup by stable key.
    lookup = await client["get"](key["path"])
    if not lookup.get("ok"):
        status = lookup.get("status")
        return {
            "ok": False,
            "reason": "http_" + (str(status) if status is not None else "network"),
            "http_status": status,
        }
    raw_matches = (lookup.get("body") or {}).get("data") or []

    # Miss: POST via create_log.
    if not raw_matches:
        r = await create_log(client, log_type, opts)
        if r.get("ok"):
            return {**r, "outcome": "created", "conflicts": [], "etag_source": None}
        return r

    # Hit (>=1 match): sort, pick oldest, surface collision warning if >1.
    sorted_matches = _sort_matches(raw_matches)
    canonical = sorted_matches[0]
    warnings = []
    if len(sorted_matches) > 1:
        matched_ids = [m.get("id") for m in sorted_matches]
        warnings.append("LogIdentityCollision:" + str(len(sorted_matches)))
        await _emit_audit(
            opts.get("audit_logger"),
            "log_identity_collision",
            {
                "log_type": log_type,
                "asset_id": (opts.get("asset_ids") or [None])[0],
                "matched_ids": matched_ids,
            },
        )

    # GET full body for merge.
    full_resp = await client["get"]("/api/log/" + log_type + "/" + canonical["id"])
    if not full_resp.get("ok"):
        status = full_resp.get("status")
        return {
            "ok": False,
            "reason": "http_" + (str(status) if status is not None else "network"),
            "http_status": status,
            "warnings": warnings,
        }
    existing = (full_resp.get("body") or {}).get("data")
    pre_merge_revision_id = (
        (existing or {}).get("attributes", {}).get("drupal_internal__revision_id")
    )

    # Build incoming and merge.
    incoming_payload = _build_log_body(log_type, opts)
    incoming = incoming_payload["data"]

    # Identity check: asset.data must match (the stable key).
    existing_asset_data = (
        ((existing or {}).get("relationships") or {}).get("asset", {}).get("data") or []
    )
    incoming_asset_data = incoming["relationships"]["asset"]["data"] or []
    if not _arrays_equal_by_id(existing_asset_data, incoming_asset_data):
        return {
            "ok": False,
            "reason": "log_identity_mismatch",
            "http_status": None,
            "log_id": canonical["id"],
            "warnings": warnings,
        }

    # Merge the photo relationship: set-union by id.
    # MUSHY-131: 'image', matching the create path. farmOS 422s a jpg on 'file'.
    existing_file_data = (
        ((existing or {}).get("relationships") or {}).get("image", {}).get("data") or []
    )
    incoming_file_data = (
        (incoming.get("relationships") or {}).get("image", {}).get("data") or []
    )
    merged_files = _set_union_refs(existing_file_data, incoming_file_data)
    files_changed = len(merged_files) != len(existing_file_data)

    # Merge notes (split-dedup-join).
    merged_notes = _merge_notes(
        (existing or {}).get("attributes", {}).get("notes"),
        incoming["attributes"]["notes"],
    )
    existing_notes_value = (
        ((existing or {}).get("attributes") or {}).get("notes", {}) or {}
    ).get("value")
    notes_changed = existing_notes_value != merged_notes["value"]

    # Scalar conflicts: timestamp / status / name -- equal=noop, differ=conflict.
    conflicts = []
    for field in ("timestamp", "status", "name"):
        ev = ((existing or {}).get("attributes") or {}).get(field)
        iv = incoming["attributes"].get(field)
        if iv is None:
            continue
        if ev is not None and ev != iv:
            conflicts.append({"field": field, "existing": ev, "incoming": iv, "kind": "scalar_conflict"})

    if not files_changed and not notes_changed:
        return {
            "ok": True,
            "log_id": canonical["id"],
            "outcome": "noop",
            "conflicts": conflicts,
            "etag_source": "soft_compare",
            "http_status": None,
            "warnings": warnings,
        }

    # Build PATCH body with merged file + notes (preserve asset identity).
    patch_body = {
        "data": {
            "type": "log--" + log_type,
            "id": canonical["id"],
            "attributes": {
                "notes": merged_notes,
            },
            "relationships": {
                "asset": {"data": existing_asset_data},
                "image": {"data": merged_files},
            },
        }
    }

    # PATCH with If-Match; soft-compare retry once on 412.
    if_match = str(pre_merge_revision_id) if pre_merge_revision_id is not None else None
    patch_opts = {"headers": {"If-Match": if_match}} if if_match else None

    patch_resp = await client["patch"](
        "/api/log/" + log_type + "/" + canonical["id"], patch_body, patch_opts
    )

    if not patch_resp.get("ok") and patch_resp.get("status") == 412:
        # Soft-compare retry: re-GET, rebuild merge, PATCH once more.
        re_get = await client["get"]("/api/log/" + log_type + "/" + canonical["id"])
        if not re_get.get("ok"):
            status = re_get.get("status")
            return {
                "ok": False,
                "reason": "http_" + (str(status) if status is not None else "network"),
                "http_status": status,
                "warnings": warnings,
            }
        refreshed = (re_get.get("body") or {}).get("data")
        refreshed_rev = ((refreshed or {}).get("attributes") or {}).get("drupal_internal__revision_id")
        refreshed_files = (
            ((refreshed or {}).get("relationships") or {}).get("image", {}).get("data") or []
        )
        refreshed_notes = ((refreshed or {}).get("attributes") or {}).get("notes")
        remerge_files = _set_union_refs(refreshed_files, incoming_file_data)
        remerge_notes = _merge_notes(refreshed_notes, incoming["attributes"]["notes"])
        retry_body = {
            "data": {
                "type": "log--" + log_type,
                "id": canonical["id"],
                "attributes": {"notes": remerge_notes},
                "relationships": {
                    "asset": {"data": existing_asset_data},
                    "image": {"data": remerge_files},
                },
            }
        }
        retry_headers = (
            {"headers": {"If-Match": str(refreshed_rev)}} if refreshed_rev is not None else None
        )
        patch_resp = await client["patch"](
            "/api/log/" + log_type + "/" + canonical["id"], retry_body, retry_headers
        )

    if not patch_resp.get("ok"):
        status = patch_resp.get("status")
        return {
            "ok": False,
            "reason": "http_" + (str(status) if status is not None else "network"),
            "http_status": status,
            "warnings": warnings,
        }

    return {
        "ok": True,
        "log_id": canonical["id"],
        "outcome": "patched",
        "conflicts": conflicts,
        "etag_source": "soft_compare",
        "http_status": patch_resp.get("status"),
        "warnings": warnings,
    }
