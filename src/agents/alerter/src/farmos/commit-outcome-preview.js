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
  // Phase 48 Plan 04: seeding_session fan-out failure modes (handler returns these reasons)
  partial_commit_failed:           'a write partway through failed, nothing saved',
  session_name_exhausted:          'too many same-day session names already exist',
  session_fungi_type_term_missing: 'farmOS session taxonomy term missing',
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
  seeding:         'seeding',
  activity:        'activity',
  input:           'input log',
  observation:     'observation',
  harvest:         'harvest',
  // Phase 48 Plan 04: multi-parent inoc session (1 session asset + N children)
  seeding_session: 'Inoc session',
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

// Phase 45 Plan 06: disambiguator. When the farmer has multiple recent drafts,
// a bare "couldn't save observation" has no referent. Embed a {date} {what}
// hint built from draft_json so each ack maps to a unique real-world event.
//
// Date precedence: event_timestamp (real-world event date) > created_at (bot
// receipt). Format "MMM D" (e.g. "May 13") - human-readable, locale-stable,
// short. Sentinel timestamps from earlier extractor versions (1970-01-01,
// 2026-01-01T00:00:00 with no time) are rejected as not-real-dates.
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function fmtDate(d) {
  if (!d) return '';
  const dt = (d instanceof Date) ? d : new Date(d);
  if (Number.isNaN(dt.getTime())) return '';
  // Reject sentinel dates (1970, year-boundary midnight defaults)
  const y = dt.getUTCFullYear();
  if (y < 2000) return '';
  if (dt.getUTCMonth() === 0 && dt.getUTCDate() === 1 && dt.getUTCHours() === 0 && dt.getUTCMinutes() === 0) return '';
  return `${MONTH_NAMES[dt.getUTCMonth()]} ${dt.getUTCDate()}`;
}

// Pull short summary from draft_json. Priority:
//   1. name field (activity verbs like "relocate", "sterilize") - 1-2 words
//   2. first ~40 chars of notes field
// Returns null if nothing useful (caller renders a date-only or bare ack).
function summaryFromDraft(draftJson) {
  if (!draftJson || typeof draftJson !== 'object') return null;
  if (typeof draftJson.name === 'string' && draftJson.name.trim() !== '') {
    return draftJson.name.trim();
  }
  if (typeof draftJson.notes === 'string') {
    const n = draftJson.notes.trim();
    if (n === '') return null;
    if (n.length <= 40) return n;
    // Truncate at word boundary
    const cut = n.slice(0, 40);
    const lastSpace = cut.lastIndexOf(' ');
    return (lastSpace > 20 ? cut.slice(0, lastSpace) : cut) + '...';
  }
  return null;
}

// Pick the best date for the ack. Prefer draft_json.event_timestamp when it
// looks real, else fall back to created_at (bot receipt time). Real backdating
// is rare and short (hours, not months); if event_timestamp predates created_at
// by more than 30 days, it's an extractor hallucination (sentinel year-boundary
// values are a known artifact) — use created_at instead.
function pickBestDate(draftJson, createdAt) {
  const created = createdAt ? new Date(createdAt) : null;
  const evRaw = draftJson && draftJson.event_timestamp;
  if (evRaw) {
    const ev = new Date(evRaw);
    if (!Number.isNaN(ev.getTime())) {
      if (created && !Number.isNaN(created.getTime())) {
        const daysDelta = (created.getTime() - ev.getTime()) / 86400000;
        if (daysDelta > 30) return created; // event_timestamp is hallucinated
      }
      return ev;
    }
  }
  return created;
}

// Phase 48 Plan 04: seeding_session disambiguator. The session-shape draft has
// no name/notes (groups carry the data), so the generic name/notes path yields
// a bare label. Instead, build "{event_date} Inoc session (N blocks across M
// parents)" so the farmer's ack names WHAT was committed, not just WHEN.
function _seedingSessionDisambiguator(draftRow, label) {
  const dj = draftRow.draft_json || {};
  const groups = Array.isArray(dj.groups) ? dj.groups : [];
  let total = 0;
  for (const g of groups) {
    const names = g && g.child_block_names && g.child_block_names.value;
    const qty = g && g.qty && g.qty.value;
    total += Array.isArray(names) ? names.length : (typeof qty === 'number' ? qty : 0);
  }
  // event_date is "YYYY-MM-DD" (already human-readable, locale-stable).
  // Fall back to pickBestDate -> fmtDate for legacy event_timestamp-only drafts.
  const eventDate = (typeof dj.event_date === 'string' && dj.event_date.trim() !== '')
    ? dj.event_date.trim()
    : fmtDate(pickBestDate(dj, draftRow.created_at));
  const dateStr = eventDate || '';
  const parts = [];
  if (dateStr) parts.push(dateStr);
  parts.push(label);
  // "(N blocks across M parents)" -- omit if total=0 AND groups=0 (degenerate)
  if (total > 0 || groups.length > 0) {
    parts.push(`(${fmtNum(total)} blocks across ${fmtNum(groups.length)} parents)`);
  }
  return parts.join(' ');
}

// Disambiguator string: "May 13 observation (sterilize)" or "May 13 observation"
// or "observation (sterilize)" or bare "observation".
function buildDisambiguator(draftRow, label) {
  // Phase 48: seeding_session has a session-shape branch.
  const djType = draftRow.draft_json && draftRow.draft_json.type;
  if (draftRow.log_type === 'seeding_session' || djType === 'seeding_session') {
    return _seedingSessionDisambiguator(draftRow, label);
  }
  const date = fmtDate(pickBestDate(draftRow.draft_json, draftRow.created_at));
  const summary = summaryFromDraft(draftRow.draft_json);
  if (date && summary) return `${date} ${label} (${summary})`;
  if (date) return `${date} ${label}`;
  if (summary) return `${label} (${summary})`;
  return label;
}

/**
 * renderOutcomeAck(draftRow, options) -> string
 *
 * draftRow shape (subset):
 *   - sender_name?: string  (named address; if absent, no leading greeting)
 *   - log_type:    'seeding'|'activity'|'input'|'observation'|'harvest'
 *   - target?:     string|number|null  (asset name/id; null = farm-level)
 *   - draft_json?: object   (extraction; provides name + notes + event_timestamp for disambiguation)
 *   - created_at?: Date|string  (fallback date when event_timestamp absent)
 *
 * options:
 *   - outcome:    'success'|'failed'  (required)
 *   - reason?:    one of the 8 reason codes (required when outcome='failed')
 *   - farmosLink?: string  (success-with-target only; surfaced as "Open in farmOS: <link>")
 */
// Farmer-facing suffix appended to a success ack when one or more attachments
// failed to upload. Attachments are best-effort and never block the commit, but
// a dropped photo must not be swallowed behind a clean "saved" (no-silent-failure
// after farmer confirm). Accepts a count or the raw failed[] array; returns ''
// when nothing failed.
function attachmentNoteFor(attachmentsFailed) {
  const n = typeof attachmentsFailed === 'number'
    ? attachmentsFailed
    : (Array.isArray(attachmentsFailed) ? attachmentsFailed.length : 0);
  if (!n || n < 1) return '';
  const noun = n === 1 ? 'photo' : 'photos';
  const them = n === 1 ? 'it' : 'them';
  return ` Heads up: ${fmtNum(n)} ${noun} did not attach, you can re-send ${them}.`;
}

function renderOutcomeAck(draftRow, options) {
  const row = draftRow || {};
  const opts = options || {};
  const outcome = opts.outcome;
  const senderName = row.sender_name;
  const logType = row.log_type;
  // Hotfix 2026-05-24: row.target is never populated anywhere in the
  // codebase, so the "saved X for Y" branch below was dead code and every
  // successful commit fell through to "general farm note" even when an
  // asset WAS matched. Read asset_ref / qr_codes / source_block_refs from
  // draft_json as the canonical target source. Multi-target commits show
  // the first ref; downstream phases can refine if needed.
  function resolveTarget() {
    if (row.target != null && String(row.target).trim() !== '') return row.target;
    const dj = row.draft_json || {};
    if (typeof dj.asset_ref === 'string' && dj.asset_ref.trim() !== '' && dj.asset_ref !== '<UNKNOWN>') {
      return dj.asset_ref.trim();
    }
    if (Array.isArray(dj.qr_codes) && dj.qr_codes.length > 0 && typeof dj.qr_codes[0] === 'string') {
      return dj.qr_codes[0];
    }
    if (Array.isArray(dj.source_block_refs) && dj.source_block_refs.length > 0 && typeof dj.source_block_refs[0] === 'string') {
      return dj.source_block_refs[0];
    }
    if (Array.isArray(dj.source_qr_codes) && dj.source_qr_codes.length > 0 && typeof dj.source_qr_codes[0] === 'string') {
      return dj.source_qr_codes[0];
    }
    return null;
  }
  const target = resolveTarget();
  const label = labelFor(logType);
  const hi = greeting(senderName);
  const what = buildDisambiguator(row, label);

  if (outcome === 'success') {
    const attachNote = attachmentNoteFor(opts.attachmentsFailed);
    // Phase 48 Plan 04: seeding_session has no single target asset (1 session +
    // N children). The legacy no-target template ("as a general farm note since
    // I couldn't match a specific block") is misleading here -- the session
    // DID commit cleanly. Short-circuit with a clean session-shaped success.
    const djType = row.draft_json && row.draft_json.type;
    if (logType === 'seeding_session' || djType === 'seeding_session') {
      let body = `${hi}saved ${what}.`;
      if (typeof opts.farmosLink === 'string' && opts.farmosLink.trim() !== '') {
        body += ` Open in farmOS: ${opts.farmosLink.trim()}`;
      }
      return sanitizeFarmerText(body + attachNote);
    }
    if (target != null && String(target).trim() !== '') {
      const tgt = fmtTarget(target);
      let body = `${hi}saved ${what} for ${tgt}.`;
      if (typeof opts.farmosLink === 'string' && opts.farmosLink.trim() !== '') {
        body += ` Open in farmOS: ${opts.farmosLink.trim()}`;
      }
      return sanitizeFarmerText(body + attachNote);
    }
    // Farm-level no-target success. Embeds disambiguator.
    const body = `${hi}saved that ${what} as a general farm note since I couldn't match a specific block. Send EDIT to attach a block if you want.`;
    return sanitizeFarmerText(body + attachNote);
  }

  if (outcome === 'failed') {
    const phrase = reasonFor(opts.reason);
    const body = `${hi}about the ${what}: couldn't save it because ${phrase}. Send EDIT to fix or NO to drop.`;
    return sanitizeFarmerText(body);
  }

  // Unknown outcome: defensive fallback (should never reach in wired code).
  return sanitizeFarmerText(`${hi}commit reached an unknown terminal state.`);
}

module.exports = {
  renderOutcomeAck,
  reasonMap,
  reasonFor,
  // Phase 50 Plan-04: exported for reuse by receive-loop's numbered ask-back
  // and quote-resolved-to-terminal acks (Plan-06 disambiguator shape).
  buildDisambiguator,
  labelFor,
};
