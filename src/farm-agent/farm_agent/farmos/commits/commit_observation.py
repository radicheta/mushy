"""farm_agent/farmos/commits/commit_observation.py -- Observation commit handler.

Faithful Python port of src/agents/alerter/src/farmos/commits/commit-observation.js
(Phase 40 B7.4 / Phase 62-08).

Resolves QR codes, uploads attachments (best-effort, field-scoped route only --
the legacy file route 415s on this farmOS), then POSTs an observation
log referencing assets and (best-effort) file_ids.

Photo attach path: upload_field_attachment() targeting the asset's 'image' field
via the field-scoped binary route /api/asset/fungi/{uuid}/image.

Returns the uniform commit envelope:
  {"ok": bool, "asset_ids": list, "log_ids": list, "file_ids": list,
   "attachments_failed": list, "attachments_skipped": list,
   "http_status": int|None, "reason": str|None}

Missing or failed attachments (D-05a) are best-effort: they do NOT flip ok to
False. The attachments_failed list is surfaced in the result and warned.

ASCII-only. No em-dashes. Never-throws at the handler level.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from farm_agent.farmos.files import upload_field_attachments
from farm_agent.farmos.logs import create_log
from farm_agent.farmos.qr import resolve_qr

log = logging.getLogger(__name__)


async def commit_observation(client: dict, draft: dict, ctx: dict | None = None) -> dict:
    """Create an observation log for the given draft.

    Signature: async commit_observation(client, draft, ctx=None) -> envelope dict.

    Port of commitObservation() from commit-observation.js lines 11-68.

    Attachment path: ctx.capturePathsFor(capture_ids) -> list of abs_paths ->
    uploaded to the first resolved asset's 'image' field via the field-scoped
    binary route. Failures are best-effort (never flip ok).
    """
    dj = draft.get("draft_json") or {}
    draft_id = draft.get("id", "")
    qr_codes = dj.get("qr_codes") if isinstance(dj.get("qr_codes"), list) else []
    timestamp = dj["timestamp"] if isinstance(dj.get("timestamp"), (int, float)) else time.time()

    asset_ids = []
    for qr in qr_codes:
        r = await resolve_qr(client, qr)
        if r.get("found") and r.get("asset_id"):
            asset_ids.append(r["asset_id"])

    if not asset_ids:
        return {"ok": False, "reason": "observation_requires_target"}

    # Gather attachment paths via ctx.capturePathsFor (best-effort).
    capture_ids = draft.get("source_capture_ids")
    capture_ids = capture_ids if isinstance(capture_ids, list) else []
    paths: list[str] = []
    if ctx and callable(ctx.get("capturePathsFor")) and capture_ids:
        try:
            paths = await ctx["capturePathsFor"](capture_ids)
        except Exception:  # noqa: BLE001
            paths = []

    # Upload attachments to the first asset's image field (field-scoped route).
    # The legacy file route is NOT used here (415 on this farmOS).
    if paths:
        # Use the first resolved asset as the attachment target.
        target_uuid = asset_ids[0]
        up_res = await upload_field_attachments(
            client, "/api/asset/fungi", target_uuid, "image", paths
        )
    else:
        up_res = {"file_ids": [], "skipped": [], "failed": []}

    attachments_failed = up_res.get("failed") or []
    attachments_skipped = up_res.get("skipped") or []
    file_ids = up_res.get("file_ids") or []

    if attachments_failed:
        logger_obj = (ctx.get("logger") if isinstance(ctx, dict) else None)
        warn_fn = None
        if isinstance(logger_obj, dict):
            warn_fn = logger_obj.get("warn")
        elif logger_obj is not None:
            warn_fn = getattr(logger_obj, "warn", None)
        msg = (
            f"[commit_observation] {len(attachments_failed)} attachment(s) failed "
            f"to upload draft={draft_id}: "
            + ", ".join(f.get("reason", "") for f in attachments_failed)
        )
        if callable(warn_fn):
            warn_fn(msg)
        else:
            log.warning(
                "[commit_observation] %d attachment(s) failed draft=%s",
                len(attachments_failed),
                draft_id,
            )

    name = "observation " + datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    r = await create_log(client, "observation", {
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
