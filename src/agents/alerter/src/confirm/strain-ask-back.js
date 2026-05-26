'use strict';

// Phase 54.1 Plan 03 Task 1: per-encounter strain ask-back render + reply parser.
//
// Style locks: ASCII-only, no em-dashes (use `--`, `?`, `n/a`), no emoji.
// Mirror the renderNumberedAskBack / renderQuoteClosed discipline from
// outbound-confirm.js.

/**
 * Render a per-encounter strain ask-back message.
 *
 * @param {string} seenCode  - the extraction code that did not match the curated set
 * @param {string|null} nearest - nearest curated suggestion from nearestKnown(), or null
 * @returns {string}
 */
function renderStrainAskBack(seenCode, nearest) {
  const code = String(seenCode || '').toUpperCase().trim();
  if (nearest) {
    const n = String(nearest).toUpperCase().trim();
    return [
      `Saw strain '${code}' -- not in the active list.`,
      `New strain, or did you mean ${n}?`,
      `Reply YES to add '${code}' as a new strain, or reply ${n} (or "no, ${n}") to use the existing one.`,
    ].join('\n');
  }
  return [
    `Saw strain '${code}' -- not in the active list.`,
    `New strain? Reply YES to add it, or reply the correct strain code to remap.`,
  ].join('\n');
}

// Token sets for parseStrainAskBackReply.
const CONFIRM_SET = new Set(['yes', 'y', 'ok', 'si', 'si', 'confirm', 'new']);

// A "strain code" token looks like 2-4 uppercase chars (optionally with one digit).
// The curated 14-code set (SHI, KOY, LIMA, SH2, etc.) are 2-4 chars.
// Keeping this narrow avoids treating common words ("maybe", "nope") as codes.
// The caller (receive-loop) validates the extracted code against the curated set.
const CODE_RE = /^[A-Za-z][A-Za-z0-9]{1,3}$/;

/**
 * Parse an inbound farmer reply to a strain ask-back.
 *
 * @param {*} text
 * @returns {{ kind: 'confirm_new' } | { kind: 'correction', code: string } | { kind: 'unknown' }}
 */
function parseStrainAskBackReply(text) {
  if (typeof text !== 'string') return { kind: 'unknown' };
  const trimmed = text.trim();
  if (!trimmed) return { kind: 'unknown' };

  const lower = trimmed.toLowerCase();
  const firstToken = lower.split(/[\s,]+/)[0];

  // Confirm / YES path
  if (CONFIRM_SET.has(firstToken)) return { kind: 'confirm_new' };

  // "no, <CODE>" or "no <CODE>" -- extract the code after the "no" token
  if (firstToken === 'no') {
    // grab next token
    const rest = trimmed.slice(firstToken.length).replace(/^[\s,]+/, '').trim();
    if (rest && CODE_RE.test(rest)) {
      return { kind: 'correction', code: rest.toUpperCase() };
    }
    // bare "no" with nothing recognizable -- unknown
    return { kind: 'unknown' };
  }

  // Bare strain code token
  if (CODE_RE.test(trimmed)) {
    return { kind: 'correction', code: trimmed.toUpperCase() };
  }

  return { kind: 'unknown' };
}

module.exports = { renderStrainAskBack, parseStrainAskBackReply };
