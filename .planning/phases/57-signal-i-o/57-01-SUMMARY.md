---
phase: 57-signal-i-o
plan: "01"
subsystem: signal-i-o
tags: [foundation, tenancy, outbound-persist, httpx, respx, tdd]
dependency_graph:
  requires: [56-foundation]
  provides: [outbound_repo.insert_outbound, TenantConfig.signal_api_url, TenantConfig.signal_additional_senders, mask_number, signal_http_fixture, FakeOutboundRepo]
  affects: [57-02, 57-03, 57-04]
tech_stack:
  added: [httpx>=0.28, respx>=0.23]
  patterns: [psycopg3-async-with-pool, fail-open-try-except, tdd-red-green]
key_files:
  created:
    - src/farm-agent/farm_agent/persistence/outbound_repo.py
    - src/farm-agent/tests/test_signal_persist.py
  modified:
    - src/farm-agent/pyproject.toml
    - src/farm-agent/uv.lock
    - src/farm-agent/farm_agent/tenancy/tenant.py
    - src/farm-agent/tests/test_tenancy.py
    - src/farm-agent/tests/conftest.py
decisions:
  - "signal_api_url uses _pick (Tier-D env-default like Node config.js:132), not _must_env -- not a secret"
  - "signal_additional_senders uses env.get only (no YAML layer) matching config.js:136-137 exact behavior"
  - "attachments passed as psycopg.types.json.Jsonb for clean jsonb cast; no JSON string coercion in repo"
  - "FakeOutboundRepo in conftest (not test file) so Plan 02 can import it without duplication"
metrics:
  duration: "~18 minutes"
  completed: "2026-06-15"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 7
---

# Phase 57 Plan 01: Foundation (httpx + TenantConfig extension + outbound_repo) Summary

Phase 57 Plan 01 lands the three foundation gaps that Wave 2 signal_io plans (02-04) build on: httpx/respx dependencies, three new TenantConfig surfaces (signal_api_url, signal_additional_senders, mask_number), and the never-throw outbound_repo.insert_outbound for SIG-02 durable persist.

## Tasks Completed

| Task | Type | Name | Commit | Result |
|------|------|------|--------|--------|
| 1 | checkpoint (pre-cleared) | Package legitimacy gate -- httpx + respx | n/a | APPROVED by orchestrator |
| 2 | auto/tdd | httpx+respx deps; TenantConfig extension; mask_number | 78660a9 | GREEN -- 38 tests pass |
| 3 | auto/tdd | outbound_repo.insert_outbound + conftest fixtures | 5ed2941 | GREEN -- 2 pass, 5 skip (no DB) |

## TDD Gate Compliance

**Task 2:**
- RED commit: `b3b583b` -- added 8 failing tests for signal_api_url, signal_additional_senders, mask_number
- GREEN commit: `78660a9` -- implementation; all 38 tenancy tests pass

**Task 3:**
- RED commit: `81ce00c` -- added 7 tests (2 DB-independent, 5 DB-gated), failing with ModuleNotFoundError
- GREEN commit: `5ed2941` -- implementation; 2 DB-independent pass, 5 DB-gated skip cleanly

## Decisions Made

- `signal_api_url` uses `_pick()` (Tier-D YAML > env > default) not `_must_env` -- it is a URL, not a secret (W9 policy applies to SIGNAL_SENDER only).
- `signal_additional_senders` reads env only (no YAML layer), exactly mirroring `config.js:136-137` split/trim/filter behavior.
- `attachments` passed as `psycopg.types.json.Jsonb` for clean `::jsonb` cast -- no JSON string coercion in the repo layer (caller owns serialization).
- `FakeOutboundRepo` placed in `conftest.py` (not `test_signal_persist.py`) so Plan 02's `test_signal_persist` extensions can import it without duplication.
- `signal_http` fixture uses `respx.mock(assert_all_called=False)` to allow partial-use in callers that only care about one endpoint.

## Verification

- `uv run pytest tests/test_tenancy.py tests/test_signal_persist.py -x` -- 40 passed, 5 skipped.
- `uv run pytest` (full suite) -- 50 passed, 10 skipped. No regression in Phase-56 tests.
- `grep -n 'httpx' src/farm-agent/pyproject.toml` returns `"httpx>=0.28"` in dependencies.

## Deviations from Plan

None -- plan executed exactly as written. Task 1 checkpoint was pre-cleared by orchestrator before execution.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced in this plan. outbound_repo.py writes to the existing `signal_outbound` table (DDL owned by migrations.py, unchanged). mask_number() is a pure function with no I/O.

## Self-Check: PASSED
