'use strict';

// Phase 38 Plan 01: Discriminated-union Draft schema + Anthropic-ready JSON Schema.
//
// EXT-01 anchor: DRAFT_JSON_SCHEMA is the value passed as tools[0].input_schema
// to the Anthropic Messages API in Plan 03. zod-to-json-schema emits draft-7 JSON
// Schema with `definitions` + `$ref` when a name arg is supplied; Anthropic accepts
// this shape as long as it is a single plain JSON object.
//
// Note: ObservationLogBase (no .refine()) is used in the union because Zod's
// discriminatedUnion only accepts pure z.object schemas. The state-or-notes rule
// is reapplied by callers via the standalone ObservationLog export when needed.

const { z } = require('zod');
const { zodToJsonSchema } = require('zod-to-json-schema');

const { SeedingLog } = require('./seeding');
const { ActivityLog } = require('./activity');
const { InputLog } = require('./input');
const { ObservationLog, ObservationLogBase } = require('./observation');
const { HarvestLog } = require('./harvest');

const Draft = z.discriminatedUnion('type', [
  SeedingLog,
  ActivityLog,
  InputLog,
  ObservationLogBase,
  HarvestLog,
]);

const DRAFT_JSON_SCHEMA = zodToJsonSchema(Draft, 'Draft');

const LOG_TYPES = Object.freeze(['seeding', 'activity', 'input', 'observation', 'harvest']);

// Phase 38 Plan 08: SUBMISSION wrapper, multi-draft shape.
// Anthropic submit_extraction tool input = {drafts: [{draft, per_field_confidence}],
// continuity, continuity_reason}. Multi-draft because a single page (e.g. a 21-block
// individuation page from mushdatadump) holds many distinct events that each need
// their own farmOS asset. Continuity is per-call (the whole capture is start_new /
// append / replace against the in-flight context).
const DraftSubmission = z
  .object({
    draft: Draft,
    per_field_confidence: z.record(z.string(), z.number().min(0).max(1)),
  })
  .strict();

const Submission = z
  .object({
    drafts: z.array(DraftSubmission).min(1),
    continuity: z.enum(['append', 'replace', 'start_new']),
    continuity_reason: z.string().min(1),
  })
  .strict();

const SUBMISSION_JSON_SCHEMA = zodToJsonSchema(Submission, 'Submission');

module.exports = {
  Draft,
  DRAFT_JSON_SCHEMA,
  DraftSubmission,
  Submission,
  SUBMISSION_JSON_SCHEMA,
  LOG_TYPES,
  SeedingLog,
  ActivityLog,
  InputLog,
  ObservationLog,
  ObservationLogBase,
  HarvestLog,
};
