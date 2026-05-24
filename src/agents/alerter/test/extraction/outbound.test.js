'use strict';

// Phase 38 Plan 06: outbound dispatcher tests.
//
// Real Signal sends for ask-back + needs-review ping side-effects. DM vs group
// routing comes from draftRow.reply_target_kind; operator pings always route to
// the operatorRecipient E.164 from config. All farmer-facing text is sanitized
// (no em-dashes, fmtNum on numerics). Dispatch never throws.

const { createOutboundDispatcher } = require('../../src/extraction/outbound');
const previewBuilder = require('../../src/extraction/preview-builder');

const silentLogger = { info: () => {}, warn: () => {}, debug: () => {}, error: () => {} };

function makeSignalOk() {
  return { send: jest.fn().mockResolvedValue({ ok: true, timestamp: 1234 }) };
}

function makeSignalFail(reason = 'boom') {
  return { send: jest.fn().mockRejectedValue(new Error(reason)) };
}

function makeDraftRow(over = {}) {
  return {
    id: 'abcdef1234567890',
    sender_e164: '+59898018597',
    farmos_person: 'vikki',
    status: 'awaiting_farmer',
    draft_json: { type: 'seeding', species: 'SHI' },
    farmer_facing_preview: 'What is the block name?\n\ntype: seeding\nspecies: SHI',
    reply_target_kind: 'dm',
    group_id: null,
    source_capture_ids: ['cap-1'],
    askback_turns: 1,
    ...over,
  };
}

describe('createOutboundDispatcher', () => {
  test('send_ask_back DM -> signalClient.send called with target = sender_e164', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const row = makeDraftRow({ reply_target_kind: 'dm' });
    const r = await d.dispatch('send_ask_back', row);
    expect(r.ok).toBe(true);
    expect(signalClient.send).toHaveBeenCalledTimes(1);
    const call = signalClient.send.mock.calls[0];
    // signal.js send signature: send(body, { to })
    expect(call[0]).toBe(row.farmer_facing_preview);
    expect(call[1]).toMatchObject({ to: '+59898018597', intent: 'extraction_preview' });
  });

  test('send_ask_back group -> signalClient.send target = { groupId }', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const row = makeDraftRow({ reply_target_kind: 'group', group_id: 'internalIdAbc' });
    const r = await d.dispatch('send_ask_back', row);
    expect(r.ok).toBe(true);
    const call = signalClient.send.mock.calls[0];
    expect(call[1]).toMatchObject({ to: { groupId: 'internalIdAbc' }, intent: 'extraction_preview' });
  });

  test('send_ask_back strips em-dash from farmer_facing_preview', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const row = makeDraftRow({
      farmer_facing_preview: 'Hey — is this right?\n\ntype: seeding',
    });
    await d.dispatch('send_ask_back', row);
    const text = signalClient.send.mock.calls[0][0];
    expect(text).not.toMatch(/—/);
    expect(text).toContain('Hey  is this right?');
  });

  test('send_needs_review_ping -> target = operatorRecipient', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const row = makeDraftRow({ status: 'needs_review' });
    const r = await d.dispatch('send_needs_review_ping', row);
    expect(r.ok).toBe(true);
    expect(signalClient.send).toHaveBeenCalledTimes(1);
    const call = signalClient.send.mock.calls[0];
    expect(call[1]).toMatchObject({ to: '+59892893012', intent: 'extraction_preview' });
  });

  test('send_needs_review_ping text addresses Don Santiago, not "operator"', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const row = makeDraftRow();
    await d.dispatch('send_needs_review_ping', row);
    const text = signalClient.send.mock.calls[0][0];
    expect(text).toContain('Don Santiago');
    // "operator" as referent (capitalized or lowercase quoted use) must not appear
    // in farmer/operator-facing text. Allow it inside code/variable names only.
    expect(text.toLowerCase()).not.toContain('operator');
  });

  test('send_needs_review_ping text contains truncated draft id + sender', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const row = makeDraftRow({ id: 'aabbccddeeffgg11223344', sender_e164: '+59898018597' });
    await d.dispatch('send_needs_review_ping', row);
    const text = signalClient.send.mock.calls[0][0];
    expect(text).toContain('aabbccddee'); // first 10 chars of id
    expect(text).toContain('+59898018597');
  });

  test('send_needs_review_ping text has no em-dash', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const row = makeDraftRow({ needs_review_reason: 'manual—review' });
    await d.dispatch('send_needs_review_ping', row);
    const text = signalClient.send.mock.calls[0][0];
    expect(text).not.toMatch(/—/);
  });

  test('handoff_to_phase_39 -> no signalClient.send call', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const r = await d.dispatch('handoff_to_phase_39', makeDraftRow());
    expect(r.ok).toBe(true);
    expect(signalClient.send).not.toHaveBeenCalled();
  });

  test('mark_expired -> no signalClient.send call', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const r = await d.dispatch('mark_expired', makeDraftRow());
    expect(r.ok).toBe(true);
    expect(signalClient.send).not.toHaveBeenCalled();
  });

  test('noop -> no send, returns ok', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const r = await d.dispatch('noop', makeDraftRow());
    expect(r.ok).toBe(true);
    expect(signalClient.send).not.toHaveBeenCalled();
  });

  test('unknown side effect -> logger.warn, no send, returns ok:false', async () => {
    const signalClient = makeSignalOk();
    const warn = jest.fn();
    const d = createOutboundDispatcher({
      signalClient, config: {},
      logger: { ...silentLogger, warn },
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const r = await d.dispatch('totally_made_up_effect', makeDraftRow());
    expect(r.ok).toBe(false);
    expect(warn).toHaveBeenCalled();
    expect(signalClient.send).not.toHaveBeenCalled();
  });

  test('signalClient.send rejects -> dispatch returns ok:false, never throws', async () => {
    const signalClient = makeSignalFail('network down');
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    let threw = false;
    let r;
    try {
      r = await d.dispatch('send_ask_back', makeDraftRow());
    } catch (e) {
      threw = true;
    }
    expect(threw).toBe(false);
    expect(r.ok).toBe(false);
    expect(r.reason).toMatch(/network down/);
  });

  test('send_ask_back with missing target -> ok:false, no send', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const row = makeDraftRow({ reply_target_kind: 'dm', sender_e164: null });
    const r = await d.dispatch('send_ask_back', row);
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('no_target');
    expect(signalClient.send).not.toHaveBeenCalled();
  });

  // Hotfix 2026-05-24: trinity-skip. When operatorRecipient == capture sender
  // (Santi/radicheta/farmer-1 trinity), operator-channel pings would interrupt
  // the farmer-side conversation with internal-looking chatter. Skip.
  test('hotfix-2026-05-24: send_batch_review_summary skipped when operator==sender (trinity)', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const batch = {
      sender_e164: '+59892893012', // SAME as operatorRecipient
      draftIds: [
        { id: 'bb34475403aa', status: 'needs_review' },
        { id: 'ccd52457c2bb', status: 'needs_review' },
      ],
    };
    const r = await d.dispatch('send_batch_review_summary', batch);
    expect(r.ok).toBe(true);
    expect(r.skipped).toBe('trinity');
    expect(signalClient.send).not.toHaveBeenCalled();
  });

  test('hotfix-2026-05-24: send_batch_review_summary still fires when operator!=sender (Vikki case)', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const batch = {
      sender_e164: '+59898018597', // Vikki, NOT the operator
      draftIds: [{ id: 'aa', status: 'needs_review' }, { id: 'bb', status: 'needs_review' }],
    };
    const r = await d.dispatch('send_batch_review_summary', batch);
    expect(r.ok).toBe(true);
    expect(r.skipped).toBeUndefined();
    expect(signalClient.send).toHaveBeenCalledTimes(1);
  });

  test('hotfix-2026-05-24: send_needs_review_ping skipped when operator==sender (trinity)', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: '+59892893012',
    });
    const row = makeDraftRow({ sender_e164: '+59892893012' }); // SAME as operator
    const r = await d.dispatch('send_needs_review_ping', row);
    expect(r.ok).toBe(true);
    expect(r.skipped).toBe('trinity');
    expect(signalClient.send).not.toHaveBeenCalled();
  });

  test('send_needs_review_ping with missing operatorRecipient -> ok:false, no send', async () => {
    const signalClient = makeSignalOk();
    const d = createOutboundDispatcher({
      signalClient, config: {}, logger: silentLogger,
      previewBuilder, operatorRecipient: null,
    });
    const r = await d.dispatch('send_needs_review_ping', makeDraftRow());
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('no_target');
    expect(signalClient.send).not.toHaveBeenCalled();
  });
});
