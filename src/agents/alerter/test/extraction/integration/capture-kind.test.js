'use strict';

// Phase 53 BACK-03: capture_kind extractor integration test.
//
// Verifies that the Submission envelope round-trips an optional capture_kind
// field through the extractor.extract() pipeline. Two cases:
//   1. Anthropic returns a tool_use with capture_kind='physical_object_photo'
//      -> result.capture_kind === 'physical_object_photo' on the envelope.
//   2. Anthropic returns a tool_use WITHOUT capture_kind (legacy / partial
//      shape) -> extract() still succeeds; capture_kind is null/undefined
//      (back-compat lock per D-BACK-03).
//
// Hermetic only -- no live LLM call. Prompt few-shot quality is exercised
// by the BACK-04 eval gate (53-04).

const { createExtractor } = require('../../../src/extraction/extractor');

const silentLogger = { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} };

function mockAnthropic({ captureKind }) {
  // Build a single-draft activity envelope; optionally include capture_kind.
  const input = {
    drafts: [
      {
        draft: {
          type: 'activity',
          name: 'sterilize',
          asset_ref: '260519_DT_1',
          event_timestamp: '2026-05-19T00:00:00Z',
          confidence: { name: 0.9, asset_ref: 0.9, event_timestamp: 0.9 },
        },
        per_field_confidence: { name: 0.9, asset_ref: 0.9, event_timestamp: 0.9 },
      },
    ],
    continuity: 'start_new',
    continuity_reason: 'no in-flight',
  };
  if (captureKind !== undefined) input.capture_kind = captureKind;
  return {
    messages: {
      create: jest.fn(async () => ({
        content: [
          { type: 'tool_use', id: 'toolu_mock_53_03', name: 'submit_extraction', input },
        ],
        usage: { input_tokens: 0, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 },
        stop_reason: 'tool_use',
      })),
    },
  };
}

describe('BACK-03 capture_kind extractor passthrough', () => {
  test('capture_kind=physical_object_photo round-trips to result envelope', async () => {
    const client = mockAnthropic({ captureKind: 'physical_object_photo' });
    const extractor = createExtractor({ apiKey: 'sk-mock', client, logger: silentLogger });
    const result = await extractor.extract({
      captures: [{ captureId: 'CAP-1', text: 'DT tubs 0519 1 and 2', transcript: null, images: [] }],
      inFlightDraft: null,
      corpusContext: null,
    });
    expect(result.ok).toBe(true);
    // The extractor returns the validated Submission envelope as-is; the
    // capture_kind lives on the top-level envelope per BACK-03 schema decision.
    expect(result.capture_kind).toBe('physical_object_photo');
  });

  test('capture_kind=paper_log round-trips', async () => {
    const client = mockAnthropic({ captureKind: 'paper_log' });
    const extractor = createExtractor({ apiKey: 'sk-mock', client, logger: silentLogger });
    const result = await extractor.extract({
      captures: [{ captureId: 'CAP-2', text: 'notebook page scan', transcript: null, images: [] }],
      inFlightDraft: null,
      corpusContext: { default_year: 2025, source: 'paper_log' },
    });
    expect(result.ok).toBe(true);
    expect(result.capture_kind).toBe('paper_log');
  });

  test('back-compat: envelope without capture_kind -> extract succeeds, capture_kind absent/null', async () => {
    const client = mockAnthropic({ captureKind: undefined });
    const extractor = createExtractor({ apiKey: 'sk-mock', client, logger: silentLogger });
    const result = await extractor.extract({
      captures: [{ captureId: 'CAP-3', text: 'plain text', transcript: null, images: [] }],
      inFlightDraft: null,
      corpusContext: null,
    });
    expect(result.ok).toBe(true);
    // Either undefined or null -- both are acceptable per the nullable+optional schema.
    expect(result.capture_kind == null).toBe(true);
  });
});
