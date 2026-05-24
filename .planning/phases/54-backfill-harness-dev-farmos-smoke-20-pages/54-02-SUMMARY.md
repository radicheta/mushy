---
phase: 54-backfill-harness-dev-farmos-smoke-20-pages
plan: 02
subsystem: alerter/backfill
tags: [v1.11, backfill, auto-confirm, santi-only, back-06]
requires: [backfill-cli-skeleton, prod-guard, santi-only-gate]
provides: [bulk-backfill-short-circuit, draft-flip-to-confirmed, commit-router-dispatch, summaries-log-writer, in-loop-santi-assertion]
affects: [src/agents/alerter/scripts/, src/agents/alerter/src/extraction/, .gitignore]
tech_added: []
patterns: [defense-in-depth-santi-gate, fire-and-forget-per-draft-try-catch, ascii-only-summary-lines]
files_created: []
files_modified:
  - src/agents/alerter/scripts/backfill-notebook.js
  - src/agents/alerter/scripts/backfill-notebook.test.js
  - src/agents/alerter/src/extraction/extraction-db.js
  - src/agents/alerter/test/extraction/extraction-db.test.js
  - .gitignore
key_decisions:
  - "DRAFT_STATUS_CONFIRMED = 'confirmed' — matches confirm/state-machine.js CONFIRMED and farmos/commit-db.js WHERE status='confirmed'. The bulk-backfill harness writes this canonical value (not a new 'confirmed_by_farmer' enum)."
  - "Auto-confirm stamps needs_review_reason='bulk_backfill_santi' on every flipped row — repudiation mitigation per T-54-06."
  - "Per-draft try/catch: draft_flip_failed or commit-router ok:false records a reason on the per-draft entry and continues to the next draft. Per T-54-08, one bad page must not abort the whole run."
  - "Summary lines are ASCII-only with em-dash stripping (replace [–—] with '--') per [[feedback_no_em_dashes_in_artifacts]]."
  - "Added .planning/backfill/ to .gitignore upfront (Plan 03 verification step pulled forward) — per-run paid-LLM JSONL is operator-local; only the canonical Cycle 1/2 attestation receipts get committed manually."
  - "In-loop santi assertion runs every iteration (defense-in-depth per T-54-05); CLI-level gate from Plan 01 is the first line, but a mid-loop opts mutation must also trip the gate."
metrics:
  duration_minutes: 20
  completed: 2026-05-24
  tasks_completed: 2
  files_changed: 5
---

# Phase 54 Plan 02: Auto-confirm short-circuit + commit-router + summaries.log Summary

Layered the bulk-backfill auto-confirm path onto Plan 01's harness. New helpers in extraction-db (`getDraftsForCapture`) and backfill-notebook (`assertSantiInLoop`, `flipDraftToConfirmed`, `buildSummaryLine`, `openSummariesLog`, `appendSummaryLine`, `processDraftsForCapture`, `computeRunDir`). Main loop now: (1) dispatch synthetic capture (Plan 01); (2) read drafts the pipeline produced via `source_capture_ids @> ARRAY[$1]`; (3) if `--bulk-backfill --farmer=santi`, flip each draft to `'confirmed'` with `needs_review_reason='bulk_backfill_santi'`; (4) dispatch to commit-router against dev farmOS; (5) audit one ASCII line per draft to `<runDir>/summaries.log`. Dep-injection seams (`extractionDb`, `commitRouter`, `clientFactory`) let tests mock all three without touching real services.

## Verification

- 47 hermetic tests pass in scripts/backfill-notebook.test.js (+18 vs Plan 01) and extraction-db.test.js +2 = 65 between the two files.
- Full alerter suite: 1198 pass / 9 skipped / 0 fail.
- Summary-line format verified: ASCII-only, em-dash-stripped, includes `ok=`/`assets=`/`logs=`/`reason=` fields.

## Deviations from Plan

- **[Rule 2 - Critical functionality] Added `.planning/backfill/` to .gitignore** during Plan 02 rather than waiting for Plan 03's verification step. Without it, the first real run would attempt to commit per-run JSONLs into the repo. Pulled forward as a one-line change to `.gitignore`.
- Status constant resolution: plan spec said "use canonical DRAFT_STATUS confirmed constant if it exists; fall back to literal `'confirmed_by_farmer'`". Investigation showed the canonical value is `'confirmed'` (Phase 39 / confirm-state-machine.js CONFIRMED). Used the literal `'confirmed'` directly (exported as `DRAFT_STATUS_CONFIRMED`). The state-machine.js DRAFT_STATUS frozen enum doesn't yet expose CONFIRMED (Phase 39 owns it elsewhere) so I did not import from there to avoid a circular concern; the literal matches what commit-db / receive-loop already read.

## Self-Check: PASSED
- FOUND: src/agents/alerter/scripts/backfill-notebook.js (Plan 02 helpers added)
- FOUND: src/agents/alerter/src/extraction/extraction-db.js (getDraftsForCapture exported)
- FOUND: .gitignore (.planning/backfill/ entry)
