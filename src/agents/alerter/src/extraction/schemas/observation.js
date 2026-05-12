'use strict';

// Phase 38 Plan 01: B7 observation-log Zod schema.
// Required-field map (RESEARCH §8): asset_ref, event_timestamp, AND at least one of state|notes.
//
// Zod note: discriminatedUnion requires pure z.object inputs (no .refine()).
// We expose ObservationLogBase (no refine) for the Draft union in schemas/index.js,
// and ObservationLog (with refine) for standalone validation.

const { z } = require('zod');

const ObservationLogBase = z
  .object({
    type: z.literal('observation'),
    asset_ref: z.string().min(1),
    state: z.string().optional(),
    notes: z.string().optional(),
    event_timestamp: z.string().datetime(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
  })
  .strict();

const hasStateOrNotes = (v) =>
  (v.state != null && v.state !== '') || (v.notes != null && v.notes !== '');

const ObservationLog = ObservationLogBase.refine(hasStateOrNotes, {
  message: 'observation requires state or notes',
  path: ['state'],
});

module.exports = { ObservationLog, ObservationLogBase, hasStateOrNotes };
