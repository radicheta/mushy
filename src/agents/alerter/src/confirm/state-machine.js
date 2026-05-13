'use strict';

// Phase 39 D-01..D-04d: confirm-loop FSM.
//
// transition(state, event) -> {nextStatus, nextEditTurnCount, side_effects[], reason}
//
// PURE: no DB, no IO, no logging. Side-effect names are dispatched by Plan 06.

const CONFIRM_STATUS = Object.freeze({
  AWAITING_FARMER: 'awaiting_farmer',
  CONFIRMED: 'confirmed',
  DISCARDED: 'discarded',
  EXPIRED: 'expired',
  NEEDS_REVIEW: 'needs_review',
});

const CONFIRM_EVENTS = Object.freeze({
  FARMER_YES: 'farmer_yes',
  FARMER_NO: 'farmer_no',
  FARMER_EDIT: 'farmer_edit',
  NUDGE_DUE: 'nudge_due',
  EXPIRE_DUE: 'expire_due',
  SUPERSEDED: 'superseded',
});

function isTerminal(status) {
  return (
    status === CONFIRM_STATUS.CONFIRMED ||
    status === CONFIRM_STATUS.DISCARDED ||
    status === CONFIRM_STATUS.EXPIRED ||
    status === CONFIRM_STATUS.NEEDS_REVIEW
  );
}

function _noop(state, reason) {
  return {
    nextStatus: state.status,
    nextEditTurnCount: state.edit_turn_count || 0,
    side_effects: ['noop'],
    reason,
  };
}

function transition(state, event) {
  if (!state || !event || !event.type) {
    return _noop(state || { status: null, edit_turn_count: 0 }, 'unknown_event');
  }

  const status = state.status;
  const editCount = state.edit_turn_count || 0;

  // Duplicate YES on already-confirmed -> soft re-affirm (D-02 + D-02a).
  if (event.type === CONFIRM_EVENTS.FARMER_YES && status === CONFIRM_STATUS.CONFIRMED) {
    return {
      nextStatus: CONFIRM_STATUS.CONFIRMED,
      nextEditTurnCount: editCount,
      side_effects: ['send_confirm_idempotent_ack'],
      reason: 'already_confirmed',
    };
  }

  // Anything else when not awaiting_farmer is inactive.
  if (status !== CONFIRM_STATUS.AWAITING_FARMER) {
    return _noop(state, 'inactive');
  }

  switch (event.type) {
    case CONFIRM_EVENTS.FARMER_YES:
      return {
        nextStatus: CONFIRM_STATUS.CONFIRMED,
        nextEditTurnCount: editCount,
        side_effects: ['send_confirm_ack'],
        reason: 'farmer_yes',
      };

    case CONFIRM_EVENTS.FARMER_NO:
      return {
        nextStatus: CONFIRM_STATUS.DISCARDED,
        nextEditTurnCount: editCount,
        side_effects: ['send_discard_ack'],
        reason: 'farmer_no',
      };

    case CONFIRM_EVENTS.FARMER_EDIT: {
      const cap = (event.maxEditTurns != null) ? event.maxEditTurns : 3;
      if (editCount >= cap) {
        return {
          nextStatus: CONFIRM_STATUS.NEEDS_REVIEW,
          nextEditTurnCount: editCount,
          side_effects: ['send_edit_cap_msg'],
          reason: 'edit_cap_exceeded',
        };
      }
      return {
        nextStatus: CONFIRM_STATUS.AWAITING_FARMER,
        nextEditTurnCount: editCount + 1,
        side_effects: ['run_edit_reextraction'],
        reason: 'edit_loop',
      };
    }

    case CONFIRM_EVENTS.NUDGE_DUE:
      if (state.nudge_sent_at != null) {
        return {
          nextStatus: CONFIRM_STATUS.AWAITING_FARMER,
          nextEditTurnCount: editCount,
          side_effects: ['noop'],
          reason: 'already_nudged',
        };
      }
      return {
        nextStatus: CONFIRM_STATUS.AWAITING_FARMER,
        nextEditTurnCount: editCount,
        side_effects: ['send_nudge', 'mark_nudge_sent'],
        reason: 'nudge',
      };

    case CONFIRM_EVENTS.EXPIRE_DUE:
      return {
        nextStatus: CONFIRM_STATUS.EXPIRED,
        nextEditTurnCount: editCount,
        side_effects: ['send_expired_note'],
        reason: 'timeout_expired',
      };

    case CONFIRM_EVENTS.SUPERSEDED:
      return {
        nextStatus: CONFIRM_STATUS.EXPIRED,
        nextEditTurnCount: editCount,
        side_effects: ['noop'],
        reason: 'superseded_by_newer_draft',
      };

    default:
      return _noop(state, 'unknown_event');
  }
}

module.exports = {
  transition,
  isTerminal,
  CONFIRM_STATUS,
  CONFIRM_EVENTS,
};
