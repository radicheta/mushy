'use strict';

// Phase 38 Plan 06: outbound dispatcher.
//
// Replaces Plan 05's logging stub with real signal-client sends. Two outbound
// paths:
//   1. send_ask_back -- farmer_facing_preview reply to the originating capture,
//      routed by reply_target_kind (DM vs group). Group sends use the bare
//      internal_id; signal.js translates to the wire id (Phase 37 D-16 / 37-04).
//   2. send_needs_review_ping -- DM to operatorRecipient (Don Santiago) when an
//      ask-back loop terminates at the 3-turn cap. Addresses him by name,
//      never as "operator" (project memory: farmer-facing artifact rules).
//
// All farmer/operator-facing text passes through sanitizeFarmerText (defense in
// depth -- preview-builder already sanitizes its output). dispatch() never
// throws; signal-cli outages return { ok:false, reason } so the pipeline keeps
// the draft row in its persisted state for retry on the next farmer message.

function truncId(id) {
  if (typeof id !== 'string') return '';
  return id.slice(0, 10);
}

function createOutboundDispatcher({
  signalClient,
  config: _config,
  logger = console,
  previewBuilder,
  operatorRecipient,
}) {
  if (!signalClient || typeof signalClient.send !== 'function') {
    throw new Error('createOutboundDispatcher: signalClient.send required');
  }
  if (!previewBuilder || typeof previewBuilder.sanitizeFarmerText !== 'function') {
    throw new Error('createOutboundDispatcher: previewBuilder.sanitizeFarmerText required');
  }
  const sanitize = previewBuilder.sanitizeFarmerText;

  function resolveAskBackTarget(draftRow) {
    if (draftRow && draftRow.reply_target_kind === 'group') {
      if (typeof draftRow.group_id === 'string' && draftRow.group_id.length > 0) {
        return { groupId: draftRow.group_id };
      }
      return null;
    }
    // Default: DM to the originating sender.
    if (typeof draftRow.sender_e164 === 'string' && draftRow.sender_e164.length > 0) {
      return draftRow.sender_e164;
    }
    return null;
  }

  async function safeSend(body, target) {
    try {
      const res = await signalClient.send(body, { to: target });
      return res || { ok: true };
    } catch (e) {
      logger.warn && logger.warn(`[outbound] signal send failed: ${e.message}`);
      return { ok: false, reason: e.message };
    }
  }

  async function sendAskBack(draftRow) {
    const target = resolveAskBackTarget(draftRow);
    if (target == null) {
      logger.warn && logger.warn(`[outbound] send_ask_back: no_target draft=${truncId(draftRow && draftRow.id)}`);
      return { ok: false, reason: 'no_target' };
    }
    const raw = (draftRow && draftRow.farmer_facing_preview) || '';
    const text = sanitize(raw);
    const res = await safeSend(text, target);
    if (res.ok) {
      logger.info && logger.info(`[outbound] ask_back sent draft=${truncId(draftRow.id)} preview="${text.slice(0, 40)}"`);
    }
    return res;
  }

  async function sendNeedsReviewPing(draftRow) {
    if (!operatorRecipient || typeof operatorRecipient !== 'string' || operatorRecipient.length === 0) {
      logger.warn && logger.warn(`[outbound] needs_review_ping: no_target (operatorRecipient unset)`);
      return { ok: false, reason: 'no_target' };
    }
    const id = truncId(draftRow && draftRow.id);
    const sender = (draftRow && draftRow.sender_e164) || '(unknown)';
    const reason = (draftRow && draftRow.needs_review_reason) || 'askback_cap';
    // Address Don Santiago by name (project memory: never "operator" as referent).
    const raw = `Hey Don Santiago, draft ${id} for ${sender} hit the 3-turn ask-back cap. Marked for manual review. Reason: ${reason}.`;
    const text = sanitize(raw);
    const res = await safeSend(text, operatorRecipient);
    if (res.ok) {
      logger.info && logger.info(`[outbound] needs_review_ping sent draft=${id}`);
    }
    return res;
  }

  async function dispatch(sideEffect, draftRow) {
    try {
      switch (sideEffect) {
        case 'send_ask_back':
          return await sendAskBack(draftRow || {});
        case 'send_needs_review_ping':
          return await sendNeedsReviewPing(draftRow || {});
        case 'mark_expired':
        case 'handoff_to_phase_39':
        case 'noop':
          logger.debug && logger.debug(`[outbound] side_effect=${sideEffect} (no send)`);
          return { ok: true, noop: true };
        default:
          logger.warn && logger.warn(`[outbound] unknown side_effect=${sideEffect}`);
          return { ok: false, reason: 'unknown_side_effect' };
      }
    } catch (e) {
      logger.warn && logger.warn(`[outbound] dispatch ${sideEffect} threw: ${e.message}`);
      return { ok: false, reason: e.message };
    }
  }

  return { dispatch };
}

module.exports = { createOutboundDispatcher };
