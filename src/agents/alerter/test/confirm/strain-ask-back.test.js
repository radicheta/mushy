'use strict';

const { renderStrainAskBack, parseStrainAskBackReply } = require('../../src/confirm/strain-ask-back');
const { createReceiveLoop } = require('../../src/receive-loop');

describe('renderStrainAskBack', () => {
  it('contains the seen code', () => {
    const msg = renderStrainAskBack('XYZ', 'SHI');
    expect(msg).toContain('XYZ');
  });

  it('contains the nearest suggestion when provided', () => {
    const msg = renderStrainAskBack('XYZ', 'SHI');
    expect(msg).toContain('SHI');
  });

  it('has no em-dashes', () => {
    const msg = renderStrainAskBack('XYZ', 'SHI');
    expect(/[–—]/.test(msg)).toBe(false);
  });

  it('has no em-dashes when nearest is null', () => {
    const msg = renderStrainAskBack('XYZ', null);
    expect(/[–—]/.test(msg)).toBe(false);
  });

  it('omits "did you mean" clause when nearest is null', () => {
    const msg = renderStrainAskBack('XYZ', null);
    expect(msg).toContain('XYZ');
    // should not mention a nearest code
    expect(msg).not.toMatch(/did you mean/i);
  });

  it('is a non-empty string', () => {
    expect(typeof renderStrainAskBack('LIM', 'LIMA')).toBe('string');
    expect(renderStrainAskBack('LIM', 'LIMA').length).toBeGreaterThan(0);
  });
});

describe('parseStrainAskBackReply', () => {
  it('"yes" -> confirm_new', () => {
    expect(parseStrainAskBackReply('yes')).toEqual({ kind: 'confirm_new' });
  });

  it('"YES" -> confirm_new (case-insensitive)', () => {
    expect(parseStrainAskBackReply('YES')).toEqual({ kind: 'confirm_new' });
  });

  it('"confirm" -> confirm_new', () => {
    expect(parseStrainAskBackReply('confirm')).toEqual({ kind: 'confirm_new' });
  });

  it('"si" -> confirm_new', () => {
    expect(parseStrainAskBackReply('si')).toEqual({ kind: 'confirm_new' });
  });

  it('"SHI" bare -> correction with uppercased code', () => {
    expect(parseStrainAskBackReply('SHI')).toEqual({ kind: 'correction', code: 'SHI' });
  });

  it('"shi" bare -> correction with uppercased code', () => {
    expect(parseStrainAskBackReply('shi')).toEqual({ kind: 'correction', code: 'SHI' });
  });

  it('"no, SHI" -> correction with code SHI', () => {
    expect(parseStrainAskBackReply('no, SHI')).toEqual({ kind: 'correction', code: 'SHI' });
  });

  it('"no, lima" -> correction with code LIMA', () => {
    expect(parseStrainAskBackReply('no, lima')).toEqual({ kind: 'correction', code: 'LIMA' });
  });

  it('gibberish / unrecognized -> unknown', () => {
    expect(parseStrainAskBackReply('??')).toEqual({ kind: 'unknown' });
  });

  it('empty string -> unknown', () => {
    expect(parseStrainAskBackReply('')).toEqual({ kind: 'unknown' });
  });

  it('non-string -> unknown', () => {
    expect(parseStrainAskBackReply(null)).toEqual({ kind: 'unknown' });
  });

  it('"maybe" (not a confirm/no/code) -> unknown', () => {
    expect(parseStrainAskBackReply('maybe')).toEqual({ kind: 'unknown' });
  });
});

// =====================================================================
// Phase 54.1 Plan 03 Task 3: receive-loop strain-pending YES / correction handling
// Tests prove: YES sets strain_confirm_approved; correction remaps draft_json;
// no-YES leaves draft without approval marker and no mint.
// =====================================================================

const CURATED = ['SHI', 'SH2', 'KOY', 'MAI', 'MALI', 'KOS', 'DT', 'CAS', 'CAZ', 'WIN', 'ALM', 'MOR', 'BP', 'LIMA'];
const BASE_CONFIG = {
  signalSender: '+15550001234',
  signalRecipient: '+15550009999',
  signalAdditionalSenders: [],
  receivePollSec: 30,
  maxEditTurns: 3,
  strains: CURATED,
};

function silentLogger() {
  return { info: jest.fn(), warn: jest.fn() };
}

function makeEnvelope({ source = '+15550001234', text = 'yes' } = {}) {
  return { envelope: { source, dataMessage: { message: text, attachments: [] } } };
}

function makeSignalClient(envelopes) {
  return { receive: jest.fn().mockResolvedValueOnce(envelopes), send: jest.fn().mockResolvedValue({ ok: true }) };
}

function makeStrainWiring({ draftRow, updateResult } = {}) {
  const pool = {};
  const confirmDb = {
    findAwaitingForSender: jest.fn().mockResolvedValue(draftRow || null),
    findActiveDraftsForSender: jest.fn().mockResolvedValue(draftRow ? [draftRow] : []),
    findDraftByQuotedMsgTs: jest.fn().mockResolvedValue(null),
    confirmDraft: jest.fn().mockResolvedValue({ ok: true, rowCount: 1 }),
    discardDraft: jest.fn().mockResolvedValue({ ok: true, rowCount: 1 }),
    expireDraft: jest.fn().mockResolvedValue({ ok: true, rowCount: 1 }),
  };
  const confirmParser = require('../../src/confirm/parser');
  const confirmOutbound = { dispatch: jest.fn().mockResolvedValue({ ok: true }) };
  const editHandler = { handleEdit: jest.fn().mockResolvedValue({ ok: true, sideEffect: 'noop' }) };
  const extractionDb = {
    updateDraftStatus: jest.fn().mockResolvedValue(updateResult || { ok: true, rowCount: 1 }),
  };
  return { pool, confirmDb, confirmParser, confirmOutbound, editHandler, extractionDb };
}

async function runOneTick(loop) {
  loop.start();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  loop.stop();
}

describe('Phase 54.1 Plan 03 Task 3: receive-loop strain-pending routing', () => {
  it('YES on strain-pending draft -> updateDraftStatus with strain_confirm_approved + confirmDraft called', async () => {
    const draftRow = {
      id: 'strain-draft-01',
      sender_e164: '+15550001234',
      needs_review_reason: 'strain_unknown_pending_confirm',
      draft_json: { species_code: 'XYZ', block_name: 'B1' },
    };
    const w = makeStrainWiring({ draftRow });
    const sig = makeSignalClient([makeEnvelope({ text: 'yes' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: BASE_CONFIG, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);

    // updateDraftStatus should have been called with the approval marker
    expect(w.extractionDb.updateDraftStatus).toHaveBeenCalledWith(
      pool_or_any(),
      'strain-draft-01',
      draftRow.status, // undefined when status not set (passes undefined to updateDraftStatus)
      expect.objectContaining({ needs_review_reason: 'strain_confirm_approved' })
    );
    // confirmDraft should proceed after approval
    expect(w.confirmDb.confirmDraft).toHaveBeenCalled();
    // confirm ack dispatched
    expect(w.confirmOutbound.dispatch).toHaveBeenCalledWith('send_confirm_ack', expect.any(Object));
  });

  it('correction with curated code -> draft_json strain rewritten to canonical + confirmDraft called (no approval marker)', async () => {
    const draftRow = {
      id: 'strain-draft-02',
      sender_e164: '+15550001234',
      needs_review_reason: 'strain_unknown_pending_confirm',
      draft_json: { species_code: 'SHIITAKE', block_name: 'B2' },
    };
    const w = makeStrainWiring({ draftRow });
    const sig = makeSignalClient([makeEnvelope({ text: 'SHI' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: BASE_CONFIG, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);

    // updateDraftStatus should rewrite species_code to SHI (NOT set approval marker)
    const updateCalls = w.extractionDb.updateDraftStatus.mock.calls;
    expect(updateCalls.length).toBeGreaterThan(0);
    const approvalCall = updateCalls.find((c) => c[3] && c[3].needs_review_reason === 'strain_confirm_approved');
    expect(approvalCall).toBeUndefined(); // no approval marker on correction

    const jsonCall = updateCalls.find((c) => c[3] && c[3].draft_json);
    expect(jsonCall).toBeDefined();
    expect(jsonCall[3].draft_json.species_code).toBe('SHI');

    // confirmDraft still called (to commit the corrected draft)
    expect(w.confirmDb.confirmDraft).toHaveBeenCalled();
  });

  it('non-curated correction code -> send_strain_ask_back re-dispatched, NO confirmDraft', async () => {
    const draftRow = {
      id: 'strain-draft-03',
      sender_e164: '+15550001234',
      needs_review_reason: 'strain_unknown_pending_confirm',
      draft_json: { species_code: 'XYZ', block_name: 'B3' },
    };
    const w = makeStrainWiring({ draftRow });
    // "POI" is not in the curated set
    const sig = makeSignalClient([makeEnvelope({ text: 'POI' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: BASE_CONFIG, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);

    expect(w.confirmDb.confirmDraft).not.toHaveBeenCalled();
    // re-ask dispatched
    const calls = w.confirmOutbound.dispatch.mock.calls;
    expect(calls.some((c) => c[0] === 'send_strain_ask_back')).toBe(true);
  });

  it('no farmer YES -> no strain_confirm_approved marker on draft, no mint path', async () => {
    // Draft is in strain_unknown_pending_confirm but nothing touches it
    // because the inbound message is a fresh capture (NOOP from parser),
    // not a YES to the strain ask-back.
    const draftRow = {
      id: 'strain-draft-04',
      sender_e164: '+15550001234',
      needs_review_reason: 'strain_unknown_pending_confirm',
      draft_json: { species_code: 'XYZ', block_name: 'B4' },
    };
    const w = makeStrainWiring({ draftRow });
    // send a message that is NOOP (unrecognized text for any parser)
    const sig = makeSignalClient([makeEnvelope({ text: '(silence)' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: BASE_CONFIG, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);

    // No approval marker should be set
    const approvalCall = w.extractionDb.updateDraftStatus.mock.calls.find(
      (c) => c[3] && c[3].needs_review_reason === 'strain_confirm_approved'
    );
    expect(approvalCall).toBeUndefined();
    // No confirmDraft either (still holding)
    expect(w.confirmDb.confirmDraft).not.toHaveBeenCalled();
  });
});

// Helper: accept any value for the pool argument in toHaveBeenCalledWith
function pool_or_any() {
  return expect.anything();
}

// =====================================================================
// Phase 54.2 Plan 02 Task 4: R2 multi-group correction guard
// Proves: a correction reply on a seeding_session draft (or any multi-group
// draft) does NOT silently no-op. It logs strain_correction_multigroup_unsupported
// and re-asks the farmer. The groups[].species.value fields are NOT changed.
// A flat-shape (single-code, no groups[]) correction still works.
// =====================================================================

describe('multigroup correction', () => {
  it('correction on seeding_session draft -> logs strain_correction_multigroup_unsupported, NO confirmDraft, NO species_code rewrite, re-asks farmer', async () => {
    const sessionDraftRow = {
      id: 'strain-session-01',
      sender_e164: '+15550001234',
      needs_review_reason: 'strain_unknown_pending_confirm',
      draft_json: {
        type: 'seeding_session',
        event_date: '2026-05-30',
        groups: [
          { parent: { value: 'P1', confidence: 1, sources: ['audio'] }, species: { value: 'PB2', confidence: 1, sources: ['audio'] }, qty: { value: 2, confidence: 1, sources: ['audio'] }, child_block_names: { value: ['260530_PB2_1', '260530_PB2_2'], confidence: 1, sources: ['paper_log_photo'] } },
        ],
      },
    };
    const w = makeStrainWiring({ draftRow: sessionDraftRow });
    // Farmer sends "SHI" as a correction (SHI is in the curated set).
    const sig = makeSignalClient([makeEnvelope({ text: 'SHI' })]);
    const logger = silentLogger();
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: BASE_CONFIG, logger, ...w,
    });
    await runOneTick(loop);

    // confirmDraft must NOT be called -- draft stays held.
    expect(w.confirmDb.confirmDraft).not.toHaveBeenCalled();
    // No species_code rewrite on draft_json (groups stay unchanged).
    const jsonCall = w.extractionDb.updateDraftStatus.mock.calls.find(
      (c) => c[3] && c[3].draft_json
    );
    expect(jsonCall).toBeUndefined();
    // send_strain_ask_back re-dispatched (re-ask).
    const reask = w.confirmOutbound.dispatch.mock.calls.find((c) => c[0] === 'send_strain_ask_back');
    expect(reask).toBeDefined();
    // The logger must have recorded the limitation.
    const warnCalls = logger.warn.mock.calls;
    expect(warnCalls.some((c) => c[0] && c[0].includes('strain_correction_multigroup_unsupported'))).toBe(true);
  });

  it('correction on flat-shape draft (no groups[]) -> species_code rewritten + confirmDraft called (unchanged path)', async () => {
    const flatDraftRow = {
      id: 'strain-flat-01',
      sender_e164: '+15550001234',
      needs_review_reason: 'strain_unknown_pending_confirm',
      draft_json: { type: 'observation', species_code: 'PB2', asset_ref: 'B1' },
    };
    const w = makeStrainWiring({ draftRow: flatDraftRow });
    // Farmer sends "SHI" as a correction (SHI is in the curated set).
    const sig = makeSignalClient([makeEnvelope({ text: 'SHI' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: BASE_CONFIG, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);

    // The flat-shape correction path: species_code must be rewritten.
    const jsonCall = w.extractionDb.updateDraftStatus.mock.calls.find(
      (c) => c[3] && c[3].draft_json
    );
    expect(jsonCall).toBeDefined();
    expect(jsonCall[3].draft_json.species_code).toBe('SHI');
    // confirmDraft called after correction.
    expect(w.confirmDb.confirmDraft).toHaveBeenCalled();
  });

  it('correction on multi-group draft without seeding_session type (groups[] present) -> same guard fires, NO confirmDraft', async () => {
    // Any draft with groups[] should be protected, not just type=seeding_session.
    const multiGroupDraft = {
      id: 'strain-multigroup-01',
      sender_e164: '+15550001234',
      needs_review_reason: 'strain_unknown_pending_confirm',
      draft_json: {
        type: 'custom_log',
        groups: [{ species: { value: 'PB2' } }],
      },
    };
    const w = makeStrainWiring({ draftRow: multiGroupDraft });
    const sig = makeSignalClient([makeEnvelope({ text: 'SHI' })]);
    const logger = silentLogger();
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: BASE_CONFIG, logger, ...w,
    });
    await runOneTick(loop);

    expect(w.confirmDb.confirmDraft).not.toHaveBeenCalled();
    expect(logger.warn.mock.calls.some((c) => c[0] && c[0].includes('strain_correction_multigroup_unsupported'))).toBe(true);
  });
});
