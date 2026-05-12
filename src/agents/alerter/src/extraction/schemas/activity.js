'use strict';

// Phase 38 Plan 01: B7 activity-log Zod schema.
// Required-field map (RESEARCH §8): name, asset_ref, event_timestamp.
// Locked name enum (CONTEXT D-04 + farmos 2026-05-11 lock):
//   sterilize, sterilize_failed, water, relocate, cold_shock, archive_spent, contam.

const { z } = require('zod');

const ACTIVITY_NAMES = ['sterilize', 'sterilize_failed', 'water', 'relocate', 'cold_shock', 'archive_spent', 'contam'];

const ActivityLog = z
  .object({
    type: z.literal('activity'),
    name: z.enum(ACTIVITY_NAMES),
    asset_ref: z.string().min(1),
    event_timestamp: z.string().datetime(),
    notes: z.string().optional(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
  })
  .strict();

module.exports = { ActivityLog, ACTIVITY_NAMES };
