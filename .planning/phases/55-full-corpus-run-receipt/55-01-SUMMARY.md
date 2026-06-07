---
phase: 55-full-corpus-run-receipt
plan: "01"
subsystem: backfill-harness
tags: [backfill, receipt, BACK-09, BACK-10, tooling]
dependency_graph:
  requires: [54-04, 54.1-02]
  provides: [BACK-09-tooling, BACK-10-tooling]
  affects: [scripts/backfill-notebook.js, scripts/build-backfill-receipt.js]
tech_stack:
  added: []
  patterns: [TDD-RED/GREEN, additive-flag-extension, copy-same-scrubbed-body]
key_files:
  created: []
  modified:
    - src/agents/alerter/scripts/backfill-notebook.js
    - src/agents/alerter/scripts/backfill-notebook.test.js
    - src/agents/alerter/scripts/build-backfill-receipt.js
    - src/agents/alerter/scripts/build-backfill-receipt.test.js
decisions:
  - "--all-pages sets opts.limit=Infinity in main() after help short-circuit; selectPages already handles Infinity correctly (verified)"
  - "notes copy-out uses the same scrubbed body string from buildReceipt (no second render) per Pitfall 5 in research"
  - "computePerShapeStats seeded with KNOWN_SHAPES so zero-commit shapes appear in table; unexpected shapes get their own bucket"
  - "notes paths derived in main() finally{} only when opts.allPages is true; Cycle runs pass no notes params"
metrics:
  duration: "~14 minutes"
  completed: "2026-06-07T21:02:18Z"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 4
---

# Phase 55 Plan 01: Backfill Harness Extension (BACK-09/10 tooling) Summary

Extends the Phase 54 backfill harness to support full-corpus runs: adds `--all-pages` flag,
`buildUuidJsonl`/`computePerShapeStats` helpers, and a BACK-10 per-shape stats section in the
receipt with optional copy-out to git-tracked `.planning/notes/`.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | --all-pages flag in backfill-notebook.js | eb711e5 | backfill-notebook.js, backfill-notebook.test.js |
| 2 | buildUuidJsonl + computePerShapeStats | 17d5c22 | build-backfill-receipt.js, build-backfill-receipt.test.js |
| 3 | notes copy-out + BACK-10 section wired | e21aa64 | build-backfill-receipt.js, backfill-notebook.js, build-backfill-receipt.test.js |

## What Was Built

**Task 1 -- `--all-pages` flag:**
- `parseArgs`: added `allPages: false` default + `if (arg === '--all-pages') { opts.allPages = true; continue; }` boolean branch
- `main()`: `if (opts.allPages) opts.limit = Infinity;` after help short-circuit, before prod-guard
- USAGE string updated with `--all-pages` documentation (ASCII-only)
- Dry-run with `--corpus-dir=/mnt/slime-kingdom/shared/mushdatadump/jpeg` selects all 73 pages

**Task 2 -- `buildUuidJsonl` + `computePerShapeStats`:**
- `KNOWN_SHAPES` constant: `['seeding', 'observation', 'activity', 'harvest', 'input']`
- `buildUuidJsonl(runSummary)`: one JSONL line per asset UUID (type:'asset', with block_name) and per log UUID (type:'log'); trailing newline when non-empty; empty string for empty/null input
- `computePerShapeStats(runSummary)`: buckets commits by log_type (seeded with KNOWN_SHAPES); counts ok/held/failed/n per shape + total; returns `{ tag: 'bulk_backfill_auto_yes', by_shape, total }` -- literal tag required by BACK-10 for v1.13 exclusion
- Both exported; 22 new unit tests covering asset/log lines, empty, held, failed, skipped, unknown-shape, total accumulation

**Task 3 -- notes copy-out + BACK-10 section:**
- `buildReceipt` accepts `notesReceiptPath` and `notesJsonlPath` (default undefined)
- BACK-10 section inserted before `## Farmer review`: markdown table (shape | n | ok | held | failed | yes_rate_pct) with `tag: bulk_backfill_auto_yes` line; yes_rate_pct rounds to 1 decimal, n=0 -> 'n/a' (no division-by-zero)
- Copy-out uses the SAME `body` string after the em-dash scrub (no second render)
- `main()` finally{}: when `opts.allPages`, derives date-stamped basename and passes notes paths; Cycle runs unchanged
- 7 new unit tests: BACK-10 content/counts, notes byte-equality, JSONL write, mkdir-p, Cycle regression guard

## Verification

**Scripts test suite:** 112 tests pass (71 backfill-notebook + 41 build-backfill-receipt), 0 fail.

**Dry-run corpus check:**
```
node scripts/backfill-notebook.js --all-pages --dry-run --corpus-dir=/mnt/slime-kingdom/shared/mushdatadump/jpeg
```
Selects 73 pages (IMG_3775..IMG_3847 PAGE_REGEX matches); no spend.

**Full alerter suite note:** 13 pre-existing failures from missing npm packages (zod, @anthropic-ai/sdk, pg, jimp, etc.) unrelated to this plan. These existed before this plan executed. The plan's specific test files are fully green.

## Deviations from Plan

None -- plan executed exactly as written. The BACK-10 per-shape table includes a `total` row as specified; the em-dash scrub regex in the original code already handled both `--` and `-` (Unicode en/em-dash); the copy-out correctly reuses the scrubbed body.

## Threat Flags

None -- no new network endpoints, auth paths, or schema changes introduced. Receipt copy-out uses the existing em-dash scrub and writes only to `.planning/notes/` (git-tracked, no credentials/tokens in output per T-55-02). The literal `tag: 'bulk_backfill_auto_yes'` is hard-coded in computePerShapeStats (T-55-01).

## Self-Check: PASSED

Files exist:
- src/agents/alerter/scripts/backfill-notebook.js -- FOUND
- src/agents/alerter/scripts/backfill-notebook.test.js -- FOUND
- src/agents/alerter/scripts/build-backfill-receipt.js -- FOUND
- src/agents/alerter/scripts/build-backfill-receipt.test.js -- FOUND

Commits exist:
- eb711e5 -- Task 1
- 17d5c22 -- Task 2
- e21aa64 -- Task 3
