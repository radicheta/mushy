'use strict';

// Phase 40 B7.4 observation: resolve QRs + upload attachments + create
// observation log referencing assets and (best-effort) file_ids. Missing
// attachments are skipped per D-05a, NOT a commit failure.

const logs = require('../logs');
const qrMod = require('../qr');
const files = require('../files');

async function commitObservation(client, draft, ctx) {
  const dj = draft.draft_json || {};
  const draftId = draft.id;
  const qrCodes = Array.isArray(dj.qr_codes) ? dj.qr_codes : [];
  const timestamp = typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000);

  const assetIds = [];
  for (const qr of qrCodes) {
    const r = await qrMod.resolveQr(client, qr);
    if (r.found && r.assetId) assetIds.push(r.assetId);
  }
  if (assetIds.length === 0) {
    return { ok: false, reason: 'observation_requires_target' };
  }

  const captureIds = Array.isArray(draft.source_capture_ids) ? draft.source_capture_ids : [];
  let paths = [];
  if (ctx && typeof ctx.capturePathsFor === 'function' && captureIds.length > 0) {
    try { paths = await ctx.capturePathsFor(captureIds); } catch (_) { paths = []; }
  }
  const upRes = paths.length > 0
    ? await files.uploadAttachments(client, paths, { logger: ctx && ctx.logger })
    : { fileIds: [], skipped: [], failed: [] };

  // Attachments are best-effort (D-05a) and never fail the commit, but a failed
  // upload must NOT be swallowed: surface it in the result so it reaches the
  // audit log and the farmer ack instead of acking "saved" with photos dropped.
  const attachmentsFailed = Array.isArray(upRes.failed) ? upRes.failed : [];
  const attachmentsSkipped = Array.isArray(upRes.skipped) ? upRes.skipped : [];
  if (attachmentsFailed.length > 0 && ctx && ctx.logger && ctx.logger.warn) {
    ctx.logger.warn(`[commit-observation] ${attachmentsFailed.length} attachment(s) failed to upload draft=${draftId}: ${attachmentsFailed.map((f) => f.reason).join(', ')}`);
  }

  const name = `observation ${new Date(timestamp * 1000).toISOString().slice(0, 10)}`;
  // Phase 51 review: observation log stays POST-only (LOG_STABLE_KEYS.observation === null per CONTEXT.md).
  const r = await logs.createLog(client, 'observation', {
    name, timestamp, assetIds, fileIds: upRes.fileIds, notes: dj.notes || '', draftId,
  });
  if (!r.ok) {
    return {
      ok: false,
      reason: r.reason,
      http_status: r.http_status,
      file_ids: upRes.fileIds,
      attachments_failed: attachmentsFailed,
      attachments_skipped: attachmentsSkipped,
    };
  }
  return {
    ok: true,
    asset_ids: [],
    log_ids: [r.logId],
    file_ids: upRes.fileIds,
    attachments_failed: attachmentsFailed,
    attachments_skipped: attachmentsSkipped,
    http_status: r.http_status,
  };
}

module.exports = commitObservation;
