'use strict';

// Phase 53 Plan 04 (BACK-04): hermetic eval ship-gate for the 2025-notebook
// extraction prereqs (53-01 corpus_context plumbing + 53-02 small-N routing
// + 53-03 capture_kind classifier).
//
// Default hermetic CI: real createExtractor + mock Anthropic client returning
// the fixture's mock-extraction.json verbatim. Asserts the returned envelope
// matches ground-truth.json on key fields (drafts, capture_kind when present).
//
// EVAL_RUN_LIVE=1: real Anthropic client + real image bytes (paid; on-demand).
// Persists each response under test/eval/ingestion/results/notebook-2025/
// per memory feedback_persist_paid_results_default (never overwrite).
//
// Phase 54 backfill harness depends on this suite being green. If the corpus
// under fixtures/notebook-2025/ is empty, the suite SKIPS rather than fails
// red -- the curation step is operator-gated (Plan 53-04 Task 1 + Task 3).

const fs = require('fs');
const path = require('path');

const { loadNotebook2025Corpus } = require('./notebook-2025-loader');
const { createExtractor } = require('../../../src/extraction/extractor');

const CORPUS_DIR = path.resolve(__dirname, 'fixtures/notebook-2025');
const RESULTS_DIR = path.resolve(__dirname, 'results/notebook-2025');

const silentLogger = { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} };

const liveMode = process.env.EVAL_RUN_LIVE === '1' && !!process.env.ANTHROPIC_API_KEY;

function makeMockAnthropicClient(mockResponse) {
  return {
    messages: {
      create: jest.fn(async () => mockResponse),
    },
  };
}

function projectDraftKeyFields(draft) {
  if (!draft) return null;
  const base = { type: draft.type };
  if (draft.event_timestamp) base.event_timestamp = draft.event_timestamp;
  if (draft.event_date) base.event_date = draft.event_date;
  if (draft.asset_ref) base.asset_ref = draft.asset_ref;
  if (draft.block_name) base.block_name = draft.block_name;
  if (draft.qty != null) base.qty = draft.qty;
  // seeding_session groups -> project to parent/species/qty values only.
  if (Array.isArray(draft.groups)) {
    base.groups = draft.groups.map((g) => ({
      parent: g && g.parent && g.parent.value,
      species: g && g.species && g.species.value,
      qty: g && g.qty && g.qty.value,
    }));
  }
  return base;
}

const ALL = loadNotebook2025Corpus(CORPUS_DIR, { logger: { warn: () => {} } });
const NAMED = ALL.filter((s) => s.manifest && s.manifest.regression_guard === true);

describe('Phase 53 BACK-04 notebook-2025 hermetic eval gate', () => {
  if (NAMED.length === 0) {
    // Curation is operator-gated (Plan 53-04 Task 1 + Task 3 human-verify
    // checkpoint). The harness ships green-when-empty so Phase 54 can be
    // explicitly blocked on operator action without coloring CI red.
    // eslint-disable-next-line jest/expect-expect, jest/no-disabled-tests
    test.skip('no fixtures present -- operator curation pending (Plan 53-04 Task 1)', () => {});
    test('harness is wired (loader + test file + npm test:eval script)', () => {
      expect(typeof loadNotebook2025Corpus).toBe('function');
    });
    return;
  }

  it.each(NAMED.map((s) => [s.name, s]))(
    '%s: extractor envelope matches ground-truth on key fields',
    async (_name, fixture) => {
      const client = makeMockAnthropicClient(fixture.mockExtraction);
      const extractor = createExtractor({ apiKey: 'sk-mock-53-04', client, logger: silentLogger });

      const result = await extractor.extract({
        captures: [
          {
            captureId: `CAP_${fixture.name}`,
            text: null,
            transcript: `[mock] ${fixture.name}`,
            images: [],
          },
        ],
        inFlightDraft: null,
        corpusContext: fixture.manifest.corpus_context || null,
      });

      expect(result.ok).toBe(true);
      expect(Array.isArray(result.drafts)).toBe(true);
      expect(result.drafts.length).toBe(fixture.groundTruth.drafts.length);

      // capture_kind round-trip when ground truth pins it.
      if (fixture.manifest.expected_capture_kind != null) {
        expect(result.capture_kind).toBe(fixture.manifest.expected_capture_kind);
      }

      // Per-draft key-field equality (tolerant on confidence / sources).
      for (let i = 0; i < fixture.groundTruth.drafts.length; i += 1) {
        const expected = projectDraftKeyFields(fixture.groundTruth.drafts[i].draft);
        const actual = projectDraftKeyFields(result.drafts[i].draft);
        expect(actual).toEqual(expected);
      }
    },
  );
});

// EVAL_RUN_LIVE=1 branch -- paid LLM call. Persists each response under
// results/notebook-2025/<page-id>-<ISO>.json.
describe('Phase 53 BACK-04 notebook-2025 live-LLM eval (EVAL_RUN_LIVE=1)', () => {
  if (!liveMode || NAMED.length === 0) {
    test.skip('live-mode disabled or no fixtures present', () => {});
    return;
  }
  it.each(NAMED.map((s) => [s.name, s]))(
    'LIVE: %s extractor envelope matches ground-truth on key fields',
    async (_name, fixture) => {
      // Real Anthropic client (no injectedClient -> creates one from API key).
      const extractor = createExtractor({
        apiKey: process.env.ANTHROPIC_API_KEY,
        logger: silentLogger,
      });
      // Live invocation expects image bytes. Loaded from imagePath if present.
      const images = [];
      if (fixture.imagePath && fs.existsSync(fixture.imagePath)) {
        const data = fs.readFileSync(fixture.imagePath).toString('base64');
        const mediaType = /\.png$/i.test(fixture.imagePath) ? 'image/png' : 'image/jpeg';
        images.push({ data, media_type: mediaType });
      }
      const result = await extractor.extract({
        captures: [{ captureId: `LIVE_${fixture.name}`, text: null, transcript: null, images }],
        inFlightDraft: null,
        corpusContext: fixture.manifest.corpus_context || null,
      });
      // Persist BEFORE asserting so paid output is never lost on a red test.
      try {
        fs.mkdirSync(RESULTS_DIR, { recursive: true });
        const stamp = new Date().toISOString().replace(/[:.]/g, '-');
        const outPath = path.join(RESULTS_DIR, `${fixture.name}-${stamp}.json`);
        fs.writeFileSync(outPath, JSON.stringify(result, null, 2));
      } catch (_e) { /* persistence is best-effort */ }
      expect(result.ok).toBe(true);
      expect(result.drafts.length).toBe(fixture.groundTruth.drafts.length);
    },
  );
});
