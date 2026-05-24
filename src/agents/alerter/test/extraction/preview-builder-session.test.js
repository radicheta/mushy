'use strict';

// Phase 48 Plan 03 Task 1: production renderSeedingSession table tests.
//
// The Phase 47-04 placeholder lived in sanitize.test.js; it was replaced by
// the group-by-parent table locked in CONTEXT.md Gray Area C and the
// em-dash-to-colon adjustment (memory: feedback_no_em_dashes_in_artifacts).
//
// All tests exercise the renderer via the public buildPreview() entry; the
// renderer is module-internal.

const { buildPreview } = require('../../src/extraction/preview-builder');

// Helper: provenanced field shape per Phase 47-01 schemas.
function prov(value, sources = ['paper_log_photo'], confidence = 0.95) {
  return { value, confidence, sources };
}

// May-22 canonical fixture: 11 blocks across 5 PARENTS (1/1/1/4/4 split per
// CONTEXT.md Gray Area C rendered example).
function may22Draft({ withConflicts = false, needsInput = undefined, notes = undefined } = {}) {
  const draft = {
    type: 'seeding_session',
    event_date: '2026-05-22',
    groups: [
      {
        parent: prov('260304_SHI_5'),
        species: prov('SHI'),
        qty: prov(1),
        child_block_names: prov(['260522_SHI_1']),
      },
      {
        parent: prov('260118_SHI_23'),
        species: prov('SHI'),
        qty: prov(1),
        child_block_names: prov(['260522_SHI_2']),
      },
      {
        parent: prov('260118_SHI_26'),
        species: prov('SHI'),
        qty: prov(1),
        child_block_names: prov(['260522_SHI_3']),
      },
      {
        parent: prov('260118_KOY_12'),
        species: prov('KOY'),
        qty: prov(4),
        child_block_names: prov(['260522_KOY_4', '260522_KOY_5', '260522_KOY_6', '260522_KOY_7']),
      },
      {
        parent: prov('260425_KOY_4'),
        species: prov('KOY'),
        qty: prov(4),
        child_block_names: prov(['260522_KOY_8', '260522_KOY_9', '260522_KOY_10', '260522_KOY_11']),
      },
    ],
  };
  if (needsInput) draft.needs_input = needsInput;
  if (notes != null) draft.notes = notes;
  if (withConflicts) {
    // A conflict on group[1].parent: paper_log_photo wins (260118_SHI_23 is the
    // value stored in the resolved draft); audio's losing candidate
    // 260118_SHI_25 must never appear in the rendered output.
    draft.conflicts = [{
      path: 'groups[1].parent.value',
      candidates: [
        { value: '260118_SHI_25', source: 'audio', confidence: 0.7 },
        { value: '260118_SHI_23', source: 'paper_log_photo', confidence: 0.95 },
      ],
      resolution: 'photo_wins_implicit',
    }];
  }
  return draft;
}

const REQ = ['event_date', 'groups'];

describe('renderSeedingSession (Phase 48-03 production table)', () => {
  test('(A) May-22 canonical: header, summary, column header, 5 group rows, footer', () => {
    const out = buildPreview({
      draft: may22Draft(), perFieldConfidence: {}, threshold: 0.7, requiredFields: REQ,
    });
    // Header line (em-dash policy: colon, not em-dash).
    expect(out).toMatch(/^Inoc session: 2026-05-22$/m);
    // Summary line: "11 blocks across 5 parents".
    expect(out).toMatch(/^11 blocks across 5 parents$/m);
    // Column header (all five columns on one line).
    const colHeaderLine = out.split('\n').find((l) => /KEY/.test(l) && /PARENT/.test(l));
    expect(colHeaderLine).toBeTruthy();
    expect(colHeaderLine).toMatch(/KEY.*PARENT.*SPECIES.*QTY.*CHILDREN/);
    // Row 1: 260304_SHI_5 / SHI / 1 / 260522_SHI_1 on the same line.
    const r1 = out.split('\n').find((l) => /260304_SHI_5/.test(l));
    expect(r1).toBeTruthy();
    expect(r1).toMatch(/260304_SHI_5/);
    expect(r1).toMatch(/SHI/);
    expect(r1).toMatch(/\b1\b/);
    expect(r1).toMatch(/260522_SHI_1\b/);
    // Row 4: 260118_KOY_12 / KOY / 4 / 260522_KOY_4..7 (range-collapsed).
    const r4 = out.split('\n').find((l) => /260118_KOY_12/.test(l));
    expect(r4).toBeTruthy();
    expect(r4).toMatch(/KOY/);
    expect(r4).toMatch(/\b4\b/);
    expect(r4).toMatch(/260522_KOY_4\.\.7/);
    // Row 5: 260425_KOY_4 / KOY / 4 / 260522_KOY_8..11.
    const r5 = out.split('\n').find((l) => /260425_KOY_4/.test(l));
    expect(r5).toBeTruthy();
    expect(r5).toMatch(/260522_KOY_8\.\.11/);
    // Footer.
    expect(out).toMatch(/^YES to commit \| NO to cancel \| EDIT to change$/m);
    // No em-dashes anywhere.
    expect(out.indexOf('—')).toBe(-1);
    // No emoji (basic high-codepoint sweep).
    expect(/[\u{1F300}-\u{1FAFF}]/u.test(out)).toBe(false);
  });

  test('(B) range-collapse: 3+ consecutive same-strain SEQs collapse; 2 or non-consecutive list', () => {
    // 3 consecutive: ranges
    let out = buildPreview({
      draft: {
        type: 'seeding_session', event_date: '2026-05-22',
        groups: [{
          parent: prov('260118_KOY_12'), species: prov('KOY'), qty: prov(3),
          child_block_names: prov(['260522_KOY_4', '260522_KOY_5', '260522_KOY_6']),
        }],
      },
      perFieldConfidence: {}, threshold: 0.7, requiredFields: REQ,
    });
    expect(out).toMatch(/260522_KOY_4\.\.6/);

    // 2 children: comma-list
    out = buildPreview({
      draft: {
        type: 'seeding_session', event_date: '2026-05-22',
        groups: [{
          parent: prov('260118_KOY_12'), species: prov('KOY'), qty: prov(2),
          child_block_names: prov(['260522_KOY_4', '260522_KOY_5']),
        }],
      },
      perFieldConfidence: {}, threshold: 0.7, requiredFields: REQ,
    });
    expect(out).toMatch(/260522_KOY_4, 260522_KOY_5/);
    expect(out).not.toMatch(/260522_KOY_4\.\.5/);

    // 3 non-consecutive: comma-list
    out = buildPreview({
      draft: {
        type: 'seeding_session', event_date: '2026-05-22',
        groups: [{
          parent: prov('260118_KOY_12'), species: prov('KOY'), qty: prov(3),
          child_block_names: prov(['260522_KOY_4', '260522_KOY_6', '260522_KOY_9']),
        }],
      },
      perFieldConfidence: {}, threshold: 0.7, requiredFields: REQ,
    });
    expect(out).toMatch(/260522_KOY_4, 260522_KOY_6, 260522_KOY_9/);
    expect(out).not.toMatch(/260522_KOY_4\.\.9/);
  });

  test('(C) overflow: 7 groups -> first 5 + "... (2 more groups)" trailing line BEFORE footer', () => {
    const groups = [];
    for (let i = 0; i < 7; i++) {
      const seq = i + 1;
      groups.push({
        parent: prov(`260118_SHI_${10 + i}`),
        species: prov('SHI'),
        qty: prov(1),
        child_block_names: prov([`260522_SHI_${seq}`]),
      });
    }
    const out = buildPreview({
      draft: { type: 'seeding_session', event_date: '2026-05-22', groups },
      perFieldConfidence: {}, threshold: 0.7, requiredFields: REQ,
    });
    // Exactly 5 data rows: scan lines that contain a parent prefix 260118_SHI_1*.
    const dataRows = out.split('\n').filter((l) => /^\s*\d+\s+260118_SHI_/.test(l));
    expect(dataRows.length).toBe(5);
    expect(out).toMatch(/^\.\.\. \(2 more groups\)$/m);
    // Overflow line precedes the YES/NO/EDIT footer.
    const lines = out.split('\n');
    const overflowIdx = lines.findIndex((l) => /^\.\.\. \(2 more groups\)$/.test(l));
    const footerIdx = lines.findIndex((l) => /^YES to commit/.test(l));
    expect(overflowIdx).toBeGreaterThan(-1);
    expect(footerIdx).toBeGreaterThan(overflowIdx);
  });

  test('(D) silent conflicts: conflict candidates + word "conflict" NEVER leak (Gray Area 4)', () => {
    const out = buildPreview({
      draft: may22Draft({ withConflicts: true }),
      perFieldConfidence: {}, threshold: 0.7, requiredFields: REQ,
    });
    // The losing audio candidate must not appear.
    expect(out.indexOf('260118_SHI_25')).toBe(-1);
    // The literal word "conflict" must not appear.
    expect(out.toLowerCase().indexOf('conflict')).toBe(-1);
    // The resolution marker must not appear.
    expect(out.indexOf('photo_wins')).toBe(-1);
    // The winning value IS the resolved parent.value -- it IS allowed to render.
    expect(out).toMatch(/260118_SHI_23/);
  });

  test('(E) notes: trailing "note: ..." line BEFORE the YES/NO/EDIT footer', () => {
    const out = buildPreview({
      draft: may22Draft({ notes: 'migration to new shelf' }),
      perFieldConfidence: {}, threshold: 0.7, requiredFields: REQ,
    });
    const lines = out.split('\n');
    const noteIdx = lines.findIndex((l) => /^note: migration to new shelf$/.test(l));
    const footerIdx = lines.findIndex((l) => /^YES to commit/.test(l));
    expect(noteIdx).toBeGreaterThan(-1);
    expect(footerIdx).toBeGreaterThan(noteIdx);
  });

  test('(F) needs_input=starting_seq: ask-back form, no table, contains starting-block-number phrasing', () => {
    const out = buildPreview({
      draft: may22Draft({ needsInput: 'starting_seq' }),
      perFieldConfidence: {}, threshold: 0.7, requiredFields: REQ,
    });
    expect(out).toMatch(/Inoc session: 2026-05-22/);
    expect(out).toMatch(/awaiting starting block-number/);
    // No table.
    expect(out).not.toMatch(/KEY.*PARENT.*SPECIES.*QTY.*CHILDREN/);
    expect(out).not.toMatch(/YES to commit/);
  });

  test('(G) single-parent legacy: 1 group / 5 consecutive children -> 1 row, CHILDREN shows range form', () => {
    const out = buildPreview({
      draft: {
        type: 'seeding_session',
        event_date: '2026-05-22',
        groups: [{
          parent: prov('260118_SHI_25'),
          species: prov('SHI'),
          qty: prov(5),
          child_block_names: prov([
            '260522_SHI_1', '260522_SHI_2', '260522_SHI_3', '260522_SHI_4', '260522_SHI_5',
          ]),
        }],
      },
      perFieldConfidence: {}, threshold: 0.7, requiredFields: REQ,
    });
    // Exactly 1 data row.
    const dataRows = out.split('\n').filter((l) => /^\s*\d+\s+260118_SHI_25/.test(l));
    expect(dataRows.length).toBe(1);
    expect(dataRows[0]).toMatch(/260522_SHI_1\.\.5/);
    // Summary updates to 5 blocks across 1 parents.
    expect(out).toMatch(/5 blocks across 1 parents/);
  });

  test('(H) parent.value === NO_PARENT renders as "no parent recorded"; sentinel never leaks', () => {
    const out = buildPreview({
      draft: {
        type: 'seeding_session', event_date: '2026-05-22',
        groups: [{
          parent: prov('NO_PARENT'), species: prov('SHI'), qty: prov(3),
          child_block_names: prov(['260522_SHI_1', '260522_SHI_2', '260522_SHI_3']),
        }],
      },
      perFieldConfidence: {}, threshold: 0.7, requiredFields: REQ,
    });
    expect(out).toMatch(/no parent recorded/);
    expect(out.indexOf('NO_PARENT')).toBe(-1);
  });
});
