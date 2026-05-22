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
