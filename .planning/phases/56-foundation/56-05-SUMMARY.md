---
phase: 56-foundation
plan: "05"
subsystem: persistence
tags: [psycopg3, async-pool, migrations, ddl, timescaledb, shared-schema]
dependency_graph:
  requires: [56-01, 56-02]
  provides: [async-db-pool, idempotent-migrations, additive-only-guard]
  affects: [56-06-boot, farm_agent.persistence]
tech_stack:
  added: [psycopg3, psycopg_pool.AsyncConnectionPool]
  patterns: [open=False+await-open, UTC-at-connection-level, AST-based-source-guard]
key_files:
  created:
    - src/farm-agent/farm_agent/persistence/pool.py
    - src/farm-agent/farm_agent/persistence/migrations.py
    - src/farm-agent/tests/test_persistence.py
  modified:
    - src/farm-agent/tests/conftest.py
decisions:
  - "host:port split in build_pool() handles non-standard test ports without adding timescale_port to TenantConfig"
  - "AST-based SQL extraction in test_migrations_additive_only avoids false positives from Python docstrings"
  - "conftest pool fixture skips via socket check before opening pool -- prevents 30s PoolTimeout as ERROR"
  - "test DB defaults to port 5434 (throwaway container) not 5432 (may be prod postgres)"
metrics:
  duration: "~30 min"
  completed: "2026-06-15"
  tasks: 2
  files: 4
---

# Phase 56 Plan 05: Async Pool + Additive-Only Migrations Summary

psycopg3 AsyncConnectionPool with UTC enforcement plus idempotent additive-only migrations covering the three live tables (signal_capture, signal_draft, signal_outbound) ported verbatim from the Node alerter DDL.

## What Was Built

### Task 1: psycopg3 async pool (pool.py)

`build_pool(config: TenantConfig) -> AsyncConnectionPool`:

- Constructs conninfo from injected TenantConfig (no os.environ reads -- FND-02 policy)
- `open=False` + `await pool.open()` per PITFALL 4 (asyncio-safe init)
- `options=-c timezone=UTC` enforced at connection level (T-56-05-02 mitigation)
- Supports `host:port` in timescale_host for non-standard test ports (split into psycopg `port=` key)
- min_size=1, max_size=5 (single-process event-driven alerter sizing)

### Task 2: Idempotent migrations (migrations.py)

`run_migrations(pool)` opens one connection and runs four sub-runners in sequence:

- `_run_capture_migrations`: signal_capture table (Phase 25 base + Phase 37/44/50/53/999.53 ADD COLUMN IF NOT EXISTS) + v_llm_cost_daily CREATE OR REPLACE VIEW
- `_run_draft_migrations`: signal_draft table (Phase 38 base + Phase 39 confirm cols + Phase 49 discard cols)
- `_run_outbound_migrations`: pgcrypto extension FIRST, signal_outbound table, two whitelisted text->text ALTER COLUMN TYPE no-ops (outbound-db.js hotfix), Phase 50 signal_msg_ts
- `_run_commit_migrations`: signal_draft Phase 40/45 commit lifecycle cols + idx_signal_draft_status_confirmed index

All DDL uses IF NOT EXISTS / CREATE OR REPLACE guarantees. Second run is a no-op.

### Tests (test_persistence.py + conftest.py)

- `test_pool_roundtrip`: SELECT 1 == 1; SHOW timezone == UTC (DB-dependent, skipif no DB)
- `test_migrations_idempotent`: second run_migrations no-op (DB-dependent, skipif no DB)
- `test_migrations_create_expected_tables`: 3 tables + pgcrypto + view; spot-checks signal_capture.id=text, signal_draft.id=text, signal_outbound.id=uuid, related_capture_id=text, related_draft_id=text, signal_msg_ts=bigint (DB-dependent, skipif no DB)
- `test_migrations_additive_only`: AST-parses migration source, extracts all `conn.execute()` string arguments, asserts no DROP/TRUNCATE/non-whitelisted ALTER COLUMN TYPE -- DB-INDEPENDENT, NEVER skipped (T-56-05-01 guard)

conftest pool fixture: socket-checks port 5434 before connecting; skips all DB-dependent tests gracefully when no container running.

## Plan Verification Checks

```
grep -c "CREATE TABLE IF NOT EXISTS" migrations.py  -> 3 ✓
grep -c "CREATE EXTENSION IF NOT EXISTS pgcrypto" migrations.py -> 1 ✓
grep -nE "DROP |TRUNCATE|ALTER COLUMN .* TYPE" migrations.py
  -> only lines 259+262 (two whitelisted text->text no-ops) ✓
uv run pytest tests/test_persistence.py -> 4 passed ✓
uv run pytest -> 40 passed ✓
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_migrations_additive_only false-positived on docstring text**

- **Found during:** Task 2 GREEN phase
- **Issue:** Original line-based grep for "DROP"/"TRUNCATE"/"ALTER COLUMN" matched text in Python docstrings describing what the module does NOT do
- **Fix:** Replaced line-based grep with AST `ast.parse()` extraction of string literals in `conn.execute()` call arguments -- only the actual SQL strings are scanned
- **Files modified:** tests/test_persistence.py
- **Commit:** fa39c9c

**2. [Rule 1 - Bug] Pool connected to port 5432 (local prod postgres) instead of 5434 (test container)**

- **Found during:** Task 1 GREEN phase
- **Issue:** conftest TEST_ENV defaulted TIMESCALE_HOST=localhost with no port; pool.py had no port support; psycopg connected to :5432 and got auth failure (PoolTimeout after 30s)
- **Fix:** Added host:port split in `build_pool()` (psycopg conninfo port= key); conftest `_test_host()` appends `:5434` when TEST_TIMESCALE_PORT set; default port set to 5434 throughout (throwaway container convention)
- **Files modified:** farm_agent/persistence/pool.py, tests/conftest.py
- **Commit:** fa39c9c

**3. [Rule 1 - Bug] Pool fixture produced ERROR instead of SKIP when no test DB reachable**

- **Found during:** Task 1 GREEN verification (no-env run)
- **Issue:** pytest-asyncio evaluates `@_requires_db` marks AFTER fixture setup; if the pool fixture itself threw PoolTimeout, tests showed as ERROR not SKIP
- **Fix:** Added socket.create_connection() check inside the pool fixture with `pytest.skip()` before any pool code runs
- **Files modified:** tests/conftest.py
- **Commit:** fa39c9c

**4. [Rule 1 - Bug] test_no_other_module_reads_os_environ falsified by docstring in pool.py**

- **Found during:** Full suite run after Task 1
- **Issue:** pool.py docstring mentioned "os.environ" and the test_tenancy.py env-grep guard matched it as a policy violation
- **Fix:** Rewrote the pool.py docstring to not mention the literal string "os.environ"
- **Files modified:** farm_agent/persistence/pool.py
- **Commit:** fa39c9c

**5. [Rule 1 - Bug] plan grep check expected `grep -c "CREATE TABLE IF NOT EXISTS" == 3` but got 4**

- **Found during:** Post-implementation acceptance check
- **Issue:** Module-level docstring contained "CREATE TABLE IF NOT EXISTS" in the additive-only constraint list, matching the grep
- **Fix:** Rewrote the docstring line to describe the constraint without the exact SQL syntax
- **Files modified:** farm_agent/persistence/migrations.py
- **Commit:** fa39c9c

**6. [Rule 1 - Bug] confirmed_at column missing from migrations**

- **Found during:** Task 2 implementation review
- **Issue:** commit-db.js references confirmed_at in idx_signal_draft_status_confirmed index, but confirmed_at is added by confirm-db.js (not in the original extraction-db.js). The RESEARCH.md column inventory mentioned confirmed_at in the index but the confirm-db.js ADD COLUMN was not initially included
- **Fix:** Added all Phase 39 confirm-db.js ADD COLUMN calls (edit_turn_count, nudge_sent_at, confirmed_at, expired_at, terminal_reason) to `_run_draft_migrations`
- **Files modified:** farm_agent/persistence/migrations.py
- **Commit:** fa39c9c

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes beyond those specified in the plan's threat model (T-56-05-01 through T-56-05-04). All mitigations applied as planned.

## Known Stubs

None. pool.py and migrations.py are complete implementations, not stubs.

## Self-Check

- [x] `src/farm-agent/farm_agent/persistence/pool.py` exists
- [x] `src/farm-agent/farm_agent/persistence/migrations.py` exists
- [x] `src/farm-agent/tests/test_persistence.py` exists
- [x] Commits 0b5648a (RED) and fa39c9c (GREEN) exist
- [x] `uv run pytest tests/test_persistence.py` -> 4 passed
- [x] `uv run pytest` -> 40 passed (all prior tests preserved)

## Self-Check: PASSED
