"""farm_agent/farmos/commits/commit_input.py -- Input commit handler.

Faithful Python port of src/agents/alerter/src/farmos/commits/commit-input.js
(Phase 40 B7.3 / Phase 62-08).

Serializes the ingredient list into notes (as-supplied order, deterministic).
Existing-asset-only path; QR codes must resolve.

Returns the uniform commit envelope:
  {"ok": bool, "asset_ids": list, "log_ids": list, "file_ids": list,
   "http_status": int|None, "reason": str|None}

ASCII-only. No em-dashes. Never-throws at the handler level.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from farm_agent.farmos.logs import create_log
from farm_agent.farmos.qr import resolve_qr


async def commit_input(client: dict, draft: dict, ctx: dict | None = None) -> dict:
    """Create an input log for the given draft.

    Signature: async commit_input(client, draft, ctx=None) -> envelope dict.

    Port of commitInput() from commit-input.js lines 9-34.
    """
    dj = draft.get("draft_json") or {}
    draft_id = draft.get("id", "")
    qr_codes = dj.get("qr_codes") if isinstance(dj.get("qr_codes"), list) else []
    timestamp = dj["timestamp"] if isinstance(dj.get("timestamp"), (int, float)) else time.time()
    ingredients = dj.get("input_ingredients") if isinstance(dj.get("input_ingredients"), list) else []

    asset_ids = []
    for qr in qr_codes:
        r = await resolve_qr(client, qr)
        if r.get("found") and r.get("asset_id"):
            asset_ids.append(r["asset_id"])

    if not asset_ids:
        return {"ok": False, "reason": "no_target_asset_for_activity"}

    lines = "\n".join("- " + str(s) for s in ingredients)
    existing_notes = dj.get("notes") or ""
    if lines:
        notes = (existing_notes + "\n" if existing_notes else "") + "Ingredients:\n" + lines
    else:
        notes = existing_notes

    name = "input " + datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    r = await create_log(client, "input", {
        "name": name,
        "timestamp": timestamp,
        "asset_ids": asset_ids,
        "notes": notes,
        "draft_id": draft_id,
    })
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason"), "http_status": r.get("http_status")}
    return {
        "ok": True,
        "asset_ids": [],
        "log_ids": [r["log_id"]],
        "file_ids": [],
        "http_status": r.get("http_status"),
    }
