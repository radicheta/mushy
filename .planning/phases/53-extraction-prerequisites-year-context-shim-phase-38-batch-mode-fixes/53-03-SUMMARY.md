---
phase: 53-extraction-prerequisites-year-context-shim-phase-38-batch-mode-fixes
plan: 03
subsystem: alerter-extraction
tags: [back-03, capture-kind, prompt-classifier, few-shot]
requires: []
provides: [capture_kind-envelope-field, dt-tubs-few-shot]
affects: [system-prompt, submission-schema, extractor.packResult]
tech_added: []
patterns: [optional-nullable-enum, prompt-only-classifier]
key_files_modified:
  - src/agents/alerter/src/extraction/schemas/index.js
  - src/agents/alerter/src/extraction/prompts/system.js
  - src/agents/alerter/src/extraction/extractor.js
  - src/agents/alerter/test/extraction/schemas.test.js
  - src/agents/alerter/test/extraction/extractor.test.js
key_files_created:
  - src/agents/alerter/test/extraction/integration/capture-kind.test.js
decisions:
  - "DT-tubs few-shot uses type=seeding (not type=activity) because the locked ACTIVITY_NAMES enum does not include 'inoc' -- inoculating fresh spawn-tubs IS a seeding event per the locked schema"
metrics:
  duration_min: 10
  tasks_complete: 2
  completed: 2026-05-24
---

# Phase 53 Plan 03: BACK-03 capture_kind prompt classifier Summary

Extractor now emits a top-level `capture_kind` enum on the Submission envelope:
`'paper_log' | 'physical_object_photo' | 'voice_note' | 'text' | null`.
Field is optional + nullable (back-compat lock per D-BACK-03). Two new
few-shots teach the model the distinction:
- `tu_fewshot_5` = 4-row paper-log notebook scan → `paper_log`
- `tu_fewshot_6` = DT-tubs physical_object_photo modelled on misclassified
  capture `01KSCW771VB2FDWBPWNS4MEHAZ` → `physical_object_photo`

Routing (BACK-02) deliberately does NOT consume this field — it is
supportive analytics metadata + a hook for future per-capture-kind routing
refinements. The load-bearing fix for the misclassification cost
(DT-tubs misrouted to operator-channel) was the BACK-02 small-N heuristic.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Submission schema: optional nullable capture_kind enum | `52f0874` | schemas/index.js, schemas.test.js |
| 2 | SYSTEM_PROMPT rules + 2 few-shots + extractor.packResult passthrough | `673c413` | prompts/system.js, extractor.js, capture-kind.test.js, extractor.test.js |

## Verification

- `cd src/agents/alerter && npx jest test/extraction/schemas.test.js` — 40/40 green
- `cd src/agents/alerter && npx jest test/extraction/integration/capture-kind.test.js` — 3/3 green
- `cd src/agents/alerter && npx jest` — full suite 1151 passed, 9 skipped, 0 failed
- Every FEW_SHOT tool_use is followed by a matching tool_result in the next
  user turn (Plan 07 Rule 1 invariant preserved); live-turn boundary moved
  from `tu_fewshot_3` → `tu_fewshot_6` in `extractor.buildInitialUserContent`

## Deviations from Plan

**[Rule 1 - Bug] DT-tubs few-shot type changed activity → seeding.**
- Found during: capture-kind.test.js initial RED run.
- Issue: The plan's suggested DT-tubs envelope used `type: 'activity', name: 'inoc'`,
  but the locked `ACTIVITY_NAMES` enum (Phase 38 Plan 01 + farmos lock 2026-05-11)
  does not include `'inoc'` — allowed names are `sterilize | sterilize_failed | water |
  relocate | cold_shock | archive_spent | contam`. The few-shot would have taught the
  model to emit invalid schema.
- Fix: Recast DT-tubs as 2 seeding events (`type: 'seeding'`, `species: 'DT'`,
  `block_name: '260519_DT_1' / _2'`, `qty: 1`). Inoculating fresh spawn-tubs IS a
  seeding event per the locked schema (each tub becomes a new asset with its own
  block_name).
- The BACK-02 pipeline test still uses `type: 'activity', asset_ref: '260519_DT_1'`
  because that test is purely a routing-heuristic check and never runs the schema
  validator (mock extractor returns the envelope as-is). The BACK-03 few-shot ships
  to the live model so it must validate.
- Files modified: `src/agents/alerter/src/extraction/prompts/system.js`
- Commit: `673c413`

## Self-Check: PASSED

- `src/agents/alerter/src/extraction/schemas/index.js` exports `CAPTURE_KIND_ENUM`
  and Submission accepts `capture_kind: 'physical_object_photo'`
- `src/agents/alerter/src/extraction/prompts/system.js` contains the
  capture_kind rules block AND `tu_fewshot_5` (paper_log) AND `tu_fewshot_6`
  (physical_object_photo with DT-tubs caption)
- `src/agents/alerter/src/extraction/extractor.js` `packResult` returns
  `capture_kind` on the result envelope; leading tool_result references
  `tu_fewshot_6`
- Commits `52f0874` and `673c413` present in `git log --oneline`
