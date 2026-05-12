'use strict';

// Phase 38 Plan 01: B7 input-log Zod schema.
// Required-field map (RESEARCH §8): recipe_lot, asset_ref, event_timestamp.

const { z } = require('zod');

const InputLog = z
  .object({
    type: z.literal('input'),
    recipe_lot: z.string().min(1),
    asset_ref: z.string().min(1),
    event_timestamp: z.string().datetime(),
    notes: z.string().optional(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
  })
  .strict();

module.exports = { InputLog };
