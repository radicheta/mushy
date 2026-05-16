# Phase 43: Phase 38<->40 Schema Normalizer + Chain Integration Tests - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-05-16
**Phase:** 43-phase-38-40-schema-normalizer-chain-integration-tests
**Areas discussed:** Q1 harvest source_block_refs resolution, Q3 input recipe_lot landing
**Areas auto-defaulted:** Q2 seeding batch_name vs parent_batch_name (kept distinct, deferred per audit), Q4 harvest qty_g vs bags (single-bag synth + v1.8 candidate per audit)

---

## Q1a: source_block_refs string shape

| Option | Description | Selected |
|--------|-------------|----------|
| Always QR-id format | Pure rename source_block_refs -> source_qr_codes. | |
| Usually QR-id, sometimes free-form | Most cases QR-id; minority free-form names. | ✓ |
| Free-form farmer names are common | Need full by-name resolution path. | |

**User's choice:** Usually QR-id, sometimes free-form
**Notes:** Drove next sub-question: how to handle the minority case.

---

## Q1b: handling the free-form minority case

| Option | Description | Selected |
|--------|-------------|----------|
| QR-id only; free-form -> commit_failed | Smallest blast radius; defers real fix. | |
| B5-regex gate + warn in notes | Drops free-form from qr_codes but commits with warning. | |
| Extend qr.resolveQr with by-name fallback | Structural fix in qr.js. | ✓ |

**User's choice:** Extend qr.resolveQr with by-name fallback
**Notes:** Captured as D-06 in CONTEXT.md.

---

## Q1c: by-name fallback trigger

| Option | Description | Selected |
|--------|-------------|----------|
| Always: id_tag -> name on miss | Single code path; two HTTP calls in miss case. | ✓ |
| Regex-gated: B5 match -> id_tag; non-match -> name | One HTTP call per resolve. | |

**User's choice:** Always: id_tag -> name on miss
**Notes:** Captured as D-06. Name collisions = farmer discipline risk (D-08).

---

## Q3: input recipe_lot landing

| Option | Description | Selected |
|--------|-------------|----------|
| Prepend to notes (audit strawman) | Zero farmOS-side change; matches existing ingredients-into-notes pattern. | ✓ |
| Extend commit-input.js with structured field | Requires farmOS schema team coordination. | |
| Defer to v1.8 (drop on floor) | Silently discards farmer-stated data. | |

**User's choice:** Prepend to notes (after clarifying what recipe_lot actually is)
**Notes:** First response was "wtf is recipe_lot?" -- I had not introduced the field before asking. Re-read schemas/input.js, state-machine.js, commit-input.js; explained recipe_lot is the farmer-stated recipe-batch identifier (e.g. "RB-2026-05") that Phase 38 made required on input logs. Showed that commit-input.js already serializes ingredients into notes -- the prepend pattern slots cleanly in front of that. User then picked option 1. Captured as D-09 in CONTEXT.md.

**Lesson for future discuss-phase sessions:** when a gray area uses a field-name that isn't self-explanatory, READ the schema and one usage site BEFORE asking the user, and lead the question with a one-line definition.

---

## Claude's Discretion

- `normalize.js` internal organization (switch vs helper functions per log_type) -- planner's call.
- Telemetry/logging on resolve-by-name fallback hits -- not in v1.7 scope unless trivially cheap.
- Unit-test file location for normalize.js -- recommended `test/farmos/normalize.test.js`.

## Deferred Ideas

- Multi-bag harvest model (Q4) -- v1.8 candidate.
- Structured farmOS-side recipe_lot field -- requires schema-team coordination.
- Seeding lineage bridge (Q2) -- after farmOS pasteurization log lands.
- Telemetry counter on by-name fallback (D-06).
- Audit follow-on D (declared extractorShape -> commitShape JSON Schema artifact).
- Resolve-by-name dedup on name collisions.
