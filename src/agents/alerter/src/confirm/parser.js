'use strict';

// Phase 39 D-01 + D-01a: pure first-token classifier for inbound farmer replies.
//
// Returns a discriminated-union shape: { kind: 'YES'|'NO'|'EDIT'|'NOOP', editText? }.
// Pure -- no IO, no logging, no throws. Receive-loop (Plan 06) is the consumer.

const REPLY_KINDS = Object.freeze({
  YES: 'YES',
  NO: 'NO',
  EDIT: 'EDIT',
  NOOP: 'NOOP',
});

const YES_SET = new Set(['yes', 'y', 'ok', 'si', 'sí']);
const NO_SET = new Set(['no', 'n', 'cancel', 'stop']);

function parseReply(body) {
  if (typeof body !== 'string') return { kind: REPLY_KINDS.NOOP };
  const trimmed = body.trim();
  if (trimmed === '') return { kind: REPLY_KINDS.NOOP };
  // Pure emoji / punctuation / symbol bodies have no ASCII letters or digits.
  if (!/[A-Za-z0-9]/.test(trimmed)) return { kind: REPLY_KINDS.NOOP };

  const lower = trimmed.toLowerCase();
  const firstToken = lower.split(/\s+/)[0];

  if (YES_SET.has(firstToken)) return { kind: REPLY_KINDS.YES };
  if (NO_SET.has(firstToken)) return { kind: REPLY_KINDS.NO };

  if (firstToken === 'edit') {
    // Remainder after the 'edit' token, preserving original casing.
    const idx = trimmed.search(/\s/);
    const remainder = idx === -1 ? '' : trimmed.slice(idx + 1).trim();
    return { kind: REPLY_KINDS.EDIT, editText: remainder };
  }

  // Implicit EDIT: full trimmed body as correction text.
  return { kind: REPLY_KINDS.EDIT, editText: trimmed };
}

module.exports = { parseReply, REPLY_KINDS };
