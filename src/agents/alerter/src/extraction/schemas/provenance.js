'use strict';

// Phase 47 Plan 01: Provenance factory.
//
// EXT-01 anchor: every field that could come from multiple sources is wrapped in
// `{value, confidence, sources[]}` so cross-source disagreement is detectable at
// commit time. SOURCE_ENUM is a closed set; no string-typed escape hatch.
//
// Per CONTEXT.md Gray Area 2 lock: inline object-per-value (NOT a sparse
// conflict-only encoding). Sparse encoding is the fallback if token cost ever
// becomes a problem; not P0.

const { z } = require('zod');

const SOURCE_ENUM = z.enum([
  'audio',
  'paper_log_photo',
  'bag_label_photo',
  'text',
  'model_inference',
]);

// Provenanced(valueSchema) -> z.object({value, confidence, sources[]}).strict()
//
// sources[] must have min 1 entry (a value with no source is meaningless).
// confidence is bounded 0..1 to match per_field_confidence convention from
// Phase 38 Plan 01.
function Provenanced(valueSchema) {
  return z
    .object({
      value: valueSchema,
      confidence: z.number().min(0).max(1),
      sources: z.array(SOURCE_ENUM).min(1),
    })
    .strict();
}

module.exports = { Provenanced, SOURCE_ENUM };
