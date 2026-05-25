---
phase: 54-backfill-harness-dev-farmos-smoke-20-pages
plan: 04
subsystem: alerter/backfill
tags: [v1.11, backfill, receipt, back-08-part1]
requires: [bulk-backfill-short-circuit, responses-jsonl-writer]
provides: [receipt-builder, per-page-csv-diff, phase-51-upsert-stability-validator, duplicate-asset-counter, cycle-1-runbook, cycle-2-runbook]
affects: [src/agents/alerter/scripts/, .planning/phases/54-.../]
tech_added: []
patterns: [farmer-facing-single-document, intra-cycle-upsert-stability-proxy-for-original-stub-enrichment, em-dash-scrub]
files_created:
  - src/agents/alerter/scripts/build-backfill-receipt.js
  - src/agents/alerter/scripts/build-backfill-receipt.test.js
  - .planning/phases/54-backfill-harness-dev-farmos-smoke-20-pages/54-CYCLE-1-RUNBOOK.md
  - .planning/phases/54-backfill-harness-dev-farmos-smoke-20-pages/54-CYCLE-2-RUNBOOK.md
files_modified:
  - src/agents/alerter/scripts/backfill-notebook.js
key_decisions:
  - "BACK-08 stub-enrichment resolution honored: the 4 May-22 ancestor stubs (260304_SHI_5, 260118_SHI_23, 260118_SHI_26, 260118_KOY_12, 260425_KOY_4) are 2026-dated and pre-date the 2025 notebook corpus, so the literal stub-enrichment check is N/A. Substituted: intra-cycle upsert stability — block_names referenced >=2 times must resolve to a single UUID. Receipt documents this substitution in the header."
  - "Receipt aggregate hard-codes the PASS/FAIL line for duplicate_asset_count == 0; cycle review gate is explicit, not buried in numbers."
  - "buildReceipt called from main()'s finally{} block — even a crashed run leaves an audit artifact (T-54-13 mitigation)."
  - "Em-dash scrub at the bottom of buildReceipt (replace [–—] with '--') is the universal escape hatch for upstream data that might leak em-dashes from LLM output or stack traces."
  - "Minimal CSV parser inline (handles quoted/comma-bearing notes field) — avoids adding csv-parse dep when alerter doesn't already depend on it."
metrics:
  duration_minutes: 30
  completed: 2026-05-24
  tasks_completed: 2
  files_changed: 5
---

# Phase 54 Plan 04: Receipt builder (per-page + aggregate + upsert-stability) Summary

Shipped `scripts/build-backfill-receipt.js` plus 19 hermetic tests. Helpers: `parseCsv`, `loadCsvForPage`, `computeCsvDiff` (case-insensitive strain match, hit/miss/extra), `renderPageSection` (markdown block per page with CSV diff or N/A), `computeAggregate` (Phase 51 upsert stability check + duplicate_asset_count + per_strain + unknown_strain_codes), `aggregateCost` (sums responses.jsonl), `buildReceipt` (writes runDir/receipt.md). Harness now invokes `buildReceipt` from its finally{} block so any run — including a crashed one — emits the audit artifact. Cycle 1 + Cycle 2 RUNBOOKs authored (operator workflows; not for autonomous execution).

## Sample receipt output (from synthetic happy-path data)

```
# Backfill Receipt -- Cycle 1 (run good)

- run_id: good
- cycle: 1
- generated_at: 2026-05-24T...
- dev_farmos_url: n/a
- elapsed_seconds: 0
- BACK-08 contract: Phase 51 upsert-by-stable-identity, validated via intra-cycle upsert stability (the original May-22-ancestor stub-enrichment check is N/A because those codes are 2026-dated and post-date the 2025 paper-log corpus).

## Aggregate
- pages: 1
- drafts: 2
- assets_created: 2
- assets_reused: 0
- logs_created: 2
- duplicate_asset_count: 0 (PASS)
- total_cost_usd: 0.0000 (across 0 LLM calls)

### Phase 51 upsert stability (BACK-08 contract validation)
- checked: 1 block_names referenced >=2 times
- stable: 1 resolved to a single UUID
- unstable: 0 (PASS)
```

(FAIL path also verified: same block_name with two different UUIDs renders `unstable: 1 (FAIL -- Phase 51 contract regression)` with the colliding UUIDs listed.)

## Verification

- 19 hermetic tests pass (`npx jest scripts/build-backfill-receipt.test.js`).
- Full alerter suite: 1232 pass / 9 skipped / 0 fail (+19 vs Plan 03's 1213).
- Both happy-path (stable) and FAIL-path (unstable + em-dash scrub) verified via inline `node -e` invocations.

## Deviations from Plan

- **[Rule 2 - Critical functionality] Authored 54-CYCLE-1-RUNBOOK.md and 54-CYCLE-2-RUNBOOK.md as part of Plan 04** rather than waiting for Plans 05/06 to formally execute. The orchestrator's directive was to build the runbook artifacts even though the cycle runs themselves are operator workflows. The RUNBOOKs include explicit copy-paste commands, prerequisite checks, and the farmer-review gate language.

- **[FINDING — real-run bootstrap not yet wired]** While writing the Cycle 1 RUNBOOK I confirmed: the harness's `main()` function relies on `poolFactory` + `pipelineFactory` dep-injection seams for real runs. Plans 01-04 ship the harness fully unit-tested but the canonical alerter bootstrap from `src/index.js` (which builds `pool` + `pipeline` with the real extractor + state-machine + outbound dispatcher) is NOT yet lifted into a `createBackfillContext()` helper. Cycle 1 cannot fire end-to-end until either (a) the bootstrap is lifted into a helper, or (b) the operator writes a small `live-fire-54.js` driver that does the bootstrap inline. **Documented in 54-CYCLE-1-RUNBOOK.md step 7** as a "before step 7" follow-on. ~30 min of work. This is intentional scope conservatism — the receipt + observer + auto-confirm + commit dispatch + summaries.log are all hermetically verified, and the missing piece is a thin wrapper that connects them.

## Self-Check: PASSED
- FOUND: src/agents/alerter/scripts/build-backfill-receipt.js
- FOUND: src/agents/alerter/scripts/build-backfill-receipt.test.js
- FOUND: .planning/phases/54-backfill-harness-dev-farmos-smoke-20-pages/54-CYCLE-1-RUNBOOK.md
- FOUND: .planning/phases/54-backfill-harness-dev-farmos-smoke-20-pages/54-CYCLE-2-RUNBOOK.md
