'use strict';

// Phase 47 Plan 01: SeedingSession + SeedingSessionGroup + ConflictEntry schemas.
//
// EXT-01 anchor: .strict() on every nested object so the LLM cannot smuggle
// off-schema fields. Legacy SeedingLog (per-bag flat shape) stays; SeedingSession
// is a new top-level discriminated-union member for the canonical multi-parent
// batch shape (~80% of real inoc sessions per [[multi-parent-inoc-batch]]).
//
// Per CONTEXT.md:
//   Gray Area 1 lock -- new top-level type, not per-bag drafts.
//   Gray Area 2 lock -- inline {value, confidence, sources[]} per field.
//   Gray Area 3 lock -- 'NEEDS_SEQ' sentinel + needs_input='starting_seq'.
//   Gray Area 4 lock -- conflicts[] is internal forensics; never shown to farmer.

const { z } = require('zod');

const { Provenanced, SOURCE_ENUM } = require('./provenance');
const { BLOCK_NAME_RE } = require('./seeding');

// Re-exported so Phase 47-02..05 and Phase 48 consumers can require it from one
// place without reaching back into the legacy seeding.js.
// (Note: re-export only; do not duplicate the regex itself.)

// Child block-name string is either a canonical B5 block_name OR the sentinel
// literal 'NEEDS_SEQ' (Gray Area 3 lock). Mixed arrays are allowed per the
// behavior spec: a session can have some bags with confirmed SEQ from the photo
// and others pending farmer ask-back.
const ChildBlockNameOrSentinel = z.union([
  z.literal('NEEDS_SEQ'),
  z.string().regex(BLOCK_NAME_RE, 'B5 block_name'),
]);

// Parent reference: a canonical block_name OR the sentinel 'NO_PARENT' when the
// extractor cannot infer (e.g. fresh-grain inoc with no parent batch). Held
// permissive (z.string().min(1)) so page-shorthand decodes (mirrors SeedingLog's
// parent_batch_name) are accepted; downstream Phase 48 normalizes.
const ParentRef = z.string().min(1);

const SeedingSessionGroup = z
  .object({
    parent: Provenanced(ParentRef),
    species: Provenanced(z.string().regex(/^[A-Z]{2,4}$/)),
    qty: Provenanced(z.number().int().positive()),
    child_block_names: Provenanced(z.array(ChildBlockNameOrSentinel).min(1)),
  })
  .strict();

// ConflictEntry: when two sources disagree on a field, the canonical resolution
// (photo wins, per Gray Area 4) is applied silently and the disagreement is
// captured here for forensics. NEVER surfaced to the farmer.
const ConflictEntry = z
  .object({
    path: z.string().min(1),
    candidates: z
      .array(
        z
          .object({
            value: z.unknown(),
            source: SOURCE_ENUM,
            confidence: z.number().min(0).max(1),
          })
          .strict()
      )
      .min(2),
    resolution: z.enum([
      'photo_wins_implicit',
      'ask_back_required',
      'accepted_consensus',
    ]),
  })
  .strict();

const SeedingSession = z
  .object({
    type: z.literal('seeding_session'),
    event_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'YYYY-MM-DD'),
    groups: z.array(SeedingSessionGroup).min(1),
    needs_input: z.enum(['starting_seq']).optional(),
    conflicts: z.array(ConflictEntry).optional(),
    notes: z.string().optional(),
  })
  .strict();

module.exports = {
  SeedingSession,
  SeedingSessionGroup,
  ConflictEntry,
  ChildBlockNameOrSentinel,
  BLOCK_NAME_RE,
};
