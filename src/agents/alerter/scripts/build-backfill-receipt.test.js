'use strict';

// Phase 54 Plan 04 hermetic tests for the backfill receipt builder.

const fs = require('fs');
const os = require('os');
const path = require('path');

const {
  parseCsv,
  loadCsvForPage,
  computeCsvDiff,
  renderPageSection,
  computeAggregate,
  buildReceipt,
} = require('./build-backfill-receipt');

describe('parseCsv', () => {
  test('parses header + rows; handles quoted notes field', () => {
    const text = `page_date,entry_num,strain,source,notes
2025-02-01,1,CAS,1-08-23,
2025-02-01,2,LIMA,12-15-28,"big, fat notes"
`;
    const rows = parseCsv(text);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({ page_date: '2025-02-01', entry_num: '1', strain: 'CAS', source: '1-08-23', notes: '' });
    expect(rows[1].notes).toBe('big, fat notes');
  });
});

describe('loadCsvForPage', () => {
  let tmpFile;
  beforeEach(() => {
    tmpFile = path.join(os.tmpdir(), `bf-csv-${Date.now()}.csv`);
    fs.writeFileSync(tmpFile, `page_date,entry_num,strain,source,notes
2025-02-01,1,CAS,a,
2025-02-01,2,LIMA,b,
2025-02-04,1,SHI,c,
`);
  });
  afterEach(() => { try { fs.unlinkSync(tmpFile); } catch (_e) {} });

  test('filters to page_date', () => {
    const rows = loadCsvForPage(tmpFile, '2025-02-01');
    expect(rows).toHaveLength(2);
    expect(rows.every((r) => r.page_date === '2025-02-01')).toBe(true);
  });

  test('returns [] for unknown date', () => {
    expect(loadCsvForPage(tmpFile, '1999-01-01')).toEqual([]);
  });

  test('returns [] when CSV unreadable', () => {
    expect(loadCsvForPage('/no/such/file.csv', '2025-02-01')).toEqual([]);
  });
});

describe('computeCsvDiff', () => {
  test('3 hits, 1 miss, 0 extras', () => {
    const csvRowsForPage = [
      { page_date: '2025-02-01', strain: 'CAS' },
      { page_date: '2025-02-01', strain: 'LIMA' },
      { page_date: '2025-02-01', strain: 'SHI' },
      { page_date: '2025-02-01', strain: 'MOR' },
    ];
    const committedAssets = [
      { strain_codes: ['CAS'] },
      { strain_codes: ['LIMA'] },
      { strain_codes: ['SHI'] },
    ];
    const diff = computeCsvDiff({ csvRowsForPage, committedAssets });
    expect(diff.hit).toBe(3);
    expect(diff.miss).toBe(1);
    expect(diff.extra).toBe(0);
    expect(diff.missing_strain_codes).toEqual(['MOR(1)']);
  });

  test('extra strain present in commits not in CSV', () => {
    const csvRowsForPage = [{ strain: 'CAS' }];
    const committedAssets = [{ strain_codes: ['CAS'] }, { strain_codes: ['DT'] }];
    const diff = computeCsvDiff({ csvRowsForPage, committedAssets });
    expect(diff.hit).toBe(1);
    expect(diff.extra).toBe(1);
    expect(diff.extra_strain_codes).toContain('DT(1)');
  });

  test('case-insensitive match', () => {
    const diff = computeCsvDiff({
      csvRowsForPage: [{ strain: 'cas' }],
      committedAssets: [{ strain_codes: ['CAS'] }],
    });
    expect(diff.hit).toBe(1);
  });
});

describe('renderPageSection', () => {
  test('emits ASCII block with diff line', () => {
    const md = renderPageSection({
      pagePath: '/c/IMG_3775.jpg',
      pageDate: '2025-02-01',
      draftIds: ['d1'],
      commits: [{ ok: true, asset_ids: ['u1', 'u2'], log_ids: ['l1'], strain_codes: ['CAS'] }],
    }, [{ strain: 'CAS' }]);
    expect(md).toMatch(/### IMG_3775\.jpg \(2025-02-01\)/);
    expect(md).toMatch(/drafts: 1/);
    expect(md).toMatch(/commits: 1 ok, 0 fail/);
    expect(md).toMatch(/assets created: 2/);
    expect(md).toMatch(/logs created: 1/);
    expect(md).toMatch(/CSV diff: 1 hit \/ 0 miss \/ 0 extra/);
    expect(md).not.toMatch(/[–—]/);
  });

  test('renders N/A when no CSV ground truth', () => {
    const md = renderPageSection({
      pagePath: '/c/IMG_3900.jpg',
      pageDate: '2026-01-01',
      draftIds: ['d1'],
      commits: [{ ok: true, asset_ids: [], log_ids: [], strain_codes: [] }],
    }, null);
    expect(md).toMatch(/CSV diff: N\/A \(no ground truth\)/);
  });

  test('lists 3 hits + 1 miss with the missing strain code', () => {
    const md = renderPageSection({
      pagePath: '/c/IMG_3775.jpg',
      pageDate: '2025-02-01',
      draftIds: ['d1','d2','d3'],
      commits: [
        { ok: true, asset_ids: ['a1'], log_ids: ['l1'], strain_codes: ['CAS'] },
        { ok: true, asset_ids: ['a2'], log_ids: ['l2'], strain_codes: ['LIMA'] },
        { ok: true, asset_ids: ['a3'], log_ids: ['l3'], strain_codes: ['SHI'] },
      ],
    }, [
      { strain: 'CAS' }, { strain: 'LIMA' }, { strain: 'SHI' }, { strain: 'MOR' },
    ]);
    expect(md).toMatch(/CSV diff: 3 hit \/ 1 miss \/ 0 extra/);
    expect(md).toMatch(/missing: MOR\(1\)/);
  });
});

describe('computeAggregate (Phase 51 upsert stability + duplicate count)', () => {
  test('tallies pages, drafts, assets, logs, per_strain', () => {
    const runSummary = [
      {
        pagePath: '/c/IMG_1.jpg',
        draftIds: ['d1', 'd2'],
        commits: [
          { ok: true, asset_ids: ['u1'], log_ids: ['l1'], strain_codes: ['SHI'], block_name: 'A' },
          { ok: true, asset_ids: ['u2'], log_ids: ['l2'], strain_codes: ['SHI'], block_name: 'B' },
        ],
      },
      {
        pagePath: '/c/IMG_2.jpg',
        draftIds: ['d3'],
        commits: [
          { ok: true, asset_ids: ['u3'], log_ids: ['l3'], strain_codes: ['CAS'], block_name: 'C' },
        ],
      },
    ];
    const agg = computeAggregate(runSummary, []);
    expect(agg.pages).toBe(2);
    expect(agg.drafts).toBe(3);
    expect(agg.assets_created).toBe(3);
    expect(agg.logs_created).toBe(3);
    expect(agg.per_strain).toEqual({ SHI: 2, CAS: 1 });
  });

  test('upsert_stability: same block_name twice resolving to the SAME UUID is stable', () => {
    const runSummary = [{
      pagePath: '/c/IMG_1.jpg', draftIds: ['d1', 'd2'],
      commits: [
        { ok: true, asset_ids: ['u-A'], block_name: '0218-3' },
        { ok: true, asset_ids: ['u-A'], block_name: '0218-3' },
      ],
    }];
    const agg = computeAggregate(runSummary, []);
    expect(agg.upsert_stability).toEqual({ checked: 1, stable: 1, unstable: [] });
  });

  test('upsert_stability: same block_name twice with TWO UUIDs is unstable', () => {
    const runSummary = [{
      pagePath: '/c/IMG_1.jpg', draftIds: ['d1', 'd2'],
      commits: [
        { ok: true, asset_ids: ['u-A1'], block_name: '0218-3' },
        { ok: true, asset_ids: ['u-A2'], block_name: '0218-3' },
      ],
    }];
    const agg = computeAggregate(runSummary, []);
    expect(agg.upsert_stability.checked).toBe(1);
    expect(agg.upsert_stability.stable).toBe(0);
    expect(agg.upsert_stability.unstable).toHaveLength(1);
    expect(agg.upsert_stability.unstable[0].block_name).toBe('0218-3');
    expect(agg.upsert_stability.unstable[0].uuids.sort()).toEqual(['u-A1', 'u-A2']);
  });

  test('duplicate_asset_count: same UUID across DIFFERENT block_names is a duplicate', () => {
    const runSummary = [{
      pagePath: '/c/IMG_1.jpg', draftIds: ['d1', 'd2'],
      commits: [
        { ok: true, asset_ids: ['shared'], block_name: 'X' },
        { ok: true, asset_ids: ['shared'], block_name: 'Y' },
      ],
    }];
    const agg = computeAggregate(runSummary, []);
    expect(agg.duplicate_asset_count).toBe(1);
  });

  test('duplicate_asset_count: same UUID + same block_name is NOT a duplicate (expected reuse)', () => {
    const runSummary = [{
      pagePath: '/c/IMG_1.jpg', draftIds: ['d1', 'd2'],
      commits: [
        { ok: true, asset_ids: ['reused'], block_name: 'X' },
        { ok: true, asset_ids: ['reused'], block_name: 'X' },
      ],
    }];
    const agg = computeAggregate(runSummary, []);
    expect(agg.duplicate_asset_count).toBe(0);
  });

  test('unknown_strain_codes flags non-active strains', () => {
    const runSummary = [{
      pagePath: '/c/IMG_1.jpg', draftIds: ['d1'],
      commits: [
        { ok: true, asset_ids: ['u'], strain_codes: ['SHI', 'FAKE'], block_name: 'A' },
      ],
    }];
    const agg = computeAggregate(runSummary, []);
    expect(agg.unknown_strain_codes).toContain('FAKE');
    expect(agg.unknown_strain_codes).not.toContain('SHI');
  });
});

describe('buildReceipt', () => {
  let tmpDir;
  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-receipt-'));
  });

  test('writes runDir/receipt.md with header + per-page + aggregate sections; ASCII-only', () => {
    const runSummary = [
      {
        pagePath: '/c/IMG_3775.jpg',
        pageDate: '2025-02-01',
        draftIds: ['d1'],
        commits: [{ ok: true, asset_ids: ['u1'], log_ids: ['l1'], strain_codes: ['CAS'], block_name: '1-08-23' }],
      },
    ];
    const receiptPath = buildReceipt({
      runDir: tmpDir,
      runSummary,
      csvPath: null,
      runId: '2026-05-24T19-00-00-000Z',
      cycleNumber: 1,
      farmosUrl: 'http://10.68.155.50:18080',
      elapsedSec: 12,
      generatedAt: '2026-05-24T19:00:12.000Z',
    });
    expect(fs.existsSync(receiptPath)).toBe(true);
    const md = fs.readFileSync(receiptPath, 'utf8');
    expect(md).toMatch(/# Backfill Receipt -- Cycle 1/);
    expect(md).toMatch(/duplicate_asset_count: 0 \(PASS\)/);
    expect(md).toMatch(/upsert stability/);
    expect(md).toMatch(/IMG_3775\.jpg/);
    expect(md).not.toMatch(/[–—]/);
  });

  test('em-dashes in upstream data scrubbed to "--"', () => {
    const runSummary = [{
      pagePath: '/c/IMG_3775.jpg',
      pageDate: '2025-02-01',
      draftIds: ['d1'],
      commits: [{ ok: false, asset_ids: [], log_ids: [], reason: 'fungi—type missing', draftId: 'd1' }],
    }];
    buildReceipt({
      runDir: tmpDir, runSummary, csvPath: null, runId: 'r1', cycleNumber: 1,
    });
    const md = fs.readFileSync(path.join(tmpDir, 'receipt.md'), 'utf8');
    expect(md).not.toMatch(/[–—]/);
    expect(md).toMatch(/fungi--type missing/);
  });

  test('failure (unstable upsert) reflected in aggregate section', () => {
    const runSummary = [{
      pagePath: '/c/IMG_3775.jpg', pageDate: '2025-02-01', draftIds: ['d1', 'd2'],
      commits: [
        { ok: true, asset_ids: ['uA'], block_name: 'X' },
        { ok: true, asset_ids: ['uB'], block_name: 'X' },
      ],
    }];
    buildReceipt({ runDir: tmpDir, runSummary, csvPath: null, runId: 'r1', cycleNumber: 1 });
    const md = fs.readFileSync(path.join(tmpDir, 'receipt.md'), 'utf8');
    expect(md).toMatch(/unstable: 1 \(FAIL -- Phase 51 contract regression\)/);
  });
});
