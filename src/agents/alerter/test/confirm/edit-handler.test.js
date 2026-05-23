'use strict';

const { createEditHandler } = require('../../src/confirm/edit-handler');
const confirmDb = require('../../src/confirm/confirm-db');
const previewBuilderConfirm = require('../../src/confirm/preview');
const previewBuilderExtraction = require('../../src/extraction/preview-builder');
const stateMachineExtraction = require('../../src/extraction/state-machine');
const { makeFakePool } = require('./fake-pool');

function makeConfig() {
  return {
    maxEditTurns: 3,
    extractionConfidenceThreshold: 0.7,
  };
}

function happyDraft() {
  return {
    type: 'seeding',
    species: 'SHI',
    block_name: '260513_SHI_1',
    qty: 12,
    event_timestamp: '2026-05-13T12:00:00Z',
  };
}

function mockOkExtractor() {
  return {
    extract: jest.fn().mockResolvedValue({
      ok: true,
      drafts: [{ draft: happyDraft(), per_field_confidence: { species: 0.95 } }],
      draft: happyDraft(),
      per_field_confidence: { species: 0.95 },
      continuity_decision: 'continue',
      continuity_reason: 'edit',
    }),
  };
}

function setup({ extractor }) {
  const pool = makeFakePool();
  const draftRow = pool.seedDraft({ id: 'd-1', edit_turn_count: 0, draft_json: { type: 'seeding' } });
  const logger = { info: jest.fn(), warn: jest.fn(), debug: jest.fn() };
  const handler = createEditHandler({
    pool,
    extractor,
    confirmDb,
    previewBuilderConfirm,
    previewBuilderExtraction,
    stateMachineExtraction,
    config: makeConfig(),
    logger,
  });
  return { pool, draftRow, handler, logger };
}

describe('edit-handler (Phase 39 D-03)', () => {
  it('EDIT under cap -> re-extract -> updateDraftAfterEdit + appendEvent(ok:true)', async () => {
    const extractor = mockOkExtractor();
    const { pool, draftRow, handler } = setup({ extractor });
    const r = await handler.handleEdit(draftRow, 'qty was 12 not 7');
    expect(r.ok).toBe(true);
    expect(r.sideEffect).toBe('send_preview_resend');
    expect(typeof r.newPreview).toBe('string');
    expect(r.newPreview.length).toBeGreaterThan(0);
    expect(pool.getDraft('d-1').edit_turn_count).toBe(1);
    expect(pool.getDraft('d-1').draft_json.qty).toBe(12);
    const events = pool.getEvents('d-1').filter((e) => e.event === 'edit');
    expect(events).toHaveLength(1);
    expect(events[0].payload.ok).toBe(true);
  });

  it('EDIT at cap -> short-circuit, no extractor call, sideEffect=send_edit_cap_msg', async () => {
    const extractor = mockOkExtractor();
    const { pool, handler } = setup({ extractor });
    pool.getDraft('d-1').edit_turn_count = 3;
    const draftAtCap = pool.getDraft('d-1');
    const r = await handler.handleEdit(draftAtCap, 'something');
    expect(r.ok).toBe(true);
    expect(r.sideEffect).toBe('send_edit_cap_msg');
    expect(extractor.extract).not.toHaveBeenCalled();
  });

  it('extractor returns ok:false reason=schema_invalid -> draft stays awaiting_farmer; event payload.ok=false', async () => {
    const extractor = { extract: jest.fn().mockResolvedValue({ ok: false, reason: 'schema_invalid' }) };
    const { pool, draftRow, handler } = setup({ extractor });
    const r = await handler.handleEdit(draftRow, 'try again');
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('schema_invalid');
    expect(pool.getDraft('d-1').status).toBe('awaiting_farmer');
    const editEvents = pool.getEvents('d-1').filter((e) => e.event === 'edit');
    expect(editEvents).toHaveLength(1);
    expect(editEvents[0].payload.ok).toBe(false);
  });

  it('extractor throws -> handler returns {ok:false}, no throw bubbles', async () => {
    const extractor = { extract: jest.fn().mockImplementation(() => { throw new Error('network'); }) };
    const { draftRow, handler } = setup({ extractor });
    const r = await handler.handleEdit(draftRow, 'try again');
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('network');
  });

  it('updateDraftAfterEdit returns rowCount=0 (concurrent confirm) -> sideEffect=noop draft_no_longer_active', async () => {
    const extractor = mockOkExtractor();
    const { pool, draftRow, handler } = setup({ extractor });
    // Make the extractor mutate status to 'confirmed' before updateDraftAfterEdit lands.
    extractor.extract = jest.fn().mockImplementation(async () => {
      pool.getDraft('d-1').status = 'confirmed';
      return {
        ok: true,
        drafts: [{ draft: happyDraft(), per_field_confidence: {} }],
        draft: happyDraft(),
        per_field_confidence: {},
      };
    });
    const r = await handler.handleEdit(draftRow, 'race');
    expect(r.ok).toBe(true);
    expect(r.sideEffect).toBe('noop');
    expect(r.reason).toBe('draft_no_longer_active');
  });

  it('editText is truncated to 200 chars in event payload', async () => {
    const extractor = mockOkExtractor();
    const { pool, draftRow, handler } = setup({ extractor });
    const longText = 'x'.repeat(500);
    await handler.handleEdit(draftRow, longText);
    const editEvents = pool.getEvents('d-1').filter((e) => e.event === 'edit');
    expect(editEvents[0].payload.editText.length).toBe(200);
  });

  it('null draftRow -> {ok:false}, no throw', async () => {
    const extractor = mockOkExtractor();
    const { handler } = setup({ extractor });
    const r = await handler.handleEdit(null, 'foo');
    expect(r.ok).toBe(false);
  });

  // Plan 45-03 Option X: commit_failed -> EDIT -> awaiting_farmer.
  it('EDIT on commit_failed draft -> transition to awaiting_farmer, re-extract, send_preview_resend', async () => {
    const extractor = mockOkExtractor();
    const { pool, handler } = setup({ extractor });
    // Re-seed d-1 as commit_failed (overwrites the default awaiting_farmer seed).
    pool.seedDraft({
      id: 'd-1',
      status: 'commit_failed',
      terminal_reason: 'observation_requires_target',
      edit_turn_count: 0,
      draft_json: { type: 'seeding' },
    });
    const draftRow = pool.getDraft('d-1');
    const r = await handler.handleEdit(draftRow, 'target is shelf B5');
    expect(r.ok).toBe(true);
    expect(r.sideEffect).toBe('send_preview_resend');
    expect(extractor.extract).toHaveBeenCalledTimes(1);
    expect(extractor.extract.mock.calls[0][0].farmerCorrection).toBe('target is shelf B5');
    expect(pool.getDraft('d-1').status).toBe('awaiting_farmer');
    expect(pool.getDraft('d-1').edit_turn_count).toBe(1);
  });

  it('EDIT on draft in confirmed/committed/discarded -> rejected, no transition', async () => {
    for (const startState of ['confirmed', 'committed', 'discarded']) {
      const extractor = mockOkExtractor();
      const { pool, handler } = setup({ extractor });
      pool.seedDraft({
        id: 'd-1',
        status: startState,
        edit_turn_count: 0,
        draft_json: { type: 'seeding' },
      });
      const draftRow = pool.getDraft('d-1');
      const r = await handler.handleEdit(draftRow, 'try to edit');
      expect(r.ok).toBe(false);
      expect(extractor.extract).not.toHaveBeenCalled();
      // Status unchanged.
      expect(pool.getDraft('d-1').status).toBe(startState);
    }
  });
});
