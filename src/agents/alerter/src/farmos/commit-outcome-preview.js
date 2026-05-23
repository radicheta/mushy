'use strict';

// Phase 45 Plan 02: farmer-facing ack renderer for terminal states of the
// confirm/commit state machine (commit_success T4, commit_failed T6).
//
// Pure functions, no I/O. Imported by Plan 04 wiring (commit-watchdog ->
// confirmOutbound.dispatch -> renderOutcomeAck).
//
// Style locks (CONTEXT.md decisions + memory):
//   - no em-dashes (sanitizeFarmerText sweep applied last)
//   - all numeric values via fmtNum (1 decimal, strip trailing .0)
//   - named address ("Hi {sender_name}, ...") when sender_name present
//   - 8-code reason -> farmer-vocab map (English-only this phase)

const { sanitizeFarmerText } = require('../extraction/preview-builder');
const { fmtNum } = require('../message');

// 8-code reason -> farmer-vocab map. Locked in 45-CONTEXT.md decisions.
// Unknown codes fall back to generic_validation_error phrasing via reasonFor().
const reasonMap = Object.freeze({
  observation_requires_target:  "couldn't match a block",
  no_target_asset_for_activity: 'no asset to attach this activity to',
  asset_not_found:              "couldn't find that asset",
  duplicate_log:                'already logged',
  farmos_unreachable:           'farm server down',
  schema_invalid:               'data format issue',
  taxonomy_term_missing:        'missing a taxonomy term',
  generic_validation_error:     'data validation failed',
});

function reasonFor(code) {
  if (typeof code === 'string' && Object.prototype.hasOwnProperty.call(reasonMap, code)) {
    return reasonMap[code];
  }
  return reasonMap.generic_validation_error;
}

// log_type -> farmer-facing label. Verified against existing convention in
// confirm/preview.js (uses "seeding", "activity", etc. lowercased).
const LOG_TYPE_LABEL = Object.freeze({
  seeding:     'seeding',
  activity:    'activity',
  input:       'input log',
  observation: 'observation',
  harvest:     'harvest',
});

function labelFor(logType) {
  if (typeof logType === 'string' && LOG_TYPE_LABEL[logType]) return LOG_TYPE_LABEL[logType];
  return 'log';
}

function greeting(senderName) {
  if (typeof senderName !== 'string') return '';
  const trimmed = senderName.trim();
  if (trimmed === '') return '';
  return `Hi ${trimmed}, `;
}

// Format target. Numeric targets (rare but possible: qty-only blocks) go
// through fmtNum. String targets pass through unchanged (sanitization at end).
function fmtTarget(target) {
  if (target == null) return '';
  if (typeof target === 'number') return fmtNum(target);
  return String(target);
}

/**
 * renderOutcomeAck(draftRow, options) -> string
 *
 * draftRow shape (subset):
 *   - sender_name?: string  (named address; if absent, no leading greeting)
 *   - log_type:    'seeding'|'activity'|'input'|'observation'|'harvest'
 *   - target?:     string|number|null  (asset name/id; null = farm-level)
 *
 * options:
 *   - outcome:    'success'|'failed'  (required)
 *   - reason?:    one of the 8 reason codes (required when outcome='failed')
 *   - farmosLink?: string  (success-with-target only; surfaced as "Open in farmOS: <link>")
 */
function renderOutcomeAck(draftRow, options) {
  const row = draftRow || {};
  const opts = options || {};
  const outcome = opts.outcome;
  const senderName = row.sender_name;
  const logType = row.log_type;
  const target = row.target;
  const label = labelFor(logType);
  const hi = greeting(senderName);

  if (outcome === 'success') {
    if (target != null && String(target).trim() !== '') {
      const tgt = fmtTarget(target);
      let body = `${hi}saved ${label} for ${tgt}.`;
      if (typeof opts.farmosLink === 'string' && opts.farmosLink.trim() !== '') {
        body += ` Open in farmOS: ${opts.farmosLink.trim()}`;
      }
      return sanitizeFarmerText(body);
    }
    // Farm-level no-target success. 3 minor variants per CONTEXT.md
    // (observation / activity / input). Other log_types fall back to the
    // observation phrasing since seeding/harvest realistically always have a
    // target.
    let noTargetBody;
    if (logType === 'activity') {
      noTargetBody = `${hi}saved that activity as a general farm note since I couldn't match a specific block. Send EDIT to attach a block if you want.`;
    } else if (logType === 'input') {
      noTargetBody = `${hi}saved that input as a general farm note since I couldn't match a specific block. Send EDIT to attach a block if you want.`;
    } else {
      // observation (default farm-level variant)
      noTargetBody = `${hi}saved that observation as a general farm note since I couldn't match a specific block. Send EDIT to attach a block if you want.`;
    }
    return sanitizeFarmerText(noTargetBody);
  }

  if (outcome === 'failed') {
    const phrase = reasonFor(opts.reason);
    const body = `${hi}couldn't save ${label}: ${phrase}. Send EDIT to fix or NO to drop.`;
    return sanitizeFarmerText(body);
  }

  // Unknown outcome: defensive fallback (should never reach in wired code).
  return sanitizeFarmerText(`${hi}commit reached an unknown terminal state.`);
}

module.exports = {
  renderOutcomeAck,
  reasonMap,
  reasonFor,
};
