"""
confirm/edit_handler.py -- EDIT re-extraction orchestrator.

Port of src/agents/alerter/src/confirm/edit-handler.js.

Bumps edit_turn_count, re-extracts via the extractor with the farmer's
correction as additional context, updates the draft in place (same id, same
source_capture_ids), re-renders the preview, and returns a side-effect tag
for dispatch.py to act on.

Never raises: every failure path returns {"ok": False, "reason": ...}.

Replaces the Phase 61 stub (farm_agent/confirm/dispatch.py
_run_edit_reextraction_stub), which logged a line and silently dropped the
farmer's correction.
"""

from __future__ import annotations

import logging

from farm_agent.confirm.preview import build_preview_with_suffix
from farm_agent.extraction.state_machine import REQUIRED_FIELDS
from farm_agent.tenancy.tenant import mask_number

_ACTIVE_STATUSES = ("awaiting_farmer", "commit_failed")

_REACTIVATE_SQL = (
    "UPDATE signal_draft SET status='awaiting_farmer', updated_at=NOW() "
    "WHERE id=%s AND status='commit_failed' RETURNING id"
)


def create_edit_handler(*, pool, extractor, confirm_repo, extraction_db, config, log=None) -> dict:
    """Build the {"handle_edit": ...} dict consumed by dispatch.py."""
    logger = log or logging.getLogger(__name__)

    async def handle_edit(draft_row: dict | None, edit_text: str) -> dict:
        try:
            if not draft_row or not draft_row.get("id"):
                return {"ok": False, "reason": "no_draft_row"}

            draft_id = draft_row["id"]
            edit_str = edit_text if isinstance(edit_text, str) else ""
            max_turns = getattr(config, "max_edit_turns", 3)

            # Plan 45-03 Option X: EDIT is permitted from awaiting_farmer (the
            # original path) and from commit_failed (the "Send EDIT to fix"
            # affordance in the failure ack must be truthful). Any other state
            # rejects.
            start_status = draft_row.get("status")
            if start_status not in _ACTIVE_STATUSES:
                return {"ok": False, "reason": "wrong_state"}

            if start_status == "commit_failed":
                # commit_failed -> awaiting_farmer must land before the
                # subsequent update (which targets an awaiting_farmer draft).
                try:
                    async with pool.connection() as conn:
                        cur = await conn.execute(_REACTIVATE_SQL, (draft_id,))
                        reactivated = await cur.fetchone()
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "[edit_handler] commit_failed->awaiting_farmer transition "
                        "threw draft_id=%s: %s", draft_id, e,
                    )
                    return {"ok": False, "reason": str(e)}
                if not reactivated:
                    # Race: another tick already moved the draft out of commit_failed.
                    logger.info(
                        "[edit_handler] commit_failed transition lost the race draft_id=%s",
                        draft_id,
                    )
                    return {"ok": False, "reason": "state_changed"}
                draft_row = dict(draft_row)
                draft_row["status"] = "awaiting_farmer"

            # Pre-cap short-circuit (avoids burning an LLM call when we know
            # the cap is hit).
            if (draft_row.get("edit_turn_count") or 0) >= max_turns:
                return {"ok": True, "side_effect": "send_edit_cap_msg", "reason": "edit_cap_exceeded"}

            bump = await confirm_repo.bump_edit_turn(pool, draft_id)
            if not bump.get("ok"):
                logger.warning(
                    "[edit_handler] bump failed draft_id=%s reason=%s", draft_id, bump.get("reason"),
                )
                return {"ok": False, "reason": bump.get("reason")}

            captures = [
                {
                    "capture_id": f"edit-{draft_id}",
                    "text": None,
                    "transcript": None,
                    "images": [],
                    "farmer_correction": edit_str,
                }
            ]

            try:
                result = await extractor["extract"](
                    captures,
                    in_flight_draft=draft_row.get("draft_json"),
                    farmer_correction=edit_str,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "[edit_handler] extractor threw sender=%s: %s",
                    mask_number(draft_row.get("sender_e164", "")), e,
                )
                # Audit-trail row (edit-handler.js:100-104): a database record
                # of the edit attempt, distinct from log output -- same
                # category as signal_capture.raw_text, kept deliberately.
                await confirm_repo.append_event_via_pool(
                    pool, draft_id, "edit",
                    {"ok": False, "reason": str(e), "edit_text": edit_str[:200]},
                )
                return {"ok": False, "reason": str(e)}

            if not result or not result.get("ok"):
                reason = (result or {}).get("reason") or "extractor_failed"
                logger.warning("[edit_handler] re-extract failed draft_id=%s reason=%s", draft_id, reason)
                # Audit-trail row (edit-handler.js:112-116).
                await confirm_repo.append_event_via_pool(
                    pool, draft_id, "edit",
                    {"ok": False, "reason": reason, "edit_text": edit_str[:200]},
                )
                return {"ok": False, "reason": reason}

            draft = result.get("draft")
            required = REQUIRED_FIELDS.get((draft or {}).get("type")) or []
            per_field_confidence = result.get("per_field_confidence") or {}
            new_preview = build_preview_with_suffix(
                draft=draft,
                per_field_confidence=per_field_confidence,
                required_fields=required,
                threshold=getattr(config, "extraction_confidence_threshold", 0.7),
            )

            upd = await extraction_db.update_draft_status(
                pool,
                draft_id,
                "awaiting_farmer",
                extras={
                    "draft_json": draft,
                    "per_field_confidence": per_field_confidence or None,
                    "farmer_facing_preview": new_preview,
                },
            )
            if not upd.get("ok"):
                logger.warning(
                    "[edit_handler] update_draft_status failed draft_id=%s reason=%s",
                    draft_id, upd.get("reason"),
                )
                return {"ok": False, "reason": upd.get("reason")}
            if upd.get("rowcount") == 0:
                logger.info(
                    "[edit_handler] draft no longer active when update landed draft_id=%s", draft_id,
                )
                return {"ok": True, "side_effect": "noop", "reason": "draft_no_longer_active"}

            # Audit-trail row (edit-handler.js:141-145).
            await confirm_repo.append_event_via_pool(
                pool, draft_id, "edit",
                {"ok": True, "edit_turn": bump.get("edit_turn_count"), "edit_text": edit_str[:200]},
            )

            return {
                "ok": True,
                "side_effect": "send_preview_resend",
                "new_preview": new_preview,
                "next_edit_turn_count": bump.get("edit_turn_count"),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[edit_handler] error: %s", e)
            return {"ok": False, "reason": str(e)}

    return {"handle_edit": handle_edit}
