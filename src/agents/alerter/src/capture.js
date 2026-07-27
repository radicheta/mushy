'use strict';
// Phase 25: capture pipeline orchestrator (D-03 — errors never escape handle()).
// Factory: createCapturePipeline({ pool, signalClient, transcribeClient, llmClient,
//   captureHistory, sensorSnapshot, baseDir, logger, clock }) → { handle(envWrapper) }

const { ulid } = require('ulid');
const path = require('path');
const fs = require('fs/promises');
const { insertCapture } = require('./capture-db');
const { maskNumber } = require('./config');

const AUDIO_TYPES = new Set([
  'audio/aac', 'audio/mp4', 'audio/mpeg', 'audio/ogg', 'audio/wav', 'audio/webm',
]);
const IMAGE_TYPES = new Set([
  'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif', 'image/gif',
]);

function classify(text, attachments) {
  const hasAudio = attachments.some((a) => AUDIO_TYPES.has(a.contentType) || a.voiceNote === true);
  const hasImage = attachments.some((a) => IMAGE_TYPES.has(a.contentType));
  if (hasAudio && (hasImage || text)) return 'mixed';
  if (hasAudio) return 'audio';
  if (hasImage) return 'image';
  return 'text';
}

function safeExt(contentType) {
  const map = {
    'audio/aac': 'aac', 'audio/mp4': 'm4a', 'audio/mpeg': 'mp3',
    'audio/ogg': 'ogg', 'audio/wav': 'wav', 'audio/webm': 'webm',
    'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp',
    'image/heic': 'heic', 'image/heif': 'heif', 'image/gif': 'gif',
  };
  return map[contentType] || 'bin';
}

function buildPath(baseDir, capturedAtMs, id, ext) {
  const d = new Date(capturedAtMs);
  const day = d.toISOString().slice(0, 10);
  const time = d.toISOString().slice(11, 19).replace(/:/g, '-');
  // V12 file/resource: never trust client filename — derive from server-controlled ULID + sanitized ext only
  return path.join(baseDir, day, `${time}-${id}.${ext.replace(/[^a-z0-9]/gi, '')}`);
}

function createCapturePipeline({
  pool,
  signalClient,
  transcribeClient,
  llmClient,
  captureHistory,
  sensorSnapshot,
  baseDir,
  logger = console,
  clock = Date.now,
  // Phase 37 D-11/D-12 — boot-time static map from config.signalFarmerMap.
  // Empty Map default keeps capture.js standalone-testable; unknown senders
  // resolve to '(unassigned)' B6 sentinel.
  signalFarmerMap = new Map(),
  // Phase 38 Plan 05 -- extraction pipeline (fire-and-forget enqueue after the
  // signal_capture row lands). Optional; when absent, capture.js behaves as
  // pre-Phase-38 (no extraction path).
  extractionPipeline = null,
  // Phase 44 Plan-04 D-02/D-04: event-gate runs BEFORE extractionPipeline.enqueue
  // and BEFORE llmClient.compose. Optional; when absent, capture.js behaves as
  // pre-Phase-44 (extraction + convo always fire).
  eventGate = null,
  // Phase 44 Plan-04 D-06: convo gate respects EVENT_GATE_CONVO_MODE — 'silent'
  // (default) | 'negative_only' | 'off'. Loaded via config (Plan-06).
  config = { eventGateConvoMode: 'silent' },
}) {
  async function handle(envWrapper, ctx = {}) {
    // Extract fields from the signal-cli envelope shape:
    // { envelope: { source, dataMessage: { message, attachments } } }
    const env = envWrapper.envelope || envWrapper;
    const source = env.source || env.sourceNumber || '';
    const dm = env.dataMessage || {};
    const text = dm.message || null;
    const attachments = dm.attachments || [];

    // Phase 37 D-02/D-11/D-12/D-13/D-14 — reply target + farmOS person + row tags.
    // ctx (from receive-loop) is authoritative; fall back to dm.groupInfo so
    // capture.js is testable in isolation without a receive-loop driving it.
    const groupId = ctx.groupId ?? (dm.groupInfo?.groupId ?? null);
    const replyTarget = groupId ? { groupId } : source;
    const farmosPerson = signalFarmerMap.get(source) ?? '(unassigned)';
    const replyTargetKind = ctx.replyTargetKind ?? (groupId ? 'group' : 'dm');
    const suppressReply = ctx.suppressReply === true;
    if (typeof logger.debug === 'function') {
      logger.debug(`[capture] routing: sender=${maskNumber(source)} kind=${replyTargetKind} farmos=${farmosPerson} groupId=${groupId ? groupId.slice(0, 8) + '…' : 'none'}`);
    }

    const capturedAtMs = clock();
    const id = ulid(capturedAtMs);
    const messageType = classify(text || '', attachments);
    const attachmentPaths = [];
    let transcript = null;
    let degraded = false;

    // Step 1: download attachments (per-attachment try/catch — partial success acceptable)
    for (const att of attachments) {
      try {
        const buf = await signalClient.fetchAttachment(att.id);
        const ext = safeExt(att.contentType);
        const filePath = buildPath(baseDir, capturedAtMs, `${id}-${att.id}`, ext);
        await fs.mkdir(path.dirname(filePath), { recursive: true });
        await fs.writeFile(filePath, buf);
        attachmentPaths.push(filePath);
      } catch (e) {
        logger.warn(`[capture] attachment ${att.id} failed: ${e.message}`);
        degraded = true;
      }
    }

    // Step 2: transcribe first audio attachment (if any)
    const audioPath = attachmentPaths.find((p) => /\.(aac|m4a|mp3|ogg|wav|webm)$/i.test(p));
    if (audioPath) {
      const r = await transcribeClient.transcribe(audioPath).catch((e) => ({ ok: false, reason: e.message }));
      if (r.ok) {
        transcript = r.text;
      } else {
        degraded = true;
        logger.warn(`[capture] transcribe degraded: ${r.reason}`);
      }
    }

    // Step 3: persist row BEFORE LLM call so capture is durable even if LLM hangs
    // Phase 50 Plan-04: derive Signal-native ts fields from envelope (best-effort;
    // NULL when missing). signal_msg_ts is the inbound msg's ms-ts (always; what
    // the bot quotes on outbound). quote_msg_ts + quote_author_e164 are populated
    // only when the farmer used Signal's quote/reply UI; receive-loop precedent
    // at receive-loop.js:23-24 accepts both quote.author and quote.authorNumber
    // due to cross-version drift in signal-cli (Risk #9 / CONTEXT D-07).
    const sigMsgTs = (typeof dm.timestamp === 'number')
      ? dm.timestamp
      : (Number.isFinite(Number(dm.timestamp)) ? Number(dm.timestamp) : null);
    const q = dm.quote || null;
    const quoteMsgTsRaw = q ? (q.id != null ? q.id : q.timestamp) : null;
    const quoteMsgTs = quoteMsgTsRaw != null && Number.isFinite(Number(quoteMsgTsRaw))
      ? Number(quoteMsgTsRaw)
      : null;
    const quoteAuthor = q ? ((typeof q.author === 'string' && q.author) ? q.author
                             : (typeof q.authorNumber === 'string' && q.authorNumber) ? q.authorNumber
                             : null) : null;

    try {
      await insertCapture(pool, {
        id,
        captured_at: new Date(capturedAtMs),
        sender: source,
        message_type: messageType,
        raw_text: text ?? null,
        attachment_paths: attachmentPaths,
        transcript,
        llm_session_tag: null,
        llm_reply: null,
        degraded,
        // Phase 37 D-14 — routing metadata stamped at capture time.
        group_id: groupId,
        farmos_person: farmosPerson,
        reply_target_kind: replyTargetKind,
        // Phase 50 Plan-04 — Signal-native quote-thread persistence.
        signal_msg_ts: sigMsgTs,
        quote_msg_ts: quoteMsgTs,
        quote_author_e164: quoteAuthor,
      });
    } catch (e) {
      logger.warn(`[capture] db insert failed: ${e.message}`);
      // continue — still try to reply so farmer is not silenced (R6)
    }

    // Phase 44 Plan-04 D-02/D-04: event-gate dispatch BEFORE extractionPipeline.enqueue.
    // Fetch the last bot outbound within 30 min (NEG fast-path needs it). The
    // resulting `lastBot` is REUSED by the convo branch below (D-19) — exactly
    // ONE selectRecentOutboundByRecipient call per capture for the gate; the
    // convo branch issues a separate 24h-window call.
    let gateDecision = { gate: 'forced', allow_extract: true, allow_convo: true };
    let lastBot = null;
    if (eventGate) {
      try {
        const negSinceMs = capturedAtMs - 30 * 60 * 1000;
        const recentOut = await captureHistory.selectRecentOutboundByRecipient(source, negSinceMs).catch(() => []);
        lastBot = recentOut && recentOut.length ? recentOut[recentOut.length - 1] : null;
        gateDecision = await eventGate.classify(
          { text: text || null, transcript, attachmentCount: attachmentPaths.length },
          lastBot,
          capturedAtMs
        );
      } catch (e) {
        logger.warn(`[capture] gate classify failed (fail-OPEN): ${e.message}`);
        gateDecision = { gate: 'forced', allow_extract: true, allow_convo: true };
      }
      // D-04 audit column — best-effort UPDATE; never throws.
      try {
        await pool.query(
          `UPDATE signal_capture SET extraction_gate = $1 WHERE id = $2`,
          [gateDecision.gate, id]
        );
      } catch (e) {
        logger.warn(`[capture] gate audit failed: ${e.message}`);
      }
    }

    // Phase 38 Plan 05 -- fire-and-forget extraction enqueue. Gated on known
    // farmer (farmosPerson resolved to a slug, not the '(unassigned)' sentinel)
    // AND on gateDecision.allow_extract (Phase 44 D-02).
    if (gateDecision.allow_extract && extractionPipeline && farmosPerson && farmosPerson !== '(unassigned)') {
      extractionPipeline.enqueue({
        captureId: id,
        sender: source,
        farmosPerson,
        text: text || null,
        transcripts: transcript ? [transcript] : [],
        attachmentPaths,
        replyTargetKind,
        groupId,
        capturedAtMs,
        // Phase 53 BACK-01: corpus_context propagates from the receive layer
        // (Phase 54 backfill harness sets it; live receive-loop never does).
        // Defaults to null so live captures behave exactly as pre-Phase-53.
        corpusContext: ctx.corpusContext || null,
      }).catch((e) => logger.warn(`[capture] extraction enqueue failed: ${e.message}`));
    }

    // Step 4: LLM compose — gate-controlled per D-05/D-06.
    let replyText;
    let llmOk = false;
    // Backlog 999.53: carry token usage + model from compose result into Step 7 UPDATE.
    let llmUsage = null;
    let llmModel = null;
    const convoAllowed = gateDecision.allow_convo || (config && config.eventGateConvoMode === 'off');
    if (convoAllowed) {
      try {
        const sinceMs = capturedAtMs - 24 * 3600 * 1000;
        const history = await captureHistory.selectRecentBySender(source, sinceMs).catch(() => []);
        const snapshot = await sensorSnapshot().catch(() => null);
        // Phase 44 Plan-04 B3 Option A (D-18/D-19): 24h outbound window for
        // fmtHistory merge + lastBotOutbound for the "last thing you said to the farmer" block.
        // lastBot from the gate lookup is REUSED (it's the most-recent outbound across both windows).
        // Defensive: pre-Phase-44 callers may not inject selectRecentOutboundByRecipient — skip silently.
        const outboundHistory = typeof captureHistory.selectRecentOutboundByRecipient === 'function'
          ? await captureHistory.selectRecentOutboundByRecipient(source, sinceMs).catch(() => [])
          : [];
        const r = await llmClient.compose({
          history,
          outboundHistory,
          lastBotOutbound: lastBot,
          sensorSnapshot: snapshot,
          currentMessage: { text, transcript, attachmentCount: attachmentPaths.length, capturedAtMs },
        });
        if (r.ok) {
          replyText = r.text;
          llmOk = true;
          llmUsage = r.usage || null;
          llmModel = r.model || null;
        }
      } catch (e) {
        logger.warn(`[capture] llm error: ${e.message}`);
      }
    } else {
      logger.info(`[capture] convo suppressed by gate=${gateDecision.gate} mode=${config && config.eventGateConvoMode}`);
    }

    // Step 5: degraded fallback reply (R6) — never silent
    if (!replyText) {
      replyText = `received ${attachmentPaths.length} attachment(s)${text ? ` + ${text.length} chars text` : ''} at ${new Date(capturedAtMs).toISOString()} — ${audioPath && !transcript ? 'transcription queued' : 'will follow up'}`;
      degraded = true;
    }

    // Step 6: send reply (errors logged, never thrown)
    // Phase 37 D-02/D-08 — route to envelope source (DM) or group (group);
    // skip send entirely when receive-loop signals suppressReply (silent group
    // listener, or command branch already handled the reply).
    if (!suppressReply) {
      await signalClient.send(replyText, {
        to: replyTarget,
        intent: 'convo_reply',
        relatedCaptureId: id,
        sourceModule: 'capture.js',
      })
        .catch((e) => logger.warn(`[capture] reply send failed: ${e.message}`));
    }

    // Step 7: update row with llm fields (best-effort).
    // Backlog 999.53: also stamp token usage + model so v_llm_cost_daily can
    // surface $/day spend. Missing usage fields bind null (no throw).
    if (llmOk) {
      try {
        await pool.query(
          `UPDATE signal_capture
             SET llm_reply = $1,
                 degraded = $2,
                 input_tokens = $3,
                 output_tokens = $4,
                 cache_creation_input_tokens = $5,
                 cache_read_input_tokens = $6,
                 model = $7
           WHERE id = $8`,
          [
            replyText,
            degraded,
            llmUsage?.input_tokens ?? null,
            llmUsage?.output_tokens ?? null,
            llmUsage?.cache_creation_input_tokens ?? null,
            llmUsage?.cache_read_input_tokens ?? null,
            llmModel,
            id,
          ]
        );
      } catch (e) {
        logger.warn(`[capture] llm-reply update failed: ${e.message}`);
      }
    }
  }

  // 2026-05-24 fix (signal-capture-missing-followup-messages): confirm-thread
  // replies (YES / NO / EDIT / strain ask-back) are consumed by receive-loop's
  // Phase 39 branch and `continue` before reaching handle(), so they never landed
  // in signal_capture. That broke Phase 50 quote-routing (QUOT-02 needs the
  // inbound's signal_msg_ts in the table), the Phase 51 stub-merge audit, and the
  // farmer paper trail of literal YES/EDIT text.
  //
  // recordReplyCapture persists the raw inbound ONLY. It deliberately does NOT
  // download attachments, transcribe, run the event-gate, enqueue extraction, or
  // compose a convo reply -- the confirm-handler owns the farmer-facing response
  // for these messages, and a fall-through NOOP still goes through full handle().
  // Field derivation mirrors handle() Step 3; keep the two in sync.
  async function recordReplyCapture(envWrapper, ctx = {}) {
    const env = envWrapper.envelope || envWrapper;
    const source = env.source || env.sourceNumber || '';
    const dm = env.dataMessage || {};
    const text = dm.message || null;
    const attachments = dm.attachments || [];
    const groupId = ctx.groupId ?? (dm.groupInfo?.groupId ?? null);
    const farmosPerson = signalFarmerMap.get(source) ?? '(unassigned)';
    const replyTargetKind = ctx.replyTargetKind ?? (groupId ? 'group' : 'dm');
    const capturedAtMs = clock();
    const id = ulid(capturedAtMs);
    const sigMsgTs = (typeof dm.timestamp === 'number')
      ? dm.timestamp
      : (Number.isFinite(Number(dm.timestamp)) ? Number(dm.timestamp) : null);
    const q = dm.quote || null;
    const quoteMsgTsRaw = q ? (q.id != null ? q.id : q.timestamp) : null;
    const quoteMsgTs = quoteMsgTsRaw != null && Number.isFinite(Number(quoteMsgTsRaw))
      ? Number(quoteMsgTsRaw)
      : null;
    const quoteAuthor = q ? ((typeof q.author === 'string' && q.author) ? q.author
                             : (typeof q.authorNumber === 'string' && q.authorNumber) ? q.authorNumber
                             : null) : null;
    try {
      await insertCapture(pool, {
        id,
        captured_at: new Date(capturedAtMs),
        sender: source,
        message_type: classify(text || '', attachments),
        raw_text: text ?? null,
        attachment_paths: [],
        transcript: null,
        llm_session_tag: null,
        llm_reply: null,
        degraded: false,
        group_id: groupId,
        farmos_person: farmosPerson,
        reply_target_kind: replyTargetKind,
        signal_msg_ts: sigMsgTs,
        quote_msg_ts: quoteMsgTs,
        quote_author_e164: quoteAuthor,
      });
      // Tag the row so reply captures (no extraction ran) are distinguishable
      // from full captures. Best-effort, mirrors handle()'s gate-audit UPDATE.
      try {
        await pool.query(
          `UPDATE signal_capture SET extraction_gate = $1 WHERE id = $2`,
          ['confirm_reply', id]
        );
      } catch (e) {
        logger.warn(`[capture] reply gate-tag failed: ${e.message}`);
      }
      if (typeof logger.debug === 'function') {
        logger.debug(`[capture] reply persisted (confirm-thread) sender=${maskNumber(source)} ts=${sigMsgTs}`);
      }
    } catch (e) {
      logger.warn(`[capture] reply db insert failed: ${e.message}`);
    }
  }

  return { handle, recordReplyCapture };
}

module.exports = { createCapturePipeline };
