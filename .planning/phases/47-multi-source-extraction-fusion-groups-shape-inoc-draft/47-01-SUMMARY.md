---
phase: 47-multi-source-extraction-fusion-groups-shape-inoc-draft
plan: 01
subsystem: extraction
tags: [schemas, zod, discriminated-union, provenance, inoc]
dependency_graph:
  requires: [Phase 38 Plan 01 SeedingLog + Draft discriminated-union foundation]
  provides:
    - "SeedingSession Zod schema (top-level Draft member)"
    - "SeedingSessionGroup Zod schema"
    - "ConflictEntry Zod schema (audit-only, never farmer-rendered)"
    - "Provenanced<T> factory + SOURCE_ENUM"
    - "LOG_TYPES extended to include 'seeding_session'"
    - "REQUIRED_FIELDS.seeding_session = ['event_date','groups']"
  affects:
    - "Phase 47 plans 02-05 (system prompt, pipeline, preview, integration)"
    - "Phase 48 commit fan-out (consumes SeedingSession draft)"
tech_stack:
  added: []
  patterns:
    - "Discriminated-union extension via additional z.object member (additive, non-breaking)"
    - "Provenanced<T> factory for inline {value, confidence, sources[]} per field"
    - "Sentinel-literal-in-union pattern (z.union([z.literal('NEEDS_SEQ'), z.string().regex(BLOCK_NAME_RE)])) for ask-back deferral"
key_files:
  created:
    - src/agents/alerter/src/extraction/schemas/provenance.js
    - src/agents/alerter/src/extraction/schemas/seeding-session.js
    - src/agents/alerter/test/extraction/seeding-session.test.js
  modified:
    - src/agents/alerter/src/extraction/schemas/index.js
    - src/agents/alerter/src/extraction/state-machine.js
    - src/agents/alerter/test/extraction/schemas.test.js
decisions:
  - "child_block_names value type is z.union([z.literal('NEEDS_SEQ'), z.string().regex(BLOCK_NAME_RE)]) -- mixed arrays supported so partial-photo sessions can carry confirmed SEQ for some bags and ask-back sentinels for others (per CONTEXT.md Gray Area 3 lock)."
  - "parent is permissive z.string().min(1) (NOT a regex). Accepts canonical block_names, page-shorthand decodes, and the documented sentinel 'NO_PARENT' for fresh-grain inoc. Downstream Phase 48 normalizes."
  - "species is strict /^[A-Z]{2,4}$/ (mirrors mossrock active-strain-codes inventory: 2-4 uppercase letters)."
  - "BLOCK_NAME_RE re-exported from seeding-session.js -- no regex duplication."
  - "REQUIRED_FIELDS only flat-field shape; per-group presence enforced by SeedingSession Zod schema itself, not the state-machine REQUIRED_FIELDS map."
metrics:
  duration: ~25min
  tasks_completed: 2
  files_created: 3
  files_modified: 3
  tests_added: 31  # 24 in seeding-session.test.js + 7 in schemas.test.js
  tests_total_passing: 872
  completed_date: 2026-05-23
---

# Phase 47 Plan 01: SeedingSession + Provenanced + ConflictEntry Schemas Summary

Three new Zod schemas (SeedingSession, SeedingSessionGroup, ConflictEntry) plus a reusable Provenanced<T> factory wired into the Draft discriminated union without breaking the 5 legacy log-type parsers. Phase 47-02..05 and Phase 48 consumers can now `require('./schemas/seeding-session')` and `require('./schemas/provenance')` directly.

## What Shipped

### Task 1 -- Provenance factory + ConflictEntry + SeedingSession schemas

- **`schemas/provenance.js`** (new). Exports `SOURCE_ENUM` (closed set: audio, paper_log_photo, bag_label_photo, text, model_inference) and `Provenanced(valueSchema)` factory returning `z.object({ value, confidence: number(0..1), sources: array(SOURCE_ENUM).min(1) }).strict()`.
- **`schemas/seeding-session.js`** (new). Exports:
  - `SeedingSessionGroup` -- 4 provenanced fields (parent, species, qty, child_block_names). `.strict()`.
  - `ConflictEntry` -- internal forensics shape `{path, candidates[2+], resolution}`. `.strict()`.
  - `SeedingSession` -- top-level discriminated-union member: `{type:'seeding_session', event_date:YYYY-MM-DD, groups[1+], needs_input?, conflicts?, notes?}`. `.strict()`.
  - `ChildBlockNameOrSentinel` -- `z.union([z.literal('NEEDS_SEQ'), z.string().regex(BLOCK_NAME_RE)])` so mixed arrays work.
  - `BLOCK_NAME_RE` re-exported (no duplication of the regex).
- **`test/extraction/seeding-session.test.js`** (new). 24 tests covering the 6 plan-spec behavior anchors plus extra guards (Provenanced shape, ConflictEntry shape, off-schema rejection, NEEDS_SEQ mixing, event_date format).

### Task 2 -- Wire into Draft + LOG_TYPES + REQUIRED_FIELDS

- **`schemas/index.js`**: added `SeedingSession` as 6th member of `Draft` discriminated-union; `LOG_TYPES` is now a frozen 6-element array; re-exports `{SeedingSession, SeedingSessionGroup, ConflictEntry, Provenanced, SOURCE_ENUM}` so downstream plans have one import surface.
- **`state-machine.js`**: `REQUIRED_FIELDS.seeding_session = ['event_date', 'groups']`. Per-group field presence is enforced by the Zod schema itself (not by the flat REQUIRED_FIELDS map), comment explains this.
- **`test/extraction/schemas.test.js`**: updated LOG_TYPES expectation to length 6; added 6 new tests covering Draft union acceptance, empty-groups rejection, Submission wrapper round-trip, legacy 5-type regression guard, and DRAFT_JSON_SCHEMA mention of `seeding_session`.

## Verification

```
$ npx jest test/extraction/seeding-session.test.js test/extraction/schemas.test.js test/extraction/state-machine.test.js --no-coverage
Test Suites: 3 passed, 3 total
Tests:       78 passed, 78 total

$ npx jest --no-coverage    # full alerter suite, regression sweep
Test Suites: 2 skipped, 65 passed, 65 of 67 total
Tests:       9 skipped, 872 passed, 881 total

$ grep -n "seeding_session" schemas/index.js state-machine.js schemas/seeding-session.js
schemas/index.js:48:  'seeding_session',
schemas/seeding-session.js:76:    type: z.literal('seeding_session'),
state-machine.js:32:  seeding_session: ['event_date', 'groups'],

$ node -e "console.log(JSON.stringify(require('./src/extraction/schemas').DRAFT_JSON_SCHEMA).length)"
5328
```

DRAFT_JSON_SCHEMA still serializes (5328 bytes) -- Anthropic tool input_schema shape preserved after union extension.

## Deviations from Plan

None on behavior. Two minor implementation notes worth recording for downstream plans:

1. **`ChildBlockNameOrSentinel` is a top-level export.** The plan asked for "z.union or regex disjunction" inline; I chose `z.union([z.literal('NEEDS_SEQ'), z.string().regex(BLOCK_NAME_RE)])` and exported it as a named schema (`ChildBlockNameOrSentinel`) so Phase 47-03 (ask-back pipeline) can `require` it for the SEQ-fill normalization step. Tests cover both branches and mixed arrays.

2. **`REQUIRED_FIELDS.seeding_session` is flat `['event_date','groups']` only.** The state-machine's REQUIRED_FIELDS map is by design a flat-field-presence shape (it's called from `shouldAskBack` which does shallow `isFieldPresent` checks). Per-group field presence (parent/species/qty/child_block_names existence) is enforced by the SeedingSession Zod schema's `.strict()` + `Provenanced(...)` factory, which runs before `shouldAskBack` ever sees the draft. An explanatory comment was added inline. This is consistent with how observation's `state OR notes` rule is handled (special-cased inline in `shouldAskBack`, not via REQUIRED_FIELDS).

3. **Source-list export.** `SOURCE_ENUM` is also re-exported from `schemas/index.js` so the Phase 47-02 system-prompt writer can pull the closed source list from one canonical place (avoids drift between the prompt and the validator).

## Known Stubs

None. All schemas are functional and validated by tests.

## Self-Check: PASSED

- [x] `src/agents/alerter/src/extraction/schemas/provenance.js` exists
- [x] `src/agents/alerter/src/extraction/schemas/seeding-session.js` exists
- [x] `src/agents/alerter/test/extraction/seeding-session.test.js` exists
- [x] `schemas/index.js` Draft union includes SeedingSession (6 members)
- [x] `state-machine.js` REQUIRED_FIELDS.seeding_session exists
- [x] All 78 targeted tests + 872 full-suite tests green
- [x] DRAFT_JSON_SCHEMA serializes (5328 bytes; mentions seeding_session)
