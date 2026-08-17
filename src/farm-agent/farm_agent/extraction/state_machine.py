"""
Extraction-draft FSM -- pure transition() function.

Port of src/agents/alerter/src/extraction/state-machine.js

Honors:
  D-01a -- 30min idle cap forces start_new (force_start_new_if_idle helper).
  D-02b -- status enum: pending / awaiting_farmer / needs_review / expired.
           (Phase 38 owns these four; Phase 39 owns confirmed/discarded.)
  D-03  -- ask-back trigger on missing-required OR per-field confidence below
           threshold.
  D-05  -- hard cap on ask-back turns (default 3) before status -> needs_review.

MUSHY-76 D-1 divergence from Node: the clean-extraction branch emits
`send_confirm_prompt` here, not Node's `handoff_to_phase_39`. That Node tag is
a no-send downstream, so a perfectly-extracted draft is silently parked and
the farmer is never told it is waiting. Everything else about that branch --
next_status, next_askback_turns, reason='ready_for_confirm', ask_back_info --
is unchanged.

PURE: no DB, no I/O, no logging side effects. All effects are returned as
strings in side_effects for the caller to dispatch against signal_draft +
signal.js.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Required-field map per RESEARCH.md section 8.
# observation special case: state OR notes required (handled inline in
# should_ask_back as the synthetic 'state_or_notes' marker).
REQUIRED_FIELDS: dict[str, list[str]] = {
    "seeding": ["species", "block_name", "qty", "event_timestamp"],
    "activity": ["name", "asset_ref", "event_timestamp"],
    "input": ["recipe_lot", "asset_ref", "event_timestamp"],
    "observation": ["asset_ref", "event_timestamp"],
    "harvest": ["harvest_batch_id", "source_block_refs", "qty_g", "event_timestamp"],
    # Phase 47 Plan 01: multi-parent groups-shape inoc. Required = event_date + groups[].
    # Per-group presence (parent/species/qty/child_block_names) is enforced by the
    # SeedingSession Zod schema, not by REQUIRED_FIELDS (which is a flat-field map).
    "seeding_session": ["event_date", "groups"],
}


class DraftStatus(str, Enum):
    PENDING = "pending"
    AWAITING_FARMER = "awaiting_farmer"
    NEEDS_REVIEW = "needs_review"
    EXPIRED = "expired"
    # Phase 39 owns: confirmed, discarded.
    # Phase 40 owns: committed.


@dataclass
class AskBackInfo:
    ask_back: bool
    missing_fields: list[str]
    low_conf_fields: list[str]


@dataclass
class ExtractionTransition:
    next_status: str
    next_askback_turns: int
    side_effects: list[str]
    reason: str | None
    ask_back_info: AskBackInfo | None = None


def _is_field_present(draft: dict, field: str) -> bool:
    v = draft.get(field)
    if v is None:
        return False
    if isinstance(v, (list, tuple)) and len(v) == 0:
        return False
    if isinstance(v, str) and v.strip() == "":
        return False
    return True


def should_ask_back(
    draft: dict | None, per_field_confidence: dict | None, threshold: float
) -> AskBackInfo:
    """Pure -- no IO. Looks up REQUIRED_FIELDS by draft['type'] then checks both
    presence and per-field confidence.
    """
    conf = per_field_confidence or {}
    draft = draft or {}
    type_ = draft.get("type")
    required = REQUIRED_FIELDS.get(type_, [])
    missing_fields: list[str] = []
    low_conf_fields: list[str] = []

    for field in required:
        if not _is_field_present(draft, field):
            missing_fields.append(field)
            continue
        c = conf.get(field)
        if isinstance(c, (int, float)) and not isinstance(c, bool) and c < threshold:
            low_conf_fields.append(field)

    # Observation special case: state OR notes (RESEARCH section 8).
    if type_ == "observation":
        has_state = _is_field_present(draft, "state")
        has_notes = _is_field_present(draft, "notes")
        if not has_state and not has_notes:
            missing_fields.append("state_or_notes")

    # Also surface low-confidence on optional fields the LLM did emit (helps the
    # preview-builder mark them with [?] and pick a top-question).
    for field, c in conf.items():
        if field in required:
            continue
        if (
            isinstance(c, (int, float))
            and not isinstance(c, bool)
            and c < threshold
            and _is_field_present(draft, field)
        ):
            low_conf_fields.append(field)

    ask_back = len(missing_fields) > 0 or len(low_conf_fields) > 0
    return AskBackInfo(
        ask_back=ask_back, missing_fields=missing_fields, low_conf_fields=low_conf_fields
    )


def force_start_new_if_idle(prev_draft: dict | None, now_ms: int, idle_gap_min: int) -> str | None:
    """D-01a hard guard: a new message after >= idle_gap_min minutes of silence
    forces continuity_decision = 'start_new', regardless of LLM judgment.
    """
    if not prev_draft or prev_draft.get("last_updated_at_ms") is None:
        return None
    elapsed_ms = now_ms - prev_draft["last_updated_at_ms"]
    if elapsed_ms >= idle_gap_min * 60 * 1000:
        return "start_new"
    return None


def _default_noop(state: dict, reason: str) -> ExtractionTransition:
    return ExtractionTransition(
        next_status=state.get("status"),
        next_askback_turns=state.get("askback_turns") or 0,
        side_effects=["noop"],
        reason=reason,
    )


def transition(state: dict, event: dict | None) -> ExtractionTransition:
    """
    Pure FSM transition mirroring the Node extraction/state-machine.js table,
    except D-1 (see module docstring).

    state = {status, askback_turns, last_updated_at_ms}
    event = {type:'extraction_result', draft, per_field_confidence, threshold,
              max_askback_turns, now_ms}
          | {type:'farmer_replied', now_ms}
          | {type:'idle_check', now_ms, idle_gap_min}

    Pure: returns the next state shape + a side-effect tag list. The caller
    dispatches the side effects (DB writes, Signal sends).
    """
    if not event or not event.get("type"):
        return _default_noop(state, "unknown_event")

    event_type = event["type"]

    if event_type == "extraction_result":
        draft = event.get("draft")
        per_field_confidence = event.get("per_field_confidence")
        threshold = event.get("threshold")
        max_askback_turns = event.get("max_askback_turns")
        ask = should_ask_back(draft, per_field_confidence, threshold)

        if not ask.ask_back:
            return ExtractionTransition(
                next_status=DraftStatus.AWAITING_FARMER,
                next_askback_turns=state.get("askback_turns") or 0,
                side_effects=["send_confirm_prompt"],
                reason="ready_for_confirm",
                ask_back_info=ask,
            )

        # Ask-back required. Check the cap (D-05, default 3).
        # state.askback_turns counts turns already used. If we have already used
        # (max_askback_turns - 1) turns and the next extraction still asks, we are
        # at the cap -> transition to needs_review rather than burn the last turn.
        # i.e. with cap=3: askback_turns=2 + still-asking -> needs_review.
        current_turns = state.get("askback_turns") or 0
        if current_turns + 1 >= max_askback_turns:
            return ExtractionTransition(
                next_status=DraftStatus.NEEDS_REVIEW,
                next_askback_turns=current_turns,
                side_effects=["send_needs_review_ping"],
                reason="askback_cap",
                ask_back_info=ask,
            )

        return ExtractionTransition(
            next_status=DraftStatus.AWAITING_FARMER,
            next_askback_turns=current_turns + 1,
            side_effects=["send_ask_back"],
            reason="ask_back",
            ask_back_info=ask,
        )

    if event_type == "farmer_replied":
        # The caller will re-run extraction next; we just count the turn. Status
        # remains awaiting_farmer until the follow-up extraction_result lands.
        return ExtractionTransition(
            next_status=DraftStatus.AWAITING_FARMER,
            next_askback_turns=(state.get("askback_turns") or 0) + 1,
            side_effects=["noop"],
            reason="farmer_replied",
        )

    if event_type == "idle_check":
        now_ms = event.get("now_ms")
        idle_gap_min = event.get("idle_gap_min")
        active_statuses = (DraftStatus.PENDING, DraftStatus.AWAITING_FARMER)
        if state.get("status") not in active_statuses:
            return _default_noop(state, "not_active")
        elapsed_ms = now_ms - (state.get("last_updated_at_ms") or 0)
        if elapsed_ms >= idle_gap_min * 60 * 1000:
            return ExtractionTransition(
                next_status=DraftStatus.EXPIRED,
                next_askback_turns=state.get("askback_turns") or 0,
                side_effects=["mark_expired"],
                reason="idle_gap",
            )
        return _default_noop(state, "within_idle_cap")

    return _default_noop(state, "unknown_event")
