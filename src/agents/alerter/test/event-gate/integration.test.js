'use strict';

// Phase 44 Plan-04 Task 4.3: capture pipeline ↔ event-gate integration.
// Covers GATE-01+GATE-02 wiring: gate runs at capture.js BEFORE
// extractionPipeline.enqueue; gate decision steers convo gate at :171
// per CONTEXT D-02 + D-04 + D-05 + D-06.

const os = require('os');
const path = require('path');
const fs = require('fs');

const { createCapturePipeline } = require('../../src/capture');
const { createEventGate } = require('../../src/event-gate');
const rules = require('../../src/event-gate/rules');

function makeEnv(text, attachments = []) {
  return {
    envelope: {
      source: '+59891234567',
      dataMessage: { message: text, attachments },
    },
  };
}

function buildPipeline({
  gate, extractionPipeline, llmCompose, eventGateConvoMode = 'silent',
  outboundRows = [], poolUpdateError = null,
} = {}) {
  const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'gate-int-'));
  const pool = {
    query: jest.fn().mockImplementation((sql) => {
      if (sql.startsWith('UPDATE signal_capture SET extraction_gate') && poolUpdateError) {
        return Promise.reject(poolUpdateError);
      }
      return Promise.resolve({ rows: [], rowCount: 1 });
    }),
  };
  const signalClient = {
    fetchAttachment: jest.fn().mockResolvedValue(Buffer.from('AAA')),
    send: jest.fn().mockResolvedValue({ ok: true }),
  };
  const transcribeClient = { transcribe: jest.fn().mockResolvedValue({ ok: true, text: 'foo' }) };
  const llmClient = { compose: llmCompose || jest.fn().mockResolvedValue({ ok: true, text: 'reply' }) };
  const captureHistory = {
    selectRecentBySender: jest.fn().mockResolvedValue([]),
    selectRecentOutboundByRecipient: jest.fn().mockResolvedValue(outboundRows),
  };
  const sensorSnapshot = jest.fn().mockResolvedValue(null);
  const logger = { info: jest.fn(), warn: jest.fn(), error: jest.fn(), debug: jest.fn() };

  const pipeline = createCapturePipeline({
    pool,
    signalClient,
    transcribeClient,
    llmClient,
    captureHistory,
    sensorSnapshot,
    baseDir,
    logger,
    signalFarmerMap: new Map([['+59891234567', 'santi']]),
    extractionPipeline,
    eventGate: gate,
    config: { eventGateConvoMode },
  });

  return { pipeline, pool, signalClient, llmClient, captureHistory, logger, baseDir };
}

afterEach(() => jest.clearAllMocks());

describe('capture pipeline ↔ event-gate integration', () => {
  test('Test 2: rulePositive (long text) → fast_event UPDATE + extraction enqueue called', async () => {
    const haiku = { classify: jest.fn() };
    const gate = createEventGate({ haikuClassifier: haiku, rules });
    const extractionPipeline = { enqueue: jest.fn().mockResolvedValue() };
    const { pipeline, pool } = buildPipeline({ gate, extractionPipeline });

    const longText = 'a'.repeat(250);
    await pipeline.handle(makeEnv(longText));

    expect(extractionPipeline.enqueue).toHaveBeenCalledTimes(1);
    const updateCalls = pool.query.mock.calls.filter((c) => /UPDATE signal_capture SET extraction_gate/.test(c[0]));
    expect(updateCalls.length).toBe(1);
    expect(updateCalls[0][1][0]).toBe('fast_event');
    expect(haiku.classify).not.toHaveBeenCalled();
  });

  test('Test 3: ruleNegative → skipped_rule_neg, extraction NOT called, convo NOT called (silent)', async () => {
    const haiku = { classify: jest.fn() };
    const gate = createEventGate({ haikuClassifier: haiku, rules });
    const extractionPipeline = { enqueue: jest.fn().mockResolvedValue() };
    const llmCompose = jest.fn().mockResolvedValue({ ok: true, text: 'reply' });

    const nowMs = Date.now();
    const outboundRows = [
      { sent_at: new Date(nowMs - 5 * 60_000).toISOString(), intent: 'attestation_kickoff', body: 'how is the chamber?' },
    ];
    const { pipeline, pool } = buildPipeline({
      gate, extractionPipeline, llmCompose, outboundRows,
    });

    await pipeline.handle(makeEnv('ok'));

    expect(extractionPipeline.enqueue).not.toHaveBeenCalled();
    expect(llmCompose).not.toHaveBeenCalled();
    const updateCalls = pool.query.mock.calls.filter((c) => /UPDATE signal_capture SET extraction_gate/.test(c[0]));
    expect(updateCalls[0][1][0]).toBe('skipped_rule_neg');
  });

  test('Test 4: gate=haiku_chitchat but convo mode=off → llmClient.compose IS called', async () => {
    const haiku = { classify: jest.fn().mockResolvedValue({ ok: true, is_event: false, confidence: 0.9 }) };
    const gate = createEventGate({ haikuClassifier: haiku, rules });
    const extractionPipeline = { enqueue: jest.fn() };
    const llmCompose = jest.fn().mockResolvedValue({ ok: true, text: 'reply' });
    const { pipeline } = buildPipeline({
      gate, extractionPipeline, llmCompose, eventGateConvoMode: 'off',
    });

    await pipeline.handle(makeEnv('hola'));

    expect(extractionPipeline.enqueue).not.toHaveBeenCalled();
    expect(llmCompose).toHaveBeenCalledTimes(1);
  });

  test('Test 6: pool UPDATE failure → logger.warn but capture continues, extraction still enqueued', async () => {
    const haiku = { classify: jest.fn() };
    const gate = createEventGate({ haikuClassifier: haiku, rules });
    const extractionPipeline = { enqueue: jest.fn().mockResolvedValue() };
    const { pipeline, logger } = buildPipeline({
      gate, extractionPipeline,
      poolUpdateError: new Error('db down'),
    });

    const longText = 'a'.repeat(250);
    await pipeline.handle(makeEnv(longText));

    expect(extractionPipeline.enqueue).toHaveBeenCalledTimes(1);
    const warned = logger.warn.mock.calls.some((c) => /gate audit failed/.test(c[0]));
    expect(warned).toBe(true);
  });

  test('Test 7 (B3): convo branch passes outboundHistory + lastBotOutbound to llmClient.compose', async () => {
    const haiku = { classify: jest.fn() };
    const gate = createEventGate({ haikuClassifier: haiku, rules });
    const extractionPipeline = { enqueue: jest.fn().mockResolvedValue() };
    const llmCompose = jest.fn().mockResolvedValue({ ok: true, text: 'reply' });
    const nowMs = Date.now();
    const outboundRows = [
      { sent_at: new Date(nowMs - 10 * 60_000).toISOString(), intent: 'convo_reply', body: 'previous bot reply' },
    ];
    const { pipeline, captureHistory } = buildPipeline({
      gate, extractionPipeline, llmCompose, outboundRows,
    });

    const longText = 'a'.repeat(250);
    await pipeline.handle(makeEnv(longText));

    expect(llmCompose).toHaveBeenCalledTimes(1);
    const arg = llmCompose.mock.calls[0][0];
    expect(arg).toHaveProperty('outboundHistory');
    expect(arg).toHaveProperty('lastBotOutbound');
    expect(Array.isArray(arg.outboundHistory)).toBe(true);

    // Single capture should invoke selectRecentOutboundByRecipient ONCE (lastBot reused
    // for both gate and convo branches). The 24h convo-history fetch counts as the 2nd.
    // Plan-04 contract: "lastBot from :147 is reused, not requeried" — so we expect
    // exactly 2 calls (one for the 30-min gate lookup, one for the 24h convo window).
    expect(captureHistory.selectRecentOutboundByRecipient).toHaveBeenCalledTimes(2);
  });
});
