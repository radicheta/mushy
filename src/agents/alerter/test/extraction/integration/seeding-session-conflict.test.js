'use strict';

// Phase 47 Plan 05: INOC-03 conflict-logging ship-gate test.
//
// Synthetic fixture: audio says parent '118-23', photo shows '118-25'. Per
// CONTEXT.md Gray Area 4 lock, the extractor MUST silently pick the photo's
// value and push a ConflictEntry into draft.conflicts[]; the farmer-facing
// preview MUST mention neither candidate nor the word 'conflict'.
//
// Hermetic only -- live-fire path is exercised by the may22 file. This file
// guards the conflict-logging branch shape against regressions.
//
// Live-fire cost (if you were to run this branch live, which we don't):
// ~$0.05 per run -- there is no actual photo, just synthesized text. Not
// worth a live run; the may22 fixture already proves end-to-end model
// behavior.

const path = require('path');

const { createExtractionPipeline } = require('../../../src/extraction/pipeline');
const { createExtractor } = require('../../../src/extraction/extractor');
const extractionDb = require('../../../src/extraction/extraction-db');
const stateMachine = require('../../../src/extraction/state-machine');
const previewBuilder = require('../../../src/extraction/preview-builder');

const silentLogger = { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} };

const AUDIO_CANDIDATE = '260118_SHI_23';
const PHOTO_CANDIDATE = '260118_SHI_25';

function makePool() {
  return {
    query: jest.fn(async (sql) => {
      if (/FROM signal_draft\s+WHERE sender_e164/i.test(sql)) return { rows: [], rowCount: 0 };
      if (/FROM signal_draft\s+WHERE status IN/i.test(sql)) return { rows: [], rowCount: 0 };
      return { rows: [], rowCount: 1 };
    }),
  };
}

// Draft with photo-wins resolution: groups[1].parent.value === photo's value,
// sources lists both; conflicts[0] captures both candidates.
function makeConflictDraft() {
  return {
    type: 'seeding_session',
    event_date: '2026-05-22',
    groups: [
      {
        parent: { value: '260304_SHI_5', confidence: 0.95, sources: ['audio', 'paper_log_photo'] },
        species: { value: 'SHI', confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
        qty: { value: 1, confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
        child_block_names: {
          value: ['260522_SHI_1'],
          confidence: 0.95,
          sources: ['paper_log_photo'],
        },
      },
      {
        // CONFLICT GROUP: audio said '118-23', photo showed '118-25'. Photo wins.
        parent: {
          value: PHOTO_CANDIDATE,
          confidence: 0.95,
          sources: ['audio', 'paper_log_photo'],
        },
        species: { value: 'SHI', confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
        qty: { value: 1, confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
        child_block_names: {
          value: ['260522_SHI_2'],
          confidence: 0.95,
          sources: ['paper_log_photo'],
        },
      },
    ],
    conflicts: [
      {
        path: 'groups[1].parent.value',
        candidates: [
          { value: AUDIO_CANDIDATE, source: 'audio', confidence: 0.7 },
          { value: PHOTO_CANDIDATE, source: 'paper_log_photo', confidence: 0.95 },
        ],
        resolution: 'photo_wins_implicit',
      },
    ],
  };
}

function makeMockAnthropicClient(draftToReturn) {
  return {
    messages: {
      create: jest.fn(async () => ({
        content: [
          {
            type: 'tool_use',
            id: 'toolu_mock_conflict',
            name: 'submit_extraction',
            input: {
              drafts: [{ draft: draftToReturn, per_field_confidence: { event_date: 0.99 } }],
              continuity: 'start_new',
              continuity_reason: 'no in-flight',
            },
          },
        ],
        usage: { input_tokens: 0, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 },
        stop_reason: 'tool_use',
      })),
    },
  };
}

function captureCtx() {
  return {
    captureId: 'CAP_CONFLICT_SYNTHETIC',
    sender: '+59891840201',
    senderName: 'Santi',
    farmosPerson: 'f1',
    text: 'May 22 inoc (synthetic conflict fixture)',
    transcripts: ['audio says 118-23'],
    attachmentPaths: [],
    replyTargetKind: 'dm',
    groupId: null,
  };
}

describe('INOC-03: synthetic conflict fixture (audio vs photo, photo wins silently)', () => {
  test('photo value wins on groups[1].parent; conflicts[] captures both candidates; preview leaks neither', async () => {
    const pool = makePool();
    const draft = makeConflictDraft();
    const client = makeMockAnthropicClient(draft);
    const extractor = createExtractor({ apiKey: 'sk-mock', client, logger: silentLogger });

    const dispatched = [];
    const outboundDispatcher = {
      dispatch: jest.fn((effect, row) => { dispatched.push({ effect, row }); }),
    };

    const pipeline = createExtractionPipeline({
      pool, extractor, extractionDb, stateMachine, previewBuilder,
      config: { extractionConfidenceThreshold: 0.7, draftIdleGapMin: 30, maxAskbackTurns: 3 },
      logger: silentLogger,
      clock: { now: () => Date.parse('2026-05-22T22:46:00Z') },
      outboundDispatcher,
    });

    const res = await pipeline.enqueue(captureCtx());
    expect(res.ok).toBe(true);

    // Draft persisted with photo's value, NOT audio's value.
    const insertCall = pool.query.mock.calls.find((c) => /INSERT INTO signal_draft/i.test(c[0]));
    expect(insertCall).toBeTruthy();
    const paramsJoined = JSON.stringify(insertCall[1] || []);
    expect(paramsJoined).toContain(PHOTO_CANDIDATE);
    expect(paramsJoined).toContain(AUDIO_CANDIDATE); // candidate logged in conflicts[]

    // Validate against schema; conflicts[0] structure intact.
    const { SeedingSession } = require('../../../src/extraction/schemas');
    const parsed = SeedingSession.safeParse(draft);
    expect(parsed.success).toBe(true);
    expect(parsed.data.groups[1].parent.value).toBe(PHOTO_CANDIDATE);
    expect(parsed.data.conflicts).toHaveLength(1);
    expect(parsed.data.conflicts[0].resolution).toBe('photo_wins_implicit');
    const candidateValues = parsed.data.conflicts[0].candidates.map((c) => c.value);
    expect(candidateValues).toEqual(expect.arrayContaining([AUDIO_CANDIDATE, PHOTO_CANDIDATE]));

    // Farmer-facing preview MUST NOT mention either candidate substring nor 'conflict'.
    const preview = previewBuilder.buildPreview({
      draft,
      perFieldConfidence: { event_date: 0.99 },
      threshold: 0.7,
      requiredFields: ['event_date', 'groups'],
    });
    // Use indexOf assertions per CONTEXT.md Gray Area 4 negative-assertion contract.
    expect(preview.indexOf('118-23')).toBe(-1);
    expect(preview.indexOf('118-25')).toBe(-1);
    expect(preview.toLowerCase().indexOf('conflict')).toBe(-1);
    // Also: the full prod-shape canonical values (audio/photo strings) shouldn't leak as-is.
    expect(preview.indexOf(AUDIO_CANDIDATE)).toBe(-1);
    // Note: parent.value (PHOTO_CANDIDATE) does appear in the per-group preview line --
    // that's the WINNER; only the loser candidate (AUDIO_CANDIDATE) and the conflict marker
    // are forbidden. The shorthand '118-25' substring is forbidden as a defense-in-depth
    // check against farmer-readable conflict leakage.
    expect(preview).not.toMatch(/—/);
  });
});
