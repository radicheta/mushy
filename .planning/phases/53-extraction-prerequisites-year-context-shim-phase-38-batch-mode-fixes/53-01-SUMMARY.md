---
phase: 53-extraction-prerequisites-year-context-shim-phase-38-batch-mode-fixes
plan: 01
subsystem: alerter-extraction
tags: [back-01, corpus-context, year-shim, jsonb, plumbing]
requires: []
provides: [corpus_context-column, corpus_context-plumbing]
affects: [signal_capture-schema, capture.js, extraction-pipeline]
tech_added: []
patterns: [additive-jsonb-column, nullable-back-compat-passthrough]
key_files_created: []
key_files_modified:
  - src/agents/alerter/src/capture-db.js
  - src/agents/alerter/src/capture.js
  - src/agents/alerter/src/extraction/pipeline.js
  - src/agents/alerter/test/capture-db.test.js
  - src/agents/alerter/test/capture.test.js
  - src/agents/alerter/test/extraction/pipeline.test.js
decisions: []
metrics:
  duration_min: 6
  tasks_complete: 2
  completed: 2026-05-24
---

# Phase 53 Plan 01: BACK-01 corpus_context JSONB column + plumbing Summary

End-to-end year-context shim wired: `signal_capture.corpus_context` (JSONB
nullable) → `capture.js` enqueue → `pipeline.js` extractor call → existing
`extractor.buildInitialUserContent` prompt block. Live captures unaffected
(null in, no prompt block emitted); the Phase 54 backfill harness will set
`{default_year: 2025, source: 'paper_log'}` on synthetic rows so the
extractor stops hallucinating years on undated 2025-notebook pages.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | corpus_context JSONB column + insertCapture passthrough | `bf721e2` | capture-db.js, capture-db.test.js |
| 2 | Plumb corpus_context capture.js -> pipeline -> extractor | `9d25ec7` | capture.js, pipeline.js, capture.test.js, pipeline.test.js |

## Verification

- `cd src/agents/alerter && npx jest test/capture-db.test.js` — 11/11 green
- `cd src/agents/alerter && npx jest test/extraction/pipeline.test.js` — 19/19 green
- `cd src/agents/alerter && npx jest` — full suite 1137 passed, 9 skipped, 0 failed
- Schema migration is idempotent (re-runs ALTER ADD COLUMN IF NOT EXISTS is a no-op)

## Deviations from Plan

None — plan executed exactly as written. The plan's note about node-postgres
JSONB binding ("verify by test") was confirmed: passing the plain object
through to pg without JSON.stringify works, and the round-trip mock test
asserts deep-equality.

## Self-Check: PASSED

- src/agents/alerter/src/capture-db.js exists with `corpus_context jsonb` ALTER
  and 17-column INSERT
- src/agents/alerter/src/extraction/pipeline.js calls `extractor.extract` with
  `corpusContext: captureCtx.corpusContext || null`
- src/agents/alerter/src/capture.js forwards `ctx.corpusContext || null` into
  the enqueue payload
- Commits `bf721e2` and `9d25ec7` present in `git log --oneline`
