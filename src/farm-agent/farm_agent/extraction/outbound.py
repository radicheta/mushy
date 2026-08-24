"""
extraction/outbound.py -- side-effect dispatcher.

Port of src/agents/alerter/src/extraction/outbound.js (189 lines). Two outbound
paths in Node:
  1. send_ask_back -- farmer_facing_preview reply to the originating capture,
     routed by reply_target_kind (DM vs group). Group sends use the bare
     internal_id; SignalClient.send translates to the wire id.
  2. send_needs_review_ping -- DM to operator_recipient (Don Santiago) when an
     ask-back loop terminates at the 3-turn cap. Addresses him by name, never
     as "operator" (project memory: farmer-facing artifact rules).

MUSHY-76 D-1 divergence: send_confirm_prompt is a new case with no Node
counterpart. In Node, a draft that extracts perfectly emits handoff_to_phase_39,
which the dispatcher no-sends -- so the farmer is never told a confirm prompt is
waiting. send_confirm_prompt routes exactly like send_ask_back (same target
resolution, same related_draft_id / related_capture_id threading) and sends
draft_row["farmer_facing_preview"], which build_confirm_prompt populates
upstream. handoff_to_phase_39 no longer exists; it falls through to the
unknown-tag branch.

Task 7 (MUSHY-76) adds two more tags for the seeding_session starting_seq
ask-back flow (farm_agent.extraction.starting_seq): send_starting_seq_askback
and send_seeding_session_filled_preview. Both route exactly like
send_ask_back / send_confirm_prompt -- same target resolution, same
draft_row["farmer_facing_preview"] payload.

All farmer/operator-facing text passes through sanitize_farmer_text (defense in
depth -- preview_builder already sanitizes its output). dispatch() never
raises: signal-cli outages return {"ok": False, "reason": ...} so the pipeline
keeps the draft row in its persisted state for retry on the next farmer
message.
"""

from __future__ import annotations

import logging


def _trunc_id(id_) -> str:
    if not isinstance(id_, str):
        return ""
    return id_[:10]


def create_outbound_dispatcher(
    signal_client,
    config,
    preview_builder,
    operator_recipient: str | None,
    log: logging.Logger | None = None,
    get_last_sent_body=None,
) -> dict:
    logger = log or logging.getLogger(__name__)
    sanitize = preview_builder.sanitize_farmer_text

    # MUSHY-91: draft ids already reported to the operator as flooding. In-memory
    # and reset on restart, matching the SignalClient send-history precedent (D-04):
    # the point is to not move the flood onto the operator's phone, and a restart
    # is not a flood.
    duplicate_reported: set = set()

    def _resolve_ask_back_target(draft_row: dict):
        if draft_row and draft_row.get("reply_target_kind") == "group":
            group_id = draft_row.get("group_id")
            if isinstance(group_id, str) and len(group_id) > 0:
                return {"groupId": group_id}
            return None
        # Default: DM to the originating sender.
        sender = draft_row.get("sender_e164") if draft_row else None
        if isinstance(sender, str) and len(sender) > 0:
            return sender
        return None

    async def _safe_send(body, target, related_capture_id=None, related_draft_id=None):
        try:
            res = await signal_client.send(
                body,
                to=target,
                intent="extraction_preview",
                related_capture_id=related_capture_id or None,
                related_draft_id=related_draft_id or None,
                source_module="extraction/outbound.py",
            )
            return res or {"ok": True}
        except Exception as e:  # noqa: BLE001
            logger.warning("[outbound] signal send failed: %s", e)
            return {"ok": False, "reason": str(e)}

    def _first_capture_id(draft_row: dict):
        arr = draft_row.get("source_capture_ids") if draft_row else None
        if isinstance(arr, list) and len(arr) > 0 and isinstance(arr[0], str):
            return arr[0]
        return None

    def _is_operator_equals_sender(sender_e164) -> bool:
        return (
            isinstance(operator_recipient, str)
            and isinstance(sender_e164, str)
            and len(operator_recipient) > 0
            and operator_recipient == sender_e164
        )

    async def _report_duplicate(draft_row: dict, log_tag: str, text: str) -> None:
        """Tell the operator once that a draft is repeating itself (MUSHY-91).

        Once per draft, not once per suppression -- otherwise the flood simply
        moves from the farmer's phone to the operator's.

        Deliberately NOT trinity-skipped, unlike needs_review_ping. That skip
        exists so Santi is not messaged twice about the same thing; here the
        farmer-facing send was suppressed, so there is no second copy and this is
        the only signal that a draft is stuck.
        """
        draft_id = (draft_row and draft_row.get("id")) or ""
        if not operator_recipient or draft_id in duplicate_reported:
            return
        duplicate_reported.add(draft_id)
        sender = (draft_row and draft_row.get("sender_e164")) or "(unknown)"
        raw = (
            f"Hey Don Santiago, draft {draft_id} for {sender} tried to re-send the "
            f"same message ({log_tag}) with nothing changed. Held it back. "
            f"The draft is likely stuck waiting on a reply it cannot parse."
        )
        await _safe_send(sanitize(raw), operator_recipient, None, draft_id or None)
        logger.info("[outbound] duplicate_send reported to operator draft=%s",
                    _trunc_id(draft_id))

    async def _send_farmer_preview(draft_row: dict, log_tag: str) -> dict:
        """Shared send-to-farmer path for send_ask_back and send_confirm_prompt (D-1)."""
        target = _resolve_ask_back_target(draft_row)
        if target is None:
            logger.warning(
                "[outbound] %s: no_target draft=%s", log_tag, _trunc_id(draft_row.get("id"))
            )
            return {"ok": False, "reason": "no_target"}
        raw = (draft_row and draft_row.get("farmer_facing_preview")) or ""
        text = sanitize(raw)

        # MUSHY-91: never send the farmer an identical message for the same draft
        # twice. askback_turns caps at 3 but only advances on a reply the confirm
        # loop understands, so unparseable input (or a contentless envelope, as on
        # 2026-08-18) leaves the cap unreachable and the resend unbounded. The
        # invariant lives on the send, not on comprehension.
        #
        # Fail-open on purpose: no hook, or a lookup that throws, degrades to
        # sending. Outbound persistence is itself fail-open, so silence here is not
        # evidence of a duplicate -- and the failure this guard prevents is noisy,
        # while the failure it must never cause is a farmer waiting on a message
        # that was silently withheld.
        draft_id = (draft_row and draft_row.get("id")) or None
        if get_last_sent_body is not None and draft_id:
            try:
                last_body = await get_last_sent_body(draft_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "[outbound] %s: duplicate-check lookup failed, sending anyway: %s",
                    log_tag, e,
                )
                last_body = None
            if last_body is not None and last_body == text:
                logger.warning(
                    "[outbound] %s suppressed duplicate send draft=%s preview=\"%s\"",
                    log_tag, _trunc_id(draft_id), text[:40],
                )
                await _report_duplicate(draft_row, log_tag, text)
                return {"ok": False, "reason": "duplicate_send"}

        res = await _safe_send(
            text, target, _first_capture_id(draft_row), draft_row.get("id") or None
        )
        if res.get("ok"):
            logger.info(
                "[outbound] %s sent draft=%s preview=\"%s\"",
                log_tag, _trunc_id(draft_row.get("id")), text[:40],
            )
        return res

    async def _send_ask_back(draft_row: dict) -> dict:
        return await _send_farmer_preview(draft_row, "ask_back")

    async def _send_confirm_prompt(draft_row: dict) -> dict:
        return await _send_farmer_preview(draft_row, "confirm_prompt")

    async def _send_starting_seq_askback(draft_row: dict) -> dict:
        return await _send_farmer_preview(draft_row, "starting_seq_askback")

    async def _send_seeding_session_filled_preview(draft_row: dict) -> dict:
        return await _send_farmer_preview(draft_row, "seeding_session_filled_preview")

    async def _send_strain_ask_back(draft_row: dict) -> dict:
        # MUSHY-109: preview is pre-rendered by the strain gate, so this routes
        # through the shared farmer path unchanged -- it only earns its own tag.
        return await _send_farmer_preview(draft_row, "strain_ask_back")

    async def _send_batch_review_summary(batch: dict) -> dict:
        # batch = {sender_e164, draft_ids: [{id, type, status}, ...], reply_target_kind,
        #          group_id, source_capture_ids}
        # Key is snake_case draft_ids, matching the producer (batch_mode.py) and every
        # other field in the payload. Node's camelCase draftIds is a sanctioned rename:
        # reading it here while the producer sent draft_ids made every summary report
        # zero drafts.
        # One Signal message to Don Santiago summarising the page instead of N per-draft pings.
        no_operator = (
            not operator_recipient
            or not isinstance(operator_recipient, str)
            or len(operator_recipient) == 0
        )
        if no_operator:
            logger.warning("[outbound] batch_review_summary: no_target (operator_recipient unset)")
            return {"ok": False, "reason": "no_target"}
        drafts = (
            batch.get("draft_ids") if batch and isinstance(batch.get("draft_ids"), list) else []
        )
        sender = (batch and batch.get("sender_e164")) or "(unknown)"
        if _is_operator_equals_sender(sender):
            logger.info(
                "[outbound] batch_review_summary skipped: operator==sender (trinity); drafts=%d",
                len(drafts),
            )
            return {"ok": True, "skipped": "trinity"}
        total = len(drafts)
        need_review = sum(1 for d in drafts if d and d.get("status") == "needs_review")
        clean = total - need_review
        ids_preview = ", ".join(_trunc_id(d.get("id") if d else None) for d in drafts[:3])
        more = f", +{len(drafts) - 3} more" if len(drafts) > 3 else ""
        raw = (
            f"Hey Don Santiago, paper-log scan from {sender}: {total} drafts "
            f"({clean} clean, {need_review} need review). IDs: {ids_preview}{more}."
        )
        text = sanitize(raw)
        res = await _safe_send(text, operator_recipient)
        if res.get("ok"):
            logger.info(
                "[outbound] batch_review_summary sent total=%d clean=%d needs_review=%d",
                total, clean, need_review,
            )
        return res

    async def _send_needs_review_ping(draft_row: dict) -> dict:
        no_operator = (
            not operator_recipient
            or not isinstance(operator_recipient, str)
            or len(operator_recipient) == 0
        )
        if no_operator:
            logger.warning("[outbound] needs_review_ping: no_target (operator_recipient unset)")
            return {"ok": False, "reason": "no_target"}
        id_ = _trunc_id(draft_row.get("id") if draft_row else None)
        sender = (draft_row and draft_row.get("sender_e164")) or "(unknown)"
        if _is_operator_equals_sender(sender):
            logger.info(
                "[outbound] needs_review_ping skipped: operator==sender (trinity); draft=%s", id_
            )
            return {"ok": True, "skipped": "trinity"}
        reason = (draft_row and draft_row.get("needs_review_reason")) or "askback_cap"
        # Address Don Santiago by name (project memory: never "operator" as referent).
        raw = (
            f"Hey Don Santiago, draft {id_} for {sender} hit the 3-turn ask-back cap. "
            f"Marked for manual review. Reason: {reason}."
        )
        text = sanitize(raw)
        res = await _safe_send(text, operator_recipient, None, draft_row.get("id") or None)
        if res.get("ok"):
            logger.info("[outbound] needs_review_ping sent draft=%s", id_)
        return res

    async def dispatch(side_effect: str, draft_row: dict | None) -> dict:
        try:
            row = draft_row or {}
            match side_effect:
                case "send_ask_back":
                    return await _send_ask_back(row)
                case "send_confirm_prompt":
                    return await _send_confirm_prompt(row)
                case "send_starting_seq_askback":
                    return await _send_starting_seq_askback(row)
                case "send_seeding_session_filled_preview":
                    return await _send_seeding_session_filled_preview(row)
                case "send_strain_ask_back":
                    return await _send_strain_ask_back(row)
                case "send_needs_review_ping":
                    return await _send_needs_review_ping(row)
                case "send_batch_review_summary":
                    # draft_row carries the batch payload for this side effect.
                    return await _send_batch_review_summary(row)
                case "mark_expired" | "noop":
                    logger.debug("[outbound] side_effect=%s (no send)", side_effect)
                    return {"ok": True, "noop": True}
                case _:
                    logger.warning("[outbound] unknown side_effect=%s", side_effect)
                    return {"ok": False, "reason": "unknown_side_effect"}
        except Exception as e:  # noqa: BLE001
            logger.warning("[outbound] dispatch %s threw: %s", side_effect, e)
            return {"ok": False, "reason": str(e)}

    return {"dispatch": dispatch}
