---
phase: 56-foundation
plan: "02"
subsystem: tenancy
tags: [config, tenancy, fnd-02, python-port]
dependency_graph:
  requires: [56-01]
  provides: [TenantConfig, farm_agent.tenancy.tenant.load]
  affects: [56-03, 56-04, 56-06]
tech_stack:
  added: [ruamel.yaml]
  patterns: [frozen-dataclass, layered-config, env-only-secrets, path-traversal-guard]
key_files:
  created:
    - src/farm-agent/farm_agent/tenancy/tenant.py
    - src/farm-agent/tests/test_tenancy.py
  modified: []
decisions:
  - "Hand-rolled layered loader (not pydantic-settings) mirrors config.js exactly"
  - "FARMOS_PASSWORD uses || '' fallback (not mustEnv) for back-compat when farmosIntegration=false"
  - "SIGNAL_RECIPIENT falls back to mustEnv when not in YAML or env (matches config.js line 135)"
metrics:
  duration_sec: 175
  completed_date: "2026-06-15"
  tasks_completed: 1
  files_changed: 2
---

# Phase 56 Plan 02: TenantConfig Loader Summary

**One-liner:** Frozen `TenantConfig` dataclass porting Node `config.js` layered YAML+env+default loading with env-only secrets and path-traversal guard.

## What Was Built

`farm_agent/tenancy/tenant.py` — the lowest node in the dependency graph and the **sole reader of `os.environ`** in farm_agent business code (FND-02).

### Core Components

| Symbol | Role |
|--------|------|
| `TENANTS_BASE` | Module-level `Path` anchoring tenant file resolution |
| `_must_env(env, key)` | Raises `RuntimeError` (not `KeyError`) on falsy/absent env var — mirrors `mustEnv()` |
| `_load_tenant_file(tenant_id, filename)` | Path-traversal guard + ruamel.yaml load; returns `{}` on escape, missing, or parse error |
| `_pick(tenant_cfg, env, key, default)` | Three-layer get: YAML → env → default |
| `_resolve_farmer_map(tenant_cfg, env)` | Handles both YAML object form and legacy `+phone:slug,...` env string |
| `_resolve_farmos_integration(tenant_cfg, env)` | Coerces YAML bool (`true`/`false`) and env string (`1`/`0`) |
| `TenantConfig` | Frozen dataclass, 34 fields (secrets + non-secrets) |
| `load(env)` | Public entry point; defaults to `os.environ`; returns `TenantConfig` |

### Field Coverage

- **Secrets (env-only via `_must_env`):** `signal_sender`, `timescale_password`, `anthropic_api_key`
- **Near-secret (env `||` `''`):** `farmos_password` — back-compat with tests not setting `FARMOS_PASSWORD` when `farmosIntegration=false`
- **Layered non-secrets:** `signal_recipient`, `signal_group_id`, `signal_farmer_map`, `strains`, `event_gate_convo_mode`, `farmos_url`, `farmos_username`, `farmos_integration`, all `timescale_*`, `whisper_url`, `capture_*`, all numeric alerter tuning fields, `timezone`, `log_level`

## Test Results

```
28 passed in 0.15s
```

Coverage of all acceptance criteria:
- Layer precedence: YAML > env > default (3 tests)
- Missing secret RuntimeError naming the key (parametrized over 3 keys + empty-string check)
- Traversal guard: `../../etc/passwd` returns `{}` (3 variants)
- SIGNAL_FARMER_MAP object form + missing + env string form (3 tests)
- FARMOS_INTEGRATION YAML bool true/false + env `1`/`0` + default false (5 tests)
- Numeric field coercion int/float + default (3 tests)
- SIGNAL_GROUP_ID `""` → `None`, real value preserved (2 tests)
- strains from YAML + empty default (2 tests)
- Frozen dataclass (1 test)
- FND-02 env-reader gate — grep confirms only `tenancy/tenant.py` reads `os.environ` (1 test)

## Acceptance Criteria Verification

- [x] `uv run pytest tests/test_tenancy.py -q` passes (28/28)
- [x] `class TenantConfig` is a frozen dataclass; `load` is exported
- [x] FND-02 gate: `grep -r "os.environ" farm_agent/ --include="*.py" | grep -v tenancy/tenant.py | grep -v boot.py` returns empty

## Deviations from Plan

None — plan executed exactly as written.

The one nuance worth documenting: `FARMOS_PASSWORD` uses `env.get("FARMOS_PASSWORD") or ""` (not `_must_env`) matching `config.js` line 218 (`env.FARMOS_PASSWORD || ''`). The plan's "secrets" list includes `farmos_password` but the Node source explicitly does NOT use `mustEnv` for it. Back-compat preserved.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. File access is limited to `TENANTS_BASE / tenant_id / filename` with the traversal guard verified by tests.

## TDD Gate Compliance

- RED commit: `1617067` — `test(56-02): add failing tests for TenantConfig layered loader`
- GREEN commit: `da82bfc` — `feat(56-02): implement TenantConfig layered loader with env-only secrets and traversal guard`
- No REFACTOR needed.

## Known Stubs

None — all fields fully wired. `strains` defaults to `[]` when no `strains.yaml` exists, which is the correct default (identical to `config.js` line 126).

## Self-Check

- [x] `src/farm-agent/farm_agent/tenancy/tenant.py` exists
- [x] `src/farm-agent/tests/test_tenancy.py` exists
- [x] RED commit `1617067` in git log
- [x] GREEN commit `da82bfc` in git log
