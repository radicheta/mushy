"""
extraction/starting_seq.py -- seeding-session starting-SEQ ask-back.

Port of src/agents/alerter/src/extraction/pipeline.js lines 80-113
(buildStartingSeqAskBackText, parseStartingSeqReply) and 792-916
(handleStartingSeqReply). The enqueue short-circuit that calls
handle_starting_seq_ask_back (pipeline.js:582-672) is wired in pipeline.py.

Why this exists: the extractor can read date + strain off a photo/voice note
but usually cannot know where the day's block-number sequence left off. When
draft.needs_input == 'starting_seq' for a seeding_session draft, the pipeline
bypasses the generic missing-field ask-back and asks this dedicated question
instead: groups are already populated, only the per-session SEQ counter is
missing.

B5 SEQ is per-session, not per-strain: the counter runs across ALL groups in
the session in order. Group 2's first child continues where group 1 stopped.
mint_child_block_names (seq_helper.py) already implements the running-counter
arithmetic -- this module only walks groups[] in order and feeds it the
running total, it does not re-derive the numbering.

Fail-soft on the hint lookup: lookup_last_seq_for_date is wrapped in
try/except everywhere it's called. A lookup failure degrades to
last_seq=None and the question still goes out -- the farmer can answer
without the hint; they cannot answer a question that was never asked.

Idempotency: handle_starting_seq_reply checks draft.needs_input == 'starting_seq'
before minting. A second reply on a draft whose needs_input is already
cleared (farmer answered once, second reply arrives -- retry, echo, etc.)
returns {"ok": True, "noop": True} without touching the DB. Without this
guard a duplicate reply would re-walk groups[] and mint (and persist) a
second, different set of block names over the first.

Dispatcher shape: outbound_dispatcher["dispatch"](effect, draft_row) -- dict
subscript only, matching the convention locked in pipeline.py and
batch_mode.py. This module never falls back to attribute access.

parity delta vs Node (deliberate, not a bug): handle_starting_seq_reply has
no caller wired here -- Node's receive-loop.js never routes to it either.
Routing farmer replies to this function is a separate, later port task.
"""

from __future__ import annotations

import logging
import re

from farm_agent.extraction.preview_builder import (
    fmt_num,
    render_seeding_session,
    sanitize_farmer_text,
)
from farm_agent.extraction.seq_helper import (
    lookup_last_seq_for_date,
    mint_child_block_names,
    yyyymmdd_to_yymmdd,
)
from farm_agent.extraction.state_machine import DraftStatus
from farm_agent.tenancy.tenant import mask_number

logger = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r"^\d+$")
_YES_RE = re.compile(r"^yes$", re.IGNORECASE)

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _format_event_date_human(event_date) -> str:
    """Render '2026-05-22' as 'May 22'. Port of pipeline.js:60-67.

    Returns the input untouched (stringified) if it does not match
    YYYY-MM-DD so the ask-back text degrades gracefully.
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


def build_starting_seq_ask_back_text(
    *,
    total_children: int,
    event_date: str,
    last_seq: int | None,
    last_block_name: str | None,
    sender_name: str | None,
) -> str:
    """Farmer-facing ask-back prompt for a seeding_session with needs_input='starting_seq'.

    Port of pipeline.js:80-105. Style locks (project memory):
      - "block number" vocabulary (NOT "SEQ" -- dev shorthand only)
      - named greeting when sender_name resolvable
      - no em-dashes (sanitize_farmer_text sweep)
      - fmt_num for the total_children count
    """
    lines = []
    if isinstance(sender_name, str) and sender_name.strip():
        lines.append(f"Hi {sender_name.strip()},")
    date_str = _format_event_date_human(event_date)
    lines.append(
        f"{date_str} inoc, {fmt_num(total_children)} blocks. "
        "What block number should I start at?"
    )
    if last_seq is not None:
        hint = last_block_name if last_block_name else f"block {fmt_num(last_seq)}"
        lines.append(f"Last block number today was {hint}, so default is {fmt_num(last_seq + 1)}.")
    else:
        lines.append("No prior session today, so default is 1.")
    lines.append("Reply with a number or just YES for the default.")
    return sanitize_farmer_text("\n".join(lines))


def parse_starting_seq_reply(reply_text: str) -> dict:
    """Parse a farmer reply for the starting_seq ask-back. Port of pipeline.js:107-113.

    Returns {"kind": "yes"} | {"kind": "number", "value": int} | {"kind": "unclear"}.
    """
    if not isinstance(reply_text, str):
        return {"kind": "unclear"}
    t = reply_text.strip()
    if not t:
        return {"kind": "unclear"}
    if _YES_RE.match(t):
        return {"kind": "yes"}
    if _NUMBER_RE.match(t):
        return {"kind": "number", "value": int(t)}
    return {"kind": "unclear"}


async def _lookup_last_seq_safe(pool, event_date, log) -> int | None:
    """Wrap lookup_last_seq_for_date so any failure degrades to None.

    The ask-back (or the reply's default resolution) must not fail because
    the hint lookup failed -- the farmer can answer without the hint; they
    cannot answer a question that was never asked.
    """
    try:
        res = await lookup_last_seq_for_date(pool, event_date, log)
        if res and res.get("ok"):
            return res.get("last_seq")
    except Exception as e:  # noqa: BLE001
        log.warning("[extraction] starting_seq lookup threw: %s", e)
    return None


def _build_last_block_name_hint(draft: dict, last_seq: int | None) -> str | None:
    """Best-effort prior block_name for the hint -- helps the farmer recognize
    their own paper-log handwriting. Falls back to None (numeric-only hint)
    on any missing/malformed field.
    """
    if last_seq is None:
        return None
    try:
        groups = draft.get("groups") or []
        first_species = (groups[0] or {}).get("species", {}).get("value") if groups else None
        if not first_species:
            return None
        return f"{yyyymmdd_to_yymmdd(draft.get('event_date'))}_{first_species}_{last_seq}"
    except Exception:  # noqa: BLE001
        return None


async def handle_starting_seq_ask_back(
    *,
    draft: dict,
    draft_id: str,
    sender: str,
    capture_ctx: dict,
    source_capture_ids: list,
    prior_askback_turns: int,
    pool,
    extraction_db,
    outbound_dispatcher,
    log=None,
) -> dict:
    """Build + persist + dispatch the starting_seq ask-back. Port of pipeline.js:591-671.

    Called from enqueue's short-circuit once the draft has been persisted
    PENDING and draft.needs_input == 'starting_seq' is detected.
    """
    _log = log or logger
    capture_ctx = capture_ctx or {}

    last_seq = await _lookup_last_seq_safe(pool, draft.get("event_date"), _log)
    total_children = _sum_group_qtys(draft.get("groups"))
    last_block_name = _build_last_block_name_hint(draft, last_seq)

    preview = build_starting_seq_ask_back_text(
        total_children=total_children,
        event_date=draft.get("event_date"),
        last_seq=last_seq,
        last_block_name=last_block_name,
        sender_name=capture_ctx.get("sender_name"),
    )

    askback_upd = await extraction_db.update_draft_status(
        pool, draft_id, DraftStatus.AWAITING_FARMER, {"farmer_facing_preview": preview}
    )
    if not askback_upd.get("ok"):
        _log.warning(
            "[extraction] starting_seq status update failed sender=%s: %s",
            mask_number(sender), askback_upd.get("reason"),
        )
        return {"ok": False, "reason": askback_upd.get("reason")}

    draft_row = {
        "id": draft_id,
        "sender_e164": sender,
        "farmos_person": capture_ctx.get("farmos_person"),
        "status": DraftStatus.AWAITING_FARMER,
        "draft_json": draft,
        "farmer_facing_preview": preview,
        "reply_target_kind": capture_ctx.get("reply_target_kind"),
        "group_id": capture_ctx.get("group_id"),
        "source_capture_ids": source_capture_ids,
        "askback_turns": prior_askback_turns,
    }
    try:
        await outbound_dispatcher["dispatch"]("send_starting_seq_askback", draft_row)
    except Exception as e:  # noqa: BLE001
        _log.warning("[extraction] dispatch send_starting_seq_askback failed: %s", e)

    return {
        "ok": True,
        "draft_id": draft_id,
        "status": DraftStatus.AWAITING_FARMER,
        "side_effects": ["send_starting_seq_askback"],
    }


async def handle_starting_seq_reply(
    *,
    draft_id: str,
    reply_text: str,
    capture_ctx: dict,
    pool,
    extraction_db,
    outbound_dispatcher,
    log=None,
) -> dict:
    """Parse the farmer's starting-SEQ reply and mint block names. Port of pipeline.js:792-916.

    - unclear reply: re-dispatch a clarifying ask-back, mint nothing.
    - yes: use the default (last_seq + 1, or 1 if no prior session today).
    - number: use that value as the running counter's start.
    - Walk groups[] in order consuming ONE running counter across groups
      (B5: SEQ is per-session, not per-strain).
    - Idempotent: a second reply on a draft whose needs_input is already
      cleared returns {"ok": True, "noop": True} without re-minting.

    Not wired to any caller here -- see module docstring (parity delta).
    """
    _log = log or logger
    capture_ctx = capture_ctx or {}
    try:
        if not draft_id:
            return {"ok": False, "reason": "missing_draft_id"}
        row = await extraction_db.get_draft_by_id(pool, draft_id)
        if not row:
            return {"ok": False, "reason": "draft_not_found"}

        draft = row.get("draft_json")
        if not draft or draft.get("type") != "seeding_session":
            return {"ok": False, "reason": "not_seeding_session"}

        # Idempotency: needs_input already cleared -> noop. Guards against
        # duplicate replies double-minting a second set of block names.
        if draft.get("needs_input") != "starting_seq":
            return {"ok": True, "noop": True}

        parsed = parse_starting_seq_reply(reply_text)

        if parsed["kind"] == "unclear":
            last_seq = await _lookup_last_seq_safe(pool, draft.get("event_date"), _log)
            total_children = _sum_group_qtys(draft.get("groups"))
            base = build_starting_seq_ask_back_text(
                total_children=total_children,
                event_date=draft.get("event_date"),
                last_seq=last_seq,
                last_block_name=None,
                sender_name=capture_ctx.get("sender_name"),
            )
            preview = sanitize_farmer_text(f"Please reply with a number or YES.\n\n{base}")
            try:
                await outbound_dispatcher["dispatch"](
                    "send_starting_seq_askback", {**row, "farmer_facing_preview": preview}
                )
            except Exception as e:  # noqa: BLE001
                _log.warning("[extraction] re-dispatch starting_seq failed: %s", e)
            return {"ok": True, "draft_id": draft_id, "status": "awaiting_farmer", "clarified": True}

        # Resolve the starting N.
        if parsed["kind"] == "number":
            start_n = parsed["value"]
        else:  # yes -> default (last_seq + 1, or 1 if none).
            last_seq = await _lookup_last_seq_safe(pool, draft.get("event_date"), _log)
            start_n = last_seq + 1 if last_seq is not None else 1

        # Mint per-group block_names from ONE running counter across groups.
        yy_mmdd = yyyymmdd_to_yymmdd(draft.get("event_date"))
        updated_groups = []
        counter = start_n
        for g in (draft.get("groups") or []):
            species_code = (g or {}).get("species", {}).get("value") if g else None
            qty = (g or {}).get("qty", {}).get("value") if g else None
            if not species_code or not isinstance(qty, (int, float)) or isinstance(qty, bool):
                return {"ok": False, "reason": "malformed_group"}
            qty = int(qty)
            names = mint_child_block_names(yy_mmdd, species_code, counter, qty)
            counter += qty
            prev_cbn = (g or {}).get("child_block_names") or {}
            prev_confidence = prev_cbn.get("confidence") if isinstance(prev_cbn, dict) else None
            updated_groups.append({
                **g,
                "child_block_names": {
                    "value": names,
                    "confidence": prev_confidence if isinstance(prev_confidence, (int, float)) else 1,
                    "sources": ["model_inference", "text"],
                },
            })

        updated_draft = {**draft, "groups": updated_groups}
        updated_draft.pop("needs_input", None)

        # Re-render the preview off the FILLED draft. row["farmer_facing_preview"] is
        # still the ask-back question; persisting and dispatching it would answer the
        # farmer's SEQ reply with the same question they just answered.
        filled_preview = render_seeding_session(updated_draft)

        upd = await extraction_db.update_draft_status(
            pool,
            draft_id,
            DraftStatus.AWAITING_FARMER,
            {"draft_json": updated_draft, "farmer_facing_preview": filled_preview},
        )
        if not upd.get("ok"):
            _log.warning("[extraction] starting_seq fill update failed: %s", upd.get("reason"))
            return {"ok": False, "reason": upd.get("reason")}

        try:
            await outbound_dispatcher["dispatch"]("send_seeding_session_filled_preview", {
                **row,
                "draft_json": updated_draft,
                "farmer_facing_preview": filled_preview,
                "status": DraftStatus.AWAITING_FARMER,
            })
        except Exception as e:  # noqa: BLE001
            _log.warning("[extraction] dispatch filled_preview failed: %s", e)

        return {
            "ok": True,
            "draft_id": draft_id,
            "status": DraftStatus.AWAITING_FARMER,
            "start_seq": start_n,
            "side_effects": ["send_seeding_session_filled_preview"],
        }
    except Exception as e:  # noqa: BLE001 -- never raises, mirrors pipeline.js:912-915
        _log.warning("[extraction] handle_starting_seq_reply error: %s", e)
        return {"ok": False, "reason": str(e)}
