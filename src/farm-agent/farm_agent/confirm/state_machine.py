"""
Confirm-loop FSM -- pure transition() function.

Port of src/agents/alerter/src/confirm/state-machine.js

PURE: no DB, no I/O, no logging. side_effects are plain strings;
the caller (ReceiveLoop / watchdog) dispatches them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConfirmStatus(str, Enum):
    AWAITING_FARMER = "awaiting_farmer"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"
    EXPIRED = "expired"
    NEEDS_REVIEW = "needs_review"


class ConfirmEvent(str, Enum):
    FARMER_YES = "farmer_yes"
    FARMER_NO = "farmer_no"
    FARMER_EDIT = "farmer_edit"
    NUDGE_DUE = "nudge_due"
    EXPIRE_DUE = "expire_due"
    SUPERSEDED = "superseded"


@dataclass
class Event:
    type: ConfirmEvent | None
    max_edit_turns: int | None = None


@dataclass
class State:
    status: str
    edit_turn_count: int = 0
    nudge_sent_at: object = field(default=None)  # datetime | None


@dataclass
class TransitionResult:
    next_status: str
    next_edit_turn_count: int
    side_effects: list[str]
    reason: str


def is_terminal(status: str) -> bool:
    """Return True for the four terminal confirm states."""
    return status in (
        ConfirmStatus.CONFIRMED,
        ConfirmStatus.DISCARDED,
        ConfirmStatus.EXPIRED,
        ConfirmStatus.NEEDS_REVIEW,
    )


def _noop(state: State, reason: str) -> TransitionResult:
    return TransitionResult(
        next_status=state.status,
        next_edit_turn_count=state.edit_turn_count or 0,
        side_effects=["noop"],
        reason=reason,
    )


def transition(state: State, event: Event) -> TransitionResult:
    """
    Pure FSM transition mirroring the Node confirm/state-machine.js table verbatim.

    Ordering rule (CRITICAL):
      1. unknown/None event -> noop reason='unknown_event'
      2. dup-YES (confirmed + farmer_yes) BEFORE the inactive guard
      3. inactive guard: status != awaiting_farmer -> noop reason='inactive'
      4. awaiting_farmer branch per event type
    """
    # (1) unknown / None event
    if not event or not event.type:
        return _noop(state or State(status=None), "unknown_event")

    status = state.status
    edit_count = state.edit_turn_count or 0

    # (2) Dup-YES: confirmed + farmer_yes -> soft re-affirm (D-02 + D-02a)
    #     BEFORE the inactive guard -- this ordering is load-bearing.
    if event.type == ConfirmEvent.FARMER_YES and status == ConfirmStatus.CONFIRMED:
        return TransitionResult(
            next_status=ConfirmStatus.CONFIRMED,
            next_edit_turn_count=edit_count,
            side_effects=["send_confirm_idempotent_ack"],
            reason="already_confirmed",
        )

    # (3) Inactive guard: anything else when not awaiting_farmer
    if status != ConfirmStatus.AWAITING_FARMER:
        return _noop(state, "inactive")

    # (4) awaiting_farmer branch
    if event.type == ConfirmEvent.FARMER_YES:
        return TransitionResult(
            next_status=ConfirmStatus.CONFIRMED,
            next_edit_turn_count=edit_count,
            side_effects=["send_confirm_ack"],
            reason="farmer_yes",
        )

    if event.type == ConfirmEvent.FARMER_NO:
        return TransitionResult(
            next_status=ConfirmStatus.DISCARDED,
            next_edit_turn_count=edit_count,
            side_effects=["send_discard_ack"],
            reason="farmer_no",
        )

    if event.type == ConfirmEvent.FARMER_EDIT:
        cap = event.max_edit_turns if event.max_edit_turns is not None else 3
        if edit_count >= cap:
            return TransitionResult(
                next_status=ConfirmStatus.NEEDS_REVIEW,
                next_edit_turn_count=edit_count,
                side_effects=["send_edit_cap_msg"],
                reason="edit_cap_exceeded",
            )
        return TransitionResult(
            next_status=ConfirmStatus.AWAITING_FARMER,
            next_edit_turn_count=edit_count + 1,
            side_effects=["run_edit_reextraction"],
            reason="edit_loop",
        )

    if event.type == ConfirmEvent.NUDGE_DUE:
        if state.nudge_sent_at is not None:
            return TransitionResult(
                next_status=ConfirmStatus.AWAITING_FARMER,
                next_edit_turn_count=edit_count,
                side_effects=["noop"],
                reason="already_nudged",
            )
        return TransitionResult(
            next_status=ConfirmStatus.AWAITING_FARMER,
            next_edit_turn_count=edit_count,
            side_effects=["send_nudge", "mark_nudge_sent"],
            reason="nudge",
        )

    if event.type == ConfirmEvent.EXPIRE_DUE:
        return TransitionResult(
            next_status=ConfirmStatus.EXPIRED,
            next_edit_turn_count=edit_count,
            side_effects=["send_expired_note"],
            reason="timeout_expired",
        )

    if event.type == ConfirmEvent.SUPERSEDED:
        return TransitionResult(
            next_status=ConfirmStatus.EXPIRED,
            next_edit_turn_count=edit_count,
            side_effects=["noop"],
            reason="superseded_by_newer_draft",
        )

    # Unknown event type (recognized enum string not matched above)
    return _noop(state, "unknown_event")
