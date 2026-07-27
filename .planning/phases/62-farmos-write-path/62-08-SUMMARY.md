---
phase: 62-farmos-write-path
plan: "08"
subsystem: farm-agent/farmos/commits
tags: [farmos, commits, normalize, python-port, tdd]
dependency_graph:
  requires: ["62-05", "62-06", "62-07"]
  provides: ["commits/normalize.py", "commit_activity", "commit_input", "commit_observation", "commit_harvest"]
  affects: ["62-09-commit-seeding", "62-10-commit-router"]
tech_stack:
  added: []
  patterns: ["pure-function", "never-throws-handler", "best-effort-attachment", "field-scoped-image-upload"]
key_files:
  created:
    - src/farm-agent/farm_agent/farmos/commits/__init__.py
    - src/farm-agent/farm_agent/farmos/commits/normalize.py
    - src/farm-agent/farm_agent/farmos/commits/commit_activity.py
    - src/farm-agent/farm_agent/farmos/commits/commit_input.py
    - src/farm-agent/farm_agent/farmos/commits/commit_observation.py
    - src/farm-agent/farm_agent/farmos/commits/commit_harvest.py
    - src/farm-agent/tests/test_farmos_normalize.py
    - src/farm-agent/tests/test_farmos_commit_simple.py
  modified: []
decisions:
  - "normalize(draft) is pure and idempotent: guards prevent double-application on already-commit-shaped input (SCHEMA-03)"
  - "observation image attach uses field-scoped /api/asset/fungi/{uuid}/image route only; attachments_failed surfaced, never swallowed (T-62-22)"
  - "commit_observation warns via ctx.logger.warn dict key (JS parity) falling back to Python logging"
  - "harvest strain resolved from harvest_batch_name HBATCH regex when no explicit strain field"
metrics:
  duration: "~25 min"
  completed: "2026-06-28"
  tasks_completed: 2
  files_created: 8
---

# Phase 62 Plan 08: normalize.py + four simple commit handlers Summary

Pure extractor->commit shape normalizer and four per-type commit handlers (activity, input, observation, harvest) faithfully ported from their Node counterparts, with field-scoped image attachment for observations.

## What Was Built

### Task 1: normalize.py (commit 1660384)

Port of `commits/normalize.js`. Pure function: returns a new draft, never mutates input, idempotent on commit-shape input. Implements:
- Common transforms: `event_timestamp` ISO -> `timestamp` unix-sec floor; `asset_ref` -> `qr_codes` with `<UNKNOWN>` filter
- Per-type: activity name->activity_subtype; harvest source_block_refs->source_qr_codes + harvest_batch_id->name + qty_g->bags; seeding species->species_code; input recipe_lot prepend+delete; observation state append+delete
- 31 tests covering all transforms, idempotency, non-mutation, array non-aliasing

### Task 2: four commit handlers (commit 6f3652f)

Port of commit-activity.js, commit-input.js, commit-observation.js, commit-harvest.js. All handlers:
- Signature: `async commit_<type>(client, draft, ctx=None) -> {ok, asset_ids, log_ids, file_ids, ...}`
- Never-throws at handler level

Handler specifics:
- **commit_activity**: QR resolve -> activity log; `no_target_asset_for_activity` on empty resolve
- **commit_input**: QR resolve + ingredient serialization -> input log; same empty-QR reason string as JS
- **commit_observation**: QR resolve + field-scoped image upload (best-effort) -> observation log; `attachments_failed` surfaced, ok stays True on photo failure; uses `/api/asset/fungi/{uuid}/image` route (never the legacy 415 route)
- **commit_harvest**: source block pre-check + bag QR collision check + strain resolve + bag asset upsert + harvest log; 5 distinct failure reasons matching JS verbatim

23 handler tests covering all acceptance criteria.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ctx.logger dict pattern**
- **Found during:** Task 2 (commit_observation test run)
- **Issue:** Warning code checked `getattr(logger_obj, "warn")` but ctx.logger is a dict `{"warn": fn}`, not an object
- **Fix:** Added isinstance dict check before attribute fallback, mirroring JS `ctx.logger.warn(...)` dict-key call pattern
- **Files modified:** commit_observation.py
- **Commit:** 6f3652f (folded into task commit)

**2. [Rule 1 - Bug] Test grep caught comment strings**
- **Found during:** Task 2 test run
- **Issue:** Acceptance criteria `grep -rc "/api/file/file"` also matched docstring/comment text in commit_observation.py
- **Fix:** Rephrased two comments to say "legacy file route" without the literal path
- **Files modified:** commit_observation.py
- **Commit:** 6f3652f (folded into task commit)

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes beyond what the plan's threat model covers. T-62-21 (normalize mutation) mitigated by pure function + 31 tests. T-62-22 (silent photo drop) mitigated by field-scoped route + attachments_failed in every observation result. T-62-23 (handler exception) mitigated by try/except in commit_router (Plan 10) + never-throws handlers.

## Known Stubs

None. All four handlers wire directly to the real farmOS client methods (create_log, upsert_fungi_asset, resolve_qr, upload_field_attachments). No placeholder data.

## Self-Check: PASSED

Files created:
- [x] src/farm-agent/farm_agent/farmos/commits/__init__.py
- [x] src/farm-agent/farm_agent/farmos/commits/normalize.py
- [x] src/farm-agent/farm_agent/farmos/commits/commit_activity.py
- [x] src/farm-agent/farm_agent/farmos/commits/commit_input.py
- [x] src/farm-agent/farm_agent/farmos/commits/commit_observation.py
- [x] src/farm-agent/farm_agent/farmos/commits/commit_harvest.py
- [x] src/farm-agent/tests/test_farmos_normalize.py
- [x] src/farm-agent/tests/test_farmos_commit_simple.py

Commits:
- [x] 1660384: feat(62-08): port normalize.py
- [x] 6f3652f: feat(62-08): port commit_activity, input, observation, harvest handlers

Tests: 54 passed (31 normalize + 23 handlers)
