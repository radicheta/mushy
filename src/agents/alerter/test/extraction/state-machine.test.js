'use strict';

// Phase 38 Plan 04 Task 2: pure state-machine for extraction draft lifecycle.
// CONTEXT D-01a (idle cap), D-02b (status enum), D-03 (confidence threshold),
// D-05 (3-turn cap). No DB, no IO -- all side effects returned as strings for
// the caller (Plan 05) to dispatch.

const sm = require('../../src/extraction/state-machine');
const { transition, shouldAskBack, forceStartNewIfIdle, DRAFT_STATUS, REQUIRED_FIELDS } = sm;

const THRESHOLD = 0.7;
const IDLE_MIN = 30;
const MAX_TURNS = 3;

// ---- shouldAskBack ----

describe('shouldAskBack', () => {
  test('seeding missing block_name -> askBack:true, missingFields:[block_name]', () => {
    const draft = { type: 'seeding', species: 'SHI', qty: 10, event_timestamp: '2026-05-12T10:00:00Z' };
    const conf = { species: 0.9, qty: 0.95, event_timestamp: 0.9 };
    const res = shouldAskBack(draft, conf, THRESHOLD);
    expect(res.askBack).toBe(true);
    expect(res.missingFields).toContain('block_name');
  });

  test('seeding all present + all confidence >= 0.7 -> askBack:false', () => {
    const draft = {
      type: 'seeding', species: 'SHI', block_name: '260512_SHI_4',
      qty: 10, event_timestamp: '2026-05-12T10:00:00Z',
    };
    const conf = { species: 0.9, block_name: 0.85, qty: 0.95, event_timestamp: 0.9 };
    const res = shouldAskBack(draft, conf, THRESHOLD);
    expect(res.askBack).toBe(false);
  });

  test('species confidence 0.5 with threshold 0.7 -> askBack:true, lowConfFields:[species]', () => {
    const draft = {
      type: 'seeding', species: 'SHI', block_name: '260512_SHI_4',
      qty: 10, event_timestamp: '2026-05-12T10:00:00Z',
    };
    const conf = { species: 0.5, block_name: 0.85, qty: 0.95, event_timestamp: 0.9 };
    const res = shouldAskBack(draft, conf, THRESHOLD);
    expect(res.askBack).toBe(true);
    expect(res.lowConfFields).toContain('species');
  });

  test('observation with neither state nor notes -> askBack:true', () => {
    const draft = {
      type: 'observation', asset_ref: 'block-1',
      event_timestamp: '2026-05-12T10:00:00Z',
    };
    const conf = { asset_ref: 0.9, event_timestamp: 0.9 };
    const res = shouldAskBack(draft, conf, THRESHOLD);
    expect(res.askBack).toBe(true);
    expect(res.missingFields).toEqual(expect.arrayContaining(['state_or_notes']));
  });

  test('observation with state present -> askBack:false', () => {
    const draft = {
      type: 'observation', asset_ref: 'block-1',
      state: 'pinning', event_timestamp: '2026-05-12T10:00:00Z',
    };
    const conf = { asset_ref: 0.9, state: 0.9, event_timestamp: 0.9 };
    const res = shouldAskBack(draft, conf, THRESHOLD);
    expect(res.askBack).toBe(false);
  });

  test('harvest source_block_refs empty -> askBack:true', () => {
    const draft = {
      type: 'harvest', harvest_batch_id: 'H-1', source_block_refs: [],
      qty_g: 1500, event_timestamp: '2026-05-12T10:00:00Z',
    };
    const conf = {
      harvest_batch_id: 0.9, source_block_refs: 0.9,
      qty_g: 0.9, event_timestamp: 0.9,
    };
    const res = shouldAskBack(draft, conf, THRESHOLD);
    expect(res.askBack).toBe(true);
    expect(res.missingFields).toContain('source_block_refs');
  });
});

// ---- transition ----

describe('transition', () => {
  const baseState = {
    status: DRAFT_STATUS.PENDING,
    askback_turns: 0,
    last_updated_at_ms: 1000,
  };

  test('extraction_result with askBack=true -> AWAITING_FARMER + send_ask_back', () => {
    const event = {
      type: 'extraction_result',
      draft: { type: 'seeding', species: 'SHI', qty: 10, event_timestamp: '2026-05-12T10:00:00Z' },
      perFieldConfidence: { species: 0.9, qty: 0.95, event_timestamp: 0.9 },
      threshold: THRESHOLD,
      maxAskbackTurns: MAX_TURNS,
      now_ms: 2000,
    };
    const res = transition(baseState, event);
    expect(res.nextStatus).toBe(DRAFT_STATUS.AWAITING_FARMER);
    expect(res.side_effects).toContain('send_ask_back');
  });

  test('extraction_result with askBack=false -> AWAITING_FARMER + handoff_to_phase_39', () => {
    const event = {
      type: 'extraction_result',
      draft: {
        type: 'seeding', species: 'SHI', block_name: '260512_SHI_4',
        qty: 10, event_timestamp: '2026-05-12T10:00:00Z',
      },
      perFieldConfidence: { species: 0.9, block_name: 0.9, qty: 0.95, event_timestamp: 0.9 },
      threshold: THRESHOLD,
      maxAskbackTurns: MAX_TURNS,
      now_ms: 2000,
    };
    const res = transition(baseState, event);
    expect(res.nextStatus).toBe(DRAFT_STATUS.AWAITING_FARMER);
    expect(res.side_effects).toContain('handoff_to_phase_39');
  });

  test('3-turn cap: state.askback_turns=2 + extraction-still-askBack -> NEEDS_REVIEW', () => {
    const state = { ...baseState, status: DRAFT_STATUS.AWAITING_FARMER, askback_turns: 2 };
    const event = {
      type: 'extraction_result',
      draft: { type: 'seeding', species: 'SHI', qty: 10, event_timestamp: '2026-05-12T10:00:00Z' },
      perFieldConfidence: { species: 0.9, qty: 0.95, event_timestamp: 0.9 },
      threshold: THRESHOLD,
      maxAskbackTurns: MAX_TURNS,
      now_ms: 2000,
    };
    const res = transition(state, event);
    expect(res.nextStatus).toBe(DRAFT_STATUS.NEEDS_REVIEW);
    expect(res.side_effects).toContain('send_needs_review_ping');
    expect(res.reason).toBe('askback_cap');
  });

  test('idle_check after 31min -> EXPIRED + mark_expired', () => {
    const state = { ...baseState, status: DRAFT_STATUS.AWAITING_FARMER, last_updated_at_ms: 0 };
    const event = { type: 'idle_check', now_ms: 31 * 60 * 1000 + 1, idleGapMin: IDLE_MIN };
    const res = transition(state, event);
    expect(res.nextStatus).toBe(DRAFT_STATUS.EXPIRED);
    expect(res.side_effects).toContain('mark_expired');
    expect(res.reason).toBe('idle_gap');
  });

  test('idle_check after 29min -> noop', () => {
    const state = { ...baseState, status: DRAFT_STATUS.AWAITING_FARMER, last_updated_at_ms: 0 };
    const event = { type: 'idle_check', now_ms: 29 * 60 * 1000, idleGapMin: IDLE_MIN };
    const res = transition(state, event);
    expect(res.side_effects).toEqual(['noop']);
  });

  test('idle_check on already-expired status -> noop', () => {
    const state = { ...baseState, status: DRAFT_STATUS.EXPIRED, last_updated_at_ms: 0 };
    const event = { type: 'idle_check', now_ms: 999999999, idleGapMin: IDLE_MIN };
    const res = transition(state, event);
    expect(res.side_effects).toEqual(['noop']);
  });

  test('farmer_replied increments askback_turns', () => {
    const state = { ...baseState, status: DRAFT_STATUS.AWAITING_FARMER, askback_turns: 1 };
    const event = { type: 'farmer_replied', now_ms: 2000 };
    const res = transition(state, event);
    expect(res.nextAskbackTurns).toBe(2);
    expect(res.nextStatus).toBe(DRAFT_STATUS.AWAITING_FARMER);
  });
});

// ---- forceStartNewIfIdle ----

describe('forceStartNewIfIdle', () => {
  test('returns start_new beyond idle cap', () => {
    const prev = { last_updated_at_ms: 0 };
    expect(forceStartNewIfIdle(prev, 31 * 60 * 1000 + 1, IDLE_MIN)).toBe('start_new');
  });

  test('returns null within cap', () => {
    const prev = { last_updated_at_ms: 0 };
    expect(forceStartNewIfIdle(prev, 29 * 60 * 1000, IDLE_MIN)).toBeNull();
  });

  test('returns null when prevDraft is null', () => {
    expect(forceStartNewIfIdle(null, 999, IDLE_MIN)).toBeNull();
  });
});

// ---- enum + purity ----

describe('DRAFT_STATUS', () => {
  test('frozen object', () => {
    expect(Object.isFrozen(DRAFT_STATUS)).toBe(true);
  });

  test('has the 4 Phase-38-owned states', () => {
    expect(DRAFT_STATUS.PENDING).toBe('pending');
    expect(DRAFT_STATUS.AWAITING_FARMER).toBe('awaiting_farmer');
    expect(DRAFT_STATUS.NEEDS_REVIEW).toBe('needs_review');
    expect(DRAFT_STATUS.EXPIRED).toBe('expired');
  });
});

describe('REQUIRED_FIELDS', () => {
  test('seeding requires species/block_name/qty/event_timestamp', () => {
    expect(REQUIRED_FIELDS.seeding).toEqual(
      expect.arrayContaining(['species', 'block_name', 'qty', 'event_timestamp']),
    );
  });

  test('harvest requires harvest_batch_id/source_block_refs/qty_g/event_timestamp', () => {
    expect(REQUIRED_FIELDS.harvest).toEqual(
      expect.arrayContaining(['harvest_batch_id', 'source_block_refs', 'qty_g', 'event_timestamp']),
    );
  });
});
