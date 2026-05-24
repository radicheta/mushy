---
phase: 53-extraction-prerequisites-year-context-shim-phase-38-batch-mode-fixes
plan: 04
subsystem: alerter-extraction-eval
tags: [back-04, eval-gate, phase54-gate, blocked-operator]
requires: [back-01, back-02, back-03]
provides: [notebook-2025-eval-harness]
affects: [phase-54-blocker]
tech_added: []
patterns: [hermetic-mock-anthropic, green-when-empty]
key_files_created:
  - src/agents/alerter/test/eval/ingestion/notebook-2025-loader.js
  - src/agents/alerter/test/eval/ingestion/notebook-2025.test.js
  - src/agents/alerter/test/eval/ingestion/fixtures/notebook-2025/README.md
key_files_modified:
  - src/agents/alerter/package.json
decisions:
  - "Harness ships green-when-empty (test.skip + a wiring-only test passes) so CI stays green while Phase 54 is explicitly blocked on operator fixture curation"
  - "DT-tubs example uses type=seeding not type=activity (carried over from 53-03 schema lock)"
metrics:
  duration_min: 6
  tasks_complete: "1 of 3 (Task 2 scaffolding only -- Task 1 + Task 3 operator-gated)"
  completed: 2026-05-24
gate_status: "BLOCKED — needs operator fixture labels"
---

# Phase 53 Plan 04: BACK-04 hermetic eval gate Summary

**BACK-04 ship-gate: BLOCKED — needs operator fixture labels.**
**Phase 54: STILL BLOCKED.**

## Status

The eval-gate INFRASTRUCTURE shipped autonomously (Task 2 — loader, test file,
`test:eval` npm script, fixtures README). The eval-gate CORPUS (5-10 hand-labeled
2025-notebook pages) requires operator judgement and was deliberately NOT
auto-curated, per the plan's explicit lock and the orchestrator's preamble:

> If 53-04 fixtures can't be hand-labeled autonomously, return cleanly with an
> explicit "BLOCKED — needs operator fixture labels" message; that's expected
> and not a failure.

The harness is green-when-empty: a wiring-assertion test passes; per-fixture
`it.each` cases skip when no subdirs exist. This keeps the CI signal honest:
`npx jest test/eval/ingestion/notebook-2025.test.js` returns green today but
proves nothing about extractor quality on real notebook pages. Phase 54
cannot kick off until the corpus is curated.

## Tasks Completed

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Hand-curate 5-10 fixtures from mushdatadump-prod | BLOCKED — operator | — |
| 2 | Hermetic eval test + npm test:eval script | DONE | `a2467ea` |
| 3 | Operator confirms Phase 54 may proceed | BLOCKED — operator | — |

## Why Task 1 was not auto-curated

`/mnt/mossrock/shared/mushdatadump-prod/` contains only 2 subdirs:
- `2026-05-12_inoc_santi/` — 2 paper-log jpg photos + audio + transcript (NOT 2025-dated)
- `2026-05-13_backlog_unprocessed/` — 3 captures, none paper-log-shaped

Neither maps onto the plan's "5-10 representative 2025-notebook pages" requirement.
The plan explicitly requires:
- ≥ 3 true paper-log pages (multi-row notebook scans)
- ≥ 1 physical-object photo (DT-tubs-shaped)
- ≥ 1 page where the year is genuinely absent (BACK-01 case)

These are not deterministically extractable from the available corpus. Even if
they were, ground-truth labels (which species code, which parent batch, which
SEQ counter) require operator knowledge of the farm's notation that cannot
be derived from image filenames alone.

Per the prompt's explicit instruction: "Don't fake labels — surface the gap
if you can't determine ground truth." Surfacing.

## What ships today

- `src/agents/alerter/test/eval/ingestion/notebook-2025-loader.js` — fixture
  loader mirroring `sessions-loader.js` shape
- `src/agents/alerter/test/eval/ingestion/notebook-2025.test.js` — hermetic
  `it.each` over the corpus + `EVAL_RUN_LIVE=1` branch (persists paid output
  to `results/notebook-2025/<page-id>-<ISO>.json` per memory
  `[[feedback_persist_paid_results_default]]`)
- `package.json` `test:eval` script (composes with `sessions.test.js` live
  branch as the plan required)
- `fixtures/notebook-2025/README.md` documenting the operator curation contract

## Operator handoff — what's needed to close Task 1 + Task 3

1. Browse `/mnt/mossrock/shared/mushdatadump-prod/` (or the wider mushdatadump corpus
   at `/mnt/mossrock/shared/mushdatadump/`) for 5-10 representative 2025-notebook pages.
2. For each, create `src/agents/alerter/test/eval/ingestion/fixtures/notebook-2025/<page-id>/`
   containing:
   - `image.jpg` (symlink into the corpus is fine; do not copy large binaries into git)
   - `manifest.json` — `{name, year:2025, corpus_context:{default_year:2025, source:'paper_log'}, expected_capture_kind, regression_guard:true}`
   - `ground-truth.json` — `{drafts: [...]}` with `type`, `event_date`, `asset_ref` or `groups[].parent.value`, `qty.value`, `event_kind` per draft; `event_date` MUST start with `2025-`
   - `mock-extraction.json` — once-produced raw Anthropic tool_use response (run `EVAL_RUN_LIVE=1` once per fixture and save the verbatim response per memory `[[feedback_persist_paid_results_default]]`; alternatively hand-author one matching the ground truth — the hermetic test only validates envelope shape, not LLM realism)
3. Run `cd src/agents/alerter && npx jest test/eval/ingestion/notebook-2025.test.js` — expect green.
4. Optionally smoke `npm run test:eval` with `ANTHROPIC_API_KEY` for live-LLM
   spot-check (paid; ~$0.10/fixture for Sonnet 4.6).
5. Signal "Phase 54 unblocked" to the orchestrator.

## Verification

- `cd src/agents/alerter && npm run test:eval-ingestion` — full ingestion suite green (49 passed, 7 skipped); `notebook-2025.test.js` passes the wiring assertion and skips per-fixture cases (expected today).

## Deviations from Plan

**[Plan-acknowledged deviation] Task 1 not auto-curated; Task 3 blocking checkpoint surfaced.**
Per the orchestrator's preamble and the plan's `checkpoint:human-verify` gate=blocking
on Task 3, the executor scaffolded the harness and STOPPED. No labels were
hallucinated. No fixtures were committed. Phase 54 remains blocked as designed.

## Self-Check: PASSED

- `src/agents/alerter/test/eval/ingestion/notebook-2025-loader.js` exists and exports `loadNotebook2025Corpus`
- `src/agents/alerter/test/eval/ingestion/notebook-2025.test.js` exists and runs green
- `src/agents/alerter/test/eval/ingestion/fixtures/notebook-2025/README.md` documents the operator handoff
- `src/agents/alerter/package.json` includes a `test:eval` script with `EVAL_RUN_LIVE=1`
- Commit `a2467ea` present in `git log --oneline`
- No fake / placeholder fixtures committed under `fixtures/notebook-2025/`
