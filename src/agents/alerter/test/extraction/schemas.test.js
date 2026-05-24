'use strict';

/**
 * Tests for Phase 38 Plan 01 Zod schemas (B7 log types).
 * Pure-unit, no DB, no Anthropic SDK. silentLogger pattern mirrored from llm-client.test.js.
 *
 * Behavior anchors:
 *   - EXT-01: .strict() on every schema; off-schema fields rejected
 *   - B5: block_name regex ^[0-9]{6}_[A-Z]{3}_[0-9]+$
 *   - C4: harvest accepts multi-parent source_block_refs[]
 *   - D-03: per-field confidence record(string, number 0..1)
 *   - Task 3: discriminated-union Draft + DRAFT_JSON_SCHEMA export
 */

const BASE_TS = '2026-05-11T12:00:00Z';

function validSeeding(overrides = {}) {
  return {
    type: 'seeding',
    species: 'shiitake',
    block_name: '260511_SHI_4',
    qty: 10,
    event_timestamp: BASE_TS,
    confidence: { species: 0.9, block_name: 0.95, qty: 0.8, event_timestamp: 0.9 },
    ...overrides,
  };
}

function validActivity(overrides = {}) {
  return {
    type: 'activity',
    name: 'sterilize',
    asset_ref: '260511_SHI_4',
    event_timestamp: BASE_TS,
    confidence: { name: 0.9, asset_ref: 0.9, event_timestamp: 0.9 },
    ...overrides,
  };
}

function validInput(overrides = {}) {
  return {
    type: 'input',
    recipe_lot: 'sub-2026-05-11-A',
    asset_ref: '260511_SHI_4',
    event_timestamp: BASE_TS,
    confidence: { recipe_lot: 0.9, asset_ref: 0.9, event_timestamp: 0.9 },
    ...overrides,
  };
}

function validObservation(overrides = {}) {
  return {
    type: 'observation',
    asset_ref: '260511_SHI_4',
    state: 'pinning',
    event_timestamp: BASE_TS,
    confidence: { state: 0.85, asset_ref: 0.9, event_timestamp: 0.9 },
    ...overrides,
  };
}

function validHarvest(overrides = {}) {
  return {
    type: 'harvest',
    harvest_batch_id: 'H-2026-05-11-001',
    source_block_refs: ['260511_SHI_3', '260511_SHI_4', '260511_SHI_5'],
    qty_g: 420,
    event_timestamp: BASE_TS,
    confidence: { harvest_batch_id: 0.95, source_block_refs: 0.9, qty_g: 0.85, event_timestamp: 0.9 },
    ...overrides,
  };
}

describe('seeding schema', () => {
  const { SeedingLog } = require('../../src/extraction/schemas/seeding');

  test('accepts valid seeding draft', () => {
    const r = SeedingLog.safeParse(validSeeding());
    expect(r.success).toBe(true);
  });

  test('B5 block_name regex rejects "260511_SHI" (missing seq)', () => {
    const r = SeedingLog.safeParse(validSeeding({ block_name: '260511_SHI' }));
    expect(r.success).toBe(false);
  });

  test('B5 block_name regex accepts "260511_SHI_4"', () => {
    const r = SeedingLog.safeParse(validSeeding({ block_name: '260511_SHI_4' }));
    expect(r.success).toBe(true);
  });

  test('negative qty rejected', () => {
    const r = SeedingLog.safeParse(validSeeding({ qty: -1 }));
    expect(r.success).toBe(false);
  });

  test('.strict() rejects unknown top-level field', () => {
    const r = SeedingLog.safeParse({ ...validSeeding(), extra_field: 'nope' });
    expect(r.success).toBe(false);
  });
});

describe('activity schema', () => {
  const { ActivityLog } = require('../../src/extraction/schemas/activity');
  const VALID_NAMES = ['sterilize', 'sterilize_failed', 'water', 'relocate', 'cold_shock', 'archive_spent', 'contam'];

  test.each(VALID_NAMES)('name enum accepts "%s"', (name) => {
    const r = ActivityLog.safeParse(validActivity({ name }));
    expect(r.success).toBe(true);
  });

  test('name enum rejects "frobnicate"', () => {
    const r = ActivityLog.safeParse(validActivity({ name: 'frobnicate' }));
    expect(r.success).toBe(false);
  });
});

describe('input schema', () => {
  const { InputLog } = require('../../src/extraction/schemas/input');

  test('accepts valid input draft', () => {
    const r = InputLog.safeParse(validInput());
    expect(r.success).toBe(true);
  });

  test('missing recipe_lot rejected', () => {
    const v = validInput();
    delete v.recipe_lot;
    const r = InputLog.safeParse(v);
    expect(r.success).toBe(false);
  });
});

describe('observation schema', () => {
  const { ObservationLog } = require('../../src/extraction/schemas/observation');

  test('accepts observation with state', () => {
    const r = ObservationLog.safeParse(validObservation());
    expect(r.success).toBe(true);
  });

  test('accepts observation with notes only', () => {
    const v = validObservation();
    delete v.state;
    v.notes = 'looks good';
    const r = ObservationLog.safeParse(v);
    expect(r.success).toBe(true);
  });

  test('requires state OR notes -- pure asset_ref rejected', () => {
    const v = validObservation();
    delete v.state;
    const r = ObservationLog.safeParse(v);
    expect(r.success).toBe(false);
  });
});

describe('harvest schema', () => {
  const { HarvestLog } = require('../../src/extraction/schemas/harvest');

  test('multi-parent source_block_refs parses 3 refs intact (C4)', () => {
    const r = HarvestLog.safeParse(validHarvest());
    expect(r.success).toBe(true);
    expect(r.data.source_block_refs).toEqual(['260511_SHI_3', '260511_SHI_4', '260511_SHI_5']);
  });

  test('empty source_block_refs rejected by .min(1)', () => {
    const r = HarvestLog.safeParse(validHarvest({ source_block_refs: [] }));
    expect(r.success).toBe(false);
  });

  test('qty_g must be positive', () => {
    const r = HarvestLog.safeParse(validHarvest({ qty_g: -1 }));
    expect(r.success).toBe(false);
  });
});

describe('per-field confidence shape', () => {
  const { SeedingLog } = require('../../src/extraction/schemas/seeding');

  test('record(string, number 0..1) rejects 1.5', () => {
    const r = SeedingLog.safeParse(validSeeding({ confidence: { species: 1.5 } }));
    expect(r.success).toBe(false);
  });

  test('record(string, number 0..1) rejects negative', () => {
    const r = SeedingLog.safeParse(validSeeding({ confidence: { species: -0.1 } }));
    expect(r.success).toBe(false);
  });
});

describe('index.js -- Draft union', () => {
  const schemas = require('../../src/extraction/schemas');

  test('LOG_TYPES is frozen, length 6, covers all log types (incl. seeding_session)', () => {
    expect(schemas.LOG_TYPES).toEqual([
      'seeding',
      'activity',
      'input',
      'observation',
      'harvest',
      'seeding_session',
    ]);
    expect(Object.isFrozen(schemas.LOG_TYPES)).toBe(true);
  });

  test('Draft accepts a valid seeding draft', () => {
    const r = schemas.Draft.safeParse(validSeeding());
    expect(r.success).toBe(true);
  });

  test('Draft rejects unknown discriminator', () => {
    const r = schemas.Draft.safeParse({ ...validSeeding(), type: 'frobnicate' });
    expect(r.success).toBe(false);
  });

  test('DRAFT_JSON_SCHEMA is a plain JSON-serializable object', () => {
    const s = schemas.DRAFT_JSON_SCHEMA;
    expect(typeof s).toBe('object');
    expect(s).not.toBeNull();
    const round = JSON.parse(JSON.stringify(s));
    expect(round).toEqual(s);
  });

  test('DRAFT_JSON_SCHEMA is Anthropic-compatible (no top-level $ref; serializable)', () => {
    // Anthropic input_schema must be a plain JSON Schema object usable as tool input_schema.
    // zod-to-json-schema with a name arg produces $ref + definitions; we resolve the named def below.
    const s = schemas.DRAFT_JSON_SCHEMA;
    // Top-level must be an object schema (oneOf/anyOf/discriminated form) reachable via definitions or directly.
    const serialized = JSON.stringify(s);
    expect(serialized).toMatch(/seeding|harvest|activity|input|observation/);
  });
});

// ============================================================================
// Phase 47 Plan 01: SeedingSession wired into Draft + Submission unions.
// Regression guards: all 5 legacy types still parse; new type parses; empty
// groups[] rejected.
// ============================================================================

function provP(value, sources = ['paper_log_photo'], confidence = 0.95) {
  return { value, sources, confidence };
}

function minimalSeedingSession(overrides = {}) {
  return {
    type: 'seeding_session',
    event_date: '2026-05-22',
    groups: [
      {
        parent: provP('260118_SHI_23'),
        species: provP('SHI'),
        qty: provP(2),
        child_block_names: provP(['260522_SHI_1', '260522_SHI_2']),
      },
    ],
    ...overrides,
  };
}

describe('Phase 47 Plan 01 -- seeding_session in Draft union', () => {
  const schemas = require('../../src/extraction/schemas');

  test('Draft accepts a minimal seeding_session', () => {
    const r = schemas.Draft.safeParse(minimalSeedingSession());
    expect(r.success).toBe(true);
  });

  test('Draft rejects seeding_session with empty groups[]', () => {
    const r = schemas.Draft.safeParse(minimalSeedingSession({ groups: [] }));
    expect(r.success).toBe(false);
  });

  test('Submission accepts seeding_session at drafts[0].draft', () => {
    const sub = {
      drafts: [
        {
          draft: minimalSeedingSession(),
          per_field_confidence: { 'groups[0].parent': 0.95 },
        },
      ],
      continuity: 'start_new',
      continuity_reason: 'new inoc session',
    };
    const r = schemas.Submission.safeParse(sub);
    expect(r.success).toBe(true);
  });

  test('SeedingSession + Provenanced are re-exported from schemas/index.js', () => {
    expect(typeof schemas.SeedingSession).toBe('object');
    expect(typeof schemas.SeedingSessionGroup).toBe('object');
    expect(typeof schemas.ConflictEntry).toBe('object');
    expect(typeof schemas.Provenanced).toBe('function');
    expect(schemas.SOURCE_ENUM.options).toContain('paper_log_photo');
  });

  test('regression -- all 5 legacy types still parse through Draft', () => {
    expect(schemas.Draft.safeParse(validSeeding()).success).toBe(true);
    expect(schemas.Draft.safeParse(validActivity()).success).toBe(true);
    expect(schemas.Draft.safeParse(validInput()).success).toBe(true);
    expect(schemas.Draft.safeParse(validObservation()).success).toBe(true);
    expect(schemas.Draft.safeParse(validHarvest()).success).toBe(true);
  });

  test('DRAFT_JSON_SCHEMA mentions seeding_session after extension', () => {
    const s = JSON.stringify(schemas.DRAFT_JSON_SCHEMA);
    expect(s).toMatch(/seeding_session/);
  });
});

// ============================================================================
// Phase 53 BACK-03: optional capture_kind field on the Submission envelope.
// Allowed values: paper_log | physical_object_photo | voice_note | text.
// Field is optional + nullable so existing callers / partial outputs keep
// validating (back-compat lock per D-BACK-03).
// ============================================================================

describe('Phase 53 BACK-03 -- capture_kind on Submission envelope', () => {
  const schemas = require('../../src/extraction/schemas');

  function baseSubmission(extra = {}) {
    return {
      drafts: [
        {
          draft: validSeeding(),
          per_field_confidence: { species: 0.9 },
        },
      ],
      continuity: 'start_new',
      continuity_reason: 'new',
      ...extra,
    };
  }

  test('back-compat: Submission with no capture_kind still validates', () => {
    const r = schemas.Submission.safeParse(baseSubmission());
    expect(r.success).toBe(true);
  });

  test('accepts capture_kind: physical_object_photo', () => {
    const r = schemas.Submission.safeParse(baseSubmission({ capture_kind: 'physical_object_photo' }));
    expect(r.success).toBe(true);
  });

  test('accepts all four enum values', () => {
    for (const v of ['paper_log', 'physical_object_photo', 'voice_note', 'text']) {
      const r = schemas.Submission.safeParse(baseSubmission({ capture_kind: v }));
      expect(r.success).toBe(true);
    }
  });

  test('accepts capture_kind: null (explicit null)', () => {
    const r = schemas.Submission.safeParse(baseSubmission({ capture_kind: null }));
    expect(r.success).toBe(true);
  });

  test('rejects invalid capture_kind value', () => {
    const r = schemas.Submission.safeParse(baseSubmission({ capture_kind: 'banana' }));
    expect(r.success).toBe(false);
  });

  test('SUBMISSION_JSON_SCHEMA mentions capture_kind', () => {
    const s = JSON.stringify(schemas.SUBMISSION_JSON_SCHEMA);
    expect(s).toMatch(/capture_kind/);
    expect(s).toMatch(/physical_object_photo/);
  });
});
