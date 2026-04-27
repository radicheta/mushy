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
}) {
  async function handle(envWrapper) {
    // Extract fields from the signal-cli envelope shape:
    // { envelope: { source, dataMessage: { message, attachments } } }
    const env = envWrapper.envelope || envWrapper;
    const source = env.source || env.sourceNumber || '';
    const dm = env.dataMessage || {};
    const text = dm.message || null;
    const attachments = dm.attachments || [];

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
      });
    } catch (e) {
      logger.warn(`[capture] db insert failed: ${e.message}`);
      // continue — still try to reply so farmer is not silenced (R6)
    }

    // Step 4: LLM compose — gather context + call
    let replyText;
    let llmOk = false;
    try {
      const sinceMs = capturedAtMs - 24 * 3600 * 1000;
      const history = await captureHistory.selectRecentBySender(source, sinceMs).catch(() => []);
      const snapshot = await sensorSnapshot().catch(() => null);
      const r = await llmClient.compose({
        history,
        sensorSnapshot: snapshot,
        currentMessage: { text, transcript, attachmentCount: attachmentPaths.length, capturedAtMs },
      });
      if (r.ok) {
        replyText = r.text;
        llmOk = true;
      }
    } catch (e) {
      logger.warn(`[capture] llm error: ${e.message}`);
    }

    // Step 5: degraded fallback reply (R6) — never silent
    if (!replyText) {
      replyText = `received ${attachmentPaths.length} attachment(s)${text ? ` + ${text.length} chars text` : ''} at ${new Date(capturedAtMs).toISOString()} — ${audioPath && !transcript ? 'transcription queued' : 'will follow up'}`;
      degraded = true;
    }

    // Step 6: send reply (errors logged, never thrown)
    await signalClient.send(replyText).catch((e) => logger.warn(`[capture] reply send failed: ${e.message}`));

    // Step 7: update row with llm fields (best-effort)
    if (llmOk) {
      try {
        await pool.query(
          `UPDATE signal_capture SET llm_reply = $1, degraded = $2 WHERE id = $3`,
          [replyText, degraded, id]
        );
      } catch (e) {
        logger.warn(`[capture] llm-reply update failed: ${e.message}`);
      }
    }
  }

  return { handle };
}

module.exports = { createCapturePipeline };
