'use strict';

// Phase 38 Plan 03 Task 1: validator.js unit tests.
// Covers validateDraft pass/fail + observation re-refine + buildToolResultRetry shape.

const { validateDraft, buildToolResultRetry } = require('../../src/extraction/validator');
const { Draft, ObservationLog } = require('../../src/extraction/schemas');

const validSeeding = {
  type: 'seeding',
  species: 'shiitake',
  block_name: '260512_SHI_1',
  qty: 10,
  event_timestamp: '2026-05-12T14:00:00Z',
  confidence: { species: 0.95, block_name: 0.9, qty: 1.0, event_timestamp: 0.85 },
};

describe('validator.validateDraft', () => {
  test('valid seeding -> {ok:true, draft}', () => {
    const res = validateDraft(validSeeding, Draft);
    expect(res.ok).toBe(true);
    expect(res.draft.type).toBe('seeding');
  });

  test('off-schema field -> {ok:false, reason:"schema_invalid", errors}', () => {
    const bad = { ...validSeeding, extra: 'nope' };
    const res = validateDraft(bad, Draft);
    expect(res.ok).toBe(false);
    expect(res.reason).toBe('schema_invalid');
    expect(Array.isArray(res.errors)).toBe(true);
    expect(res.errors.length).toBeGreaterThan(0);
  });

  test('missing required field -> {ok:false}', () => {
    const bad = { ...validSeeding };
    delete bad.qty;
    const res = validateDraft(bad, Draft);
    expect(res.ok).toBe(false);
    expect(res.reason).toBe('schema_invalid');
  });

  test('observation with neither state nor notes is rejected via re-applied refine', () => {
    const bareObs = {
      type: 'observation',
      asset_ref: 'block-123',
      event_timestamp: '2026-05-12T14:00:00Z',
      confidence: { asset_ref: 0.9, event_timestamp: 0.9 },
    };
    // Discriminated-union accepts the base; validator must re-apply refine.
    const res = validateDraft(bareObs, Draft);
    expect(res.ok).toBe(false);
    expect(res.reason).toBe('schema_invalid');
  });

  test('observation with notes passes', () => {
    const obs = {
      type: 'observation',
      asset_ref: 'block-123',
      notes: 'pinning visible',
      event_timestamp: '2026-05-12T14:00:00Z',
      confidence: { asset_ref: 0.9, notes: 0.9, event_timestamp: 0.9 },
    };
    const res = validateDraft(obs, Draft);
    expect(res.ok).toBe(true);
  });
});

describe('validator.buildToolResultRetry', () => {
  test('returns user-role content block with is_error:true', () => {
    const errors = [
      { path: ['qty'], message: 'Required' },
      { path: ['block_name'], message: 'B5 block_name' },
    ];
    const block = buildToolResultRetry('tu_xyz', errors);
    expect(block).toEqual({
      type: 'tool_result',
      tool_use_id: 'tu_xyz',
      is_error: true,
      content: expect.any(String),
    });
    expect(block.content).toMatch(/qty/);
    expect(block.content).toMatch(/block_name/);
  });

  test('handles empty errors gracefully', () => {
    const block = buildToolResultRetry('tu_1', []);
    expect(block.tool_use_id).toBe('tu_1');
    expect(block.is_error).toBe(true);
    expect(typeof block.content).toBe('string');
  });
});
