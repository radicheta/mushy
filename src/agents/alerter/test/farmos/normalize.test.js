'use strict';

// Phase 43 Plan 01: unit tests for normalize.js
// Covers common transforms, all 5 log_types, idempotency (SCHEMA-03), and non-mutation.

const { normalize } = require('../../src/farmos/commits/normalize');

// ---------------------------------------------------------------------------
// Helper: build a minimal draft envelope
// ---------------------------------------------------------------------------
function makeDraft(log_type, draft_json) {
  return { id: 'test-1', log_type, draft_json };
}

// ---------------------------------------------------------------------------
// Common transforms
// ---------------------------------------------------------------------------
describe('normalize -- common transforms', () => {
  it('event_timestamp ISO string -> timestamp unix seconds (floor)', () => {
    const draft = makeDraft('activity', {
      name: 'water',
      asset_ref: 'Q1',
      event_timestamp: '2026-05-15T14:30:00.000Z',
    });
    const out = normalize(draft).draft_json;
    expect(typeof out.timestamp).toBe('number');
    expect(out.timestamp).toBe(Math.floor(Date.parse('2026-05-15T14:30:00.000Z') / 1000));
  });

  it('event_timestamp is skipped when timestamp already a number', () => {
    const draft = makeDraft('activity', {
      timestamp: 9999999,
      event_timestamp: '2026-05-15T14:30:00.000Z',
    });
    const out = normalize(draft).draft_json;
    expect(out.timestamp).toBe(9999999);
  });

  it('asset_ref string -> qr_codes single-element array', () => {
    const draft = makeDraft('activity', { name: 'water', asset_ref: 'Q42', timestamp: 1000 });
    const out = normalize(draft).draft_json;
    expect(out.qr_codes).toEqual(['Q42']);
  });

  it('asset_ref === "<UNKNOWN>" -> qr_codes empty array', () => {
    const draft = makeDraft('activity', { name: 'water', asset_ref: '<UNKNOWN>', timestamp: 1000 });
    const out = normalize(draft).draft_json;
    expect(out.qr_codes).toEqual([]);
  });

  it('asset_ref is skipped when qr_codes already an array', () => {
    const draft = makeDraft('activity', {
      name: 'water', asset_ref: 'Q-old', qr_codes: ['Q-new'], timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.qr_codes).toEqual(['Q-new']);
  });

  it('missing both event_timestamp and numeric timestamp -> timestamp left undefined', () => {
    const draft = makeDraft('activity', { name: 'water', asset_ref: 'Q1' });
    const out = normalize(draft).draft_json;
    expect(out.timestamp).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Per-log_type transforms
// ---------------------------------------------------------------------------
describe('normalize -- activity: name -> activity_subtype', () => {
  it('name is copied to activity_subtype', () => {
    const draft = makeDraft('activity', { name: 'relocate', asset_ref: 'Q1', timestamp: 1000 });
    const out = normalize(draft).draft_json;
    expect(out.activity_subtype).toBe('relocate');
  });

  it('activity_subtype already present -> not overwritten', () => {
    const draft = makeDraft('activity', {
      name: 'water', activity_subtype: 'sterilize', qr_codes: ['Q1'], timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.activity_subtype).toBe('sterilize');
  });
});

describe('normalize -- harvest transforms', () => {
  it('source_block_refs -> source_qr_codes verbatim (no filter)', () => {
    const draft = makeDraft('harvest', {
      source_block_refs: ['260515_SHI_1', '260515_SHI_2'],
      harvest_batch_id: 'HBATCH-2026-05-15-SHI-001',
      qty_g: 120,
      timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.source_qr_codes).toEqual(['260515_SHI_1', '260515_SHI_2']);
  });

  it('harvest_batch_id -> harvest_batch_name', () => {
    const draft = makeDraft('harvest', {
      source_block_refs: ['260515_SHI_1'],
      harvest_batch_id: 'HBATCH-2026-05-15-SHI-001',
      qty_g: 100,
      timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.harvest_batch_name).toBe('HBATCH-2026-05-15-SHI-001');
  });

  it('qty_g -> bags single synthesized bag', () => {
    const draft = makeDraft('harvest', {
      source_block_refs: ['260515_SHI_1'],
      harvest_batch_id: 'HBATCH-001',
      qty_g: 250,
      timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(Array.isArray(out.bags)).toBe(true);
    expect(out.bags).toEqual([{ weight_grams: 250 }]);
  });

  it('when qty_g absent bags remains absent', () => {
    const draft = makeDraft('harvest', {
      source_block_refs: ['260515_SHI_1'],
      harvest_batch_id: 'HBATCH-001',
      timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.bags).toBeUndefined();
  });
});

describe('normalize -- seeding: species -> species_code', () => {
  it('species copied to species_code when species_code absent', () => {
    const draft = makeDraft('seeding', {
      species: 'SHI',
      block_name: '260515_SHI_1',
      qty: 5,
      timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.species_code).toBe('SHI');
  });

  it('species_code already present -> not overwritten', () => {
    const draft = makeDraft('seeding', {
      species: 'SHI',
      species_code: 'MAI',
      block_name: '260515_MAI_1',
      qty: 3,
      timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.species_code).toBe('MAI');
  });

  it('batch_name and parent_batch_name stay distinct (D-11)', () => {
    const draft = makeDraft('seeding', {
      species: 'DT',
      block_name: '260515_DT_1',
      qty: 2,
      batch_name: 'STERI-2026-05-15',
      parent_batch_name: '260510_DT_3',
      timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.batch_name).toBe('STERI-2026-05-15');
    expect(out.parent_batch_name).toBe('260510_DT_3');
  });
});

describe('normalize -- input: recipe_lot prepended to notes (D-09)', () => {
  it('recipe_lot prepended as "recipe_lot: <value>\\n" before existing notes', () => {
    const draft = makeDraft('input', {
      recipe_lot: 'RB-2026-05',
      asset_ref: 'Q1',
      notes: 'some existing notes',
      timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.notes).toBe('recipe_lot: RB-2026-05\nsome existing notes');
  });

  it('recipe_lot prepended even when notes absent', () => {
    const draft = makeDraft('input', {
      recipe_lot: 'RB-2026-05',
      asset_ref: 'Q1',
      timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.notes).toBe('recipe_lot: RB-2026-05');
  });
});

describe('normalize -- observation: state appended to notes', () => {
  it('state appended to notes as "state: <value>"', () => {
    const draft = makeDraft('observation', {
      asset_ref: 'Q1',
      state: 'pinning',
      notes: 'looking good',
      timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.notes).toBe('looking good\nstate: pinning');
  });

  it('state written to notes when notes absent', () => {
    const draft = makeDraft('observation', {
      asset_ref: 'Q1',
      state: 'contaminated',
      timestamp: 1000,
    });
    const out = normalize(draft).draft_json;
    expect(out.notes).toBe('state: contaminated');
  });
});

// ---------------------------------------------------------------------------
// Idempotency (SCHEMA-03): commit-shape input passes through byte-identical
// ---------------------------------------------------------------------------
describe('normalize -- idempotency (SCHEMA-03)', () => {
  it('activity: commit-shape draft_json passes through unchanged', () => {
    const commitShape = {
      activity_subtype: 'relocate',
      qr_codes: ['Q1'],
      timestamp: 1700000000,
      notes: 'moved to shelf 3',
    };
    const draft = makeDraft('activity', { ...commitShape });
    const out = normalize(draft).draft_json;
    expect(out).toEqual(commitShape);
  });

  it('harvest: commit-shape draft_json passes through unchanged', () => {
    const commitShape = {
      source_qr_codes: ['260515_SHI_1'],
      harvest_batch_name: 'HBATCH-2026-05-15-SHI-001',
      bags: [{ weight_grams: 200 }],
      timestamp: 1700000000,
    };
    const draft = makeDraft('harvest', { ...commitShape });
    const out = normalize(draft).draft_json;
    expect(out).toEqual(commitShape);
  });

  it('seeding: commit-shape draft_json passes through unchanged', () => {
    const commitShape = {
      species_code: 'SHI',
      block_name: '260515_SHI_1',
      qr_codes: ['260515_SHI_1'],
      qty: 5,
      timestamp: 1700000000,
    };
    const draft = makeDraft('seeding', { ...commitShape });
    const out = normalize(draft).draft_json;
    expect(out).toEqual(commitShape);
  });

  it('input: commit-shape draft_json passes through unchanged (notes already has recipe_lot prefix)', () => {
    // When recipe_lot has already been prepended, out.notes starts with "recipe_lot:"
    // so it must NOT be double-prepended. The guard: recipe_lot field must be absent or
    // already consumed. Commit-shape has no recipe_lot field separately.
    const commitShape = {
      qr_codes: ['Q1'],
      notes: 'recipe_lot: RB-2026-05\nIngredients:\n- oat 1kg',
      input_ingredients: ['oat 1kg'],
      timestamp: 1700000000,
    };
    const draft = makeDraft('input', { ...commitShape });
    const out = normalize(draft).draft_json;
    expect(out).toEqual(commitShape);
  });

  it('observation: commit-shape draft_json passes through unchanged (state already in notes)', () => {
    // When state has already been appended, out.notes ends with "\nstate: pinning"
    // The guard: state must be absent from commit-shape.
    const commitShape = {
      qr_codes: ['Q1'],
      notes: 'looking good\nstate: pinning',
      timestamp: 1700000000,
    };
    const draft = makeDraft('observation', { ...commitShape });
    const out = normalize(draft).draft_json;
    expect(out).toEqual(commitShape);
  });
});

// ---------------------------------------------------------------------------
// Non-mutation: normalize must NOT mutate input draft or draft_json
// ---------------------------------------------------------------------------
describe('normalize -- non-mutation', () => {
  it('returns a new object, not the input draft', () => {
    const draft = makeDraft('activity', { name: 'water', asset_ref: 'Q1', timestamp: 1000 });
    const result = normalize(draft);
    expect(result).not.toBe(draft);
  });

  it('input draft.draft_json is unchanged after normalize()', () => {
    const dj = { name: 'water', asset_ref: 'Q1', event_timestamp: '2026-05-15T14:30:00.000Z' };
    const draft = makeDraft('activity', dj);
    normalize(draft);
    // Original draft_json must not have been mutated
    expect(draft.draft_json).toBe(dj);
    expect(dj.qr_codes).toBeUndefined();
    expect(dj.timestamp).toBeUndefined();
    expect(dj.activity_subtype).toBeUndefined();
  });
});
