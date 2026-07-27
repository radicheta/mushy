---
phase: 62-farmos-write-path
plan: 10
subsystem: farmos-write-path
tags: [commit-router, commit-db, origin-guard, dispatch, DAO, psycopg3]
dependency_graph:
  requires: ["62-01", "62-08", "62-09"]
  provides: ["commit_router.commit", "commit_db.find_confirmed_candidates", "commit_db.acquire_commit_lock", "commit_db.mark_committed", "commit_db.mark_failed", "commit_db.requeue_for_retry", "commit_db.release_stale_locks"]
  affects: ["farm_agent.farmos.commit_watchdog"]
tech_stack:
  added: []
  patterns: ["psycopg3 never-throws DAO", "CAS WHERE status= atomic transition", "origin guard SELECT + SET", "dispatch table with uniform envelope", "time.monotonic latency measurement"]
key_files:
  created:
    - src/farm-agent/farm_agent/farmos/commits/commit_router.py
    - src/farm-agent/farm_agent/farmos/commit_db.py
    - src/farm-agent/tests/test_farmos_commit_router.py
    - src/farm-agent/tests/test_farmos_commit_db.py
  modified: []
decisions:
  - "find_confirmed_candidates uses cursor.description to build dicts from SELECT * (avoids hardcoded column list that would need updating with each migration)"
  - "DB-independent tests assert SQL text for origin guard (17 tests always run); 6 DB-gated tests skip gracefully when :5434 not available"
  - "FakePool captures last_sql/last_params via _FakeConn for SQL assertion without a real DB"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-28"
  tasks_completed: 2
  tasks_total: 2
  files_created: 4
  files_modified: 0
---

# Phase 62 Plan 10: commit_router.py + commit_db.py Summary

**One-liner:** Six-handler dispatch router via normalize() + origin-guarded Python commit-lifecycle DAO that stamps origin='python' on every signal_draft write so the live Node watchdog never drains Python rows.

## What Was Built

### Task 1: commit_router.py (TDD)

`src/farm-agent/farm_agent/farmos/commits/commit_router.py` -- ports `commit-router.js` exactly:

- `DISPATCH` dict maps all six log types to their handler coroutines (seeding, activity, input, observation, harvest, seeding_session)
- `commit(client, draft, ctx)`: guards log_type against LOG_TYPES, applies `normalize(draft)` before dispatch (original draft NOT mutated), measures latency via `time.monotonic`, normalizes result into uniform envelope
- `UnsupportedLogTypeError` from handler -> `reason='unsupported_log_type'` envelope
- Any other exception -> `ok=False, reason=str(e)` envelope
- All envelopes carry: `ok, asset_ids, log_ids, file_ids, attachments_failed, latency_ms, reason`

### Task 2: commit_db.py (TDD)

`src/farm-agent/farm_agent/farmos/commit_db.py` -- ports `commit-db.js` write helpers with origin guard:

| Function | SQL Guard | origin='python' |
|---|---|---|
| `find_confirmed_candidates` | WHERE status='confirmed' AND origin='python' | SELECT filter |
| `acquire_commit_lock` | WHERE id=%s AND status='confirmed' | SET origin='python' |
| `mark_committed` | WHERE id=%s AND status='committing' | SET origin='python' |
| `mark_failed` | WHERE id=%s AND status='committing' | no SET (terminal) |
| `requeue_for_retry` | WHERE id=%s AND status='committing' | SET origin='python' |
| `release_stale_locks` | WHERE status='committing' AND committed_at_attempt < stale interval | no SET |

All helpers are never-throws (try/except BLE001). Write helpers return `{ok, rowcount}` or `{ok, reason}`. `find_confirmed_candidates` returns `[]` on error.

`grep -c "origin='python'" commit_db.py` = 12 (4+ SQL occurrences satisfy acceptance criteria).

## Tests

- `test_farmos_commit_router.py`: 14 tests -- DISPATCH completeness, unsupported log_type, normalize applied + draft not mutated, handler exception envelope, envelope fields on success, missing id lists default to []
- `test_farmos_commit_db.py`: 23 tests (17 DB-independent, 6 DB-gated) -- never-throws on fake raising pool, SQL text asserts origin='python' in all four guarded functions, CAS rowcount=0 on race, DB round-trips for committed/failed/requeue/stale-locks

Full suite: 625 passed, 33 skipped (all skips are DB-gated, no :5434 in CI).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] find_confirmed_candidates double-query refactored**
- **Found during:** Task 2 implementation review
- **Issue:** First draft ran the SELECT twice (once to check rows, once to get column names) -- wasteful and could return inconsistent results
- **Fix:** Used `cur.description` on the single psycopg3 cursor returned by `conn.execute()` to extract column names in one pass
- **Files modified:** src/farm-agent/farm_agent/farmos/commit_db.py
- **Commit:** 6ff792c

## Commits

| Task | Commit | Description |
|---|---|---|
| Task 1 (router) | c9efffd | feat(62-10): commit_router.py six-handler dispatch via normalize + tests |
| Task 2 (DAO) | 6ff792c | feat(62-10): commit_db.py origin-guarded commit-lifecycle DAO + tests |

## Self-Check: PASSED

Files exist:
- src/farm-agent/farm_agent/farmos/commits/commit_router.py: FOUND
- src/farm-agent/farm_agent/farmos/commit_db.py: FOUND
- src/farm-agent/tests/test_farmos_commit_router.py: FOUND
- src/farm-agent/tests/test_farmos_commit_db.py: FOUND

Commits:
- c9efffd: FOUND
- 6ff792c: FOUND

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns introduced. All writes are to the existing `signal_draft` table (already in scope from Phase 40). The `origin='python'` guard is the mitigation for T-62-27 (row drainage by Node watchdog).

## Known Stubs

None.
