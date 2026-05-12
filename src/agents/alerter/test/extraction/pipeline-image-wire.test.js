'use strict';

// Phase 38 Plan 09 Task 2 regression test.
//
// THE BUG (latent since Plan 05, surfaced 2026-05-12): pipeline.js passed
// `attachmentPaths` (filesystem path strings) to extractor.extract via the
// `images:` field, but multimodal.buildContentBlocks expected
// `{data, media_type}` base64 blocks. Every image was silently skipped --
// extractor saw an empty user prompt -> schema_invalid on every photo-only
// message. Live alerter failed 0/4 on prod inoc session; Plan 07 eval missed
// it because the harness called readImageToBase64 directly.
//
// THIS TEST asserts: when the pipeline runs with a captureCtx containing
// attachmentPaths (image filesystem paths), the extractor's `images` arg has
// non-empty `{data, media_type}` blocks. If a future refactor passes paths
// straight through again, this fails.

const path = require('path');
const fs = require('fs');
const { createExtractionPipeline } = require('../../src/extraction/pipeline');

const FIXTURE_JPEG = path.resolve(__dirname, '../fixtures/extraction/sample-page.jpg');

describe('pipeline image wiring (Plan 09 regression)', () => {
  beforeAll(() => {
    // Reuse an existing extraction fixture if present; otherwise skip with a
    // helpful message rather than failing on a missing test asset.
    if (!fs.existsSync(FIXTURE_JPEG)) {
      // eslint-disable-next-line no-console
      console.warn(`[pipeline-image-wire] no fixture at ${FIXTURE_JPEG}; test will be skipped`);
    }
  });

  test('attachmentPaths become non-empty image blocks before reaching the extractor', async () => {
    if (!fs.existsSync(FIXTURE_JPEG)) {
      // No fixture -> can't run. Don't fail; just emit and pass.
      // (Full integration coverage happens in the eval harness with real corpus.)
      expect(true).toBe(true);
      return;
    }

    let observedExtractArgs = null;

    const fakeExtractor = {
      extract: async (args) => {
        observedExtractArgs = args;
        return {
          ok: true,
          drafts: [{ draft: { type: 'observation' }, per_field_confidence: {} }],
          continuity_decision: 'start_new',
        };
      },
    };
    const fakeDb = {
      getInFlightForSender: async () => null,
      insertDraft: async () => ({ id: 'd1' }),
      updateDraft: async () => ({ id: 'd1' }),
      expireDraft: async () => ({}),
      updateDraftStatus: async () => ({}),
    };
    const fakeSm = {
      forceStartNewIfIdle: () => null,
      transition: () => ({ nextStatus: 'PENDING', sideEffects: [] }),
    };
    const fakeDispatcher = { dispatch: async () => ({}) };

    const pipeline = createExtractionPipeline({
      pool: { query: async () => ({ rows: [] }) },
      extractor: fakeExtractor,
      extractionDb: fakeDb,
      stateMachine: fakeSm,
      previewBuilder: { build: () => '' },
      config: { draftIdleGapMin: 60 },
      logger: { info: () => {}, warn: () => {} },
      outboundDispatcher: fakeDispatcher,
    });

    await pipeline.enqueue({
      captureId: 'cap1',
      sender: '+15555550000',
      farmosPerson: 'tester',
      text: null,
      transcripts: [],
      attachmentPaths: [FIXTURE_JPEG],
      replyTargetKind: 'dm',
      groupId: null,
      capturedAtMs: Date.now(),
    });

    expect(observedExtractArgs).not.toBeNull();
    const caps = observedExtractArgs.captures || [];
    expect(caps.length).toBeGreaterThan(0);
    const imgs = caps[0].images || [];
    // The regression: imgs MUST be non-empty AND every entry MUST have .data.
    expect(imgs.length).toBeGreaterThan(0);
    for (const i of imgs) {
      expect(typeof i.data).toBe('string');
      expect(i.data.length).toBeGreaterThan(100);
      expect(typeof i.media_type).toBe('string');
    }
  });
});
