'use strict';

// Phase 39 D-03 / D-03a: EDIT-loop orchestrator.
//
// Bumps edit_turn_count, re-extracts via the Phase 38 extractor with the
// farmer's correction as additional context, updates the draft in place
// (same id, same source_capture_ids), re-renders the preview, and returns
// a side-effect tag for Plan 06's receive-loop to dispatch.
//
// Never throws -- all failure paths return {ok:false, reason}.

function createEditHandler({
  pool,
  extractor,
  confirmDb,
  previewBuilderConfirm,
  // previewBuilderExtraction kept in signature for forward-compat / explicit wiring,
  // even though we currently call the confirm-flavored renderer (which already wraps
  // the extraction preview-builder).
  // eslint-disable-next-line no-unused-vars
  previewBuilderExtraction,
  stateMachineExtraction,
  config,
  logger = console,
}) {
  async function handleEdit(draftRow, editText) {
    try {
      if (!draftRow || !draftRow.id) {
        return { ok: false, reason: 'no_draft_row' };
      }
      const editStr = typeof editText === 'string' ? editText : '';
      const maxTurns = config.maxEditTurns;

      // Plan 45-03 Option X: state guard. EDIT is permitted from awaiting_farmer
      // (the original Phase 39 path) and from commit_failed (the NORTH-STAR fix:
      // the "Send EDIT to fix" affordance in the failure ack must be truthful).
      // Any other state (confirmed, committed, discarded, expired, needs_review,
      // draft, committing) rejects.
      const startStatus = draftRow.status;
      if (startStatus !== 'awaiting_farmer' && startStatus !== 'commit_failed') {
        return { ok: false, reason: 'wrong_state' };
      }

      // commit_failed -> awaiting_farmer transition before falling through to
      // the existing awaiting_farmer code path. We do NOT touch outcome_ack_sent_at
      // (the original commit's ack stands; Plan 04 ack-slot semantics will apply
      // to the next attempt). bumpEditTurn + updateDraftAfterEdit both WHERE on
      // status='awaiting_farmer', so the transition MUST happen first.
      if (startStatus === 'commit_failed') {
        let reactivate;
        try {
          reactivate = await pool.query(
            `UPDATE signal_draft
                SET status='awaiting_farmer',
                    updated_at=NOW()
              WHERE id=$1 AND status='commit_failed'
              RETURNING id`,
            [draftRow.id]
          );
        } catch (e) {
          logger.warn(`[edit-handler] commit_failed->awaiting_farmer transition threw: ${e.message}`);
          return { ok: false, reason: e.message };
        }
        if (!reactivate || reactivate.rowCount === 0) {
          // Race: another tick already moved the draft out of commit_failed.
          logger.info('[edit-handler] commit_failed transition lost the race');
          return { ok: false, reason: 'state_changed' };
        }
        // Reflect on the in-memory draftRow so downstream sees the new state.
        draftRow.status = 'awaiting_farmer';
      }

      // Pre-cap short-circuit (avoids burning an LLM call when we know the cap is hit).
      if ((draftRow.edit_turn_count || 0) >= maxTurns) {
        return { ok: true, sideEffect: 'send_edit_cap_msg', reason: 'edit_cap_exceeded' };
      }

      const bump = await confirmDb.bumpEditTurn(pool, draftRow.id);
      if (!bump.ok) {
        logger.warn(`[edit-handler] bump failed: ${bump.reason}`);
        return { ok: false, reason: bump.reason };
      }

      let result;
      try {
        result = await extractor.extract({
          captures: [
            {
              captureId: 'edit-' + draftRow.id,
              text: null,
              transcript: null,
              images: [],
              farmerCorrection: editStr,
            },
          ],
          inFlightDraft: draftRow.draft_json,
          farmerCorrection: editStr,
        });
      } catch (e) {
        logger.warn(`[edit-handler] extractor threw: ${e.message}`);
        await confirmDb.appendEventViaPool(pool, draftRow.id, 'edit', {
          ok: false,
          reason: e.message,
          editText: editStr.slice(0, 200),
        });
        return { ok: false, reason: e.message };
      }

      if (!result || !result.ok) {
        const reason = (result && result.reason) || 'extractor_failed';
        logger.warn(`[edit-handler] re-extract failed: ${reason}`);
        await confirmDb.appendEventViaPool(pool, draftRow.id, 'edit', {
          ok: false,
          reason,
          editText: editStr.slice(0, 200),
        });
        return { ok: false, reason };
      }

      const draft = result.draft;
      const required = (stateMachineExtraction.REQUIRED_FIELDS &&
                        stateMachineExtraction.REQUIRED_FIELDS[draft && draft.type]) || [];
      const newPreview = previewBuilderConfirm.buildPreviewWithSuffix({
        draft,
        perFieldConfidence: result.per_field_confidence || {},
        requiredFields: required,
        threshold: config.extractionConfidenceThreshold,
      });

      const upd = await confirmDb.updateDraftAfterEdit(pool, draftRow.id, {
        draftJson: draft,
        perFieldConfidence: result.per_field_confidence || null,
        farmerFacingPreview: newPreview,
      });
      if (!upd.ok) {
        logger.warn(`[edit-handler] updateDraftAfterEdit failed: ${upd.reason}`);
        return { ok: false, reason: upd.reason };
      }
      if (upd.rowCount === 0) {
        logger.info('[edit-handler] draft no longer active when update landed (concurrent confirm/expire)');
        return { ok: true, sideEffect: 'noop', reason: 'draft_no_longer_active' };
      }

      await confirmDb.appendEventViaPool(pool, draftRow.id, 'edit', {
        ok: true,
        edit_turn: bump.edit_turn_count,
        editText: editStr.slice(0, 200),
      });

      return {
        ok: true,
        sideEffect: 'send_preview_resend',
        newPreview,
        nextEditTurnCount: bump.edit_turn_count,
      };
    } catch (e) {
      logger.warn(`[edit-handler] error: ${e.message}`);
      return { ok: false, reason: e.message };
    }
  }

  return { handleEdit };
}

module.exports = { createEditHandler };
