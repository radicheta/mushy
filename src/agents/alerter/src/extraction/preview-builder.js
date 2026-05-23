'use strict';

// Phase 38 Plan 04 Task 3: farmer-facing preview rendering for the ask-back
// flow. Honors D-04 ask-back shape (one-line top question + full draft preview
// with [?] markers) and the project memory rules:
//   - no em-dashes anywhere in farmer-facing text (sanitizeFarmerText sweep)
//   - all numeric values run through fmtNum (round to 1 decimal, strip .0)
//   - neutral language (no "operator" as a referent to a human)

const { fmtNum } = require('../message');

// Top-question phrasing keyed by `${draftType}.${fieldName}`. Missing-field
// templates use the .miss suffix; low-confidence templates use .low. Fall back
// to a generic confirm prompt when no template matches.
const TOP_Q_TEMPLATES = Object.freeze({
  // Seeding
  'seeding.species.miss':         'Which species is this seeding? (SHI, OYS, LIO, ...)',
  'seeding.species.low':          'Can you confirm the species for this seeding? I am not fully sure.',
  'seeding.block_name.miss':      "What's the block name? Looking for the YYMMDD_SPECIES_SEQ form (like 260512_SHI_4).",
  'seeding.block_name.low':       'Can you confirm the block name? Format: YYMMDD_SPECIES_SEQ (like 260512_SHI_4).',
  'seeding.qty.miss':             'How many blocks were seeded?',
  'seeding.qty.low':              'Can you confirm the quantity for this seeding?',
  'seeding.event_timestamp.miss': 'What time did you do this seeding?',
  // Activity
  'activity.name.miss':           'What activity was this? (sterilize, water, relocate, cold_shock, archive_spent, contam)',
  'activity.asset_ref.miss':      'Which block or batch was this for?',
  // Input
  'input.recipe_lot.miss':        'Which recipe lot was used?',
  'input.asset_ref.miss':         'Which block or batch did this input go to?',
  // Observation
  'observation.asset_ref.miss':   'Which block or batch are you observing?',
  'observation.state_or_notes.miss': 'What did you observe? A state (pinning, fruiting, contam, ...) or a short note works.',
  // Harvest
  'harvest.harvest_batch_id.miss':  'What is the harvest batch id?',
  'harvest.source_block_refs.miss': 'Which source blocks did this harvest come from?',
  'harvest.qty_g.miss':             'How many grams were harvested?',
});

/**
 * sanitizeFarmerText(s) -> string
 *
 * Strip em-dashes (project memory: feedback_no_em_dashes_in_artifacts). Convert
 * en-dashes to ASCII hyphens for safety. Idempotent.
 */
function sanitizeFarmerText(s) {
  if (s == null) return '';
  // Use \u escapes so this source file itself stays ASCII-clean (memory rule
  // sweep + memory: feedback_no_em_dashes_in_artifacts.md).
  return String(s)
    .replace(/\u2014/g, '')   // em-dash removed entirely
    .replace(/\u2013/g, '-'); // en-dash to ASCII hyphen
}

/**
 * buildTopQuestion({missingFields, lowConfFields, draftType}) -> string
 *
 * Priority: first missing required field > first low-confidence field. Returns
 * a single-line string. Falls back to a generic confirm prompt when no
 * template matches.
 */
function buildTopQuestion({ missingFields, lowConfFields, draftType }) {
  const missing = Array.isArray(missingFields) ? missingFields : [];
  const lowConf = Array.isArray(lowConfFields) ? lowConfFields : [];

  if (missing.length > 0) {
    const f = missing[0];
    const key = `${draftType}.${f}.miss`;
    const tmpl = TOP_Q_TEMPLATES[key];
    if (tmpl) return sanitizeFarmerText(tmpl);
    return sanitizeFarmerText(`Can you confirm the ${f} for this ${draftType}?`);
  }

  if (lowConf.length > 0) {
    const f = lowConf[0];
    const key = `${draftType}.${f}.low`;
    const tmpl = TOP_Q_TEMPLATES[key];
    if (tmpl) return sanitizeFarmerText(tmpl);
    return sanitizeFarmerText(`Can you double-check the ${f} for this ${draftType}?`);
  }

  return sanitizeFarmerText(`Does this ${draftType} look right?`);
}

function renderValue(v) {
  if (v == null) return '[?]';
  if (Array.isArray(v)) {
    return `[${v.map((x) => renderScalar(x)).join(', ')}]`;
  }
  return renderScalar(v);
}

function renderScalar(v) {
  if (v == null) return '[?]';
  if (typeof v === 'number') return fmtNum(v);
  if (typeof v === 'string') {
    // Datetime: trim millisecond fraction. ISO shape YYYY-MM-DDTHH:MM:SS(.SSS)Z.
    const m = v.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+\-]\d{2}:?\d{2})$/);
    if (m) return `${m[1]}Z`;
    return v;
  }
  return String(v);
}

function classifyField(field, draft, perFieldConfidence, threshold) {
  // observation state_or_notes is a synthetic field -- never directly present.
  if (field === 'state_or_notes') {
    const has = (draft.state != null && draft.state !== '') ||
                (draft.notes != null && draft.notes !== '');
    if (!has) return 'missing';
    return 'ok';
  }
  const v = draft[field];
  if (v == null || (Array.isArray(v) && v.length === 0) ||
      (typeof v === 'string' && v.trim() === '')) {
    return 'missing';
  }
  const c = perFieldConfidence && perFieldConfidence[field];
  if (typeof c === 'number' && c < threshold) return 'low_conf';
  return 'ok';
}

/**
 * buildPreview({draft, perFieldConfidence, threshold, requiredFields}) -> string
 *
 * Returns a multi-line farmer-facing string:
 *   line 1: top question (the single most-blocking ambiguity)
 *   line 2: blank
 *   line 3+: draft body, one `field: value` (or `field: [?]`) per line.
 *
 * Numbers are formatted via fmtNum. The full output is run through
 * sanitizeFarmerText before returning.
 */
function buildPreview({ draft, perFieldConfidence, threshold, requiredFields }) {
  // Phase 47-04: seeding_session placeholder branch. Early-return before the
  // flat-field renderer because the groups-shape provenanced body does not fit
  // the legacy `field: value` rendering. Phase 48 ships the production
  // group-by-parent table; this branch is the safety net so previewBuilder
  // never crashes or returns empty on a seeding_session draft.
  //
  // CRITICAL: this branch NEVER reads or renders draft.conflicts[] -- per
  // CONTEXT.md Gray Area 4 lock, OCR-vs-Whisper conflicts are forensics-only
  // and must never surface to the farmer.
  if (draft && draft.type === 'seeding_session') {
    return buildSeedingSessionPlaceholder(draft);
  }

  const conf = perFieldConfidence || {};
  const required = Array.isArray(requiredFields) ? requiredFields : [];

  // Find missing + low-confidence fields for the top question.
  const missingFields = [];
  const lowConfFields = [];
  for (const f of required) {
    const cls = classifyField(f, draft, conf, threshold);
    if (cls === 'missing') missingFields.push(f);
    if (cls === 'low_conf') lowConfFields.push(f);
  }
  // Also surface low-confidence optional fields the LLM emitted.
  for (const [field, c] of Object.entries(conf)) {
    if (required.includes(field)) continue;
    if (typeof c === 'number' && c < threshold &&
        classifyField(field, draft, conf, threshold) !== 'missing') {
      lowConfFields.push(field);
    }
  }

  const topQ = buildTopQuestion({
    missingFields,
    lowConfFields,
    draftType: draft && draft.type,
  });

  // Build the body. Field order: type first, then required fields in order,
  // then any remaining draft keys (stable insertion order).
  const seen = new Set(['type']);
  const lines = [];
  lines.push(`type: ${renderScalar(draft.type)}`);
  for (const f of required) {
    if (f === 'state_or_notes') continue; // synthetic -- skip in body listing
    seen.add(f);
    const cls = classifyField(f, draft, conf, threshold);
    if (cls === 'missing' || cls === 'low_conf') {
      lines.push(`${f}: [?]`);
    } else {
      lines.push(`${f}: ${renderValue(draft[f])}`);
    }
  }
  for (const k of Object.keys(draft)) {
    if (seen.has(k)) continue;
    if (k === 'confidence' || k === 'per_field_confidence') continue;
    const cls = classifyField(k, draft, conf, threshold);
    if (cls === 'low_conf') {
      lines.push(`${k}: [?]`);
    } else {
      lines.push(`${k}: ${renderValue(draft[k])}`);
    }
  }

  // Observation: if state and notes both missing, surface the synthetic marker.
  if (draft && draft.type === 'observation') {
    const hasState = draft.state != null && draft.state !== '';
    const hasNotes = draft.notes != null && draft.notes !== '';
    if (!hasState && !hasNotes) {
      lines.push('state_or_notes: [?]');
    }
  }

  const out = `${topQ}\n\n${lines.join('\n')}`;
  return sanitizeFarmerText(out);
}

/**
 * buildSeedingSessionPlaceholder(draft) -> string
 *
 * Phase 47-04 minimal placeholder for groups-shape inoc drafts. Production
 * group-by-parent rendering ships in Phase 48. Output shape:
 *
 *   Line 1: "{N} blocks across {G} groups for {event_date}"
 *   Line 2: (blank)
 *   Line 3: when needs_input==='starting_seq':
 *             "Awaiting block-number to start at."
 *           otherwise:
 *             "Group-by-parent preview coming in Phase 48."
 *   Line 4+: one line per group: "{species} x {qty} from {parent}"
 *           where parent.value === 'NO_PARENT' renders as "no parent recorded".
 *
 * Numbers go through fmtNum; output is sanitized for em-dashes. NEVER touches
 * draft.conflicts[] (Gray Area 4 lock).
 */
function buildSeedingSessionPlaceholder(draft) {
  const groups = Array.isArray(draft.groups) ? draft.groups : [];
  const groupCount = groups.length;

  // Total child count: prefer child_block_names.value.length when array is
  // present (more authoritative than qty.value when a partial-photo session
  // has populated names); otherwise fall back to qty.value.
  let totalChildren = 0;
  for (const g of groups) {
    const names = g && g.child_block_names && g.child_block_names.value;
    if (Array.isArray(names)) {
      totalChildren += names.length;
    } else {
      const qv = g && g.qty && g.qty.value;
      if (typeof qv === 'number') totalChildren += qv;
    }
  }

  const eventDate = draft.event_date || '[?]';

  const headline = `${fmtNum(totalChildren)} blocks across ${fmtNum(groupCount)} groups for ${eventDate}`;

  const phase48Marker = draft.needs_input === 'starting_seq'
    ? 'Awaiting block-number to start at.'
    : 'Group-by-parent preview coming in Phase 48.';

  const groupLines = groups.map((g) => {
    const species = (g && g.species && g.species.value != null)
      ? renderScalar(g.species.value) : '[?]';
    const qty = (g && g.qty && g.qty.value != null)
      ? renderScalar(g.qty.value) : '[?]';
    const parentVal = g && g.parent && g.parent.value;
    const parent = parentVal === 'NO_PARENT'
      ? 'no parent recorded'
      : (parentVal != null ? renderScalar(parentVal) : '[?]');
    return `${species} x ${qty} from ${parent}`;
  });

  const out = [headline, '', phase48Marker, ...groupLines].join('\n');
  return sanitizeFarmerText(out);
}

module.exports = {
  buildPreview,
  buildTopQuestion,
  sanitizeFarmerText,
  TOP_Q_TEMPLATES,
};
