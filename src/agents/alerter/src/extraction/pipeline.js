'use strict';

// Phase 38 Plan 05: extraction pipeline orchestrator.
//
// Composes Plans 02-04: signal_draft DB CRUD + extractor LLM call + state-machine.
// Capture.js fires enqueue() in fire-and-forget mode for any farmer message with
// a resolved farmos_person. This pipeline never throws -- the top-level try/catch
// returns { ok: false, reason } so the caller's .catch(logger.warn) seam stays a
// no-op on the happy path.
//
// Sequence per 38-05-PLAN.md:
//   1. getInFlightForSender
//   2. forceStartNewIfIdle (D-01a hard guard)
//   3. extractor.extract({captures, inFlightDraft})
//   4. resolve continuity decision: 'append' / 'replace' / 'start_new'
//        - append:   update existing draft, extend source_capture_ids
//        - replace:  update existing draft, replace draft_json
//        - start_new: mark prior in-flight EXPIRED, insert new draft (PENDING)
//   5. state-machine.transition with the freshly persisted draft
//   6. updateDraftStatus to nextStatus + farmer_facing_preview (when ask-back)
//   7. dispatch each side_effect via outboundDispatcher.dispatch
//
// All side effects (signal sends, etc.) are owned by the injected dispatcher.
// In Plan 05 it is a logging stub; Plan 06 swaps in the real signal-client send.

const { DRAFT_STATUS, REQUIRED_FIELDS } = require('./state-machine');

function createExtractionPipeline({
  pool,
  extractor,
  extractionDb,
  stateMachine,
  previewBuilder,
  config,
  logger = console,
  clock = { now: () => Date.now() },
  outboundDispatcher = { dispatch: () => {} },
}) {
  if (!pool) throw new Error('createExtractionPipeline: pool required');
  if (!extractor) throw new Error('createExtractionPipeline: extractor required');
  if (!extractionDb) throw new Error('createExtractionPipeline: extractionDb required');
  if (!stateMachine) throw new Error('createExtractionPipeline: stateMachine required');
  if (!previewBuilder) throw new Error('createExtractionPipeline: previewBuilder required');
  if (!config) throw new Error('createExtractionPipeline: config required');

  async function enqueue(captureCtx) {
    try {
      const nowMs = clock.now();
      const sender = captureCtx && captureCtx.sender;
      const captureId = captureCtx && captureCtx.captureId;
      if (!sender || !captureId) {
        return { ok: false, reason: 'missing_sender_or_capture_id' };
      }

      // 1. in-flight lookup
      let inFlight = null;
      try {
        inFlight = await extractionDb.getInFlightForSender(pool, sender);
      } catch (e) {
        logger.warn && logger.warn(`[extraction] in-flight lookup failed: ${e.message}`);
        return { ok: false, reason: e.message };
      }

      // Normalize inFlight last_updated_at_ms for the state-machine helpers.
      const inFlightForSm = inFlight
        ? {
            ...inFlight,
            last_updated_at_ms: inFlight.updated_at instanceof Date
              ? inFlight.updated_at.getTime()
              : (inFlight.updated_at ? new Date(inFlight.updated_at).getTime() : null),
          }
        : null;

      // 2. idle-gap hard guard
      const forced = stateMachine.forceStartNewIfIdle(
        inFlightForSm,
        nowMs,
        config.draftIdleGapMin,
      );
      const treatInFlight = forced === 'start_new' ? null : inFlight;

      // 3. extractor
      const captures = [{
        captureId,
        text: captureCtx.text || null,
        transcript: Array.isArray(captureCtx.transcripts) ? captureCtx.transcripts.join('\n') : null,
        images: Array.isArray(captureCtx.attachmentPaths) ? captureCtx.attachmentPaths : [],
      }];
      let extractResult;
      try {
        extractResult = await extractor.extract({
          captures,
          inFlightDraft: treatInFlight,
        });
      } catch (e) {
        logger.warn && logger.warn(`[extraction] extract threw: ${e.message}`);
        return { ok: false, reason: e.message };
      }
      if (!extractResult || !extractResult.ok) {
        const reason = extractResult && extractResult.reason ? extractResult.reason : 'extractor_failed';
        logger.warn && logger.warn(`[extraction] extractor returned ok:false reason=${reason}`);
        return { ok: false, reason };
      }

      // 4. resolve continuity
      const llmDecision = extractResult.continuity_decision || 'start_new';
      const continuity = forced === 'start_new' ? 'start_new' : llmDecision;

      let draftId;
      let sourceCaptureIds;
      let priorAskbackTurns = 0;

      if (continuity === 'append' && treatInFlight) {
        sourceCaptureIds = [
          ...(treatInFlight.source_capture_ids || []),
          captureId,
        ];
        draftId = treatInFlight.id;
        priorAskbackTurns = treatInFlight.askback_turns || 0;
      } else if (continuity === 'replace' && treatInFlight) {
        sourceCaptureIds = treatInFlight.source_capture_ids || [captureId];
        draftId = treatInFlight.id;
        priorAskbackTurns = treatInFlight.askback_turns || 0;
      } else {
        // start_new (or forced, or LLM said append/replace but no in-flight existed)
        sourceCaptureIds = [captureId];
        draftId = extractionDb.computeDraftId(sourceCaptureIds);
        priorAskbackTurns = 0;
      }

      // Expire prior in-flight if starting new.
      if (continuity === 'start_new' && inFlight && inFlight.id !== draftId) {
        const exp = await extractionDb.updateDraftStatus(
          pool,
          inFlight.id,
          DRAFT_STATUS.EXPIRED,
        );
        if (!exp.ok) {
          logger.warn && logger.warn(`[extraction] expire prior draft failed: ${exp.reason}`);
        }
      }

      // 5. persist draft -- insert on start_new, update on append/replace.
      const draft = extractResult.draft;
      const logType = draft && draft.type;

      if (continuity === 'append' || continuity === 'replace') {
        const upd = await extractionDb.updateDraftStatus(
          pool,
          draftId,
          DRAFT_STATUS.PENDING,
          {
            draft_json: draft,
            per_field_confidence: extractResult.per_field_confidence || null,
            log_type: logType || null,
          },
        );
        if (!upd.ok) {
          logger.warn && logger.warn(`[extraction] update-existing failed: ${upd.reason}`);
          return { ok: false, reason: upd.reason };
        }
        // source_capture_ids extension: separate SQL since whitelist excludes arrays.
        try {
          await pool.query(
            `UPDATE signal_draft SET source_capture_ids = $2 WHERE id = $1`,
            [draftId, sourceCaptureIds],
          );
        } catch (e) {
          logger.warn && logger.warn(`[extraction] source_capture_ids update failed: ${e.message}`);
        }
      } else {
        // start_new -> insert.
        const ins = await extractionDb.insertDraft(pool, {
          id: draftId,
          sender_e164: sender,
          farmos_person: captureCtx.farmosPerson || null,
          source_capture_ids: sourceCaptureIds,
          status: DRAFT_STATUS.PENDING,
          log_type: logType || null,
          draft_json: draft,
          per_field_confidence: extractResult.per_field_confidence || null,
          askback_turns: 0,
          reply_target_kind: captureCtx.replyTargetKind || null,
          group_id: captureCtx.groupId || null,
        });
        if (!ins.ok) {
          logger.warn && logger.warn(`[extraction] insertDraft failed: ${ins.reason}`);
          return { ok: false, reason: ins.reason };
        }
      }

      // 6. state-machine transition
      const transition = stateMachine.transition(
        {
          status: DRAFT_STATUS.PENDING,
          askback_turns: priorAskbackTurns,
          last_updated_at_ms: nowMs,
        },
        {
          type: 'extraction_result',
          draft,
          perFieldConfidence: extractResult.per_field_confidence || {},
          threshold: config.extractionConfidenceThreshold,
          maxAskbackTurns: config.maxAskbackTurns,
          now_ms: nowMs,
        },
      );

      // 7. status update with extras (preview when ask-back path)
      const extras = {};
      const askInfo = transition.askBackInfo || { missingFields: [], lowConfFields: [] };
      const needsPreview = transition.side_effects.includes('send_ask_back')
        || transition.side_effects.includes('send_needs_review_ping');

      if (needsPreview) {
        try {
          const required = REQUIRED_FIELDS[draft && draft.type] || [];
          const preview = previewBuilder.buildPreview({
            draft,
            perFieldConfidence: extractResult.per_field_confidence || {},
            threshold: config.extractionConfidenceThreshold,
            requiredFields: required,
          });
          extras.farmer_facing_preview = preview;
        } catch (e) {
          logger.warn && logger.warn(`[extraction] preview build failed: ${e.message}`);
        }
      }
      if (transition.reason === 'askback_cap') {
        extras.needs_review_reason = 'askback_cap_exceeded';
      }

      const finalUpd = await extractionDb.updateDraftStatus(
        pool,
        draftId,
        transition.nextStatus,
        extras,
      );
      if (!finalUpd.ok) {
        logger.warn && logger.warn(`[extraction] final status update failed: ${finalUpd.reason}`);
        return { ok: false, reason: finalUpd.reason };
      }

      // Bump askback_turns counter when ask-back fired.
      if (transition.side_effects.includes('send_ask_back')) {
        const bump = await extractionDb.advanceAskbackTurn(pool, draftId);
        if (!bump.ok) {
          logger.warn && logger.warn(`[extraction] askback bump failed: ${bump.reason}`);
        }
      }

      // 8. dispatch side effects. Build a minimal draftRow for the dispatcher.
      const draftRow = {
        id: draftId,
        sender_e164: sender,
        farmos_person: captureCtx.farmosPerson || null,
        status: transition.nextStatus,
        draft_json: draft,
        farmer_facing_preview: extras.farmer_facing_preview || null,
        reply_target_kind: captureCtx.replyTargetKind || null,
        group_id: captureCtx.groupId || null,
        source_capture_ids: sourceCaptureIds,
        askback_turns: transition.nextAskbackTurns,
      };
      for (const effect of transition.side_effects) {
        try {
          outboundDispatcher.dispatch(effect, draftRow);
        } catch (e) {
          logger.warn && logger.warn(`[extraction] dispatch ${effect} failed: ${e.message}`);
        }
      }

      return {
        ok: true,
        draftId,
        status: transition.nextStatus,
        continuity,
        sideEffects: transition.side_effects,
      };
    } catch (e) {
      logger.warn && logger.warn(`[extraction] error: ${e.message}`);
      return { ok: false, reason: e.message };
    }
  }

  return { enqueue };
}

module.exports = { createExtractionPipeline };
