---
phase: 54-backfill-harness-dev-farmos-smoke-20-pages
plan: 01
subsystem: alerter/backfill
tags: [v1.11, backfill, harness, back-05]
requires: []
provides: [backfill-cli-skeleton, prod-guard, santi-only-gate, page-range-filter, synthetic-capture-dispatcher]
affects: [src/agents/alerter/scripts/]
tech_added: []
patterns: [prod-guard-mirror-from-live-fire-52, hermetic-cli-tests, deps-injection-seam-pool-pipeline-factory]
files_created:
  - src/agents/alerter/scripts/backfill-notebook.js
  - src/agents/alerter/scripts/backfill-notebook.test.js
files_modified: []
key_decisions:
  - "Reused capture-db.insertCapture instead of re-rolling the signal_capture INSERT shape; harness imports capture-db dynamically inside insertSyntheticCapture so unit tests can jest.mock it without touching the real DB."
  - "computeRunId emits ISO-8601 with both ':' and '.' replaced by '-' to avoid filesystem-illegal chars and ms-precision dots in path segments."
  - "Real-run path (no --dry-run, no injected factories) returns exit code 1 with an explicit 'bootstrap not wired in Plan 01' message — Plan 02 wires the canonical pool + pipeline factory; until then live runs only work via the dep-injection seam."
  - "Page-range regex IMG_3(7[7-9][0-9]|8[0-5][0-9]|86[0-1]) restricts dispatch to IMG_3775..IMG_3861 (CSV-ground-truth range per HANDOFF.md); IMG_3862..IMG_3884 trip a warn-and-skip with a HANDOFF.md citation."
metrics:
  duration_minutes: 25
  completed: 2026-05-24
  tasks_completed: 2
  files_changed: 2
---

# Phase 54 Plan 01: CLI core + prod-guard + santi-gate Summary

Shipped `scripts/backfill-notebook.js` with full CLI surface (--help/--bulk-backfill/--farmer/--cycle/--limit/--dry-run/--resume-from/--run-id/--corpus-dir), `assertProdGuard` (mirrors live-fire-52.js — refuses ':8082' / ':8082/' / 'prod' substrings, case-insensitive), `assertFarmerGate` (santi-only hard gate per T-54-02), `listCorpusPages` (IMG_3775..IMG_3861 only, warn-and-skip on the un-transcribed Jan–Apr 2026 gap), `selectPages` (limit + resumeFrom), `buildSyntheticCapture` (corpus_context literal `{default_year:2025, source:'paper_log'}`), and a sequential `dispatchPage` loop wired to `capture-db.insertCapture` + `pipeline.enqueue`. Real-run pool/pipeline bootstrap is intentionally a TODO marker for Plan 02; Plan 01 ships --dry-run + dep-injection seams for hermetic tests.

## Verification

- 29 hermetic tests pass (`npx jest scripts/backfill-notebook.test.js`).
- Full alerter suite: 1180 pass / 9 skipped / 0 fail (+29 new vs 1151 baseline).
- Live dry-run smoke against real corpus: 5 IMG_NNNN pages listed, exit 0. Warn-and-skip lines fired for 9 of the un-transcribed IMG_386x..IMG_388x.
- Prod-guard smoke (FARMOS_URL=...:8082): exit 3 with REFUSING message.
- Farmer-gate smoke (--farmer=vikki): exit 4 with REFUSING message.

## Deviations from Plan

None — Tasks 1+2 executed exactly as planned. The plan's "Task 2 dispatch loop ships in this plan" was honored; auto-confirm, paid-LLM persistence, and receipt remain Plan 02/03/04 surface.

## Self-Check: PASSED
- FOUND: src/agents/alerter/scripts/backfill-notebook.js
- FOUND: src/agents/alerter/scripts/backfill-notebook.test.js
