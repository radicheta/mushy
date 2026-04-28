'use strict';

/**
 * Tests for llm-client (Phase 25-04, R5).
 * Mocks @anthropic-ai/sdk; asserts prompt shape and never-throw discipline.
 */

const mockCreate = jest.fn();
jest.mock('@anthropic-ai/sdk', () => {
  return jest.fn().mockImplementation(() => ({
    messages: { create: mockCreate },
  }));
});

const { createLlmClient, _internal } = require('../src/llm-client');

const silentLogger = { warn: () => {}, info: () => {}, error: () => {} };

function baseMessage(overrides = {}) {
  return {
    text: 'logged 3 jars',
    transcript: '',
    attachmentCount: 0,
    capturedAtMs: Date.parse('2026-04-27T14:30:12Z'),
    ...overrides,
  };
}

describe('createLlmClient', () => {
  let client;

  beforeEach(() => {
    mockCreate.mockReset();
    client = createLlmClient({ apiKey: 'sk-test-key', logger: silentLogger });
  });

  test('(R5) success — SDK returns text → compose() returns { ok: true, text }', async () => {
    mockCreate.mockResolvedValueOnce({
      content: [{ type: 'text', text: 'logged inoc-2026-04-27' }],
    });
    const result = await client.compose({
      currentMessage: baseMessage(),
      history: [],
      sensorSnapshot: { sensors: { humidity: 90, temperature: 22, co2: 600 } },
    });
    expect(result).toEqual({ ok: true, text: 'logged inoc-2026-04-27' });
  });

  test('(R6) SDK throws → compose() returns { ok: false, reason } without throwing', async () => {
    mockCreate.mockRejectedValueOnce(new Error('rate limit'));
    let threw = false;
    let result;
    try {
      result = await client.compose({
        currentMessage: baseMessage(),
        history: [],
        sensorSnapshot: null,
      });
    } catch (_) {
      threw = true;
    }
    expect(threw).toBe(false);
    expect(result.ok).toBe(false);
    expect(typeof result.reason).toBe('string');
    expect(result.reason).toMatch(/rate limit/);
  });

  test('(prompt shape) messages.create called with correct model, max_tokens, system, user block', async () => {
    mockCreate.mockResolvedValueOnce({ content: [{ type: 'text', text: 'ok' }] });
    await client.compose({
      currentMessage: baseMessage({ text: 'tray 4 pinning', attachmentCount: 2 }),
      history: [],
      sensorSnapshot: { sensors: { humidity: 88, temperature: 21, co2: 580 } },
    });
    expect(mockCreate).toHaveBeenCalledTimes(1);
    const args = mockCreate.mock.calls[0][0];
    expect(args.model).toBe('claude-sonnet-4-6');
    expect(args.max_tokens).toBe(150);
    expect(args.system).toMatch(/≤2 lines/);
    expect(args.system).toMatch(/session tag/);
    const userContent = args.messages[0].content;
    expect(userContent).toMatch(/## Current message/);
    expect(userContent).toMatch(/## Sensor snapshot/);
    expect(userContent).toMatch(/## Recent history/);
  });

  test('(D-10) history rows formatted oldest-first, capped at 20 when 25 supplied', async () => {
    mockCreate.mockResolvedValueOnce({ content: [{ type: 'text', text: 'ok' }] });
    const history = [];
    for (let i = 0; i < 25; i++) {
      history.push({
        captured_at: new Date(Date.parse('2026-04-27T08:00:00Z') + i * 60000),
        message_type: 'text',
        raw_text: `msg ${i}`,
      });
    }
    await client.compose({
      currentMessage: baseMessage(),
      history,
      sensorSnapshot: null,
    });
    const userContent = mockCreate.mock.calls[0][0].messages[0].content;
    expect(userContent).toMatch(/## Recent history/);
    // Only the last 20 (msg 5..msg 24) should appear; msg 0..4 dropped.
    expect(userContent).not.toMatch(/'msg 0'/);
    expect(userContent).not.toMatch(/'msg 4'/);
    expect(userContent).toMatch(/'msg 5'/);
    expect(userContent).toMatch(/'msg 24'/);
    // Count history bracketed lines.
    const lines = userContent.split('\n').filter((l) => /^\s+\[20\d\d-/.test(l));
    expect(lines.length).toBeLessThanOrEqual(20);
  });

  test('(D-11) sensor snapshot rendered; null snapshot → "(unavailable)"', async () => {
    mockCreate.mockResolvedValueOnce({ content: [{ type: 'text', text: 'ok' }] });
    await client.compose({
      currentMessage: baseMessage(),
      history: [],
      sensorSnapshot: { sensors: { humidity: 90.1, temperature: 22, co2: 600 } },
    });
    let userContent = mockCreate.mock.calls[0][0].messages[0].content;
    expect(userContent).toMatch(/humidity: 90\.1/);
    expect(userContent).toMatch(/temperature: 22/);
    expect(userContent).toMatch(/co2: 600/);

    mockCreate.mockResolvedValueOnce({ content: [{ type: 'text', text: 'ok' }] });
    await client.compose({
      currentMessage: baseMessage(),
      history: [],
      sensorSnapshot: null,
    });
    userContent = mockCreate.mock.calls[1][0].messages[0].content;
    expect(userContent).toMatch(/\(unavailable\)/);
  });

  test('(V2) API key never appears in console.warn output', async () => {
    const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
    const realLoggerClient = createLlmClient({ apiKey: 'sk-secret-shhhh' });
    mockCreate.mockRejectedValueOnce(new Error('boom'));
    await realLoggerClient.compose({
      currentMessage: baseMessage(),
      history: [],
      sensorSnapshot: null,
    });
    for (const call of warnSpy.mock.calls) {
      const joined = call.map(String).join(' ');
      expect(joined).not.toMatch(/sk-/);
    }
    warnSpy.mockRestore();
  });

  test('(buildUserBlock) deterministic shape via _internal export', () => {
    const block = _internal.buildUserBlock({
      currentMessage: baseMessage({ text: 'hello', transcript: 'audio body' }),
      history: [],
      sensorSnapshot: null,
    });
    expect(block).toMatch(/time: 2026-04-27T14:30:12/);
    expect(block).toMatch(/text: 'hello'/);
    expect(block).toMatch(/transcript: 'audio body'/);
    expect(block).toMatch(/attachments: 0/);
  });
});
