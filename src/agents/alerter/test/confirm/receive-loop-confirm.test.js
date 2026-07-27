'use strict';

const { createReceiveLoop } = require('../../src/receive-loop');

function silentLogger() {
  return { info: jest.fn(), warn: jest.fn(), debug: jest.fn() };
}

function makeEnvelope({ source = '+15550001234', text = 'YES', quote = null } = {}) {
  const dataMessage = { message: text, attachments: [] };
  if (quote) dataMessage.quote = quote;
  return {
    envelope: {
      source,
      dataMessage,
    },
  };
}

function makeSignalClient(envelopes) {
  return {
    receive: jest.fn().mockResolvedValueOnce(envelopes),
    send: jest.fn().mockResolvedValue({ ok: true }),
  };
}

const baseConfig = {
  signalSender: '+15550001234',
  signalRecipient: '+15550009999',
  signalAdditionalSenders: [],
  receivePollSec: 30,
  maxEditTurns: 3,
};

function makeWiring({
  findResult = null,
  confirmResult = { ok: true, rowCount: 1 },
  discardResult = { ok: true, rowCount: 1 },
  editHandlerResult = { ok: true, sideEffect: 'send_preview_resend', newPreview: 'NEW' },
  parserOverride = null,
  // Phase 50 Plan-04: list-shape sibling + quote resolver. Default to the
  // single-row findResult shape (returned as a 1-element array) so existing
  // tests work unchanged. Tests can override to inject multiple drafts or a
  // quote-resolved draft.
  activeDrafts = undefined,
  quoteResolveResult = null,
} = {}) {
  const pool = {};
  const list = activeDrafts !== undefined ? activeDrafts : (findResult ? [findResult] : []);
  const confirmDb = {
    findAwaitingForSender: jest.fn().mockResolvedValue(findResult),
    findActiveDraftsForSender: jest.fn().mockResolvedValue(list),
    findDraftByQuotedMsgTs: jest.fn().mockResolvedValue(quoteResolveResult),
    confirmDraft: jest.fn().mockResolvedValue(confirmResult),
    discardDraft: jest.fn().mockResolvedValue(discardResult),
    expireDraft: jest.fn().mockResolvedValue({ ok: true, rowCount: 1 }),
  };
  const confirmParser = parserOverride || require('../../src/confirm/parser');
  const confirmOutbound = { dispatch: jest.fn().mockResolvedValue({ ok: true }) };
  const editHandler = { handleEdit: jest.fn().mockResolvedValue(editHandlerResult) };
  return { pool, confirmDb, confirmParser, confirmOutbound, editHandler };
}

async function runOneTick(loop) {
  // The loop's tick is internal; we trigger it via start() which calls tick() immediately,
  // then immediately stop() so the setInterval doesn't keep running.
  loop.start();
  // Allow the queued microtasks to finish.
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  loop.stop();
}

describe('receive-loop confirm branch (Phase 39 D-01)', () => {
  it('YES on awaiting_farmer draft -> confirmDraft + send_confirm_ack; capture NOT called', async () => {
    const w = makeWiring({ findResult: { id: 'd1', sender_e164: '+15550001234' } });
    const capture = { handle: jest.fn().mockResolvedValue(null) };
    const sig = makeSignalClient([makeEnvelope({ text: 'YES' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);
    expect(w.confirmDb.confirmDraft).toHaveBeenCalledWith({}, 'd1');
    expect(w.confirmOutbound.dispatch).toHaveBeenCalledWith('send_confirm_ack', expect.any(Object));
    expect(capture.handle).not.toHaveBeenCalled();
  });

  it('Duplicate YES (rowCount=0) -> send_confirm_idempotent_ack', async () => {
    const w = makeWiring({ findResult: { id: 'd1', sender_e164: '+15550001234' }, confirmResult: { ok: true, rowCount: 0 } });
    const capture = { handle: jest.fn() };
    const sig = makeSignalClient([makeEnvelope({ text: 'YES' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);
    expect(w.confirmOutbound.dispatch).toHaveBeenCalledWith('send_confirm_idempotent_ack', expect.any(Object));
    expect(capture.handle).not.toHaveBeenCalled();
  });

  it('NO -> discardDraft + send_discard_ack; capture NOT called', async () => {
    const w = makeWiring({ findResult: { id: 'd1', sender_e164: '+15550001234' } });
    const capture = { handle: jest.fn() };
    const sig = makeSignalClient([makeEnvelope({ text: 'NO' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);
    expect(w.confirmDb.discardDraft).toHaveBeenCalledWith({}, 'd1');
    expect(w.confirmOutbound.dispatch).toHaveBeenCalledWith('send_discard_ack', expect.any(Object));
    expect(capture.handle).not.toHaveBeenCalled();
  });

  it('EDIT under cap -> editHandler called -> send_preview_resend', async () => {
    const w = makeWiring({ findResult: { id: 'd1', sender_e164: '+15550001234' } });
    const capture = { handle: jest.fn() };
    const sig = makeSignalClient([makeEnvelope({ text: 'EDIT qty was 12' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);
    expect(w.editHandler.handleEdit).toHaveBeenCalledTimes(1);
    expect(w.confirmOutbound.dispatch).toHaveBeenCalledWith('send_preview_resend', expect.any(Object), expect.objectContaining({ newPreview: 'NEW' }));
    expect(capture.handle).not.toHaveBeenCalled();
  });

  it('EDIT at cap -> expireDraft(edit_cap_exceeded) + send_edit_cap_msg', async () => {
    const w = makeWiring({
      findResult: { id: 'd1', sender_e164: '+15550001234' },
      editHandlerResult: { ok: true, sideEffect: 'send_edit_cap_msg', reason: 'edit_cap_exceeded' },
    });
    const capture = { handle: jest.fn() };
    const sig = makeSignalClient([makeEnvelope({ text: 'EDIT one more time' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);
    expect(w.confirmDb.expireDraft).toHaveBeenCalledWith({}, 'd1', 'edit_cap_exceeded');
    expect(w.confirmOutbound.dispatch).toHaveBeenCalledWith('send_edit_cap_msg', expect.any(Object), expect.objectContaining({ maxEditTurns: 3 }));
  });

  it('Pure-emoji reply -> NOOP from parser -> falls through to capture pipeline', async () => {
    const w = makeWiring({ findResult: { id: 'd1', sender_e164: '+15550001234' } });
    const capture = { handle: jest.fn().mockResolvedValue(null) };
    const sig = makeSignalClient([makeEnvelope({ text: '👍' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);
    expect(w.confirmDb.confirmDraft).not.toHaveBeenCalled();
    expect(capture.handle).toHaveBeenCalledTimes(1);
  });

  it('No awaiting_farmer draft -> confirm branch short-circuits, capture called', async () => {
    const w = makeWiring({ findResult: null });
    const capture = { handle: jest.fn().mockResolvedValue(null) };
    const sig = makeSignalClient([makeEnvelope({ text: 'fresh message' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);
    expect(w.confirmDb.confirmDraft).not.toHaveBeenCalled();
    expect(w.editHandler.handleEdit).not.toHaveBeenCalled();
    expect(capture.handle).toHaveBeenCalledTimes(1);
  });

  it('findAwaitingForSender throws -> caught + falls through to capture', async () => {
    const w = makeWiring({ findResult: null });
    w.confirmDb.findAwaitingForSender = jest.fn().mockRejectedValue(new Error('db down'));
    const capture = { handle: jest.fn().mockResolvedValue(null) };
    const sig = makeSignalClient([makeEnvelope({ text: 'hi' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);
    expect(capture.handle).toHaveBeenCalledTimes(1);
  });

  it('null pool/confirmDb/editHandler -> confirm branch entirely skipped (back-compat)', async () => {
    const capture = { handle: jest.fn().mockResolvedValue(null) };
    const sig = makeSignalClient([makeEnvelope({ text: 'YES' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(),
      // no confirm wiring
    });
    await runOneTick(loop);
    expect(capture.handle).toHaveBeenCalledTimes(1);
  });

  it("snooze 'mute' wins over confirm branch: confirmDb.findAwaitingForSender NOT called", async () => {
    const w = makeWiring({ findResult: { id: 'd1', sender_e164: '+15550001234' } });
    const capture = { handle: jest.fn() };
    const sig = makeSignalClient([makeEnvelope({ text: 'mute' })]);
    const loop = createReceiveLoop({
      signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
    });
    await runOneTick(loop);
    expect(w.confirmDb.findAwaitingForSender).not.toHaveBeenCalled();
  });

  // ============================================================
  // Phase 50 Plan-04 — quote-first routing + numbered ask-back
  // QUOT-06 four-case matrix + terminal-draft polite ack + orphan quote.
  // ============================================================

  describe('Phase 50 Plan-04: quote-first routing + numbered ask-back', () => {
    const SENDER = '+15550001234';
    const SENDER_OTHER = '+15559999999';
    const BOT = '+15550009999';

    function quoteShape(targetTs) {
      return { id: targetTs, author: BOT, authorNumber: BOT, text: 'previous bot ack' };
    }

    // Case (1-active, no quote): route to that single draft (existing behavior).
    it('(QUOT-06 case 1) 1 active draft + no quote -> route to that draft (unchanged behavior)', async () => {
      const d1 = { id: 'd1', sender_e164: SENDER, status: 'awaiting_farmer' };
      const w = makeWiring({ findResult: d1, activeDrafts: [d1] });
      const capture = { handle: jest.fn() };
      const sig = makeSignalClient([makeEnvelope({ source: SENDER, text: 'YES' })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      expect(w.confirmDb.findDraftByQuotedMsgTs).not.toHaveBeenCalled();
      expect(w.confirmDb.confirmDraft).toHaveBeenCalledWith({}, 'd1');
      expect(w.confirmOutbound.dispatch).toHaveBeenCalledWith('send_confirm_ack', expect.any(Object));
    });

    // Case (1-active + quote resolves): quote-resolved draft wins.
    it('(QUOT-06 case 2) 1 active draft + quote resolves to actionable -> route to QUOTED draft', async () => {
      const dOther = { id: 'd-mostrecent', sender_e164: SENDER, status: 'awaiting_farmer' };
      const dQuoted = { id: 'd-quoted', sender_e164: SENDER, status: 'awaiting_farmer' };
      const w = makeWiring({
        findResult: dOther,
        activeDrafts: [dOther],
        quoteResolveResult: dQuoted,
      });
      const capture = { handle: jest.fn() };
      const sig = makeSignalClient([makeEnvelope({
        source: SENDER, text: 'YES', quote: quoteShape(1779562666675),
      })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      expect(w.confirmDb.findDraftByQuotedMsgTs).toHaveBeenCalledWith({}, 1779562666675);
      expect(w.confirmDb.confirmDraft).toHaveBeenCalledWith({}, 'd-quoted');
      // findActiveDraftsForSender should NOT be needed when quote resolves.
      expect(w.confirmDb.findActiveDraftsForSender).not.toHaveBeenCalled();
    });

    // Case (>1 active + quote): quote wins; no ask-back; route to quoted.
    it('(QUOT-06 case 3) >1 active + quote resolves -> route to QUOTED draft; NO ask-back', async () => {
      const dA = { id: 'd-A', sender_e164: SENDER, status: 'awaiting_farmer' };
      const dB = { id: 'd-B', sender_e164: SENDER, status: 'awaiting_farmer' };
      const dQuoted = { id: 'd-B', sender_e164: SENDER, status: 'awaiting_farmer' };
      const w = makeWiring({
        findResult: dA,
        activeDrafts: [dA, dB],
        quoteResolveResult: dQuoted,
      });
      const capture = { handle: jest.fn() };
      const sig = makeSignalClient([makeEnvelope({
        source: SENDER, text: 'EDIT shelf B5', quote: quoteShape(1779562666675),
      })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      expect(w.editHandler.handleEdit).toHaveBeenCalledWith(dQuoted, 'shelf B5');
      const askBack = w.confirmOutbound.dispatch.mock.calls.find((c) => c[0] === 'send_ask_back');
      expect(askBack).toBeUndefined();
    });

    // Case (>1 active + no quote): emit numbered ask-back; no draft mutation.
    it('(QUOT-06 case 4) >1 active + no quote -> emit send_ask_back; NO confirm/discard/edit', async () => {
      const dA = { id: 'd-A', sender_e164: SENDER, status: 'awaiting_farmer', log_type: 'observation', draft_json: { event_timestamp: '2026-05-22T12:00:00Z', notes: 'block A note' }, created_at: new Date('2026-05-22T12:00:00Z') };
      const dB = { id: 'd-B', sender_e164: SENDER, status: 'commit_failed',   log_type: 'seeding',     draft_json: { event_timestamp: '2026-05-21T12:00:00Z', name: 'inoc' },        created_at: new Date('2026-05-21T12:00:00Z') };
      const w = makeWiring({ findResult: dA, activeDrafts: [dA, dB] });
      const capture = { handle: jest.fn() };
      const sig = makeSignalClient([makeEnvelope({ source: SENDER, text: 'YES' })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      const askBack = w.confirmOutbound.dispatch.mock.calls.find((c) => c[0] === 'send_ask_back');
      expect(askBack).toBeDefined();
      expect(askBack[2]).toMatchObject({ activeDrafts: [dA, dB], senderE164: SENDER });
      expect(w.confirmDb.confirmDraft).not.toHaveBeenCalled();
      expect(w.confirmDb.discardDraft).not.toHaveBeenCalled();
      expect(w.editHandler.handleEdit).not.toHaveBeenCalled();
    });

    // Hotfix 2026-05-23: stale commit_failed drafts must not trap fresh captures.
    // The SQL-side fix in confirm-db.findActiveDraftsForSender ages them out.
    // This test mirrors the live-fire failure (Santi sent "DT tubs 0519 1 and 2"
    // with 5 stale commit_failed drafts from May 13-21); the receive-loop sees
    // an EMPTY activeDrafts list (mocked here) and falls through to capture.
    it('hotfix-2026-05-23: fresh capture with NO stale-active drafts -> capture pipeline runs', async () => {
      const w = makeWiring({ findResult: null, activeDrafts: [] }); // post-hotfix view
      const capture = { handle: jest.fn() };
      const sig = makeSignalClient([makeEnvelope({ source: SENDER, text: 'DT tubs 0519 1 and 2' })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      const askBack = w.confirmOutbound.dispatch.mock.calls.find((c) => c[0] === 'send_ask_back');
      expect(askBack).toBeUndefined();
      expect(capture.handle).toHaveBeenCalledTimes(1);
    });

    // Terminal-draft polite ack: quote resolves to committed -> send_quote_closed; no mutation.
    it('quote resolves to a terminal (committed) draft -> send_quote_closed; no mutation', async () => {
      const dTerm = { id: 'd-old', sender_e164: SENDER, status: 'committed', log_type: 'seeding', draft_json: { name: 'inoc' }, created_at: new Date('2026-05-13T12:00:00Z') };
      const w = makeWiring({ findResult: null, activeDrafts: [], quoteResolveResult: dTerm });
      const capture = { handle: jest.fn() };
      const sig = makeSignalClient([makeEnvelope({
        source: SENDER, text: 'EDIT actually 10 not 5', quote: quoteShape(1779000000000),
      })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      const closed = w.confirmOutbound.dispatch.mock.calls.find((c) => c[0] === 'send_quote_closed');
      expect(closed).toBeDefined();
      expect(closed[1]).toBe(dTerm);
      expect(w.editHandler.handleEdit).not.toHaveBeenCalled();
      expect(w.confirmDb.confirmDraft).not.toHaveBeenCalled();
    });

    // Orphan quote (resolves to null) + 1 active -> falls through to single active draft.
    it('orphan quote (resolves null) + 1 active -> falls through to that draft', async () => {
      const d1 = { id: 'd1', sender_e164: SENDER, status: 'awaiting_farmer' };
      const w = makeWiring({ findResult: d1, activeDrafts: [d1], quoteResolveResult: null });
      const capture = { handle: jest.fn() };
      const sig = makeSignalClient([makeEnvelope({
        source: SENDER, text: 'YES', quote: quoteShape(9999999999999),
      })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      expect(w.confirmDb.findDraftByQuotedMsgTs).toHaveBeenCalled();
      expect(w.confirmDb.confirmDraft).toHaveBeenCalledWith({}, 'd1');
    });

    // Orphan quote + >1 active -> numbered ask-back (orphan-quote-with-ambiguous-fallback).
    it('orphan quote + >1 active -> numbered ask-back (no silent route)', async () => {
      const dA = { id: 'd-A', sender_e164: SENDER, status: 'awaiting_farmer' };
      const dB = { id: 'd-B', sender_e164: SENDER, status: 'awaiting_farmer' };
      const w = makeWiring({ findResult: dA, activeDrafts: [dA, dB], quoteResolveResult: null });
      const capture = { handle: jest.fn() };
      const sig = makeSignalClient([makeEnvelope({
        source: SENDER, text: 'NO', quote: quoteShape(9999999999999),
      })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      const askBack = w.confirmOutbound.dispatch.mock.calls.find((c) => c[0] === 'send_ask_back');
      expect(askBack).toBeDefined();
      expect(w.confirmDb.discardDraft).not.toHaveBeenCalled();
    });

    // T-50-04-01: quote resolves to a draft owned by a different sender -> spoof guard.
    it('T-50-04-01: quote resolves to a draft owned by ANOTHER sender -> drop; no route', async () => {
      const dSpoofed = { id: 'd-spoofed', sender_e164: SENDER_OTHER, status: 'awaiting_farmer' };
      const w = makeWiring({ findResult: null, activeDrafts: [], quoteResolveResult: dSpoofed });
      const capture = { handle: jest.fn().mockResolvedValue(null) };
      const sig = makeSignalClient([makeEnvelope({
        source: SENDER, text: 'NO', quote: quoteShape(1779562666675),
      })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      // No route to spoofed draft.
      expect(w.confirmDb.discardDraft).not.toHaveBeenCalled();
      expect(w.editHandler.handleEdit).not.toHaveBeenCalled();
      // No quote-closed (different sender) and no ask-back (0 active for THIS sender).
      const closed = w.confirmOutbound.dispatch.mock.calls.find((c) => c[0] === 'send_quote_closed');
      expect(closed).toBeUndefined();
      // Falls through to capture (treated as orphan + 0-active).
      expect(capture.handle).toHaveBeenCalledTimes(1);
    });

    it('quote-bearing envelope reads dm.quote.timestamp when dm.quote.id is absent', async () => {
      const d1 = { id: 'd-quoted', sender_e164: SENDER, status: 'awaiting_farmer' };
      const w = makeWiring({ findResult: null, activeDrafts: [], quoteResolveResult: d1 });
      const capture = { handle: jest.fn() };
      const sig = makeSignalClient([makeEnvelope({
        source: SENDER, text: 'YES',
        quote: { timestamp: 1779560222000, authorNumber: BOT, text: 'older bot ack' },
      })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      expect(w.confirmDb.findDraftByQuotedMsgTs).toHaveBeenCalledWith({}, 1779560222000);
      expect(w.confirmDb.confirmDraft).toHaveBeenCalledWith({}, 'd-quoted');
    });
  });

  // 2026-05-24 fix (signal-capture-missing-followup-messages): confirm-branch
  // replies are consumed before the SLOW PATH, so they must persist their own
  // paper-trail row via capturePipeline.recordReplyCapture. NOOP fall-through must
  // NOT (full handle() persists it instead -- no double-write).
  describe('confirm-thread replies persist to signal_capture (recordReplyCapture)', () => {
    function makeCaptureSpy() {
      return { handle: jest.fn().mockResolvedValue(null), recordReplyCapture: jest.fn().mockResolvedValue(null) };
    }

    it.each([
      ['YES', { id: 'd1', sender_e164: '+15550001234' }],
      ['NO', { id: 'd1', sender_e164: '+15550001234' }],
      ['EDIT qty was 12', { id: 'd1', sender_e164: '+15550001234' }],
    ])('consumed reply %p -> recordReplyCapture once, handle never', async (text, findResult) => {
      const w = makeWiring({ findResult });
      const capture = makeCaptureSpy();
      const sig = makeSignalClient([makeEnvelope({ text })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      expect(capture.recordReplyCapture).toHaveBeenCalledTimes(1);
      expect(capture.handle).not.toHaveBeenCalled();
    });

    it('NOOP fall-through -> handle once, recordReplyCapture never (no double-persist)', async () => {
      const w = makeWiring({ findResult: { id: 'd1', sender_e164: '+15550001234' } });
      const capture = makeCaptureSpy();
      const sig = makeSignalClient([makeEnvelope({ text: '👍' })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      expect(capture.handle).toHaveBeenCalledTimes(1);
      expect(capture.recordReplyCapture).not.toHaveBeenCalled();
    });

    it('no active draft -> handle once, recordReplyCapture never', async () => {
      const w = makeWiring({ findResult: null });
      const capture = makeCaptureSpy();
      const sig = makeSignalClient([makeEnvelope({ text: 'fresh message' })]);
      const loop = createReceiveLoop({
        signalClient: sig, dispatch: jest.fn(), config: baseConfig, capturePipeline: capture, logger: silentLogger(), ...w,
      });
      await runOneTick(loop);
      expect(capture.handle).toHaveBeenCalledTimes(1);
      expect(capture.recordReplyCapture).not.toHaveBeenCalled();
    });
  });
});
