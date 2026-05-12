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
