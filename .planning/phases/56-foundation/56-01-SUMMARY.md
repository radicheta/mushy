---
phase: 56-foundation
plan: 01
subsystem: farm-agent
tags: [python, uv, pydantic, psycopg3, scaffold, json-schema]
dependency_graph:
  requires: []
  provides: [farm_agent_package, uv_lock, dockerfile, json_schema_fixture, conftest_scaffold]
  affects: [56-02, 56-03, 56-04, 56-05, 56-06]
tech_stack:
  added:
    - uv 0.11.21 (package manager)
    - Python 3.12.13 (via uv auto-resolved from .python-version)
    - pydantic 2.13.4
    - psycopg[binary] 3.3.4
    - psycopg-pool 3.3.1
    - ruamel.yaml 0.19.1
    - pytest 9.1.0
    - pytest-asyncio 1.4.0
    - ruff 0.15.17
    - import-linter 2.11
  patterns:
    - uv-in-Docker (pyproject.toml + uv.lock + python:3.12-slim-bookworm)
    - pytest-asyncio auto mode (asyncio_mode=auto in pyproject.toml)
    - local-import guard in conftest (pool fixture defers imports until Plans 02+03 land)
key_files:
  created:
    - src/farm-agent/pyproject.toml
    - src/farm-agent/.python-version
    - src/farm-agent/uv.lock
    - src/farm-agent/Dockerfile
    - src/farm-agent/farm_agent/__init__.py
    - src/farm-agent/farm_agent/tenancy/__init__.py
    - src/farm-agent/farm_agent/persistence/__init__.py
    - src/farm-agent/farm_agent/extraction/__init__.py
    - src/farm-agent/farm_agent/extraction/schemas/__init__.py
    - src/farm-agent/tests/__init__.py
    - src/farm-agent/tests/conftest.py
    - src/farm-agent/tests/fixtures/submission_json_schema.json
    - src/farm-agent/tests/test_scaffold.py
  modified: []
decisions:
  - "Pinned .python-version to 3.12 locally; repo-root pyenv mushroom_farm version resolves to 3.10 and is not installed"
  - "Added tests/test_scaffold.py so pytest --co exits 0 (exit code 5 = no tests collected, which is not 0)"
  - "Fixture is 19431 chars, not 6155 as research doc stated; the 6155 figure was for DRAFT_JSON_SCHEMA not SUBMISSION_JSON_SCHEMA"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-15"
  tasks_completed: 2
  files_created: 13
---

# Phase 56 Plan 01: uv Scaffold + Package Skeleton + JSON-Schema Fixture Summary

One-liner: uv/Python-3.12 project with Foray sub-package stubs, python:3.12-slim Dockerfile, committed Node JSON-Schema fixture (19431 chars, draft-7), and pytest conftest scaffold.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create uv project + package skeleton + Dockerfile | 07513cb | pyproject.toml, .python-version, uv.lock, Dockerfile, 6x __init__.py |
| 2 | Generate + commit Node JSON-Schema fixture + conftest scaffold | dc2e3aa | tests/fixtures/submission_json_schema.json, tests/conftest.py, tests/test_scaffold.py |

## Acceptance Criteria Results

- `uv sync` exits 0 and `uv.lock` is committed: PASS
- `uv run python -c "import farm_agent.tenancy, farm_agent.persistence, farm_agent.extraction.schemas"` prints OK: PASS
- `grep -v '^#' pyproject.toml | grep -c 'asyncio_mode'` returns 1: PASS (returns 1)
- `grep -c 'python:3.12-slim' Dockerfile` returns at least 1: PASS (returns 1); no `libpq-dev`: PASS
- No `chamber/` directory under `farm_agent/`: PASS
- `tests/fixtures/submission_json_schema.json` contains `definitions`, `anyOf`, `additionalProperties`: PASS
- `uv run pytest tests/ -q --co` exits 0: PASS (1 test collected)
- `grep -c "TEST_ENV" tests/conftest.py` returns at least 1: PASS (returns 4)
- No real secret value in fixture or conftest: PASS (placeholder values only)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Added tests/test_scaffold.py**
- **Found during:** Task 2 verification
- **Issue:** `uv run pytest tests/ -q --co` exits 5 (no tests collected) when there are no test files. The plan's acceptance criterion says "exits 0". Exit 5 is pytest's "no tests collected" signal, not an error, but it violates the literal criterion.
- **Fix:** Added `tests/test_scaffold.py` with `test_farm_agent_imports()` that imports all sub-packages. This ensures `--co` exits 0 and gives a real boot-smoke test.
- **Files modified:** `src/farm-agent/tests/test_scaffold.py` (new)
- **Commit:** dc2e3aa

**2. [Observation] Fixture size discrepancy**
- **Found during:** Task 2 fixture generation
- **Issue:** RESEARCH.md stated the fixture is "~6155 chars" but the actual `SUBMISSION_JSON_SCHEMA` is 19431 chars. The 6155 figure likely referred to `DRAFT_JSON_SCHEMA` (the inner schema without the Submission wrapper). The fixture is structurally correct (definitions/anyOf/additionalProperties all present, top-level $ref + definitions + $schema).
- **Action:** No fix needed. Committed the correct SUBMISSION_JSON_SCHEMA verbatim.

## Known Stubs

- `farm_agent/__init__.py` and all sub-package `__init__.py` files are empty stubs. Plans 02-05 populate them.
- `tests/conftest.py` pool fixture uses local imports (deferred until Plans 02+03 ship tenancy/persistence).

## Threat Flags

None. The fixture contains JSON Schema shape only (field names, types, enums) -- no secrets or PII. TEST_ENV uses placeholder-only credentials.

## Self-Check

- [x] `src/farm-agent/pyproject.toml` exists
- [x] `src/farm-agent/uv.lock` exists
- [x] `src/farm-agent/Dockerfile` exists
- [x] `src/farm-agent/tests/fixtures/submission_json_schema.json` exists
- [x] `src/farm-agent/tests/conftest.py` exists
- [x] Commits 07513cb and dc2e3aa exist in git log
- [x] `uv run pytest tests/ -q --co` exits 0 (verified)

## Self-Check: PASSED
