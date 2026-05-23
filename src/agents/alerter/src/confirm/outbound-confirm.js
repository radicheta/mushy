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
//
// Phase 45 Plan 04: registers `send_commit_outcome_ack` side-effect. The body
// is built by `renderOutcomeAck` (commit-outcome-preview.js, Plan 02). Sent
// with intent='commit_outcome_ack', which causes signal.js's single-hook
// signal_outbound persistence (Phase 44 Plan-02 D-14) to write a row tagged
// with tenant_id='mossrock', related_draft_id=draftRow.id. Logging is
// best-effort in signal.js (fail-open per D-03); we add no extra outboundDb
// write here.

const { renderOutcomeAck } = require('../farmos/commit-outcome-preview');

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
  // Phase 50 Plan 03: pool + confirmDb needed to resolve quote targets for
  // send_commit_outcome_ack and send_confirm_ack. Both are OPTIONAL -- when
  // missing, dispatch degrades to unquoted acks (no crash, no behavior change
  // from pre-Plan-03 callers).
  pool = null,
  confirmDb = null,
}) {
  if (!signalClient || typeof signalClient.send !== 'function') {
    throw new Error('createConfirmOutbound: signalClient.send required');
  }

  async function safeSend(body, target, draftId, intentOverride, quote) {
    try {
      // Phase 44 Plan-03 D-13/D-16: confirm-loop sends go through the wrapped
      // send with intent='confirm_prompt' so the signal_outbound row carries
      // the canonical enum + relatedDraftId for auditing.
      // Phase 45 Plan 04: callers may override intent (e.g. 'commit_outcome_ack')
      // so the signal_outbound row carries the terminal-state ack intent.
      // Phase 50 Plan 03: callers may pass a quote payload; signal.js validates
      // it and falls back to unquoted send if invalid. Undefined means no quote.
      const opts = {
        to: target,
        intent: intentOverride || 'confirm_prompt',
        relatedDraftId: draftId || null,
        sourceModule: 'outbound-confirm.js',
      };
      if (quote) opts.quote = quote;
      const res = await signalClient.send(body, opts);
      return res || { ok: true };
    } catch (e) {
      logger.warn && logger.warn(`[outbound-confirm] signal send failed: ${e.message}`);
      return { ok: false, reason: e.message };
    }
  }

  // Phase 50 Plan 03: resolve the first source-capture's Signal-native ts +
  // sender into a quote payload. Returns null on EVERY failure mode
  // (missing pool/confirmDb, missing draftRow, empty source_capture_ids,
  // capture row missing, NULL signal_msg_ts, DB error). When the lookup
  // was *attempted* but yielded nothing (capture row missing OR NULL ts OR
  // DB error), a warn is emitted; the empty-source-capture-ids path stays
  // silent (that is the expected shape for ack-without-capture flows).
  async function tryBuildQuoteForDraft(draftRow) {
    if (!draftRow) return null;
    if (!pool || !confirmDb || typeof confirmDb.getCaptureQuoteTarget !== 'function') {
      return null;
    }
    const captureIds = Array.isArray(draftRow.source_capture_ids)
      ? draftRow.source_capture_ids
      : [];
    if (captureIds.length === 0) return null;
    const captureId = captureIds[0];
    let tgt = null;
    try {
      tgt = await confirmDb.getCaptureQuoteTarget(pool, captureId);
    } catch (_e) {
      tgt = null;
    }
    if (!tgt || tgt.signal_msg_ts == null) {
      logger.warn &&
        logger.warn(
          `[outbound-confirm] no quote target for draft=${truncId(draftRow.id)} capture=${truncId(captureId)} -- sending unquoted ack`
        );
      return null;
    }
    const trimmed = String(tgt.raw_text || '').slice(0, 200);
    return {
      timestamp: Number(tgt.signal_msg_ts),
      author: tgt.sender,
      message: trimmed,
    };
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
        case 'send_confirm_ack': {
          // Phase 50 Plan 03: quote-aware ack. Best-effort -- lookup failure
          // degrades to unquoted ack rather than blocking (CONTEXT D-05,
          // [[feedback_no_silent_failure_after_farmer_confirm]]).
          body = previewBuilderConfirm.buildConfirmAck((draftRow && draftRow.id) || '');
          target = dm;
          if (target == null) {
            logger.warn && logger.warn(`[outbound-confirm] ${sideEffect}: no_target draft=${truncId(draftRow && draftRow.id)}`);
            return { ok: false, reason: 'no_target' };
          }
          const quote = await tryBuildQuoteForDraft(draftRow || null);
          const res = await safeSend(body, target, draftRow && draftRow.id, undefined, quote);
          if (res.ok) {
            logger.info && logger.info(`[outbound-confirm] ${sideEffect} sent draft=${truncId(draftRow && draftRow.id)}`);
          }
          return res;
        }
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
        case 'send_commit_outcome_ack': {
          // Phase 45 Plan 04: terminal-state ack (T4 commit_success, T6 commit_failed).
          // DM-only (per-farmer ack, never group). signal_outbound row is written
          // by signal.js's single-hook persistence with intent='commit_outcome_ack',
          // tenant_id='mossrock' (default), related_draft_id=draftRow.id. Best-effort
          // (fail-open per D-03); logging failure does NOT unwind the ack send.
          if (!extras.outcome) {
            logger.warn && logger.warn(`[outbound-confirm] send_commit_outcome_ack missing outcome draft=${truncId(draftRow && draftRow.id)}`);
            return { ok: false, reason: 'missing_outcome' };
          }
          let farmosLink;
          const resp = draftRow && draftRow.farmos_response;
          if (resp && typeof resp === 'object' && typeof resp.link === 'string' && resp.link.trim() !== '') {
            farmosLink = resp.link.trim();
          }
          if (dm == null) {
            logger.warn && logger.warn(`[outbound-confirm] send_commit_outcome_ack: no_target draft=${truncId(draftRow && draftRow.id)}`);
            return { ok: false, reason: 'no_target' };
          }
          body = renderOutcomeAck(draftRow || {}, {
            outcome: extras.outcome,
            reason: extras.reason,
            farmosLink,
          });
          // Phase 50 Plan 03: quote-aware ack on the highest-traffic terminal
          // ack site. Best-effort -- lookup failure degrades to unquoted ack.
          const quote = await tryBuildQuoteForDraft(draftRow || null);
          const res = await safeSend(body, dm, draftRow && draftRow.id, 'commit_outcome_ack', quote);
          if (res && res.ok) {
            logger.info && logger.info(`[outbound-confirm] send_commit_outcome_ack sent outcome=${extras.outcome} draft=${truncId(draftRow && draftRow.id)}`);
          }
          return res;
        }
        default:
          logger.warn && logger.warn(`[outbound-confirm] unknown side_effect=${sideEffect}`);
          return { ok: false, reason: 'unknown_side_effect' };
      }

      if (target == null) {
        logger.warn && logger.warn(`[outbound-confirm] ${sideEffect}: no_target draft=${truncId(draftRow && draftRow.id)}`);
        return { ok: false, reason: 'no_target' };
      }

      const res = await safeSend(body, target, draftRow && draftRow.id);
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
