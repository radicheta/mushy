"""
100% table-parity test for the pure confirm FSM (SC-1).

Asserts the Python transition table == the Node golden table on every
(status, event, condition) case including invalid/inactive transitions.

No DB, no mocks, no asyncio -- pure function.
"""

import pytest

from farm_agent.confirm.state_machine import (
    ConfirmEvent,
    ConfirmStatus,
    Event,
    State,
    TransitionResult,
    is_terminal,
    transition,
)

# ---------------------------------------------------------------------------
# is_terminal
# ---------------------------------------------------------------------------


def test_is_terminal_confirmed():
    assert is_terminal("confirmed") is True


def test_is_terminal_discarded():
    assert is_terminal("discarded") is True


def test_is_terminal_expired():
    assert is_terminal("expired") is True


def test_is_terminal_needs_review():
    assert is_terminal("needs_review") is True


def test_is_terminal_awaiting_farmer_false():
    assert is_terminal("awaiting_farmer") is False


# ---------------------------------------------------------------------------
# Golden transition table -- full parametrized parity (SC-1)
#
# Column order: status, event_type, condition_kwargs,
#               expected_next, expected_effects, expected_reason
#
# Covers every row of the Node state-machine.js transition table verbatim,
# including all valid and invalid (inactive) transitions.
# ---------------------------------------------------------------------------

_SENTINEL_NUDGE_TIME = "2026-01-01T00:00:00Z"  # any non-None value

_TABLE = [
    # --- Row 1: dup-YES on already-confirmed (BEFORE inactive guard) ---
    (
        "confirmed",
        ConfirmEvent.FARMER_YES,
        {},
        "confirmed",
        ["send_confirm_idempotent_ack"],
        "already_confirmed",
    ),
    # --- Row 2: inactive -- discarded + farmer_no ---
    (
        "discarded",
        ConfirmEvent.FARMER_NO,
        {},
        "discarded",
        ["noop"],
        "inactive",
    ),
    # --- Row 3: inactive -- expired + farmer_yes (NOT dup-YES; status != confirmed) ---
    (
        "expired",
        ConfirmEvent.FARMER_YES,
        {},
        "expired",
        ["noop"],
        "inactive",
    ),
    # --- Row 4: inactive -- needs_review + nudge_due ---
    (
        "needs_review",
        ConfirmEvent.NUDGE_DUE,
        {},
        "needs_review",
        ["noop"],
        "inactive",
    ),
    # --- Row 5: awaiting_farmer + farmer_yes -> confirmed ---
    (
        "awaiting_farmer",
        ConfirmEvent.FARMER_YES,
        {},
        "confirmed",
        ["send_confirm_ack"],
        "farmer_yes",
    ),
    # --- Row 6: awaiting_farmer + farmer_no -> discarded ---
    (
        "awaiting_farmer",
        ConfirmEvent.FARMER_NO,
        {},
        "discarded",
        ["send_discard_ack"],
        "farmer_no",
    ),
    # --- Row 7: awaiting_farmer + farmer_edit (count=0, cap default 3) -> edit_loop ---
    (
        "awaiting_farmer",
        ConfirmEvent.FARMER_EDIT,
        {"edit_turn_count": 0},
        "awaiting_farmer",
        ["run_edit_reextraction"],
        "edit_loop",
    ),
    # --- Row 8: awaiting_farmer + farmer_edit (count=3, cap default 3) -> edit_cap_exceeded ---
    (
        "awaiting_farmer",
        ConfirmEvent.FARMER_EDIT,
        {"edit_turn_count": 3},
        "needs_review",
        ["send_edit_cap_msg"],
        "edit_cap_exceeded",
    ),
    # --- Row 9: awaiting_farmer + nudge_due (nudge_sent_at=None) -> nudge ---
    (
        "awaiting_farmer",
        ConfirmEvent.NUDGE_DUE,
        {"nudge_sent_at": None},
        "awaiting_farmer",
        ["send_nudge", "mark_nudge_sent"],
        "nudge",
    ),
    # --- Row 10: awaiting_farmer + nudge_due (nudge_sent_at set) -> already_nudged ---
    (
        "awaiting_farmer",
        ConfirmEvent.NUDGE_DUE,
        {"nudge_sent_at": _SENTINEL_NUDGE_TIME},
        "awaiting_farmer",
        ["noop"],
        "already_nudged",
    ),
    # --- Row 11: awaiting_farmer + expire_due -> timeout_expired ---
    (
        "awaiting_farmer",
        ConfirmEvent.EXPIRE_DUE,
        {},
        "expired",
        ["send_expired_note"],
        "timeout_expired",
    ),
    # --- Row 12: awaiting_farmer + superseded -> superseded_by_newer_draft ---
    (
        "awaiting_farmer",
        ConfirmEvent.SUPERSEDED,
        {},
        "expired",
        ["noop"],
        "superseded_by_newer_draft",
    ),
    # --- Row 13: unknown event (type=None) -> unknown_event ---
    (
        "awaiting_farmer",
        None,
        {},
        "awaiting_farmer",
        ["noop"],
        "unknown_event",
    ),
]

_IDS = [
    "dup_yes_on_confirmed",
    "inactive_discarded_farmer_no",
    "inactive_expired_farmer_yes",
    "inactive_needs_review_nudge_due",
    "awaiting_farmer_yes",
    "awaiting_farmer_no",
    "edit_loop_count0",
    "edit_cap_exceeded_count3",
    "nudge_sent_at_none",
    "nudge_already_sent",
    "expire_due",
    "superseded",
    "unknown_event_none",
]


@pytest.mark.parametrize(
    "status,event_type,condition_kwargs,expected_next,expected_effects,expected_reason",
    _TABLE,
    ids=_IDS,
)
def test_transition_parity(
    status,
    event_type,
    condition_kwargs,
    expected_next,
    expected_effects,
    expected_reason,
):
    state = State(status=status, **condition_kwargs)
    event = Event(type=event_type)
    result = transition(state, event)

    assert isinstance(result, TransitionResult)
    assert result.next_status == expected_next, (
        f"next_status: got {result.next_status!r}, want {expected_next!r}"
    )
    assert result.side_effects == expected_effects, (
        f"side_effects: got {result.side_effects!r}, want {expected_effects!r}"
    )
    assert result.reason == expected_reason, (
        f"reason: got {result.reason!r}, want {expected_reason!r}"
    )


# ---------------------------------------------------------------------------
# edit_loop increments next_edit_turn_count (dedicated assertion per SC-1)
# ---------------------------------------------------------------------------


def test_edit_loop_increments_turn_count():
    state = State(status="awaiting_farmer", edit_turn_count=1)
    result = transition(state, Event(type=ConfirmEvent.FARMER_EDIT))
    assert result.reason == "edit_loop"
    assert result.next_edit_turn_count == 2


def test_edit_loop_at_zero_increments_to_one():
    state = State(status="awaiting_farmer", edit_turn_count=0)
    result = transition(state, Event(type=ConfirmEvent.FARMER_EDIT))
    assert result.reason == "edit_loop"
    assert result.next_edit_turn_count == 1


def test_edit_cap_does_not_increment_turn_count():
    state = State(status="awaiting_farmer", edit_turn_count=3)
    result = transition(state, Event(type=ConfirmEvent.FARMER_EDIT))
    assert result.reason == "edit_cap_exceeded"
    assert result.next_edit_turn_count == 3  # unchanged at cap


def test_edit_cap_custom_max_edit_turns():
    """max_edit_turns passed on event overrides the default cap of 3."""
    state = State(status="awaiting_farmer", edit_turn_count=1)
    result = transition(state, Event(type=ConfirmEvent.FARMER_EDIT, max_edit_turns=1))
    assert result.reason == "edit_cap_exceeded"
    assert result.next_status == "needs_review"


def test_edit_loop_custom_cap_not_exceeded():
    state = State(status="awaiting_farmer", edit_turn_count=0)
    result = transition(state, Event(type=ConfirmEvent.FARMER_EDIT, max_edit_turns=5))
    assert result.reason == "edit_loop"
    assert result.next_edit_turn_count == 1


# ---------------------------------------------------------------------------
# Ordering rule: dup-YES fires BEFORE inactive guard
# ---------------------------------------------------------------------------


def test_dup_yes_fires_before_inactive_guard():
    """
    confirmed + farmer_yes must return already_confirmed,
    NOT inactive (which the inactive guard would return if checked first).
    """
    result = transition(
        State(status="confirmed"), Event(type=ConfirmEvent.FARMER_YES)
    )
    assert result.reason == "already_confirmed"
    assert result.next_status == "confirmed"
    assert result.side_effects == ["send_confirm_idempotent_ack"]


# ---------------------------------------------------------------------------
# Non-dup-YES on confirmed is inactive (not dup-YES path)
# ---------------------------------------------------------------------------


def test_confirmed_farmer_no_is_inactive():
    result = transition(
        State(status="confirmed"), Event(type=ConfirmEvent.FARMER_NO)
    )
    assert result.reason == "inactive"
    assert result.next_status == "confirmed"
    assert result.side_effects == ["noop"]
