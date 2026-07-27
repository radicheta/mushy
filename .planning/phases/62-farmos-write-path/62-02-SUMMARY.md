---
phase: 62-farmos-write-path
plan: "02"
subsystem: farmos-client
tags: [farmos, httpx, auth, retry, never-throws, tdd]
dependency_graph:
  requires: ["62-01"]
  provides: ["create_farmos_client -- auth+retry transport seam for FWR-01"]
  affects: ["62-03 assets", "62-04 logs", "62-05 files", "62-06 commits"]
tech_stack:
  added: []
  patterns: ["never-throws httpx factory (mirror transcribe_client.py)", "injectable _sleep for backoff spy", "closure _session dict (mirror JS)"]
key_files:
  created:
    - src/farm-agent/farm_agent/farmos/__init__.py
    - src/farm-agent/farm_agent/farmos/client.py
    - src/farm-agent/tests/test_farmos_client.py
  modified: []
decisions:
  - "Injectable _sleep kwarg (default asyncio.sleep) enables backoff-order assertion in tests without real delays"
  - "httpx.TransportError catch-all covers TimeoutException + ConnectError in _is_transient_error (cleaner than enumerating Node AbortError/TypeError/msg-pattern)"
  - "Grep counts for user/login?_format=json and X-CSRF-Token return 2 not 1 -- docstring occurrences are benign; behavioral tests are the real gate"
metrics:
  duration_minutes: 22
  completed_date: "2026-06-28"
  tasks_completed: 1
  files_created: 3
  lines_written: 783
requirements: [FWR-01]
---

# Phase 62 Plan 02: farmOS httpx Client Summary

**One-liner:** httpx async farmOS client with session-cookie + CSRF auth, (1s/4s/16s) backoff retry, one-shot 401 reauth, never-throws envelope, octet-stream binary upload.

## What Was Built

`farm_agent/farmos/client.py` -- a faithful Python port of `src/agents/alerter/src/farmos/client.js`.

Factory `create_farmos_client(farmos_url, username, password, http, ...)` returns a dict of async callables:
- `get/post/patch/post_binary/head/delete` -- all return `{"ok", "status", "body", "latency_ms"}`
- `_session` -- closure dict for test introspection (cookie, csrf, authed_at)

Key behaviors ported byte-identical from Node:
- `_authenticate()` POSTs `/user/login?_format=json`, takes first Set-Cookie segment and `csrf_token` body field
- Lazy auth on first non-skip-auth request
- One-shot reauth on 401/403 (`did_reauth` flag prevents infinite loop)
- 5xx + network transient retry with configurable backoff `(1000, 4000, 16000)` ms
- `post_binary` sends `application/octet-stream` + `Content-Disposition: file; filename=...` with 30s timeout
- Never raises: all callables catch httpx exceptions and return `{"ok": False, ..., "error": str(e)}`

`farm_agent/farmos/__init__.py` -- package marker re-exporting `create_farmos_client`.

15 unit tests in `tests/test_farmos_client.py` covering:
- Auth populates `_session["cookie"]` and `_session["csrf"]`
- GET success envelope shape (ok, status, body, latency_ms)
- 401 triggers exactly one reauth; second 401 returns ok=False without loop
- 5xx retry sequence: sleep called with [1000], then [1000, 4000], then exhausted ok=False
- TimeoutException and ConnectError return ok=False with error key, never propagate
- post_binary sends octet-stream + Content-Disposition
- X-CSRF-Token header value matches stored csrf
- 4xx (404) is final -- not retried
- Auth network failure returns ok=False envelope

## TDD Gate Compliance

- RED commit `ea9d854`: test file written with 15 failing tests (ModuleNotFoundError)
- GREEN commit `1d0c028`: implementation; all 15 tests pass
- No REFACTOR phase needed (implementation was clean on first pass)

## Deviations from Plan

### Minor: grep count deviation

The acceptance criteria states `grep -c "user/login?_format=json" client.py` returns 1 and `grep -c "X-CSRF-Token" client.py` returns 1. Actual counts are 2 for each because the strings also appear in docstrings (module-level and function-level documentation). The behavioral tests that verify these features all pass. The docstring occurrences improve code navigation and are intentional.

All other acceptance criteria pass:
- `grep -c "application/octet-stream"` returns 1 (correct)
- 401 reauth test: login called exactly twice -- PASS
- TimeoutException test: ok=False with error key, no exception escape -- PASS
- Backoff test: sleep called with [1000] on first 5xx retry -- PASS

## Threat Model Compliance

- **T-62-04** (no credentials/cookie/csrf in logs): `_authenticate()` logs only status code on failure, never password or token values.
- **T-62-05** (reauth on 401/403): `did_reauth` flag enforces exactly one reauth cycle.
- **T-62-06** (bounded timeout): 10s per-call timeout passed to httpx; `post_binary` uses 30s; `retry_max=3` is the ceiling.

## Known Stubs

None. The factory is fully functional; all callables work with the injected httpx.AsyncClient.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `farm_agent/farmos/__init__.py` exists | FOUND |
| `farm_agent/farmos/client.py` exists | FOUND |
| `tests/test_farmos_client.py` exists | FOUND |
| RED commit `ea9d854` | FOUND |
| GREEN commit `1d0c028` | FOUND |
| 15 tests pass (`uv run pytest tests/test_farmos_client.py`) | PASS |
| Full suite (345 pass / 25 skip) | PASS |
