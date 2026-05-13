'use strict';

// Phase 39 D-06 + D-06a: confirm-loop outbound dispatcher.
//
// Routing rules:
//   DM-always (D-06a): send_confirm_ack, send_confirm_idempotent_ack,
//     send_discard_ack, send_edit_cap_msg, send_nudge, send_expired_note.
//     These are personal acks -- never blast back to a group thread.
//   Group-aware (D-06): send_preview_resend honors reply_target_kind.
//
// Style locks: no em-dashes (sanitizeFarmerText sweep in preview.js), fmtNum
// for numbers, named address. Never throws.

function truncId(id) {
  if (typeof id !== 'string') return '';
  return id.slice(0, 10);
}

function createConfirmOutbound({
  signalClient,
  previewBuilderConfirm,
  // operatorRecipient kept for forward-compat (future "ping operator" tags). Currently unused.
  // eslint-disable-next-line no-unused-vars
  operatorRecipient,
  logger = console,
}) {
  if (!signalClient || typeof signalClient.send !== 'function') {
    throw new Error('createConfirmOutbound: signalClient.send required');
  }

  async function safeSend(body, target) {
    try {
      const res = await signalClient.send(body, { to: target });
      return res || { ok: true };
    } catch (e) {
      logger.warn && logger.warn(`[outbound-confirm] signal send failed: ${e.message}`);
      return { ok: false, reason: e.message };
    }
  }

  function dmTarget(draftRow) {
    if (draftRow && typeof draftRow.sender_e164 === 'string' && draftRow.sender_e164.length > 0) {
      return draftRow.sender_e164;
    }
    return null;
  }

  function groupAwareTarget(draftRow) {
    if (draftRow && draftRow.reply_target_kind === 'group') {
      if (typeof draftRow.group_id === 'string' && draftRow.group_id.length > 0) {
        return { groupId: draftRow.group_id };
      }
    }
    return dmTarget(draftRow);
  }

  function previewSummaryFromBody(body) {
    if (typeof body !== 'string') return '';
    const lines = body.split('\n').slice(2, 4).map((l) => l.trim()).filter(Boolean);
    return lines.join(' / ');
  }

  async function dispatch(sideEffect, draftRow, extras) {
    extras = extras || {};
    try {
      let body = null;
      let target = null;
      const dm = dmTarget(draftRow || {});

      switch (sideEffect) {
        case 'send_confirm_ack':
          body = previewBuilderConfirm.buildConfirmAck((draftRow && draftRow.id) || '');
          target = dm;
          break;
        case 'send_confirm_idempotent_ack':
          body = previewBuilderConfirm.buildIdempotentAck();
          target = dm;
          break;
        case 'send_discard_ack':
          body = previewBuilderConfirm.buildDiscardAck();
          target = dm;
          break;
        case 'send_edit_cap_msg':
          body = previewBuilderConfirm.buildEditCapMsg(extras.maxEditTurns);
          target = dm;
          break;
        case 'send_nudge':
          body = previewBuilderConfirm.buildNudge({
            minutesRemaining: extras.minutesRemaining,
            previewSummary: previewSummaryFromBody(draftRow && draftRow.farmer_facing_preview),
          });
          target = dm;
          break;
        case 'send_expired_note':
          body = previewBuilderConfirm.buildExpiredNote();
          target = dm;
          break;
        case 'send_preview_resend':
          body = extras.newPreview || (draftRow && draftRow.farmer_facing_preview) || '';
          target = groupAwareTarget(draftRow || {});
          break;
        default:
          logger.warn && logger.warn(`[outbound-confirm] unknown side_effect=${sideEffect}`);
          return { ok: false, reason: 'unknown_side_effect' };
      }

      if (target == null) {
        logger.warn && logger.warn(`[outbound-confirm] ${sideEffect}: no_target draft=${truncId(draftRow && draftRow.id)}`);
        return { ok: false, reason: 'no_target' };
      }

      const res = await safeSend(body, target);
      if (res.ok) {
        logger.info && logger.info(`[outbound-confirm] ${sideEffect} sent draft=${truncId(draftRow && draftRow.id)}`);
      }
      return res;
    } catch (e) {
      logger.warn && logger.warn(`[outbound-confirm] dispatch ${sideEffect} threw: ${e.message}`);
      return { ok: false, reason: e.message };
    }
  }

  return { dispatch };
}

module.exports = { createConfirmOutbound };
