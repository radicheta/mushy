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

// Phase 53 BACK-02: small-N high-confidence multi-draft routing.
// drafts.length > 1 AND length <= 5 AND min(per-draft min-leaf confidence) >= 0.7
// -> fan out as N independent per-draft confirm flows (send_confirm_prompt).
// Else (>5 OR low-conf) -> existing runBatchMode (send_batch_review_summary).
describe('extraction pipeline -- BACK-02 multi-draft routing', () => {
  function makeBack02Deps({ drafts, transitionResults }) {
    const dispatched = [];
    const inserts = [];
    const updates = [];
    const pool = {
      query: jest.fn(async () => ({ rows: [], rowCount: 1 })),
    };
    const extractor = {
      extract: jest.fn(async () => ({
        ok: true,
        drafts,
        continuity_decision: 'start_new',
      })),
    };
    const extractionDb = {
      getInFlightForSender: jest.fn(async () => null),
      insertDraft: jest.fn(async (_p, row) => { inserts.push(row); return { ok: true }; }),
      updateDraftStatus: jest.fn(async (_p, id, status, extras) => {
        updates.push({ id, status, extras });
        return { ok: true };
      }),
      advanceAskbackTurn: jest.fn(async () => ({ ok: true })),
      computeDraftId: jest.fn((ids, idx) => `draft-${(ids || []).join('-')}-${idx || 0}`),
    };
    let txnIdx = 0;
    const stateMachine = {
      forceStartNewIfIdle: jest.fn(() => null),
      transition: jest.fn(() => transitionResults
        ? transitionResults[txnIdx++ % transitionResults.length]
        : ({
            nextStatus: DRAFT_STATUS.AWAITING_FARMER,
            side_effects: ['send_confirm_prompt'],
            nextAskbackTurns: 0,
            reason: 'ok',
            askBackInfo: { missingFields: [], lowConfFields: [] },
          })),
    };
    const previewBuilder = { buildPreview: jest.fn(() => 'preview') };
    const config = { draftIdleGapMin: 60, extractionConfidenceThreshold: 0.7, maxAskbackTurns: 3 };
    const logger = { info: jest.fn(), warn: jest.fn(), error: jest.fn() };
    const outboundDispatcher = {
      dispatch: jest.fn((effect, row) => { dispatched.push({ effect, row }); }),
    };
    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder, config, logger, outboundDispatcher,
    });
    return { pipeline, extractor, extractionDb, stateMachine, dispatched, inserts, updates, outboundDispatcher };
  }

  const ctxBack02 = {
    captureId: '01KSCW771VB2FDWBPWNS4MEHAZ',
    sender: '+59891840201',
    farmosPerson: 'f1',
    text: 'DT tubs 0519 1 and 2',
    transcripts: [],
    attachmentPaths: [],
    replyTargetKind: 'dm',
    groupId: null,
    capturedAtMs: Date.parse('2026-05-19T22:00:00Z'),
  };

  test('DT tubs 0519 1 and 2 (capture 01KSCW771VB2FDWBPWNS4MEHAZ): 2 high-conf drafts -> 2 send_confirm_prompt, zero send_batch_review_summary', async () => {
    const drafts = [
      { draft: { type: 'activity', asset_ref: '260519_DT_1' }, per_field_confidence: { type: 0.95, asset_ref: 0.9 } },
      { draft: { type: 'activity', asset_ref: '260519_DT_2' }, per_field_confidence: { type: 0.95, asset_ref: 0.9 } },
    ];
    const { pipeline, dispatched, inserts } = makeBack02Deps({ drafts });
    const res = await pipeline.enqueue(ctxBack02);
    expect(res.ok).toBe(true);
    expect(res.mode).toBe('multi_confirm');
    expect(res.count).toBe(2);
    const confirmCalls = dispatched.filter((d) => d.effect === 'send_confirm_prompt');
    const batchSummary = dispatched.filter((d) => d.effect === 'send_batch_review_summary');
    expect(confirmCalls).toHaveLength(2);
    expect(batchSummary).toHaveLength(0);
    expect(inserts).toHaveLength(2);
    // Each insert lands as PENDING with distinct ids
    expect(inserts[0].id).not.toEqual(inserts[1].id);
  });

  test('2-draft multi with one draft confidence 0.5: routes to runBatchMode (send_batch_review_summary)', async () => {
    const drafts = [
      { draft: { type: 'activity', asset_ref: 'A' }, per_field_confidence: { type: 0.95, asset_ref: 0.9 } },
      { draft: { type: 'activity', asset_ref: 'B' }, per_field_confidence: { type: 0.5, asset_ref: 0.9 } },
    ];
    const { pipeline, dispatched } = makeBack02Deps({ drafts });
    const res = await pipeline.enqueue(ctxBack02);
    expect(res.ok).toBe(true);
    expect(res.mode).toBe('batch');
    expect(dispatched.filter((d) => d.effect === 'send_batch_review_summary')).toHaveLength(1);
    expect(dispatched.filter((d) => d.effect === 'send_confirm_prompt')).toHaveLength(0);
  });

  test('6 high-conf drafts (>5 threshold): routes to runBatchMode', async () => {
    const drafts = Array.from({ length: 6 }, (_, i) => ({
      draft: { type: 'activity', asset_ref: `R${i}` },
      per_field_confidence: { type: 0.95, asset_ref: 0.9 },
    }));
    const { pipeline, dispatched } = makeBack02Deps({ drafts });
    const res = await pipeline.enqueue(ctxBack02);
    expect(res.ok).toBe(true);
    expect(res.mode).toBe('batch');
    expect(dispatched.filter((d) => d.effect === 'send_batch_review_summary')).toHaveLength(1);
  });

  test('multi-draft including a seeding_session: falls through to runBatchMode (safe default)', async () => {
    const drafts = [
      { draft: { type: 'activity', asset_ref: 'A' }, per_field_confidence: { type: 0.95 } },
      { draft: { type: 'seeding_session', event_date: '2025-05-19', groups: [] }, per_field_confidence: { type: 0.95 } },
    ];
    const { pipeline, dispatched } = makeBack02Deps({ drafts });
    const res = await pipeline.enqueue(ctxBack02);
    expect(res.ok).toBe(true);
    expect(res.mode).toBe('batch');
    expect(dispatched.filter((d) => d.effect === 'send_batch_review_summary')).toHaveLength(1);
  });

  test('small-N path expires prior in-flight before fan-out', async () => {
    const drafts = [
      { draft: { type: 'activity', asset_ref: 'A' }, per_field_confidence: { type: 0.95 } },
      { draft: { type: 'activity', asset_ref: 'B' }, per_field_confidence: { type: 0.95 } },
    ];
    const { pipeline, extractionDb } = makeBack02Deps({ drafts });
    // Override getInFlightForSender to return an existing draft
    extractionDb.getInFlightForSender.mockResolvedValueOnce({ id: 'OLD-DRAFT', source_capture_ids: ['x'], askback_turns: 0 });
    await pipeline.enqueue(ctxBack02);
    // First updateDraftStatus call should be EXPIRED on OLD-DRAFT
    const expireCall = extractionDb.updateDraftStatus.mock.calls.find(
      (c) => c[1] === 'OLD-DRAFT' && c[2] === DRAFT_STATUS.EXPIRED
    );
    expect(expireCall).toBeDefined();
  });
});

// Cycle-1 finding 2026-05-25: batch-mode in_flight_conflict regression.
// The earlier BACK-02 tests mock insertDraft as always-ok, so they never
// exercised extraction-db's partial unique index
// (sender_e164) WHERE status IN ('pending','awaiting_farmer'). This block's fake
// extractionDb MODELS that constraint, reproducing the bug where clean batch
// drafts landed in awaiting_farmer, held the one-per-sender in-flight slot, and
// every sibling PENDING insert failed -> only 1 of N entries per page persisted.
describe('extraction pipeline -- batch mode in-flight-index regression', () => {
  const IN_FLIGHT = new Set(['pending', 'awaiting_farmer']);

  function makeConstraintDeps({ drafts }) {
    const store = new Map(); // id -> { sender, status }
    const inFlight = (sender) => [...store.values()]
      .filter((r) => r.sender === sender && IN_FLIGHT.has(r.status)).length;
    const insertResults = [];
    const extractor = {
      extract: jest.fn(async () => ({ ok: true, drafts, continuity_decision: 'start_new' })),
    };
    const extractionDb = {
      getInFlightForSender: jest.fn(async () => null),
      insertDraft: jest.fn(async (_p, row) => {
        // Model the partial unique index: at most one in-flight draft per sender.
        if (IN_FLIGHT.has(row.status) && inFlight(row.sender_e164) >= 1) {
          const r = { ok: false, reason: 'in_flight_conflict' };
          insertResults.push(r);
          return r;
        }
        store.set(row.id, { sender: row.sender_e164, status: row.status });
        const r = { ok: true };
        insertResults.push(r);
        return r;
      }),
      updateDraftStatus: jest.fn(async (_p, id, status) => {
        const r = store.get(id);
        if (r) r.status = status;
        return { ok: true };
      }),
      advanceAskbackTurn: jest.fn(async () => ({ ok: true })),
      computeDraftId: jest.fn((ids, idx) => `draft-${idx || 0}`),
    };
    const stateMachine = {
      forceStartNewIfIdle: jest.fn(() => null),
      // Clean, high-confidence draft -> awaiting_farmer (the real state machine's
      // behavior; reason absent). The fix in runBatchMode must remap this to
      // needs_review so the in-flight slot frees between sibling inserts.
      transition: jest.fn(() => ({
        nextStatus: DRAFT_STATUS.AWAITING_FARMER,
        side_effects: ['handoff_to_phase_39'],
        nextAskbackTurns: 0,
        reason: 'ok',
      })),
    };
    const pipeline = createExtractionPipeline({
      pool: { query: jest.fn(async () => ({ rows: [], rowCount: 1 })) },
      extractor,
      extractionDb,
      stateMachine,
      previewBuilder: { buildPreview: jest.fn(() => 'preview') },
      config: { draftIdleGapMin: 60, extractionConfidenceThreshold: 0.7, maxAskbackTurns: 3 },
      logger: { info: jest.fn(), warn: jest.fn(), error: jest.fn() },
      outboundDispatcher: { dispatch: jest.fn() },
    });
    return { pipeline, extractionDb, store, insertResults };
  }

  const ctx = { sender: '+59891840205', captureId: 'CAP-batch', attachmentPaths: ['/x.jpg'] };

  test('6 clean drafts from one page all persist (no in_flight_conflict drops)', async () => {
    const drafts = Array.from({ length: 6 }, (_, i) => ({
      draft: { type: 'observation', asset_ref: `R${i}` },
      per_field_confidence: { type: 0.95, asset_ref: 0.9 },
    }));
    const { pipeline, store, insertResults } = makeConstraintDeps({ drafts });
    const res = await pipeline.enqueue(ctx);

    expect(res.ok).toBe(true);
    expect(res.mode).toBe('batch');
    // All 6 entries persisted -- the bug dropped 5 of them to in_flight_conflict.
    expect(res.count).toBe(6);
    expect(store.size).toBe(6);
    expect(insertResults.filter((r) => r.reason === 'in_flight_conflict')).toHaveLength(0);
    // Clean batch drafts now land in needs_review (not awaiting_farmer).
    const statuses = [...store.values()].map((r) => r.status);
    expect(statuses.every((s) => s === DRAFT_STATUS.NEEDS_REVIEW)).toBe(true);
    // Clean-vs-flagged split preserved via reason marker.
    expect(res.cleanCount).toBe(6);
    expect(res.needsReviewCount).toBe(0);
  });
});

// Phase 53 BACK-01 Task 2: corpus_context plumbing.
// captureCtx.corpusContext -> extractor.extract({corpusContext:...}). Null/absent
// preserves pre-Phase-53 behavior (back-compat with every existing live caller).
describe('extraction pipeline -- BACK-01 corpus_context plumbing', () => {
  test('captureCtx.corpusContext={default_year:2025,...} passes through to extractor.extract verbatim', async () => {
    const cc = { default_year: 2025, source: 'paper_log' };
    const { pipeline, extractor } = makeBaseDeps({
      extractResult: {
        ok: true,
        drafts: [{ draft: { type: 'observation' }, per_field_confidence: {} }],
        draft: { type: 'observation' },
        per_field_confidence: {},
        continuity_decision: 'start_new',
      },
    });
    await pipeline.enqueue({ ...captureCtx, corpusContext: cc });
    expect(extractor.extract).toHaveBeenCalledTimes(1);
    const arg = extractor.extract.mock.calls[0][0];
    expect(arg.corpusContext).toEqual(cc);
  });

  test('captureCtx omits corpusContext -> extractor.extract called with corpusContext:null (back-compat)', async () => {
    const { pipeline, extractor } = makeBaseDeps({
      extractResult: {
        ok: true,
        drafts: [{ draft: { type: 'observation' }, per_field_confidence: {} }],
        draft: { type: 'observation' },
        per_field_confidence: {},
        continuity_decision: 'start_new',
      },
    });
    await pipeline.enqueue(captureCtx);
    const arg = extractor.extract.mock.calls[0][0];
    expect(arg.corpusContext).toBeNull();
  });
});

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

// ---------------------------------------------------------------------------
// Phase 47 Plan 03: seeding_session starting_seq ask-back branch + reply handler
// ---------------------------------------------------------------------------

const {
  buildStartingSeqAskBackText,
  parseStartingSeqReply,
} = require('../../src/extraction/pipeline');

function makeSeedingSessionDraft({ groups, needsInput = 'starting_seq', eventDate = '2026-05-22' } = {}) {
  return {
    type: 'seeding_session',
    event_date: eventDate,
    needs_input: needsInput,
    groups: groups || [
      {
        parent: { value: '260118_SHI_25', confidence: 0.95, sources: ['paper_log_photo'] },
        species: { value: 'SHI', confidence: 0.95, sources: ['paper_log_photo'] },
        qty: { value: 3, confidence: 0.95, sources: ['paper_log_photo'] },
        child_block_names: { value: ['NEEDS_SEQ', 'NEEDS_SEQ', 'NEEDS_SEQ'], confidence: 0, sources: ['model_inference'] },
      },
    ],
  };
}

describe('pipeline -- buildStartingSeqAskBackText', () => {
  test('renders named greeting + date + total + last-today hint + default + reply hint', () => {
    const text = buildStartingSeqAskBackText({
      totalChildren: 11,
      eventDate: '2026-05-22',
      lastSeq: 3,
      lastBlockName: '260522_KOY_3',
      senderName: 'Santi',
    });
    expect(text).toMatch(/^Hi Santi,/);
    expect(text).toMatch(/May 22 inoc, 11 blocks/);
    expect(text).toMatch(/block number/);
    expect(text).toMatch(/Last block number today was 260522_KOY_3/);
    expect(text).toMatch(/default is 4/);
    expect(text).toMatch(/Reply with a number or just YES/);
  });

  test('renders "default is 1" when lastSeq is null', () => {
    const text = buildStartingSeqAskBackText({
      totalChildren: 5,
      eventDate: '2026-05-22',
      lastSeq: null,
      lastBlockName: null,
      senderName: null,
    });
    expect(text).toMatch(/No prior session today, so default is 1/);
    expect(text).not.toMatch(/^Hi /);
  });

  test('no em-dashes in output (project memory: feedback_no_em_dashes_in_artifacts)', () => {
    const text = buildStartingSeqAskBackText({
      totalChildren: 11,
      eventDate: '2026-05-22',
      lastSeq: 3,
      lastBlockName: '260522_KOY_3',
      senderName: 'Santi',
    });
    expect(text).not.toMatch(/—/);
  });
});

describe('pipeline -- parseStartingSeqReply', () => {
  test('YES (any case) -> kind=yes', () => {
    expect(parseStartingSeqReply('YES').kind).toBe('yes');
    expect(parseStartingSeqReply('yes').kind).toBe('yes');
    expect(parseStartingSeqReply('  Yes ').kind).toBe('yes');
  });
  test('numeric -> kind=number', () => {
    expect(parseStartingSeqReply('4')).toEqual({ kind: 'number', n: 4 });
    expect(parseStartingSeqReply(' 10 ')).toEqual({ kind: 'number', n: 10 });
  });
  test('non-numeric / mixed -> kind=unclear', () => {
    expect(parseStartingSeqReply('4abc').kind).toBe('unclear');
    expect(parseStartingSeqReply('blah').kind).toBe('unclear');
    expect(parseStartingSeqReply('').kind).toBe('unclear');
    expect(parseStartingSeqReply(null).kind).toBe('unclear');
  });
});

describe('pipeline -- seeding_session starting_seq enqueue branch', () => {
  function makeStartingSeqDeps({ lastSeqRows = [] } = {}) {
    const draft = makeSeedingSessionDraft();
    const dispatched = [];
    const updates = [];
    const pool = {
      query: jest.fn(async (sql) => {
        // seq-helper SELECT
        if (/FROM signal_draft\s+WHERE status IN/.test(sql)) {
          return { rows: lastSeqRows };
        }
        return { rows: [], rowCount: 1 };
      }),
    };
    const extractor = {
      extract: jest.fn(async () => ({
        ok: true,
        drafts: [{ draft, per_field_confidence: {} }],
        draft,
        per_field_confidence: {},
        continuity_decision: 'start_new',
        usage: null,
      })),
    };
    const extractionDb = {
      getInFlightForSender: jest.fn(async () => null),
      insertDraft: jest.fn(async () => ({ ok: true })),
      updateDraftStatus: jest.fn(async (_pool, id, status, extras) => {
        updates.push({ id, status, extras });
        return { ok: true };
      }),
      advanceAskbackTurn: jest.fn(async () => ({ ok: true })),
      computeDraftId: jest.fn((ids, idx) => `draft-${(ids || []).join('-')}-${idx || 0}`),
      getDraftById: jest.fn(),
    };
    const stateMachine = {
      forceStartNewIfIdle: jest.fn(() => null),
      transition: jest.fn(),
    };
    const previewBuilder = { buildPreview: jest.fn(() => 'preview') };
    const config = {
      draftIdleGapMin: 60,
      extractionConfidenceThreshold: 0.7,
      maxAskbackTurns: 3,
    };
    const logger = { info: jest.fn(), warn: jest.fn(), error: jest.fn() };
    const outboundDispatcher = {
      dispatch: jest.fn((effect, row) => { dispatched.push({ effect, row }); }),
    };
    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder, config, logger,
      outboundDispatcher,
    });
    return { pipeline, pool, extractor, extractionDb, stateMachine, outboundDispatcher, logger, dispatched, updates, draft };
  }

  const ctx = {
    captureId: 'CAP-SS',
    sender: '+59891840201',
    senderName: 'Santi',
    farmosPerson: 'f1',
    text: 'May 22 inoc',
    transcripts: [],
    attachmentPaths: [],
    replyTargetKind: 'dm',
    groupId: null,
  };

  test('lastSeq=3 in DB -> dispatches send_starting_seq_askback with "default is 4" preview', async () => {
    const lastSeqRows = [
      { draft_json: { type: 'seeding', block_name: '260522_KOY_3' } },
    ];
    const { pipeline, outboundDispatcher, updates, stateMachine } = makeStartingSeqDeps({ lastSeqRows });
    const res = await pipeline.enqueue(ctx);
    expect(res.ok).toBe(true);
    expect(res.status).toBe('awaiting_farmer');
    expect(res.sideEffects).toEqual(['send_starting_seq_askback']);
    // state-machine.transition NOT called on the short-circuit path
    expect(stateMachine.transition).not.toHaveBeenCalled();
    // Dispatcher called once with the correct side-effect name
    const sse = outboundDispatcher.dispatch.mock.calls.find((c) => c[0] === 'send_starting_seq_askback');
    expect(sse).toBeDefined();
    expect(sse[1].farmer_facing_preview).toMatch(/default is 4/);
    expect(sse[1].farmer_facing_preview).toMatch(/^Hi Santi,/);
    // Persisted preview
    const lastUpdate = updates[updates.length - 1];
    expect(lastUpdate.status).toBe('awaiting_farmer');
    expect(lastUpdate.extras.farmer_facing_preview).toMatch(/default is 4/);
  });

  test('lastSeq=null -> preview contains "default is 1"', async () => {
    const { pipeline, outboundDispatcher } = makeStartingSeqDeps({ lastSeqRows: [] });
    await pipeline.enqueue(ctx);
    const sse = outboundDispatcher.dispatch.mock.calls.find((c) => c[0] === 'send_starting_seq_askback');
    expect(sse[1].farmer_facing_preview).toMatch(/default is 1/);
  });
});

describe('pipeline -- handleStartingSeqReply', () => {
  function makeReplyDeps({ draft, lastSeqRows = [] } = {}) {
    const updates = [];
    const dispatched = [];
    const pool = {
      query: jest.fn(async (sql) => {
        if (/FROM signal_draft\s+WHERE status IN/.test(sql)) {
          return { rows: lastSeqRows };
        }
        return { rows: [], rowCount: 1 };
      }),
    };
    const initialDraft = draft || makeSeedingSessionDraft({
      groups: [
        {
          parent: { value: 'P1', confidence: 1, sources: ['paper_log_photo'] },
          species: { value: 'SHI', confidence: 1, sources: ['paper_log_photo'] },
          qty: { value: 5, confidence: 1, sources: ['paper_log_photo'] },
          child_block_names: { value: ['NEEDS_SEQ', 'NEEDS_SEQ', 'NEEDS_SEQ', 'NEEDS_SEQ', 'NEEDS_SEQ'], confidence: 0, sources: ['model_inference'] },
        },
        {
          parent: { value: 'P2', confidence: 1, sources: ['paper_log_photo'] },
          species: { value: 'KOY', confidence: 1, sources: ['paper_log_photo'] },
          qty: { value: 4, confidence: 1, sources: ['paper_log_photo'] },
          child_block_names: { value: ['NEEDS_SEQ', 'NEEDS_SEQ', 'NEEDS_SEQ', 'NEEDS_SEQ'], confidence: 0, sources: ['model_inference'] },
        },
        {
          parent: { value: 'P3', confidence: 1, sources: ['paper_log_photo'] },
          species: { value: 'MAI', confidence: 1, sources: ['paper_log_photo'] },
          qty: { value: 2, confidence: 1, sources: ['paper_log_photo'] },
          child_block_names: { value: ['NEEDS_SEQ', 'NEEDS_SEQ'], confidence: 0, sources: ['model_inference'] },
        },
      ],
    });
    // Live "DB" -- getDraftById returns the latest persisted draft_json.
    let currentRow = { id: 'D1', sender_e164: '+x', draft_json: initialDraft, status: 'awaiting_farmer' };
    const extractionDb = {
      getDraftById: jest.fn(async () => currentRow),
      updateDraftStatus: jest.fn(async (_p, id, status, extras) => {
        updates.push({ id, status, extras });
        if (extras && extras.draft_json) {
          currentRow = { ...currentRow, draft_json: extras.draft_json, status };
        } else {
          currentRow = { ...currentRow, status };
        }
        return { ok: true };
      }),
      getInFlightForSender: jest.fn(),
      insertDraft: jest.fn(),
      advanceAskbackTurn: jest.fn(),
      computeDraftId: jest.fn(),
    };
    const stateMachine = { forceStartNewIfIdle: jest.fn(), transition: jest.fn() };
    const previewBuilder = { buildPreview: jest.fn(() => '') };
    const config = { draftIdleGapMin: 60, extractionConfidenceThreshold: 0.7, maxAskbackTurns: 3 };
    const logger = { info: jest.fn(), warn: jest.fn(), error: jest.fn() };
    const outboundDispatcher = {
      dispatch: jest.fn((effect, row) => { dispatched.push({ effect, row }); }),
    };
    const extractor = { extract: jest.fn() };
    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder, config, logger,
      outboundDispatcher,
    });
    return { pipeline, extractionDb, outboundDispatcher, dispatched, updates, getCurrentRow: () => currentRow };
  }

  test('replyText=YES with default=4 over 5+4+2 groups -> consecutive child_block_names across groups', async () => {
    const lastSeqRows = [{ draft_json: { type: 'seeding', block_name: '260522_SHI_3' } }];
    const { pipeline, updates, dispatched } = makeReplyDeps({ lastSeqRows });
    const res = await pipeline.handleStartingSeqReply({
      draftId: 'D1', replyText: 'YES', captureCtx: { senderName: 'Santi' },
    });
    expect(res.ok).toBe(true);
    expect(res.startSeq).toBe(4);
    const persisted = updates[updates.length - 1].extras.draft_json;
    expect(persisted.needs_input).toBeUndefined();
    expect(persisted.groups[0].child_block_names.value).toEqual([
      '260522_SHI_4', '260522_SHI_5', '260522_SHI_6', '260522_SHI_7', '260522_SHI_8',
    ]);
    expect(persisted.groups[1].child_block_names.value).toEqual([
      '260522_KOY_9', '260522_KOY_10', '260522_KOY_11', '260522_KOY_12',
    ]);
    expect(persisted.groups[2].child_block_names.value).toEqual([
      '260522_MAI_13', '260522_MAI_14',
    ]);
    expect(persisted.groups[0].child_block_names.sources).toEqual(['model_inference', 'text']);
    expect(dispatched.find((d) => d.effect === 'send_seeding_session_filled_preview')).toBeDefined();
  });

  test('replyText=10 -> starts at 10 across groups', async () => {
    const { pipeline, updates } = makeReplyDeps({});
    const res = await pipeline.handleStartingSeqReply({
      draftId: 'D1', replyText: '10', captureCtx: {},
    });
    expect(res.ok).toBe(true);
    expect(res.startSeq).toBe(10);
    const persisted = updates[updates.length - 1].extras.draft_json;
    expect(persisted.groups[0].child_block_names.value[0]).toBe('260522_SHI_10');
    expect(persisted.groups[1].child_block_names.value[0]).toBe('260522_KOY_15');
    expect(persisted.groups[2].child_block_names.value[0]).toBe('260522_MAI_19');
  });

  test('replyText=blah -> dispatches clarifying ask-back, draft unchanged', async () => {
    const { pipeline, updates, dispatched } = makeReplyDeps({});
    const res = await pipeline.handleStartingSeqReply({
      draftId: 'D1', replyText: 'blah', captureCtx: {},
    });
    expect(res.ok).toBe(true);
    expect(res.clarified).toBe(true);
    // No draft_json mutation persisted
    expect(updates.find((u) => u.extras && u.extras.draft_json)).toBeUndefined();
    const reaskback = dispatched.find((d) => d.effect === 'send_starting_seq_askback');
    expect(reaskback).toBeDefined();
    expect(reaskback.row.farmer_facing_preview).toMatch(/Please reply with a number or YES/);
  });

  test('idempotent: second YES after needs_input cleared returns noop:true', async () => {
    const { pipeline, updates } = makeReplyDeps({});
    const first = await pipeline.handleStartingSeqReply({
      draftId: 'D1', replyText: 'YES', captureCtx: {},
    });
    expect(first.ok).toBe(true);
    const updatesAfterFirst = updates.length;
    const second = await pipeline.handleStartingSeqReply({
      draftId: 'D1', replyText: 'YES', captureCtx: {},
    });
    expect(second).toEqual(expect.objectContaining({ ok: true, noop: true }));
    expect(updates.length).toBe(updatesAfterFirst);
  });
});
