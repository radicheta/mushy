# notebook-2025 hermetic eval corpus (BACK-04 ship-gate)

**Status (2026-05-24):** EMPTY — operator curation pending.

This directory is the ship-gate corpus for Phase 53 BACK-04 (year-context
shim + small-N routing + capture_kind classifier). Phase 54 (backfill harness)
cannot kick off until at least one hand-labeled fixture lives here AND
`cd src/agents/alerter && npx jest test/eval/ingestion/notebook-2025.test.js`
runs green.

## What goes here

5-10 subdirs drawn from `/mnt/mossrock/shared/mushdatadump-prod/` covering:
- ≥ 3 true paper-log notebook scans (multi-row) → expected_capture_kind=`paper_log`
- ≥ 1 physical-object photo (e.g. DT tubs 0519 1 and 2) → expected_capture_kind=`physical_object_photo`
- ≥ 1 page where the year is genuinely absent → BACK-01 case (event_date starts with `2025-` because corpus_context.default_year=2025)

## Per-fixture layout

```
fixtures/notebook-2025/<page-id>/
  image.jpg                # symlink to the source under mushdatadump-prod
  manifest.json            # { name, year, corpus_context, expected_capture_kind, regression_guard:true }
  ground-truth.json        # { drafts: [...] } -- hand-labeled per-page expected envelope
  mock-extraction.json     # raw Anthropic tool_use response for hermetic replay
```

## Why this is operator-gated

Hand-labeling requires reading the actual notebook page (handwriting,
shorthand, abbreviations) and knowing the farm's notation conventions
(SEQ counters, species codes, parent-batch shorthand). The harness must
not fake labels — silent label errors would silently green-light the
extractor on the very pages it's supposed to fix.

The plan's Task 3 is a `checkpoint:human-verify` with `gate="blocking"`
for exactly this reason. The executor scaffolds the loader + test file
+ npm script and stops. Operator action:

1. Browse `/mnt/mossrock/shared/mushdatadump-prod/` for 5-10 representative pages.
2. For each, create a subdir here with the 4 artifacts above.
3. Run `cd src/agents/alerter && npx jest test/eval/ingestion/notebook-2025.test.js` (hermetic).
4. Optionally run `npm run test:eval` once with `ANTHROPIC_API_KEY` set
   to smoke the live LLM (paid; ~$0.10 per fixture for Sonnet 4.6).
5. Confirm "Phase 54 unblocked" to the orchestrator.

## When empty (today)

The test suite under `test/eval/ingestion/notebook-2025.test.js` ships
green-when-empty: it skips per-fixture cases and only asserts that the
loader is wired. This keeps CI green while Phase 54 stays explicitly
blocked.
