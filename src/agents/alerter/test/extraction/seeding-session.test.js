'use strict';

/**
 * Tests for Phase 47 Plan 01 schemas:
 *   - Provenanced<T> factory + SOURCE_ENUM
 *   - SeedingSessionGroup
 *   - ConflictEntry
 *   - SeedingSession (top-level discriminated-union member)
 *
 * Behavior anchors (PLAN 47-01 task 1):
 *   (a) May-22-shape happy path (5 groups, 11 children) parses
 *   (b) off-schema field at top level rejected
 *   (c) provenanced field missing 'sources' rejected
 *   (d) child_block_names with mixed 'NEEDS_SEQ' + valid block_names parses
 *   (e) ConflictEntry with only 1 candidate rejected
 *   (f) species lowercase rejected
 */

const {
  SeedingSession,
  SeedingSessionGroup,
  ConflictEntry,
} = require('../../src/extraction/schemas/seeding-session');
const {
  Provenanced,
  SOURCE_ENUM,
} = require('../../src/extraction/schemas/provenance');
const { z } = require('zod');

function prov(value, sources = ['paper_log_photo'], confidence = 0.95) {
  return { value, sources, confidence };
}

function validGroup(overrides = {}) {
  return {
    parent: prov('260118_SHI_23'),
    species: prov('SHI'),
    qty: prov(3),
    child_block_names: prov(['260522_SHI_1', '260522_SHI_2', '260522_SHI_3']),
    ...overrides,
  };
}

// May 22 canonical session: 5 groups, 11 children, 2 species (SHI 3 + KOY 8).
function may22Session() {
  return {
    type: 'seeding_session',
    event_date: '2026-05-22',
    groups: [
      {
        parent: prov('260118_SHI_23', ['audio', 'paper_log_photo']),
        species: prov('SHI'),
        qty: prov(3),
        child_block_names: prov(['260522_SHI_1', '260522_SHI_2', '260522_SHI_3']),
      },
      {
        parent: prov('260201_KOY_5'),
        species: prov('KOY'),
        qty: prov(2),
        child_block_names: prov(['260522_KOY_4', '260522_KOY_5']),
      },
      {
        parent: prov('260201_KOY_7'),
        species: prov('KOY'),
        qty: prov(2),
        child_block_names: prov(['260522_KOY_6', '260522_KOY_7']),
      },
      {
        parent: prov('260201_KOY_9'),
        species: prov('KOY'),
        qty: prov(2),
        child_block_names: prov(['260522_KOY_8', '260522_KOY_9']),
      },
      {
        parent: prov('260201_KOY_11'),
        species: prov('KOY'),
        qty: prov(2),
        child_block_names: prov(['260522_KOY_10', '260522_KOY_11']),
      },
    ],
  };
}

describe('Provenanced factory', () => {
  test('wraps a value schema and accepts {value, confidence, sources[]}', () => {
    const P = Provenanced(z.string());
    const r = P.safeParse({ value: 'x', confidence: 0.9, sources: ['audio'] });
    expect(r.success).toBe(true);
  });

  test('rejects missing sources field', () => {
    const P = Provenanced(z.string());
    const r = P.safeParse({ value: 'x', confidence: 0.9 });
    expect(r.success).toBe(false);
  });

  test('rejects empty sources array', () => {
    const P = Provenanced(z.string());
    const r = P.safeParse({ value: 'x', confidence: 0.9, sources: [] });
    expect(r.success).toBe(false);
  });

  test('rejects source not in SOURCE_ENUM', () => {
    const P = Provenanced(z.string());
    const r = P.safeParse({ value: 'x', confidence: 0.9, sources: ['video'] });
    expect(r.success).toBe(false);
  });

  test('rejects confidence > 1', () => {
    const P = Provenanced(z.string());
    const r = P.safeParse({ value: 'x', confidence: 1.5, sources: ['audio'] });
    expect(r.success).toBe(false);
  });

  test('rejects off-schema extra field (strict)', () => {
    const P = Provenanced(z.string());
    const r = P.safeParse({
      value: 'x',
      confidence: 0.9,
      sources: ['audio'],
      extra: 'nope',
    });
    expect(r.success).toBe(false);
  });

  test('SOURCE_ENUM covers the locked 5 sources', () => {
    expect(SOURCE_ENUM.options).toEqual([
      'audio',
      'paper_log_photo',
      'bag_label_photo',
      'text',
      'model_inference',
    ]);
  });
});

describe('SeedingSessionGroup', () => {
  test('accepts valid group', () => {
    const r = SeedingSessionGroup.safeParse(validGroup());
    expect(r.success).toBe(true);
  });

  test('species lowercase rejected', () => {
    const r = SeedingSessionGroup.safeParse(
      validGroup({ species: prov('shi') })
    );
    expect(r.success).toBe(false);
  });

  test('child_block_names accepts mixed NEEDS_SEQ + valid block_names', () => {
    const r = SeedingSessionGroup.safeParse(
      validGroup({
        child_block_names: prov(['260522_SHI_1', 'NEEDS_SEQ', '260522_SHI_3']),
      })
    );
    expect(r.success).toBe(true);
  });

  test('child_block_names rejects garbage string', () => {
    const r = SeedingSessionGroup.safeParse(
      validGroup({ child_block_names: prov(['not_a_block']) })
    );
    expect(r.success).toBe(false);
  });

  test('parent accepts NO_PARENT sentinel string', () => {
    const r = SeedingSessionGroup.safeParse(
      validGroup({ parent: prov('NO_PARENT') })
    );
    expect(r.success).toBe(true);
  });

  test('qty must be positive integer', () => {
    const r = SeedingSessionGroup.safeParse(validGroup({ qty: prov(0) }));
    expect(r.success).toBe(false);
  });

  test('off-schema field at group level rejected (strict)', () => {
    const r = SeedingSessionGroup.safeParse({
      ...validGroup(),
      surprise: 'rejected',
    });
    expect(r.success).toBe(false);
  });
});

describe('ConflictEntry', () => {
  test('accepts a 2-candidate photo_wins_implicit conflict', () => {
    const r = ConflictEntry.safeParse({
      path: 'groups[1].parent.value',
      candidates: [
        { value: '260118_SHI_23', source: 'audio', confidence: 0.7 },
        { value: '260118_SHI_25', source: 'paper_log_photo', confidence: 0.95 },
      ],
      resolution: 'photo_wins_implicit',
    });
    expect(r.success).toBe(true);
  });

  test('rejects ConflictEntry with only 1 candidate', () => {
    const r = ConflictEntry.safeParse({
      path: 'groups[1].parent.value',
      candidates: [
        { value: '260118_SHI_23', source: 'audio', confidence: 0.7 },
      ],
      resolution: 'photo_wins_implicit',
    });
    expect(r.success).toBe(false);
  });

  test('rejects unknown resolution value', () => {
    const r = ConflictEntry.safeParse({
      path: 'groups[1].parent.value',
      candidates: [
        { value: 'a', source: 'audio', confidence: 0.7 },
        { value: 'b', source: 'paper_log_photo', confidence: 0.95 },
      ],
      resolution: 'coin_flip',
    });
    expect(r.success).toBe(false);
  });
});

describe('SeedingSession (top-level)', () => {
  test('May-22-shape (5 groups, 11 children) parses', () => {
    const r = SeedingSession.safeParse(may22Session());
    expect(r.success).toBe(true);
    if (r.success) {
      const totalChildren = r.data.groups.reduce(
        (n, g) => n + g.child_block_names.value.length,
        0
      );
      expect(totalChildren).toBe(11);
      expect(r.data.groups.length).toBe(5);
    }
  });

  test('off-schema field at top level rejected (strict)', () => {
    const r = SeedingSession.safeParse({
      ...may22Session(),
      surprise_field: 'rejected',
    });
    expect(r.success).toBe(false);
  });

  test('event_date wrong format rejected', () => {
    const r = SeedingSession.safeParse({
      ...may22Session(),
      event_date: '05/22/2026',
    });
    expect(r.success).toBe(false);
  });

  test('empty groups[] rejected', () => {
    const r = SeedingSession.safeParse({ ...may22Session(), groups: [] });
    expect(r.success).toBe(false);
  });

  test('accepts needs_input=starting_seq with NEEDS_SEQ children', () => {
    const session = {
      type: 'seeding_session',
      event_date: '2026-05-22',
      needs_input: 'starting_seq',
      groups: [
        {
          parent: prov('260118_SHI_23'),
          species: prov('SHI'),
          qty: prov(3),
          child_block_names: prov(['NEEDS_SEQ', 'NEEDS_SEQ', 'NEEDS_SEQ']),
        },
      ],
    };
    const r = SeedingSession.safeParse(session);
    expect(r.success).toBe(true);
  });

  test('accepts optional conflicts[] array', () => {
    const r = SeedingSession.safeParse({
      ...may22Session(),
      conflicts: [
        {
          path: 'groups[0].parent.value',
          candidates: [
            { value: '260118_SHI_23', source: 'audio', confidence: 0.7 },
            {
              value: '260118_SHI_25',
              source: 'paper_log_photo',
              confidence: 0.95,
            },
          ],
          resolution: 'photo_wins_implicit',
        },
      ],
    });
    expect(r.success).toBe(true);
  });

  test('provenanced field missing sources rejected', () => {
    const bad = may22Session();
    // remove sources from groups[0].parent
    delete bad.groups[0].parent.sources;
    const r = SeedingSession.safeParse(bad);
    expect(r.success).toBe(false);
  });
});
