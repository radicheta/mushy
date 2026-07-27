"""farm_agent/farmos/commits/commit_seeding_session.py -- Seeding session commit.

Faithful Python port of src/agents/alerter/src/farmos/commits/commit-seeding-session.js
(Phase 52 / Phase 62-09).

Shape (locked by 52-CONTEXT.md):
  1. PREFLIGHT: upsert_group_asset for 'inoc YYYY-MM-DD' (with '#N' collision
     suffix up to #9). Session entity is asset--group from the stock farm_group
     module (enabled farmos commit 1857037).
  2. OPTIONAL IMAGE ATTACH: page photos POST octet-stream to the group's
     'image' field via /api/asset/group/{uuid}/image (field-scoped route,
     creates + links in one call). Best-effort -- failure never flips ok.
  3. CHILDREN LOOP: source blocks + N child blocks each with
     parent=[sourceBlock] ONLY -- NO secondary edge to the session group
     (honors C4: lineage is an event, not a property).
  4. POST-LOOP MEMBERSHIP LOG: one log--activity with is_group_assignment=True
     binding all child UUIDs to the session group.

All-or-nothing rollback (reverse order):
  membership log (if created) -> children + source blocks (createdAssetIds
  in reverse) -> session group (if just-created this run).

ASCII-only. No em-dashes. Never-throws at the handler level.
"""
from __future__ import annotations

import logging

from farm_agent.farmos import assets, logs
from farm_agent.farmos import group_assets, activity_logs
from farm_agent.farmos.activity_logs import epoch_seconds_for_date
from farm_agent.farmos.files import upload_field_attachments

log = logging.getLogger(__name__)

_COLLISION_MAX = 9


async def _resolve_session_name(
    client: dict, event_date: str, draft_id: str
) -> dict | None:
    """Probe 'inoc <date>' then '#2'..'#9' for a free or own-draft slot.

    Port of _resolveSessionName() from commit-seeding-session.js.

    Returns {"name": str, "existing_id": str | None} on success, or None
    when all collision slots are taken by foreign-draft groups.
    """
    base_name = "inoc " + event_date
    for n in range(1, _COLLISION_MAX + 1):
        candidate = base_name if n == 1 else (base_name + " #" + str(n))
        lookup = await group_assets.find_group_asset_by_name(client, candidate)
        if not lookup["found"]:
            return {"name": candidate, "existing_id": None}
        # Hit -- check if it belongs to THIS draft via notes-trailer match.
        r = await client["get"]("/api/asset/group/" + lookup["asset_id"])
        if r.get("ok") and r.get("body"):
            note_value = (
                ((r["body"].get("data") or {}).get("attributes") or {})
                .get("notes") or {}
            ).get("value", "")
            if "mushy:draft:" + str(draft_id) in note_value:
                return {"name": candidate, "existing_id": lookup["asset_id"]}
        # Foreign draft -- advance to next #N.
    return None


async def _cleanup(
    client: dict,
    ctx: dict | None,
    draft: dict,
    created_asset_ids: list,
    original_reason: str,
    failed_at_child_index: int,
    opts: dict | None = None,
) -> dict:
    """Reverse-order rollback: membership log -> assets (reverse) -> session group.

    Port of _cleanup() from commit-seeding-session.js.
    Returns the partial_commit_failed envelope.
    """
    audit_logger = (ctx or {}).get("audit_logger") if ctx else None
    membership_log_id = (opts or {}).get("membership_log_id")
    session_group_id_just_created = (opts or {}).get("session_group_id_just_created")
    attempted = 0
    failed = 0
    failed_ids: list = []

    async def _emit_orphan(orphan_id: str, r: dict) -> None:
        if audit_logger and callable(audit_logger.get("log_commit")):
            try:
                await audit_logger["log_commit"]("orphan_cleanup_failed", draft, {
                    "asset_ids": [orphan_id],
                    "reason": "orphan_cleanup_failed",
                    "http_status": r.get("http_status"),
                })
            except Exception:  # noqa: BLE001
                pass

    if membership_log_id:
        attempted += 1
        r = await activity_logs.delete_activity_log(client, membership_log_id)
        if not r.get("ok"):
            failed += 1
            failed_ids.append(membership_log_id)
            await _emit_orphan(membership_log_id, r)

    for asset_id in reversed(created_asset_ids):
        attempted += 1
        r = await assets.delete_fungi_asset(client, asset_id)
        if not r.get("ok"):
            failed += 1
            failed_ids.append(asset_id)
            await _emit_orphan(asset_id, r)

    if session_group_id_just_created:
        attempted += 1
        r = await group_assets.delete_group_asset(client, session_group_id_just_created)
        if not r.get("ok"):
            failed += 1
            failed_ids.append(session_group_id_just_created)
            await _emit_orphan(session_group_id_just_created, r)

    return {
        "ok": False,
        "reason": "partial_commit_failed",
        "asset_ids": [],
        "log_ids": [],
        "file_ids": [],
        "farmos_response": {
            "original_reason": original_reason,
            "failed_at_child_index": failed_at_child_index,
            "orphan_attempted_count": attempted,
            "orphan_cleanup_failed_count": failed,
            "orphan_cleanup_failed_ids": failed_ids,
        },
    }


async def commit_seeding_session(
    client: dict, draft: dict, ctx: dict | None = None
) -> dict:
    """Commit a seeding session: group preflight + children loop + membership log.

    Port of commitSeedingSession() from commit-seeding-session.js.

    ctx keys consumed:
      session_page_paths  -- list of abs paths to attach to the group image field
      audit_logger        -- dict with "log_commit" async callable
      logger              -- dict or obj with "warn" callable (for attach warnings)
    """
    try:
        dj = (draft and draft.get("draft_json")) or {}
        event_date = dj.get("event_date")
        groups = dj.get("groups") if isinstance(dj.get("groups"), list) else []
        draft_id = draft.get("id") if draft else None

        if not event_date or not groups:
            return {
                "ok": False,
                "reason": "invalid_seeding_session",
                "asset_ids": [],
                "log_ids": [],
                "file_ids": [],
            }

        created_asset_ids: list = []
        child_block_ids: list = []
        child_log_ids: list = []
        timestamp = epoch_seconds_for_date(event_date)
        notes = dj.get("notes") if isinstance(dj.get("notes"), str) else ""

        # ---- PREFLIGHT: session group asset ----
        name_res = await _resolve_session_name(client, event_date, draft_id)
        if not name_res:
            return {
                "ok": False,
                "reason": "session_name_collision_exhausted",
                "asset_ids": [],
                "log_ids": [],
                "file_ids": [],
            }
        session_name = name_res["name"]
        group_res = await group_assets.upsert_group_asset(client, {
            "name": session_name,
            "draft_id": draft_id,
            "notes": notes,
        })
        if not group_res.get("ok"):
            return {
                "ok": False,
                "reason": "session_group_upsert_failed",
                "asset_ids": [],
                "log_ids": [],
                "file_ids": [],
                "farmos_response": {
                    "upsert_reason": group_res.get("reason"),
                    "http_status": group_res.get("http_status"),
                },
            }
        session_group_id = group_res["asset_id"]
        session_group_just_created = group_res.get("outcome") == "created"

        # ---- OPTIONAL: attach page images to session group (best-effort, D-03) ----
        # Photos POST octet-stream to /api/asset/group/{uuid}/image (field-scoped route).
        # Creates + links the file in ONE call. The 'file' field rejects jpg; the legacy
        # two-step (upload + relationships.file PATCH) never routed on this farmOS.
        attach_paths: list = (ctx or {}).get("session_page_paths") or [] if ctx else []
        uploaded_file_ids: list = []
        attachments_failed: list = []
        if attach_paths:
            up_res = await upload_field_attachments(
                client, "/api/asset/group", session_group_id, "image", attach_paths,
            )
            uploaded_file_ids = up_res.get("file_ids") or []
            attachments_failed = up_res.get("failed") or []
            if attachments_failed:
                log.warning(
                    "[commit_seeding_session] %d attachment(s) failed to upload draft=%s: %s",
                    len(attachments_failed),
                    draft_id,
                    ", ".join(f.get("reason", "") for f in attachments_failed),
                )

        child_index = 0
        audit_logger = (ctx or {}).get("audit_logger") if ctx else None

        for g in groups:
            species = ((g or {}).get("species") or {}).get("value")
            parent_name = ((g or {}).get("parent") or {}).get("value")
            qty = ((g or {}).get("qty") or {}).get("value")
            child_names = ((g or {}).get("child_block_names") or {}).get("value") or []

            if not species or not parent_name or not qty:
                return await _cleanup(
                    client, ctx, draft, created_asset_ids,
                    "invalid_group_shape", child_index,
                    {"session_group_id_just_created": session_group_id if session_group_just_created else None},
                )

            source_block_id = None
            if parent_name != "NO_PARENT":
                r = await assets.upsert_fungi_asset(client, {
                    "name": parent_name,
                    "fungi_type_name": species,
                    "fungi_xing_name": "block",
                    "draft_id": draft_id,
                })
                if not r.get("ok"):
                    return await _cleanup(
                        client, ctx, draft, created_asset_ids,
                        r.get("reason") or "source_block_upsert_failed", child_index,
                        {"session_group_id_just_created": session_group_id if session_group_just_created else None},
                    )
                source_block_id = r["asset_id"]
                if r.get("outcome") == "created":
                    created_asset_ids.append(source_block_id)
                if audit_logger and callable(audit_logger.get("log_commit")):
                    try:
                        await audit_logger["log_commit"]("upsert_outcome", draft, {
                            "asset_ids": [source_block_id],
                            "outcome": r.get("outcome"),
                            "conflicts": r.get("conflicts"),
                            "etag_source": r.get("etag_source"),
                        })
                    except Exception:  # noqa: BLE001
                        pass

            for i in range(int(qty)):
                child_name = child_names[i] if i < len(child_names) else None
                if not child_name:
                    return await _cleanup(
                        client, ctx, draft, created_asset_ids,
                        "missing_child_block_name", child_index,
                        {"session_group_id_just_created": session_group_id if session_group_just_created else None},
                    )
                # Children carry parent=[sourceBlock] ONLY -- NO session group edge.
                parent_ids = [source_block_id] if source_block_id else []
                child_res = await assets.upsert_fungi_asset(client, {
                    "name": child_name,
                    "fungi_type_name": species,
                    "fungi_xing_name": "block",
                    "parent_ids": parent_ids,
                    "draft_id": draft_id,
                })
                if not child_res.get("ok"):
                    return await _cleanup(
                        client, ctx, draft, created_asset_ids,
                        child_res.get("reason") or "child_block_upsert_failed", child_index,
                        {"session_group_id_just_created": session_group_id if session_group_just_created else None},
                    )
                child_block_id = child_res["asset_id"]
                if child_res.get("outcome") == "created":
                    created_asset_ids.append(child_block_id)
                child_block_ids.append(child_block_id)
                if audit_logger and callable(audit_logger.get("log_commit")):
                    try:
                        await audit_logger["log_commit"]("upsert_outcome", draft, {
                            "asset_ids": [child_block_id],
                            "outcome": child_res.get("outcome"),
                            "conflicts": child_res.get("conflicts"),
                            "etag_source": child_res.get("etag_source"),
                        })
                    except Exception:  # noqa: BLE001
                        pass

                log_res = await logs.upsert_log(client, "seeding", {
                    "name": "Inoc " + child_name,
                    "timestamp": timestamp,
                    "asset_ids": [child_block_id],
                    "notes": notes,
                    "draft_id": draft_id,
                })
                if not log_res.get("ok"):
                    return await _cleanup(
                        client, ctx, draft, created_asset_ids,
                        log_res.get("reason") or "seeding_log_upsert_failed", child_index,
                        {"session_group_id_just_created": session_group_id if session_group_just_created else None},
                    )
                child_log_ids.append(log_res["log_id"])
                if audit_logger and callable(audit_logger.get("log_commit")):
                    try:
                        await audit_logger["log_commit"]("upsert_outcome", draft, {
                            "log_ids": [log_res["log_id"]],
                            "outcome": log_res.get("outcome"),
                            "conflicts": log_res.get("conflicts") or [],
                            "etag_source": log_res.get("etag_source"),
                        })
                    except Exception:  # noqa: BLE001
                        pass
                child_index += 1

        # ---- POST-LOOP: membership log ----
        membership_name = f"inoc {event_date} ({len(child_block_ids)} bags)"
        membership_res = await activity_logs.create_group_assignment_log(client, {
            "child_ids": child_block_ids,
            "session_group_id": session_group_id,
            "event_date": event_date,
            "name": membership_name,
            "draft_id": draft_id,
            "notes": notes,
        })
        if not membership_res.get("ok"):
            return await _cleanup(
                client, ctx, draft, created_asset_ids,
                "membership_log_create_failed", child_index,
                {"session_group_id_just_created": session_group_id if session_group_just_created else None},
            )

        # Build success return shape.
        asset_ids_out = (
            [session_group_id, *created_asset_ids]
            if session_group_just_created
            else list(created_asset_ids)
        )
        log_ids_out = [membership_res["log_id"], *child_log_ids]

        return {
            "ok": True,
            "asset_ids": asset_ids_out,
            "log_ids": log_ids_out,
            "file_ids": uploaded_file_ids,
            "attachments_failed": attachments_failed,
            "http_status": 201,
        }

    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "reason": str(e) or "commit_seeding_session_error",
            "asset_ids": [],
            "log_ids": [],
            "file_ids": [],
        }
