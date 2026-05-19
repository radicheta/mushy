'use strict';

// Backlog 999.53 Task 3: extraction pipeline stamps Anthropic token usage onto
// the originating signal_capture row when extractor.extract() resolves with
// ok:true + a non-null usage object.
//
// Best-effort by design: UPDATE failure is logged and swallowed; the pipeline
// never degrades on a usage-only write hiccup. Degraded extractor result and
// missing-usage paths skip the UPDATE entirely.

const { createExtractionPipeline } = require('../../src/extraction/pipeline');
const { DRAFT_STATUS } = require('../../src/extraction/state-machine');

function makeBaseDeps({ extractResult, poolQueryImpl } = {}) {
  const calls = [];
  const pool = {
    query: jest.fn(async (sql, params) => {
      calls.push([sql, params]);
      if (poolQueryImpl) return poolQueryImpl(sql, params);
      return { rows: [], rowCount: 1 };
    }),
  };
  const extractor = {
    extract: jest.fn(async () => extractResult),
  };
  const extractionDb = {
    getInFlightForSender: jest.fn(async () => null),
    insertDraft: jest.fn(async () => ({ ok: true })),
    updateDraftStatus: jest.fn(async () => ({ ok: true })),
    advanceAskbackTurn: jest.fn(async () => ({ ok: true })),
    computeDraftId: jest.fn((sourceIds, idx) => `draft-${(sourceIds || []).join('-')}-${idx || 0}`),
  };
  const stateMachine = {
    forceStartNewIfIdle: jest.fn(() => null),
    transition: jest.fn(() => ({
      nextStatus: DRAFT_STATUS.AWAITING_FARMER,
      side_effects: [],
      nextAskbackTurns: 0,
      reason: 'ok',
      askBackInfo: { missingFields: [], lowConfFields: [] },
    })),
  };
  const previewBuilder = { buildPreview: jest.fn(() => 'preview') };
  const config = {
    draftIdleGapMin: 60,
    extractionConfidenceThreshold: 0.7,
    maxAskbackTurns: 3,
  };
  const logger = { info: jest.fn(), warn: jest.fn(), error: jest.fn() };

  const pipeline = createExtractionPipeline({
    pool,
    extractor,
    extractionDb,
    stateMachine,
    previewBuilder,
    config,
    logger,
  });
  return { pipeline, pool, extractor, extractionDb, stateMachine, logger, calls };
}

const captureCtx = {
  captureId: 'CAP-001',
  sender: '+15555550001',
  farmosPerson: 'f2',
  text: 'logged 3 jars',
  transcripts: [],
  attachmentPaths: [],
  replyTargetKind: 'dm',
  groupId: null,
  capturedAtMs: Date.parse('2026-05-18T12:00:00Z'),
};

describe('extraction pipeline -- 999.53 usage stamp', () => {
  test('ok + usage object: issues UPDATE signal_capture SET input_tokens ... WHERE id = captureId', async () => {
    const { pipeline, pool } = makeBaseDeps({
      extractResult: {
        ok: true,
        drafts: [{ draft: { type: 'observation' }, per_field_confidence: {} }],
        draft: { type: 'observation' },
        per_field_confidence: {},
        continuity_decision: 'start_new',
        usage: {
          input_tokens: 3500,
          output_tokens: 250,
          cache_creation_input_tokens: 200,
          cache_read_input_tokens: 1800,
        },
      },
    });

    // Use single-draft path (drafts.length === 1) -- batch mode only runs for >1.
    await pipeline.enqueue(captureCtx);

    const updateCall = pool.query.mock.calls.find(
      (c) => /UPDATE signal_capture\s+SET input_tokens/.test(c[0])
    );
    expect(updateCall).toBeDefined();
    const [sql, params] = updateCall;
    expect(sql).toMatch(/output_tokens/);
    expect(sql).toMatch(/cache_creation_input_tokens/);
    expect(sql).toMatch(/cache_read_input_tokens/);
    expect(sql).toMatch(/model = \$5/);
    expect(sql).toMatch(/WHERE id = \$6/);
    expect(params).toEqual([3500, 250, 200, 1800, 'claude-sonnet-4-6', 'CAP-001']);
  });

  test('ok + usage with missing fields: missing fields bind null', async () => {
    const { pipeline, pool } = makeBaseDeps({
      extractResult: {
        ok: true,
        drafts: [{ draft: { type: 'observation' }, per_field_confidence: {} }],
        draft: { type: 'observation' },
        per_field_confidence: {},
        continuity_decision: 'start_new',
        usage: { input_tokens: 500, output_tokens: 30 },
      },
    });
    await pipeline.enqueue(captureCtx);
    const updateCall = pool.query.mock.calls.find(
      (c) => /UPDATE signal_capture\s+SET input_tokens/.test(c[0])
    );
    expect(updateCall).toBeDefined();
    const [, params] = updateCall;
    expect(params[0]).toBe(500);
    expect(params[1]).toBe(30);
    expect(params[2]).toBeNull();
    expect(params[3]).toBeNull();
    expect(params[4]).toBe('claude-sonnet-4-6');
    expect(params[5]).toBe('CAP-001');
  });

  test('ok but usage:null: no usage UPDATE issued (avoid all-null writes)', async () => {
    const { pipeline, pool } = makeBaseDeps({
      extractResult: {
        ok: true,
        drafts: [{ draft: { type: 'observation' }, per_field_confidence: {} }],
        draft: { type: 'observation' },
        per_field_confidence: {},
        continuity_decision: 'start_new',
        usage: null,
      },
    });
    await pipeline.enqueue(captureCtx);
    const updateCall = pool.query.mock.calls.find(
      (c) => /UPDATE signal_capture\s+SET input_tokens/.test(c[0])
    );
    expect(updateCall).toBeUndefined();
  });

  test('ok:false (degraded extractor): no usage UPDATE issued', async () => {
    const { pipeline, pool } = makeBaseDeps({
      extractResult: { ok: false, reason: 'schema_invalid', usage: { input_tokens: 100, output_tokens: 5 } },
    });
    await pipeline.enqueue(captureCtx);
    const updateCall = pool.query.mock.calls.find(
      (c) => /UPDATE signal_capture\s+SET input_tokens/.test(c[0])
    );
    expect(updateCall).toBeUndefined();
  });

  test('UPDATE failure is swallowed (logger.warn called, pipeline still returns ok:true)', async () => {
    let usageUpdateCount = 0;
    const { pipeline, logger } = makeBaseDeps({
      extractResult: {
        ok: true,
        drafts: [{ draft: { type: 'observation' }, per_field_confidence: {} }],
        draft: { type: 'observation' },
        per_field_confidence: {},
        continuity_decision: 'start_new',
        usage: { input_tokens: 100, output_tokens: 10 },
      },
      poolQueryImpl: (sql) => {
        if (/UPDATE signal_capture\s+SET input_tokens/.test(sql)) {
          usageUpdateCount += 1;
          throw new Error('boom');
        }
        return { rows: [], rowCount: 1 };
      },
    });
    const result = await pipeline.enqueue(captureCtx);
    expect(usageUpdateCount).toBe(1);
    expect(result.ok).toBe(true);
    expect(logger.warn).toHaveBeenCalledWith(expect.stringMatching(/usage stamp failed/));
  });
});
