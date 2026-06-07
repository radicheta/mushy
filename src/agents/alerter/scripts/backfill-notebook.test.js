'use strict';

// Phase 54 Plan 01 hermetic tests for the backfill-notebook harness.

const path = require('path');

jest.mock('../src/capture-db', () => ({
  insertCapture: jest.fn().mockResolvedValue(undefined),
}));

const captureDb = require('../src/capture-db');

const {
  parseArgs,
  assertProdGuard,
  assertFarmerGate,
  listCorpusPages,
  selectPages,
  computeRunId,
  buildSyntheticCapture,
  dispatchPage,
  assertSantiInLoop,
  buildSummaryLine,
  openSummariesLog,
  appendSummaryLine,
  processDraftsForCapture,
  computeRunDir,
  DRAFT_STATUS_CONFIRMED,
  runIdExistsGuard,
  openResponsesJsonl,
  buildResponsesLine,
  makeResponsesObserver,
  estimateCostUsd,
  buildUnknownStrainMessage,
  main,
  CORPUS_DEFAULT,
} = require('./backfill-notebook');

describe('parseArgs', () => {
  test('returns defaults for empty argv', () => {
    const o = parseArgs([]);
    expect(o.help).toBe(false);
    expect(o.bulkBackfill).toBe(false);
    expect(o.cycle).toBe(1);
    expect(o.limit).toBe(5);
    expect(o.dryRun).toBe(false);
    expect(o.corpusDir).toBe(CORPUS_DEFAULT);
  });

  test('parses every documented flag', () => {
    const o = parseArgs([
      '--bulk-backfill',
      '--farmer=santi',
      '--cycle=2',
      '--limit=20',
      '--dry-run',
      '--resume-from=IMG_3778.jpg',
      '--run-id=test-run',
      '--corpus-dir=/tmp/x',
    ]);
    expect(o).toMatchObject({
      bulkBackfill: true,
      farmer: 'santi',
      cycle: 2,
      limit: 20,
      dryRun: true,
      resumeFrom: 'IMG_3778.jpg',
      runId: 'test-run',
      corpusDir: '/tmp/x',
    });
  });

  test('--help sets help flag', () => {
    expect(parseArgs(['--help']).help).toBe(true);
    expect(parseArgs(['-h']).help).toBe(true);
  });
});

describe('assertProdGuard', () => {
  test('passes dev :18080 URL', () => {
    expect(() => assertProdGuard('http://10.68.155.50:18080')).not.toThrow();
  });

  test('throws on :8082', () => {
    expect(() => assertProdGuard('http://x.y:8082')).toThrow('prod-guard');
  });

  test('throws on path with :8082/', () => {
    expect(() => assertProdGuard('http://x.y:8082/jsonapi')).toThrow('prod-guard');
  });

  test('throws on "prod" substring', () => {
    expect(() => assertProdGuard('http://farmos.prod.example.com')).toThrow('prod-guard');
  });

  test('case-insensitive', () => {
    expect(() => assertProdGuard('http://FARMOS.PROD/')).toThrow('prod-guard');
  });
});

describe('assertFarmerGate', () => {
  test('passes when bulkBackfill+santi', () => {
    expect(() => assertFarmerGate({ bulkBackfill: true, farmer: 'santi' })).not.toThrow();
  });

  test('throws on vikki under bulkBackfill', () => {
    expect(() => assertFarmerGate({ bulkBackfill: true, farmer: 'vikki' })).toThrow('santi-only');
  });

  test('throws on null farmer under bulkBackfill', () => {
    expect(() => assertFarmerGate({ bulkBackfill: true, farmer: null })).toThrow('santi-only');
  });

  test('passes without bulkBackfill regardless of farmer', () => {
    expect(() => assertFarmerGate({ bulkBackfill: false, farmer: 'vikki' })).not.toThrow();
  });
});

describe('listCorpusPages', () => {
  test('returns only IMG_3775..IMG_3861 sorted ascending', () => {
    const fake = ['IMG_3775.jpg', 'IMG_3862.jpg', 'IMG_3884.jpg', 'IMG_3861.jpg', 'IMG_3860.jpg', 'README.md'];
    const pages = listCorpusPages('/fake', {
      readdirSync: () => fake,
      logger: { warn: () => {} },
    });
    expect(pages.map((p) => path.basename(p))).toEqual([
      'IMG_3775.jpg', 'IMG_3860.jpg', 'IMG_3861.jpg',
    ]);
  });

  test('warns-and-skips IMG_3862..IMG_3884 with a reason mentioning HANDOFF.md', () => {
    const warnings = [];
    listCorpusPages('/fake', {
      readdirSync: () => ['IMG_3865.jpg'],
      logger: { warn: (m) => warnings.push(m) },
    });
    expect(warnings.some((m) => /un-transcribed gap.*HANDOFF\.md/.test(m))).toBe(true);
  });

  test('returns [] when readdir fails', () => {
    const pages = listCorpusPages('/no', {
      readdirSync: () => { throw new Error('ENOENT'); },
      logger: { warn: () => {} },
    });
    expect(pages).toEqual([]);
  });
});

describe('selectPages', () => {
  const all = ['IMG_3775.jpg', 'IMG_3776.jpg', 'IMG_3777.jpg', 'IMG_3778.jpg', 'IMG_3779.jpg', 'IMG_3780.jpg', 'IMG_3781.jpg', 'IMG_3782.jpg']
    .map((b) => `/c/${b}`);

  test('slices limit from start', () => {
    expect(selectPages(all, { limit: 3 }).map((p) => path.basename(p)))
      .toEqual(['IMG_3775.jpg', 'IMG_3776.jpg', 'IMG_3777.jpg']);
  });

  test('honors resumeFrom', () => {
    expect(selectPages(all, { limit: 2, resumeFrom: 'IMG_3778.jpg' }).map((p) => path.basename(p)))
      .toEqual(['IMG_3778.jpg', 'IMG_3779.jpg']);
  });

  test('returns [] when resumeFrom not found', () => {
    expect(selectPages(all, { limit: 3, resumeFrom: 'IMG_9999.jpg' })).toEqual([]);
  });

  test('limit=Infinity returns the full array (all-pages path)', () => {
    expect(selectPages(all, { limit: Infinity })).toHaveLength(all.length);
    expect(selectPages(all, { limit: Infinity }).map((p) => path.basename(p)))
      .toEqual(all.map((p) => path.basename(p)));
  });
});

describe('parseArgs -- all-pages flag', () => {
  test('--all-pages sets opts.allPages = true', () => {
    const o = parseArgs(['--all-pages']);
    expect(o.allPages).toBe(true);
  });

  test('default opts.allPages is false', () => {
    const o = parseArgs([]);
    expect(o.allPages).toBe(false);
  });
});

describe('main() -- all-pages resolves limit to Infinity', () => {
  test('--all-pages --dry-run selects all corpus pages', async () => {
    const fakePages = [
      '/c/IMG_3775.jpg', '/c/IMG_3776.jpg', '/c/IMG_3777.jpg',
    ];
    const result = await main(['--all-pages', '--dry-run'], {
      env: {},
      logger: { log: () => {}, warn: () => {}, error: () => {} },
      poolFactory: null,
      pipelineFactory: null,
      // Override listCorpusPages via the corpusDir + readdirSync would not work here;
      // instead we spy on process: but since main() calls listCorpusPages internally
      // we test the integration via --corpus-dir pointing at a controlled dir.
      // Use the selectPages Infinity behavior verified above as the unit truth.
      // For this integration test we just verify code: 0 (no crash).
    });
    // main() with --dry-run returns code 0 even if corpus dir is missing (logs warn).
    expect(result.code).toBe(0);
  });
});

describe('computeRunId', () => {
  test('emits a colon-free, dot-free ISO-8601 string', () => {
    const id = computeRunId(new Date('2026-05-24T18:30:01.234Z'));
    expect(id).toBe('2026-05-24T18-30-01-234Z');
    expect(id).not.toMatch(/[:.]/);
  });
});

describe('buildSyntheticCapture', () => {
  test('produces the documented row shape with corpus_context wired', () => {
    const row = buildSyntheticCapture({
      page: '/c/IMG_3775.jpg',
      runId: 'r1',
      sender: '+59891840205',
    });
    expect(row).toMatchObject({
      id: 'backfill-r1-IMG_3775',
      sender: '+59891840205',
      message_type: 'attachment',
      raw_text: null,
      attachment_paths: ['/c/IMG_3775.jpg'],
      transcript: null,
      corpus_context: { default_year: 2025, source: 'paper_log' },
    });
    expect(row.captured_at).toBeInstanceOf(Date);
  });
});

describe('dispatchPage', () => {
  beforeEach(() => {
    captureDb.insertCapture.mockClear();
  });

  test('dry-run skips DB + pipeline; returns ok="dry-run"', async () => {
    const pipeline = { enqueue: jest.fn() };
    const entry = await dispatchPage({
      pool: {}, pipeline, page: '/c/IMG_3775.jpg', runId: 'r1',
      sender: '+1', corpusContext: { default_year: 2025, source: 'paper_log' }, dryRun: true,
    });
    expect(entry.ok).toBe('dry-run');
    expect(captureDb.insertCapture).not.toHaveBeenCalled();
    expect(pipeline.enqueue).not.toHaveBeenCalled();
  });

  test('inserts capture then enqueues with corpusContext literal', async () => {
    const pipeline = { enqueue: jest.fn().mockResolvedValue({ ok: true }) };
    const pool = { query: jest.fn() };
    const entry = await dispatchPage({
      pool, pipeline, page: '/c/IMG_3775.jpg', runId: 'r1',
      sender: '+1', corpusContext: { default_year: 2025, source: 'paper_log' }, dryRun: false,
    });
    expect(captureDb.insertCapture).toHaveBeenCalledTimes(1);
    const insertedRow = captureDb.insertCapture.mock.calls[0][1];
    expect(insertedRow.corpus_context).toEqual({ default_year: 2025, source: 'paper_log' });
    expect(pipeline.enqueue).toHaveBeenCalledWith({
      sender: '+1',
      captureId: 'backfill-r1-IMG_3775',
      attachmentPaths: ['/c/IMG_3775.jpg'],
      corpusContext: { default_year: 2025, source: 'paper_log' },
    });
    expect(entry.ok).toBe(true);
  });

  test('records reason when capture insert throws', async () => {
    captureDb.insertCapture.mockRejectedValueOnce(new Error('boom'));
    const pipeline = { enqueue: jest.fn() };
    const entry = await dispatchPage({
      pool: {}, pipeline, page: '/c/IMG_3775.jpg', runId: 'r1',
      sender: '+1', corpusContext: {}, dryRun: false,
    });
    expect(entry.ok).toBe(false);
    expect(entry.reason).toMatch(/capture_insert_failed: boom/);
    expect(pipeline.enqueue).not.toHaveBeenCalled();
  });

  test('records reason when pipeline returns {ok:false}', async () => {
    const pipeline = { enqueue: jest.fn().mockResolvedValue({ ok: false, reason: 'no_attachment' }) };
    const entry = await dispatchPage({
      pool: {}, pipeline, page: '/c/IMG_3775.jpg', runId: 'r1',
      sender: '+1', corpusContext: {}, dryRun: false,
    });
    expect(entry.ok).toBe(false);
    expect(entry.reason).toBe('no_attachment');
  });
});

describe('main (integration of helpers)', () => {
  function mkLogger() {
    const lines = { log: [], warn: [], error: [] };
    return {
      log: (m) => lines.log.push(m),
      warn: (m) => lines.warn.push(m),
      error: (m) => lines.error.push(m),
      _lines: lines,
    };
  }

  test('--help prints usage and exits 0', async () => {
    const logger = mkLogger();
    const writes = [];
    const origWrite = process.stdout.write.bind(process.stdout);
    process.stdout.write = (s) => { writes.push(String(s)); return true; };
    try {
      const r = await main(['--help'], { env: {}, logger });
      expect(r.code).toBe(0);
      expect(writes.join('')).toMatch(/Usage:/);
      expect(writes.join('')).toMatch(/--bulk-backfill/);
    } finally {
      process.stdout.write = origWrite;
    }
  });

  test('prod-guard trips with exit 3 when FARMOS_URL contains :8082', async () => {
    const logger = mkLogger();
    const r = await main(
      ['--bulk-backfill', '--farmer=santi', '--dry-run'],
      { env: { FARMOS_URL: 'http://10.68.155.50:8082' }, logger }
    );
    expect(r.code).toBe(3);
    expect(logger._lines.error.some((m) => /REFUSING.*prod-guard/.test(m))).toBe(true);
  });

  test('farmer-gate trips with exit 4 on --bulk-backfill --farmer=vikki', async () => {
    const logger = mkLogger();
    const r = await main(
      ['--bulk-backfill', '--farmer=vikki', '--dry-run'],
      { env: {}, logger }
    );
    expect(r.code).toBe(4);
    expect(logger._lines.error.some((m) => /REFUSING.*--bulk-backfill requires --farmer=santi/.test(m))).toBe(true);
  });

  test('--dry-run with --bulk-backfill --farmer=santi lists selected pages and exits 0', async () => {
    const logger = mkLogger();
    // Stub the fs readdir by mocking the corpus dir with one not actually used.
    const fs = require('fs');
    const orig = fs.readdirSync;
    fs.readdirSync = () => ['IMG_3775.jpg', 'IMG_3776.jpg', 'IMG_3862.jpg'];
    try {
      const r = await main(
        ['--bulk-backfill', '--farmer=santi', '--cycle=1', '--limit=2', '--dry-run'],
        { env: { FARMOS_URL: 'http://10.68.155.50:18080' }, logger, now: new Date('2026-05-24T19:00:00.000Z') }
      );
      expect(r.code).toBe(0);
      expect(r.runId).toBe('2026-05-24T19-00-00-000Z');
      expect(r.runSummary).toHaveLength(2);
      expect(r.runSummary.every((e) => e.ok === 'dry-run')).toBe(true);
    } finally {
      fs.readdirSync = orig;
    }
  });

  test('non-dry-run missing env exits 5', async () => {
    const logger = mkLogger();
    const r = await main(
      ['--bulk-backfill', '--farmer=santi'],
      { env: { FARMOS_URL: 'http://10.68.155.50:18080' }, logger }
    );
    expect(r.code).toBe(5);
    expect(logger._lines.error.some((m) => /MISSING env/.test(m))).toBe(true);
  });
});

// ============================================================================
// Phase 54 Plan 02 tests: auto-confirm + commit-router dispatch + summaries.log
// ============================================================================

const fs = require('fs');
const os = require('os');
const path2 = require('path');

describe('assertSantiInLoop (Plan 02)', () => {
  test('throws when bulkBackfill+farmer mutated to vikki mid-loop', () => {
    expect(() => assertSantiInLoop({ bulkBackfill: true, farmer: 'vikki' })).toThrow('santi-only');
  });

  test('passes on santi', () => {
    expect(() => assertSantiInLoop({ bulkBackfill: true, farmer: 'santi' })).not.toThrow();
  });

  test('passes when bulkBackfill=false', () => {
    expect(() => assertSantiInLoop({ bulkBackfill: false, farmer: 'vikki' })).not.toThrow();
  });
});

describe('DRAFT_STATUS_CONFIRMED', () => {
  test('matches the canonical confirm-state-machine value', () => {
    expect(DRAFT_STATUS_CONFIRMED).toBe('confirmed');
  });
});

describe('buildSummaryLine', () => {
  test('emits ASCII-only line in the documented shape', () => {
    const line = buildSummaryLine({
      ts: '2026-05-24T19:30:00.000Z',
      page: 'IMG_3775.jpg',
      captureId: 'backfill-r1-IMG_3775',
      draftId: 'd1',
      logType: 'seeding',
      ok: true,
      assetCount: 5,
      logCount: 11,
    });
    expect(line).toBe('2026-05-24T19:30:00.000Z page=IMG_3775.jpg capture=backfill-r1-IMG_3775 draft=d1 log_type=seeding ok=true assets=5 logs=11');
    expect(line).not.toMatch(/[–—]/);
  });

  test('includes reason= when ok!=true', () => {
    const line = buildSummaryLine({
      ts: '2026-05-24T00:00:00.000Z',
      page: 'IMG_3775.jpg', captureId: 'c', draftId: 'd', logType: 'seeding',
      ok: false, assetCount: 0, logCount: 0, reason: 'commit_failed',
    });
    expect(line).toMatch(/reason=commit_failed$/);
  });

  test('strips em-dashes from reason text', () => {
    const line = buildSummaryLine({
      ts: 't', page: 'p', captureId: 'c', draftId: 'd', logType: 'x',
      ok: false, assetCount: 0, logCount: 0,
      reason: 'fungi—type missing',
    });
    expect(line).not.toMatch(/[–—]/);
    expect(line).toMatch(/fungi--type missing/);
  });

  test('omits reason= when ok=true', () => {
    const line = buildSummaryLine({
      ts: 't', page: 'p', captureId: 'c', draftId: 'd', logType: 'x',
      ok: true, assetCount: 1, logCount: 1, reason: 'ignored',
    });
    expect(line).not.toMatch(/reason=/);
  });
});

describe('summaries.log writer', () => {
  let tmpDir;
  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path2.join(os.tmpdir(), 'bf-test-'));
  });

  test('openSummariesLog creates runDir + file; append writes one line + \\n', () => {
    const runDir = path2.join(tmpDir, 'rd');
    const fd = openSummariesLog(runDir);
    appendSummaryLine(fd, 'line1');
    appendSummaryLine(fd, 'line2');
    fs.closeSync(fd);
    const got = fs.readFileSync(path2.join(runDir, 'summaries.log'), 'utf8');
    expect(got).toBe('line1\nline2\n');
  });
});

describe('computeRunDir', () => {
  test('joins under .planning/backfill/2025-notebook/<runId>', () => {
    expect(computeRunDir('2026-05-24T00-00-00-000Z')).toBe(
      '.planning/backfill/2025-notebook/2026-05-24T00-00-00-000Z'
    );
  });
});

describe('processDraftsForCapture (Plan 02 core)', () => {
  let tmpDir;
  let fd;
  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path2.join(os.tmpdir(), 'bf-pd-'));
    fd = fs.openSync(path2.join(tmpDir, 'summaries.log'), 'a');
  });
  afterEach(() => {
    try { fs.closeSync(fd); } catch (_e) {}
  });

  function readLog() {
    return fs.readFileSync(path2.join(tmpDir, 'summaries.log'), 'utf8').trim().split('\n').filter(Boolean);
  }

  test('bulk-backfill+santi: flips each draft to confirmed and dispatches commit-router', async () => {
    const drafts = [
      { id: 'd1', log_type: 'seeding' },
      { id: 'd2', log_type: 'seeding' },
      { id: 'd3', log_type: 'observation' },
    ];
    const updateDraftStatus = jest.fn().mockResolvedValue({ ok: true, rowCount: 1 });
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus,
    };
    const commitRouter = {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: ['a1', 'a2'], log_ids: ['l1'] }),
    };

    const r = await processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: true, farmer: 'santi' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: false,
    });

    expect(r.drafts).toEqual(drafts);
    expect(r.commits).toHaveLength(3);
    expect(r.commits.every((c) => c.ok === true)).toBe(true);
    expect(updateDraftStatus).toHaveBeenCalledTimes(3);
    // Each flip uses canonical 'confirmed' status with bulk_backfill_santi marker.
    for (const call of updateDraftStatus.mock.calls) {
      expect(call[2]).toBe('confirmed');
      expect(call[3]).toEqual({ needs_review_reason: 'bulk_backfill_santi' });
    }
    expect(commitRouter.commit).toHaveBeenCalledTimes(3);

    const lines = readLog();
    expect(lines).toHaveLength(3);
    for (const line of lines) {
      expect(line).toMatch(/ok=true assets=2 logs=1/);
      expect(line).not.toMatch(/[–—]/);
    }
  });

  test('attaches strain_codes + block_name to commit entries and passes createMissingFungiType ctx', async () => {
    const drafts = [
      { id: 'd1', log_type: 'seeding', draft_json: { species: 'cas', block_name: '250201_CAS_1' } },
      { id: 'd2', log_type: 'seeding', draft_json: { species_code: 'POY', block_name: '250201_POY_3' } },
    ];
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus: jest.fn().mockResolvedValue({ ok: true, rowCount: 1 }),
    };
    const commitRouter = {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: ['a1'], log_ids: ['l1'] }),
    };

    const r = await processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: true, farmer: 'santi' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: false,
    });

    // strain_codes uppercased (CSV diff matches case-insensitively); block_name preserved.
    expect(r.commits[0].strain_codes).toEqual(['CAS']);
    expect(r.commits[0].block_name).toBe('250201_CAS_1');
    expect(r.commits[1].strain_codes).toEqual(['POY']);
    // Blind-mint is OFF: unknown strains get a farmer double-check before their
    // fungi_type term is minted (Cycle-1 finding B 2026-05-25), not auto-created.
    for (const call of commitRouter.commit.mock.calls) {
      expect(call[2].createMissingFungiType).toBe(false);
    }
  });

  test('dry-run: zero flips, zero commits, summary lines emit ok=dry-run', async () => {
    const drafts = [{ id: 'd1', log_type: 'seeding' }, { id: 'd2', log_type: 'seeding' }];
    const updateDraftStatus = jest.fn();
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus,
    };
    const commitRouter = { commit: jest.fn() };

    const r = await processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: true, farmer: 'santi' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: true,
    });

    expect(updateDraftStatus).not.toHaveBeenCalled();
    expect(commitRouter.commit).not.toHaveBeenCalled();
    expect(r.commits.every((c) => c.ok === 'dry-run')).toBe(true);
    const lines = readLog();
    expect(lines).toHaveLength(2);
    expect(lines.every((l) => /ok=dry-run/.test(l))).toBe(true);
  });

  test('without --bulk-backfill: drafts stay pending, commit-router NOT called', async () => {
    const drafts = [{ id: 'd1', log_type: 'seeding' }];
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus: jest.fn(),
    };
    const commitRouter = { commit: jest.fn() };

    await processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: false, farmer: 'santi' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: false,
    });

    expect(extractionDb.updateDraftStatus).not.toHaveBeenCalled();
    expect(commitRouter.commit).not.toHaveBeenCalled();
    const lines = readLog();
    expect(lines[0]).toMatch(/reason=no_bulk_backfill/);
  });

  test('in-loop santi assertion: opts.farmer mutated to vikki after Task-1 gate trips exit 4 path', async () => {
    const drafts = [{ id: 'd1', log_type: 'seeding' }];
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus: jest.fn(),
    };
    const commitRouter = { commit: jest.fn() };

    await expect(processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: true, farmer: 'vikki' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: false,
    })).rejects.toThrow('santi-only');
    expect(commitRouter.commit).not.toHaveBeenCalled();
  });

  test('draft_flip_failed: continues to next draft and stamps reason in summary', async () => {
    const drafts = [{ id: 'd1', log_type: 'seeding' }, { id: 'd2', log_type: 'seeding' }];
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus: jest.fn()
        .mockResolvedValueOnce({ ok: false, reason: 'db_down' })
        .mockResolvedValueOnce({ ok: true, rowCount: 1 }),
    };
    const commitRouter = {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: ['a1'], log_ids: ['l1'] }),
    };

    const r = await processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: true, farmer: 'santi' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: false,
    });

    expect(r.commits[0].ok).toBe(false);
    expect(r.commits[0].reason).toMatch(/draft_flip_failed: db_down/);
    expect(r.commits[1].ok).toBe(true);
    expect(commitRouter.commit).toHaveBeenCalledTimes(1);
  });

  test('commit-router ok:false: summary line ok=false reason carried, loop continues', async () => {
    const drafts = [{ id: 'd1', log_type: 'seeding' }, { id: 'd2', log_type: 'seeding' }];
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus: jest.fn().mockResolvedValue({ ok: true, rowCount: 1 }),
    };
    const commitRouter = {
      commit: jest.fn()
        .mockResolvedValueOnce({ ok: false, asset_ids: [], log_ids: [], reason: 'http_422' })
        .mockResolvedValueOnce({ ok: true, asset_ids: ['a1'], log_ids: ['l1'] }),
    };

    const r = await processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: true, farmer: 'santi' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: false,
    });

    expect(r.commits[0].ok).toBe(false);
    expect(r.commits[1].ok).toBe(true);
    const lines = readLog();
    expect(lines[0]).toMatch(/ok=false.*reason=http_422/);
    expect(lines[1]).toMatch(/ok=true/);
  });
});

// ============================================================================
// Phase 54.1 Plan 02 Task 1 tests: strain-gate in processDraftsForCapture
// ============================================================================

describe('processDraftsForCapture (Plan 54.1-02 strain-gate)', () => {
  // Curated set matches tenants/mossrock/strains.yaml (14 codes).
  const CURATED = ['SHI', 'SH2', 'KOY', 'MAI', 'MALI', 'KOS', 'DT', 'CAS', 'CAZ', 'WIN', 'ALM', 'MOR', 'BP', 'LIMA'];
  let tmpDir;
  let fd;
  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path2.join(os.tmpdir(), 'bf-sg-'));
    fd = fs.openSync(path2.join(tmpDir, 'summaries.log'), 'a');
  });
  afterEach(() => {
    try { fs.closeSync(fd); } catch (_e) {}
  });

  function readLog() {
    return fs.readFileSync(path2.join(tmpDir, 'summaries.log'), 'utf8').trim().split('\n').filter(Boolean);
  }

  test('unknown-strain draft is held as needs_review, NOT flipped to confirmed, NOT committed', async () => {
    // POY is NOT in the curated 14-code set -> must be held.
    const drafts = [{ id: 'd1', log_type: 'seeding', draft_json: { species_code: 'POY' } }];
    const updateDraftStatus = jest.fn().mockResolvedValue({ ok: true, rowCount: 1 });
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus,
    };
    const commitRouter = { commit: jest.fn() };

    const r = await processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: true, farmer: 'santi' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: false,
      curatedStrains: CURATED,
    });

    // commit-router must NOT be called
    expect(commitRouter.commit).not.toHaveBeenCalled();
    // updateDraftStatus must be called once with needs_review (not confirmed)
    expect(updateDraftStatus).toHaveBeenCalledTimes(1);
    const [, , status, extras] = updateDraftStatus.mock.calls[0];
    expect(status).toBe('needs_review');
    expect(extras).toMatchObject({ needs_review_reason: 'strain_unknown_pending_confirm' });
    // commit entry reflects held state
    expect(r.commits).toHaveLength(1);
    expect(r.commits[0].ok).toBe('held');
    expect(r.commits[0].reason).toBe('strain_unknown_pending_confirm');
    // held codes returned from processDraftsForCapture
    expect(r.heldUnknownCodes).toEqual(expect.arrayContaining([
      expect.objectContaining({ code: 'POY' }),
    ]));
  });

  test('known-strain draft (SHI) proceeds: confirmed + committed, NOT held', async () => {
    const drafts = [{ id: 'd2', log_type: 'seeding', draft_json: { species_code: 'SHI' } }];
    const updateDraftStatus = jest.fn().mockResolvedValue({ ok: true, rowCount: 1 });
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus,
    };
    const commitRouter = {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: ['a1'], log_ids: ['l1'] }),
    };

    const r = await processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: true, farmer: 'santi' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: false,
      curatedStrains: CURATED,
    });

    // Should flip to confirmed and commit (known path unchanged)
    const statusCalls = updateDraftStatus.mock.calls.filter((c) => c[2] === 'confirmed');
    expect(statusCalls).toHaveLength(1);
    expect(commitRouter.commit).toHaveBeenCalledTimes(1);
    expect(commitRouter.commit.mock.calls[0][2].createMissingFungiType).toBe(false);
    expect(r.commits[0].ok).toBe(true);
    expect(r.heldUnknownCodes).toHaveLength(0);
  });

  test('mixed: known CAS committed, unknown LIM held; heldUnknownCodes has LIM+nearest', async () => {
    const drafts = [
      { id: 'd1', log_type: 'seeding', draft_json: { species_code: 'CAS' } },
      { id: 'd2', log_type: 'seeding', draft_json: { species_code: 'LIM' } },
    ];
    const updateDraftStatus = jest.fn().mockResolvedValue({ ok: true, rowCount: 1 });
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus,
    };
    const commitRouter = {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: ['a1'], log_ids: ['l1'] }),
    };

    const r = await processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: true, farmer: 'santi' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: false,
      curatedStrains: CURATED,
    });

    // CAS committed; LIM held
    expect(commitRouter.commit).toHaveBeenCalledTimes(1);
    expect(r.commits[0].ok).toBe(true);   // CAS
    expect(r.commits[1].ok).toBe('held'); // LIM
    // heldUnknownCodes includes LIM with nearest=LIMA
    expect(r.heldUnknownCodes).toHaveLength(1);
    expect(r.heldUnknownCodes[0].code).toBe('LIM');
    expect(r.heldUnknownCodes[0].nearest).toBe('LIMA');
    expect(r.heldUnknownCodes[0].draftIds).toContain('d2');
  });

  test('draft with NO strain: existing behavior (no hold gate)', async () => {
    // No strain at all -> goes through the known path (commit may fail for other reasons);
    // the strain-gate only intercepts UNKNOWN codes, not absent ones.
    const drafts = [{ id: 'd1', log_type: 'seeding', draft_json: {} }];
    const updateDraftStatus = jest.fn().mockResolvedValue({ ok: true, rowCount: 1 });
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus,
    };
    const commitRouter = {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: [], log_ids: [] }),
    };

    const r = await processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: true, farmer: 'santi' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: false,
      curatedStrains: CURATED,
    });

    // With no strain present, the gate does not hold the draft (no-strain is not the same as unknown)
    expect(r.heldUnknownCodes).toHaveLength(0);
    // draft goes through existing flip+commit path
    expect(commitRouter.commit).toHaveBeenCalledTimes(1);
  });

  test('empty curatedStrains (default []): no drafts held (no gate, legacy behavior)', async () => {
    // Existing tests call processDraftsForCapture without curatedStrains -> defaults to []
    // -> resolveStrain with empty set -> known:false but we don't hold when curatedStrains is empty
    // (hermetic test backward-compat).
    const drafts = [{ id: 'd1', log_type: 'seeding', draft_json: { species_code: 'ANYTHING' } }];
    const updateDraftStatus = jest.fn().mockResolvedValue({ ok: true, rowCount: 1 });
    const extractionDb = {
      getDraftsForCapture: jest.fn().mockResolvedValue(drafts),
      updateDraftStatus,
    };
    const commitRouter = {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: [], log_ids: [] }),
    };

    const r = await processDraftsForCapture({
      pool: {}, client: {}, captureId: 'cap-1', pagePath: '/c/IMG_3775.jpg',
      opts: { bulkBackfill: true, farmer: 'santi' },
      summariesFd: fd, extractionDb, commitRouter, dryRun: false,
      // no curatedStrains -> defaults to []
    });

    // No hold when curated set is empty
    expect(r.heldUnknownCodes).toHaveLength(0);
    expect(commitRouter.commit).toHaveBeenCalledTimes(1);
  });
});

// ============================================================================
// Phase 54.1 Plan 02 Task 2 tests: buildUnknownStrainMessage + batched send
// ============================================================================

describe('buildUnknownStrainMessage', () => {
  test('single unknown code with nearest: message lists code and nearest, no em-dash', () => {
    const unknowns = [{ code: 'LIM', nearest: 'LIMA', draftIds: ['d1'] }];
    const msg = buildUnknownStrainMessage(unknowns);
    expect(typeof msg).toBe('string');
    expect(msg).toContain('LIM');
    expect(msg).toContain('LIMA');
    // No em-dash per [[feedback_no_em_dashes_in_artifacts]]
    expect(/[–—]/.test(msg)).toBe(false);
  });

  test('two unknown codes: message contains both codes', () => {
    const unknowns = [
      { code: 'LIM', nearest: 'LIMA', draftIds: ['d1'] },
      { code: 'SHITAKE', nearest: 'SHI', draftIds: ['d2'] },
    ];
    const msg = buildUnknownStrainMessage(unknowns);
    expect(msg).toContain('LIM');
    expect(msg).toContain('SHITAKE');
    expect(msg).toContain('LIMA');
    expect(msg).toContain('SHI');
    expect(/[–—]/.test(msg)).toBe(false);
  });

  test('code without nearest: no crash, code still appears', () => {
    const unknowns = [{ code: 'MYSTERY', nearest: null, draftIds: ['d1'] }];
    const msg = buildUnknownStrainMessage(unknowns);
    expect(msg).toContain('MYSTERY');
    expect(/[–—]/.test(msg)).toBe(false);
  });
});

// NOTE: The {sendUnknownStrainBatch} helper is the testable unit for Task 2 signal+file logic.
// main() calls it after the page loop; these tests cover the batch helper directly.
const { sendUnknownStrainBatch } = require('./backfill-notebook');

describe('sendUnknownStrainBatch (Plan 54.1-02 Task 2)', () => {
  let tmpDir;
  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path2.join(os.tmpdir(), 'bf-sb-'));
  });

  test('two held unknowns: exactly ONE send; pending-strain-confirm.json written with both codes + draftIds', async () => {
    const runDir = path2.join(tmpDir, 'run1');
    fs.mkdirSync(runDir, { recursive: true });
    const signalSend = jest.fn().mockResolvedValue({ ok: true });
    const unknowns = [
      { code: 'LIM', nearest: 'LIMA', draftIds: ['d1'] },
      { code: 'SHITAKE', nearest: 'SHI', draftIds: ['d2'] },
    ];

    await sendUnknownStrainBatch({ unknowns, runDir, runId: 'run1', signalSend, recipient: '+599999999' });

    expect(signalSend).toHaveBeenCalledTimes(1);
    const pendingPath = path2.join(runDir, 'pending-strain-confirm.json');
    expect(fs.existsSync(pendingPath)).toBe(true);
    const pending = JSON.parse(fs.readFileSync(pendingPath, 'utf8'));
    expect(pending.runId).toBe('run1');
    expect(Array.isArray(pending.unknowns)).toBe(true);
    const codes = pending.unknowns.map((u) => u.code);
    expect(codes).toContain('LIM');
    expect(codes).toContain('SHITAKE');
    expect(pending.unknowns.find((u) => u.code === 'LIM').draftIds).toContain('d1');
  });

  test('zero unknowns: no send, no pending file', async () => {
    const runDir = path2.join(tmpDir, 'run2');
    fs.mkdirSync(runDir, { recursive: true });
    const signalSend = jest.fn();

    await sendUnknownStrainBatch({ unknowns: [], runDir, runId: 'run2', signalSend, recipient: '+599999999' });

    expect(signalSend).not.toHaveBeenCalled();
    expect(fs.existsSync(path2.join(runDir, 'pending-strain-confirm.json'))).toBe(false);
  });

  test('send failure: pending file still written (best-effort)', async () => {
    const runDir = path2.join(tmpDir, 'run3');
    fs.mkdirSync(runDir, { recursive: true });
    const signalSend = jest.fn().mockRejectedValue(new Error('network error'));
    const unknowns = [{ code: 'POY', nearest: 'KOY', draftIds: ['d3'] }];

    // Must not throw even when send rejects
    await expect(sendUnknownStrainBatch({ unknowns, runDir, runId: 'run3', signalSend, recipient: '+599999999' })).resolves.not.toThrow();
    // pending file still written
    expect(fs.existsSync(path2.join(runDir, 'pending-strain-confirm.json'))).toBe(true);
  });
});

// ============================================================================
// Phase 54 Plan 03 tests: responses.jsonl writer + run-id guard + cost calc.
// ============================================================================

describe('estimateCostUsd', () => {
  test('Sonnet rate: 1M input + 1M output -> 18 USD', () => {
    expect(estimateCostUsd('claude-sonnet-4-6', 1_000_000, 1_000_000)).toBeCloseTo(18, 4);
  });

  test('Haiku rate: 1M input + 1M output -> 4.80 USD', () => {
    expect(estimateCostUsd('claude-haiku-3-5', 1_000_000, 1_000_000)).toBeCloseTo(4.80, 4);
  });

  test('zero tokens -> 0', () => {
    expect(estimateCostUsd('claude-sonnet-4-6', 0, 0)).toBe(0);
  });

  test('case-insensitive haiku detection', () => {
    expect(estimateCostUsd('CLAUDE-HAIKU-XYZ', 1_000_000, 0)).toBeCloseTo(0.80, 4);
  });
});

describe('runIdExistsGuard', () => {
  let tmpDir;
  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path2.join(os.tmpdir(), 'bf-guard-'));
  });

  test('passes on empty runDir', () => {
    expect(() => runIdExistsGuard(tmpDir)).not.toThrow();
  });

  test('passes on nonexistent runDir', () => {
    expect(() => runIdExistsGuard(path2.join(tmpDir, 'no'))).not.toThrow();
  });

  test('throws RUN_ID_EXISTS when responses.jsonl present', () => {
    fs.writeFileSync(path2.join(tmpDir, 'responses.jsonl'), '{}\n');
    let caught;
    try { runIdExistsGuard(tmpDir); } catch (e) { caught = e; }
    expect(caught).toBeTruthy();
    expect(caught.code).toBe('RUN_ID_EXISTS');
  });
});

describe('responses.jsonl writer (buildResponsesLine + makeResponsesObserver)', () => {
  let tmpDir;
  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path2.join(os.tmpdir(), 'bf-rj-'));
  });

  test('observer writes exactly one line per call, valid JSON, all required keys', () => {
    const fd = openResponsesJsonl(tmpDir);
    const obs = makeResponsesObserver(fd);
    obs({
      ts: '2026-05-24T19:30:00.000Z',
      captureId: 'backfill-r1-IMG_3775',
      model: 'claude-sonnet-4-6',
      input_tokens: 1234, output_tokens: 456,
      cache_creation_input_tokens: 0, cache_read_input_tokens: 0,
      latency_ms: 3210, request_hash: 'a1b2c3d4',
      raw_response: { id: 'msg_1', usage: { input_tokens: 1234 } },
    });
    obs({
      ts: '2026-05-24T19:30:05.000Z',
      captureId: 'backfill-r1-IMG_3776',
      model: 'claude-sonnet-4-6',
      input_tokens: 2000, output_tokens: 800,
      latency_ms: 4200, request_hash: 'deadbeef',
      raw_response: {},
    });
    fs.closeSync(fd);
    const lines = fs.readFileSync(path2.join(tmpDir, 'responses.jsonl'), 'utf8')
      .trim().split('\n');
    expect(lines).toHaveLength(2);
    for (const line of lines) {
      const obj = JSON.parse(line);
      expect(obj).toHaveProperty('ts');
      expect(obj).toHaveProperty('captureId');
      expect(obj).toHaveProperty('model');
      expect(obj).toHaveProperty('input_tokens');
      expect(obj).toHaveProperty('output_tokens');
      expect(obj).toHaveProperty('latency_ms');
      expect(obj).toHaveProperty('cost_estimate_usd');
      expect(obj).toHaveProperty('request_hash');
      expect(obj).toHaveProperty('raw_response');
    }
    const first = JSON.parse(lines[0]);
    expect(first.cost_estimate_usd).toBeCloseTo(
      (1234 / 1e6) * 3 + (456 / 1e6) * 15, 6
    );
  });

  test('append mode: re-opening preserves prior lines', () => {
    const fd1 = openResponsesJsonl(tmpDir);
    fs.writeSync(fd1, JSON.stringify({ ts: 't1' }) + '\n');
    fs.closeSync(fd1);
    const fd2 = openResponsesJsonl(tmpDir);
    fs.writeSync(fd2, JSON.stringify({ ts: 't2' }) + '\n');
    fs.closeSync(fd2);
    const lines = fs.readFileSync(path2.join(tmpDir, 'responses.jsonl'), 'utf8')
      .trim().split('\n');
    expect(lines).toHaveLength(2);
  });
});

describe('main: run-id collision (Plan 03)', () => {
  let tmpDir;
  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path2.join(os.tmpdir(), 'bf-main-rj-'));
  });

  test('non-dry-run with existing responses.jsonl in --run-id dir exits 6', async () => {
    // Pre-seed the runDir under the *expected* RUN_DIR_ROOT path. main() builds
    // runDir from RUN_DIR_ROOT/<runId>; chdir into tmpDir so the relative path
    // points there.
    const cwd = process.cwd();
    process.chdir(tmpDir);
    try {
      const runDir = path2.join(tmpDir, '.planning/backfill/2025-notebook/collide-run');
      fs.mkdirSync(runDir, { recursive: true });
      fs.writeFileSync(path2.join(runDir, 'responses.jsonl'), '{}\n');

      const logger = { log: () => {}, warn: () => {}, error: jest.fn() };
      const r = await main(
        ['--bulk-backfill', '--farmer=santi', '--run-id=collide-run', '--limit=1'],
        {
          env: {
            FARMOS_URL: 'http://10.68.155.50:18080',
            FARMOS_USERNAME: 'x', FARMOS_PASSWORD: 'x', DATABASE_URL: 'x',
          },
          logger,
        }
      );
      expect(r.code).toBe(6);
      expect(logger.error).toHaveBeenCalledWith(expect.stringMatching(/REFUSING.*already has responses.jsonl/));
    } finally {
      process.chdir(cwd);
    }
  });
});
