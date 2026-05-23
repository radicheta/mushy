'use strict';

// Phase 38 Plan 04 Task 3: preview-builder + farmer-facing sanitize sweep.
// Covers D-04 ask-back shape (top question + draft body with [?] markers),
// memory rules (no em-dashes, fmtNum on numbers, neutral language).

const path = require('path');
const fs = require('fs');

const pb = require('../../src/extraction/preview-builder');
const { buildPreview, buildTopQuestion, sanitizeFarmerText } = pb;

const SEEDING_REQUIRED = ['species', 'block_name', 'qty', 'event_timestamp'];

// ---- buildPreview ----

describe('buildPreview', () => {
  test('seeding with missing block_name renders [?] on that field', () => {
    const out = buildPreview({
      draft: {
        type: 'seeding', species: 'SHI', qty: 10,
        event_timestamp: '2026-05-12T10:00:00.000Z',
      },
      perFieldConfidence: { species: 0.9, qty: 0.95, event_timestamp: 0.9 },
      threshold: 0.7,
      requiredFields: SEEDING_REQUIRED,
    });
    expect(out).toMatch(/block_name:\s*\[\?\]/);
    expect(out).toMatch(/species:\s*SHI/);
  });

  test('qty 10.5000000001 renders as 10.5 via fmtNum', () => {
    const out = buildPreview({
      draft: {
        type: 'seeding', species: 'SHI', block_name: '260512_SHI_4',
        qty: 10.5000000001, event_timestamp: '2026-05-12T10:00:00.000Z',
      },
      perFieldConfidence: { species: 0.9, block_name: 0.9, qty: 0.9, event_timestamp: 0.9 },
      threshold: 0.7,
      requiredFields: SEEDING_REQUIRED,
    });
    expect(out).toMatch(/qty:\s*10\.5(\s|$)/m);
    expect(out).not.toMatch(/10\.50000/);
  });

  test('source_block_refs array renders as bracketed comma list', () => {
    const out = buildPreview({
      draft: {
        type: 'harvest', harvest_batch_id: 'H-1',
        source_block_refs: ['260512_SHI_3', '260512_SHI_4'],
        qty_g: 1500, event_timestamp: '2026-05-12T10:00:00.000Z',
      },
      perFieldConfidence: {
        harvest_batch_id: 0.9, source_block_refs: 0.9,
        qty_g: 0.9, event_timestamp: 0.9,
      },
      threshold: 0.7,
      requiredFields: ['harvest_batch_id', 'source_block_refs', 'qty_g', 'event_timestamp'],
    });
    expect(out).toMatch(/\[260512_SHI_3, 260512_SHI_4\]/);
  });

  test('output contains no em-dash', () => {
    const out = buildPreview({
      draft: {
        type: 'seeding', species: 'SHI', qty: 10,
        event_timestamp: '2026-05-12T10:00:00.000Z',
      },
      perFieldConfidence: { species: 0.9, qty: 0.95, event_timestamp: 0.9 },
      threshold: 0.7,
      requiredFields: SEEDING_REQUIRED,
    });
    expect(out).not.toMatch(/—/);
  });

  test('output starts with a non-blank line (top question)', () => {
    const out = buildPreview({
      draft: {
        type: 'seeding', species: 'SHI', qty: 10,
        event_timestamp: '2026-05-12T10:00:00.000Z',
      },
      perFieldConfidence: { species: 0.9, qty: 0.95, event_timestamp: 0.9 },
      threshold: 0.7,
      requiredFields: SEEDING_REQUIRED,
    });
    const firstLine = out.split('\n')[0];
    expect(firstLine.trim().length).toBeGreaterThan(0);
  });

  test('top question is on a separate paragraph from draft body', () => {
    const out = buildPreview({
      draft: {
        type: 'seeding', species: 'SHI', qty: 10,
        event_timestamp: '2026-05-12T10:00:00.000Z',
      },
      perFieldConfidence: { species: 0.9, qty: 0.95, event_timestamp: 0.9 },
      threshold: 0.7,
      requiredFields: SEEDING_REQUIRED,
    });
    const lines = out.split('\n');
    expect(lines[1]).toBe('');
  });

  test('event_timestamp renders without millisecond suffix', () => {
    const out = buildPreview({
      draft: {
        type: 'seeding', species: 'SHI', block_name: '260512_SHI_4',
        qty: 10, event_timestamp: '2026-05-12T10:00:00.000Z',
      },
      perFieldConfidence: { species: 0.9, block_name: 0.9, qty: 0.9, event_timestamp: 0.9 },
      threshold: 0.7,
      requiredFields: SEEDING_REQUIRED,
    });
    expect(out).toMatch(/event_timestamp:\s*2026-05-12T10:00:00Z/);
  });
});

// ---- buildPreview: seeding_session placeholder branch (Phase 47-04) ----

// Helper: provenanced field shape per Phase 47-01 schemas.
function prov(value, sources = ['paper_log_photo'], confidence = 0.95) {
  return { value, confidence, sources };
}

// May-22 canonical fixture: 11 blocks across 5 groups (3 SHI + 8 KOY split
// across 5 parents). Mirrors the multi-parent-inoc-batch shape from CONTEXT.md.
function may22Draft({ withConflicts = false, needsInput = undefined } = {}) {
  const draft = {
    type: 'seeding_session',
    event_date: '2026-05-22',
    groups: [
      {
        parent: prov('260118_SHI_25'),
        species: prov('SHI'),
        qty: prov(3),
        child_block_names: prov(['260522_SHI_1', '260522_SHI_2', '260522_SHI_3']),
      },
      {
        parent: prov('260201_KOY_1'),
        species: prov('KOY'),
        qty: prov(2),
        child_block_names: prov(['260522_KOY_4', '260522_KOY_5']),
      },
      {
        parent: prov('260203_KOY_2'),
        species: prov('KOY'),
        qty: prov(2),
        child_block_names: prov(['260522_KOY_6', '260522_KOY_7']),
      },
      {
        parent: prov('260210_KOY_3'),
        species: prov('KOY'),
        qty: prov(2),
        child_block_names: prov(['260522_KOY_8', '260522_KOY_9']),
      },
      {
        parent: prov('260215_KOY_4'),
        species: prov('KOY'),
        qty: prov(2),
        child_block_names: prov(['260522_KOY_10', '260522_KOY_11']),
      },
    ],
  };
  if (needsInput) draft.needs_input = needsInput;
  if (withConflicts) {
    draft.conflicts = [{
      path: 'groups[0].parent.value',
      candidates: [
        { value: '260118_SHI_23', source: 'audio', confidence: 0.7 },
        { value: '260118_SHI_25', source: 'paper_log_photo', confidence: 0.95 },
      ],
      resolution: 'photo_wins_implicit',
    }];
  }
  return draft;
}

describe('buildPreview: seeding_session placeholder branch', () => {
  test('(a) May-22-shape draft renders 11 blocks across 5 groups + event_date + per-group lines', () => {
    const out = buildPreview({
      draft: may22Draft(),
      perFieldConfidence: {},
      threshold: 0.7,
      requiredFields: ['event_date', 'groups'],
    });
    expect(out).toMatch(/11 blocks across 5 groups/);
    // Phase 47-04 hotfix: human-readable date ("May 22") per CONTEXT.md style lock.
    expect(out).toMatch(/May 22/);
    expect(out).not.toMatch(/2026-05-22/);
    // Per-group line for each group's species x qty from parent.
    expect(out).toMatch(/SHI x 3 from 260118_SHI_25/);
    expect(out).toMatch(/KOY x 2 from 260201_KOY_1/);
    expect(out).toMatch(/KOY x 2 from 260203_KOY_2/);
    expect(out).toMatch(/KOY x 2 from 260210_KOY_3/);
    expect(out).toMatch(/KOY x 2 from 260215_KOY_4/);
    expect(out).toMatch(/Group-by-parent preview coming in Phase 48/);
  });

  test('(b) needs_input=starting_seq renders the awaiting marker line', () => {
    const out = buildPreview({
      draft: may22Draft({ needsInput: 'starting_seq' }),
      perFieldConfidence: {},
      threshold: 0.7,
      requiredFields: ['event_date', 'groups'],
    });
    expect(out).toMatch(/Awaiting block-number to start at\./);
    // The Phase 48 placeholder line must NOT appear when ask-back path is active.
    expect(out).not.toMatch(/Group-by-parent preview coming in Phase 48/);
  });

  test('(c) NEGATIVE ASSERTION: conflicts[] candidate values + the word "conflict" NEVER leak (Gray Area 4 lock)', () => {
    const out = buildPreview({
      draft: may22Draft({ withConflicts: true }),
      perFieldConfidence: {},
      threshold: 0.7,
      requiredFields: ['event_date', 'groups'],
    });
    // The losing candidate (audio) must never appear.
    expect(out.indexOf('260118_SHI_23')).toBe(-1);
    // The literal word "conflict" must never appear (case-insensitive).
    expect(out.toLowerCase().indexOf('conflict')).toBe(-1);
    // The resolution marker must never appear.
    expect(out.indexOf('photo_wins')).toBe(-1);
    // Sanity: the winning value (which is the resolved parent.value) IS allowed
    // -- it is the canonical group.parent.value the renderer reads, not the
    // conflict array.
    expect(out).toMatch(/260118_SHI_25/);
  });

  test('(d) parent.value === NO_PARENT renders as "no parent recorded"', () => {
    const draft = {
      type: 'seeding_session',
      event_date: '2026-05-22',
      groups: [
        {
          parent: prov('NO_PARENT'),
          species: prov('SHI'),
          qty: prov(4),
          child_block_names: prov(['260522_SHI_1', '260522_SHI_2', '260522_SHI_3', '260522_SHI_4']),
        },
      ],
    };
    const out = buildPreview({
      draft,
      perFieldConfidence: {},
      threshold: 0.7,
      requiredFields: ['event_date', 'groups'],
    });
    expect(out).toMatch(/SHI x 4 from no parent recorded/);
    // Sentinel literal NO_PARENT must not appear as raw text in farmer output.
    expect(out.indexOf('NO_PARENT')).toBe(-1);
  });

  test('(e) regression: legacy 5-type preview rendering still works (seeding)', () => {
    const out = buildPreview({
      draft: {
        type: 'seeding', species: 'SHI', block_name: '260512_SHI_4',
        qty: 10, event_timestamp: '2026-05-12T10:00:00.000Z',
      },
      perFieldConfidence: { species: 0.9, block_name: 0.9, qty: 0.9, event_timestamp: 0.9 },
      threshold: 0.7,
      requiredFields: SEEDING_REQUIRED,
    });
    // Still uses the field-listing body, not the seeding_session placeholder.
    expect(out).toMatch(/type:\s*seeding(\s|$)/m);
    expect(out).toMatch(/block_name:\s*260512_SHI_4/);
    expect(out).not.toMatch(/Group-by-parent preview/);
    expect(out).not.toMatch(/blocks across/);
  });

  test('(f) output sanitized: no em-dashes in seeding_session placeholder', () => {
    const out = buildPreview({
      draft: may22Draft(),
      perFieldConfidence: {},
      threshold: 0.7,
      requiredFields: ['event_date', 'groups'],
    });
    expect(out).not.toMatch(/—/);
  });

  test('(g) total block count uses child_block_names.value.length when present', () => {
    // Synthetic: qty.value disagrees with child_block_names length; N must
    // follow the names array length (more authoritative when present).
    const draft = {
      type: 'seeding_session',
      event_date: '2026-05-22',
      groups: [
        {
          parent: prov('260118_SHI_25'),
          species: prov('SHI'),
          qty: prov(999),
          child_block_names: prov(['260522_SHI_1', '260522_SHI_2']),
        },
      ],
    };
    const out = buildPreview({
      draft,
      perFieldConfidence: {},
      threshold: 0.7,
      requiredFields: ['event_date', 'groups'],
    });
    expect(out).toMatch(/2 blocks across 1 groups/);
  });
});

// ---- buildTopQuestion ----

describe('buildTopQuestion', () => {
  test('seeding missing block_name picks block-name-specific phrasing with 260512_SHI_4 example', () => {
    const q = buildTopQuestion({
      missingFields: ['block_name'],
      lowConfFields: [],
      draftType: 'seeding',
    });
    expect(q).toMatch(/block name/i);
    expect(q).toMatch(/260512_SHI_4/);
    expect(q).not.toMatch(/—/);
    expect(q).not.toMatch(/\n/);
  });

  test('low-conf-only path triggers different phrasing than missing', () => {
    const qMissing = buildTopQuestion({
      missingFields: ['species'],
      lowConfFields: [],
      draftType: 'seeding',
    });
    const qLow = buildTopQuestion({
      missingFields: [],
      lowConfFields: ['species'],
      draftType: 'seeding',
    });
    expect(qMissing).not.toBe(qLow);
  });

  test('fallback when no missing + no low-conf returns generic confirm prompt', () => {
    const q = buildTopQuestion({
      missingFields: [],
      lowConfFields: [],
      draftType: 'seeding',
    });
    expect(typeof q).toBe('string');
    expect(q.length).toBeGreaterThan(0);
  });
});

// ---- sanitizeFarmerText ----

describe('sanitizeFarmerText', () => {
  test('replaces em-dashes', () => {
    expect(sanitizeFarmerText('one — two')).not.toMatch(/—/);
  });

  test('is idempotent', () => {
    const once = sanitizeFarmerText('one — two');
    const twice = sanitizeFarmerText(once);
    expect(once).toBe(twice);
  });

  test('en-dash converted to ASCII hyphen', () => {
    expect(sanitizeFarmerText('a–b')).toBe('a-b');
  });
});

// ---- source-file memory check ----

describe('memory: no em-dashes in source', () => {
  test('preview-builder.js source has no em-dash characters', () => {
    const src = fs.readFileSync(
      path.join(__dirname, '..', '..', 'src', 'extraction', 'preview-builder.js'),
      'utf8',
    );
    expect(src).not.toMatch(/—/);
  });
});
