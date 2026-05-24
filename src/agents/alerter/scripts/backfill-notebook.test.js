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
