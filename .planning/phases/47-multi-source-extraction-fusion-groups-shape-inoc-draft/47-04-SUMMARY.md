---
phase: 47-multi-source-extraction-fusion-groups-shape-inoc-draft
plan: 04
subsystem: extraction
tags: [preview-builder, seeding-session, placeholder, gray-area-4-lock]
dependency_graph:
  requires: [Phase 47-01 SeedingSession schema]
  provides:
    - "buildPreview seeding_session branch (placeholder until Phase 48)"
    - "buildSeedingSessionPlaceholder helper (groups-shape renderer)"
  affects:
    - "Phase 47-03 pipeline ask-back rendering (placeholder line 3 marker)"
    - "Phase 48 commit-side group-by-parent preview (will replace this branch)"
tech_stack:
  added: []
  patterns:
    - "Early-return branch in buildPreview before flat-field renderer (different-shape body)"
    - "Negative-assertion testing: conflict candidate values + literal 'conflict' word indexOf -1"
key_files:
  created: []
  modified:
    - src/agents/alerter/src/extraction/preview-builder.js
    - src/agents/alerter/test/extraction/sanitize.test.js
decisions:
  - "Headline line uses raw YYYY-MM-DD event_date (matches plan test spec '(a) 2026-05-22'); humanized 'May 22' format deferred to Phase 48's production preview where farmer locale + naming can be co-designed"
  - "Total child count prefers child_block_names.value.length when present; falls back to qty.value otherwise (handles partial-photo sessions per multi-parent-inoc-batch shape)"
  - "Phase-48-marker line is conditional: 'Awaiting block-number to start at.' when needs_input==='starting_seq', else 'Group-by-parent preview coming in Phase 48.' This keeps Plan 47-03's ask-back path uncluttered by the Phase 48 IOU"
  - "NO_PARENT sentinel renders as 'no parent recorded' in farmer text; raw sentinel string never appears in output"
  - "Tests landed in existing sanitize.test.js (the canonical preview-builder test file by convention)"
metrics:
  duration: ~12min
  tasks_completed: 1
  files_created: 0
  files_modified: 2
  tests_added: 7
  tests_total_passing: 903
  completed_date: 2026-05-23
---

# Phase 47 Plan 04: preview-builder placeholder for seeding_session Summary

Minimal placeholder branch in `buildPreview` so groups-shape drafts no longer crash or fall through to the flat-field renderer. Phase 48 ships the production group-by-parent table; this plan is the safety seam.

## What Shipped

### Final placeholder text

For the canonical May-22 draft (no ask-back), `buildPreview` returns:

```
11 blocks across 5 groups for 2026-05-22

Group-by-parent preview coming in Phase 48.
SHI x 3 from 260118_SHI_25
KOY x 2 from 260201_KOY_1
KOY x 2 from 260203_KOY_2
KOY x 2 from 260210_KOY_3
KOY x 2 from 260215_KOY_4
```

When `needs_input === 'starting_seq'`, line 3 becomes `Awaiting block-number to start at.` instead of the Phase 48 marker; the per-group lines still render so the farmer can sanity-check the species/qty/parent shape before answering the SEQ ask-back.

### Tests landed

7 new tests in `src/agents/alerter/test/extraction/sanitize.test.js` under `describe('buildPreview: seeding_session placeholder branch', ...)`:

- (a) May-22 fixture: 11 blocks across 5 groups, event_date present, 5 per-group lines
- (b) needs_input='starting_seq' renders "Awaiting block-number to start at." AND suppresses the Phase 48 marker
- (c) **negative assertion (Gray Area 4 lock)**: conflict candidate values, the literal word "conflict", and the resolution marker `photo_wins` all `indexOf -1` against output
- (d) `parent.value === 'NO_PARENT'` renders "no parent recorded"; raw sentinel never appears
- (e) regression: legacy seeding type still uses field-listing body, no placeholder leak
- (f) output has no em-dashes
- (g) child_block_names length wins over qty.value when both present (partial-photo support)

## Verification

```
$ cd src/agents/alerter && npx jest test/extraction/sanitize.test.js --no-coverage
Test Suites: 1 passed, 1 total
Tests:       21 passed, 21 total       # 14 legacy + 7 new

$ npx jest --no-coverage                # full alerter suite
Test Suites: 2 skipped, 66 passed, 66 of 68 total
Tests:       9 skipped, 903 passed, 912 total      # +7 vs phase 47-01 baseline (872 -> 903 with intermediate plans)

$ grep -in "draft\.conflicts" src/agents/alerter/src/extraction/preview-builder.js
# (zero matches in code; only doc-comment references warning against it)
```

## Deviations from Plan

1. **Date format kept as YYYY-MM-DD, not humanized to "May 22".** The orchestrator style_locks asked for "May 22" format, but the plan's test (a) explicitly asserts the output `string contains "2026-05-22"`. The plan is authoritative; humanizing the date would have made the spec test fail. Production farmer-facing humanization deferred to Phase 48's preview redesign where locale + farmer naming can be co-designed (the placeholder line itself already announces "Phase 48").

2. **Added test (g) beyond plan's 5-test ask.** Plan listed 5 tests (a-e); shipped 7 (added (f) em-dash sanitization sanity-check for the new branch + (g) total-count tie-breaker behavior). Both pulled their weight: (g) caught and locked the qty-vs-names precedence decision recorded above.

No behavioral deviation from the `<behavior>` block; the 4-line format (headline / blank / marker / per-group) is honored exactly.

## Known Stubs

The whole branch IS a stub — that is the plan's purpose. The "Group-by-parent preview coming in Phase 48." line is explicit operator-visible acknowledgement that Phase 48 owns the production renderer. No other stubs.

## Self-Check: PASSED

- [x] `src/agents/alerter/src/extraction/preview-builder.js` modified (early-return branch + buildSeedingSessionPlaceholder helper)
- [x] `src/agents/alerter/test/extraction/sanitize.test.js` modified (7 new tests added)
- [x] All 21 sanitize.test.js tests green (14 legacy untouched + 7 new)
- [x] Full alerter suite 903 passing, 0 failing
- [x] Negative assertion (c) passes: conflicts never leak to farmer output
- [x] Source-file `grep -i "draft\.conflicts"` returns zero code references (only doc-comments)
