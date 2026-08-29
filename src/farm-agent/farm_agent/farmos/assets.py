"""
farm_agent/farmos/assets.py -- Fungi asset upsert primitive (Phase 62-07).

Faithful Python port of src/agents/alerter/src/farmos/assets.js (Phase 40/51).

JS camelCase -> Python snake_case mapping for opts parameters:
  name                   -> name
  parentIds              -> parent_ids
  fungiTypeName          -> fungi_type_name
  fungiXingName          -> fungi_xing_name
  draftId                -> draft_id
  qrCodes                -> qr_codes
  notes                  -> notes
  allowNoFungiType       -> allow_no_fungi_type
  createMissingFungiType -> create_missing_fungi_type

Return keys are snake_case throughout (asset_id, http_status, etag_source, etc.).

Phase 40 fungi asset creation primitive. Option A hybrid shape (2026-05-14):
asset--fungi requires fungi_type (strain code term, e.g. SHI/SH2/...) AND
fungi_xing (structural classifier: block | fruit). Pre-inoc substrates are NOT
fungi assets -- they live in the material bundle or as pasteurization logs.

Module-level LRU cache for asset name -> id resolution (cap-32 OrderedDict).
NAME_CACHE survives PATCH without invalidation because UPSERT-03's
IdentityMutationError on name change makes (name -> id) stable.

ASCII-only source. No em-dashes.
"""

from __future__ import annotations

import json
import urllib.parse
from collections import OrderedDict

from farm_agent.farmos import fungi_type_cache, fungi_xing_cache, qr
from farm_agent.farmos.merge import IdentityMutationError, merge_asset_fields

# Phase 51 UPSERT-05: marker string in notes.value identifies hand-stubbed
# ancestors awaiting 2025-paper-scan backfill.
# See .planning/notes/2026-05-24-prod-write-receipt.md (4 stubs in prod farmOS).
STUB_BACKFILL_MARKER = "STUB - awaits 2025-paper-scan backfill"

_NAME_CACHE: OrderedDict[str, str] = OrderedDict()  # name -> asset_id; capped at 32
_NAME_CACHE_MAX = 32


def _cache_get(name: str) -> str | None:
    """LRU get: move-to-end on hit (mirror JS Map delete+set pattern)."""
    if name not in _NAME_CACHE:
        return None
    _NAME_CACHE.move_to_end(name)
    return _NAME_CACHE[name]


def _cache_set(name: str, asset_id: str) -> None:
    """LRU set: move-to-end, evict-oldest on overflow."""
    if name in _NAME_CACHE:
        _NAME_CACHE.move_to_end(name)
    _NAME_CACHE[name] = asset_id
    while len(_NAME_CACHE) > _NAME_CACHE_MAX:
        _NAME_CACHE.popitem(last=False)  # evict oldest (FIFO)


def _clear_cache() -> None:
    """Clear the name cache (test isolation)."""
    _NAME_CACHE.clear()


def is_stub_asset(asset: dict | None) -> bool:
    """Pure predicate: True when asset notes.value contains the STUB backfill marker.

    Port of isStubAsset() from assets.js lines 143-148.
    """
    if not asset:
        return False
    attrs = asset.get("attributes") or {}
    notes = attrs.get("notes")
    if not notes:
        return False
    value = notes.get("value")
    return isinstance(value, str) and STUB_BACKFILL_MARKER in value


async def find_asset_by_name(client: dict, name: str) -> dict:
    """Resolve name -> asset_id via name-filter GET on /api/asset/fungi.

    Port of findAssetByName() from assets.js lines 48-61.
    Uses the name-value filter query parameter (D-05 name-based stable identity).
    LRU-cached (cap-32). Transport failure is NOT a miss.

    Returns:
      {"found": True,  "asset_id": str}                   -- resolved fresh
      {"found": True,  "asset_id": str, "cached": True}   -- LRU cache hit
      {"found": False}                                     -- not found (empty data)
      {"found": False, "error": "http_<status|network>"}  -- transport failure
    """
    cached = _cache_get(name)
    if cached:
        return {"found": True, "asset_id": cached, "cached": True}
    enc = urllib.parse.quote(name, safe="")
    r = await client["get"](f"/api/asset/fungi?filter[name][value]={enc}")
    if not r["ok"]:
        return {
            "found": False,
            "error": "http_" + (str(r.get("status")) if r.get("status") else "network"),
        }
    arr = (r.get("body") or {}).get("data")
    if isinstance(arr, list) and arr:
        asset_id = arr[0]["id"]
        _cache_set(name, asset_id)
        return {"found": True, "asset_id": asset_id}
    return {"found": False}


# MUSHY-133: every lookup in this module was hardcoded to the fungi bundle, so
# the agent could not see the other 34 assets on the farm. Kimba the farm dog is
# asset--animal id 1; an observation naming her failed as though she did not
# exist, and ref_check offered to "create" her.
#
# Fungi first so the common path costs one request and keeps the name cache.
# Creation stays fungi-only on purpose: this list is for RESOLUTION.
RESOLVABLE_BUNDLES = ("fungi", "animal", "plant", "structure", "group", "land", "equipment", "water")


async def find_asset_any_bundle(client: dict, name: str) -> dict:
    """Resolve name -> (asset_id, bundle) across every asset bundle.

    Deliberately NOT a widening of find_asset_by_name. That one feeds
    upsert_fungi_asset's create-or-patch decision, and if it started returning
    an animal that happens to share a block's name, the upsert would PATCH the
    animal as a fungi asset. Resolution and creation need different scopes.

    Only the fungi step touches the LRU name cache, for the same reason: a
    cached non-fungi id would leak into the upsert path through the cache.

    A transport failure on ANY bundle is returned as an error rather than a
    miss, matching find_asset_by_name. "I could not look" is not "not there".

    Returns:
      {"found": True, "asset_id": str, "bundle": str}
      {"found": False}
      {"found": False, "error": "http_<status|network>"}
    """
    fungi = await find_asset_by_name(client, name)
    if fungi.get("found"):
        return {"found": True, "asset_id": fungi["asset_id"], "bundle": "fungi"}
    if fungi.get("error"):
        return fungi

    enc = urllib.parse.quote(name, safe="")
    for bundle in RESOLVABLE_BUNDLES:
        if bundle == "fungi":
            continue
        r = await client["get"](f"/api/asset/{bundle}?filter[name][value]={enc}")
        if not r["ok"]:
            status = r.get("status")
            # A bundle this farmOS does not expose is a 404 on the collection,
            # which is a fact about the schema, not a failed lookup. Keep going.
            if status == 404:
                continue
            return {
                "found": False,
                "error": "http_" + (str(status) if status else "network"),
            }
        arr = (r.get("body") or {}).get("data")
        if isinstance(arr, list) and arr:
            return {"found": True, "asset_id": arr[0]["id"], "bundle": bundle}
    return {"found": False}


async def _build_asset_body(client: dict, opts: dict) -> dict:
    """Internal payload builder shared by create_fungi_asset and upsert_fungi_asset.

    Port of _buildAssetBody() from assets.js lines 67-120.

    Returns {"ok": True, "payload": dict, "attributes": dict, "relationships": dict}
    or {"ok": False, "reason": str, ...} on taxonomy resolution failure.
    """
    name = opts.get("name")
    parent_ids = opts.get("parent_ids") or []
    fungi_type_name = opts.get("fungi_type_name") or None
    fungi_xing_name = opts.get("fungi_xing_name") or None
    draft_id = opts.get("draft_id")
    qr_codes = opts.get("qr_codes") or []
    notes = opts.get("notes") or None
    allow_no_fungi_type = opts.get("allow_no_fungi_type", False)
    create_missing_fungi_type = opts.get("create_missing_fungi_type", False)

    if not allow_no_fungi_type and not fungi_type_name:
        return {"ok": False, "reason": "missing_fungi_type_name"}
    if not fungi_xing_name:
        return {"ok": False, "reason": "missing_fungi_xing_name"}

    ft = None
    if fungi_type_name:
        ft = await fungi_type_cache.ensure_fungi_type_uuid(
            client, fungi_type_name, create=create_missing_fungi_type
        )
        if not ft["ok"]:
            return {"ok": False, "reason": ft["reason"], "fungi_type_name": fungi_type_name}

    fx = await fungi_xing_cache.get_fungi_xing_uuid(client, fungi_xing_name)
    if not fx["ok"]:
        return {"ok": False, "reason": fx["reason"], "fungi_xing_name": fungi_xing_name}

    note_trailer = (notes + "\n" if notes else "") + "mushy:draft:" + str(draft_id)
    attributes: dict = {
        "name": name,
        "status": "active",
        "notes": {"value": note_trailer, "format": "plain_text"},
    }
    relationships: dict = {
        "fungi_xing": {"data": [{"type": "taxonomy_term--fungi_xing", "id": fx["uuid"]}]},
    }
    if ft and ft.get("uuid"):
        relationships["fungi_type"] = {
            "data": [{"type": "taxonomy_term--fungi_type", "id": ft["uuid"]}]
        }
    if parent_ids:
        relationships["parent"] = {
            "data": [{"type": "asset--fungi", "id": pid} for pid in parent_ids]
        }

    payload: dict = {
        "data": {
            "type": "asset--fungi",
            "attributes": attributes,
        },
    }
    payload["data"]["relationships"] = relationships
    if qr_codes:
        qr.bind_qr_on_create(payload, qr_codes)

    return {"ok": True, "payload": payload, "attributes": attributes, "relationships": relationships}


async def create_fungi_asset(client: dict, opts: dict) -> dict:
    """POST /api/asset/fungi to create a new fungi asset.

    Port of createFungiAsset() from assets.js lines 122-135.

    Returns {"ok": True, "asset_id": str, "qr_bindings": [], "http_status": int}
    or {"ok": False, "reason": str, "http_status": int?}.
    """
    built = await _build_asset_body(client, opts)
    if not built["ok"]:
        return built
    r = await client["post"]("/api/asset/fungi", built["payload"])
    if not r["ok"]:
        return {
            "ok": False,
            "reason": "http_" + (str(r.get("status")) if r.get("status") else "network"),
            "http_status": r.get("status"),
        }
    asset_id = ((r.get("body") or {}).get("data") or {}).get("id")
    if not asset_id:
        return {"ok": False, "reason": "no_asset_id_in_response"}
    _cache_set(opts["name"], asset_id)
    return {"ok": True, "asset_id": asset_id, "qr_bindings": [], "http_status": r.get("status")}


async def resolve_or_create_asset(client: dict, opts: dict) -> dict:
    """Find by name; if not found, create.

    Port of resolveOrCreateAsset() from assets.js lines 137-141.
    """
    lookup = await find_asset_by_name(client, opts["name"])
    if lookup["found"]:
        return {"ok": True, "asset_id": lookup["asset_id"], "reused": True}
    return await create_fungi_asset(client, opts)


def _is_merge_noop(existing: dict | None, merged: dict | None) -> bool:
    """Structural compare of merged vs existing on attributes + relationships.

    Port of _isMergeNoop() from assets.js lines 153-174.
    Normalizes notes to value-only projection and drops drupal_internal__revision_id
    before comparing (both are server-side metadata irrelevant to PATCH decisions).
    Uses sort_keys=True to normalize key insertion order.
    """
    def _norm_attrs(a: dict | None) -> dict:
        out = dict(a or {})
        if out.get("notes") and isinstance(out["notes"], dict):
            out["notes"] = {"value": out["notes"].get("value")}
        out.pop("drupal_internal__revision_id", None)
        return out

    ea = _norm_attrs((existing or {}).get("attributes"))
    er = (existing or {}).get("relationships") or {}
    ma = _norm_attrs((merged or {}).get("attributes"))
    mr = (merged or {}).get("relationships") or {}
    return (
        json.dumps(ea, sort_keys=True) == json.dumps(ma, sort_keys=True)
        and json.dumps(er, sort_keys=True) == json.dumps(mr, sort_keys=True)
    )


async def upsert_fungi_asset(client: dict, opts: dict) -> dict:
    """Lookup-merge-or-create primitive for asset--fungi.

    Port of upsertFungiAsset() from assets.js lines 189-312 (Phase 51 UPSERT-01/04/05).

    Outcomes:
      miss   -> POST via create_fungi_asset -> outcome='created'
      hit, no structural diff -> no PATCH -> outcome='noop'
      hit, diff               -> PATCH merged body -> outcome='patched'
      hit, scalar conflict    -> no PATCH -> outcome='noop', conflicts non-empty
      identity mutation       -> ok=False, reason='identity_mutation'
      concurrency race (soft revision moved) -> retry once; still racing ->
        outcome='noop', reason='concurrency_loss'

    Soft compare degrades to etag_source='absent' when the GET response has no
    drupal_internal__revision_id (no If-Match header sent in that case).
    """
    lookup = await find_asset_by_name(client, opts["name"])

    # Miss path -> POST via create_fungi_asset.
    if not lookup["found"]:
        r = await create_fungi_asset(client, opts)
        if not r["ok"]:
            return {
                "ok": False,
                "reason": r.get("reason"),
                "http_status": r.get("http_status"),
                "conflicts": [],
                "etag_source": None,
            }
        return {
            "ok": True,
            "asset_id": r["asset_id"],
            "outcome": "created",
            "conflicts": [],
            "etag_source": None,
            "http_status": r.get("http_status"),
        }

    # Hit path -> GET existing, build incoming, merge, decide PATCH-or-noop.
    built = await _build_asset_body(client, opts)
    if not built["ok"]:
        return {
            "ok": False,
            "reason": built.get("reason"),
            "http_status": None,
            "conflicts": [],
            "etag_source": None,
        }

    # Normalize incoming relationships to singleton-data shape that merge.py's
    # SCALAR_REL_FIELDS expects. create_fungi_asset POSTs fungi_type/fungi_xing as
    # `{data: [{...}]}` (array form accepted on create); existing assets on GET come
    # back as `{data: {...}}` (singleton). Collapse for like-with-like comparison.
    incoming_relationships = dict(built["relationships"])
    for field in ("fungi_type", "fungi_xing"):
        rel = incoming_relationships.get(field)
        if rel and isinstance(rel.get("data"), list):
            incoming_relationships[field] = {
                "data": rel["data"][0] if rel["data"] else None
            }

    incoming = {
        "type": "asset--fungi",
        "attributes": built["attributes"],
        "relationships": incoming_relationships,
    }

    async def _get_existing() -> dict | None:
        r = await client["get"]("/api/asset/fungi/" + lookup["asset_id"])
        if not r["ok"]:
            return None
        return (r.get("body") or {}).get("data")

    # One merge-cycle attempt: GET existing -> merge -> soft-revision re-GET -> PATCH or noop.
    # Returns {"kind": str, "result": dict?}. kind="race" means caller should retry.
    async def _attempt() -> dict:
        existing = await _get_existing()
        if not existing:
            return {
                "kind": "noop",
                "result": {
                    "ok": False,
                    "reason": "lookup_missing_after_find",
                    "http_status": None,
                    "conflicts": [],
                    "etag_source": None,
                },
            }

        attrs = existing.get("attributes") or {}
        pre_merge_rev = attrs.get("drupal_internal__revision_id")
        etag_source = "soft_compare" if pre_merge_rev is not None else "absent"

        try:
            out = merge_asset_fields(existing, incoming)
            merged = out["merged"]
            conflicts = out["conflicts"]
        except IdentityMutationError:
            return {
                "kind": "identity",
                "result": {
                    "ok": False,
                    "reason": "identity_mutation",
                    "http_status": None,
                    "conflicts": [],
                    "etag_source": None,
                },
            }

        if conflicts:
            return {
                "kind": "conflict",
                "result": {
                    "ok": True,
                    "asset_id": lookup["asset_id"],
                    "outcome": "noop",
                    "conflicts": conflicts,
                    "etag_source": etag_source,
                    "http_status": None,
                },
            }

        if _is_merge_noop(existing, merged):
            return {
                "kind": "noop",
                "result": {
                    "ok": True,
                    "asset_id": lookup["asset_id"],
                    "outcome": "noop",
                    "conflicts": [],
                    "etag_source": etag_source,
                    "http_status": None,
                },
            }

        # Soft-compare guard: re-GET to verify revision_id is still stable.
        if pre_merge_rev is not None:
            re_got = await _get_existing()
            current_rev = (re_got and (re_got.get("attributes") or {}).get("drupal_internal__revision_id"))
            if current_rev != pre_merge_rev:
                return {"kind": "race"}

        # PATCH path.
        headers = {"If-Match": str(pre_merge_rev)} if pre_merge_rev is not None else None
        patch_body = {
            "data": {
                "type": "asset--fungi",
                "id": lookup["asset_id"],
                "attributes": merged.get("attributes"),
                "relationships": merged.get("relationships"),
            },
        }
        pr = await client["patch"](
            "/api/asset/fungi/" + lookup["asset_id"],
            patch_body,
            {"headers": headers} if headers else None,
        )
        if not pr["ok"]:
            return {
                "kind": "patched",
                "result": {
                    "ok": False,
                    "reason": "http_" + (str(pr.get("status")) if pr.get("status") else "network"),
                    "http_status": pr.get("status"),
                    "conflicts": [],
                    "etag_source": etag_source,
                },
            }
        return {
            "kind": "patched",
            "result": {
                "ok": True,
                "asset_id": lookup["asset_id"],
                "outcome": "patched",
                "conflicts": [],
                "etag_source": etag_source,
                "http_status": pr.get("status"),
            },
        }

    first = await _attempt()
    if first["kind"] != "race":
        return first["result"]
    # Retry budget = 1.
    second = await _attempt()
    if second["kind"] != "race":
        return second["result"]
    # Still racing -> concurrency_loss.
    return {
        "ok": True,
        "asset_id": lookup["asset_id"],
        "outcome": "noop",
        "reason": "concurrency_loss",
        "conflicts": [],
        "etag_source": "soft_compare",
        "http_status": None,
    }


async def delete_fungi_asset(client: dict, asset_id: str) -> dict:
    """Best-effort DELETE /api/asset/fungi/<id> + name-cache invalidation.

    Port of deleteFungiAsset() from assets.js lines 317-331.
    Never raises; caller treats non-ok as audit-log-and-continue.
    Linear scan of the LRU cache (capped at 32) to invalidate stale name->id entries.
    """
    if not asset_id:
        return {"ok": False, "reason": "missing_asset_id"}
    if not callable(client.get("delete")):
        return {"ok": False, "reason": "client_delete_unavailable"}
    r = await client["delete"]("/api/asset/fungi/" + asset_id)
    if not r["ok"]:
        return {
            "ok": False,
            "reason": "http_" + (str(r.get("status")) if r.get("status") else "network"),
            "http_status": r.get("status"),
        }
    # Invalidate any cache entry pointing at this asset_id.
    to_remove = [name for name, aid in _NAME_CACHE.items() if aid == asset_id]
    for name in to_remove:
        del _NAME_CACHE[name]
    return {"ok": True, "http_status": r.get("status")}
