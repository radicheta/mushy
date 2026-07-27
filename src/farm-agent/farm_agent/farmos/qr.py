"""
farm_agent/farmos/qr.py -- QR tag lookup and binding for farmOS fungi assets.

Port of src/agents/alerter/src/farmos/qr.js (Phase 40 D-04 / D-06).

Provides:
  ID_TAG_TYPE        -- 'other' (prod farmOS allowed type)
  resolve_qr         -- id_tag-first lookup, name fallback on empty hit
  bind_qr_on_create  -- write id_tag list into a create-payload

D-06: id_tag-first, name-on-miss fallback.
  Transport failures on the id_tag call are NOT a miss -- return immediately
  without falling back to the name lookup.

ASCII-only. No em-dashes. Never-throws.
"""

from __future__ import annotations

import urllib.parse

# 'other' rather than 'qr': prod-farmOS farm_id_tag allows a restricted set of
# id_tag types and 'qr' is not in it. 'other' matches the type already in use
# on pre-existing prod assets. Flip this constant if farmOS adds 'qr' later.
ID_TAG_TYPE = "other"


async def resolve_qr(client: dict, qr_code: str) -> dict:
    """Resolve a QR code to a farmOS fungi asset id.

    Flow (D-06):
      1. GET /api/asset/fungi with id_tag.id filter on qr_code (URL-encoded)
         - ok + data[0] -> found:True, asset_id, path='id_tag'
         - ok + empty   -> name fallback (step 2)
         - not ok       -> found:False, error, path='id_tag' (NOT a miss, no fallback)
      2. GET /api/asset/fungi with name filter on qr_code (URL-encoded)
         - data[0] -> found:True, asset_id, path='name'
         - empty   -> found:False, path='name'

    Returns {"found": bool, "asset_id": str?, "path": str?, "error": str?}.
    Never raises.
    """
    try:
        enc = urllib.parse.quote(qr_code, safe="")
        r = await client["get"](f"/api/asset/fungi?filter[id_tag.id][value]={enc}")
        if not r["ok"]:
            return {
                "found": False,
                "error": "http_" + (str(r.get("status")) if r.get("status") else "network"),
                "path": "id_tag",
            }
        arr = (r.get("body") or {}).get("data")
        if isinstance(arr, list) and arr:
            return {"found": True, "asset_id": arr[0]["id"], "path": "id_tag"}
        # id_tag lookup returned empty -- fall back to name lookup (D-06)
        r2 = await client["get"](f"/api/asset/fungi?filter[name][value]={enc}")
        if not r2["ok"]:
            return {
                "found": False,
                "error": "http_" + (str(r2.get("status")) if r2.get("status") else "network"),
                "path": "name",
            }
        arr2 = (r2.get("body") or {}).get("data")
        if isinstance(arr2, list) and arr2:
            return {"found": True, "asset_id": arr2[0]["id"], "path": "name"}
        return {"found": False, "path": "name"}
    except Exception as e:  # noqa: BLE001
        return {"found": False, "error": str(e)}


def bind_qr_on_create(payload: dict, qr_codes: list[str] | None) -> dict:
    """Write id_tag entries into a farmOS create-payload's attributes.

    Port of bindQrOnCreate() from qr.js lines 57-62.
    Mutates payload.data.attributes.id_tag in place (mirrors JS behavior).
    No-op when qr_codes is empty or None.

    Args:
        payload:   farmOS JSON:API create payload dict.
        qr_codes:  List of QR code strings to bind.

    Returns the (mutated) payload for convenience.
    """
    if not qr_codes:
        return payload
    if not payload or not payload.get("data") or "attributes" not in payload["data"]:
        return payload
    payload["data"]["attributes"]["id_tag"] = [
        {"id": c, "type": ID_TAG_TYPE, "location": ""} for c in qr_codes
    ]
    return payload
