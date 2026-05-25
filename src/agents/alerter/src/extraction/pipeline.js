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
const { readImageToBase64 } = require('./multimodal');
const { sanitizeFarmerText } = require('./preview-builder');
const { fmtNum } = require('../message');
const {
  lookupLastSeqForDate,
  mintChildBlockNames,
  yyyymmddToYymmdd,
} = require('./seq-helper');

const IMAGE_EXT_RE = /\.(jpe?g|png|gif|webp)$/i;

async function loadImageBlocks(paths, logger) {
  if (!Array.isArray(paths) || paths.length === 0) return [];
  const blocks = [];
  for (const p of paths) {
    if (typeof p !== 'string' || !IMAGE_EXT_RE.test(p)) continue;
    const r = await readImageToBase64(p, { logger }).catch((e) => ({ ok: false, reason: e.message }));
    if (!r || !r.ok) {
      logger.warn && logger.warn(`[pipeline] image load skipped: ${p} (${r && r.reason})`);
      continue;
    }
    blocks.push({ data: r.data, media_type: r.media_type });
  }
  return blocks;
}

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

// Render '2026-05-22' as 'May 22'. Returns the input untouched if it does
// not match YYYY-MM-DD so the ask-back text degrades gracefully.
function formatEventDateHuman(eventDate) {
  if (typeof eventDate !== 'string') return String(eventDate);
  const m = eventDate.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return eventDate;
  const month = MONTHS[parseInt(m[2], 10) - 1] || m[2];
  const day = parseInt(m[3], 10);
  return `${month} ${day}`;
}

/**
 * buildStartingSeqAskBackText({totalChildren, eventDate, lastSeq, lastBlockName, senderName})
 *   -> string
 *
 * Phase 47 Plan 03: farmer-facing ask-back prompt for a seeding_session draft
 * with needs_input='starting_seq'. Style locks (project memory):
 *   - "block number" vocabulary (NOT "SEQ" -- dev shorthand only)
 *   - named greeting when senderName resolvable
 *   - no em-dashes (sanitizeFarmerText sweep)
 *   - fmtNum for the totalChildren count
 */
function buildStartingSeqAskBackText({
  totalChildren,
  eventDate,
  lastSeq,
  lastBlockName,
  senderName,
}) {
  const lines = [];
  if (senderName && typeof senderName === 'string' && senderName.trim()) {
    lines.push(`Hi ${senderName.trim()},`);
  }
  const dateStr = formatEventDateHuman(eventDate);
  lines.push(`${dateStr} inoc, ${fmtNum(totalChildren)} blocks. What block number should I start at?`);
  if (lastSeq != null) {
    const hint = lastBlockName ? lastBlockName : `block ${fmtNum(lastSeq)}`;
    lines.push(`Last block number today was ${hint}, so default is ${fmtNum(lastSeq + 1)}.`);
  } else {
    lines.push('No prior session today, so default is 1.');
  }
  lines.push('Reply with a number or just YES for the default.');
  return sanitizeFarmerText(lines.join('\n'));
}

// Parse a farmer reply for the starting_seq ask-back. Returns:
//   {kind:'yes'} | {kind:'number', n:int} | {kind:'unclear'}
function parseStartingSeqReply(replyText) {
  if (typeof replyText !== 'string') return { kind: 'unclear' };
  const t = replyText.trim();
  if (!t) return { kind: 'unclear' };
  if (/^yes$/i.test(t)) return { kind: 'yes' };
  if (/^(\d+)$/.test(t)) return { kind: 'number', n: parseInt(t, 10) };
  return { kind: 'unclear' };
}

// Sum a SeedingSession's group qtys. Tolerates missing/malformed qty fields.
function sumGroupQtys(groups) {
  if (!Array.isArray(groups)) return 0;
  let total = 0;
  for (const g of groups) {
    const v = g && g.qty && g.qty.value;
    if (typeof v === 'number' && Number.isFinite(v)) total += v;
  }
  return total;
}

// Phase 53 BACK-02: walk the nested per_field_confidence object and return the
// min numeric leaf. Empty / missing-leaf objects return 0 (forces batch-review --
// conservative: we'd rather over-route to the operator-summary path than spam
// the farmer with N confirm prompts based on zero confidence signal).
function minLeafConfidence(obj) {
  if (!obj || typeof obj !== 'object') return 0;
  let min = Infinity;
  let saw = false;
  const walk = (v) => {
    if (typeof v === 'number' && Number.isFinite(v)) {
      saw = true;
      if (v < min) min = v;
      return;
    }
    if (v && typeof v === 'object') {
      for (const k of Object.keys(v)) walk(v[k]);
    }
  };
  walk(obj);
  return saw ? min : 0;
}

// Phase 53 BACK-02: routing heuristic locked per D-BACK-02.
// drafts.length > 5  OR  min over drafts of minLeafConfidence(per_field_confidence) < 0.7
// -> existing runBatchMode (operator summary, needs_review marking).
// Otherwise -> small-N fan-out (N independent send_confirm_prompt dispatches).
function shouldBatchReview(draftsArr) {
  if (!Array.isArray(draftsArr) || draftsArr.length === 0) return false;
  if (draftsArr.length > 5) return true;
  for (const item of draftsArr) {
    const c = minLeafConfidence(item && item.per_field_confidence);
    if (c < 0.7) return true;
  }
  return false;
}

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

  // Plan 08 batch mode: multi-draft paper-log scan. Forces start_new, never asks the
  // farmer back, summarises the whole page to the operator in one Signal message.
  // Each draft gets a unique id via (sourceCaptureIds, index).
  async function runBatchMode({ draftsArr, captureCtx, sender, captureId, sourceCaptureIdsBase, nowMs, inFlight }) {
    const logger_ = logger;
    // Expire any prior in-flight before the batch lands -- paper-log scan resets conversational state.
    if (inFlight) {
      const exp = await extractionDb.updateDraftStatus(pool, inFlight.id, DRAFT_STATUS.EXPIRED);
      if (!exp.ok) {
        logger_.warn && logger_.warn(`[extraction] batch: expire prior draft failed: ${exp.reason}`);
      }
    }

    const persisted = [];
    for (let i = 0; i < draftsArr.length; i += 1) {
      const item = draftsArr[i] || {};
      const draft = item.draft || null;
      const perFieldConfidence = item.per_field_confidence || null;
      const draftId = extractionDb.computeDraftId(sourceCaptureIdsBase, i);

      const ins = await extractionDb.insertDraft(pool, {
        id: draftId,
        sender_e164: sender,
        farmos_person: captureCtx.farmosPerson || null,
        source_capture_ids: sourceCaptureIdsBase,
        status: DRAFT_STATUS.PENDING,
        log_type: (draft && draft.type) || null,
        draft_json: draft,
        per_field_confidence: perFieldConfidence,
        askback_turns: 0,
        reply_target_kind: captureCtx.replyTargetKind || null,
        group_id: captureCtx.groupId || null,
      });
      if (!ins.ok) {
        logger_.warn && logger_.warn(`[extraction] batch: insertDraft idx=${i} failed: ${ins.reason}`);
        continue;
      }

      // Run state-machine with maxAskbackTurns=0 to force NEEDS_REVIEW path
      // instead of send_ask_back for any draft that has missing/low-conf fields.
      const transition = stateMachine.transition(
        { status: DRAFT_STATUS.PENDING, askback_turns: 0, last_updated_at_ms: nowMs },
        {
          type: 'extraction_result',
          draft,
          perFieldConfidence: perFieldConfidence || {},
          threshold: config.extractionConfidenceThreshold,
          maxAskbackTurns: 0,
          now_ms: nowMs,
        },
      );

      // Cycle-1 finding 2026-05-25: batch mode never asks the farmer back (it
      // sends ONE operator summary per page), so a CLEAN draft must NOT land in
      // awaiting_farmer. Two reasons: (1) it would wait forever for a per-draft
      // YES that batch mode never solicits; (2) awaiting_farmer is in the
      // per-sender in-flight partial-unique-index set (extraction-db D-02c), so
      // the first clean draft holds the slot and every sibling PENDING insert in
      // the same page fails with in_flight_conflict -- silently dropping all but
      // the first entry of a multi-entry page. Route clean batch drafts to
      // needs_review too; the clean-vs-flagged split is preserved via
      // needs_review_reason for the operator summary.
      let nextStatus = transition.nextStatus;
      const extras = {};
      if (transition.reason === 'askback_cap') {
        extras.needs_review_reason = 'batch_mode_low_conf';
      } else if (nextStatus === DRAFT_STATUS.AWAITING_FARMER) {
        nextStatus = DRAFT_STATUS.NEEDS_REVIEW;
        extras.needs_review_reason = 'batch_mode_clean';
      }
      const finalUpd = await extractionDb.updateDraftStatus(pool, draftId, nextStatus, extras);
      if (!finalUpd.ok) {
        logger_.warn && logger_.warn(`[extraction] batch: final status update idx=${i} failed: ${finalUpd.reason}`);
      }
      persisted.push({
        id: draftId,
        type: draft && draft.type,
        status: nextStatus,
        needs_review_reason: extras.needs_review_reason || null,
      });
    }

    // One summary ping to the operator for the whole page.
    if (persisted.length > 0) {
      try {
        outboundDispatcher.dispatch('send_batch_review_summary', {
          sender_e164: sender,
          source_capture_ids: sourceCaptureIdsBase,
          reply_target_kind: captureCtx.replyTargetKind || null,
          group_id: captureCtx.groupId || null,
          draftIds: persisted,
        });
      } catch (e) {
        logger_.warn && logger_.warn(`[extraction] batch: dispatch summary failed: ${e.message}`);
      }
    }

    return {
      ok: true,
      mode: 'batch',
      count: persisted.length,
      draftIds: persisted.map((d) => d.id),
      // Clean-vs-flagged split now keyed off needs_review_reason since both land
      // in needs_review status (Cycle-1 finding 2026-05-25): 'batch_mode_clean'
      // were high-confidence, 'batch_mode_low_conf' tripped the confidence gate.
      cleanCount: persisted.filter((d) => d.needs_review_reason === 'batch_mode_clean').length,
      needsReviewCount: persisted.filter((d) => d.needs_review_reason === 'batch_mode_low_conf').length,
    };
  }

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
      // BUG FIX 2026-05-12: attachmentPaths are filesystem path strings, but multimodal.buildContentBlocks
      // expects {data, media_type} base64 blocks. Load images here before handing to extractor;
      // otherwise every image is silently skipped and Claude sees an empty prompt -> schema_invalid.
      const imageBlocks = await loadImageBlocks(captureCtx.attachmentPaths, logger);
      const captures = [{
        captureId,
        text: captureCtx.text || null,
        transcript: Array.isArray(captureCtx.transcripts) ? captureCtx.transcripts.join('\n') : null,
        images: imageBlocks,
      }];
      let extractResult;
      try {
        // Phase 53 BACK-01: forward corpus_context (e.g. {default_year:2025,
        // source:'paper_log'}) when the caller supplies it. The extractor's
        // buildInitialUserContent emits a `corpus_context: {...}` prompt block
        // only when this is a non-null object (extractor.js:64-69), so passing
        // null is a back-compat no-op for every existing live-capture caller.
        extractResult = await extractor.extract({
          captures,
          inFlightDraft: treatInFlight,
          corpusContext: captureCtx.corpusContext || null,
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

      // 999.53: stamp token usage on the originating signal_capture row.
      // Best-effort; failure logged + swallowed so the extraction pipeline never
      // degrades on a usage-only write hiccup. Skipped on ok:false (above) and
      // on usage:null to avoid all-null writes.
      if (extractResult.usage) {
        const u = extractResult.usage;
        try {
          await pool.query(
            `UPDATE signal_capture
               SET input_tokens = $1,
                   output_tokens = $2,
                   cache_creation_input_tokens = $3,
                   cache_read_input_tokens = $4,
                   model = $5
             WHERE id = $6`,
            [
              u.input_tokens ?? null,
              u.output_tokens ?? null,
              u.cache_creation_input_tokens ?? null,
              u.cache_read_input_tokens ?? null,
              'claude-sonnet-4-6',
              captureId,
            ],
          );
        } catch (e) {
          logger.warn && logger.warn(`[extraction] usage stamp failed: ${e.message}`);
        }
      }

      // Plan 08: extractor now returns drafts[] (multi-event per page for paper-log scans).
      // drafts.length === 1: legacy single-draft path (conversational, ask-back enabled).
      // drafts.length  >  1: batch mode -- force start_new, persist N rows, no per-draft
      // ask-back (would spam farmer with 21+ messages from one photo), one summary ping to
      // Don Santiago. See discuss with Don Santiago 2026-05-12.
      const draftsArr = Array.isArray(extractResult.drafts) ? extractResult.drafts : [];
      if (draftsArr.length > 1) {
        // Phase 53 BACK-02: route small-N high-confidence multi-draft captures
        // (e.g. "DT tubs 0519 1 and 2") through N independent confirm prompts
        // instead of the operator-channel batch-review queue. Heuristic locked
        // per D-BACK-02: drafts.length > 5 OR min per-draft confidence < 0.7
        // -> runBatchMode (unchanged). seeding_session in the mix falls
        // through to runBatchMode (safe default; small-N path is for
        // observation/activity shapes, not session shapes).
        const hasSeedingSession = draftsArr.some(
          (d) => d && d.draft && d.draft.type === 'seeding_session'
        );
        if (shouldBatchReview(draftsArr) || hasSeedingSession) {
          return await runBatchMode({
            draftsArr,
            captureCtx,
            sender,
            captureId,
            sourceCaptureIdsBase: [captureId],
            nowMs,
            inFlight,
          });
        }
        // Small-N high-conf fan-out: each draft -> its own normal confirm flow.
        // Expire prior in-flight once (a multi-draft capture resets the
        // conversational state, mirroring runBatchMode's behavior).
        if (inFlight) {
          const exp = await extractionDb.updateDraftStatus(pool, inFlight.id, DRAFT_STATUS.EXPIRED);
          if (!exp.ok) {
            logger.warn && logger.warn(`[extraction] multi_confirm: expire prior draft failed: ${exp.reason}`);
          }
        }
        const results = [];
        const sideEffectsAll = [];
        for (let i = 0; i < draftsArr.length; i += 1) {
          const item = draftsArr[i] || {};
          const dDraft = item.draft || null;
          const dPfc = item.per_field_confidence || {};
          const dLogType = dDraft && dDraft.type;
          const dDraftId = extractionDb.computeDraftId([captureId], i);
          // Insert as PENDING.
          const ins = await extractionDb.insertDraft(pool, {
            id: dDraftId,
            sender_e164: sender,
            farmos_person: captureCtx.farmosPerson || null,
            source_capture_ids: [captureId],
            status: DRAFT_STATUS.PENDING,
            log_type: dLogType || null,
            draft_json: dDraft,
            per_field_confidence: dPfc,
            askback_turns: 0,
            reply_target_kind: captureCtx.replyTargetKind || null,
            group_id: captureCtx.groupId || null,
          });
          if (!ins.ok) {
            logger.warn && logger.warn(`[extraction] multi_confirm: insertDraft idx=${i} failed: ${ins.reason}`);
            continue;
          }
          // Run state-machine with full maxAskbackTurns; high-conf path
          // typically produces send_confirm_prompt directly (no ask-back).
          const transition = stateMachine.transition(
            { status: DRAFT_STATUS.PENDING, askback_turns: 0, last_updated_at_ms: nowMs },
            {
              type: 'extraction_result',
              draft: dDraft,
              perFieldConfidence: dPfc,
              threshold: config.extractionConfidenceThreshold,
              maxAskbackTurns: config.maxAskbackTurns,
              now_ms: nowMs,
            },
          );
          const dExtras = {};
          const dNeedsPreview = transition.side_effects.includes('send_ask_back')
            || transition.side_effects.includes('send_needs_review_ping')
            || transition.side_effects.includes('send_confirm_prompt');
          if (dNeedsPreview) {
            try {
              const required = REQUIRED_FIELDS[dDraft && dDraft.type] || [];
              dExtras.farmer_facing_preview = previewBuilder.buildPreview({
                draft: dDraft,
                perFieldConfidence: dPfc,
                threshold: config.extractionConfidenceThreshold,
                requiredFields: required,
              });
            } catch (e) {
              logger.warn && logger.warn(`[extraction] multi_confirm: preview build failed: ${e.message}`);
            }
          }
          const finalUpd = await extractionDb.updateDraftStatus(pool, dDraftId, transition.nextStatus, dExtras);
          if (!finalUpd.ok) {
            logger.warn && logger.warn(`[extraction] multi_confirm: final status update idx=${i} failed: ${finalUpd.reason}`);
          }
          // Build per-draft draftRow and dispatch each side effect independently.
          const dDraftRow = {
            id: dDraftId,
            sender_e164: sender,
            farmos_person: captureCtx.farmosPerson || null,
            status: transition.nextStatus,
            draft_json: dDraft,
            farmer_facing_preview: dExtras.farmer_facing_preview || null,
            reply_target_kind: captureCtx.replyTargetKind || null,
            group_id: captureCtx.groupId || null,
            source_capture_ids: [captureId],
            askback_turns: transition.nextAskbackTurns || 0,
          };
          for (const effect of transition.side_effects) {
            try {
              outboundDispatcher.dispatch(effect, dDraftRow);
              sideEffectsAll.push(effect);
            } catch (e) {
              logger.warn && logger.warn(`[extraction] multi_confirm: dispatch ${effect} failed: ${e.message}`);
            }
          }
          results.push({ id: dDraftId, status: transition.nextStatus });
        }
        return {
          ok: true,
          mode: 'multi_confirm',
          count: results.length,
          draftIds: results.map((r) => r.id),
          sideEffects: sideEffectsAll,
        };
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

      // 5b. Phase 47 Plan 03: seeding_session ask-back short-circuit.
      // When the extractor emits draft.needs_input='starting_seq', we bypass
      // the generic state-machine ask-back path entirely: there is no
      // missing-required-field problem to render with TOP_Q_TEMPLATES (groups
      // are populated; only the per-session SEQ counter is missing). Build a
      // dedicated farmer-facing prompt with the last-today hint, persist as
      // AWAITING_FARMER, dispatch send_starting_seq_askback, return early.
      if (draft && draft.type === 'seeding_session' && draft.needs_input === 'starting_seq') {
        let lastSeqResult = { ok: true, lastSeq: null };
        try {
          lastSeqResult = await lookupLastSeqForDate(pool, draft.event_date, { logger });
        } catch (e) {
          logger.warn && logger.warn(`[extraction] starting_seq lookup threw: ${e.message}`);
        }
        const lastSeq = lastSeqResult && lastSeqResult.ok ? lastSeqResult.lastSeq : null;
        const totalChildren = sumGroupQtys(draft.groups);
        // Render the prior block_name for the hint when available -- helps the
        // farmer recognize their own paper-log handwriting.
        let lastBlockName = null;
        if (lastSeq != null) {
          // Best-effort: pull the first species code from the draft for the
          // hint format. Falls back to a numeric-only hint when unavailable.
          try {
            const firstSpecies = draft.groups
              && draft.groups[0]
              && draft.groups[0].species
              && draft.groups[0].species.value;
            if (firstSpecies) {
              lastBlockName = `${yyyymmddToYymmdd(draft.event_date)}_${firstSpecies}_${lastSeq}`;
            }
          } catch (_e) { /* ignore */ }
        }
        const preview = buildStartingSeqAskBackText({
          totalChildren,
          eventDate: draft.event_date,
          lastSeq,
          lastBlockName,
          senderName: captureCtx.senderName || null,
        });
        const askbackUpd = await extractionDb.updateDraftStatus(
          pool,
          draftId,
          DRAFT_STATUS.AWAITING_FARMER,
          { farmer_facing_preview: preview },
        );
        if (!askbackUpd.ok) {
          logger.warn && logger.warn(`[extraction] starting_seq status update failed: ${askbackUpd.reason}`);
          return { ok: false, reason: askbackUpd.reason };
        }
        const draftRow = {
          id: draftId,
          sender_e164: sender,
          farmos_person: captureCtx.farmosPerson || null,
          status: DRAFT_STATUS.AWAITING_FARMER,
          draft_json: draft,
          farmer_facing_preview: preview,
          reply_target_kind: captureCtx.replyTargetKind || null,
          group_id: captureCtx.groupId || null,
          source_capture_ids: sourceCaptureIds,
          askback_turns: priorAskbackTurns,
        };
        try {
          outboundDispatcher.dispatch('send_starting_seq_askback', draftRow);
        } catch (e) {
          logger.warn && logger.warn(`[extraction] dispatch send_starting_seq_askback failed: ${e.message}`);
        }
        return {
          ok: true,
          draftId,
          status: DRAFT_STATUS.AWAITING_FARMER,
          continuity,
          sideEffects: ['send_starting_seq_askback'],
        };
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

  /**
   * Phase 47 Plan 03: farmer-reply handler for the starting_seq ask-back.
   * Phase 48 will wire this into the reply-routing layer; for Phase 47 it is
   * unit-tested in isolation.
   *
   * Behavior:
   *   - Parse replyText: 'YES' (case-insensitive) -> use default; numeric ->
   *     use that N; anything else -> re-dispatch a clarifying ask-back.
   *   - Walk groups[] in order, consuming the per-session SEQ counter:
   *     each group mints qty.value block_names starting at the running N.
   *   - Set child_block_names.value = minted array per group, leave
   *     .confidence unchanged; set .sources to ['model_inference','text']
   *     to reflect the farmer-supplied SEQ.
   *   - Clear draft.needs_input.
   *   - Persist draft_json via updateDraftStatus({status: AWAITING_FARMER}).
   *   - Dispatch send_seeding_session_filled_preview so Phase 48's preview
   *     builder can render the group-by-parent table.
   *   - Idempotent: a second YES on a draft whose needs_input is already
   *     cleared returns {ok:true, noop:true} without re-minting.
   */
  async function handleStartingSeqReply({ draftId, replyText, captureCtx }) {
    try {
      if (!draftId) return { ok: false, reason: 'missing_draft_id' };
      const row = await extractionDb.getDraftById(pool, draftId);
      if (!row) return { ok: false, reason: 'draft_not_found' };

      const draft = row.draft_json || null;
      if (!draft || draft.type !== 'seeding_session') {
        return { ok: false, reason: 'not_seeding_session' };
      }

      // Idempotency: needs_input already cleared -> noop. Guards against
      // duplicate replies / Phase 48 retries that double-mint.
      if (draft.needs_input !== 'starting_seq') {
        return { ok: true, draftId, noop: true };
      }

      const parsed = parseStartingSeqReply(replyText);

      if (parsed.kind === 'unclear') {
        // Re-dispatch clarifying ask-back; draft state unchanged.
        let lastSeqResult = { ok: true, lastSeq: null };
        try {
          lastSeqResult = await lookupLastSeqForDate(pool, draft.event_date, { logger });
        } catch (_e) { /* ignore */ }
        const lastSeq = lastSeqResult && lastSeqResult.ok ? lastSeqResult.lastSeq : null;
        const totalChildren = sumGroupQtys(draft.groups);
        const base = buildStartingSeqAskBackText({
          totalChildren,
          eventDate: draft.event_date,
          lastSeq,
          lastBlockName: null,
          senderName: (captureCtx && captureCtx.senderName) || null,
        });
        const preview = sanitizeFarmerText(`Please reply with a number or YES.\n\n${base}`);
        try {
          outboundDispatcher.dispatch('send_starting_seq_askback', {
            ...row,
            farmer_facing_preview: preview,
          });
        } catch (e) {
          logger.warn && logger.warn(`[extraction] re-dispatch starting_seq failed: ${e.message}`);
        }
        return { ok: true, draftId, status: 'awaiting_farmer', clarified: true };
      }

      // Resolve the starting N.
      let startN;
      if (parsed.kind === 'number') {
        startN = parsed.n;
      } else {
        // YES -> use the default (lastSeq + 1, or 1 if none).
        let lastSeqResult = { ok: true, lastSeq: null };
        try {
          lastSeqResult = await lookupLastSeqForDate(pool, draft.event_date, { logger });
        } catch (_e) { /* ignore */ }
        const lastSeq = lastSeqResult && lastSeqResult.ok ? lastSeqResult.lastSeq : null;
        startN = (lastSeq != null) ? lastSeq + 1 : 1;
      }

      // Mint per-group block_names from the running counter.
      const yyMMdd = yyyymmddToYymmdd(draft.event_date);
      const updatedGroups = [];
      let counter = startN;
      for (const g of (draft.groups || [])) {
        const speciesCode = g && g.species && g.species.value;
        const qty = g && g.qty && g.qty.value;
        if (!speciesCode || typeof qty !== 'number') {
          return { ok: false, reason: 'malformed_group' };
        }
        const names = mintChildBlockNames({
          eventDateYYMMDD: yyMMdd,
          speciesCode,
          startSeq: counter,
          qty,
        });
        counter += qty;
        const prevCbn = (g && g.child_block_names) || {};
        updatedGroups.push({
          ...g,
          child_block_names: {
            value: names,
            confidence: typeof prevCbn.confidence === 'number' ? prevCbn.confidence : 1,
            sources: ['model_inference', 'text'],
          },
        });
      }

      const updatedDraft = { ...draft, groups: updatedGroups };
      delete updatedDraft.needs_input;

      const upd = await extractionDb.updateDraftStatus(
        pool,
        draftId,
        DRAFT_STATUS.AWAITING_FARMER,
        { draft_json: updatedDraft },
      );
      if (!upd.ok) {
        logger.warn && logger.warn(`[extraction] starting_seq fill update failed: ${upd.reason}`);
        return { ok: false, reason: upd.reason };
      }

      try {
        outboundDispatcher.dispatch('send_seeding_session_filled_preview', {
          ...row,
          draft_json: updatedDraft,
          status: DRAFT_STATUS.AWAITING_FARMER,
        });
      } catch (e) {
        logger.warn && logger.warn(`[extraction] dispatch filled_preview failed: ${e.message}`);
      }

      return {
        ok: true,
        draftId,
        status: DRAFT_STATUS.AWAITING_FARMER,
        startSeq: startN,
        sideEffects: ['send_seeding_session_filled_preview'],
      };
    } catch (e) {
      logger.warn && logger.warn(`[extraction] handleStartingSeqReply error: ${e.message}`);
      return { ok: false, reason: e.message };
    }
  }

  return { enqueue, handleStartingSeqReply };
}

module.exports = {
  createExtractionPipeline,
  loadImageBlocks,
  buildStartingSeqAskBackText,
  parseStartingSeqReply,
};
