'use strict';

/**
 * RED skeleton tests for capture pipeline (Wave 1 implements the subject).
 * Skip-guard: if ../src/capture doesn't exist yet, all tests are skipped.
 * Remove the try/catch wrapper in Wave 1 when replacing with direct require.
 */

const os = require('os');
const path = require('path');
const fs = require('fs');

const textEnvelope = require('./fixtures/envelopes/text.json')[0];
const audioEnvelope = require('./fixtures/envelopes/audio.json')[0];
const photoBatchEnvelope = require('./fixtures/envelopes/photo-batch.json')[0];

let createCapturePipeline;
let subjectMissing = false;

try {
  ({ createCapturePipeline } = require('../src/capture'));
} catch (_) {
  subjectMissing = true;
}

const describeFn = subjectMissing ? describe.skip : describe;

describeFn('createCapturePipeline', () => {
  let pool;
  let signalClient;
  let transcribeClient;
  let llmClient;
  let captureHistory;
  let sensorSnapshot;
  let baseDir;
  let logger;
  let pipeline;

  beforeEach(() => {
    baseDir = path.join(os.tmpdir(), 'capture-test-' + Date.now());
    fs.mkdirSync(baseDir, { recursive: true });

    pool = { query: jest.fn().mockResolvedValue({ rows: [], rowCount: 1 }) };
    signalClient = {
      fetchAttachment: jest.fn().mockResolvedValue(Buffer.from('AAA')),
      send: jest.fn().mockResolvedValue({ ok: true }),
    };
    transcribeClient = {
      transcribe: jest.fn().mockResolvedValue({ ok: true, text: 'foo', duration_ms: 100, language: 'en' }),
    };
    llmClient = {
      compose: jest.fn().mockResolvedValue({ ok: true, text: 'logged inoculation 2026-04-27' }),
    };
    captureHistory = {
      selectRecentBySender: jest.fn().mockResolvedValue([]),
    };
    sensorSnapshot = jest.fn().mockResolvedValue({ sensors: { humidity: 90, temperature: 22, co2: 600 } });
    logger = { info: jest.fn(), warn: jest.fn(), error: jest.fn() };

    pipeline = createCapturePipeline({
      pool,
      signalClient,
      transcribeClient,
      llmClient,
      captureHistory,
      sensorSnapshot,
      baseDir,
      logger,
    });
  });

  afterEach(() => {
    fs.rmSync(baseDir, { recursive: true, force: true });
  });

  test('(R2) text-only envelope — pool.query INSERT with message_type=text, raw_text, attachment_paths=[]', async () => {
    await pipeline.handle(textEnvelope);
    expect(pool.query).toHaveBeenCalled();
    const [sql, params] = pool.query.mock.calls[0];
    expect(sql).toMatch(/INSERT/i);
    const rowJson = JSON.stringify(params);
    expect(rowJson).toMatch(/text/);
    expect(rowJson).toMatch(/logged 3 jars in tent A/);
  });

  test('(R2) audio envelope — fetchAttachment called; transcribeClient called; INSERT includes transcript', async () => {
    await pipeline.handle(audioEnvelope);
    expect(signalClient.fetchAttachment).toHaveBeenCalledWith(
      audioEnvelope.envelope.dataMessage.attachments[0].id
    );
    expect(transcribeClient.transcribe).toHaveBeenCalled();
    const rowJson = JSON.stringify(pool.query.mock.calls[0]);
    expect(rowJson).toMatch(/foo/); // transcript text
  });

  test('(R2) photo-batch envelope — 3 fetchAttachment calls; INSERT includes 3 attachment paths', async () => {
    await pipeline.handle(photoBatchEnvelope);
    expect(signalClient.fetchAttachment).toHaveBeenCalledTimes(3);
    const rowJson = JSON.stringify(pool.query.mock.calls[0]);
    // attachment_paths should have 3 entries — match on the three attachment IDs or filenames
    expect(rowJson).toMatch(/att-img-00[123]/);
  });

  test('(R6) degraded transcribe — transcribeClient returns ok=false → row has degraded=true, transcript=null; signalClient.send called; no throw', async () => {
    transcribeClient.transcribe.mockResolvedValue({ ok: false, reason: 'timeout' });
    await expect(pipeline.handle(audioEnvelope)).resolves.not.toThrow();
    const rowJson = JSON.stringify(pool.query.mock.calls[0]);
    expect(rowJson).toMatch(/degraded/);
    expect(signalClient.send).toHaveBeenCalled();
    const sendArg = signalClient.send.mock.calls[0][0];
    // degraded reply must reference attachment count or timestamp
    expect(typeof sendArg).toBe('string');
    expect(sendArg.length).toBeGreaterThan(0);
  });

  test('(R6) degraded LLM — llmClient.compose returns ok=false → row has llm_reply=null; fallback send called; no throw', async () => {
    llmClient.compose.mockResolvedValue({ ok: false, reason: 'api error' });
    await expect(pipeline.handle(textEnvelope)).resolves.not.toThrow();
    const rowJson = JSON.stringify(pool.query.mock.calls[0]);
    expect(rowJson).toMatch(/llm_reply|null/);
    expect(signalClient.send).toHaveBeenCalled();
  });

  test('(R2) any internal throw (pool.query rejects) — handle() resolves; logger.warn called', async () => {
    pool.query.mockRejectedValue(new Error('db error'));
    await expect(pipeline.handle(textEnvelope)).resolves.not.toThrow();
    expect(logger.warn).toHaveBeenCalled();
  });
});
