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
// Phase 47 Plan 01: new top-level type for multi-parent groups-shape inoc.
// Legacy SeedingLog stays for single-bag-no-session contexts (rare).
const {
  SeedingSession,
  SeedingSessionGroup,
  ConflictEntry,
} = require('./seeding-session');
const { Provenanced, SOURCE_ENUM } = require('./provenance');

const Draft = z.discriminatedUnion('type', [
  SeedingLog,
  ActivityLog,
  InputLog,
  ObservationLogBase,
  HarvestLog,
  SeedingSession,
]);

const DRAFT_JSON_SCHEMA = zodToJsonSchema(Draft, 'Draft');

const LOG_TYPES = Object.freeze([
  'seeding',
  'activity',
  'input',
  'observation',
  'harvest',
  'seeding_session',
]);

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

// Phase 53 BACK-03: optional capture_kind classifier on the extraction
// envelope. Allowed values: paper_log | physical_object_photo | voice_note |
// text. Nullable + optional so existing/partial-output callers keep
// validating (back-compat lock per D-BACK-03). Routing (BACK-02) does NOT
// consume this field today -- it is supportive analytics metadata + a hook
// for future per-capture-kind refinements.
const CAPTURE_KIND_ENUM = z.enum(['paper_log', 'physical_object_photo', 'voice_note', 'text']);

const Submission = z
  .object({
    drafts: z.array(DraftSubmission).min(1),
    continuity: z.enum(['append', 'replace', 'start_new']),
    continuity_reason: z.string().min(1),
    capture_kind: CAPTURE_KIND_ENUM.nullable().optional(),
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
  SeedingSession,
  SeedingSessionGroup,
  ConflictEntry,
  Provenanced,
  SOURCE_ENUM,
  CAPTURE_KIND_ENUM,
};
