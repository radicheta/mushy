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
