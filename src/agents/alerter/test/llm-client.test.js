'use strict';

/**
 * RED skeleton tests for llm-client (Wave 3 implements the subject).
 * Skip-guard: if ../src/llm-client or @anthropic-ai/sdk doesn't exist yet, all tests are skipped.
 * Remove the try/catch wrapper and switch jest.doMock→jest.mock in Wave 3.
 */

let createLlmClient;
let subjectMissing = false;
let MockAnthropic;
let mockCreate;

try {
  // Check SDK is present before mocking; both must exist to run tests.
  require.resolve('@anthropic-ai/sdk');
  require.resolve('../src/llm-client');

  mockCreate = jest.fn();
  MockAnthropic = jest.fn().mockImplementation(() => ({
    messages: { create: mockCreate },
  }));
  MockAnthropic._mockCreate = mockCreate;

  jest.doMock('@anthropic-ai/sdk', () => MockAnthropic);
  ({ createLlmClient } = require('../src/llm-client'));
} catch (_) {
  subjectMissing = true;
}

const describeFn = subjectMissing ? describe.skip : describe;

describeFn('createLlmClient', () => {
  let client;

  beforeEach(() => {
    mockCreate.mockReset();
    client = createLlmClient({ apiKey: 'test-key' });
  });

  test('(R5) success — client.messages.create returns stub → compose() returns { ok: true, text }', async () => {
    mockCreate.mockResolvedValue({
      content: [{ type: 'text', text: 'logged inoculation batch 2026-04-27' }],
    });
    const result = await client.compose({
      currentMessage: 'logged 3 jars',
      history: [],
      sensorSnapshot: { humidity: 90, temperature: 22, co2: 600 },
    });
    expect(result.ok).toBe(true);
    expect(typeof result.text).toBe('string');
  });

  test('(R5) client.messages.create throws — compose() returns { ok: false, reason } without throwing', async () => {
    mockCreate.mockRejectedValue(new Error('API error'));
    const result = await client.compose({
      currentMessage: 'test',
      history: [],
      sensorSnapshot: {},
    });
    expect(result.ok).toBe(false);
    expect(typeof result.reason).toBe('string');
  });

  test('(R5) prompt assembly — messages.create called with correct model, max_tokens, and content blocks', async () => {
    mockCreate.mockResolvedValue({
      content: [{ type: 'text', text: 'ok' }],
    });
    await client.compose({
      currentMessage: 'tray 4 pinning',
      history: [{ role: 'user', content: 'earlier message' }],
      sensorSnapshot: { humidity: 88, temperature: 21, co2: 580 },
    });
    expect(mockCreate).toHaveBeenCalledTimes(1);
    const callArgs = mockCreate.mock.calls[0][0];
    expect(callArgs.model).toBe('claude-sonnet-4-6');
    expect(callArgs.max_tokens).toBe(150);
    // user content must reference rolling history, sensor snapshot, and current message
    const userContent = JSON.stringify(callArgs.messages);
    expect(userContent).toMatch(/earlier message/);
    expect(userContent).toMatch(/humidity|co2|temperature/i);
    expect(userContent).toMatch(/tray 4 pinning/);
  });
});
