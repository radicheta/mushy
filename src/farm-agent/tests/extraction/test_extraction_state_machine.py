"""100% transition-table parity for the extraction FSM. Pure: no DB, no mocks."""

import pytest

from farm_agent.extraction.state_machine import (
    DraftStatus,
    force_start_new_if_idle,
    should_ask_back,
    transition,
)

CLEAN_HARVEST = {
    "type": "harvest",
    "harvest_batch_id": "H1",
    "source_block_refs": ["b1"],
    "qty_g": 500,
    "event_timestamp": "2026-05-22T10:00:00Z",
}


def test_should_ask_back_clean_draft():
    r = should_ask_back(CLEAN_HARVEST, {}, 0.7)
    assert r.ask_back is False
    assert r.missing_fields == []
    assert r.low_conf_fields == []


def test_should_ask_back_missing_required():
    draft = dict(CLEAN_HARVEST)
    del draft["qty_g"]
    r = should_ask_back(draft, {}, 0.7)
    assert r.ask_back is True
    assert "qty_g" in r.missing_fields


@pytest.mark.parametrize("value", [None, [], "", "   "])
def test_field_presence_rules(value):
    draft = dict(CLEAN_HARVEST, source_block_refs=value)
    r = should_ask_back(draft, {}, 0.7)
    assert "source_block_refs" in r.missing_fields


def test_low_confidence_required_field_is_flagged_not_missing():
    r = should_ask_back(CLEAN_HARVEST, {"qty_g": 0.4}, 0.7)
    assert r.ask_back is True
    assert r.low_conf_fields == ["qty_g"]
    assert r.missing_fields == []


def test_low_confidence_optional_present_field_is_flagged():
    # Optional fields the LLM emitted below threshold surface too, so the
    # preview-builder can mark them [?]. state-machine.js:90-95.
    draft = dict(CLEAN_HARVEST, notes="maybe")
    r = should_ask_back(draft, {"notes": 0.2}, 0.7)
    assert "notes" in r.low_conf_fields


def test_low_confidence_absent_field_is_not_flagged():
    r = should_ask_back(CLEAN_HARVEST, {"notes": 0.2}, 0.7)
    assert "notes" not in r.low_conf_fields


def test_observation_state_or_notes_marker():
    draft = {"type": "observation", "asset_ref": "a1", "event_timestamp": "t"}
    r = should_ask_back(draft, {}, 0.7)
    assert "state_or_notes" in r.missing_fields


def test_observation_notes_alone_satisfies():
    draft = {"type": "observation", "asset_ref": "a1", "event_timestamp": "t", "notes": "n"}
    r = should_ask_back(draft, {}, 0.7)
    assert r.ask_back is False


def test_unknown_type_has_no_required_fields():
    r = should_ask_back({"type": "nonsense"}, {}, 0.7)
    assert r.ask_back is False


# --- force_start_new_if_idle -------------------------------------------------


def test_force_start_new_none_when_no_prior():
    assert force_start_new_if_idle(None, 1_000_000, 30) is None


def test_force_start_new_none_when_no_timestamp():
    assert force_start_new_if_idle({"last_updated_at_ms": None}, 1_000_000, 30) is None


def test_force_start_new_at_exactly_the_gap():
    now = 30 * 60 * 1000
    assert force_start_new_if_idle({"last_updated_at_ms": 0}, now, 30) == "start_new"


def test_force_start_new_none_just_under_the_gap():
    now = 30 * 60 * 1000 - 1
    assert force_start_new_if_idle({"last_updated_at_ms": 0}, now, 30) is None


# --- transition --------------------------------------------------------------


def _extraction_event(draft, conf=None, threshold=0.7, cap=3, now_ms=0):
    return {
        "type": "extraction_result", "draft": draft,
        "per_field_confidence": conf or {}, "threshold": threshold,
        "max_askback_turns": cap, "now_ms": now_ms,
    }


def test_clean_extraction_asks_the_farmer_to_confirm():
    """D-1: Node emits handoff_to_phase_39 here, which no-sends, so the farmer is
    never told a clean draft is waiting. We emit send_confirm_prompt instead."""
    t = transition({"status": "pending", "askback_turns": 0}, _extraction_event(CLEAN_HARVEST))
    assert t.next_status == DraftStatus.AWAITING_FARMER
    assert t.side_effects == ["send_confirm_prompt"]
    assert t.reason == "ready_for_confirm"
    assert t.next_askback_turns == 0


def test_handoff_to_phase_39_is_never_emitted():
    t = transition({"status": "pending", "askback_turns": 0}, _extraction_event(CLEAN_HARVEST))
    assert "handoff_to_phase_39" not in t.side_effects


def test_dirty_extraction_asks_back_and_increments():
    draft = dict(CLEAN_HARVEST)
    del draft["qty_g"]
    t = transition({"status": "pending", "askback_turns": 0}, _extraction_event(draft))
    assert t.next_status == DraftStatus.AWAITING_FARMER
    assert t.side_effects == ["send_ask_back"]
    assert t.reason == "ask_back"
    assert t.next_askback_turns == 1


def test_askback_cap_reached_goes_needs_review_without_burning_last_turn():
    draft = dict(CLEAN_HARVEST)
    del draft["qty_g"]
    t = transition({"status": "pending", "askback_turns": 2}, _extraction_event(draft, cap=3))
    assert t.next_status == DraftStatus.NEEDS_REVIEW
    assert t.side_effects == ["send_needs_review_ping"]
    assert t.reason == "askback_cap"
    assert t.next_askback_turns == 2


def test_farmer_replied_counts_the_turn_only():
    t = transition({"status": "awaiting_farmer", "askback_turns": 1},
                   {"type": "farmer_replied", "now_ms": 0})
    assert t.next_status == DraftStatus.AWAITING_FARMER
    assert t.next_askback_turns == 2
    assert t.side_effects == ["noop"]


def test_idle_check_expires_active_draft():
    t = transition({"status": "pending", "askback_turns": 0, "last_updated_at_ms": 0},
                   {"type": "idle_check", "now_ms": 30 * 60 * 1000, "idle_gap_min": 30})
    assert t.next_status == DraftStatus.EXPIRED
    assert t.side_effects == ["mark_expired"]
    assert t.reason == "idle_gap"


def test_idle_check_noop_within_cap():
    t = transition({"status": "pending", "askback_turns": 0, "last_updated_at_ms": 0},
                   {"type": "idle_check", "now_ms": 60_000, "idle_gap_min": 30})
    assert t.side_effects == ["noop"]
    assert t.reason == "within_idle_cap"


def test_idle_check_noop_on_inactive_status():
    t = transition({"status": "expired", "askback_turns": 0, "last_updated_at_ms": 0},
                   {"type": "idle_check", "now_ms": 10**12, "idle_gap_min": 30})
    assert t.next_status == "expired"
    assert t.reason == "not_active"


@pytest.mark.parametrize("event", [None, {}, {"type": "bogus"}])
def test_unknown_event_is_noop_preserving_state(event):
    t = transition({"status": "pending", "askback_turns": 4}, event)
    assert t.next_status == "pending"
    assert t.next_askback_turns == 4
    assert t.side_effects == ["noop"]
    assert t.reason == "unknown_event"
