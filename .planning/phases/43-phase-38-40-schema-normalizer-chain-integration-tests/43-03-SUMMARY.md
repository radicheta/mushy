---
phase: 43
plan: "03"
subsystem: alerter/farmos/commits
tags: [normalizer, commit-router, dispatch, schema]
dependency_graph:
  requires: [43-01]
  provides: [router normalizes before dispatch]
  affects: [commit-seeding, commit-activity, commit-input, commit-observation, commit-harvest]
tech_stack:
  added: []
  patterns: [pre-dispatch normalize, idempotent transform]
key_files:
  modified:
    - src/agents/alerter/src/farmos/commits/commit-router.js
decisions:
  - "Top-of-file require for normalize rather than inline require -- cleaner, consistent with other module imports"
  - "Two-line change: one require line + one normalize() call replacing bare fn(client, draft, ctx)"
metrics:
  duration: "~5 min"
  completed: "2026-05-16"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
---

# Phase 43 Plan 03: Normalize Wire-In Summary

One-liner: normalize() wired into commit-router.js dispatch path per D-02 -- extractor-shape drafts now pass through the idempotent normalizer before every commit handler call.

## What Was Done

Single task executed:

**Task 1: Wire normalize() into commit-router.js**

Added `const { normalize } = require('./normalize');` at the top of the file alongside the other commit-module requires, then replaced:

```js
const r = await fn(client, draft, ctx);
```

with:

```js
// Phase 43 D-02: normalize extractor-shape -> commit-shape before dispatch.
// Original signal_draft.draft_json is NOT mutated; normalized copy is local only.
const r = await fn(client, normalize(draft), ctx);
```

The original `draft` parameter is not mutated. `normalize()` returns a new object. The audit-trail extractor-shape farmers see in askback previews is preserved.

## Verification

- `grep -c "normalize" commit-router.js` returns 4 (>= 2 required by plan)
- `cd src/agents/alerter && npm test` exits 0: 684 tests pass, 8 pre-existing skips
- No test modifications required -- confirms SCHEMA-03 idempotency over ~50+ existing commit-shape fixtures

## Commits

| Hash    | Message                                                         |
| ------- | --------------------------------------------------------------- |
| 082271a | feat(43-03): wire normalize() into commit-router dispatch path (D-02) |

## Deviations from Plan

None. Plan executed exactly as written.

## Self-Check: PASSED

- [x] `src/agents/alerter/src/farmos/commits/commit-router.js` modified and committed at 082271a
- [x] `grep -c "normalize"` returns 4
- [x] All 684 tests pass
- [x] Original `signal_draft.draft_json` not mutated (normalize returns new object, local frame only)
