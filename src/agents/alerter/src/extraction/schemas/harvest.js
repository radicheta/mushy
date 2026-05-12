'use strict';

// Phase 38 Plan 01: B7 harvest-log Zod schema.
// Required-field map (RESEARCH §8): harvest_batch_id, source_block_refs[] (>=1), qty_g, event_timestamp.
// Multi-parent source_block_refs is the C4 lineage anchor -- one harvest can pull from N blocks.

const { z } = require('zod');

const HarvestLog = z
  .object({
    type: z.literal('harvest'),
    harvest_batch_id: z.string().min(1),
    source_block_refs: z.array(z.string().min(1)).min(1),
    qty_g: z.number().positive(),
    event_timestamp: z.string().datetime(),
    notes: z.string().optional(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
  })
  .strict();

module.exports = { HarvestLog };
