'use strict';

// Phase 38 Plan 01: B7 seeding-log Zod schema.
// Required-field map (RESEARCH §8): species, block_name, qty, event_timestamp.
// B5 block_name regex (CONTEXT D-04, RESEARCH §1.3): {YYMMDD}_{SPECIES3}_{SEQ}.
// .strict() is the EXT-01 anchor: no off-schema fields from the LLM.

const { z } = require('zod');

// B5 block_name = YYMMDD_SPECIES_SEQ. SPECIES is 2-4 uppercase letters in production
// (DT and other 2-letter codes are real; CONTEXT D-04's "{SPECIES3}" was inaccurate).
const BLOCK_NAME_RE = /^[0-9]{6}_[A-Z]{2,4}_[0-9]+$/;

// parent_batch_name (lineage C4): the inoculation source — the parent block/batch
// this individuation event consumes. May be canonical (YYMMDD_SPECIES3_SEQ) OR a
// page-shorthand decoded by the LLM (e.g. "0627-2" -> "250627_DT_2" using corpus
// context + species column). Optional because not every page records lineage.
const SeedingLog = z
  .object({
    type: z.literal('seeding'),
    species: z.string().min(1),
    block_name: z.string().regex(BLOCK_NAME_RE, 'B5 block_name'),
    qty: z.number().int().positive(),
    event_timestamp: z.string().datetime(),
    parent_batch_name: z.string().min(1).optional(),
    notes: z.string().optional(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
  })
  .strict();

module.exports = { SeedingLog, BLOCK_NAME_RE };
