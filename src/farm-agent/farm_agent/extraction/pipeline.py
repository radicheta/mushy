"""
extraction/pipeline.py -- enqueue orchestrator.

Port of src/agents/alerter/src/extraction/pipeline.js lines 38-159 (module
helpers) and 289-791 (enqueue). Composes the extraction-db DAO (Task 1), the
pure state-machine (Task 2), the preview builder (Task 3), and the outbound
dispatcher (Task 4) with the pre-existing extractor (farm_agent.extraction.
extractor.create_extractor).

capture.js fires enqueue() in fire-and-forget mode for any farmer message with
a resolved farmos_person. enqueue() NEVER raises -- the top-level try/except
returns {"ok": False, "reason": str(e)} so a caller's .catch-equivalent stays a
no-op on the happy path.

Sequence (mirrors pipeline.js:289-791):
  1. get_in_flight_for_sender
  2. force_start_new_if_idle (D-01a hard guard)
  3. load image blocks, then extractor.extract(captures, in_flight_draft=...)
  4. resolve continuity decision: 'append' / 'replace' / 'start_new'
       - append:   update existing draft, extend source_capture_ids
       - replace:  update existing draft, replace draft_json
       - start_new: mark prior in-flight EXPIRED, insert new draft (PENDING)
  5. state_machine.transition with the freshly persisted draft
  6. update_draft_status to next_status + farmer_facing_preview (ask-back /
     needs-review-ping / confirm-prompt -- see D-1 below)
  7. dispatch each side_effect via outbound_dispatcher.dispatch

One branch is intentionally NOT ported here and is stubbed to raise
NotImplementedError, caught by the outer try/except like any other failure:
  - seeding_session starting_seq short-circuit  -- Task 7
handle_starting_seq_reply (pipeline.js:792+) is out of this port's line range
entirely and is stubbed the same way.

Multi-draft routing (drafts.length > 1, pipeline.js:393-407) dispatches to
farm_agent.extraction.batch_mode.run_batch_mode or .run_multi_confirm (Task
6): run_batch_mode when _should_batch_review(drafts) is true or any draft is
a seeding_session, else run_multi_confirm.

MUSHY-76 D-1 divergence from Node (pipeline.js:698-699): Node's preview check
covers only send_ask_back and send_needs_review_ping, so a cleanly-extracted
draft (state_machine's send_confirm_prompt tag) never gets a preview and the
farmer is never told a draft is waiting. This port's preview check covers all
three tags: build_confirm_prompt (with the YES/NO/EDIT suffix) for
send_confirm_prompt, build_preview (a question, not a confirm request -- no
suffix) for the other two.

2026-05-12 Node bug fix ported verbatim: attachment_paths are filesystem
paths, but the multimodal layer expects base64 {data, media_type} blocks.
Images are loaded via multimodal.read_image_to_base64 BEFORE the extractor
call; passing raw paths silently drops every image and the model sees an
empty prompt (schema_invalid).

Everything after the extractor call succeeds is fail-soft: a failed usage
stamp or a failed side-effect dispatch is logged and swallowed -- enqueue
still returns {"ok": True, ...}.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from farm_agent.extraction import extraction_db as _extraction_db_module
from farm_agent.extraction import multimodal
from farm_agent.extraction import preview_builder as _preview_builder_module
from farm_agent.extraction import state_machine as _state_machine_module
from farm_agent.extraction.batch_mode import run_batch_mode, run_multi_confirm
from farm_agent.tenancy.tenant import mask_number

logger = logging.getLogger(__name__)

_IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|gif|webp)$", re.IGNORECASE)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_USAGE_MODEL = "claude-sonnet-4-6"

_PREVIEW_SIDE_EFFECTS = ("send_ask_back", "send_needs_review_ping", "send_confirm_prompt")

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# ---------------------------------------------------------------------------
# Module helpers -- pipeline.js:38-159
# ---------------------------------------------------------------------------


async def _load_image_blocks(paths, log: logging.Logger) -> list[dict]:
    """Resolve filesystem attachment paths into base64 content blocks.

    Port of pipeline.js:38-51 (loadImageBlocks). Fail-open per path: a load
    failure is logged and the path is skipped, never raised.
    """
    if not isinstance(paths, list) or len(paths) == 0:
        return []
    blocks: list[dict] = []
    for p in paths:
        if not isinstance(p, str) or not _IMAGE_EXT_RE.search(p):
            continue
        r = await multimodal.read_image_to_base64(p, log)
        if not r or not r.get("ok"):
            log.warning(
                "[pipeline] image load skipped: %s (%s)",
                p, r.get("reason") if r else None,
            )
            continue
        blocks.append({"data": r["data"], "media_type": r["media_type"]})
    return blocks


def _format_event_date_human(event_date) -> str:
    """Render '2026-05-22' as 'May 22'. Port of pipeline.js:60-67.

    Returns the input untouched (stringified) if it does not match
    YYYY-MM-DD so ask-back text degrades gracefully.
    """
    if not isinstance(event_date, str):
        return str(event_date)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", event_date)
    if not m:
        return event_date
    month_idx = int(m.group(2)) - 1
    month = MONTHS[month_idx] if 0 <= month_idx < 12 else m.group(2)
    day = int(m.group(3))
    return f"{month} {day}"


def _sum_group_qtys(groups) -> float:
    """Sum a SeedingSession's group qtys. Port of pipeline.js:115-123.

    Tolerates missing/malformed qty fields.
    """
    if not isinstance(groups, list):
        return 0
    total = 0
    for g in groups:
        v = (g or {}).get("qty", {}).get("value") if g else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            total += v
    return total


def _min_leaf_confidence(obj) -> float:
    """Walk a nested per_field_confidence object, return the min numeric leaf.

    Port of pipeline.js:129-145. Empty/missing-leaf objects return 0 --
    conservative: forces batch-review over spamming the farmer with confirm
    prompts based on zero confidence signal.
    """
    if not isinstance(obj, dict):
        return 0
    state = {"min": None, "saw": False}

    def walk(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            state["saw"] = True
            if state["min"] is None or v < state["min"]:
                state["min"] = v
            return
        if isinstance(v, dict):
            for k in v:
                walk(v[k])

    walk(obj)
    return state["min"] if state["saw"] else 0


def _should_batch_review(drafts_arr) -> bool:
    """Routing heuristic locked per D-BACK-02. Port of pipeline.js:151-159.

    drafts.length > 5 OR min over drafts of _min_leaf_confidence < 0.7
    -> batch review (operator summary). Otherwise -> small-N fan-out.
    """
    if not isinstance(drafts_arr, list) or len(drafts_arr) == 0:
        return False
    if len(drafts_arr) > 5:
        return True
    for item in drafts_arr:
        c = _min_leaf_confidence((item or {}).get("per_field_confidence"))
        if c < 0.7:
            return True
    return False


def _normalize_updated_at_ms(updated_at) -> int | None:
    """Normalize the in-flight row's `updated_at` into `last_updated_at_ms`.

    MUSHY-76 decision: `updated_at` is the real signal_draft column name (a
    datetime, an ISO string, or None) -- there is no `updated_at_ms` column.
    """
    if updated_at is None:
        return None
    if isinstance(updated_at, datetime):
        dt = updated_at if updated_at.tzinfo is not None else updated_at.replace(tzinfo=timezone.utc)
        return int((dt - _EPOCH).total_seconds() * 1000)
    if isinstance(updated_at, str):
        try:
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int((dt - _EPOCH).total_seconds() * 1000)
    return None


async def _noop_dispatch(effect, row):  # pragma: no cover -- only used absent a real dispatcher
    return {"ok": True, "noop": True}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_extraction_pipeline(
    pool,
    extractor: dict,
    config,
    *,
    extraction_db=None,
    state_machine=None,
    preview_builder=None,
    outbound_dispatcher=None,
    clock=None,
    log: logging.Logger | None = None,
) -> dict:
    db = extraction_db if extraction_db is not None else _extraction_db_module
    sm = state_machine if state_machine is not None else _state_machine_module
    pb = preview_builder if preview_builder is not None else _preview_builder_module
    _log = log or logger
    _clock = clock or (lambda: int(datetime.now(timezone.utc).timestamp() * 1000))
    _dispatch = (
        outbound_dispatcher["dispatch"] if outbound_dispatcher is not None else _noop_dispatch
    )

    async def _route_multi(*, drafts_arr, capture_ctx, sender, capture_id, now_ms, in_flight):
        # pipeline.js:395-407 routing rule.
        has_seeding_session = any(
            ((item or {}).get("draft") or {}).get("type") == "seeding_session"
            for item in drafts_arr
        )
        route_kwargs = dict(
            drafts_arr=drafts_arr,
            capture_ctx=capture_ctx,
            sender=sender,
            capture_id=capture_id,
            now_ms=now_ms,
            in_flight=in_flight,
            pool=pool,
            extraction_db=db,
            state_machine=sm,
            preview_builder=pb,
            outbound_dispatcher={"dispatch": _dispatch},
            config=config,
            log=_log,
        )
        if _should_batch_review(drafts_arr) or has_seeding_session:
            return await run_batch_mode(source_capture_ids_base=[capture_id], **route_kwargs)
        return await run_multi_confirm(**route_kwargs)

    async def _handle_starting_seq_askback(**kwargs):
        # Task 7: seeding_session starting_seq short-circuit (pipeline.js:582-672).
        raise NotImplementedError("starting_seq short-circuit is ported in Task 7")

    async def handle_starting_seq_reply(**kwargs):
        # pipeline.js:792+ -- out of this task's ported line range entirely.
        raise NotImplementedError("handle_starting_seq_reply is not ported by Task 5")

    async def _dispatch_effect(effect: str, row: dict) -> None:
        try:
            await _dispatch(effect, row)
        except Exception as e:  # noqa: BLE001 -- fail-soft, never fail enqueue
            _log.warning("[extraction] dispatch %s failed: %s", effect, e)

    async def enqueue(capture_ctx: dict) -> dict:
        try:
            now_ms = _clock()
            capture_ctx = capture_ctx or {}
            sender = capture_ctx.get("sender")
            capture_id = capture_ctx.get("capture_id")
            if not sender or not capture_id:
                return {"ok": False, "reason": "missing_sender_or_capture_id"}

            # 1. in-flight lookup
            try:
                in_flight = await db.get_in_flight_for_sender(pool, sender)
            except Exception as e:  # noqa: BLE001
                _log.warning(
                    "[extraction] in-flight lookup failed sender=%s: %s", mask_number(sender), e
                )
                return {"ok": False, "reason": str(e)}

            # Normalize in_flight last_updated_at_ms for the state-machine helpers.
            in_flight_for_sm = None
            if in_flight:
                in_flight_for_sm = dict(in_flight)
                in_flight_for_sm["last_updated_at_ms"] = _normalize_updated_at_ms(
                    in_flight.get("updated_at")
                )

            # 2. idle-gap hard guard
            forced = sm.force_start_new_if_idle(in_flight_for_sm, now_ms, config.draft_idle_gap_min)
            treat_in_flight = None if forced == "start_new" else in_flight

            # 3. extractor. Load images BEFORE calling extract() -- attachment_paths
            # are filesystem paths, not base64 blocks (2026-05-12 Node bug fix).
            image_blocks = await _load_image_blocks(capture_ctx.get("attachment_paths"), _log)
            transcripts = capture_ctx.get("transcripts")
            captures = [{
                "capture_id": capture_id,
                "text": capture_ctx.get("text") or None,
                "transcript": "\n".join(transcripts) if isinstance(transcripts, list) else None,
                "images": image_blocks,
            }]
            try:
                extract_result = await extractor["extract"](
                    captures,
                    in_flight_draft=treat_in_flight,
                    corpus_context=capture_ctx.get("corpus_context"),
                )
            except Exception as e:  # noqa: BLE001
                _log.warning("[extraction] extract threw sender=%s: %s", mask_number(sender), e)
                return {"ok": False, "reason": str(e)}

            if not extract_result or not extract_result.get("ok"):
                reason = (extract_result or {}).get("reason") or "extractor_failed"
                _log.warning("[extraction] extractor returned ok:false reason=%s", reason)
                return {"ok": False, "reason": reason}

            # 999.53: best-effort token-usage stamp on the originating signal_capture
            # row. Skipped on usage:None; failure is logged and swallowed.
            usage = extract_result.get("usage")
            if usage:
                try:
                    async with pool.connection() as conn:
                        await conn.execute(
                            """UPDATE signal_capture
                                 SET input_tokens = %s,
                                     output_tokens = %s,
                                     cache_creation_input_tokens = %s,
                                     cache_read_input_tokens = %s,
                                     model = %s
                               WHERE id = %s""",
                            (
                                usage.get("input_tokens"),
                                usage.get("output_tokens"),
                                usage.get("cache_creation_input_tokens"),
                                usage.get("cache_read_input_tokens"),
                                _USAGE_MODEL,
                                capture_id,
                            ),
                        )
                except Exception as e:  # noqa: BLE001
                    _log.warning("[extraction] usage stamp failed: %s", e)

            # Plan 08: extractor returns drafts[] (multi-event per page for
            # paper-log scans). drafts.length == 1 is the legacy single-draft
            # path below; > 1 routes to multi-draft handling (Task 6).
            drafts_arr = extract_result.get("drafts")
            drafts_arr = drafts_arr if isinstance(drafts_arr, list) else []
            if len(drafts_arr) > 1:
                return await _route_multi(
                    drafts_arr=drafts_arr,
                    capture_ctx=capture_ctx,
                    sender=sender,
                    capture_id=capture_id,
                    now_ms=now_ms,
                    in_flight=in_flight,
                )

            # 4. resolve continuity
            llm_decision = extract_result.get("continuity_decision") or "start_new"
            continuity = "start_new" if forced == "start_new" else llm_decision

            if continuity == "append" and treat_in_flight:
                source_capture_ids = list(treat_in_flight.get("source_capture_ids") or []) + [
                    capture_id
                ]
                draft_id = treat_in_flight["id"]
                prior_askback_turns = treat_in_flight.get("askback_turns") or 0
            elif continuity == "replace" and treat_in_flight:
                source_capture_ids = treat_in_flight.get("source_capture_ids") or [capture_id]
                draft_id = treat_in_flight["id"]
                prior_askback_turns = treat_in_flight.get("askback_turns") or 0
            else:
                # start_new (or forced, or LLM said append/replace but no in-flight existed)
                source_capture_ids = [capture_id]
                draft_id = db.compute_draft_id(source_capture_ids)
                prior_askback_turns = 0

            # Expire prior in-flight if starting new.
            if continuity == "start_new" and in_flight and in_flight.get("id") != draft_id:
                exp = await db.update_draft_status(pool, in_flight["id"], sm.DraftStatus.EXPIRED)
                if not exp.get("ok"):
                    _log.warning("[extraction] expire prior draft failed: %s", exp.get("reason"))

            # 5. persist draft -- insert on start_new, update on append/replace.
            draft = extract_result.get("draft")
            log_type = draft.get("type") if draft else None

            if continuity in ("append", "replace"):
                upd = await db.update_draft_status(
                    pool,
                    draft_id,
                    sm.DraftStatus.PENDING,
                    {
                        "draft_json": draft,
                        "per_field_confidence": extract_result.get("per_field_confidence"),
                        "log_type": log_type,
                    },
                )
                if not upd.get("ok"):
                    _log.warning("[extraction] update-existing failed: %s", upd.get("reason"))
                    return {"ok": False, "reason": upd.get("reason")}
                # source_capture_ids extension: separate SQL since the extras
                # whitelist excludes arrays.
                try:
                    async with pool.connection() as conn:
                        await conn.execute(
                            "UPDATE signal_draft SET source_capture_ids = %s WHERE id = %s",
                            (source_capture_ids, draft_id),
                        )
                except Exception as e:  # noqa: BLE001
                    _log.warning("[extraction] source_capture_ids update failed: %s", e)
            else:
                ins = await db.insert_draft(
                    pool,
                    {
                        "id": draft_id,
                        "sender_e164": sender,
                        "farmos_person": capture_ctx.get("farmos_person"),
                        "source_capture_ids": source_capture_ids,
                        "status": sm.DraftStatus.PENDING,
                        "log_type": log_type,
                        "draft_json": draft,
                        "per_field_confidence": extract_result.get("per_field_confidence"),
                        "askback_turns": 0,
                        "reply_target_kind": capture_ctx.get("reply_target_kind"),
                        "group_id": capture_ctx.get("group_id"),
                    },
                )
                if not ins.get("ok"):
                    _log.warning("[extraction] insert_draft failed: %s", ins.get("reason"))
                    return {"ok": False, "reason": ins.get("reason")}

            # 5b. seeding_session starting_seq short-circuit -- Task 7 stub.
            if draft and draft.get("type") == "seeding_session" and draft.get("needs_input") == "starting_seq":
                return await _handle_starting_seq_askback(
                    draft=draft,
                    draft_id=draft_id,
                    sender=sender,
                    capture_ctx=capture_ctx,
                    source_capture_ids=source_capture_ids,
                    prior_askback_turns=prior_askback_turns,
                    continuity=continuity,
                )

            # 6. state-machine transition
            transition = sm.transition(
                {
                    "status": sm.DraftStatus.PENDING,
                    "askback_turns": prior_askback_turns,
                    "last_updated_at_ms": now_ms,
                },
                {
                    "type": "extraction_result",
                    "draft": draft,
                    "per_field_confidence": extract_result.get("per_field_confidence") or {},
                    "threshold": config.extraction_confidence_threshold,
                    "max_askback_turns": config.max_askback_turns,
                    "now_ms": now_ms,
                },
            )

            # 7. status update with extras (preview when ask-back/needs-review/
            # confirm-prompt path -- D-1 divergence covers all three tags).
            extras: dict = {}
            needs_preview = any(effect in transition.side_effects for effect in _PREVIEW_SIDE_EFFECTS)
            if needs_preview:
                try:
                    required = sm.REQUIRED_FIELDS.get((draft or {}).get("type"), [])
                    if "send_confirm_prompt" in transition.side_effects:
                        preview = pb.build_confirm_prompt(
                            draft=draft,
                            per_field_confidence=extract_result.get("per_field_confidence") or {},
                            threshold=config.extraction_confidence_threshold,
                            required_fields=required,
                        )
                    else:
                        preview = pb.build_preview(
                            draft=draft,
                            per_field_confidence=extract_result.get("per_field_confidence") or {},
                            threshold=config.extraction_confidence_threshold,
                            required_fields=required,
                        )
                    extras["farmer_facing_preview"] = preview
                except Exception as e:  # noqa: BLE001
                    _log.warning("[extraction] preview build failed: %s", e)
            if transition.reason == "askback_cap":
                extras["needs_review_reason"] = "askback_cap_exceeded"

            final_upd = await db.update_draft_status(pool, draft_id, transition.next_status, extras)
            if not final_upd.get("ok"):
                _log.warning("[extraction] final status update failed: %s", final_upd.get("reason"))
                return {"ok": False, "reason": final_upd.get("reason")}

            # Bump askback_turns counter when ask-back fired.
            if "send_ask_back" in transition.side_effects:
                bump = await db.advance_askback_turn(pool, draft_id)
                if not bump.get("ok"):
                    _log.warning("[extraction] askback bump failed: %s", bump.get("reason"))

            # 8. dispatch side effects. Build a minimal draft_row for the dispatcher.
            draft_row = {
                "id": draft_id,
                "sender_e164": sender,
                "farmos_person": capture_ctx.get("farmos_person"),
                "status": transition.next_status,
                "draft_json": draft,
                "farmer_facing_preview": extras.get("farmer_facing_preview"),
                "reply_target_kind": capture_ctx.get("reply_target_kind"),
                "group_id": capture_ctx.get("group_id"),
                "source_capture_ids": source_capture_ids,
                "askback_turns": transition.next_askback_turns,
            }
            for effect in transition.side_effects:
                await _dispatch_effect(effect, draft_row)

            return {
                "ok": True,
                "draft_id": draft_id,
                "status": transition.next_status,
                "continuity": continuity,
                "side_effects": transition.side_effects,
            }
        except Exception as e:  # noqa: BLE001 -- enqueue never raises
            _log.warning("[extraction] error: %s", e)
            return {"ok": False, "reason": str(e)}

    return {"enqueue": enqueue, "handle_starting_seq_reply": handle_starting_seq_reply}
