---
phase: 56-foundation
fixed_at: 2026-06-15T20:00:00Z
review_path: .planning/phases/56-foundation/56-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 56: Code Review Fix Report

**Fixed at:** 2026-06-15T20:00:00Z
**Source review:** .planning/phases/56-foundation/56-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9
- Fixed: 9
- Skipped: 0

Full suite result after all fixes: **45 passed** (10.63s, with test DB on :5434).

## Fixed Issues

### CR-01: `signal_draft_event` table missing from migrations

**Files modified:** `src/farm-agent/farm_agent/persistence/migrations.py`, `src/farm-agent/tests/test_persistence.py`
**Commit:** 9971853
**Applied fix:** Added `_run_confirm_event_migrations(conn)` function that ports the
`signal_draft_event` CREATE TABLE + 2 indexes verbatim from `confirm-db.js`. Called
from `run_migrations()` between `_run_draft_migrations` and `_run_outbound_migrations`.
Updated `test_migrations_create_expected_tables` to assert all four tables
(signal_capture, signal_draft, signal_draft_event, signal_outbound) exist.

### CR-02: `TENANTS_BASE` miscounted by one parent level

**Files modified:** `src/farm-agent/farm_agent/tenancy/tenant.py`, `src/farm-agent/tests/test_tenancy.py`
**Commit:** f634653
**Applied fix:** Changed `Path(__file__).parent.parent.parent.parent / "tenants"` to
`Path(__file__).parent.parent.parent.parent.parent / "tenants"` (5 parents to repo root,
not 4). Updated the comment to show the full traversal path. Added two tests without
monkeypatching: `test_tenants_base_name_is_tenants` (asserts `.name == "tenants"`) and
`test_tenants_base_parent_is_repo_root` (asserts CLAUDE.md exists in parent directory).

### CR-03: Raw f-string conninfo breaks on passwords with special chars

**Files modified:** `src/farm-agent/farm_agent/persistence/pool.py`, `src/farm-agent/tests/test_persistence.py`
**Commit:** 67526be
**Applied fix:** Replaced raw f-string conninfo building with
`from psycopg.conninfo import make_conninfo` + kwargs dict. Port split-out is handled
by setting `kwargs["host"]` and `kwargs["port"]` after splitting on `:`. Added
`test_make_conninfo_quotes_special_password` verifying quoted output for a password
containing a space and a backslash.

### WR-01: `test_boot_completes_in_5s` cannot distinguish fast boot from hung boot

**Files modified:** `src/farm-agent/tests/test_boot.py`
**Commit:** 92cec84
**Applied fix:** Added `caplog` fixture parameter and wrapped the `asyncio.create_task`
block in `with caplog.at_level(logging.INFO, logger="farm_agent")`. After the task
completes or is cancelled, asserts `any("boot complete" in m for m in boot_messages)`,
so a DB stall that gets cancelled at 5s without completing boot now fails the test.

### WR-02: `_parse_int_env` and `_parse_float_env` raise uncaught `ValueError`

**Files modified:** `src/farm-agent/farm_agent/tenancy/tenant.py`
**Commit:** 8b89b28
**Applied fix:** Wrapped `int(raw)` and `float(raw)` in try/except ValueError, re-raising
as `RuntimeError(f"[config] {key}={raw!r} is not a valid integer/float")` with
`from None` to suppress the original traceback noise.

### WR-03: `strains.yaml` can shadow non-strain config keys

**Files modified:** `src/farm-agent/farm_agent/tenancy/tenant.py`
**Commit:** 24b8789
**Applied fix:** Replaced `**_load_tenant_file(tenant_id, "strains.yaml")` wholesale
merge with a scoped pull: `_load_tenant_file` result stored in `strains_raw`, then
only `{"STRAIN_CODES": strains_raw["STRAIN_CODES"]}` is merged if that key exists.
A stray `FARMOS_URL` or `SIGNAL_RECIPIENT` in `strains.yaml` no longer overrides
`config.yaml`.

### WR-04: Empty test body for `test_missing_farmos_password_does_not_raise`

**Files modified:** `src/farm-agent/tests/test_tenancy.py`
**Commit:** 0e9d504
**Applied fix:** Implemented the test body: creates a minimal tenant dir in `tmp_path`,
deletes `FARMOS_PASSWORD` from the env dict, calls `_tenant_mod.load(env)`, and asserts
`cfg.farmos_password == ""`. Added `tmp_path` and `monkeypatch` fixture params.

### IN-01: `test_schema_parity.py` FIXTURE_PATH uses redundant `"tests"` descent

**Files modified:** `src/farm-agent/tests/test_schema_parity.py`
**Commit:** 0d8ad97
**Applied fix:** Simplified `Path(__file__).parent.parent / "tests" / "fixtures" / ...`
to `Path(__file__).parent / "fixtures" / ...`. Resolves to the same file but
is correct and robust to the test file being in `tests/`.

### IN-02: `alerter-py` compose block missing `ANTHROPIC_API_KEY` warning

**Files modified:** `docker-compose.override.yml`
**Commit:** 30d2354
**Applied fix:** Added a comment above the `environment:` block explaining that
`ANTHROPIC_API_KEY` is already sourced from `tenants/mossrock/secrets.env` via
`env_file:` and must not be added to `environment:` to avoid overriding the
per-tenant secret (referencing the 2026-05-23 outage pattern).

---

_Fixed: 2026-06-15T20:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
