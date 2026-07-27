---
phase: 62-farmos-write-path
plan: "06"
subsystem: farmos-write-path
tags: [farmos, logs, upsert, tdd, port]
dependency_graph:
  requires: ["62-02", "62-03"]
  provides: ["logs.py: create_log, upsert_log, LOG_STABLE_KEYS"]
  affects: ["commit pipeline log writes"]
tech_stack:
  added: []
  patterns: ["TDD RED/GREEN", "upsert-by-stable-key", "JSON:API"]
key_files:
  created:
    - src/farm-agent/farm_agent/farmos/logs.py
    - src/farm-agent/tests/test_farmos_logs.py
  modified: []
decisions:
  - "Port opts keys to snake_case (asset_ids, file_ids, draft_id, audit_logger) for Python idiom; test fixtures use snake_case throughout"
  - "audit_logger passed as dict with log_commit callable key (matches Python client dict pattern); not an object with method"
  - "LOG_STABLE_KEYS seeding entry is a module-level function reference (not lambda) for clarity and testability"
metrics:
  duration: "214s"
  completed_date: "2026-06-28"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
---

# Phase 62 Plan 06: logs.py -- Native Log Types + Upsert-by-Stable-Key Summary

Faithful Python port of the Node log layer (`farmos/logs.js`): native log types with the
`mushy:draft:{draftId}` notes marker and Phase-51 upsert-by-stable-key for `seeding` (B5
invariant: exactly one seeding log per child asset). All 38 tests green; TDD RED/GREEN gates
confirmed.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for create_log + LOG_STABLE_KEYS | 9a3852b | tests/test_farmos_logs.py |
| 1+2 (GREEN) | Port logs.py -- all modules + upsert_log | 7d68fc0 | farm_agent/farmos/logs.py |

## TDD Gate Compliance

- RED gate: commit `9a3852b` -- `test(62-06): add failing tests` (ModuleNotFoundError confirmed)
- GREEN gate: commit `7d68fc0` -- `feat(62-06): port logs.py` (38 tests pass)
- REFACTOR gate: not needed (code is clean on first pass)

## What Was Built

`farm_agent/farmos/logs.py` exports:

- `NATIVE_LOG_TYPES` -- ["seeding", "activity", "input", "observation", "harvest"]
- `LOG_TYPES` -- NATIVE + "seeding_session" (router guard)
- `UnsupportedLogTypeError(log_type)` -- raised before any farmOS call for non-native types
- `LogIdentityCollision(log_type, asset_id, matched_ids)` -- collision audit record
- `LOG_STABLE_KEYS` -- dict mapping "seeding" to a callable returning the
  `filter[asset.id][value]` filter path (urllib.parse.quote); other four native types map to None
- `create_log(client, log_type, opts)` -- POST /api/log/<type>; returns `{ok, log_id, http_status}`
- `upsert_log(client, log_type, opts)` -- lookup-by-stable-key then PATCH-merge-or-POST

Key upsert_log behaviors (all tested):

- null stable key (activity, input, observation, harvest): delegate to create_log, outcome="created"
- seeding miss: lookup returns empty -> create_log, outcome="created"
- seeding hit noop: existing log already has file+notes -> no PATCH, outcome="noop"
- seeding hit patch: incoming adds file id -> set-union files + merge notes -> PATCH, outcome="patched"
- 412 retry: PATCH returns 412 -> re-GET, re-merge, single retry PATCH
- identity mismatch: existing asset.data != incoming asset.data -> {ok:False, reason:"log_identity_mismatch"}
- collision: >1 match -> sort oldest-first (by attributes.created, then id), warnings includes
  "LogIdentityCollision:<n>", audit_logger called
- missing stable key (seeding with empty asset_ids): {ok:False, reason:"missing_stable_key"}

## Deviations from Plan

### Auto-adjusted for Python idiom

**[Rule 1 - Adaptation] opts dict keys use snake_case instead of camelCase**
- **Found during:** Task 1 (test writing)
- **Rationale:** Consistent with existing Python port conventions (client.py, merge.py). JS uses
  assetIds/fileIds/draftId; Python uses asset_ids/file_ids/draft_id/audit_logger.
- **Impact:** Tests and implementation match; no external consumers yet (farm_agent is internal).
- **Commits:** 9a3852b, 7d68fc0

None of the other behaviors deviated from the JS source.

## Known Stubs

None. All exported functions are fully implemented.

## Threat Flags

No new network endpoints or auth paths introduced. All farmOS calls go through the injected
client dict (same pattern as assets.py, files.py). Threat mitigations implemented:

- T-62-15: stable-key lookup-then-upsert enforces one seeding log per asset (B5 invariant)
- T-62-16: _arrays_equal_by_id asset-identity guard -> log_identity_mismatch (no PATCH on mismatch)
- T-62-17: LogIdentityCollision warning + oldest-canonical pick (no silent overwrite)

## Self-Check: PASSED

- [x] `src/farm-agent/farm_agent/farmos/logs.py` exists
- [x] `src/farm-agent/tests/test_farmos_logs.py` exists
- [x] Commit 9a3852b (RED): `git log --oneline | grep 9a3852b` -- found
- [x] Commit 7d68fc0 (GREEN): `git log --oneline | grep 7d68fc0` -- found
- [x] 38 tests pass: `uv run pytest tests/test_farmos_logs.py -q` -- 38 passed
- [x] `grep -c "mushy:draft:" logs.py` returns 2
