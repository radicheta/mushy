'use strict';

// Phase 44 Plan-04 Task 4.2: Haiku 4.5 classifier (mocked SDK).
// Covers GATE-02 mocked-SDK shape per CONTEXT D-02; fail-OPEN on error/timeout
// (D-03); zod tool_use input shape validation; cache-control / ≥4096-token system.

const fs = require('fs');
const path = require('path');

const { createHaikuClassifier } = require('../../src/event-gate/haiku-classifier');
const { CACHEABLE_SYSTEM_BLOCKS, SYSTEM_PROMPT, HOLDOUT_ROW_IDS } = require('../../src/event-gate/prompts');

function fakeOkResp(input = { is_event: true, kind: 'observation', confidence: 0.91 }) {
  return {
    content: [{ type: 'tool_use', name: 'classify_capture', input }],
    usage: { input_tokens: 10, output_tokens: 5 },
  };
}

describe('event-gate/haiku-classifier', () => {
  test('Test 1: accepts injected client; defers live Anthropic construction', () => {
    const fake = { messages: { create: jest.fn() } };
    const c = createHaikuClassifier({ apiKey: 'test', client: fake });
    expect(typeof c.classify).toBe('function');
  });

  test('Test 2: issues messages.create with model, max_tokens, system, tool_choice', async () => {
    const fake = { messages: { create: jest.fn().mockResolvedValue(fakeOkResp()) } };
    const c = createHaikuClassifier({ apiKey: 'test', client: fake });
    await c.classify({ text: 'logged SHI today', attachmentCount: 0 });
    expect(fake.messages.create).toHaveBeenCalledTimes(1);
    const req = fake.messages.create.mock.calls[0][0];
    expect(req.model).toBe('claude-haiku-4-5-20251001');
    expect(req.max_tokens).toBe(100);
    expect(req.system).toBe(CACHEABLE_SYSTEM_BLOCKS);
    expect(Array.isArray(req.tools)).toBe(true);
    expect(req.tools[0].name).toBe('classify_capture');
    expect(req.tool_choice).toEqual({ type: 'tool', name: 'classify_capture' });
  });

  test('Test 3: successful tool_use → {ok:true, is_event, kind, confidence}', async () => {
    const fake = { messages: { create: jest.fn().mockResolvedValue(fakeOkResp()) } };
    const c = createHaikuClassifier({ apiKey: 'test', client: fake });
    const r = await c.classify({ text: 'foo', attachmentCount: 0 });
    expect(r.ok).toBe(true);
    expect(r.is_event).toBe(true);
    expect(r.kind).toBe('observation');
    expect(r.confidence).toBe(0.91);
  });

  test('Test 4: SDK error → {ok:false, reason, fallthrough:forced}', async () => {
    const fake = { messages: { create: jest.fn().mockRejectedValue(new Error('boom')) } };
    const c = createHaikuClassifier({ apiKey: 'test', client: fake, logger: { warn: () => {} } });
    const r = await c.classify({ text: 'foo', attachmentCount: 0 });
    expect(r.ok).toBe(false);
    expect(r.fallthrough).toBe('forced');
    expect(r.reason).toMatch(/boom/);
  });

  test('Test 5: missing tool_use block → {ok:false, no_tool_use_in_response, forced}', async () => {
    const fake = {
      messages: { create: jest.fn().mockResolvedValue({ content: [{ type: 'text', text: 'no tool' }] }) },
    };
    const c = createHaikuClassifier({ apiKey: 'test', client: fake, logger: { warn: () => {} } });
    const r = await c.classify({ text: 'foo', attachmentCount: 0 });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('no_tool_use_in_response');
    expect(r.fallthrough).toBe('forced');
  });

  test('Test 6: zod validation failure → {ok:false, reason}', async () => {
    const fake = {
      messages: {
        create: jest.fn().mockResolvedValue({
          content: [{ type: 'tool_use', name: 'classify_capture', input: { is_event: 'yes', kind: 'observation', confidence: 0.9 } }],
        }),
      },
    };
    const c = createHaikuClassifier({ apiKey: 'test', client: fake, logger: { warn: () => {} } });
    const r = await c.classify({ text: 'foo', attachmentCount: 0 });
    expect(r.ok).toBe(false);
    expect(r.fallthrough).toBe('forced');
  });

  test('Test 7: prompts.SYSTEM_PROMPT.length > 20000', () => {
    expect(SYSTEM_PROMPT.length).toBeGreaterThan(20000);
  });

  test('Test 8: CACHEABLE_SYSTEM_BLOCKS uses cache_control ephemeral', () => {
    expect(CACHEABLE_SYSTEM_BLOCKS[0].cache_control).toEqual({ type: 'ephemeral' });
  });

  test('Test 9: timeout uses AbortSignal.timeout(2000) on messages.create', async () => {
    const fake = { messages: { create: jest.fn().mockResolvedValue(fakeOkResp()) } };
    const c = createHaikuClassifier({ apiKey: 'test', client: fake, timeoutMs: 2000 });
    await c.classify({ text: 'foo', attachmentCount: 0 });
    // SDK accepts signal at the top-level options OR as second arg; we pass it on the request object as `signal`.
    const req = fake.messages.create.mock.calls[0][0];
    expect(req.signal).toBeDefined();
    // AbortSignal-shaped: has aborted property and addEventListener.
    expect(typeof req.signal.aborted).toBe('boolean');
  });

  test('Test 10 (W10 holdout): SYSTEM_PROMPT does NOT contain any holdout row text', () => {
    const jsonlPath = path.join(__dirname, '..', '..', '..', '..', '..', '.planning', 'phases',
      '44-event-gate-durable-signal-outbound-tenant-aware', '44-hand-classified-100.jsonl');
    const rows = fs.readFileSync(jsonlPath, 'utf8').trim().split('\n').map((l) => JSON.parse(l));
    const byId = new Map(rows.map((r) => [r.capture_id, r]));
    expect(HOLDOUT_ROW_IDS.length).toBeGreaterThanOrEqual(10);
    for (const id of HOLDOUT_ROW_IDS) {
      const row = byId.get(id);
      expect(row).toBeTruthy();
      const txt = (row.raw_text || row.transcript || '').trim();
      if (txt && txt.length >= 8) {
        expect(SYSTEM_PROMPT.includes(txt)).toBe(false);
      }
    }
  });
});
