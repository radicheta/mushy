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

// Phase 38 Plan 03 Task 2: SUBMISSION wrapper.
// Anthropic submit_extraction tool input = {draft, continuity, continuity_reason,
// per_field_confidence}. Keeps Plan 01's Draft schema pure (no _meta hacks) while
// the wrapper carries the continuity decision the LLM makes per CONTEXT D-01.
const Submission = z
  .object({
    draft: Draft,
    continuity: z.enum(['append', 'replace', 'start_new']),
    continuity_reason: z.string().min(1),
    per_field_confidence: z.record(z.string(), z.number().min(0).max(1)),
  })
  .strict();

const SUBMISSION_JSON_SCHEMA = zodToJsonSchema(Submission, 'Submission');

module.exports = {
  Draft,
  DRAFT_JSON_SCHEMA,
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
