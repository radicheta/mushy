'use strict';

const { createReceiveLoop } = require('../../src/receive-loop');

function silentLogger() {
  return { info: jest.fn(), warn: jest.fn(), debug: jest.fn() };
}

function makeEnvelope({ source = '+15550001234', text = 'YES' } = {}) {
  return {
    envelope: {
      source,
      dataMessage: { message: text, attachments: [] },
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

function makeWiring({ findResult = null, confirmResult = { ok: true, rowCount: 1 }, discardResult = { ok: true, rowCount: 1 }, editHandlerResult = { ok: true, sideEffect: 'send_preview_resend', newPreview: 'NEW' }, parserOverride = null } = {}) {
  const pool = {};
  const confirmDb = {
    findAwaitingForSender: jest.fn().mockResolvedValue(findResult),
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
});
