"""farm_agent/farmos/commits/commit_harvest.py -- Harvest commit handler.

Faithful Python port of src/agents/alerter/src/farmos/commits/commit-harvest.js
(Phase 40 B7.5 D-03b / Phase 62-08).

Option A hybrid shape (2026-05-14):
  * Bag assets ARE fungi assets: fungi_type=<strain>, fungi_xing='fruit',
    parent=source blocks (C4 lineage).
  * NO harvest_batch fungi asset under the new schema -- 'batch' is not
    a valid fungi_xing value, and the harvest log itself bundles the
    bags + source blocks together. harvest_batch_name (if present) is
    preserved in the log notes for human-readable lineage.
  * Missing source block aborts BEFORE any farmOS write. Bag QR
    collision is terminal.

Strain resolution: extract from harvest_batch_name (HBATCH-...-{STRAIN}-...)
or fall back to draft.strain / draft.species_code. Missing strain = terminal.

Returns the uniform commit envelope:
  {"ok": bool, "asset_ids": list, "log_ids": list, "file_ids": list,
   "http_status": int|None, "reason": str|None}

ASCII-only. No em-dashes. Never-throws at the handler level.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from farm_agent.farmos.assets import upsert_fungi_asset
from farm_agent.farmos.logs import create_log
from farm_agent.farmos.qr import resolve_qr

# HBATCH-2026-05-13-DT-001 -> 'DT'. Matches B5 strain codes (2-4 uppercase chars).
_HBATCH_STRAIN_RE = re.compile(r"-([A-Z]{2,4})-[0-9]+$")


def _resolve_strain(dj: dict) -> str | None:
    """Extract strain code from draft_json fields. Mirrors resolveStrain() in JS."""
    if dj.get("strain"):
        return dj["strain"]
    if dj.get("fungi_type"):
        return dj["fungi_type"]
    if dj.get("species_code"):
        return dj["species_code"]
    if dj.get("species"):
        return dj["species"]
    if dj.get("harvest_batch_name"):
        m = _HBATCH_STRAIN_RE.search(dj["harvest_batch_name"])
        if m:
            return m.group(1)
    return None


async def commit_harvest(client: dict, draft: dict, ctx: dict | None = None) -> dict:
    """Create bag assets and a harvest log for the given draft.

    Signature: async commit_harvest(client, draft, ctx=None) -> envelope dict.

    Port of commitHarvest() from commit-harvest.js lines 39-117.
    """
    dj = draft.get("draft_json") or {}
    draft_id = draft.get("id", "")
    timestamp = dj["timestamp"] if isinstance(dj.get("timestamp"), (int, float)) else time.time()

    source_qrs = dj.get("source_qr_codes") if isinstance(dj.get("source_qr_codes"), list) else []
    bags = dj.get("bags") if isinstance(dj.get("bags"), list) else []

    # 1. Resolve source blocks. Pre-check ALL before any write.
    source_ids = []
    for qr in source_qrs:
        r = await resolve_qr(client, qr)
        if not r.get("found") or not r.get("asset_id"):
            return {"ok": False, "reason": "missing_source_block"}
        source_ids.append(r["asset_id"])

    if not source_ids:
        return {"ok": False, "reason": "missing_source_block"}

    # 1b. Pre-check bag QRs are unbound (no collision).
    for bag in bags:
        if not bag or not bag.get("qr_code"):
            continue
        r = await resolve_qr(client, bag["qr_code"])
        if r.get("found") and r.get("asset_id"):
            return {"ok": False, "reason": "qr_already_bound_for_bag"}

    # 2. Strain required for bag fungi_type.
    strain = _resolve_strain(dj)
    if not strain:
        return {"ok": False, "reason": "missing_strain"}

    # 3. Create bag assets (parents = source blocks).
    batch_name = dj.get("harvest_batch_name")  # labelling only; not an asset.
    bag_ids = []
    for bag in bags:
        bag_name = bag.get("name") or (
            (batch_name or "harvest") + "-bag-" + str(len(bag_ids) + 1)
        )
        bag_res = await upsert_fungi_asset(client, {
            "name": bag_name,
            "parent_ids": source_ids,
            "fungi_type_name": strain,
            "fungi_xing_name": "fruit",
            "qr_codes": [bag["qr_code"]] if bag.get("qr_code") else [],
            "draft_id": draft_id,
        })
        if not bag_res.get("ok"):
            return {
                "ok": False,
                "reason": bag_res.get("reason") or "bag_upsert_failed",
                "http_status": bag_res.get("http_status"),
                "asset_ids": list(bag_ids),
            }
        bag_ids.append(bag_res["asset_id"])

    # 4. Harvest log: order = source blocks, bags.
    all_asset_ids = [*source_ids, *bag_ids]
    weight_lines = "\n".join(
        "bag" + str(i + 1) + ": " + (str(b.get("weight_grams")) + "g" if b.get("weight_grams") is not None else "n/a")
        for i, b in enumerate(bags)
    )
    note_parts = []
    if dj.get("notes"):
        note_parts.append(dj["notes"])
    if batch_name:
        note_parts.append("harvest_batch: " + batch_name)
    if weight_lines:
        note_parts.append("Weights:\n" + weight_lines)
    notes = "\n".join(note_parts)

    name = "harvest " + datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    log_res = await create_log(client, "harvest", {
        "name": name,
        "timestamp": timestamp,
        "asset_ids": all_asset_ids,
        "notes": notes,
        "draft_id": draft_id,
    })
    if not log_res.get("ok"):
        return {
            "ok": False,
            "reason": log_res.get("reason"),
            "http_status": log_res.get("http_status"),
            "asset_ids": list(bag_ids),
        }
    return {
        "ok": True,
        "asset_ids": list(bag_ids),
        "log_ids": [log_res["log_id"]],
        "file_ids": [],
        "http_status": log_res.get("http_status"),
    }
