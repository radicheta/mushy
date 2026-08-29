"""farm_agent/farmos/commits/commit_activity.py -- Activity commit handler.

Faithful Python port of src/agents/alerter/src/farmos/commits/commit-activity.js
(Phase 40 B7.2 / Phase 62-08).

Resolves QR codes to existing asset ids, mints a block for a ref farmOS
confirms is absent (MUSHY-126), uploads any photos the farmer sent
(best-effort, MUSHY-131), then POSTs an activity log with activity_subtype as
the leading token in the name.

Returns the uniform commit envelope:
  {"ok": bool, "asset_ids": list, "log_ids": list, "file_ids": list,
   "http_status": int|None, "reason": str|None}

ASCII-only. No em-dashes. Never-throws at the handler level.
"""
from __future__ import annotations

import logging
import time

from farm_agent.farmos.farm_time import ymd

from farm_agent.farmos import assets
from farm_agent.farmos.commits.attachments import upload_draft_attachments
from farm_agent.farmos.commits.targets import resolve_asset_targets
from farm_agent.farmos.logs import create_log
from farm_agent.farmos.ref_check import strain_code_from_ref

log = logging.getLogger(__name__)


def _ymd(unix_sec: float) -> str:
    """Format unix seconds as YYYY-MM-DD (UTC). Mirrors _ymd() from commit-activity.js."""
    return ymd(unix_sec)


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

    # MUSHY-133: resolves across every asset bundle before considering a mint.
    # Without this an activity naming a non-fungi asset would be "absent" and,
    # if its name happened to look like a block name, minted as a DUPLICATE
    # fungi asset shadowing the real one.
    res = await resolve_asset_targets(client, qr_codes)
    if not res.get("ok"):
        return {
            "ok": False,
            "reason": res.get("reason"),
            "http_status": res.get("http_status"),
        }
    targets = res["targets"]
    asset_ids = [t[0] for t in targets]
    absent = res["absent"]

    # MUSHY-126: farmOS confirmed these refs are absent from every bundle, and
    # the farmer already approved a confirmation that said "New in farmOS, will
    # be created". Before this the handler resolved only, so an activity on a
    # block that farmOS had never heard of could never commit at all.
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
        targets.append((block_res["asset_id"], "fungi"))

    if not asset_ids:
        return {"ok": False, "reason": "no_target_asset_for_activity"}

    # MUSHY-131: a photo sent with an activity used to be captured, written to
    # disk, referenced by the draft, and then dropped here without a word. Kept
    # best-effort: a photo that will not upload must not unwind a correct log.
    up_res = await upload_draft_attachments(client, draft, ctx, asset_ids, targets[0][1] if targets else "fungi")
    attachments_failed = up_res.get("failed") or []
    attachments_skipped = up_res.get("skipped") or []
    file_ids = up_res.get("file_ids") or []

    if attachments_failed:
        log.warning(
            "[commit_activity] %d attachment(s) failed draft=%s: %s",
            len(attachments_failed), draft_id,
            ", ".join(f.get("reason", "") for f in attachments_failed),
        )

    name = subtype + " " + _ymd(timestamp)
    r = await create_log(client, "activity", {
        "name": name,
        "timestamp": timestamp,
        "asset_ids": asset_ids,
        "file_ids": file_ids,
        "notes": dj.get("notes") or "",
        "draft_id": draft_id,
    })
    if not r.get("ok"):
        return {
            "ok": False,
            "reason": r.get("reason"),
            "http_status": r.get("http_status"),
            "file_ids": file_ids,
            "attachments_failed": attachments_failed,
            "attachments_skipped": attachments_skipped,
        }
    return {
        "ok": True,
        "asset_ids": [],
        "log_ids": [r["log_id"]],
        "file_ids": file_ids,
        "attachments_failed": attachments_failed,
        "attachments_skipped": attachments_skipped,
        "http_status": r.get("http_status"),
    }
