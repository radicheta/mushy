"""farm_agent/farmos/commits/commit_activity.py -- Activity commit handler.

Faithful Python port of src/agents/alerter/src/farmos/commits/commit-activity.js
(Phase 40 B7.2 / Phase 62-08).

Resolves QR codes to existing asset ids, mints a block for a ref farmOS
confirms is absent (MUSHY-126), then POSTs an activity log with
activity_subtype as the leading token in the name.

Returns the uniform commit envelope:
  {"ok": bool, "asset_ids": list, "log_ids": list, "file_ids": list,
   "http_status": int|None, "reason": str|None}

ASCII-only. No em-dashes. Never-throws at the handler level.
"""
from __future__ import annotations

import time
from farm_agent.farmos.farm_time import ymd

from farm_agent.farmos import assets
from farm_agent.farmos.logs import create_log
from farm_agent.farmos.qr import resolve_qr
from farm_agent.farmos.ref_check import strain_code_from_ref


def _ymd(unix_sec: float) -> str:
    """Format unix seconds as YYYY-MM-DD (UTC). Mirrors _ymd() from commit-activity.js."""
    return ymd(unix_sec)


def _status_from_lookup_error(error: str) -> int | None:
    """The HTTP status inside a qr.py error string ("http_404", "http_network").

    Carried through so _is_transient can tell a 500 from a 403 on the far side.
    A lookup that never got a status keeps http_status None and is recognised
    by its "network" reason instead.
    """
    digits = (error or "").rsplit("_", 1)[-1]
    return int(digits) if digits.isdigit() else None


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
    absent: list[str] = []
    for qr in qr_codes:
        r = await resolve_qr(client, qr)
        if r.get("found") and r.get("asset_id"):
            asset_ids.append(r["asset_id"])
        elif r.get("error"):
            # A lookup that could not reach farmOS is NOT a miss (qr.py D-06).
            # Minting on it would create a duplicate of a block that is already
            # there, so the whole commit stops and stays retryable instead.
            return {
                "ok": False,
                "reason": r["error"],
                "http_status": _status_from_lookup_error(r["error"]),
            }
        else:
            absent.append(qr)

    # MUSHY-126: farmOS confirmed these refs are absent, and the farmer already
    # approved a confirmation that said "New in farmOS, will be created". Before
    # this the handler resolved only, so an activity on a block that farmOS had
    # never heard of could never commit at all.
    #
    # Same gate as commit_seeding: the strain has to come from the ref itself,
    # and create_missing_fungi_type stays off unless ctx turns it on, so an
    # unrecognised strain code fails loudly rather than minting a junk taxonomy
    # term. A ref that is not a block name is left alone entirely.
    for ref in absent:
        strain = strain_code_from_ref(ref)
        if not strain:
            continue
        block_res = await assets.upsert_fungi_asset(client, {
            "name": ref,
            "fungi_type_name": strain,
            "fungi_xing_name": "block",
            "qr_codes": [ref],
            "draft_id": draft_id,
            "create_missing_fungi_type": bool(ctx and ctx.get("create_missing_fungi_type")),
        })
        if not block_res.get("ok"):
            return {
                "ok": False,
                "reason": block_res.get("reason") or "block_upsert_failed",
                "http_status": block_res.get("http_status"),
            }
        asset_ids.append(block_res["asset_id"])

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
