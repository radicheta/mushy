---
phase: 62-farmos-write-path
plan: 11
subsystem: farmos
tags: [commit-watchdog, fidelity-gate, boot-wiring, asyncio, drain-loop]
dependency_graph:
  requires: [62-04, 62-10]
  provides: [commit_watchdog_loop, tick_once, boot-farmos-wiring]
  affects: [farm_agent/boot.py, farm_agent/farmos/commit_watchdog.py, farm_agent/farmos/commit_db.py]
tech_stack:
  added: []
  patterns: [immediate-then-sleep asyncio loop, CancelledError re-raise, per-row never-throws, fidelity gate pre-commit guard, asyncio.Lock tick overlap prevention]
key_files:
  created:
    - src/farm-agent/farm_agent/farmos/commit_watchdog.py
    - src/farm-agent/tests/test_farmos_commit_watchdog.py
  modified:
    - src/farm-agent/farm_agent/boot.py
    - src/farm-agent/farm_agent/farmos/commit_db.py
    - src/farm-agent/tests/test_boot.py
decisions:
  - hold_for_fidelity added to commit_db.py (plan allowed helper or inline UPDATE; helper chosen for testability)
  - fidelity hold ask-back dispatched as log.WARNING (best-effort; no signal_client in watchdog scope)
  - commit_watchdog_task=None when farmos_integration=False (clean None guard in shutdown block)
metrics:
  duration: 20min
  completed: 2026-06-28
---

# Phase 62 Plan 11: Commit Watchdog + Boot Wiring Summary

Port `commit-watchdog.js` to an asyncio drain loop, wire the CSV fidelity gate as a pre-commit hold (FWR-03 / D-06), and integrate the shared farmOS client + watchdog task into boot.py (FWR-04 / FWR-01).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| TDD RED | Failing tests for commit_watchdog | fd6b603 | tests/test_farmos_commit_watchdog.py |
| 1 | commit_watchdog.py + commit_db hold helper | 830b35e | farmos/commit_watchdog.py, farmos/commit_db.py |
| 2 | boot.py wiring + test_boot new assertions | 94e8748 | boot.py, tests/test_boot.py |

## What Was Built

**commit_watchdog.py** -- `tick_once` + `commit_watchdog_loop` + `_is_transient`:

- `_is_transient(result)`: port of JS classifier -- transient when http_status None, >=500, or reason matches timeout/abort/econnreset/econnrefused.
- `tick_once(pool, farmos_client, config, *, lock, db, router, csv_rows)`: one watchdog tick. Sequence: `release_stale_locks` -> `find_confirmed_candidates(origin='python')` -> per row: `acquire_commit_lock`; fidelity gate BEFORE router call; `mark_committed` / `requeue_for_retry` / `mark_failed`. Never-throws per-row (Exception -> WARNING + continue). CancelledError re-raised.
- `commit_watchdog_loop(pool, farmos_client, config)`: immediate-then-sleep loop. Loads CSV once at call time. Mirrors `confirm_watchdog_loop` exactly.

**commit_db.py** -- `hold_for_fidelity(pool, draft_id)`:

- CAS transition: `status='committing'` -> `'fidelity_cross_check_unverified'`, `origin='python'` preserved.
- Never-throws; returns `{ok, rowcount}`.

**boot.py** wiring:

- Imports `create_farmos_client`, `commit_watchdog_loop`.
- Constructs farmOS client (reusing existing `httpx.AsyncClient http`) when `config.farmos_integration` is True.
- `commit_watchdog_task = asyncio.create_task(commit_watchdog_loop(...))` alongside `confirm_task`.
- Shutdown: `commit_watchdog_task.cancel()` + `await` with `CancelledError` swallow.
- T-56-06-01 compliance: `farmos_url`, `farmos_username`, `farmos_password` never appear in log calls.

## Fidelity Gate Pre-Commit Hold (D-06 / T-62-30)

The critical invariant: `check_fidelity(locked_row, csv_rows)` is called BEFORE `router.commit()`. On `reason == "strain_mismatch"`:

1. `db.hold_for_fidelity(pool, draft_id)` transitions draft to `fidelity_cross_check_unverified`.
2. `log.warning` logs draft_id, draft_strain, csv_strain, ask_back_msg (best-effort dispatch).
3. `continue` -- `commit_router.commit` is NEVER called for that row.

Test `test_tick_fidelity_strain_mismatch_never_calls_router` asserts via spy that `router.calls == []`.

## Test Results

```
20 passed (test_farmos_commit_watchdog.py)
4 skipped (test_boot.py -- no test DB on this host; DB-required, same skip pattern as existing boot tests)
52 passed, 6 skipped (farmos test suite: commit_watchdog + fidelity_gate + commit_db)
```

## Deviations from Plan

### Auto-added Missing Critical Functionality

**1. [Rule 2 - Missing] hold_for_fidelity added to commit_db.py**
- **Found during:** Task 1
- **Issue:** commit_db.py had no function to transition a draft to `fidelity_cross_check_unverified`. The plan's action said "a commit_db helper or an UPDATE setting status"; the helper was chosen for testability (injectable via `db=` parameter in tick_once).
- **Fix:** Added `hold_for_fidelity(pool, draft_id)` and `_HOLD_FIDELITY_SQL` to commit_db.py.
- **Files modified:** src/farm-agent/farm_agent/farmos/commit_db.py
- **Commit:** 830b35e

**2. [Rule 2 - Design] Fidelity ask-back dispatch as log.WARNING (best-effort)**
- **Found during:** Task 1
- **Issue:** Plan says "dispatching the ask_back_msg best-effort" but `commit_watchdog_loop` has no `signal_client` in scope (unlike confirm watchdog). The watchdog's interface is `(pool, farmos_client, config)` and adding a signal_client would require a broader signature change not in scope for this plan.
- **Fix:** ask_back_msg dispatched as `log.warning` with full context (draft_id, strains, message). Future plan can add Signal send when the watchdog signature is extended.
- **Files modified:** src/farm-agent/farm_agent/farmos/commit_watchdog.py
- **Commit:** 830b35e

## Known Stubs

None. All functionality is wired. Boot test assertions skip (not stub) due to no test DB on this host -- the skip condition is identical to the two existing boot tests.

## Threat Flags

No new network endpoints, auth paths, or schema changes beyond what the plan's threat model covers (T-62-30 thru T-62-33 all mitigated).

## Self-Check: PASSED

- FOUND: src/farm-agent/farm_agent/farmos/commit_watchdog.py
- FOUND: src/farm-agent/tests/test_farmos_commit_watchdog.py
- FOUND: commits fd6b603, 830b35e, 94e8748
- No secret logging in boot.py
- No stubs in created files
