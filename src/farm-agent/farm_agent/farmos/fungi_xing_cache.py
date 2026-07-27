"""
farm_agent/farmos/fungi_xing_cache.py -- Per-process LRU cache for fungi_xing taxonomy terms.

Port of src/agents/alerter/src/farmos/fungi-xing-cache.js (Phase 40).

fungi_xing carries the structural classifier (block | fruit) on asset--fungi.
Cap-4 LRU using OrderedDict (same pattern as fungi_type_cache, smaller cap).

Provides:
  get_fungi_xing_uuid  -- resolve term name to UUID, cache hit skips GET
  _clear               -- test isolation
  _cache_size          -- test inspection

Reason strings match Node verbatim:
  fungi_xing_taxonomy_missing  (404 -- taxonomy endpoint missing)
  fungi_xing_not_found         (empty data -- term not found)
  http_<status|network>        (other HTTP errors)

ASCII-only. No em-dashes. Never-throws contract.
"""

from __future__ import annotations

import urllib.parse
from collections import OrderedDict

_CACHE: OrderedDict[str, str] = OrderedDict()  # name -> uuid
_CACHE_MAX = 4


def _get(name: str) -> str | None:
    """LRU get: move-to-end on hit."""
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
        _CACHE.popitem(last=False)


def _clear() -> None:
    """Clear the cache (test isolation)."""
    _CACHE.clear()


def _cache_size() -> int:
    """Return current cache size (test inspection)."""
    return len(_CACHE)


async def get_fungi_xing_uuid(client: dict, xing_name: str) -> dict:
    """Resolve a fungi_xing term name to its UUID.

    Port of getFungiXingUuid() from fungi-xing-cache.js lines 34-50.

    Returns:
      {"ok": True,  "uuid": str, "cached"?: True}
      {"ok": False, "reason": "fungi_xing_taxonomy_missing"}
      {"ok": False, "reason": "fungi_xing_not_found", "xing_name": str}
      {"ok": False, "reason": "http_<status|network>"}
    """
    cached = _get(xing_name)
    if cached is not None:
        return {"ok": True, "uuid": cached, "cached": True}
    enc = urllib.parse.quote(xing_name, safe="")
    r = await client["get"](f"/api/taxonomy_term/fungi_xing?filter[name][value]={enc}")
    if not r["ok"]:
        if r.get("status") == 404:
            return {"ok": False, "reason": "fungi_xing_taxonomy_missing"}
        return {
            "ok": False,
            "reason": "http_" + (str(r.get("status")) if r.get("status") else "network"),
        }
    arr = (r.get("body") or {}).get("data")
    if not isinstance(arr, list) or not arr:
        return {"ok": False, "reason": "fungi_xing_not_found", "xing_name": xing_name}
    uuid = arr[0]["id"]
    _set(xing_name, uuid)
    return {"ok": True, "uuid": uuid}
