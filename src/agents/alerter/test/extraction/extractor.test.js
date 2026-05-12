'use strict';

// Phase 38 Plan 03 Task 2: extractor unit tests.
// Mocks @anthropic-ai/sdk per test/llm-client.test.js pattern.
// Covers: happy path, multimodal fusion, schema-invalid retry, retry-twice-fail,
// SDK throws, API-key-never-leaks, tool_choice forces submit_extraction,
// DRAFT/SUBMISSION input_schema wired.

const mockCreate = jest.fn();
jest.mock('@anthropic-ai/sdk', () => {
  return jest.fn().mockImplementation(() => ({
    messages: { create: mockCreate },
  }));
});

const { createExtractor, _internal } = require('../../src/extraction/extractor');
const { Submission, SUBMISSION_JSON_SCHEMA } = require('../../src/extraction/schemas');

const silentLogger = { warn: () => {}, info: () => {}, error: () => {} };

function validInput() {
  // Plan 08 multi-draft Submission shape.
  return {
    drafts: [
      {
        draft: {
          type: 'seeding',
          species: 'shiitake',
          block_name: '260512_SHI_1',
          qty: 12,
          event_timestamp: '2026-05-12T00:00:00Z',
          confidence: { species: 0.95, block_name: 0.95, qty: 0.95, event_timestamp: 0.6 },
        },
        per_field_confidence: { species: 0.95, block_name: 0.95, qty: 0.95, event_timestamp: 0.6 },
      },
    ],
    continuity: 'start_new',
    continuity_reason: 'No in-flight draft.',
  };
}

function toolUseResponse(input, id = 'tu_1') {
  return {
    id: 'msg_x',
    type: 'message',
    role: 'assistant',
    content: [{ type: 'tool_use', id, name: 'submit_extraction', input }],
    stop_reason: 'tool_use',
    usage: { input_tokens: 10, output_tokens: 10 },
  };
}

describe('createExtractor', () => {
  let extractor;

  beforeEach(() => {
    mockCreate.mockReset();
    extractor = createExtractor({ apiKey: 'sk-test-key', logger: silentLogger });
  });

  test('(R1) happy path -- text-only capture returns ok+draft+continuity', async () => {
    mockCreate.mockResolvedValueOnce(toolUseResponse(validInput()));
    const result = await extractor.extract({
      captures: [{ text: 'seeded 12 blocks shiitake' }],
      inFlightDraft: null,
    });
    expect(result.ok).toBe(true);
    expect(result.draft.type).toBe('seeding');
    expect(result.draft.qty).toBe(12);
    expect(result.continuity_decision).toBe('start_new');
    expect(result.continuity_reason).toMatch(/in-flight/i);
    expect(result.per_field_confidence).toEqual(expect.any(Object));
  });

  test('(R2) multimodal fusion -- text + transcript + image yields ONE call with all modalities', async () => {
    mockCreate.mockResolvedValueOnce(toolUseResponse(validInput()));
    await extractor.extract({
      captures: [{
        text: 'block 4 pinning',
        transcript: 'voice memo body',
        images: [{ data: 'aGVsbG8=', media_type: 'image/jpeg' }],
      }],
      inFlightDraft: null,
    });
    expect(mockCreate).toHaveBeenCalledTimes(1);
    const args = mockCreate.mock.calls[0][0];
    const userContent = args.messages[args.messages.length - 1].content;
    expect(Array.isArray(userContent)).toBe(true);
    // Expect: in-flight-draft text + new text + transcript text + image = 4 blocks
    expect(userContent.length).toBeGreaterThanOrEqual(4);
    const types = userContent.map((b) => b.type);
    expect(types).toContain('image');
    const imgBlock = userContent.find((b) => b.type === 'image');
    expect(imgBlock.source).toEqual({ type: 'base64', media_type: 'image/jpeg', data: 'aGVsbG8=' });
  });

  test('(R3) schema-invalid first response triggers tool_result retry; second valid -> ok', async () => {
    const bad = { ...validInput(), continuity: 'maybe' }; // invalid enum
    mockCreate.mockResolvedValueOnce(toolUseResponse(bad, 'tu_first'));
    mockCreate.mockResolvedValueOnce(toolUseResponse(validInput(), 'tu_second'));
    const result = await extractor.extract({
      captures: [{ text: 'seeded 12 blocks shiitake' }],
      inFlightDraft: null,
    });
    expect(result.ok).toBe(true);
    expect(mockCreate).toHaveBeenCalledTimes(2);
    // Second call must carry a tool_result with is_error:true referencing tu_first
    const secondArgs = mockCreate.mock.calls[1][0];
    const flat = JSON.stringify(secondArgs);
    expect(flat).toMatch(/tool_result/);
    expect(flat).toMatch(/tu_first/);
    expect(flat).toMatch(/is_error/);
  });

  test('(R4) schema-invalid twice -> {ok:false, reason:"schema_invalid"}', async () => {
    const bad = { ...validInput(), continuity: 'nope' };
    mockCreate.mockResolvedValueOnce(toolUseResponse(bad, 'tu_1'));
    mockCreate.mockResolvedValueOnce(toolUseResponse(bad, 'tu_2'));
    const result = await extractor.extract({
      captures: [{ text: 'seeded 12 blocks shiitake' }],
      inFlightDraft: null,
    });
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('schema_invalid');
    expect(mockCreate).toHaveBeenCalledTimes(2);
  });

  test('(R5) SDK throws -> {ok:false, reason} without throwing', async () => {
    mockCreate.mockRejectedValueOnce(new Error('rate limit'));
    let threw = false;
    let result;
    try {
      result = await extractor.extract({ captures: [{ text: 'hi' }], inFlightDraft: null });
    } catch (_) {
      threw = true;
    }
    expect(threw).toBe(false);
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/rate limit/);
  });

  test('(R6) API key never appears in logger calls', async () => {
    const warnSpy = jest.fn();
    const infoSpy = jest.fn();
    const errSpy = jest.fn();
    const spyLogger = { warn: warnSpy, info: infoSpy, error: errSpy };
    const localExt = createExtractor({ apiKey: 'sk-secret-shhhh', logger: spyLogger });
    mockCreate.mockRejectedValueOnce(new Error('boom'));
    await localExt.extract({ captures: [{ text: 'x' }], inFlightDraft: null });
    for (const spy of [warnSpy, infoSpy, errSpy]) {
      for (const call of spy.mock.calls) {
        const joined = call.map(String).join(' ');
        expect(joined).not.toMatch(/sk-/);
      }
    }
  });

  test('(R7) tool_choice forces submit_extraction', async () => {
    mockCreate.mockResolvedValueOnce(toolUseResponse(validInput()));
    await extractor.extract({ captures: [{ text: 'x' }], inFlightDraft: null });
    const args = mockCreate.mock.calls[0][0];
    expect(args.tool_choice).toEqual({ type: 'tool', name: 'submit_extraction' });
    expect(Array.isArray(args.tools)).toBe(true);
    expect(args.tools[0].name).toBe('submit_extraction');
  });

  test('(R8) SUBMISSION_JSON_SCHEMA wired as input_schema', async () => {
    mockCreate.mockResolvedValueOnce(toolUseResponse(validInput()));
    await extractor.extract({ captures: [{ text: 'x' }], inFlightDraft: null });
    const args = mockCreate.mock.calls[0][0];
    expect(args.tools[0].input_schema).toBeDefined();
    // SUBMISSION_JSON_SCHEMA from zodToJsonSchema with name 'Submission' emits {$ref, definitions}
    const flat = JSON.stringify(args.tools[0].input_schema);
    expect(flat).toMatch(/Submission|continuity/);
  });

  test('(prompt shape) cache_control:ephemeral applied to system block', async () => {
    mockCreate.mockResolvedValueOnce(toolUseResponse(validInput()));
    await extractor.extract({ captures: [{ text: 'x' }], inFlightDraft: null });
    const args = mockCreate.mock.calls[0][0];
    expect(Array.isArray(args.system)).toBe(true);
    expect(args.system[0]).toEqual(expect.objectContaining({
      type: 'text',
      cache_control: { type: 'ephemeral' },
    }));
  });

  test('(in-flight draft) renders into first user text block', async () => {
    mockCreate.mockResolvedValueOnce(toolUseResponse(validInput()));
    const inFlight = { type: 'seeding', species: 'shiitake', qty: 10 };
    await extractor.extract({ captures: [{ text: 'correction 14' }], inFlightDraft: inFlight });
    const args = mockCreate.mock.calls[0][0];
    const userContent = args.messages[args.messages.length - 1].content;
    const flat = JSON.stringify(userContent);
    expect(flat).toMatch(/shiitake/);
  });
});
