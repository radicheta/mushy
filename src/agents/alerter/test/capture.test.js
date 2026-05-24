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
const textQuoteReplyEnv = require('./fixtures/envelopes/text-quote-reply.json')[0];
const textQuoteReplyAuthorNumberOnlyEnv = require('./fixtures/envelopes/text-quote-reply-authornumber-only.json')[0];

const { createCapturePipeline } = require('../src/capture');

describe('createCapturePipeline', () => {
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

  // Phase 50 Plan-04: capture-side persistence of Signal-native ts + quote target.
  describe('Phase 50 Plan-04: signal_msg_ts + quote_* persistence', () => {
    test('text envelope without quote: signal_msg_ts populated from dm.timestamp; quote fields NULL', async () => {
      await pipeline.handle(textEnvelope);
      const insertCall = pool.query.mock.calls.find((c) => /INSERT INTO signal_capture/.test(c[0]));
      expect(insertCall).toBeDefined();
      const params = insertCall[1];
      // INSERT positions: 13=signal_msg_ts, 14=quote_msg_ts, 15=quote_author_e164.
      expect(params[13]).toBe(1714240000000);
      expect(params[14]).toBeNull();
      expect(params[15]).toBeNull();
    });

    test('quote-reply envelope (quote.id + quote.author): all three fields populated', async () => {
      await pipeline.handle(textQuoteReplyEnv);
      const insertCall = pool.query.mock.calls.find((c) => /INSERT INTO signal_capture/.test(c[0]));
      const params = insertCall[1];
      expect(params[13]).toBe(1779562666675); // inbound msg ts
      expect(params[14]).toBe(1779560111000); // quote target ts (from quote.id)
      expect(params[15]).toBe('+59891840205'); // quote author (from quote.author)
    });

    test('quote-reply envelope (no quote.id, only quote.timestamp; no quote.author, only quote.authorNumber)', async () => {
      // CONTEXT D-07 / receive-loop.js:23-24 cross-version drift acceptance.
      await pipeline.handle(textQuoteReplyAuthorNumberOnlyEnv);
      const insertCall = pool.query.mock.calls.find((c) => /INSERT INTO signal_capture/.test(c[0]));
      const params = insertCall[1];
      expect(params[13]).toBe(1779562777777);
      expect(params[14]).toBe(1779560222000); // from quote.timestamp (no .id)
      expect(params[15]).toBe('+59891840205'); // from quote.authorNumber (no .author)
    });

    test('envelope without dataMessage.timestamp: signal_msg_ts is null; capture still saves', async () => {
      const noTs = JSON.parse(JSON.stringify(textEnvelope));
      delete noTs.envelope.dataMessage.timestamp;
      await pipeline.handle(noTs);
      const insertCall = pool.query.mock.calls.find((c) => /INSERT INTO signal_capture/.test(c[0]));
      expect(insertCall).toBeDefined();
      const params = insertCall[1];
      expect(params[13]).toBeNull();
      expect(params[14]).toBeNull();
      expect(params[15]).toBeNull();
    });
  });

  // ============================================================
  // Phase 37 Plan 03 — replyTarget threading + farmer-map + new row fields
  // ============================================================

  describe('Phase 37 — multi-farmer routing', () => {
    const F2_PHONE = '+59892893012';
    const GROUP_ID = 'hKw0KX1gte8Mnjw7fMlMCsPc7s/g3drpkpVsBwPcxwE=';
    const groupSilentEnv = require('./fixtures/envelopes/group-silent.json')[0];
    const groupMentionEnv = require('./fixtures/envelopes/group-mention.json')[0];
    const groupUnknownEnv = require('./fixtures/envelopes/group-unknown-sender.json')[0];

    function rebuild(signalFarmerMap) {
      pipeline = createCapturePipeline({
        pool,
        signalClient,
        transcribeClient,
        llmClient,
        captureHistory,
        sensorSnapshot,
        baseDir,
        logger,
        signalFarmerMap,
      });
    }

    test('DM envelope: signalClient.send called with {to: source}', async () => {
      rebuild(new Map([[F2_PHONE, 'f2']]));
      await pipeline.handle(textEnvelope);
      expect(signalClient.send).toHaveBeenCalled();
      const [, opts] = signalClient.send.mock.calls[0];
      expect(opts).toMatchObject({ to: F2_PHONE, intent: 'convo_reply', sourceModule: 'capture.js' });
    });

    test('DM envelope: row.reply_target_kind=dm, group_id=null, farmos_person=slug', async () => {
      rebuild(new Map([[F2_PHONE, 'f2']]));
      await pipeline.handle(textEnvelope);
      const [, params] = pool.query.mock.calls[0];
      // 17 params: 13 base + Phase 50 Plan-04 (signal_msg_ts, quote_msg_ts, quote_author_e164) + Phase 53 BACK-01 (corpus_context)
      expect(params).toHaveLength(17);
      expect(params[16]).toBeNull();           // corpus_context (live captures never set it)
      expect(params[10]).toBeNull();          // group_id
      expect(params[11]).toBe('f2');           // farmos_person
      expect(params[12]).toBe('dm');           // reply_target_kind
    });

    test('DM envelope, sender NOT in farmer-map → farmos_person=(unassigned), reply still fires', async () => {
      rebuild(new Map()); // empty map
      await pipeline.handle(textEnvelope);
      const [, params] = pool.query.mock.calls[0];
      expect(params[11]).toBe('(unassigned)');
      expect(signalClient.send).toHaveBeenCalled();
    });

    test('Group envelope with ctx (triggered) → send with {to: {groupId}}, kind=group', async () => {
      rebuild(new Map([[F2_PHONE, 'f2']]));
      await pipeline.handle(groupMentionEnv, {
        replyTargetKind: 'group',
        groupId: GROUP_ID,
        suppressReply: false,
      });
      expect(signalClient.send).toHaveBeenCalled();
      const [, opts] = signalClient.send.mock.calls[0];
      expect(opts.to).toEqual({ groupId: GROUP_ID });
      const [, params] = pool.query.mock.calls[0];
      expect(params[10]).toBe(GROUP_ID);
      expect(params[11]).toBe('f2');
      expect(params[12]).toBe('group');
    });

    test('Group silent (ctx.suppressReply=true) → row written, NO signal send', async () => {
      rebuild(new Map([[F2_PHONE, 'f2']]));
      await pipeline.handle(groupSilentEnv, {
        replyTargetKind: 'none',
        groupId: GROUP_ID,
        suppressReply: true,
      });
      expect(signalClient.send).not.toHaveBeenCalled();
      const [, params] = pool.query.mock.calls[0];
      expect(params[10]).toBe(GROUP_ID);
      expect(params[11]).toBe('f2');
      expect(params[12]).toBe('none');
    });

    test('Group unknown sender → row.farmos_person=(unassigned), suppressReply respected', async () => {
      rebuild(new Map([[F2_PHONE, 'f2']]));
      await pipeline.handle(groupUnknownEnv, {
        replyTargetKind: 'none',
        groupId: GROUP_ID,
        suppressReply: true,
      });
      const [, params] = pool.query.mock.calls[0];
      expect(params[11]).toBe('(unassigned)');
      expect(params[12]).toBe('none');
    });

    test('Standalone (no ctx): falls back to dm.groupInfo for routing', async () => {
      rebuild(new Map([[F2_PHONE, 'f2']]));
      // Call without ctx — capture.js should sniff groupInfo from envelope itself
      await pipeline.handle(groupMentionEnv);
      // DM envelope has no groupInfo; this one DOES — so send should target group
      const [, opts] = signalClient.send.mock.calls[0];
      expect(opts.to).toEqual({ groupId: GROUP_ID });
    });

    test('signalFarmerMap optional → defaults to empty Map → (unassigned)', async () => {
      // No signalFarmerMap option passed
      pipeline = createCapturePipeline({
        pool, signalClient, transcribeClient, llmClient,
        captureHistory, sensorSnapshot, baseDir, logger,
      });
      await pipeline.handle(textEnvelope);
      const [, params] = pool.query.mock.calls[0];
      expect(params[11]).toBe('(unassigned)');
    });
  });

  // ============================================================
  // Backlog 999.53 -- token usage persistence in Step 7 UPDATE
  // ============================================================

  describe('999.53 -- token usage persistence', () => {
    test('happy path: Step 7 UPDATE binds 8 params (llm_reply, degraded, 4 token cols, model, id)', async () => {
      llmClient.compose.mockResolvedValueOnce({
        ok: true,
        text: 'logged inoc-2026-05-18',
        usage: {
          input_tokens: 100,
          output_tokens: 50,
          cache_creation_input_tokens: 0,
          cache_read_input_tokens: 0,
        },
        model: 'claude-sonnet-4-6',
      });
      await pipeline.handle(textEnvelope);
      // Find the UPDATE call (Step 7) -- INSERT is call 0.
      const updateCall = pool.query.mock.calls.find(
        (c) => /UPDATE signal_capture\s+SET llm_reply/.test(c[0])
      );
      expect(updateCall).toBeDefined();
      const [sql, params] = updateCall;
      expect(sql).toMatch(/input_tokens/);
      expect(sql).toMatch(/output_tokens/);
      expect(sql).toMatch(/cache_creation_input_tokens/);
      expect(sql).toMatch(/cache_read_input_tokens/);
      expect(sql).toMatch(/model/);
      expect(params).toHaveLength(8);
      expect(params[0]).toBe('logged inoc-2026-05-18'); // llm_reply
      expect(params[1]).toBe(false);                     // degraded
      expect(params[2]).toBe(100);                       // input_tokens
      expect(params[3]).toBe(50);                        // output_tokens
      expect(params[4]).toBe(0);                         // cache_creation_input_tokens
      expect(params[5]).toBe(0);                         // cache_read_input_tokens
      expect(params[6]).toBe('claude-sonnet-4-6');       // model
      expect(typeof params[7]).toBe('string');           // id (ulid)
    });

    test('usage missing entirely: UPDATE still fires, token params bind as null without throwing', async () => {
      llmClient.compose.mockResolvedValueOnce({
        ok: true,
        text: 'ok',
        usage: null,
        model: 'claude-sonnet-4-6',
      });
      await expect(pipeline.handle(textEnvelope)).resolves.not.toThrow();
      const updateCall = pool.query.mock.calls.find(
        (c) => /UPDATE signal_capture\s+SET llm_reply/.test(c[0])
      );
      expect(updateCall).toBeDefined();
      const [, params] = updateCall;
      expect(params[2]).toBeNull();
      expect(params[3]).toBeNull();
      expect(params[4]).toBeNull();
      expect(params[5]).toBeNull();
      expect(params[6]).toBe('claude-sonnet-4-6');
    });

    test('partial usage (only input/output_tokens): missing cache cols bind null', async () => {
      llmClient.compose.mockResolvedValueOnce({
        ok: true,
        text: 'ok',
        usage: { input_tokens: 200, output_tokens: 75 },
        model: 'claude-sonnet-4-6',
      });
      await pipeline.handle(textEnvelope);
      const updateCall = pool.query.mock.calls.find(
        (c) => /UPDATE signal_capture\s+SET llm_reply/.test(c[0])
      );
      const [, params] = updateCall;
      expect(params[2]).toBe(200);
      expect(params[3]).toBe(75);
      expect(params[4]).toBeNull();
      expect(params[5]).toBeNull();
    });

    test('degraded LLM (compose ok:false): no Step 7 UPDATE invoked (preserves existing behavior)', async () => {
      llmClient.compose.mockResolvedValueOnce({ ok: false, reason: 'rate limit' });
      await pipeline.handle(textEnvelope);
      const updateCall = pool.query.mock.calls.find(
        (c) => /UPDATE signal_capture\s+SET llm_reply/.test(c[0])
      );
      expect(updateCall).toBeUndefined();
    });
  });
});
