'use strict';

// Phase 39 D-05 / D-05a / D-05b: farmer-facing string renderers for the
// confirm loop. Style locks: no em-dashes (sanitizeFarmerText sweep), all
// numbers via fmtNum, named address.

const { sanitizeFarmerText, buildPreview } = require('../extraction/preview-builder');
const { fmtNum } = require('../message');

function truncId(id) {
  if (typeof id !== 'string') return '';
  return id.slice(0, 10);
}

const REPLY_SUFFIX = '\n\nReply YES to commit, NO to discard, EDIT <text> to amend.';

function buildPreviewWithSuffix({ draft, perFieldConfidence, requiredFields, threshold }) {
  const body = buildPreview({ draft, perFieldConfidence, requiredFields, threshold });
  // Strip any [?] markers (D-05): by awaiting_farmer time, every field has
  // cleared the threshold or been explicitly confirmed.
  const cleaned = String(body).replace(/\s*\[\?\]/g, '');
  return sanitizeFarmerText(cleaned + REPLY_SUFFIX);
}

function buildConfirmAck(draftId) {
  return sanitizeFarmerText(`Locked in. Writing now. (draft ${truncId(draftId)})`);
}

function buildIdempotentAck() {
  return sanitizeFarmerText('Already locked in. Check the previous message.');
}

function buildDiscardAck() {
  return sanitizeFarmerText('Discarded. Nothing written.');
}

function buildEditCapMsg(maxEditTurns) {
  return sanitizeFarmerText(
    `I cannot get this right after ${fmtNum(maxEditTurns)} tries. Try splitting the message into smaller updates, or send NO to discard.`
  );
}

function buildNudge({ minutesRemaining, previewSummary } = {}) {
  const minsRaw = (minutesRemaining == null || Number.isNaN(Number(minutesRemaining)))
    ? 0
    : Math.max(0, Math.round(Number(minutesRemaining)));
  let body = `Still want to lock in this draft? Reply YES / NO / EDIT or it auto-expires in ${fmtNum(minsRaw)} min.`;
  if (typeof previewSummary === 'string' && previewSummary.trim() !== '') {
    body += `\n${previewSummary.trim()}`;
  }
  return sanitizeFarmerText(body);
}

function buildExpiredNote() {
  return sanitizeFarmerText(
    'Draft expired. Nothing was written. Send a fresh message if you still want to log this.'
  );
}

module.exports = {
  buildPreviewWithSuffix,
  buildConfirmAck,
  buildIdempotentAck,
  buildDiscardAck,
  buildEditCapMsg,
  buildNudge,
  buildExpiredNote,
};
