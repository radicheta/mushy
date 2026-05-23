'use strict';

// Phase 44 Plan-04 D-02 step 1+2: pure rule fast-paths for the event-gate.
// rulePositive  — image/audio/strain-code/block-name/long-text → fast_event
// ruleNegative  — short ack within 30m of attestation_kickoff → skipped_rule_neg
// Both are pure (no I/O), mirror src/rules.js style.

const STRAIN_RE = /\b[A-Z]{2,4}\b/;
const BLOCK_RE = /\b\d{6}_[A-Z]{2,4}_\d+\b/;
const ACK_RE = /^(ok|yes|got it|thanks|gracias|si|sí|👍)$/i;

function rulePositive(envCtx) {
  if ((envCtx.attachmentCount || 0) > 0) return { hit: true, kind: 'image_or_audio' };
  const body = envCtx.text || envCtx.transcript || '';
  if (body.length > 200) return { hit: true, kind: 'long_text' };
  if (STRAIN_RE.test(body)) return { hit: true, kind: 'strain_code' };
  if (BLOCK_RE.test(body)) return { hit: true, kind: 'block_name' };
  return { hit: false };
}

function ruleNegative(envCtx, lastBotOutbound, nowMs) {
  if (!lastBotOutbound || lastBotOutbound.intent !== 'attestation_kickoff') {
    return { hit: false };
  }
  const sentAtMs = new Date(lastBotOutbound.sent_at).getTime();
  if (nowMs - sentAtMs > 30 * 60 * 1000) return { hit: false };
  const body = ((envCtx && envCtx.text) || '').trim();
  if (body.length >= 40) return { hit: false };
  if (!ACK_RE.test(body)) return { hit: false };
  return { hit: true, kind: 'short_ack_within_30m' };
}

module.exports = { rulePositive, ruleNegative };
