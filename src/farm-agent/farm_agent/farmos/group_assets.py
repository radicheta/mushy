"""
farm_agent/farmos/group_assets.py -- asset--group primitives for session-entity preflight.

Port of src/agents/alerter/src/farmos/groupAssets.js (Phase 52 Plan 01 / Phase 62-09).

asset--group is the stock farmOS farm_group bundle enabled on dev + prod
(farmos commit 1857037). It carries name + status + notes; NO taxonomy
terms, NO parent edge, NO QR. Membership lives on log--activity with
is_group_assignment=True (see activity_logs.py), NOT on this asset.

upsert_group_asset is lookup-or-create only. NO merge layer in v1.10.1 --
same-name hit returns the existing UUID with outcome='reused'.

NOTE (Phase 55B, 2026-06-14): page photos use the field-scoped binary route
POST /api/asset/group/{uuid}/image via files.upload_field_attachments.
The 'file' field rejects jpg; the old /api/file/file route never routed on
this farmOS. See memory project_farmos_image_upload_needs_field_scoped_route.

Module-level LRU cache for group name -> id (cap-32 OrderedDict).

ASCII-only. No em-dashes. Never-throws.
"""

from __future__ import annotations

import urllib.parse
from collections import OrderedDict

_NAME_CACHE: OrderedDict[str, str] = OrderedDict()
_NAME_CACHE_MAX = 32


def _cache_get(name: str) -> str | None:
    """LRU get: move-to-end on hit."""
    if name not in _NAME_CACHE:
        return None
    _NAME_CACHE.move_to_end(name)
    return _NAME_CACHE[name]


def _cache_set(name: str, group_id: str) -> None:
    """LRU set: move-to-end, evict-oldest on overflow."""
    if name in _NAME_CACHE:
        _NAME_CACHE.move_to_end(name)
    _NAME_CACHE[name] = group_id
    while len(_NAME_CACHE) > _NAME_CACHE_MAX:
        _NAME_CACHE.popitem(last=False)


def _clear_cache() -> None:
    """Clear the name cache (test isolation)."""
    _NAME_CACHE.clear()


async def find_group_asset_by_name(client: dict, name: str) -> dict:
    """Resolve name -> group asset_id via name-filter GET on /api/asset/group.

    Port of findGroupAssetByName() from groupAssets.js.
    LRU-cached (cap-32). Transport failure is NOT a miss.

    Returns:
      {"found": True,  "asset_id": str}                   -- resolved fresh
      {"found": True,  "asset_id": str, "cached": True}   -- LRU cache hit
      {"found": False}                                     -- not found
      {"found": False, "error": "http_<status|network>"}  -- transport failure
    """
    cached = _cache_get(name)
    if cached:
        return {"found": True, "asset_id": cached, "cached": True}
    enc = urllib.parse.quote(name, safe="")
    r = await client["get"](f"/api/asset/group?filter[name][value]={enc}")
    if not r["ok"]:
        return {
            "found": False,
            "error": "http_" + (str(r.get("status")) if r.get("status") else "network"),
        }
    arr = (r.get("body") or {}).get("data")
    if isinstance(arr, list) and arr:
        group_id = arr[0]["id"]
        _cache_set(name, group_id)
        return {"found": True, "asset_id": group_id}
    return {"found": False}


async def upsert_group_asset(client: dict, opts: dict) -> dict:
    """Lookup-or-create for asset--group. No merge layer (v1.10.1).

    Port of upsertGroupAsset() from groupAssets.js.

    Returns {"ok": True, "asset_id": str, "outcome": "reused"|"created", "http_status": ...}
    or {"ok": False, "reason": str, "http_status": int?}.
    """
    name = opts.get("name")
    draft_id = opts.get("draft_id")
    notes = opts.get("notes") or None

    lookup = await find_group_asset_by_name(client, name)
    if lookup["found"]:
        return {
            "ok": True,
            "asset_id": lookup["asset_id"],
            "outcome": "reused",
            "http_status": None,
        }

    note_trailer = (notes + "\n" if notes else "") + "mushy:draft:" + str(draft_id)
    payload = {
        "data": {
            "type": "asset--group",
            "attributes": {
                "name": name,
                "status": "active",
                "notes": {"value": note_trailer, "format": "plain_text"},
            },
        },
    }
    r = await client["post"]("/api/asset/group", payload)
    if not r["ok"]:
        return {
            "ok": False,
            "reason": "http_" + (str(r.get("status")) if r.get("status") else "network"),
            "http_status": r.get("status"),
        }
    group_id = ((r.get("body") or {}).get("data") or {}).get("id")
    if not group_id:
        return {
            "ok": False,
            "reason": "no_asset_id_in_response",
            "http_status": r.get("status"),
        }
    _cache_set(name, group_id)
    return {
        "ok": True,
        "asset_id": group_id,
        "outcome": "created",
        "http_status": r.get("status"),
    }


async def delete_group_asset(client: dict, asset_id: str) -> dict:
    """DELETE /api/asset/group/<id> + name-cache invalidation.

    Port of deleteGroupAsset() from groupAssets.js.
    Never raises; caller treats non-ok as audit-log-and-continue.
    """
    if not asset_id:
        return {"ok": False, "reason": "missing_asset_id"}
    if not callable(client.get("delete")):
        return {"ok": False, "reason": "client_delete_unavailable"}
    r = await client["delete"]("/api/asset/group/" + asset_id)
    if not r["ok"]:
        return {
            "ok": False,
            "reason": "http_" + (str(r.get("status")) if r.get("status") else "network"),
            "http_status": r.get("status"),
        }
    # Invalidate cache entries pointing at this id.
    to_remove = [n for n, gid in _NAME_CACHE.items() if gid == asset_id]
    for n in to_remove:
        del _NAME_CACHE[n]
    return {"ok": True, "http_status": r.get("status")}
