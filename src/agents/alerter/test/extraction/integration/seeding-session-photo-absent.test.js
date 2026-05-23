'use strict';

// Phase 47 Plan 05: INOC-05 photo-absent ask-back ship-gate test.
//
// Synthetic fixture: audio only, no SEQ in audio, no photo attachment. Per
// CONTEXT.md Gray Area 3 lock, the extractor MUST emit
//   draft.needs_input = 'starting_seq'
//   every child_block_names.value entry === 'NEEDS_SEQ'
//
// The pipeline's short-circuit branch (Phase 47-03) renders an ask-back
// matching the locked template. A subsequent farmer reply '4' via
// handleStartingSeqReply must fill child_block_names with valid BLOCK_NAME_RE
// strings starting from 4, clear needs_input, and dispatch the filled-preview
// side-effect for Phase 48.
//
// Hermetic only -- no live-fire (no real fixture; the may22 test covers live).

const { createExtractionPipeline } = require('../../../src/extraction/pipeline');
const { createExtractor } = require('../../../src/extraction/extractor');
const stateMachine = require('../../../src/extraction/state-machine');
const previewBuilder = require('../../../src/extraction/preview-builder');
const { BLOCK_NAME_RE } = require('../../../src/extraction/schemas/seeding-session');

const silentLogger = { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} };

function makePhotoAbsentDraft() {
  return {
    type: 'seeding_session',
    event_date: '2026-05-22',
    needs_input: 'starting_seq',
    groups: [
      {
        parent: { value: '260118_SHI_25', confidence: 0.7, sources: ['audio'] },
        species: { value: 'SHI', confidence: 0.9, sources: ['audio'] },
        qty: { value: 3, confidence: 0.9, sources: ['audio'] },
        child_block_names: {
          value: ['NEEDS_SEQ', 'NEEDS_SEQ', 'NEEDS_SEQ'],
          confidence: 0,
          sources: ['model_inference'],
        },
      },
      {
        parent: { value: '260201_KOY_1', confidence: 0.7, sources: ['audio'] },
        species: { value: 'KOY', confidence: 0.9, sources: ['audio'] },
        qty: { value: 8, confidence: 0.9, sources: ['audio'] },
        child_block_names: {
          value: Array(8).fill('NEEDS_SEQ'),
          confidence: 0,
          sources: ['model_inference'],
        },
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
            id: 'toolu_mock_photo_absent',
            name: 'submit_extraction',
            input: {
              drafts: [{ draft: draftToReturn, per_field_confidence: { event_date: 0.9 } }],
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

// Mini in-memory extractionDb stub that holds the draft row mutations so we
// can simulate a farmer reply round-trip through handleStartingSeqReply.
function makeLiveExtractionDb(initialDraft) {
  const rows = {};
  return {
    rows,
    getInFlightForSender: jest.fn(async () => null),
    insertDraft: jest.fn(async (_pool, row) => {
      rows[row.id] = { ...row, draft_json: row.draft_json };
      return { ok: true };
    }),
    updateDraftStatus: jest.fn(async (_pool, id, status, extras) => {
      if (!rows[id]) rows[id] = { id };
      rows[id].status = status;
      if (extras) {
        if (extras.draft_json) rows[id].draft_json = extras.draft_json;
        if (extras.farmer_facing_preview) rows[id].farmer_facing_preview = extras.farmer_facing_preview;
      }
      return { ok: true };
    }),
    advanceAskbackTurn: jest.fn(async () => ({ ok: true })),
    computeDraftId: jest.fn((ids, idx) => `draft-${(ids || []).join('-')}-${idx || 0}`),
    getDraftById: jest.fn(async (_pool, id) => rows[id] || null),
  };
}

function makePool() {
  return {
    query: jest.fn(async (sql) => {
      if (/FROM signal_draft\s+WHERE sender_e164/i.test(sql)) return { rows: [], rowCount: 0 };
      if (/FROM signal_draft\s+WHERE status IN/i.test(sql)) return { rows: [], rowCount: 0 };
      return { rows: [], rowCount: 1 };
    }),
  };
}

function captureCtx() {
  return {
    captureId: 'CAP_PHOTO_ABSENT_SYNTHETIC',
    sender: '+59891840201',
    senderName: 'Santi',
    farmosPerson: 'f1',
    text: 'inoc today, audio only',
    transcripts: ['eleven bags total, three shiitake and eight king oyster'],
    attachmentPaths: [],
    replyTargetKind: 'dm',
    groupId: null,
  };
}

describe('INOC-05: photo-absent ask-back -> numeric reply fills block_names', () => {
  test('pipeline emits send_starting_seq_askback with the locked template; numeric reply fills child_block_names per BLOCK_NAME_RE', async () => {
    const pool = makePool();
    const draft = makePhotoAbsentDraft();
    const client = makeMockAnthropicClient(draft);
    const extractor = createExtractor({ apiKey: 'sk-mock', client, logger: silentLogger });
    const extractionDb = makeLiveExtractionDb(draft);

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

    // --- Step 1: enqueue the photo-absent capture -> ask-back fires ---------
    const res = await pipeline.enqueue(captureCtx());
    expect(res.ok).toBe(true);
    expect(res.status).toBe('awaiting_farmer');
    expect(res.sideEffects).toEqual(['send_starting_seq_askback']);

    // The dispatched ask-back row carries the locked template text.
    const askback = dispatched.find((d) => d.effect === 'send_starting_seq_askback');
    expect(askback).toBeDefined();
    const preview = askback.row.farmer_facing_preview;
    expect(preview).toMatch(/^Hi Santi,/);
    expect(preview).toMatch(/May 22 inoc, 11 blocks/);
    expect(preview).toMatch(/block number/);
    expect(preview).toMatch(/default is 1/); // no prior session today (pool returns 0 rows)
    expect(preview).toMatch(/Reply with a number or just YES/);
    expect(preview).not.toMatch(/—/);

    // The persisted draft retains the NEEDS_SEQ sentinels until reply fires.
    const persistedRow = extractionDb.rows[res.draftId];
    expect(persistedRow).toBeDefined();
    expect(persistedRow.draft_json.needs_input).toBe('starting_seq');
    for (const g of persistedRow.draft_json.groups) {
      for (const v of g.child_block_names.value) {
        expect(v).toBe('NEEDS_SEQ');
      }
    }

    // --- Step 2: farmer reply '4' -> handleStartingSeqReply fills names ----
    const replyRes = await pipeline.handleStartingSeqReply({
      draftId: res.draftId,
      replyText: '4',
      captureCtx: { senderName: 'Santi' },
    });
    expect(replyRes.ok).toBe(true);
    expect(replyRes.startSeq).toBe(4);
    expect(replyRes.sideEffects).toEqual(['send_seeding_session_filled_preview']);

    const filledDraft = extractionDb.rows[res.draftId].draft_json;
    expect(filledDraft.needs_input).toBeUndefined();

    // All child_block_names match BLOCK_NAME_RE and are session-wide-sequential from 4.
    const flatNames = filledDraft.groups.flatMap((g) => g.child_block_names.value);
    expect(flatNames).toEqual([
      '260522_SHI_4', '260522_SHI_5', '260522_SHI_6',
      '260522_KOY_7', '260522_KOY_8', '260522_KOY_9', '260522_KOY_10',
      '260522_KOY_11', '260522_KOY_12', '260522_KOY_13', '260522_KOY_14',
    ]);
    for (const n of flatNames) {
      expect(n).toMatch(BLOCK_NAME_RE);
      expect(n).not.toBe('NEEDS_SEQ');
    }

    // sources updated to record the SEQ came from farmer reply (model_inference + text).
    for (const g of filledDraft.groups) {
      expect(g.child_block_names.sources).toEqual(['model_inference', 'text']);
    }

    // --- Step 3: downstream preview-builder placeholder fires on filled draft ---
    const filledPreview = previewBuilder.buildPreview({
      draft: filledDraft,
      perFieldConfidence: { event_date: 0.9 },
      threshold: 0.7,
      requiredFields: ['event_date', 'groups'],
    });
    expect(filledPreview).toContain('11 blocks across 2 groups for May 22');
    expect(filledPreview).toContain('Phase 48');
    expect(filledPreview).not.toMatch(/—/);
  });
});
