---
phase: 38-extraction-pipeline
plan: "01"
subsystem: alerter/extraction
tags: [zod, schemas, b7, anthropic-tool-use]
requires: []
provides:
  - extraction-schemas-zod
  - draft-json-schema-anthropic
  - b5-block-name-regex
affects: [src/agents/alerter]
tech_stack_added: [zod, zod-to-json-schema]
patterns_added: [discriminated-union-with-pre-refine-base]
key_files_created:
  - src/agents/alerter/src/extraction/schemas/seeding.js
  - src/agents/alerter/src/extraction/schemas/activity.js
  - src/agents/alerter/src/extraction/schemas/input.js
  - src/agents/alerter/src/extraction/schemas/observation.js
  - src/agents/alerter/src/extraction/schemas/harvest.js
  - src/agents/alerter/src/extraction/schemas/index.js
  - src/agents/alerter/test/extraction/schemas.test.js
key_files_modified:
  - src/agents/alerter/package.json
decisions:
  - "ObservationLogBase (no .refine) feeds the discriminatedUnion; ObservationLog (with .refine) exported for standalone use -- Zod constraint workaround"
  - "DRAFT_JSON_SCHEMA emitted via zodToJsonSchema(Draft, 'Draft') -- shape is {$ref, definitions.Draft.anyOf[]} (draft-7, Anthropic-compatible)"
  - "Activity name enum hardcoded to 7 locked values (sterilize, sterilize_failed, water, relocate, cold_shock, archive_spent, contam) per CONTEXT D-04"
  - "B5 block_name regex ^[0-9]{6}_[A-Z]{3}_[0-9]+\\$ applied only to seeding.block_name; activity/input/observation use the looser asset_ref string per RESEARCH §8"
metrics:
  duration: "~12min"
  completed: "2026-05-12"
  tasks_complete: 3
  files_touched: 8
  tests_added: 28
---

# Phase 38 Plan 01: Zod Schema Foundation Summary

## One-liner

B7 log-type Zod schemas (seeding/activity/input/observation/harvest) + discriminated-union `Draft` + Anthropic-ready `DRAFT_JSON_SCHEMA` landed under `src/agents/alerter/src/extraction/schemas/`, gated by 28 unit tests.

## What shipped

- **5 per-log-type Zod schemas** with `.strict()` envelopes (EXT-01 anchor: no off-schema fields), per-field `confidence` record (D-03), and required-field maps from RESEARCH §8.
- **B5 block_name regex** `^[0-9]{6}_[A-Z]{3}_[0-9]+$` enforced on `seeding.block_name`.
- **Multi-parent harvest lineage (C4)** — `source_block_refs` is `z.array(z.string()).min(1)`; tested with a 3-parent fixture.
- **Discriminated-union `Draft`** over the 5 log types; `DRAFT_JSON_SCHEMA = zodToJsonSchema(Draft, 'Draft')` is the value Plan 03 will pass as `tools[0].input_schema` to Anthropic.
- **`LOG_TYPES`** frozen array for callers needing an iterable list.
- **28 unit tests** in `test/extraction/schemas.test.js` — TDD RED then GREEN, covering: B5 accept/reject, activity 7-enum exhaustive, observation state-or-notes refine, harvest multi-parent + empty rejection, confidence-range rejection (1.5 / -0.1), `.strict()` rejection of unknown top-level fields, Draft discriminator rejection, `DRAFT_JSON_SCHEMA` JSON round-trip.

## Commits

| Hash    | Type | Message                                                                    |
| ------- | ---- | -------------------------------------------------------------------------- |
| 3375c65 | feat | add zod deps + scaffold extraction/schemas directory                       |
| 0f948d4 | test | add failing zod schema tests for B7 log types (RED)                        |
| 30f0ff8 | feat | implement zod schemas for B7 log types (GREEN for per-type)                |
| fe344d5 | feat | discriminated-union Draft schema + Anthropic input_schema export (GREEN)   |

## Tasks executed

| # | Name                                                  | Status   | Commit  |
|---|-------------------------------------------------------|----------|---------|
| 1 | Add Zod deps + scaffold schema directory              | complete | 3375c65 |
| 2 | Author per-log-type Zod schemas + tests (RED→GREEN)   | complete | 0f948d4, 30f0ff8 |
| 3 | Discriminated-union Draft + Anthropic input_schema    | complete | fe344d5 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Observation `.refine()` breaks `z.discriminatedUnion`**

- **Found during:** Task 3 GREEN phase
- **Issue:** Zod's `discriminatedUnion` requires pure `z.object` inputs; an `ObservationLog` exported with `.refine()` (for the state-or-notes rule) caused `Cannot read properties of undefined (reading 'type')` when added to the union.
- **Fix:** Split `observation.js` into `ObservationLogBase` (pre-refine, used by the union) and `ObservationLog` (post-refine, used for standalone validation). Both exported. Callers validating observation drafts directly should use `ObservationLog`; the Draft union uses `ObservationLogBase` and downstream code (Plan 02 validator) will re-apply the state-or-notes check when needed.
- **Files modified:** `src/extraction/schemas/observation.js`, `src/extraction/schemas/index.js`
- **Commit:** fe344d5

No other deviations. The plan's Task-3 hint about adjusting JSON-Schema test shape assertions ("may use definitions/$ref") played out exactly as predicted -- the test was written to substring-match on log-type names rather than deep-equal the structure, so no test change was needed.

## Deferred Issues

**Pre-existing failure unrelated to Plan 38-01:** `test/config.test.js` Test A fails locally because the dev shell exports `DASHBOARD_URL=http://100.96.10.66:8080/` which overrides the default expected by the test. This failure also reproduces on `main` before this plan. Not in scope. Flagged for a follow-up sweep or env-isolation fix in a future plan.

## Verification

- `cd src/agents/alerter && npm test -- test/extraction/schemas.test.js` -> 28/28 pass.
- `cd src/agents/alerter && npm test` -> 296/297 (1 pre-existing failure documented above; no regressions caused by this plan).
- `cd src/agents/alerter && node -e "const s = require('./src/extraction/schemas'); console.log(JSON.stringify(s.DRAFT_JSON_SCHEMA).slice(0,120))"` -> emits `{"$ref":"#/definitions/Draft","definitions":{"Draft":{"anyOf":[{"type":"object",...`.
- `grep -E "—" src/extraction/schemas/*.js` -> no matches (no em-dashes).
- `grep -c ".strict()" src/extraction/schemas/*.js` -> at least 1 per per-type file (5 total, 6 with index.js comment hit excluded by manual inspection).

## Threat Mitigations Applied

| Threat ID   | Mitigation in code |
|-------------|--------------------|
| T-38-01-01  | `.strict()` on every per-type schema; tests assert unknown field rejection (seeding case) |
| T-38-01-02  | `BLOCK_NAME_RE` regex on `seeding.block_name`; tests assert both accept and reject cases |
| T-38-01-03  | (accepted) `DRAFT_JSON_SCHEMA` contains only field names + types, no secrets, suitable for inclusion in Anthropic request bodies |

## Downstream Seams

- **Plan 02 (validator):** can `require('./schemas')` and call `Draft.safeParse(rawToolInput)`; will re-apply the observation state-or-notes refine when the discriminator is `observation`.
- **Plan 03 (extractor):** passes `DRAFT_JSON_SCHEMA` as `tools[0].input_schema` to `client.messages.create({...})`.
- **Plan 04 (sanitizer):** reads `LOG_TYPES` to iterate when rendering farmer-facing previews.

## Self-Check: PASSED

- `src/agents/alerter/src/extraction/schemas/seeding.js` -> FOUND
- `src/agents/alerter/src/extraction/schemas/activity.js` -> FOUND
- `src/agents/alerter/src/extraction/schemas/input.js` -> FOUND
- `src/agents/alerter/src/extraction/schemas/observation.js` -> FOUND
- `src/agents/alerter/src/extraction/schemas/harvest.js` -> FOUND
- `src/agents/alerter/src/extraction/schemas/index.js` -> FOUND
- `src/agents/alerter/test/extraction/schemas.test.js` -> FOUND
- Commit 3375c65 -> FOUND
- Commit 0f948d4 -> FOUND
- Commit 30f0ff8 -> FOUND
- Commit fe344d5 -> FOUND
