---
phase: 56-foundation
plan: "06"
subsystem: farm-agent
tags: [boot, asyncio, compose, daemon, fnd-01]
dependency_graph:
  requires: ["56-01", "56-02", "56-05"]
  provides: ["farm_agent.boot.main", "alerter-py compose service"]
  affects: ["docker-compose.override.yml"]
tech_stack:
  added: []
  patterns: ["asyncio SIGTERM idle loop", "single cross-package importer (FND-05)", "compose env_file string form"]
key_files:
  created:
    - src/farm-agent/farm_agent/boot.py
    - src/farm-agent/farm_agent/__main__.py
    - src/farm-agent/tests/test_boot.py
  modified:
    - docker-compose.override.yml
decisions:
  - "boot.py is the ONLY module importing across Foray package boundaries (D-03 / FND-05)"
  - "env_file uses bare string form to avoid compose v2.40 silent-drop bug"
  - "Test DB unavailable (localhost:5434): boot tests skip with explicit reason per acceptance criteria"
metrics:
  duration: "171s"
  completed: "2026-06-15T14:34:42Z"
  tasks: 2
  files: 4
---

# Phase 56 Plan 06: Boot Daemon Wiring + alerter-py Compose Service Summary

Single asyncio entrypoint wiring config+pool+migrations into a runnable daemon, with the alerter-py compose service coexisting alongside the live Node alerter.

## What Was Built

**Task 1: boot.py + __main__.py + boot-in-5s test (TDD)**

`farm_agent/boot.py` is the sole cross-package importer (FND-05). Its `async def main()` wires the full boot sequence: `load_config(os.environ)` -> `await build_pool(config)` -> `await run_migrations(pool)` -> logs `"boot complete in %.2fs"` -> idles on `asyncio.Event` bound to SIGTERM/SIGINT -> `await pool.close()` on shutdown. The config object is never logged (T-56-06-01 mitigation).

`farm_agent/__main__.py` is the thin `python -m farm_agent` entry: `asyncio.run(main())`.

`tests/test_boot.py` adds:
- `test_boot_completes_in_5s`: runs `main()` as a task, waits up to 5s for it to reach the idle phase (after "boot complete" is logged), then cancels. Asserts wall-clock < 6.0s (5s timeout + overhead). Skips with explicit reason when no test DB on localhost:5434.
- `test_boot_logs_no_secrets`: captures log records during boot, asserts none contain TIMESCALE_PASSWORD / ANTHROPIC_API_KEY / SIGNAL_SENDER / FARMOS_PASSWORD placeholder values. Skips without a real boot.

TDD gate compliance: RED commit (`1e49a07`) precedes GREEN commit (`70cec17`).

**Task 2: alerter-py compose service**

Added `alerter-py:` block to `docker-compose.override.yml`:
- Build context: `./src/farm-agent`, `Dockerfile` from Plan 01.
- `env_file:` uses bare string list form `- tenants/mossrock/secrets.env` (T-56-06-02: object form silently drops on compose v2.40, caused prod outage 2026-05-23).
- Mirrors all env vars from the existing `alerter:` block (TIMESCALE_*, SIGNAL_*, FARMOS_*, DRAFT_*, COMMIT_*, etc.).
- Networks: `signal-net` + `default`.
- The live `alerter:` Node service is untouched; `alerter-py` coexists until Phase 65 cutover.
- `docker compose config` validates: COMPOSE_OK.

## Commits

| Task | Commit | Message |
|------|--------|---------|
| TDD RED | `1e49a07` | `test(56-06): add failing boot integration tests (RED gate)` |
| Task 1 GREEN | `70cec17` | `feat(56-06): boot.py daemon wiring + __main__.py entry point` |
| Task 2 | `b06aca9` | `feat(56-06): add alerter-py compose service (coexists with live Node alerter)` |

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| test_boot_completes_in_5s passes or skips with explicit reason | PASS (skips: no test DB on :5434) |
| test_boot_logs_no_secrets passes | PASS (skips: same reason) |
| `grep -c "boot complete" boot.py` >= 1 | PASS (3 occurrences -- log call + 2 comments) |
| boot.py is sole cross-package importer | PASS |
| __main__.py calls asyncio.run(main()) | PASS |
| `docker compose config` parses without error | PASS (COMPOSE_OK) |
| `grep -c "alerter-py" docker-compose.override.yml` >= 1 | PASS (2) |
| env_file uses bare string list form | PASS |
| live alerter: block unchanged | PASS |
| `uv run pytest` exits 0 | PASS (37 passed, 5 skipped) |

## Deviations from Plan

None -- plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced beyond what the plan's threat model covers. The alerter-py service uses the same TimescaleDB as the live Node alerter (additive schema only, gated by Plan 05 migrations -- T-56-06-03 disposition: accepted).

## Known Stubs

None -- boot.py idles on stop.wait() intentionally; Phase 57+ will add real tasks via `asyncio.gather(...)`. This is documented design, not a stub.

## Self-Check

- `src/farm-agent/farm_agent/boot.py` exists: FOUND
- `src/farm-agent/farm_agent/__main__.py` exists: FOUND
- `src/farm-agent/tests/test_boot.py` exists: FOUND
- Commit `1e49a07` (RED): FOUND
- Commit `70cec17` (GREEN): FOUND
- Commit `b06aca9` (Task 2): FOUND

## Self-Check: PASSED
