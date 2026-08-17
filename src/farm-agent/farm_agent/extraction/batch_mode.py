"""
extraction/batch_mode.py -- multi-draft page routing.

Port of src/agents/alerter/src/extraction/pipeline.js lines 182-288
(runBatchMode) and 393-493 (the small-N multi_confirm fan-out). Handles the
case where one capture (a photographed paper-log page) yields more than one
draft.

Routing between the two functions is decided by the caller (pipeline.py's
_route_multi): run_batch_mode when _should_batch_review(drafts) is true or
any draft is a seeding_session, else run_multi_confirm.

2026-05-25 regression this module exists to prevent (ported verbatim from
pipeline.js:231-248): batch mode sends ONE operator summary for the whole
page and never solicits a per-draft farmer YES. If a clean batch draft were
left in awaiting_farmer, it would (1) wait forever for a confirmation that
batch mode never asks for, and (2) hold the per-sender in-flight slot
(D-02c's partial unique index on sender_e164 WHERE status IN ('pending',
'awaiting_farmer')), so every sibling insert on the same page would fail
with in_flight_conflict -- silently dropping all but the first entry of a
multi-entry page. run_batch_mode therefore reroutes a clean transition to
needs_review, preserving the clean-vs-flagged split via needs_review_reason
('batch_mode_clean' vs 'batch_mode_low_conf') for the operator summary.

Both functions are fail-soft per draft: a failed insert or status update on
one draft is logged and the loop continues -- one bad entry must never drop
the rest of the page.

MUSHY-76 D-1 divergence applies to run_multi_confirm exactly as it does to
the single-draft path (pipeline.py): the FSM's send_confirm_prompt tag is now
live, so a clean small-N draft gets a preview built via build_confirm_prompt
and a confirm-prompt dispatch, not silence.

MUSHY-76 D-4: run_multi_confirm cannot literally give N drafts N independent
confirm prompts. Phase 53 BACK-02 intended exactly that for small-N
high-confidence multi-draft captures, but the FSM's clean-confirm (and
under-cap ask-back) branches both resolve to AWAITING_FARMER, and D-02c's
partial unique index permits at most ONE pending/awaiting_farmer row per
sender, globally -- not per draft. A literal pipeline.js:393-493 port (insert
each draft PENDING, then update to whatever the FSM says) hits this the
moment a second draft in the same batch would also reach awaiting_farmer: in
Node, against a real DB, that second INSERT fails with in_flight_conflict and
the draft is silently dropped -- the identical failure class the 2026-05-25
batch-mode fix exists to prevent, just reached via a different path. (Node's
own pipeline.test.js never catches this because its insertDraft mock always
returns ok:true, never enforcing the index.)

Changing the index to allow more than one in-flight row per sender is out of
scope here -- it is shared with the live Node agent against the production
database. Instead: every draft still persists, deterministically. The FIRST
draft to resolve to AWAITING_FARMER claims the slot and gets its per-draft
dispatch (send_confirm_prompt or send_ask_back). Every SUBSEQUENT draft that
would also resolve to AWAITING_FARMER is persisted as needs_review instead
(needs_review_reason='multi_confirm_slot_taken') and gets no per-draft
dispatch -- persisting it for operator review beats Node's silent drop.
Drafts that land in needs_review on their own merits (askback_cap) keep their
own needs_review_reason and are unaffected by the slot rule. Because the FSM
transition is pure, run_multi_confirm evaluates it BEFORE inserting each
draft so the correct, already-final status can be written in a single insert
-- no draft is ever inserted as pending/awaiting_farmer only to be downgraded
a moment later, which would still race the next draft's insert against the
partial index.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PREVIEW_SIDE_EFFECTS = ("send_ask_back", "send_needs_review_ping", "send_confirm_prompt")


async def run_batch_mode(
    *,
    drafts_arr,
    capture_ctx,
    sender,
    capture_id,
    source_capture_ids_base,
    now_ms,
    in_flight,
    pool,
    extraction_db,
    state_machine,
    preview_builder,
    outbound_dispatcher,
    config,
    log,
) -> dict:
    _log = log or logger

    # Expire any prior in-flight before the batch lands -- paper-log scan resets
    # conversational state.
    if in_flight:
        exp = await extraction_db.update_draft_status(
            pool, in_flight["id"], state_machine.DraftStatus.EXPIRED
        )
        if not exp.get("ok"):
            _log and _log.warning(
                "[extraction] batch: expire prior draft failed: %s", exp.get("reason")
            )

    persisted: list[dict] = []
    for i, item in enumerate(drafts_arr):
        item = item or {}
        draft = item.get("draft")
        per_field_confidence = item.get("per_field_confidence")
        draft_id = extraction_db.compute_draft_id(source_capture_ids_base, i)

        ins = await extraction_db.insert_draft(
            pool,
            {
                "id": draft_id,
                "sender_e164": sender,
                "farmos_person": capture_ctx.get("farmos_person"),
                "source_capture_ids": source_capture_ids_base,
                "status": state_machine.DraftStatus.PENDING,
                "log_type": draft.get("type") if draft else None,
                "draft_json": draft,
                "per_field_confidence": per_field_confidence,
                "askback_turns": 0,
                "reply_target_kind": capture_ctx.get("reply_target_kind"),
                "group_id": capture_ctx.get("group_id"),
            },
        )
        if not ins.get("ok"):
            _log and _log.warning(
                "[extraction] batch: insert_draft idx=%d failed: %s", i, ins.get("reason")
            )
            continue

        # Run the FSM with max_askback_turns=0 to force the needs-review path
        # instead of send_ask_back for any draft with missing/low-conf fields.
        transition = state_machine.transition(
            {"status": state_machine.DraftStatus.PENDING, "askback_turns": 0,
             "last_updated_at_ms": now_ms},
            {
                "type": "extraction_result",
                "draft": draft,
                "per_field_confidence": per_field_confidence or {},
                "threshold": config.extraction_confidence_threshold,
                "max_askback_turns": 0,
                "now_ms": now_ms,
            },
        )

        next_status = transition.next_status
        extras: dict = {}
        if transition.reason == "askback_cap":
            extras["needs_review_reason"] = "batch_mode_low_conf"
        elif next_status == state_machine.DraftStatus.AWAITING_FARMER:
            # 2026-05-25: a clean batch draft must NOT sit in awaiting_farmer. It
            # would (1) wait forever for a per-draft YES that batch mode never
            # solicits, and (2) hold the per-sender in-flight slot, so every
            # sibling insert on the same page fails with in_flight_conflict and
            # all but the first entry of a multi-entry page is silently dropped.
            next_status = state_machine.DraftStatus.NEEDS_REVIEW
            extras["needs_review_reason"] = "batch_mode_clean"

        final_upd = await extraction_db.update_draft_status(pool, draft_id, next_status, extras)
        if not final_upd.get("ok"):
            _log and _log.warning(
                "[extraction] batch: final status update idx=%d failed: %s",
                i, final_upd.get("reason"),
            )
        persisted.append({
            "id": draft_id,
            "type": draft.get("type") if draft else None,
            "status": next_status,
            "needs_review_reason": extras.get("needs_review_reason"),
        })

    # One summary ping to the operator for the whole page.
    if persisted:
        try:
            await outbound_dispatcher["dispatch"]("send_batch_review_summary", {
                "sender_e164": sender,
                "source_capture_ids": source_capture_ids_base,
                "reply_target_kind": capture_ctx.get("reply_target_kind"),
                "group_id": capture_ctx.get("group_id"),
                "draft_ids": persisted,
            })
        except Exception as e:  # noqa: BLE001 -- fail-soft, never fail the batch
            _log and _log.warning("[extraction] batch: dispatch summary failed: %s", e)

    return {
        "ok": True,
        "mode": "batch",
        "count": len(persisted),
        "draft_ids": [d["id"] for d in persisted],
        # Clean-vs-flagged split keyed off needs_review_reason since both land in
        # needs_review status (2026-05-25): batch_mode_clean were high-confidence,
        # batch_mode_low_conf tripped the confidence gate.
        "clean_count": sum(1 for d in persisted if d["needs_review_reason"] == "batch_mode_clean"),
        "needs_review_count": sum(
            1 for d in persisted if d["needs_review_reason"] == "batch_mode_low_conf"
        ),
    }


async def run_multi_confirm(
    *,
    drafts_arr,
    capture_ctx,
    sender,
    capture_id,
    in_flight,
    pool,
    extraction_db,
    state_machine,
    preview_builder,
    outbound_dispatcher,
    config,
    log,
    now_ms=None,
) -> dict:
    _log = log or logger

    # Expire prior in-flight once -- a multi-draft capture resets the
    # conversational state, mirroring run_batch_mode's behavior.
    if in_flight:
        exp = await extraction_db.update_draft_status(
            pool, in_flight["id"], state_machine.DraftStatus.EXPIRED
        )
        if not exp.get("ok"):
            _log and _log.warning(
                "[extraction] multi_confirm: expire prior draft failed: %s", exp.get("reason")
            )

    results: list[dict] = []
    side_effects_all: list[str] = []
    # D-4: whether an earlier draft in THIS batch has already claimed the
    # sender's one in-flight slot. The FSM transition is pure (no IO), so it
    # is evaluated BEFORE inserting each draft -- the correct, already-final
    # status is written on a single insert. No draft is ever written as
    # pending/awaiting_farmer only to be downgraded a moment later, which
    # would still race the next draft's insert against the partial index.
    slot_taken = False
    for i, item in enumerate(drafts_arr):
        item = item or {}
        draft = item.get("draft")
        per_field_confidence = item.get("per_field_confidence") or {}
        draft_id = extraction_db.compute_draft_id([capture_id], i)

        # Run the FSM with the real configured max_askback_turns; the high-conf
        # path typically produces send_confirm_prompt directly (no ask-back).
        transition = state_machine.transition(
            {"status": state_machine.DraftStatus.PENDING, "askback_turns": 0,
             "last_updated_at_ms": now_ms},
            {
                "type": "extraction_result",
                "draft": draft,
                "per_field_confidence": per_field_confidence,
                "threshold": config.extraction_confidence_threshold,
                "max_askback_turns": config.max_askback_turns,
                "now_ms": now_ms,
            },
        )

        final_status = transition.next_status
        d_extras: dict = {}
        slot_conflict = False
        if transition.reason == "askback_cap":
            d_extras["needs_review_reason"] = "askback_cap_exceeded"
        if final_status == state_machine.DraftStatus.AWAITING_FARMER:
            if slot_taken:
                # D-4: first draft to reach awaiting_farmer wins the slot
                # deterministically; every later one that would also reach it
                # is persisted for operator review instead of either holding
                # a second (index-violating) in-flight row or being dropped.
                final_status = state_machine.DraftStatus.NEEDS_REVIEW
                d_extras["needs_review_reason"] = "multi_confirm_slot_taken"
                slot_conflict = True
            else:
                slot_taken = True

        # D-1: the FSM's send_confirm_prompt tag is live (Task 2), so a clean
        # draft now gets a preview and a confirm-prompt dispatch here too.
        needs_preview = any(e in transition.side_effects for e in _PREVIEW_SIDE_EFFECTS)
        if needs_preview:
            try:
                required = state_machine.REQUIRED_FIELDS.get((draft or {}).get("type"), [])
                if "send_confirm_prompt" in transition.side_effects:
                    preview = preview_builder.build_confirm_prompt(
                        draft=draft,
                        per_field_confidence=per_field_confidence,
                        threshold=config.extraction_confidence_threshold,
                        required_fields=required,
                    )
                else:
                    preview = preview_builder.build_preview(
                        draft=draft,
                        per_field_confidence=per_field_confidence,
                        threshold=config.extraction_confidence_threshold,
                        required_fields=required,
                    )
                d_extras["farmer_facing_preview"] = preview
            except Exception as e:  # noqa: BLE001
                _log and _log.warning(
                    "[extraction] multi_confirm: preview build failed: %s", e
                )

        ins = await extraction_db.insert_draft(
            pool,
            {
                "id": draft_id,
                "sender_e164": sender,
                "farmos_person": capture_ctx.get("farmos_person"),
                "source_capture_ids": [capture_id],
                "status": final_status,
                "log_type": draft.get("type") if draft else None,
                "draft_json": draft,
                "per_field_confidence": per_field_confidence,
                "askback_turns": 0,
                "farmer_facing_preview": d_extras.get("farmer_facing_preview"),
                "needs_review_reason": d_extras.get("needs_review_reason"),
                "reply_target_kind": capture_ctx.get("reply_target_kind"),
                "group_id": capture_ctx.get("group_id"),
            },
        )
        if not ins.get("ok"):
            _log and _log.warning(
                "[extraction] multi_confirm: insert_draft idx=%d failed: %s", i, ins.get("reason")
            )
            continue

        # D-4: a draft that lost the slot race gets no per-draft dispatch --
        # its confirm prompt / ask-back was never promised, unlike the winner.
        if not slot_conflict:
            d_draft_row = {
                "id": draft_id,
                "sender_e164": sender,
                "farmos_person": capture_ctx.get("farmos_person"),
                "status": final_status,
                "draft_json": draft,
                "farmer_facing_preview": d_extras.get("farmer_facing_preview"),
                "reply_target_kind": capture_ctx.get("reply_target_kind"),
                "group_id": capture_ctx.get("group_id"),
                "source_capture_ids": [capture_id],
                "askback_turns": transition.next_askback_turns or 0,
            }
            for effect in transition.side_effects:
                try:
                    await outbound_dispatcher["dispatch"](effect, d_draft_row)
                    side_effects_all.append(effect)
                except Exception as e:  # noqa: BLE001 -- fail-soft, never fail the fan-out
                    _log and _log.warning(
                        "[extraction] multi_confirm: dispatch %s failed: %s", effect, e
                    )

        results.append({"id": draft_id, "status": final_status})

    return {
        "ok": True,
        "mode": "multi_confirm",
        "count": len(results),
        "draft_ids": [r["id"] for r in results],
        "side_effects": side_effects_all,
    }
