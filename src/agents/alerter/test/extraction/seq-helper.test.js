'use strict';

// Phase 47 Plan 03 Task 1: seq-helper unit tests.
//
// Covers: mintChildBlockNames (pure), yyyymmddToYymmdd (pure),
// lookupLastSeqForDate (DB-backed; tolerates legacy + new draft shapes).

const {
  mintChildBlockNames,
  yyyymmddToYymmdd,
  lookupLastSeqForDate,
} = require('../../src/extraction/seq-helper');

describe('seq-helper -- yyyymmddToYymmdd', () => {
  test('converts a valid YYYY-MM-DD to YYMMDD', () => {
    expect(yyyymmddToYymmdd('2026-05-22')).toBe('260522');
    expect(yyyymmddToYymmdd('2025-01-01')).toBe('250101');
  });

  test('throws on bad input', () => {
    expect(() => yyyymmddToYymmdd('26-05-22')).toThrow();
    expect(() => yyyymmddToYymmdd('2026/05/22')).toThrow();
    expect(() => yyyymmddToYymmdd(null)).toThrow();
    expect(() => yyyymmddToYymmdd('')).toThrow();
  });
});

describe('seq-helper -- mintChildBlockNames', () => {
  test('happy path: returns qty consecutive block names from startSeq', () => {
    const out = mintChildBlockNames({
      eventDateYYMMDD: '260522',
      speciesCode: 'KOY',
      startSeq: 4,
      qty: 3,
    });
    expect(out).toEqual(['260522_KOY_4', '260522_KOY_5', '260522_KOY_6']);
  });

  test('qty=0 returns empty array', () => {
    const out = mintChildBlockNames({
      eventDateYYMMDD: '260522',
      speciesCode: 'SHI',
      startSeq: 1,
      qty: 0,
    });
    expect(out).toEqual([]);
  });

  test('throws on lowercase species (invalid block_name)', () => {
    expect(() => mintChildBlockNames({
      eventDateYYMMDD: '260522',
      speciesCode: 'koy',
      startSeq: 1,
      qty: 1,
    })).toThrow(/mint_invalid_block_name/);
  });

  test('throws on bad eventDateYYMMDD', () => {
    expect(() => mintChildBlockNames({
      eventDateYYMMDD: '2026-05-22',
      speciesCode: 'KOY',
      startSeq: 1,
      qty: 1,
    })).toThrow(/mint_invalid_block_name/);
  });
});

describe('seq-helper -- lookupLastSeqForDate', () => {
  function makePool(rows) {
    return { query: jest.fn(async () => ({ rows })) };
  }

  test('empty DB -> {ok:true, lastSeq:null, source:none}', async () => {
    const pool = makePool([]);
    const r = await lookupLastSeqForDate(pool, '2026-05-22');
    expect(r).toEqual({ ok: true, lastSeq: null, source: 'none' });
  });

  test('bad eventDate format -> {ok:false}', async () => {
    const pool = makePool([]);
    const r = await lookupLastSeqForDate(pool, '26-05-22');
    expect(r.ok).toBe(false);
  });

  test('mixed legacy seeding + seeding_session rows -> returns MAX SEQ across both', async () => {
    const rows = [
      // legacy SeedingLog
      { draft_json: { type: 'seeding', block_name: '260522_SHI_3' } },
      // new SeedingSession with two groups
      {
        draft_json: {
          type: 'seeding_session',
          event_date: '2026-05-22',
          groups: [
            {
              child_block_names: {
                value: ['260522_KOY_4', '260522_KOY_5', '260522_KOY_11'],
              },
            },
            {
              child_block_names: {
                value: ['260522_SHI_1', '260522_SHI_2'],
              },
            },
          ],
        },
      },
      // legacy seeding with a lower SEQ
      { draft_json: { type: 'seeding', block_name: '260522_SHI_7' } },
    ];
    const pool = makePool(rows);
    const r = await lookupLastSeqForDate(pool, '2026-05-22');
    expect(r.ok).toBe(true);
    expect(r.lastSeq).toBe(11);
    expect(r.source).toBe('signal_draft');
  });

  test('row with NEEDS_SEQ sentinel is skipped (not parsed as SEQ)', async () => {
    const rows = [
      {
        draft_json: {
          type: 'seeding_session',
          groups: [
            { child_block_names: { value: ['NEEDS_SEQ', 'NEEDS_SEQ'] } },
          ],
        },
      },
    ];
    const pool = makePool(rows);
    const r = await lookupLastSeqForDate(pool, '2026-05-22');
    expect(r.lastSeq).toBeNull();
  });

  test('malformed draft_json rows do not crash the lookup (skip-on-error)', async () => {
    const rows = [
      { draft_json: null },
      { draft_json: 'not an object' },
      { draft_json: { type: 'seeding_session' } }, // groups missing
      { draft_json: { type: 'seeding', block_name: '260522_KOY_8' } },
    ];
    const pool = makePool(rows);
    const r = await lookupLastSeqForDate(pool, '2026-05-22');
    expect(r.ok).toBe(true);
    expect(r.lastSeq).toBe(8);
  });

  test('issues a SELECT against signal_draft with event_date param', async () => {
    const pool = makePool([]);
    await lookupLastSeqForDate(pool, '2026-05-22');
    expect(pool.query).toHaveBeenCalledTimes(1);
    const [sql, params] = pool.query.mock.calls[0];
    expect(sql).toMatch(/FROM signal_draft/);
    expect(sql).toMatch(/event_date/);
    expect(params).toEqual(['2026-05-22']);
  });
});
