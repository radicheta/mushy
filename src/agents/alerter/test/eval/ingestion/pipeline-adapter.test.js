'use strict';

// Phase 41 Plan 02 Task 3: pipeline-adapter unit tests.
// Pure-JS; fake extractor + transcribe + loadImageBlocks injected via DI.

const { runFixtureThroughPipeline } = require('./pipeline-adapter');

function makeStubs(overrides = {}) {
  const extractorCalls = [];
  const transcribeCalls = [];
  const loadImageBlocksCalls = [];
  return {
    extractorCalls,
    transcribeCalls,
    loadImageBlocksCalls,
    extractor: {
      async extract(payload) {
        extractorCalls.push(payload);
        return overrides.extractorResult || { ok: true, draft: { type: 'seeding' }, per_field_confidence: {} };
      },
    },
    transcribe: {
      async transcribe(arg) {
        transcribeCalls.push(arg);
        return { ok: true, text: overrides.transcriptText != null ? overrides.transcriptText : 'transcript-text' };
      },
    },
    loadImageBlocks: async (paths) => {
      loadImageBlocksCalls.push(paths);
      return paths.map((p) => ({ type: 'image', source: p }));
    },
  };
}

describe('pipeline-adapter runFixtureThroughPipeline', () => {
  test('image-only: transcribe not called, transcribe_latency_ms = 0', async () => {
    const s = makeStubs();
    const fx = {
      name: 'fx1',
      kind: 'synthetic',
      envelope: { body: 'hello' },
      attachments: [{ type: 'image', path: '/tmp/a.jpg' }],
      expected: { fields: {} },
    };
    const r = await runFixtureThroughPipeline(fx, s);
    expect(s.transcribeCalls.length).toBe(0);
    expect(r.transcribe_latency_ms).toBe(0);
    expect(s.loadImageBlocksCalls.length).toBe(1);
    expect(s.extractorCalls[0].text).toBe('hello');
    expect(r.actual.ok).toBe(true);
  });

  test('audio-only: composedText equals transcript', async () => {
    const s = makeStubs({ transcriptText: 'spoken' });
    const fx = {
      name: 'fx2',
      kind: 'synthetic',
      envelope: { body: '' },
      attachments: [{ type: 'audio', path: '/tmp/a.m4a' }],
      expected: { fields: {} },
    };
    const r = await runFixtureThroughPipeline(fx, s);
    expect(s.transcribeCalls.length).toBe(1);
    expect(s.extractorCalls[0].text).toBe('spoken');
    expect(s.extractorCalls[0].imageBlocks).toEqual([]);
    expect(r.transcribe_latency_ms).toBeGreaterThanOrEqual(0);
  });

  test('multimodal: composedText = envelope.body + newline + transcript', async () => {
    const s = makeStubs({ transcriptText: 'spoken' });
    const fx = {
      name: 'fx3',
      kind: 'synthetic',
      envelope: { body: 'written' },
      attachments: [
        { type: 'image', path: '/tmp/a.jpg' },
        { type: 'audio', path: '/tmp/a.m4a' },
      ],
      expected: { fields: {} },
    };
    const r = await runFixtureThroughPipeline(fx, s);
    expect(s.extractorCalls[0].text).toBe('written\nspoken');
    expect(r.actual.ok).toBe(true);
  });

  test('extractor error path: returns actual.ok=false, error set, draft null', async () => {
    const s = makeStubs({ extractorResult: { ok: false, reason: 'schema_invalid' } });
    const fx = {
      name: 'fx4',
      kind: 'synthetic',
      envelope: { body: 'x' },
      attachments: [],
      expected: { fields: {} },
    };
    const r = await runFixtureThroughPipeline(fx, s);
    expect(r.actual.ok).toBe(false);
    expect(r.actual.draft).toBe(null);
    expect(r.error).toBe('schema_invalid');
  });

  test('two audio attachments: transcript parts joined by newline', async () => {
    let n = 0;
    const calls = [];
    const transcribe = {
      async transcribe(arg) {
        calls.push(arg);
        n += 1;
        return { ok: true, text: `part${n}` };
      },
    };
    const extractor = { async extract(p) { return { ok: true, draft: { received: p.text } }; } };
    const fx = {
      name: 'fx5',
      kind: 'synthetic',
      envelope: { body: '' },
      attachments: [
        { type: 'audio', path: '/tmp/a.m4a' },
        { type: 'audio', path: '/tmp/b.m4a' },
      ],
      expected: { fields: {} },
    };
    const r = await runFixtureThroughPipeline(fx, { extractor, transcribe, loadImageBlocks: async () => [] });
    expect(calls.length).toBe(2);
    expect(r.actual.draft).toEqual({ received: 'part1\npart2' });
  });
});
