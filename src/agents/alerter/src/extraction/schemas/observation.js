'use strict';

// Phase 38 Plan 01: B7 observation-log Zod schema.
// Required-field map (RESEARCH §8): asset_ref, event_timestamp, AND at least one of state|notes.
// state/notes "at-least-one" enforced via .refine() since Zod cannot express it structurally.

const { z } = require('zod');

const ObservationLog = z
  .object({
    type: z.literal('observation'),
    asset_ref: z.string().min(1),
    state: z.string().optional(),
    notes: z.string().optional(),
    event_timestamp: z.string().datetime(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
  })
  .strict()
  .refine((v) => (v.state != null && v.state !== '') || (v.notes != null && v.notes !== ''), {
    message: 'observation requires state or notes',
    path: ['state'],
  });

module.exports = { ObservationLog };
