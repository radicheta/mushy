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

describe('Phase 39 D-03: farmerCorrection plumbing', () => {
  const { buildInitialUserContent } = _internal;
  let extractor;
  beforeEach(() => {
    mockCreate.mockReset();
    extractor = createExtractor({ apiKey: 'sk-test', logger: silentLogger });
  });

  test('null/undefined/empty/whitespace farmerCorrection produces unchanged blocks (regression vs Phase 38 Plan 09 PASS)', () => {
    const base = buildInitialUserContent({ captures: [], inFlightDraft: null });
    const withNull = buildInitialUserContent({ captures: [], inFlightDraft: null, farmerCorrection: null });
    const withUndef = buildInitialUserContent({ captures: [], inFlightDraft: null, farmerCorrection: undefined });
    const withEmpty = buildInitialUserContent({ captures: [], inFlightDraft: null, farmerCorrection: '' });
    const withWs = buildInitialUserContent({ captures: [], inFlightDraft: null, farmerCorrection: '   ' });
    expect(JSON.stringify(withNull)).toBe(JSON.stringify(base));
    expect(JSON.stringify(withUndef)).toBe(JSON.stringify(base));
    expect(JSON.stringify(withEmpty)).toBe(JSON.stringify(base));
    expect(JSON.stringify(withWs)).toBe(JSON.stringify(base));
  });

  test('non-empty farmerCorrection prepends exactly one text block after the In-flight draft block', () => {
    const blocks = buildInitialUserContent({
      captures: [],
      inFlightDraft: { type: 'seeding' },
      farmerCorrection: 'qty was 7 not 5',
    });
    const idxInFlight = blocks.findIndex((b) => b.type === 'text' && /In-flight draft/.test(b.text));
    const idxCorrection = blocks.findIndex((b) => b.type === 'text' && /Farmer correction/.test(b.text));
    expect(idxInFlight).toBeGreaterThanOrEqual(0);
    expect(idxCorrection).toBe(idxInFlight + 1);
    expect(blocks[idxCorrection].text).toBe('Farmer correction: qty was 7 not 5');
  });

  test('whitespace-only farmerCorrection short-circuits (no new block)', () => {
    const blocks = buildInitialUserContent({
      captures: [],
      inFlightDraft: null,
      farmerCorrection: '   ',
    });
    expect(blocks.some((b) => b.type === 'text' && /Farmer correction/.test(b.text))).toBe(false);
  });

  test('farmerCorrection reaches buildInitialUserContent when passed via extract()', async () => {
    mockCreate.mockResolvedValueOnce(toolUseResponse(validInput()));
    await extractor.extract({
      captures: [],
      inFlightDraft: { type: 'seeding' },
      farmerCorrection: 'change qty to 12',
    });
    const args = mockCreate.mock.calls[0][0];
    const userContent = args.messages[args.messages.length - 1].content;
    expect(JSON.stringify(userContent)).toMatch(/Farmer correction: change qty to 12/);
  });
});

describe('Phase 47 Plan 02: SYSTEM_PROMPT teaches seeding_session policy', () => {
  const { CACHEABLE_SYSTEM_BLOCKS } = require('../../src/extraction/prompts/system');
  const promptText = CACHEABLE_SYSTEM_BLOCKS[0].text;

  test('mentions seeding_session token', () => {
    expect(promptText).toMatch(/seeding_session/);
  });

  test('mentions NEEDS_SEQ sentinel', () => {
    expect(promptText).toContain('NEEDS_SEQ');
  });

  test('mentions photo_wins_implicit conflict resolution', () => {
    expect(promptText).toContain('photo_wins_implicit');
  });

  test('mentions needs_input + starting_seq ask-back', () => {
    expect(promptText).toContain('needs_input');
    expect(promptText).toContain('starting_seq');
  });

  test('mentions conflicts[] forensics array', () => {
    expect(promptText).toContain('conflicts');
  });

  test('mentions NO_PARENT sentinel for fresh-grain inoc', () => {
    expect(promptText).toContain('NO_PARENT');
  });

  test('mentions session-vs-single cardinality rule (groups + total)', () => {
    expect(promptText).toMatch(/groups/);
  });

  test('contains no em-dashes', () => {
    expect(promptText).not.toMatch(/—/);
  });
});

describe('Phase 47 Plan 02: FEW_SHOT includes May-22 multi-parent seeding_session example', () => {
  const { FEW_SHOT } = require('../../src/extraction/prompts/system');
  const { Submission } = require('../../src/extraction/schemas');

  function findToolUseById(id) {
    for (const msg of FEW_SHOT) {
      if (msg.role !== 'assistant' || !Array.isArray(msg.content)) continue;
      for (const b of msg.content) {
        if (b && b.type === 'tool_use' && b.id === id) return b;
      }
    }
    return null;
  }

  test('tu_fewshot_4 tool_use exists', () => {
    const tu = findToolUseById('tu_fewshot_4');
    expect(tu).not.toBeNull();
    expect(tu.name).toBe('submit_extraction');
  });

  test('tu_fewshot_4 input.drafts[0].draft validates as SeedingSession via Submission', () => {
    const tu = findToolUseById('tu_fewshot_4');
    const parsed = Submission.safeParse(tu.input);
    if (!parsed.success) {
      // surface the zod error to make failure obvious
      throw new Error('Submission.safeParse failed: ' + JSON.stringify(parsed.error.issues, null, 2));
    }
    const draft = parsed.data.drafts[0].draft;
    expect(draft.type).toBe('seeding_session');
    expect(draft.event_date).toBe('2026-05-22');
    expect(draft.groups.length).toBe(5);
    const totalChildren = draft.groups.reduce(
      (n, g) => n + g.child_block_names.value.length,
      0
    );
    expect(totalChildren).toBe(11);
    // Expected canonical block-name set per CONTEXT.md INOC-01
    const allNames = draft.groups.flatMap((g) => g.child_block_names.value);
    const expected = [
      '260522_SHI_1', '260522_SHI_2', '260522_SHI_3',
      '260522_KOY_4', '260522_KOY_5', '260522_KOY_6', '260522_KOY_7',
      '260522_KOY_8', '260522_KOY_9', '260522_KOY_10', '260522_KOY_11',
    ];
    expect(allNames.sort()).toEqual(expected.sort());
  });

  test('FEW_SHOT tool_use blocks each have a matching tool_result in the next user turn (except the final one which extractor.js closes at runtime)', () => {
    const toolUses = [];
    for (let i = 0; i < FEW_SHOT.length; i++) {
      const msg = FEW_SHOT[i];
      if (msg.role !== 'assistant' || !Array.isArray(msg.content)) continue;
      for (const b of msg.content) {
        if (b && b.type === 'tool_use') toolUses.push({ id: b.id, idx: i });
      }
    }
    for (let k = 0; k < toolUses.length; k++) {
      const { id, idx } = toolUses[k];
      const isFinal = k === toolUses.length - 1;
      if (isFinal) {
        // Final tool_use is closed by extractor.buildInitialUserContent's tool_result at runtime.
        // Phase 53 BACK-03: live-turn boundary moved from tu_fewshot_3 to tu_fewshot_6
        // (DT-tubs physical_object_photo few-shot is now the last in the chain).
        expect(id).toBe('tu_fewshot_6');
        continue;
      }
      const nextUser = FEW_SHOT[idx + 1];
      expect(nextUser && nextUser.role).toBe('user');
      const hasResult = nextUser.content.some(
        (b) => b && b.type === 'tool_result' && b.tool_use_id === id
      );
      if (!hasResult) {
        throw new Error(`tool_use ${id} has no matching tool_result in the next user turn`);
      }
      expect(hasResult).toBe(true);
    }
  });

  test('tu_fewshot_6 is the LAST tool_use in FEW_SHOT (live-turn boundary invariant; updated by Phase 53 BACK-03)', () => {
    const ids = [];
    for (const msg of FEW_SHOT) {
      if (msg.role !== 'assistant' || !Array.isArray(msg.content)) continue;
      for (const b of msg.content) {
        if (b && b.type === 'tool_use') ids.push(b.id);
      }
    }
    expect(ids[ids.length - 1]).toBe('tu_fewshot_6');
  });
});

// ============================================================================
// Phase 54 Plan 03: onLlmCall observer hook tests.
// ============================================================================

describe('extractor onLlmCall observer (Phase 54 Plan 03)', () => {
  beforeEach(() => {
    mockCreate.mockReset();
  });

  test('fires once per successful Anthropic call with all documented fields', async () => {
    mockCreate.mockResolvedValueOnce(toolUseResponse(validInput()));
    const observed = [];
    const ex = createExtractor({
      apiKey: 'k', logger: silentLogger,
      onLlmCall: (o) => { observed.push(o); },
    });
    const r = await ex.extract({
      captures: [{ captureId: 'cap-1', text: 'hi' }],
    });
    expect(r.ok).toBe(true);
    expect(observed).toHaveLength(1);
    const o = observed[0];
    expect(o.captureId).toBe('cap-1');
    expect(o.model).toBe('claude-sonnet-4-6');
    expect(typeof o.input_tokens).toBe('number');
    expect(typeof o.output_tokens).toBe('number');
    expect(typeof o.latency_ms).toBe('number');
    expect(o.raw_response).toBeTruthy();
    expect(o.request_hash).toMatch(/^[0-9a-f]{16}$/);
    expect(typeof o.ts).toBe('string');
    expect(o.error).toBeNull();
  });

  test('fires for BOTH the initial call and the schema-retry call', async () => {
    // First call -> invalid (forces retry); second -> valid.
    mockCreate
      .mockResolvedValueOnce(toolUseResponse({ bogus: true }))
      .mockResolvedValueOnce(toolUseResponse(validInput()));
    const observed = [];
    const ex = createExtractor({
      apiKey: 'k', logger: silentLogger,
      onLlmCall: (o) => { observed.push(o); },
    });
    const r = await ex.extract({ captures: [{ captureId: 'cap-2', text: 'x' }] });
    expect(r.ok).toBe(true);
    expect(observed).toHaveLength(2);
    expect(observed.every((o) => o.captureId === 'cap-2')).toBe(true);
  });

  test('observer throwing does not propagate; extract returns normal result', async () => {
    mockCreate.mockResolvedValueOnce(toolUseResponse(validInput()));
    const warnings = [];
    const ex = createExtractor({
      apiKey: 'k',
      logger: { ...silentLogger, warn: (m) => warnings.push(m) },
      onLlmCall: () => { throw new Error('observer-boom'); },
    });
    const r = await ex.extract({ captures: [{ captureId: 'cap-3', text: 'x' }] });
    expect(r.ok).toBe(true);
    expect(warnings.some((m) => /onLlmCall observer threw: observer-boom/.test(m))).toBe(true);
  });

  test('without onLlmCall, no errors and existing call sites unchanged (regression)', async () => {
    mockCreate.mockResolvedValueOnce(toolUseResponse(validInput()));
    const ex = createExtractor({ apiKey: 'k', logger: silentLogger });
    const r = await ex.extract({ captures: [{ text: 'x' }] });
    expect(r.ok).toBe(true);
  });

  test('request_hash differs per request content', async () => {
    mockCreate.mockResolvedValue(toolUseResponse(validInput()));
    const observed = [];
    const ex = createExtractor({
      apiKey: 'k', logger: silentLogger,
      onLlmCall: (o) => { observed.push(o); },
    });
    await ex.extract({ captures: [{ captureId: 'c1', text: 'alpha' }] });
    await ex.extract({ captures: [{ captureId: 'c2', text: 'beta' }] });
    expect(observed[0].request_hash).not.toBe(observed[1].request_hash);
  });
});
