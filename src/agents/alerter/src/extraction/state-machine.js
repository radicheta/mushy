'use strict';

// Phase 38 Plan 04 Task 2: pure state-machine for extraction draft lifecycle.
//
// Honors:
//   D-01a -- 30min idle cap forces start_new (forceStartNewIfIdle helper).
//   D-02b -- status enum: pending / awaiting_farmer / needs_review / expired.
//            (Phase 38 owns these four; Phase 39 owns confirmed/discarded.)
//   D-03  -- ask-back trigger on missing-required OR per-field confidence below
//            threshold.
//   D-05  -- hard cap on ask-back turns (default 3) before status -> needs_review.
//
// PURE: no DB, no IO, no logging side effects. All effects are returned as
// strings in side_effects for the caller (Plan 05) to dispatch against
// signal_draft + signal.js.
//
// Farmer-facing text lives in preview-builder.js -- this module emits only
// side-effect names + reasons.

// Required-field map per RESEARCH.md section 8.
// observation special case: state OR notes required (handled inline in
// shouldAskBack as the synthetic 'state_or_notes' marker).
const REQUIRED_FIELDS = Object.freeze({
  seeding:     ['species', 'block_name', 'qty', 'event_timestamp'],
  activity:    ['name', 'asset_ref', 'event_timestamp'],
  input:       ['recipe_lot', 'asset_ref', 'event_timestamp'],
  observation: ['asset_ref', 'event_timestamp'],
  harvest:     ['harvest_batch_id', 'source_block_refs', 'qty_g', 'event_timestamp'],
});

const DRAFT_STATUS = Object.freeze({
  PENDING:         'pending',
  AWAITING_FARMER: 'awaiting_farmer',
  NEEDS_REVIEW:    'needs_review',
  EXPIRED:         'expired',
  // Phase 39 owns: confirmed, discarded.
  // Phase 40 owns: committed.
});

function isFieldPresent(draft, field) {
  const v = draft[field];
  if (v == null) return false;
  if (Array.isArray(v) && v.length === 0) return false;
  if (typeof v === 'string' && v.trim() === '') return false;
  return true;
}

/**
 * shouldAskBack(draft, perFieldConfidence, threshold) -> {
 *   askBack: boolean,
 *   missingFields: string[],
 *   lowConfFields: string[],
 * }
 *
 * Pure -- no IO. Looks up REQUIRED_FIELDS by draft.type then checks both
 * presence and per-field confidence.
 */
function shouldAskBack(draft, perFieldConfidence, threshold) {
  const conf = perFieldConfidence || {};
  const type = draft && draft.type;
  const required = REQUIRED_FIELDS[type] || [];
  const missingFields = [];
  const lowConfFields = [];

  for (const field of required) {
    if (!isFieldPresent(draft, field)) {
      missingFields.push(field);
      continue;
    }
    if (typeof conf[field] === 'number' && conf[field] < threshold) {
      lowConfFields.push(field);
    }
  }

  // Observation special case: state OR notes (RESEARCH section 8).
  if (type === 'observation') {
    const hasState = isFieldPresent(draft, 'state');
    const hasNotes = isFieldPresent(draft, 'notes');
    if (!hasState && !hasNotes) {
      missingFields.push('state_or_notes');
    }
  }

  // Also surface low-confidence on optional fields the LLM did emit (helps the
  // preview-builder mark them with [?] and pick a top-question).
  for (const [field, c] of Object.entries(conf)) {
    if (required.includes(field)) continue;
    if (typeof c === 'number' && c < threshold && isFieldPresent(draft, field)) {
      lowConfFields.push(field);
    }
  }

  const askBack = missingFields.length > 0 || lowConfFields.length > 0;
  return { askBack, missingFields, lowConfFields };
}

/**
 * forceStartNewIfIdle(prevDraft, nowMs, idleGapMin) -> 'start_new' | null
 *
 * D-01a hard guard: a new message after >= idleGapMin minutes of silence
 * forces continuity_decision = 'start_new', regardless of LLM judgment.
 */
function forceStartNewIfIdle(prevDraft, nowMs, idleGapMin) {
  if (!prevDraft || prevDraft.last_updated_at_ms == null) return null;
  const elapsedMs = nowMs - prevDraft.last_updated_at_ms;
  if (elapsedMs >= idleGapMin * 60 * 1000) return 'start_new';
  return null;
}

/**
 * transition(state, event) -> {
 *   nextStatus,
 *   nextAskbackTurns,
 *   side_effects: string[],
 *   reason: string|null,
 *   askBackInfo?: {missingFields, lowConfFields},
 * }
 *
 * state = {status, askback_turns, last_updated_at_ms}
 * event = {type:'extraction_result', draft, perFieldConfidence, threshold, maxAskbackTurns, now_ms}
 *       | {type:'farmer_replied', now_ms}
 *       | {type:'idle_check', now_ms, idleGapMin}
 *
 * Pure: returns the next state shape + a side-effect tag list. The caller
 * dispatches the side effects (DB writes, Signal sends).
 */
function transition(state, event) {
  if (!event || !event.type) {
    return defaultNoop(state, 'unknown_event');
  }

  if (event.type === 'extraction_result') {
    const { draft, perFieldConfidence, threshold, maxAskbackTurns } = event;
    const ask = shouldAskBack(draft, perFieldConfidence, threshold);

    if (!ask.askBack) {
      return {
        nextStatus: DRAFT_STATUS.AWAITING_FARMER,
        nextAskbackTurns: state.askback_turns || 0,
        side_effects: ['handoff_to_phase_39'],
        reason: 'ready_for_confirm',
        askBackInfo: ask,
      };
    }

    // Ask-back required. Check the cap (D-05, default 3).
    // state.askback_turns counts turns already used. If we have already used
    // (maxAskbackTurns - 1) turns and the next extraction still asks, we are
    // at the cap -> transition to needs_review rather than burn the last turn.
    // i.e. with cap=3: askback_turns=2 + still-asking -> needs_review.
    const currentTurns = state.askback_turns || 0;
    if (currentTurns + 1 >= maxAskbackTurns) {
      return {
        nextStatus: DRAFT_STATUS.NEEDS_REVIEW,
        nextAskbackTurns: currentTurns,
        side_effects: ['send_needs_review_ping'],
        reason: 'askback_cap',
        askBackInfo: ask,
      };
    }

    return {
      nextStatus: DRAFT_STATUS.AWAITING_FARMER,
      nextAskbackTurns: currentTurns + 1,
      side_effects: ['send_ask_back'],
      reason: 'ask_back',
      askBackInfo: ask,
    };
  }

  if (event.type === 'farmer_replied') {
    // The caller will re-run extraction next; we just count the turn. Status
    // remains awaiting_farmer until the follow-up extraction_result lands.
    return {
      nextStatus: DRAFT_STATUS.AWAITING_FARMER,
      nextAskbackTurns: (state.askback_turns || 0) + 1,
      side_effects: ['noop'],
      reason: 'farmer_replied',
    };
  }

  if (event.type === 'idle_check') {
    const { now_ms, idleGapMin } = event;
    const activeStatuses = [DRAFT_STATUS.PENDING, DRAFT_STATUS.AWAITING_FARMER];
    if (!activeStatuses.includes(state.status)) {
      return defaultNoop(state, 'not_active');
    }
    const elapsedMs = now_ms - (state.last_updated_at_ms || 0);
    if (elapsedMs >= idleGapMin * 60 * 1000) {
      return {
        nextStatus: DRAFT_STATUS.EXPIRED,
        nextAskbackTurns: state.askback_turns || 0,
        side_effects: ['mark_expired'],
        reason: 'idle_gap',
      };
    }
    return defaultNoop(state, 'within_idle_cap');
  }

  return defaultNoop(state, 'unknown_event');
}

function defaultNoop(state, reason) {
  return {
    nextStatus: state.status,
    nextAskbackTurns: state.askback_turns || 0,
    side_effects: ['noop'],
    reason,
  };
}

module.exports = {
  transition,
  shouldAskBack,
  forceStartNewIfIdle,
  DRAFT_STATUS,
  REQUIRED_FIELDS,
};
