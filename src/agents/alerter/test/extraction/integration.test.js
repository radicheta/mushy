'use strict';

// Phase 38 Plan 05: extraction pipeline integration tests.
//
// Stubs the pool, extractor, state-machine, preview-builder, outboundDispatcher.
// Covers R1..R8 from 38-05-PLAN.md.
//
// The pipeline composes:
//   getInFlightForSender -> forceStartNewIfIdle -> extractor.extract ->
//   apply continuity (insertDraft / updateDraftStatus / markExpired) ->
//   state-machine.transition -> updateDraftStatus(nextStatus + extras incl preview)
//   -> outboundDispatcher.dispatch(sideEffect, draftRow)

const path = require('path');
const REQUIRE_PIPELINE = '../../src/extraction/pipeline';

// We do NOT mock @anthropic-ai/sdk here. The extractor is injected as a stub.

const silentLogger = { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} };

function makePool(extraRow = null) {
  // Default pool: every query returns rowCount=1; the SELECT for in-flight
  // returns extraRow if provided.
  return {
    query: jest.fn(async (sql) => {
      const isSelectInFlight = /FROM signal_draft\s+WHERE sender_e164/i.test(sql);
      if (isSelectInFlight) {
        return { rows: extraRow ? [extraRow] : [], rowCount: extraRow ? 1 : 0 };
      }
      if (/RETURNING askback_turns/i.test(sql)) {
        return { rows: [{ askback_turns: 1 }], rowCount: 1 };
      }
      return { rows: [], rowCount: 1 };
    }),
  };
}

function makeExtractor(result) {
  return {
    extract: jest.fn(async () => result),
  };
}

function makeDispatcher() {
  return { dispatch: jest.fn() };
}

function makeConfig(over = {}) {
  return {
    extractionConfidenceThreshold: 0.7,
    draftIdleGapMin: 30,
    maxAskbackTurns: 3,
    ...over,
  };
}

const NOW_MS = Date.parse('2026-05-12T12:00:00Z');
const clock = { now: () => NOW_MS };

function baseCaptureCtx(over = {}) {
  return {
    captureId: 'cap_001',
    sender: '+59891840205',
    farmosPerson: 'santi',
    text: 'logged 12 shiitake blocks today',
    transcripts: [],
    attachmentPaths: [],
    replyTargetKind: 'dm',
    groupId: null,
    capturedAtMs: NOW_MS,
    ...over,
  };
}

function validDraft() {
  return {
    type: 'seeding',
    species: 'shiitake',
    block_name: '260512_SHI_1',
    qty: 12,
    event_timestamp: '2026-05-12T00:00:00Z',
    confidence: { species: 0.95, block_name: 0.95, qty: 0.95, event_timestamp: 0.95 },
  };
}

describe('createExtractionPipeline', () => {
  let pool;
  let extractor;
  let extractionDb;
  let stateMachine;
  let previewBuilder;
  let outboundDispatcher;
  let config;

  beforeEach(() => {
    extractionDb = require('../../src/extraction/extraction-db');
    stateMachine = require('../../src/extraction/state-machine');
    previewBuilder = require('../../src/extraction/preview-builder');
    outboundDispatcher = makeDispatcher();
    config = makeConfig();
  });

  test('(R1) new sender, no in-flight, ask-back required -> insert draft + dispatch send_ask_back', async () => {
    pool = makePool(null);
    // Missing event_timestamp triggers ask-back.
    const draftMissing = { ...validDraft(), event_timestamp: null,
      confidence: { species: 0.95, block_name: 0.95, qty: 0.95 } };
    extractor = makeExtractor({
      ok: true,
      draft: draftMissing,
      continuity_decision: 'start_new',
      per_field_confidence: draftMissing.confidence,
    });

    const { createExtractionPipeline } = require(REQUIRE_PIPELINE);
    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder,
      config, logger: silentLogger, clock, outboundDispatcher,
    });
    const res = await pipeline.enqueue(baseCaptureCtx());
    expect(res.ok).toBe(true);

    // INSERT into signal_draft was issued.
    const insertCall = pool.query.mock.calls.find((c) => /INSERT INTO signal_draft/i.test(c[0]));
    expect(insertCall).toBeTruthy();
    // UPDATE status to awaiting_farmer
    const updateCall = pool.query.mock.calls.find((c) =>
      /UPDATE signal_draft/i.test(c[0]) && c[1] && c[1][1] === 'awaiting_farmer');
    expect(updateCall).toBeTruthy();
    // Dispatcher fired send_ask_back
    expect(outboundDispatcher.dispatch).toHaveBeenCalled();
    const effects = outboundDispatcher.dispatch.mock.calls.map((c) => c[0]);
    expect(effects).toContain('send_ask_back');
  });

  test('(R2) new sender, no in-flight, complete draft -> updateDraftStatus ready + dispatch handoff_to_phase_39', async () => {
    pool = makePool(null);
    extractor = makeExtractor({
      ok: true,
      draft: validDraft(),
      continuity_decision: 'start_new',
      per_field_confidence: validDraft().confidence,
    });

    const { createExtractionPipeline } = require(REQUIRE_PIPELINE);
    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder,
      config, logger: silentLogger, clock, outboundDispatcher,
    });
    const res = await pipeline.enqueue(baseCaptureCtx());
    expect(res.ok).toBe(true);
    const effects = outboundDispatcher.dispatch.mock.calls.map((c) => c[0]);
    expect(effects).toContain('handoff_to_phase_39');
  });

  test('(R3) in-flight 35min stale -> forceStartNewIfIdle expires old + new draft inserted', async () => {
    const stale = {
      id: 'stale_id',
      sender_e164: '+59891840205',
      source_capture_ids: ['cap_old'],
      status: 'awaiting_farmer',
      askback_turns: 1,
      updated_at: new Date(NOW_MS - 35 * 60 * 1000),
      draft_json: validDraft(),
    };
    pool = makePool(stale);
    extractor = makeExtractor({
      ok: true,
      draft: validDraft(),
      continuity_decision: 'append', // LLM-says append but idle cap forces start_new
      per_field_confidence: validDraft().confidence,
    });

    const { createExtractionPipeline } = require(REQUIRE_PIPELINE);
    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder,
      config, logger: silentLogger, clock, outboundDispatcher,
    });
    const res = await pipeline.enqueue(baseCaptureCtx());
    expect(res.ok).toBe(true);

    // Old draft expired
    const expireCall = pool.query.mock.calls.find((c) =>
      /UPDATE signal_draft/i.test(c[0]) && c[1] && c[1][0] === 'stale_id' && c[1][1] === 'expired');
    expect(expireCall).toBeTruthy();
    // New draft inserted
    const insertCall = pool.query.mock.calls.find((c) => /INSERT INTO signal_draft/i.test(c[0]));
    expect(insertCall).toBeTruthy();
  });

  test('(R4) in-flight 5min ago, LLM says append -> existing draft extended', async () => {
    const fresh = {
      id: 'fresh_id',
      sender_e164: '+59891840205',
      source_capture_ids: ['cap_old'],
      status: 'awaiting_farmer',
      askback_turns: 1,
      updated_at: new Date(NOW_MS - 5 * 60 * 1000),
      draft_json: validDraft(),
    };
    pool = makePool(fresh);
    extractor = makeExtractor({
      ok: true,
      draft: validDraft(),
      continuity_decision: 'append',
      per_field_confidence: validDraft().confidence,
    });

    const { createExtractionPipeline } = require(REQUIRE_PIPELINE);
    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder,
      config, logger: silentLogger, clock, outboundDispatcher,
    });
    const res = await pipeline.enqueue(baseCaptureCtx());
    expect(res.ok).toBe(true);

    // No INSERT for new draft (append updates existing)
    const insertCall = pool.query.mock.calls.find((c) => /INSERT INTO signal_draft/i.test(c[0]));
    expect(insertCall).toBeFalsy();
    // UPDATE to fresh_id with extended source_capture_ids
    const updateCall = pool.query.mock.calls.find((c) =>
      /UPDATE signal_draft/i.test(c[0]) && c[1] && c[1][0] === 'fresh_id');
    expect(updateCall).toBeTruthy();
  });

  test('(R5) extractor returns ok:false -> pipeline returns ok:false, no draft state change', async () => {
    pool = makePool(null);
    extractor = makeExtractor({ ok: false, reason: 'schema_invalid' });
    const warnSpy = jest.fn();
    const logger = { info: () => {}, warn: warnSpy, error: () => {}, debug: () => {} };

    const { createExtractionPipeline } = require(REQUIRE_PIPELINE);
    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder,
      config, logger, clock, outboundDispatcher,
    });
    const res = await pipeline.enqueue(baseCaptureCtx());
    expect(res.ok).toBe(false);
    // Should NOT insert a draft with bogus status
    const insertCall = pool.query.mock.calls.find((c) => /INSERT INTO signal_draft/i.test(c[0]));
    expect(insertCall).toBeFalsy();
    expect(warnSpy).toHaveBeenCalled();
  });

  test('(R6) 3rd ask-back turn cap -> updateDraftStatus needs_review + dispatch send_needs_review_ping', async () => {
    const inflight = {
      id: 'inflight_id',
      sender_e164: '+59891840205',
      source_capture_ids: ['cap_a', 'cap_b'],
      status: 'awaiting_farmer',
      askback_turns: 2,
      updated_at: new Date(NOW_MS - 5 * 60 * 1000),
      draft_json: validDraft(),
    };
    pool = makePool(inflight);
    const draftMissing = { ...validDraft(), event_timestamp: null,
      confidence: { species: 0.95, block_name: 0.95, qty: 0.95 } };
    extractor = makeExtractor({
      ok: true,
      draft: draftMissing,
      continuity_decision: 'append',
      per_field_confidence: draftMissing.confidence,
    });

    const { createExtractionPipeline } = require(REQUIRE_PIPELINE);
    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder,
      config, logger: silentLogger, clock, outboundDispatcher,
    });
    const res = await pipeline.enqueue(baseCaptureCtx());
    expect(res.ok).toBe(true);

    const updateCall = pool.query.mock.calls.find((c) =>
      /UPDATE signal_draft/i.test(c[0]) && c[1] && c[1][1] === 'needs_review');
    expect(updateCall).toBeTruthy();

    const effects = outboundDispatcher.dispatch.mock.calls.map((c) => c[0]);
    expect(effects).toContain('send_needs_review_ping');
  });

  test('(R7) pipeline.enqueue NEVER throws even when pool.query throws', async () => {
    pool = {
      query: jest.fn(async () => { throw new Error('connection refused'); }),
    };
    extractor = makeExtractor({
      ok: true,
      draft: validDraft(),
      continuity_decision: 'start_new',
      per_field_confidence: validDraft().confidence,
    });

    const { createExtractionPipeline } = require(REQUIRE_PIPELINE);
    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder,
      config, logger: silentLogger, clock, outboundDispatcher,
    });
    let threw = false;
    let res;
    try {
      res = await pipeline.enqueue(baseCaptureCtx());
    } catch (e) {
      threw = true;
    }
    expect(threw).toBe(false);
    expect(res.ok).toBe(false);
  });

  test('(R8) preview text written to farmer_facing_preview before dispatch', async () => {
    pool = makePool(null);
    const draftMissing = { ...validDraft(), event_timestamp: null,
      confidence: { species: 0.95, block_name: 0.95, qty: 0.95 } };
    extractor = makeExtractor({
      ok: true,
      draft: draftMissing,
      continuity_decision: 'start_new',
      per_field_confidence: draftMissing.confidence,
    });

    const { createExtractionPipeline } = require(REQUIRE_PIPELINE);
    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder,
      config, logger: silentLogger, clock, outboundDispatcher,
    });
    await pipeline.enqueue(baseCaptureCtx());

    // Find the UPDATE that sets status=awaiting_farmer (carries preview).
    const updateCall = pool.query.mock.calls.find((c) =>
      /UPDATE signal_draft/i.test(c[0]) && c[1] && c[1][1] === 'awaiting_farmer');
    expect(updateCall).toBeTruthy();
    // farmer_facing_preview must be in the SQL set list
    expect(updateCall[0]).toMatch(/farmer_facing_preview/);
    // And params must contain non-empty preview string
    const paramsHasPreview = updateCall[1].some(
      (p) => typeof p === 'string' && p.length > 0 && /\?|seeding|block|species|confirm|right|sure|time|how many|which/i.test(p),
    );
    expect(paramsHasPreview).toBe(true);

    // Ordering: the UPDATE comes before the dispatch call.
    const updateCallIdx = pool.query.mock.invocationCallOrder[
      pool.query.mock.calls.indexOf(updateCall)
    ];
    const dispatchOrder = outboundDispatcher.dispatch.mock.invocationCallOrder[0];
    expect(updateCallIdx).toBeLessThan(dispatchOrder);
  });
});
