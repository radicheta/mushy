"""farm_agent/farmos/commits/commit_activity.py -- Activity commit handler.

Faithful Python port of src/agents/alerter/src/farmos/commits/commit-activity.js
(Phase 40 B7.2 / Phase 62-08).

Resolves QR codes to existing asset ids (no asset creation), then POSTs an
activity log with activity_subtype as the leading token in the name.

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


def _ymd(unix_sec: float) -> str:
    """Format unix seconds as YYYY-MM-DD (UTC). Mirrors _ymd() from commit-activity.js."""
    return datetime.fromtimestamp(unix_sec, tz=timezone.utc).strftime("%Y-%m-%d")


async def commit_activity(client: dict, draft: dict, ctx: dict | None = None) -> dict:
    """Create an activity log for the given draft.

    Signature: async commit_activity(client, draft, ctx=None) -> envelope dict.

    Port of commitActivity() from commit-activity.js lines 14-37.
    """
    dj = draft.get("draft_json") or {}
    draft_id = draft.get("id", "")
    qr_codes = dj.get("qr_codes") if isinstance(dj.get("qr_codes"), list) else []
    timestamp = dj["timestamp"] if isinstance(dj.get("timestamp"), (int, float)) else (time.time())
    subtype = dj.get("activity_subtype") or "activity"

    asset_ids = []
    for qr in qr_codes:
        r = await resolve_qr(client, qr)
        if r.get("found") and r.get("asset_id"):
            asset_ids.append(r["asset_id"])

    if not asset_ids:
        return {"ok": False, "reason": "no_target_asset_for_activity"}

    name = subtype + " " + _ymd(timestamp)
    r = await create_log(client, "activity", {
        "name": name,
        "timestamp": timestamp,
        "asset_ids": asset_ids,
        "notes": dj.get("notes") or "",
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
