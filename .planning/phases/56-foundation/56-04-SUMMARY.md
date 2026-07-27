---
phase: 56-foundation
plan: "04"
subsystem: extraction/schemas
tags: [pydantic, json-schema, parity-gate, zod-port, fnd-04]
dependency_graph:
  requires: ["56-01"]
  provides: ["FND-04 parity gate", "SUBMISSION_JSON_SCHEMA", "extraction schema models"]
  affects: ["Phase 60 extraction pipeline (LLM tool input_schema)"]
tech_stack:
  added: []
  patterns:
    - "pydantic v2 Generic[T] for Provenanced factory"
    - "Custom Annotated types for optional-not-nullable fields (OptStr, OptStrMin1, _StripNullFromAnyOf)"
    - "normalize_schema: inline $refs + strip title/default/description + sort required"
    - "plain Union (no discriminator) -> anyOf instead of oneOf"
key_files:
  created:
    - src/farm-agent/farm_agent/extraction/schemas/_types.py
    - src/farm-agent/farm_agent/extraction/schemas/provenance.py
    - src/farm-agent/farm_agent/extraction/schemas/seeding.py
    - src/farm-agent/farm_agent/extraction/schemas/activity.py
    - src/farm-agent/farm_agent/extraction/schemas/input.py
    - src/farm-agent/farm_agent/extraction/schemas/observation.py
    - src/farm-agent/farm_agent/extraction/schemas/harvest.py
    - src/farm-agent/farm_agent/extraction/schemas/seeding_session.py
    - src/farm-agent/farm_agent/extraction/schemas/submission.py
    - src/farm-agent/tests/test_schema_parity.py
  modified: []
decisions:
  - "Use plain Union (no Field(discriminator=)) to get anyOf instead of oneOf+discriminator in JSON Schema"
  - "Custom OptStr/OptStrMin1/OptStartingSeq/_StripNullFromAnyOf types for zod .optional() (not nullable) fields"
  - "normalize_schema inlines all $refs before comparison — pydantic uses $defs, fixture uses inline objects"
  - "value: Any = None in _CandidateEntry (not required) matches zod z.unknown() omitting value from required[]"
metrics:
  duration: "~40 minutes"
  completed: "2026-06-15"
  tasks_completed: 2
  files_created: 10
  files_modified: 0
---

# Phase 56 Plan 04: Pydantic v2 Schemas + JSON-Schema Parity Gate Summary

Ported all 6 zod extraction schemas to pydantic v2 and landed the FND-04 JSON-Schema parity gate. `uv run pytest tests/test_schema_parity.py` exits 0. The gate defends against silent zod-to-pydantic schema drift before any LLM call exists in the Python stack.

## What Was Built

**8 schema modules** (`_types.py`, `provenance.py`, `seeding.py`, `activity.py`, `input.py`, `observation.py`, `harvest.py`, `seeding_session.py`, `submission.py`) + **1 parity test** (`test_schema_parity.py`).

**`SUBMISSION_JSON_SCHEMA`** is exported from `submission.py` and will be passed verbatim as `input_schema` to the Anthropic tool-use call in Phase 60.

## Task 1: Spike — Cosmetic-Only Diff Proven

Built minimal `Submission` with SeedingLog only. Key findings:

**Pitfall 2 verdict (exclusiveMinimum form):** pydantic v2 emits `exclusiveMinimum: 0` (numeric, draft-7 form) for `int = Field(gt=0)`. No normalizer adjustment needed.

**Structural differences found and handled:**
1. `$defs` vs `definitions` — normalized via string replace
2. `$ref` in `anyOf` vs inline objects — `_inline_refs()` recursively inlines all `$ref`s
3. `title`/`description`/`default` keys — stripped in normalizer
4. `required` ordering — sorted in normalizer
5. Top-level fixture has `{$ref, definitions, $schema}` — normalizer resolves root `$ref` then inlines

**New pattern discovered:** `str | None = None` in pydantic emits `anyOf: [{type:string}, {type:null}]` but zod's `.optional()` (not `.nullable()`) emits just `{type:string}`. Required custom types.

## Task 2: Full Port — Parity Gate GREEN

Ported all 6 log types. Three non-obvious schema parity issues resolved:

1. **Optional-not-nullable fields** (`notes`, `state`, `parent_batch_name`, `needs_input`, `conflicts`): Created `OptStr`, `OptStrMin1`, `OptStartingSeq` (custom annotated types with `__get_pydantic_json_schema__` that suppress the null union), and `_StripNullFromAnyOf` for optional list fields.

2. **`value: Any = None` in ConflictEntry candidates**: zod's `z.unknown()` does not include `value` in `required[]`. Pydantic's `Any` without a default IS required. Setting `value: Any = None` makes it non-required, matching the fixture.

3. **`capture_kind: CaptureKind | None = None`** correctly preserves `anyOf: [{type:string, enum:...}, {type:null}]` because `capture_kind` is `z.nullable().optional()` in zod — the null union is intentional and the fixture has it.

## Parity Acceptance Criteria — All Met

- `uv run pytest tests/test_schema_parity.py -q` passes all 4 tests
- `extra="forbid"` on every nested model (grep count): 12 occurrences across 8 files
- Fixture byte-unchanged: `git diff HEAD -- tests/fixtures/submission_json_schema.json` → empty
- `SUBMISSION_JSON_SCHEMA = Submission.model_json_schema()` exported from `submission.py`
- `test_all_models_forbid_extra` green: every schema object with `properties` has `additionalProperties:false`
- ObservationLog cross-field validator: raises when both `state` and `notes` are None

## Deviations from Plan

### Auto-discovered pattern gap

**[Rule 1 - Structural Fix] OptStr / _StripNullFromAnyOf custom types needed**
- **Found during:** Task 1 spike investigation
- **Issue:** pydantic `str | None = None` emits `anyOf: [{type:string}, {type:null}]` but zod `.optional()` (not `.nullable()`) emits `{type:string}` — a substantive schema difference
- **Fix:** Created custom annotated types in `_types.py` that have correct pydantic runtime behavior (accept None) but emit the correct JSON Schema (no null union)
- **Files modified:** `_types.py` (new), `observation.py`, `seeding.py`, `seeding_session.py`
- **Commit:** `a1c51eb`

### Auto-discovered pydantic Union behavior

**[Rule 1 - Structural Fix] Plain Union (not Field(discriminator=)) needed for anyOf**
- **Found during:** Task 1 spike investigation
- **Issue:** `Annotated[Union[...], Field(discriminator='type')]` emits `oneOf` + `discriminator` object, not `anyOf`. Fixture uses `anyOf`.
- **Fix:** Use plain `Union[...]` without discriminator — pydantic then emits `anyOf` with `$ref` to `$defs`. After `_inline_refs()`, structure matches fixture.
- **Files modified:** `submission.py`
- **Commit:** `3f9d348`

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries introduced. These are pure pydantic model definitions (no I/O). The threat register (T-56-04-01, T-56-04-02) is satisfied: parity test actively defends against schema drift; fixture was not edited.

## Self-Check: PASSED

All created files exist:
- `src/farm-agent/farm_agent/extraction/schemas/_types.py` ✓
- `src/farm-agent/farm_agent/extraction/schemas/provenance.py` ✓
- `src/farm-agent/farm_agent/extraction/schemas/seeding.py` ✓
- `src/farm-agent/farm_agent/extraction/schemas/activity.py` ✓
- `src/farm-agent/farm_agent/extraction/schemas/input.py` ✓
- `src/farm-agent/farm_agent/extraction/schemas/observation.py` ✓
- `src/farm-agent/farm_agent/extraction/schemas/harvest.py` ✓
- `src/farm-agent/farm_agent/extraction/schemas/seeding_session.py` ✓
- `src/farm-agent/farm_agent/extraction/schemas/submission.py` ✓
- `src/farm-agent/tests/test_schema_parity.py` ✓

Commits verified:
- `6629257` — test(56-04): RED spike parity test ✓
- `3f9d348` — feat(56-04): GREEN spike ✓
- `a1c51eb` — feat(56-04): GREEN full parity gate ✓
