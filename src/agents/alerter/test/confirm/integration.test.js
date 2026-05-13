'use strict';

// Phase 39 integration test (Plan 07).
//
// Wires real confirm modules (confirm-db, parser, state-machine, preview,
// outbound-confirm, edit-handler, watchdog) against the in-memory fake pool,
// a mocked signalClient, and a mocked extractor. Drives the same code paths
// as the receive-loop for YES/NO/EDIT and the watchdog for nudge/expire.
//
// Scenarios 1-8: synthetic.
// Scenario 9: real-prod fixture (D-09a ship-gate witness).

const confirmDb = require('../../src/confirm/confirm-db');
const previewBuilderConfirm = require('../../src/confirm/preview');
const previewBuilderExtraction = require('../../src/extraction/preview-builder');
const stateMachineExtraction = require('../../src/extraction/state-machine');
const { createConfirmOutbound } = require('../../src/confirm/outbound-confirm');
const { createEditHandler } = require('../../src/confirm/edit-handler');
const { createWatchdog } = require('../../src/confirm/watchdog');
const { parseReply } = require('../../src/confirm/parser');
const { makeFakePool } = require('./fake-pool');

const seedingClean = require('./fixtures/curated/seeding-clean.json');
const prodFixture = require('./fixtures/prod-draft-awaiting.json');

function silentLogger() { return { info: jest.fn(), warn: jest.fn(), debug: jest.fn() }; }

function makeSignalClient() {
  return { send: jest.fn().mockResolvedValue({ ok: true }) };
}

function makeRevisedDraft(over = {}) {
  return Object.assign({
    type: 'seeding',
    species: 'SHI',
    block_name: '260513_SHI_1',
    qty: 12,
    event_timestamp: '2026-05-13T12:00:00Z',
  }, over);
}

function makeOkExtractor(draftFactory = makeRevisedDraft) {
  return {
    extract: jest.fn().mockImplementation(async () => {
      const draft = draftFactory();
      return {
        ok: true,
        drafts: [{ draft, per_field_confidence: { species: 0.95 } }],
        draft,
        per_field_confidence: { species: 0.95 },
      };
    }),
  };
}

const config = {
  maxEditTurns: 3,
  extractionConfidenceThreshold: 0.7,
  draftPendingTimeoutMin: 30,
  draftNudgeFraction: 0.8,
  draftWatchdogIntervalMs: 60000,
};

function buildWiring({ extractor } = {}) {
  const pool = makeFakePool();
  const signalClient = makeSignalClient();
  const confirmOutbound = createConfirmOutbound({
    signalClient, previewBuilderConfirm, operatorRecipient: '+15550009999', logger: silentLogger(),
  });
  const editHandler = createEditHandler({
    pool,
    extractor: extractor || makeOkExtractor(),
    confirmDb,
    previewBuilderConfirm,
    previewBuilderExtraction,
    stateMachineExtraction,
    config,
    logger: silentLogger(),
  });
  const watchdog = createWatchdog({
    pool, confirmDb, outboundConfirm: confirmOutbound, config, logger: silentLogger(),
  });
  return { pool, signalClient, confirmOutbound, editHandler, watchdog };
}

// Drive a single inbound reply through the confirm branch logic.
async function driveReply(wiring, draftRow, replyText) {
  const parsed = parseReply(replyText);
  if (parsed.kind === 'YES') {
    const r = await confirmDb.confirmDraft(wiring.pool, draftRow.id);
    if (r.ok && r.rowCount === 1) {
      await wiring.confirmOutbound.dispatch('send_confirm_ack', draftRow);
    } else if (r.ok && r.rowCount === 0) {
      await wiring.confirmOutbound.dispatch('send_confirm_idempotent_ack', draftRow);
    }
    return;
  }
  if (parsed.kind === 'NO') {
    const r = await confirmDb.discardDraft(wiring.pool, draftRow.id);
    if (r.ok && r.rowCount === 1) {
      await wiring.confirmOutbound.dispatch('send_discard_ack', draftRow);
    }
    return;
  }
  if (parsed.kind === 'EDIT') {
    const eh = await wiring.editHandler.handleEdit(draftRow, parsed.editText || '');
    // Re-read latest draft state from pool so dispatches see fresh farmer_facing_preview.
    const latest = wiring.pool.getDraft(draftRow.id) || draftRow;
    if (eh.ok && eh.sideEffect === 'send_edit_cap_msg') {
      await confirmDb.expireDraft(wiring.pool, draftRow.id, 'edit_cap_exceeded');
      await wiring.confirmOutbound.dispatch('send_edit_cap_msg', latest, { maxEditTurns: config.maxEditTurns });
    } else if (eh.ok && eh.sideEffect === 'send_preview_resend') {
      await wiring.confirmOutbound.dispatch('send_preview_resend', latest, { newPreview: eh.newPreview });
    }
  }
}

describe('Phase 39 integration', () => {
  describe('scenario 1: YES happy path (CONF-01, CONF-02)', () => {
    it('confirms cleanly', async () => {
      const w = buildWiring();
      w.pool.seedDraft(seedingClean);
      const draftRow = w.pool.getDraft(seedingClean.id);
      await driveReply(w, draftRow, 'YES');
      const row = w.pool.getDraft(seedingClean.id);
      expect(row.status).toBe('confirmed');
      expect(row.confirmed_at).not.toBeNull();
      const events = w.pool.getEvents(seedingClean.id);
      expect(events.filter((e) => e.event === 'yes')).toHaveLength(1);
      expect(w.signalClient.send).toHaveBeenCalledTimes(1);
      expect(w.signalClient.send.mock.calls[0][0]).toContain('Locked in');
    });
  });

  describe('scenario 2: NO discard (CONF-03)', () => {
    it('discards cleanly', async () => {
      const w = buildWiring();
      w.pool.seedDraft(seedingClean);
      await driveReply(w, w.pool.getDraft(seedingClean.id), 'NO');
      const row = w.pool.getDraft(seedingClean.id);
      expect(row.status).toBe('discarded');
      expect(w.signalClient.send.mock.calls[0][0]).toContain('Discarded');
    });
  });

  describe('scenario 3: duplicate YES no-op (CONF-02)', () => {
    it('soft re-affirms without inserting a new event', async () => {
      const w = buildWiring();
      const seeded = w.pool.seedDraft(Object.assign({}, seedingClean, { status: 'confirmed', terminal_reason: 'farmer_yes' }));
      await driveReply(w, seeded, 'YES');
      const events = w.pool.getEvents(seedingClean.id);
      expect(events.filter((e) => e.event === 'yes')).toHaveLength(0);
      expect(w.signalClient.send.mock.calls[0][0]).toContain('Already locked in');
    });
  });

  describe('scenario 4: EDIT once -> re-extract -> preview re-render (CONF-04)', () => {
    it('updates draft, increments edit_turn_count, sends new preview', async () => {
      const extractor = makeOkExtractor(() => makeRevisedDraft({ qty: 12 }));
      const w = buildWiring({ extractor });
      w.pool.seedDraft(seedingClean);
      await driveReply(w, w.pool.getDraft(seedingClean.id), 'EDIT change qty to 12');
      const row = w.pool.getDraft(seedingClean.id);
      expect(row.edit_turn_count).toBe(1);
      expect(row.draft_json.qty).toBe(12);
      expect(extractor.extract).toHaveBeenCalledTimes(1);
      const editEvents = w.pool.getEvents(seedingClean.id).filter((e) => e.event === 'edit');
      expect(editEvents).toHaveLength(1);
      expect(editEvents[0].payload.ok).toBe(true);
      expect(w.signalClient.send).toHaveBeenCalledTimes(1);
      expect(w.signalClient.send.mock.calls[0][0]).toMatch(/Reply YES to commit/);
    });
  });

  describe('scenario 5: EDIT 3 times then cap (CONF-04)', () => {
    it('hits cap on the 4th EDIT and transitions to needs_review', async () => {
      const extractor = makeOkExtractor();
      const w = buildWiring({ extractor });
      w.pool.seedDraft(seedingClean);
      const draft = w.pool.getDraft(seedingClean.id);
      await driveReply(w, w.pool.getDraft(draft.id), 'EDIT one');
      await driveReply(w, w.pool.getDraft(draft.id), 'EDIT two');
      await driveReply(w, w.pool.getDraft(draft.id), 'EDIT three');
      // The 4th EDIT triggers the cap.
      await driveReply(w, w.pool.getDraft(draft.id), 'EDIT four');
      const row = w.pool.getDraft(draft.id);
      expect(row.status).toBe('needs_review');
      expect(row.terminal_reason).toBe('edit_cap_exceeded');
      const capEvents = w.pool.getEvents(draft.id).filter((e) => e.event === 'edit_cap_exceeded');
      expect(capEvents).toHaveLength(1);
      // Last outbound message must contain the cap-text with "3 tries".
      const last = w.signalClient.send.mock.calls[w.signalClient.send.mock.calls.length - 1][0];
      expect(last).toMatch(/\b3 tries\b/);
    });
  });

  describe('scenario 6: nudge at 0.8*timeout (CONF-05)', () => {
    it('fires send_nudge with whole-integer minutesRemaining', async () => {
      const w = buildWiring();
      // Seed with updated_at 25 min ago (> 0.8*30 = 24).
      const past = new Date(w.pool._now().getTime() - 25 * 60 * 1000);
      w.pool.seedDraft(Object.assign({}, seedingClean, { updated_at: past }));
      await w.watchdog.tickOnce();
      const row = w.pool.getDraft(seedingClean.id);
      expect(row.nudge_sent_at).not.toBeNull();
      expect(w.signalClient.send).toHaveBeenCalledTimes(1);
      const body = w.signalClient.send.mock.calls[0][0];
      expect(body).toMatch(/\b\d+ min\b/);
      const nudgeEvents = w.pool.getEvents(seedingClean.id).filter((e) => e.event === 'nudge_sent');
      expect(nudgeEvents).toHaveLength(1);
    });
  });

  describe('scenario 7: expire at full timeout (CONF-05)', () => {
    it('transitions to expired with terminal_reason=timeout_expired', async () => {
      const w = buildWiring();
      const past = new Date(w.pool._now().getTime() - 31 * 60 * 1000);
      const nudgedAt = new Date(w.pool._now().getTime() - 10 * 60 * 1000);
      w.pool.seedDraft(Object.assign({}, seedingClean, { updated_at: past, nudge_sent_at: nudgedAt }));
      await w.watchdog.tickOnce();
      const row = w.pool.getDraft(seedingClean.id);
      expect(row.status).toBe('expired');
      expect(row.expired_at).not.toBeNull();
      expect(row.terminal_reason).toBe('timeout_expired');
      const body = w.signalClient.send.mock.calls[0][0];
      expect(body).toContain('Draft expired');
      expect(body).toContain('Nothing was written');
    });
  });

  describe('scenario 8: superseded-by-newer-draft', () => {
    it('expireDraft(superseded_by_newer_draft) closes out the older row silently', async () => {
      const w = buildWiring();
      w.pool.seedDraft({ id: 'old', sender_e164: '+15550001234', status: 'awaiting_farmer' });
      const r = await confirmDb.expireDraft(w.pool, 'old', 'superseded_by_newer_draft');
      expect(r.rowCount).toBe(1);
      const row = w.pool.getDraft('old');
      expect(row.status).toBe('expired');
      expect(row.terminal_reason).toBe('superseded_by_newer_draft');
      const events = w.pool.getEvents('old').filter((e) => e.event === 'superseded');
      expect(events).toHaveLength(1);
    });
  });

  describe('scenario 9: real-prod fixture (D-09a ship-gate)', () => {
    it('9a: YES on prod-draft-awaiting -> confirmed', async () => {
      expect(prodFixture.status).toBe('awaiting_farmer');
      expect(prodFixture._provenance).toBeDefined();
      const w = buildWiring();
      w.pool.seedDraft(prodFixture);
      await driveReply(w, w.pool.getDraft(prodFixture.id), 'YES');
      const row = w.pool.getDraft(prodFixture.id);
      expect(row.status).toBe('confirmed');
      expect(row.confirmed_at).not.toBeNull();
      expect(w.signalClient.send.mock.calls[0][0]).toContain('Locked in');
    });

    it('9b: NO on prod-draft-awaiting -> discarded', async () => {
      const w = buildWiring();
      w.pool.seedDraft(prodFixture);
      await driveReply(w, w.pool.getDraft(prodFixture.id), 'NO');
      const row = w.pool.getDraft(prodFixture.id);
      expect(row.status).toBe('discarded');
      expect(w.signalClient.send.mock.calls[0][0]).toContain('Discarded');
    });

    it('9c: EDIT (mocked re-extract) on prod-draft-awaiting -> preview re-rendered, edit_turn_count=1', async () => {
      const extractor = makeOkExtractor(() => Object.assign({}, prodFixture.draft_json, { qty: 2 }));
      const w = buildWiring({ extractor });
      w.pool.seedDraft(prodFixture);
      await driveReply(w, w.pool.getDraft(prodFixture.id), 'EDIT actually qty was 2');
      const row = w.pool.getDraft(prodFixture.id);
      expect(row.edit_turn_count).toBe(1);
      expect(row.draft_json.qty).toBe(2);
      expect(extractor.extract).toHaveBeenCalledTimes(1);
      expect(w.signalClient.send.mock.calls[0][0]).toMatch(/Reply YES to commit/);
    });
  });
});
