---
phase: 56-foundation
reviewed: 2026-06-15T18:00:00Z
depth: deep
files_reviewed: 34
files_reviewed_list:
  - docker-compose.override.yml
  - src/farm-agent/Dockerfile
  - src/farm-agent/farm_agent/boot.py
  - src/farm-agent/farm_agent/extraction/__init__.py
  - src/farm-agent/farm_agent/extraction/schemas/activity.py
  - src/farm-agent/farm_agent/extraction/schemas/harvest.py
  - src/farm-agent/farm_agent/extraction/schemas/__init__.py
  - src/farm-agent/farm_agent/extraction/schemas/input.py
  - src/farm-agent/farm_agent/extraction/schemas/observation.py
  - src/farm-agent/farm_agent/extraction/schemas/provenance.py
  - src/farm-agent/farm_agent/extraction/schemas/seeding.py
  - src/farm-agent/farm_agent/extraction/schemas/seeding_session.py
  - src/farm-agent/farm_agent/extraction/schemas/submission.py
  - src/farm-agent/farm_agent/extraction/schemas/_types.py
  - src/farm-agent/farm_agent/__init__.py
  - src/farm-agent/farm_agent/__main__.py
  - src/farm-agent/farm_agent/persistence/__init__.py
  - src/farm-agent/farm_agent/persistence/migrations.py
  - src/farm-agent/farm_agent/persistence/pool.py
  - src/farm-agent/farm_agent/tenancy/__init__.py
  - src/farm-agent/farm_agent/tenancy/tenant.py
  - src/farm-agent/.lint-imports
  - src/farm-agent/pyproject.toml
  - src/farm-agent/.python-version
  - src/farm-agent/tests/conftest.py
  - src/farm-agent/tests/fixtures/submission_json_schema.json
  - src/farm-agent/tests/__init__.py
  - src/farm-agent/tests/test_boot.py
  - src/farm-agent/tests/test_foray_seam.py
  - src/farm-agent/tests/test_persistence.py
  - src/farm-agent/tests/test_scaffold.py
  - src/farm-agent/tests/test_schema_parity.py
  - src/farm-agent/tests/test_tenancy.py
  - src/farm-agent/uv.lock
findings:
  critical: 3
  warning: 4
  info: 2
  total: 9
status: issues_found
---

# Phase 56: Code Review Report

**Reviewed:** 2026-06-15T18:00:00Z
**Depth:** deep
**Files Reviewed:** 34
**Status:** issues_found

## Summary

Phase 56 is a well-structured foundation port. The psycopg3 lifecycle (`open=False` + `await pool.open()`), the additive-only migration design, the Foray seam enforcement, and the `extra='forbid'` coverage across pydantic models are all correctly implemented. The JSON-Schema parity gate is the most thoughtful part of the implementation and the fixture-plus-normalize-schema approach is sound.

Three blockers were found. The most safety-critical: `signal_draft_event` (the confirm-loop audit table, created by `confirm-db.js`) is entirely absent from the Python migrations. If `alerter-py` boots against a DB where the Node alerter has NOT yet run, `signal_draft_event` will not exist -- breaking the Node alerter's confirm-loop when it starts. If the Node alerter has already run, `alerter-py` boots fine but the Python migration inventory is incomplete and will diverge from reality. The second blocker: `TENANTS_BASE` is miscounted by one parent level, resolving to `src/tenants/` on the host and `/tenants/` in Docker (both nonexistent). All unit tests pass because they monkeypatch `TENANTS_BASE`; the bug hides completely in CI. The third blocker: the raw f-string conninfo in `pool.py` is not safe against passwords containing spaces or backslashes, which is the libpq connection string format requirement.

---

## Critical Issues

### CR-01: `signal_draft_event` table missing from migrations

**File:** `src/farm-agent/farm_agent/persistence/migrations.py`
**Issue:** The Python migration runner omits the `signal_draft_event` audit table entirely. The live Node `confirm-db.js` creates this table unconditionally (same `initDb()` call that Phase 56 is porting). The table schema is:

```sql
CREATE TABLE IF NOT EXISTS signal_draft_event (
  draft_id   text NOT NULL,
  seq        integer NOT NULL,
  event      text NOT NULL,
  payload    jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (draft_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_signal_draft_event_created_at
  ON signal_draft_event (created_at);
CREATE INDEX IF NOT EXISTS idx_signal_draft_event_nudge_expire
  ON signal_draft (status, updated_at) WHERE status = 'awaiting_farmer';
```

Impact: if `alerter-py` boots first on a fresh DB (before the Node alerter), the Node alerter's confirm-loop will fail at the first `appendEvent()` call with "relation signal_draft_event does not exist". Even on an already-migrated production DB the Python migration inventory is permanently out of sync with the Node source, so future additive columns on `signal_draft_event` will be missed.

**Fix:** Add a `_run_confirm_event_migrations(conn)` function in `migrations.py` and call it from `run_migrations()`:
```python
async def _run_confirm_event_migrations(conn) -> None:
    """Port of confirm-db.js signal_draft_event table."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_draft_event (
          draft_id   text NOT NULL,
          seq        integer NOT NULL,
          event      text NOT NULL,
          payload    jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (draft_id, seq)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_draft_event_created_at "
        "ON signal_draft_event (created_at)"
    )
    # This index is on signal_draft (not signal_draft_event) -- partial nudge/expire index
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_draft_event_nudge_expire "
        "ON signal_draft (status, updated_at) WHERE status = 'awaiting_farmer'"
    )
```
Add to `test_migrations_create_expected_tables`: check `signal_draft_event` in the `pg_tables` query.

---

### CR-02: `TENANTS_BASE` miscounted by one parent level

**File:** `src/farm-agent/farm_agent/tenancy/tenant.py:27`
**Issue:** The comment says "four parents up from this file" to reach the repo root, but the actual path from `farm_agent/tenancy/tenant.py` requires five parents up:

```
4 parents: farm_agent/tenancy/tenant.py
           -> farm_agent/tenancy
           -> farm_agent
           -> src/farm-agent
           -> src          <- this is parent 4, NOT the repo root
```

The code `Path(__file__).parent.parent.parent.parent / "tenants"` resolves to `src/tenants/` on the host (which does not exist) and to `/tenants/` in Docker (also does not exist). The bug is completely hidden because every unit test monkeypatches `TENANTS_BASE` to a `tmp_path`, and in the Docker container the compose block has no `volumes:` mount for `tenants/` so `_load_tenant_file` silently returns `{}` for all lookups -- which is the actual production behavior (config comes from compose `environment:` block).

The risk: if a future phase mounts `tenants/mossrock/config.yaml` into the container for YAML-side config (a natural next step for Phase 62+), `_load_tenant_file` will always return `{}` and the YAML layer will silently not load. The path-traversal guard will also compare against the wrong boundary.

**Fix:** Add one more `.parent` call, or anchor from the `farm_agent` package root:

```python
# Option A: correct parent count (5 levels to repo root)
TENANTS_BASE = Path(__file__).parent.parent.parent.parent.parent / "tenants"

# Option B: anchor from the package, more readable
TENANTS_BASE = Path(__file__).parent.parent.parent / "tenants"
# (farm_agent/tenancy/tenant.py -> farm_agent/tenancy -> farm_agent -> src/farm-agent)
# Then mount as /app/tenants in Docker via compose volumes
```

Update the comment to match the chosen path. Add a unit test (without monkeypatching) that `TENANTS_BASE.name == "tenants"` to catch future regressions.

---

### CR-03: Raw f-string conninfo breaks on passwords with spaces, backslashes, or special chars

**File:** `src/farm-agent/farm_agent/persistence/pool.py:32-39`
**Issue:** The libpq connection string format (space-separated `key=value` pairs) requires values containing spaces or backslashes to be single-quoted. The current code builds an unquoted f-string:

```python
conninfo = (
    f"host={host} "
    f"dbname={config.timescale_db} "
    f"user={config.timescale_user} "
    f"password={config.timescale_password} "   # <-- not quoted
    ...
)
```

A production password like `p@ss w0rd` becomes `password=p@ss w0rd` which libpq parses as password `p@ss` with unknown keyword `w0rd`, yielding a connection error. A password with a backslash or single-quote can produce similar misparsing or injection. The test password `"test"` has no special characters so this never surfaces in CI.

**Fix:** Use `psycopg.conninfo.make_conninfo()` which properly quotes values:

```python
from psycopg.conninfo import make_conninfo

async def build_pool(config: TenantConfig) -> AsyncConnectionPool:
    kwargs = dict(
        host=host,
        dbname=config.timescale_db,
        user=config.timescale_user,
        password=config.timescale_password,
        options="-c timezone=UTC",
    )
    if port_part:
        kwargs["port"] = int(port_str)
    conninfo = make_conninfo(**kwargs)
    pool = AsyncConnectionPool(conninfo=conninfo, min_size=1, max_size=5, open=False)
    await pool.open()
    return pool
```

---

## Warnings

### WR-01: `test_boot_completes_in_5s` cannot distinguish fast boot from hung boot

**File:** `src/farm-agent/tests/test_boot.py:40-91`
**Issue:** The test waits 5 seconds via `asyncio.wait_for(..., timeout=5.0)` and then asserts `elapsed < 6.0`. This timing check does not verify that boot completed -- only that it did not exceed 6 seconds total. If the boot hangs (e.g., DB connection stalls for 4.9 seconds), the test still passes with `elapsed ~= 5.0 < 6.0`. The "boot complete" log line is never checked.

**Fix:** Capture caplog inside the test and assert the "boot complete" line was emitted:

```python
with caplog.at_level(logging.INFO, logger="farm_agent"):
    task = asyncio.create_task(main())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

boot_messages = [r.getMessage() for r in caplog.records]
assert any("boot complete" in m for m in boot_messages), (
    f"'boot complete' not found in logs -- boot may have hung. Log: {boot_messages}"
)
```

---

### WR-02: `_parse_int_env` and `_parse_float_env` raise uncaught `ValueError` on non-numeric env input

**File:** `src/farm-agent/farm_agent/tenancy/tenant.py:88-101`
**Issue:** `_parse_int_env` calls `int(raw)` without a try/except. If a compose env var like `ALERT_PI_OFFLINE_MIN=abc` is set (operator typo, partial variable expansion, or a forgotten `${VAR}` that didn't expand), the daemon crashes at boot with a bare `ValueError` that names neither the env key nor the bad value. This also affects all float fields.

**Fix:**
```python
def _parse_int_env(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(
            f"[config] {key}={raw!r} is not a valid integer"
        ) from None
```

Apply the same pattern to `_parse_float_env`.

---

### WR-03: `strains.yaml` can shadow non-secret config keys from `config.yaml` via merge order

**File:** `src/farm-agent/farm_agent/tenancy/tenant.py:256-259`
**Issue:** The YAML merge is `{**config_yaml, **strains_yaml}`, meaning `strains.yaml` wins on any key collision. The intent is that `strains.yaml` contains only `STRAIN_CODES`. But if a tenant's `strains.yaml` accidentally contains a key like `FARMOS_URL` or `SIGNAL_RECIPIENT`, it silently overrides `config.yaml`. This is consistent with the Node behavior (which uses the same merge), but it's worth flagging because the Python port makes secrets bypass the merge entirely (`_must_env`) while non-secrets do not -- so a malicious or accidentally augmented `strains.yaml` can redirect `FARMOS_URL` to an attacker-controlled host.

**Fix:** Enforce that `strains.yaml` contributes only `STRAIN_CODES`:
```python
strains_raw = _load_tenant_file(tenant_id, "strains.yaml")
tenant_cfg: dict[str, Any] = {
    **_load_tenant_file(tenant_id, "config.yaml"),
    # Only pull STRAIN_CODES from strains.yaml, not arbitrary keys
    **({"STRAIN_CODES": strains_raw["STRAIN_CODES"]}
       if "STRAIN_CODES" in strains_raw else {}),
}
```

---

### WR-04: Empty test body for `test_missing_farmos_password_does_not_raise`

**File:** `src/farm-agent/tests/test_tenancy.py:110-116`
**Issue:** The test function body contains only comments and a blank line -- no assertions, no actual call. pytest collects it, runs it, and reports it as PASSED (an empty test body always passes in pytest). The behavior it claims to test (that missing `FARMOS_PASSWORD` silently defaults to `""`) is real production behavior (`farmos_password = env.get("FARMOS_PASSWORD") or ""`) but is not actually verified.

**Fix:**
```python
def test_missing_farmos_password_does_not_raise(tmp_path, monkeypatch):
    """FARMOS_PASSWORD missing uses empty string default (back-compat, not mustEnv)."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    env = _env(TENANT_ID="t1")
    del env["FARMOS_PASSWORD"]
    cfg = _tenant_mod.load(env)
    assert cfg.farmos_password == ""
```

---

## Info

### IN-01: `test_schema_parity.py` FIXTURE_PATH uses a redundant `"tests"` descent

**File:** `src/farm-agent/tests/test_schema_parity.py:29`
**Issue:** The fixture path is constructed as:
```python
FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "submission_json_schema.json"
```
`__file__` is `tests/test_schema_parity.py`, so `.parent.parent` is `src/farm-agent/`, then the path descends back into `tests/fixtures/`. This resolves to the correct file but the intermediate `.parent.parent / "tests"` climb-then-descend is confusing and would break if the test file were moved out of `tests/`.

**Fix:**
```python
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "submission_json_schema.json"
```

---

### IN-02: `alerter-py` compose block does not forward `ANTHROPIC_API_KEY` in `environment:`

**File:** `docker-compose.override.yml:175-218`
**Issue:** The `alerter-py` compose block sources `ANTHROPIC_API_KEY` from `tenants/mossrock/secrets.env` (via `env_file:`), which is correct. However, unlike the Node `alerter:` block (which has an explicit comment explaining why `ANTHROPIC_API_KEY` is absent from `environment:`), the `alerter-py` block has no such comment. When Phase 59-60 wires up the LLM client that reads `config.anthropic_api_key`, a future developer adding env vars may not realize the key is already present (from `env_file`), and might add it to `environment:` -- which would override the `env_file` value with whatever is or isn't in the repo-root `.env`, repeating the regression that caused the 2026-05-23 prod outage.

**Fix:** Add a comment parallel to the Node `alerter:` block:
```yaml
# ANTHROPIC_API_KEY sourced from tenants/mossrock/secrets.env (env_file above).
# Do NOT add it to environment: -- that would override the per-tenant secret
# with whatever is in repo-root .env (see 2026-05-23 alerter outage).
```

---

_Reviewed: 2026-06-15T18:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
