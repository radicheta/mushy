'use strict';

// Phase 43 Plan 01: router-side normalizer for extractor->commit shape translation.
//
// normalize(draft) is a PURE function: returns a NEW draft with draft_json
// reshaped to commit-shape per log_type. Does NOT mutate its input.
//
// Idempotent by design: each transform is guarded so that if the commit-shape
// marker is already present (qr_codes, timestamp number, activity_subtype, etc.),
// the transform is skipped. This satisfies SCHEMA-03 and means that once
// commit-router.js wires in normalize(), all existing commit-shape test fixtures
// continue to pass through unchanged.
//
// Decisions applied here (from 43-CONTEXT.md):
//   D-01: pure function, new draft returned, no mutation
//   D-03: common transforms (event_timestamp->timestamp, asset_ref->qr_codes)
//   D-04: per-log_type switch (follows audit §3 sketch)
//   D-05: harvest source_block_refs -> source_qr_codes verbatim (no B5 regex filter)
//   D-09: input recipe_lot PREPENDS to notes (not append); commit-input's own
//         ingredients serializer chains after this
//   D-11: seeding batch_name vs parent_batch_name left distinct (no fold)
//   D-12: harvest qty_g -> bags single-bag synth only when qty_g present AND bags absent

function normalize(draft) {
  const dj = draft.draft_json || {};
  // Shallow copy -- no mutation of input.
  const out = Object.assign({}, dj);

  // ------------------------------------------------------------------
  // Common transforms (all log_types)
  // ------------------------------------------------------------------

  // event_timestamp (ISO string) -> timestamp (unix seconds, floor).
  // Guard: skip if timestamp already a number (idempotency).
  if (typeof out.timestamp !== 'number' && typeof out.event_timestamp === 'string') {
    const ms = Date.parse(out.event_timestamp);
    if (Number.isFinite(ms)) out.timestamp = Math.floor(ms / 1000);
  }

  // asset_ref (string) -> qr_codes (string[]). Filter <UNKNOWN> sentinel.
  // Guard: skip if qr_codes already an array (idempotency).
  if (!Array.isArray(out.qr_codes) && typeof out.asset_ref === 'string') {
    out.qr_codes = out.asset_ref === '<UNKNOWN>' ? [] : [out.asset_ref];
  }

  // ------------------------------------------------------------------
  // Per-log_type transforms
  // ------------------------------------------------------------------
  switch (draft.log_type) {
    case 'activity':
      // name -> activity_subtype.
      // Guard: skip if activity_subtype already present (idempotency).
      if (!out.activity_subtype && typeof out.name === 'string') {
        out.activity_subtype = out.name;
      }
      break;

    case 'harvest':
      // source_block_refs -> source_qr_codes (verbatim rename, D-05: no regex filter).
      // Guard: skip if source_qr_codes already an array (idempotency).
      if (!Array.isArray(out.source_qr_codes) && Array.isArray(out.source_block_refs)) {
        out.source_qr_codes = out.source_block_refs;
      }
      // harvest_batch_id -> harvest_batch_name.
      // Guard: skip if harvest_batch_name already present (idempotency).
      if (!out.harvest_batch_name && typeof out.harvest_batch_id === 'string') {
        out.harvest_batch_name = out.harvest_batch_id;
      }
      // qty_g -> bags: single synthesized unnamed bag (D-12).
      // Guard: only when bags absent AND qty_g present (idempotency).
      if (!Array.isArray(out.bags) && typeof out.qty_g === 'number') {
        out.bags = [{ weight_grams: out.qty_g }];
      }
      break;

    case 'seeding':
      // species -> species_code (only if species_code absent, D-11 note: batch_name and
      // parent_batch_name are left distinct -- no fold).
      // Guard: skip if species_code already present (idempotency).
      if (!out.species_code && typeof out.species === 'string') {
        out.species_code = out.species;
      }
      // batch_name and parent_batch_name: left as-is per D-11.
      break;

    case 'input':
      // recipe_lot PREPENDED to notes as "recipe_lot: <value>\n" (D-09).
      // This runs before commit-input.js's own ingredients-into-notes serializer
      // (commit-input.js:25), so final notes order is:
      //   recipe_lot: RB-2026-05
      //   <existing notes if any>
      //   Ingredients:
      //   - oat 1kg
      //   ...
      // Guard: skip if recipe_lot field absent (idempotency for commit-shape which
      // has no recipe_lot field -- the field is consumed and removed from the
      // extractor-shape, so the guard naturally fires on pass-through).
      if (typeof out.recipe_lot === 'string') {
        out.notes = 'recipe_lot: ' + out.recipe_lot + (out.notes ? '\n' + out.notes : '');
      }
      break;

    case 'observation':
      // state appended to notes as "state: <value>" (audit §3 sketch).
      // Guard: skip if state field absent (idempotency for commit-shape which has
      // no state field after normalization).
      if (typeof out.state === 'string' && out.state !== '') {
        out.notes = out.notes ? (out.notes + '\nstate: ' + out.state) : ('state: ' + out.state);
      }
      break;

    // No transforms needed for unknown log_types -- return as-is.
    default:
      break;
  }

  return Object.assign({}, draft, { draft_json: out });
}

module.exports = { normalize };
