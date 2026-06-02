'use strict';

// Phase 54.2 Plan 02 Task 4: R1 integration test.
// A seeding_session needing BOTH starting_seq (SEQ) AND strain-confirm resolves
// SEQ first. The strain gate must NOT fire on the first pass (while needs_input='starting_seq'),
// and MUST fire on the second pass (after SEQ resolution), holding the draft for strain
// confirmation before any filled-preview dispatch.
//
// This test proves the shared-helper (maybeHoldForStrainConfirm) gate-ordering guarantee:
//   Pass 1 (enqueue, needs_input='starting_seq'): SEQ short-circuit fires first -> returns
//     send_starting_seq_askback. Strain gate is never reached.
//   Pass 2 (handleStartingSeqReply): after child_block_names minted, strain gate fires ->
//     draft held with strain_unknown_pending_confirm. Filled-preview dispatch suppressed.
// A session needing both is never committed missing either resolution.

const { createExtractionPipeline } = require('../../../src/extraction/pipeline');
const { DRAFT_STATUS } = require('../../../src/extraction/state-machine');
const extractionDb = require('../../../src/extraction/extraction-db');
const stateMachine = require('../../../src/extraction/state-machine');
const previewBuilder = require('../../../src/extraction/preview-builder');

const silentLogger = { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} };

// Fake farmosClient: SHI is known (ok:true), POY is unknown (fungi_type_not_found).
// Note: species codes in child_block_names must match /^[0-9]{6}_[A-Z]{2,4}_[0-9]+$/
// (BLOCK_NAME_RE), so the unknown code must be all uppercase letters. POY is used
// as the unknown (3 uppercase chars, not in config.strains=['SHI','KOY','LIMA']).
function makeFakeFarmosClient() {
  return {
    get: jest.fn(async (url) => {
      const m = url.match(/filter\[name\]\[value\]=([^&]+)/);
      const code = m ? decodeURIComponent(m[1]) : null;
      if (code === 'SHI') {
        return { ok: true, body: { data: [{ id: 'uuid-shi' }] } };
      }
      // POY and anything else -> not found.
      return { ok: true, body: { data: [] } };
    }),
  };
}

// Draft: seeding_session with needs_input='starting_seq' AND an unknown strain code (POY).
// POY is used as the unknown: 3 uppercase letters -> valid for BLOCK_NAME_RE minting,
// but not in config.strains=['SHI','KOY','LIMA'] and not in farmOS (fake client returns not-found).
function makeSeqAndStrainDraft() {
  return {
    type: 'seeding_session',
    event_date: '2026-05-30',
    needs_input: 'starting_seq',
    groups: [
      {
        parent: { value: '260118_SHI_01', confidence: 0.95, sources: ['audio'] },
        species: { value: 'SHI', confidence: 0.95, sources: ['audio'] },
        qty: { value: 3, confidence: 0.95, sources: ['paper_log_photo'] },
        child_block_names: { value: ['NEEDS_SEQ', 'NEEDS_SEQ', 'NEEDS_SEQ'], confidence: 0, sources: ['model_inference'] },
      },
      {
        parent: { value: '260118_POY_01', confidence: 0.95, sources: ['audio'] },
        species: { value: 'POY', confidence: 0.95, sources: ['audio'] },
        qty: { value: 2, confidence: 0.95, sources: ['paper_log_photo'] },
        child_block_names: { value: ['NEEDS_SEQ', 'NEEDS_SEQ'], confidence: 0, sources: ['model_inference'] },
      },
    ],
  };
}

function makePool(storedDraft) {
  // Returns the stored seeding_session draft for getDraftById-style queries.
  // Seq-helper SELECT MAX returns null (no prior session).
  return {
    query: jest.fn(async (sql) => {
      if (/FROM signal_draft\s+WHERE status IN/i.test(sql)) {
        return { rows: [], rowCount: 0 };
      }
      if (/FROM signal_draft\s+WHERE id/i.test(sql)) {
        return { rows: storedDraft ? [storedDraft] : [], rowCount: storedDraft ? 1 : 0 };
      }
      if (/SELECT MAX/i.test(sql)) {
        return { rows: [{ max: null }] };
      }
      return { rows: [], rowCount: 1 };
    }),
  };
}

describe('R1: seeding_session needing both starting_seq and strain-confirm -- gate ordering', () => {
  test('Pass 1 (enqueue with needs_input=starting_seq): SEQ gate fires first; strain gate is NOT reached; returns send_starting_seq_askback', async () => {
    // Clear the fungi-type cache so no stale entries from sibling tests.
    require('../../../src/farmos/fungi-type-cache')._clear();

    const draft = makeSeqAndStrainDraft();
    const dispatched = [];
    const updates = [];
    // We use a simple stored state for the draft row (getDraftById in handleStartingSeqReply).
    let storedRow = { id: 'D-SEQ-STRAIN', sender_e164: '+x', draft_json: draft, status: 'awaiting_farmer', source_capture_ids: ['CAP-01'], askback_turns: 0, reply_target_kind: 'dm', group_id: null, farmos_person: 'f1' };
    const pool = makePool(storedRow);

    const extractionDbMock = {
      getInFlightForSender: jest.fn(async () => null),
      insertDraft: jest.fn(async () => ({ ok: true })),
      getDraftById: jest.fn(async () => storedRow),
      updateDraftStatus: jest.fn(async (_p, id, status, extras) => {
        updates.push({ id, status, extras });
        if (extras && extras.draft_json) {
          storedRow = { ...storedRow, draft_json: extras.draft_json, status };
        } else {
          storedRow = { ...storedRow, status };
        }
        return { ok: true };
      }),
      advanceAskbackTurn: jest.fn(async () => ({ ok: true })),
      computeDraftId: jest.fn(() => 'D-SEQ-STRAIN'),
    };

    const outboundDispatcher = { dispatch: jest.fn((e, r) => dispatched.push({ effect: e, row: r })) };

    const pipeline = createExtractionPipeline({
      pool,
      extractor: { extract: jest.fn(async () => ({
        ok: true,
        drafts: [{ draft, per_field_confidence: {} }],
        draft,
        per_field_confidence: {},
        continuity_decision: 'start_new',
        usage: null,
      })) },
      extractionDb: extractionDbMock,
      stateMachine,
      previewBuilder,
      config: {
        extractionConfidenceThreshold: 0.7,
        draftIdleGapMin: 30,
        maxAskbackTurns: 3,
        strains: ['SHI', 'KOY', 'LIMA'],
      },
      logger: silentLogger,
      clock: { now: () => Date.parse('2026-05-30T22:00:00Z') },
      outboundDispatcher,
      farmosClient: makeFakeFarmosClient(),
    });

    const res = await pipeline.enqueue({
      captureId: 'CAP-01',
      sender: '+x',
      senderName: 'Santi',
      farmosPerson: 'f1',
      text: 'inoc PB2',
      transcripts: [],
      attachmentPaths: [],
      replyTargetKind: 'dm',
      groupId: null,
    });

    // SEQ gate must have fired (send_starting_seq_askback in sideEffects).
    expect(res.ok).toBe(true);
    expect(res.sideEffects).toContain('send_starting_seq_askback');
    expect(res.sideEffects).not.toContain('send_strain_ask_back');
    // Strain gate must NOT have fired on Pass 1.
    const strainHold = updates.find((u) => u.extras && u.extras.needs_review_reason === 'strain_unknown_pending_confirm');
    expect(strainHold).toBeUndefined();
    // Only the SEQ ask-back dispatched.
    expect(dispatched.find((d) => d.effect === 'send_starting_seq_askback')).toBeDefined();
    expect(dispatched.find((d) => d.effect === 'send_strain_ask_back')).toBeUndefined();
  });

  test('Pass 2 (handleStartingSeqReply with YES): after SEQ resolved, strain gate fires, draft held with strain_unknown_pending_confirm; filled_preview NOT dispatched', async () => {
    require('../../../src/farmos/fungi-type-cache')._clear();

    // Build a draft that has needs_input='starting_seq' still set (handleStartingSeqReply
    // processes this -- clears needs_input and mints child_block_names, THEN runs strain gate).
    // Species: SHI (known in farmOS), POY (unknown -> triggers strain hold).
    const draftWithSeq = {
      type: 'seeding_session',
      event_date: '2026-05-30',
      needs_input: 'starting_seq', // handleStartingSeqReply will clear this internally
      groups: [
        {
          parent: { value: '260118_SHI_01', confidence: 0.95, sources: ['audio'] },
          species: { value: 'SHI', confidence: 0.95, sources: ['audio'] },
          qty: { value: 3, confidence: 0.95, sources: ['paper_log_photo'] },
          child_block_names: { value: ['NEEDS_SEQ', 'NEEDS_SEQ', 'NEEDS_SEQ'], confidence: 0, sources: ['model_inference'] },
        },
        {
          parent: { value: '260118_POY_01', confidence: 0.95, sources: ['audio'] },
          species: { value: 'POY', confidence: 0.95, sources: ['audio'] },
          qty: { value: 2, confidence: 0.95, sources: ['paper_log_photo'] },
          child_block_names: { value: ['NEEDS_SEQ', 'NEEDS_SEQ'], confidence: 0, sources: ['model_inference'] },
        },
      ],
    };

    const dispatched = [];
    const updates = [];
    let storedRow = {
      id: 'D-SEQ-STRAIN',
      sender_e164: '+x',
      draft_json: draftWithSeq,
      status: 'awaiting_farmer',
      source_capture_ids: ['CAP-01'],
      askback_turns: 0,
      reply_target_kind: 'dm',
      group_id: null,
      farmos_person: 'f1',
    };

    const pool = makePool(storedRow);

    const extractionDbMock = {
      getInFlightForSender: jest.fn(async () => null),
      insertDraft: jest.fn(async () => ({ ok: true })),
      getDraftById: jest.fn(async () => storedRow),
      updateDraftStatus: jest.fn(async (_p, id, status, extras) => {
        updates.push({ id, status, extras });
        if (extras && extras.draft_json) {
          storedRow = { ...storedRow, draft_json: extras.draft_json, status };
        } else {
          storedRow = { ...storedRow, status };
        }
        return { ok: true };
      }),
      advanceAskbackTurn: jest.fn(async () => ({ ok: true })),
      computeDraftId: jest.fn(() => 'D-SEQ-STRAIN'),
    };

    const outboundDispatcher = { dispatch: jest.fn((e, r) => dispatched.push({ effect: e, row: r })) };

    const pipeline = createExtractionPipeline({
      pool,
      extractor: { extract: jest.fn() },
      extractionDb: extractionDbMock,
      stateMachine,
      previewBuilder,
      config: {
        extractionConfidenceThreshold: 0.7,
        draftIdleGapMin: 30,
        maxAskbackTurns: 3,
        strains: ['SHI', 'KOY', 'LIMA'],
      },
      logger: silentLogger,
      clock: { now: () => Date.parse('2026-05-30T22:00:00Z') },
      outboundDispatcher,
      farmosClient: makeFakeFarmosClient(),
    });

    const res = await pipeline.handleStartingSeqReply({
      draftId: 'D-SEQ-STRAIN',
      replyText: '1',
      captureCtx: { senderName: 'Santi' },
    });

    // The strain gate should have fired post-SEQ -> draft held for strain confirm.
    expect(res.ok).toBe(true);
    expect(res.sideEffects).toContain('send_strain_ask_back');
    // The filled_preview dispatch must NOT have happened (strain gate returned early).
    expect(dispatched.find((d) => d.effect === 'send_seeding_session_filled_preview')).toBeUndefined();
    // Draft must be held with the correct reason.
    const strainHold = updates.find((u) => u.extras && u.extras.needs_review_reason === 'strain_unknown_pending_confirm');
    expect(strainHold).toBeDefined();
    // The unknown code POY must appear in the preview.
    expect(strainHold.extras.farmer_facing_preview).toContain('POY');
    // The known code SHI must NOT trigger a hold entry.
    expect(strainHold.extras.farmer_facing_preview).not.toContain('SHI -- not in the active list');
    // strain_confirm_approved must NOT be set (no auto-confirm).
    const autoApprove = updates.find((u) => u.extras && u.extras.needs_review_reason === 'strain_confirm_approved');
    expect(autoApprove).toBeUndefined();
  });
});
