'use strict';

const { createConfirmOutbound } = require('../../src/confirm/outbound-confirm');
const previewBuilderConfirm = require('../../src/confirm/preview');

function makeSignal() {
  return { send: jest.fn().mockResolvedValue({ ok: true }) };
}

function silentLogger() {
  return { info: jest.fn(), warn: jest.fn(), debug: jest.fn() };
}

function makeDispatcher(over = {}) {
  return createConfirmOutbound(Object.assign({
    signalClient: makeSignal(),
    previewBuilderConfirm,
    operatorRecipient: '+15550009999',
    logger: silentLogger(),
  }, over));
}

// Plan 50-03 helper: dispatcher with pool + confirmDb wired in.
function makeQuoteHarness({ getCaptureQuoteTarget } = {}) {
  const signal = makeSignal();
  const logger = silentLogger();
  const pool = { query: jest.fn() };
  const confirmDb = {
    getCaptureQuoteTarget:
      getCaptureQuoteTarget == null
        ? jest.fn().mockResolvedValue(null)
        : getCaptureQuoteTarget,
  };
  const d = createConfirmOutbound({
    signalClient: signal,
    previewBuilderConfirm,
    operatorRecipient: '+x',
    logger,
    pool,
    confirmDb,
  });
  return { d, signal, logger, pool, confirmDb };
}

describe('confirm outbound dispatcher (Phase 39 D-06 / D-06a)', () => {
  it('send_confirm_ack on group-origin draft -> DM to sender (D-06a override)', async () => {
    const signal = makeSignal();
    const d = createConfirmOutbound({
      signalClient: signal, previewBuilderConfirm, operatorRecipient: '+x', logger: silentLogger(),
    });
    const draftRow = { id: 'abcdef1234', sender_e164: '+15550001234', reply_target_kind: 'group', group_id: 'gX' };
    await d.dispatch('send_confirm_ack', draftRow);
    expect(signal.send).toHaveBeenCalledTimes(1);
    expect(signal.send.mock.calls[0][1]).toMatchObject({ to: '+15550001234', intent: 'confirm_prompt' });
  });

  it('send_confirm_idempotent_ack body contains "Already locked in"', async () => {
    const signal = makeSignal();
    const d = createConfirmOutbound({ signalClient: signal, previewBuilderConfirm, operatorRecipient: '+x', logger: silentLogger() });
    await d.dispatch('send_confirm_idempotent_ack', { id: 'a', sender_e164: '+1' });
    expect(signal.send.mock.calls[0][0]).toContain('Already locked in');
  });

  it('send_discard_ack body contains "Discarded"', async () => {
    const signal = makeSignal();
    const d = createConfirmOutbound({ signalClient: signal, previewBuilderConfirm, operatorRecipient: '+x', logger: silentLogger() });
    await d.dispatch('send_discard_ack', { id: 'a', sender_e164: '+1' });
    expect(signal.send.mock.calls[0][0]).toContain('Discarded');
  });

  it('send_edit_cap_msg includes max-edit-turns count', async () => {
    const signal = makeSignal();
    const d = createConfirmOutbound({ signalClient: signal, previewBuilderConfirm, operatorRecipient: '+x', logger: silentLogger() });
    await d.dispatch('send_edit_cap_msg', { id: 'a', sender_e164: '+1' }, { maxEditTurns: 3 });
    expect(signal.send.mock.calls[0][0]).toMatch(/\b3\b/);
  });

  it('send_nudge with minutesRemaining=5.7 -> body contains "6 min" (Math.round)', async () => {
    const signal = makeSignal();
    const d = createConfirmOutbound({ signalClient: signal, previewBuilderConfirm, operatorRecipient: '+x', logger: silentLogger() });
    await d.dispatch('send_nudge', { id: 'a', sender_e164: '+1', farmer_facing_preview: 'q?\n\ntype: seeding' }, { minutesRemaining: 5.7 });
    expect(signal.send.mock.calls[0][0]).toMatch(/\b6 min\b/);
  });

  it('send_expired_note contains "expired" + "Nothing was written"', async () => {
    const signal = makeSignal();
    const d = createConfirmOutbound({ signalClient: signal, previewBuilderConfirm, operatorRecipient: '+x', logger: silentLogger() });
    await d.dispatch('send_expired_note', { id: 'a', sender_e164: '+1' });
    const body = signal.send.mock.calls[0][0];
    expect(body.toLowerCase()).toContain('expired');
    expect(body).toContain('Nothing was written');
  });

  it('send_preview_resend on group-origin -> target=groupId (D-06 group routing for preview)', async () => {
    const signal = makeSignal();
    const d = createConfirmOutbound({ signalClient: signal, previewBuilderConfirm, operatorRecipient: '+x', logger: silentLogger() });
    const draftRow = { id: 'a', sender_e164: '+15550001234', reply_target_kind: 'group', group_id: 'gZ' };
    await d.dispatch('send_preview_resend', draftRow, { newPreview: 'NEW PREVIEW' });
    expect(signal.send.mock.calls[0][1]).toMatchObject({ to: { groupId: 'gZ' }, intent: 'confirm_prompt' });
    expect(signal.send.mock.calls[0][0]).toBe('NEW PREVIEW');
  });

  it('sender-less draftRow on send_confirm_ack -> ok:false, no_target, no throw', async () => {
    const signal = makeSignal();
    const d = createConfirmOutbound({ signalClient: signal, previewBuilderConfirm, operatorRecipient: '+x', logger: silentLogger() });
    const r = await d.dispatch('send_confirm_ack', { id: 'a' });
    expect(r).toEqual({ ok: false, reason: 'no_target' });
    expect(signal.send).not.toHaveBeenCalled();
  });

  it('unknown side_effect -> ok:false, unknown_side_effect, no throw', async () => {
    const d = makeDispatcher();
    const r = await d.dispatch('nonsense', { sender_e164: '+1' });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('unknown_side_effect');
  });
});

// =====================================================================
// Phase 50 Plan 03: outbound quote-threading at send_commit_outcome_ack
// and send_confirm_ack dispatch sites. Best-effort: missing capture /
// NULL signal_msg_ts / DB error all degrade to an unquoted ack rather
// than blocking. Other 6 side-effect cases must remain quote-free.
// =====================================================================

describe('Phase 50 Plan 03: quote-threaded outbound (send_commit_outcome_ack)', () => {
  function commitOutcomeDraft(extra = {}) {
    return Object.assign(
      {
        id: 'draft-abc-0001',
        sender_e164: '+15550001234',
        source_capture_ids: ['cap-1'],
        farmos_response: null,
      },
      extra
    );
  }

  it('quote-resolvable capture -> signal.send called with opts.quote', async () => {
    const { d, signal, confirmDb } = makeQuoteHarness({
      getCaptureQuoteTarget: jest.fn().mockResolvedValue({
        signal_msg_ts: 1779562666675,
        sender: '+15550001234',
        raw_text: 'farmer original message text',
      }),
    });
    await d.dispatch('send_commit_outcome_ack', commitOutcomeDraft(), {
      outcome: 'commit_success',
    });
    expect(confirmDb.getCaptureQuoteTarget).toHaveBeenCalledWith(expect.anything(), 'cap-1');
    expect(signal.send).toHaveBeenCalledTimes(1);
    const opts = signal.send.mock.calls[0][1];
    expect(opts.quote).toEqual({
      timestamp: 1779562666675,
      author: '+15550001234',
      message: 'farmer original message text',
    });
    expect(opts.intent).toBe('commit_outcome_ack');
  });

  it('raw_text > 200 chars is truncated to 200 in quote.message', async () => {
    const longText = 'x'.repeat(500);
    const { d, signal } = makeQuoteHarness({
      getCaptureQuoteTarget: jest.fn().mockResolvedValue({
        signal_msg_ts: 1779562666675,
        sender: '+15550001234',
        raw_text: longText,
      }),
    });
    await d.dispatch('send_commit_outcome_ack', commitOutcomeDraft(), {
      outcome: 'commit_success',
    });
    const opts = signal.send.mock.calls[0][1];
    expect(opts.quote.message).toHaveLength(200);
    expect(opts.quote.message).toBe('x'.repeat(200));
  });

  it('NULL signal_msg_ts -> ack still sends WITHOUT quote, warn logged', async () => {
    const { d, signal, logger } = makeQuoteHarness({
      getCaptureQuoteTarget: jest.fn().mockResolvedValue(null),
    });
    const r = await d.dispatch('send_commit_outcome_ack', commitOutcomeDraft(), {
      outcome: 'commit_success',
    });
    expect(r.ok).toBe(true);
    expect(signal.send).toHaveBeenCalledTimes(1);
    const opts = signal.send.mock.calls[0][1];
    expect(opts.quote).toBeUndefined();
    expect(logger.warn).toHaveBeenCalledWith(expect.stringMatching(/no quote target/));
  });

  it('source_capture_ids empty -> ack sends WITHOUT quote, NO warn (expected path)', async () => {
    const { d, signal, logger, confirmDb } = makeQuoteHarness();
    const r = await d.dispatch(
      'send_commit_outcome_ack',
      commitOutcomeDraft({ source_capture_ids: [] }),
      { outcome: 'commit_success' }
    );
    expect(r.ok).toBe(true);
    expect(signal.send).toHaveBeenCalledTimes(1);
    expect(signal.send.mock.calls[0][1].quote).toBeUndefined();
    expect(confirmDb.getCaptureQuoteTarget).not.toHaveBeenCalled();
    // No "no quote target" warn for the empty path (only the lookup-failure path warns).
    const warnsAboutQuote = logger.warn.mock.calls.filter((c) =>
      String(c[0]).includes('no quote target')
    );
    expect(warnsAboutQuote).toHaveLength(0);
  });

  it('source_capture_ids missing/non-array -> ack sends WITHOUT quote, no crash', async () => {
    const { d, signal } = makeQuoteHarness();
    const r = await d.dispatch(
      'send_commit_outcome_ack',
      commitOutcomeDraft({ source_capture_ids: undefined }),
      { outcome: 'commit_success' }
    );
    expect(r.ok).toBe(true);
    expect(signal.send.mock.calls[0][1].quote).toBeUndefined();
  });

  it('getCaptureQuoteTarget throws -> ack still fires WITHOUT quote, no exception escapes', async () => {
    const { d, signal, logger } = makeQuoteHarness({
      getCaptureQuoteTarget: jest.fn().mockRejectedValue(new Error('boom')),
    });
    const r = await d.dispatch('send_commit_outcome_ack', commitOutcomeDraft(), {
      outcome: 'commit_success',
    });
    expect(r.ok).toBe(true);
    expect(signal.send).toHaveBeenCalledTimes(1);
    expect(signal.send.mock.calls[0][1].quote).toBeUndefined();
    expect(logger.warn).toHaveBeenCalledWith(expect.stringMatching(/no quote target/));
  });

  it('no pool/confirmDb in scope -> ack sends WITHOUT quote, no crash', async () => {
    const signal = makeSignal();
    const d = createConfirmOutbound({
      signalClient: signal,
      previewBuilderConfirm,
      operatorRecipient: '+x',
      logger: silentLogger(),
      // pool + confirmDb intentionally omitted
    });
    const r = await d.dispatch('send_commit_outcome_ack', commitOutcomeDraft(), {
      outcome: 'commit_success',
    });
    expect(r.ok).toBe(true);
    expect(signal.send).toHaveBeenCalledTimes(1);
    expect(signal.send.mock.calls[0][1].quote).toBeUndefined();
  });
});

describe('Phase 50 Plan 03: quote-threaded outbound (send_confirm_ack)', () => {
  function confirmDraft(extra = {}) {
    return Object.assign(
      {
        id: 'draft-confirm-0001',
        sender_e164: '+15550001234',
        source_capture_ids: ['cap-2'],
      },
      extra
    );
  }

  it('quote-resolvable capture -> signal.send called with opts.quote', async () => {
    const { d, signal, confirmDb } = makeQuoteHarness({
      getCaptureQuoteTarget: jest.fn().mockResolvedValue({
        signal_msg_ts: 1779562700000,
        sender: '+15550001234',
        raw_text: 'i meant the other one',
      }),
    });
    await d.dispatch('send_confirm_ack', confirmDraft());
    expect(confirmDb.getCaptureQuoteTarget).toHaveBeenCalledWith(expect.anything(), 'cap-2');
    expect(signal.send).toHaveBeenCalledTimes(1);
    const opts = signal.send.mock.calls[0][1];
    expect(opts.quote).toEqual({
      timestamp: 1779562700000,
      author: '+15550001234',
      message: 'i meant the other one',
    });
  });

  it('NULL signal_msg_ts -> ack still sends WITHOUT quote, warn logged', async () => {
    const { d, signal, logger } = makeQuoteHarness({
      getCaptureQuoteTarget: jest.fn().mockResolvedValue(null),
    });
    await d.dispatch('send_confirm_ack', confirmDraft());
    expect(signal.send).toHaveBeenCalledTimes(1);
    expect(signal.send.mock.calls[0][1].quote).toBeUndefined();
    expect(logger.warn).toHaveBeenCalledWith(expect.stringMatching(/no quote target/));
  });

  it('source_capture_ids empty -> ack sends WITHOUT quote, NO warn', async () => {
    const { d, signal, logger } = makeQuoteHarness();
    await d.dispatch('send_confirm_ack', confirmDraft({ source_capture_ids: [] }));
    expect(signal.send).toHaveBeenCalledTimes(1);
    expect(signal.send.mock.calls[0][1].quote).toBeUndefined();
    const warns = logger.warn.mock.calls.filter((c) => String(c[0]).includes('no quote target'));
    expect(warns).toHaveLength(0);
  });

  it('getCaptureQuoteTarget throws -> ack still fires WITHOUT quote, no exception escapes', async () => {
    const { d, signal } = makeQuoteHarness({
      getCaptureQuoteTarget: jest.fn().mockRejectedValue(new Error('boom')),
    });
    const r = await d.dispatch('send_confirm_ack', confirmDraft());
    expect(r.ok).toBe(true);
    expect(signal.send.mock.calls[0][1].quote).toBeUndefined();
  });
});

describe('Phase 50 Plan 03: 6 other dispatch sites remain quote-free', () => {
  // CONTEXT: only send_commit_outcome_ack + send_confirm_ack carry quotes in
  // this plan. The other 6 cases (send_preview_resend, send_discard_ack,
  // send_expired_note, send_confirm_idempotent_ack, send_nudge, send_edit_cap_msg)
  // must NOT call getCaptureQuoteTarget and signal.send must be called without
  // opts.quote. send_idempotent_no_ack / send_preview_first are listed in CONTEXT
  // as future side-effect kinds but not yet registered as dispatch cases.

  const baseDraft = {
    id: 'draft-other',
    sender_e164: '+15550001234',
    source_capture_ids: ['cap-x'],
    reply_target_kind: 'dm',
  };

  test.each([
    ['send_discard_ack', baseDraft, undefined],
    ['send_expired_note', baseDraft, undefined],
    ['send_confirm_idempotent_ack', baseDraft, undefined],
    ['send_edit_cap_msg', baseDraft, { maxEditTurns: 3 }],
    ['send_nudge', Object.assign({}, baseDraft, { farmer_facing_preview: 'q?\n\ntype: seeding' }), { minutesRemaining: 5 }],
    ['send_preview_resend', baseDraft, { newPreview: 'NEW' }],
  ])('%s does NOT call getCaptureQuoteTarget and sends without opts.quote', async (kind, draft, extras) => {
    const { d, signal, confirmDb } = makeQuoteHarness({
      getCaptureQuoteTarget: jest.fn().mockResolvedValue({
        signal_msg_ts: 1779562700000,
        sender: '+15550001234',
        raw_text: 'should not appear',
      }),
    });
    await d.dispatch(kind, draft, extras);
    expect(confirmDb.getCaptureQuoteTarget).not.toHaveBeenCalled();
    expect(signal.send).toHaveBeenCalledTimes(1);
    expect(signal.send.mock.calls[0][1].quote).toBeUndefined();
  });
});
