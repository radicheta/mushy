"""
farm_agent/farmos/fungi_type_cache.py -- Per-process LRU cache for fungi_type taxonomy terms.

Port of src/agents/alerter/src/farmos/fungi-type-cache.js (Phase 40 / Phase 54 Cycle-1).

fungi_type carries the STRAIN CODE (SHI, KOY, ...) on asset--fungi.
Cap-16 LRU using OrderedDict (move-to-end on hit, evict-oldest on overflow).

Provides:
  get_fungi_type_uuid    -- resolve term name to UUID, cache hit skips GET
  ensure_fungi_type_uuid -- resolve or mint (create=True) on not_found
  _clear                 -- test isolation
  _cache_size            -- test inspection

Reason strings match Node verbatim:
  fungi_type_taxonomy_missing  (404 -- taxonomy endpoint missing)
  fungi_type_not_found         (empty data -- term not found)
  http_<status|network>        (other HTTP errors)

ASCII-only. No em-dashes. Never-throws contract (callers must not depend on exceptions).
"""

from __future__ import annotations

import urllib.parse
from collections import OrderedDict

_CACHE: OrderedDict[str, str] = OrderedDict()  # name -> uuid
_CACHE_MAX = 16


def _get(name: str) -> str | None:
    """LRU get: move-to-end on hit (mirror JS Map delete+set pattern)."""
    if name not in _CACHE:
        return None
    _CACHE.move_to_end(name)
    return _CACHE[name]


def _set(name: str, uuid: str) -> None:
    """LRU set: move-to-end, evict-oldest on overflow."""
    if name in _CACHE:
        _CACHE.move_to_end(name)
    _CACHE[name] = uuid
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)  # evict oldest


def _clear() -> None:
    """Clear the cache (test isolation)."""
    _CACHE.clear()


def _cache_size() -> int:
    """Return current cache size (test inspection)."""
    return len(_CACHE)


async def get_fungi_type_uuid(client: dict, type_name: str) -> dict:
    """Resolve a fungi_type term name to its UUID.

    Port of getFungiTypeUuid() from fungi-type-cache.js lines 35-51.

    Returns:
      {"ok": True,  "uuid": str, "cached"?: True}   -- resolved
      {"ok": False, "reason": "fungi_type_taxonomy_missing"}  -- 404
      {"ok": False, "reason": "fungi_type_not_found", "type_name": str}  -- empty
      {"ok": False, "reason": "http_<status|network>"}  -- other error
    """
    cached = _get(type_name)
    if cached is not None:
        return {"ok": True, "uuid": cached, "cached": True}
    enc = urllib.parse.quote(type_name, safe="")
    r = await client["get"](f"/api/taxonomy_term/fungi_type?filter[name][value]={enc}")
    if not r["ok"]:
        if r.get("status") == 404:
            return {"ok": False, "reason": "fungi_type_taxonomy_missing"}
        return {
            "ok": False,
            "reason": "http_" + (str(r.get("status")) if r.get("status") else "network"),
        }
    arr = (r.get("body") or {}).get("data")
    if not isinstance(arr, list) or not arr:
        return {"ok": False, "reason": "fungi_type_not_found", "type_name": type_name}
    uuid = arr[0]["id"]
    _set(type_name, uuid)
    return {"ok": True, "uuid": uuid}


async def ensure_fungi_type_uuid(
    client: dict,
    type_name: str,
    *,
    create: bool = False,
) -> dict:
    """Resolve or mint a fungi_type term.

    Port of ensureFungiTypeUuid() from fungi-type-cache.js lines 61-75.

    create=False (default): pass through not_found without POST.
    create=True: POST /api/taxonomy_term/fungi_type to mint the term if
      it is genuinely not_found. Does NOT create on taxonomy_missing or
      HTTP errors (infrastructure problems).

    Returns:
      {"ok": True,  "uuid": str, "created"?: True}
      {"ok": False, "reason": str, ...}
    """
    existing = await get_fungi_type_uuid(client, type_name)
    if existing["ok"]:
        return existing
    if not create or existing.get("reason") != "fungi_type_not_found":
        return existing
    # Mint the term
    r = await client["post"](
        "/api/taxonomy_term/fungi_type",
        {
            "data": {
                "type": "taxonomy_term--fungi_type",
                "attributes": {"name": type_name},
            }
        },
    )
    if not r["ok"]:
        return {
            "ok": False,
            "reason": "fungi_type_create_http_" + (str(r.get("status")) if r.get("status") else "network"),
            "type_name": type_name,
        }
    uuid = ((r.get("body") or {}).get("data") or {}).get("id")
    if not uuid:
        return {"ok": False, "reason": "fungi_type_create_no_id", "type_name": type_name}
    _set(type_name, uuid)
    return {"ok": True, "uuid": uuid, "created": True}
