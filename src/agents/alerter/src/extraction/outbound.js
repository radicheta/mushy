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

  async function safeSend(body, target, relatedCaptureId, relatedDraftId) {
    try {
      // Phase 44 Plan-03 D-13/D-16: extraction outbound sends go through the
      // wrapped send with intent='extraction_preview' (covers ask-back replies,
      // needs-review pings, and batch review summaries — all preview-class).
      const res = await signalClient.send(body, {
        to: target,
        intent: 'extraction_preview',
        relatedCaptureId: relatedCaptureId || null,
        // 2026-05-24 fix: per-draft outbounds must record the draft they relate
        // to, else forensic "every outbound for draft X" joins skip preview rows
        // (related_draft_id was landing NULL). Batch summaries span many drafts
        // and pass null. signal.js threads this to signal_outbound.related_draft_id.
        relatedDraftId: relatedDraftId || null,
        sourceModule: 'extraction/outbound.js',
      });
      return res || { ok: true };
    } catch (e) {
      logger.warn && logger.warn(`[outbound] signal send failed: ${e.message}`);
      return { ok: false, reason: e.message };
    }
  }

  function firstCaptureId(draftRow) {
    const arr = draftRow && draftRow.source_capture_ids;
    if (Array.isArray(arr) && arr.length > 0 && typeof arr[0] === 'string') return arr[0];
    return null;
  }

  async function sendAskBack(draftRow) {
    const target = resolveAskBackTarget(draftRow);
    if (target == null) {
      logger.warn && logger.warn(`[outbound] send_ask_back: no_target draft=${truncId(draftRow && draftRow.id)}`);
      return { ok: false, reason: 'no_target' };
    }
    const raw = (draftRow && draftRow.farmer_facing_preview) || '';
    const text = sanitize(raw);
    const res = await safeSend(text, target, firstCaptureId(draftRow), (draftRow && draftRow.id) || null);
    if (res.ok) {
      logger.info && logger.info(`[outbound] ask_back sent draft=${truncId(draftRow.id)} preview="${text.slice(0, 40)}"`);
    }
    return res;
  }

  // Hotfix 2026-05-24: trinity-skip. When operatorRecipient == the captured
  // event's sender (Santi/radicheta/farmer-1 trinity), operator-channel pings
  // would interrupt his own farmer-side conversation with internal-looking
  // chatter (his own phone written back, opaque draft-id hex, batch
  // mechanics). Skip the operator ping in that case; the operator IS the
  // farmer here and the per-draft farmer-facing flow already covers it.
  function isOperatorEqualsSender(senderE164) {
    return typeof operatorRecipient === 'string'
      && typeof senderE164 === 'string'
      && operatorRecipient.length > 0
      && operatorRecipient === senderE164;
  }

  async function sendBatchReviewSummary(batch) {
    // Plan 08 batch mode (paper-log scan: drafts.length > 1).
    // batch = { sender_e164, draftIds: [{id, type, status}, ...], reply_target_kind, group_id, source_capture_ids }
    // One Signal message to Don Santiago summarising the page instead of N per-draft pings.
    if (!operatorRecipient || typeof operatorRecipient !== 'string' || operatorRecipient.length === 0) {
      logger.warn && logger.warn(`[outbound] batch_review_summary: no_target (operatorRecipient unset)`);
      return { ok: false, reason: 'no_target' };
    }
    const drafts = (batch && Array.isArray(batch.draftIds)) ? batch.draftIds : [];
    const sender = (batch && batch.sender_e164) || '(unknown)';
    if (isOperatorEqualsSender(sender)) {
      logger.info && logger.info(`[outbound] batch_review_summary skipped: operator==sender (trinity); drafts=${drafts.length}`);
      return { ok: true, skipped: 'trinity' };
    }
    const total = drafts.length;
    const needReview = drafts.filter((d) => d && d.status === 'needs_review').length;
    const clean = total - needReview;
    const idsPreview = drafts.slice(0, 3).map((d) => truncId(d && d.id)).join(', ');
    const more = drafts.length > 3 ? `, +${drafts.length - 3} more` : '';
    const raw = `Hey Don Santiago, paper-log scan from ${sender}: ${total} drafts (${clean} clean, ${needReview} need review). IDs: ${idsPreview}${more}.`;
    const text = sanitize(raw);
    const res = await safeSend(text, operatorRecipient);
    if (res.ok) {
      logger.info && logger.info(`[outbound] batch_review_summary sent total=${total} clean=${clean} needs_review=${needReview}`);
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
    if (isOperatorEqualsSender(sender)) {
      logger.info && logger.info(`[outbound] needs_review_ping skipped: operator==sender (trinity); draft=${id}`);
      return { ok: true, skipped: 'trinity' };
    }
    const reason = (draftRow && draftRow.needs_review_reason) || 'askback_cap';
    // Address Don Santiago by name (project memory: never "operator" as referent).
    const raw = `Hey Don Santiago, draft ${id} for ${sender} hit the 3-turn ask-back cap. Marked for manual review. Reason: ${reason}.`;
    const text = sanitize(raw);
    const res = await safeSend(text, operatorRecipient, null, (draftRow && draftRow.id) || null);
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
        // 2026-08-18: both of these are dispatched by the seeding-session flow
        // (pipeline.js + the starting-seq handler) and had no case here, so they
        // fell to default and sent nothing while the draft sat in
        // awaiting_farmer. Routing is identical to send_ask_back -- same target
        // resolution, same farmer_facing_preview payload -- which is exactly how
        // farm_agent/extraction/outbound.py has always handled them.
        case 'send_starting_seq_askback':
        case 'send_seeding_session_filled_preview':
          return await sendAskBack(draftRow || {});
        case 'send_needs_review_ping':
          return await sendNeedsReviewPing(draftRow || {});
        case 'send_batch_review_summary':
          // draftRow carries the batch payload for this side effect.
          return await sendBatchReviewSummary(draftRow || {});
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
