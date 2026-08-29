"""farm_agent/farmos/commits/commit_seeding.py -- Seeding (inoc) commit handler.

Faithful Python port of src/agents/alerter/src/farmos/commits/commit-seeding.js
(Phase 40 B7.1 / Phase 62-09).

Option A hybrid shape (2026-05-14):
  * Block (B2) is the only fungi asset this module creates. fungi_type
    carries the strain code, fungi_xing='block'.
  * The pre-inoc sterilization batch (B1) is NOT a fungi asset under the
    new schema -- it lives as a pasteurization log on the farmOS side or as
    a material asset for euc logs. The alerter does not write it for now;
    batch_name is preserved in the seeding log notes so lineage is
    recoverable from the log when pasteurization-log wiring lands.
  * Path B (QR resolves to existing block): append-log-only.

Cross-ref: .planning/notes/2026-05-14-reply-from-farmos-fungi-schema.md

Returns the uniform commit envelope:
  {"ok": bool, "asset_ids": list, "log_ids": list, "file_ids": list,
   "http_status": int|None, "reason": str|None}

ASCII-only. No em-dashes. Never-throws at the handler level.
"""
from __future__ import annotations

import logging
import time

from farm_agent.farmos import assets, logs
from farm_agent.farmos.commits.attachments import upload_draft_attachments
from farm_agent.farmos import qr as qr_mod

log = logging.getLogger(__name__)


async def commit_seeding(client: dict, draft: dict, ctx: dict | None = None) -> dict:
    """Create a seeding (inoc) commit: optional block upsert + seeding log.

    Port of commitSeeding() from commit-seeding.js.

    Path A: QR unresolved -> upsert_fungi_asset for block, then upsert seeding log.
    Path B: QR resolves to existing block -> seeding log only.
    Ambiguous: >1 QR resolved -> {ok: False, reason: 'ambiguous_qr_seeding'}.
    Missing strain or block_name on path A -> early {ok: False, reason: ...}.
    """
    dj = draft.get("draft_json") or {}
    draft_id = draft.get("id")
    qr_codes = dj.get("qr_codes") if isinstance(dj.get("qr_codes"), list) else []
    timestamp = dj["timestamp"] if isinstance(dj.get("timestamp"), (int, float)) else time.time()

    # Path A vs Path B (QR resolution).
    path_b_ids: list = []
    path_a_qrs: list = []
    for qr_code in qr_codes:
        r = await qr_mod.resolve_qr(client, qr_code)
        if r.get("found") and r.get("asset_id"):
            path_b_ids.append(r["asset_id"])
        else:
            path_a_qrs.append(qr_code)

    if len(path_b_ids) > 1:
        return {"ok": False, "reason": "ambiguous_qr_seeding"}

    block_id = None
    created_assets: list = []

    if len(path_b_ids) == 1:
        block_id = path_b_ids[0]
    else:
        # Strain (= fungi_type) required when creating a new block.
        strain = (
            dj.get("species_code")
            or dj.get("species")
            or dj.get("strain")
            or dj.get("fungi_type")
        )
        if not strain:
            return {"ok": False, "reason": "missing_strain"}

        block_name = dj.get("block_name")
        if not block_name:
            return {"ok": False, "reason": "missing_block_name"}

        # Phase 51 UPSERT-01: route through upsert_fungi_asset so a re-run against a
        # populated farmOS is idempotent. Only track in created_assets when
        # outcome='created' (patched/noop assets must not be rolled back).
        block_res = await assets.upsert_fungi_asset(client, {
            "name": block_name,
            "fungi_type_name": strain,
            "fungi_xing_name": "block",
            "qr_codes": path_a_qrs,
            "draft_id": draft_id,
            "create_missing_fungi_type": bool(ctx and ctx.get("create_missing_fungi_type")),
        })
        if not block_res.get("ok"):
            return {
                "ok": False,
                "reason": block_res.get("reason") or "block_upsert_failed",
                "http_status": block_res.get("http_status"),
            }
        block_id = block_res["asset_id"]
        if block_res.get("outcome") == "created":
            created_assets.append(block_id)

    # Seeding log. batch_name preserved in notes (pasteurization log not
    # wired yet on farmOS side -- see header comment).
    batch_name = dj.get("batch_name")
    note_parts: list = []
    if dj.get("notes"):
        note_parts.append(str(dj["notes"]))
    if batch_name:
        note_parts.append("sterilization_batch: " + str(batch_name))
    notes = "\n".join(note_parts)

    # MUSHY-131: the photo of the bag being inoculated. This handler had no
    # attachment path at all, and seeding is the most common shape on the farm:
    # 13 of the 21 recoverable dropped photos are seeding. Best-effort, so a
    # photo that will not upload never unwinds a seeding that is otherwise
    # correct.
    up_res = await upload_draft_attachments(client, draft, ctx, [block_id], "fungi")
    file_ids = up_res.get("file_ids") or []
    attachments_failed = up_res.get("failed") or []
    if attachments_failed:
        log.warning(
            "[commit_seeding] %d attachment(s) failed draft=%s: %s",
            len(attachments_failed), draft_id,
            ", ".join(f.get("reason", "") for f in attachments_failed),
        )

    log_res = await logs.upsert_log(client, "seeding", {
        "name": "Inoc " + (dj.get("block_name") or str(block_id)),
        "timestamp": timestamp,
        "asset_ids": [block_id],
        "file_ids": file_ids,
        "notes": notes,
        "draft_id": draft_id,
    })
    if not log_res.get("ok"):
        return {
            "ok": False,
            "reason": log_res.get("reason") or "log_upsert_failed",
            "http_status": log_res.get("http_status"),
            "asset_ids": created_assets,
        }

    return {
        "ok": True,
        "asset_ids": created_assets,
        "log_ids": [log_res["log_id"]],
        "file_ids": file_ids,
        "attachments_failed": attachments_failed,
        "http_status": log_res.get("http_status"),
    }
