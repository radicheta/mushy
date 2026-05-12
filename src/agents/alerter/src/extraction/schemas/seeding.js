'use strict';

// Phase 38 Plan 01: B7 seeding-log Zod schema.
// Required-field map (RESEARCH §8): species, block_name, qty, event_timestamp.
// B5 block_name regex (CONTEXT D-04, RESEARCH §1.3): {YYMMDD}_{SPECIES3}_{SEQ}.
// .strict() is the EXT-01 anchor: no off-schema fields from the LLM.

const { z } = require('zod');

const BLOCK_NAME_RE = /^[0-9]{6}_[A-Z]{3}_[0-9]+$/;

const SeedingLog = z
  .object({
    type: z.literal('seeding'),
    species: z.string().min(1),
    block_name: z.string().regex(BLOCK_NAME_RE, 'B5 block_name'),
    qty: z.number().int().positive(),
    event_timestamp: z.string().datetime(),
    notes: z.string().optional(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
  })
  .strict();

module.exports = { SeedingLog, BLOCK_NAME_RE };
