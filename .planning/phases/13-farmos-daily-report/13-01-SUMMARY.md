---
phase: 13-farmos-daily-report
plan: "01"
subsystem: farmos-agent
tags: [farmos, timescaledb, report, bridge, tdd]
dependency_graph:
  requires: []
  provides:
    - farmos_client: FarmOS session-cookie auth + observation CRUD
    - telemetry_query: TimescaleDB daily aggregation
    - report_builder: Markdown daily summary with anomaly flags
    - bridge /camera/latest.jpg: JPEG snapshot alias endpoint
  affects:
    - src/mission-control/bridge/src/index.js
tech_stack:
  added:
    - requests (FarmOS JSON:API via session-cookie)
    - psycopg2 (TimescaleDB via parameterized SQL)
    - zoneinfo (stdlib, midnight timezone boundary)
  patterns:
    - TDD red-green with pytest and unittest.mock
    - Module-level cache with autouse fixture isolation
    - Parameterized SQL for all DB queries (T-13-01)
    - Session-cookie auth with CSRF header (T-13-03)
key_files:
  created:
    - src/farmos-agent/farmos_agent/__init__.py
    - src/farmos-agent/farmos_agent/farmos_client.py
    - src/farmos-agent/farmos_agent/telemetry_query.py
    - src/farmos-agent/farmos_agent/report_builder.py
    - src/farmos-agent/tests/__init__.py
    - src/farmos-agent/tests/conftest.py
    - src/farmos-agent/tests/test_farmos_client.py
    - src/farmos-agent/tests/test_telemetry_query.py
    - src/farmos-agent/tests/test_report_builder.py
  modified:
    - src/mission-control/bridge/src/index.js
decisions:
  - "Session-cookie auth (not OAuth2) — OAuth2 consumer not configured in FarmOS instance; proven pattern from /mnt/slime-kingdom/shared/farmos/logger/server.py"
  - "Module-level UUID cache with _cache injection parameter — allows test isolation without clearing global state directly in production code"
  - "autouse conftest fixture clears _asset_uuid_cache between tests — prevents state bleed between test cases"
  - "/camera/latest.jpg added as bridge route alias, not rename — /camera/snapshot preserved for backward compat"
metrics:
  duration_seconds: 254
  completed_date: "2026-04-13"
  tasks_completed: 2
  tasks_total: 2
  files_created: 9
  files_modified: 1
  tests_added: 34
  tests_passing: 34
---

# Phase 13 Plan 01: FarmOS Core Library Modules Summary

**One-liner:** Session-cookie FarmOS client, parameterized TimescaleDB aggregation, and markdown report builder with anomaly detection — all TDD-built with 34 passing tests.

## What Was Built

Three Python library modules forming the data layer for the FarmOS daily report agent, plus a bridge endpoint alias:

**`farmos_client.py`** — FarmOS JSON:API integration using proven session-cookie auth:
- `get_session()`: POST to `/user/login?_format=json`, extract `csrf_token`, set `X-CSRF-Token` + JSON:API headers. 10s timeout.
- `get_asset_uuid()`: GET `/api/asset/structure`, find by name, cache UUID. 10s timeout.
- `upload_photo()`: POST binary JPEG to `/api/log/observation/image` with `octet-stream` + `Content-Disposition`. 30s timeout.
- `create_observation()`: POST `log--observation` with asset and optional image relationships. 15s timeout.
- `observation_exists_for_date()`: GET with `CONTAINS` name filter for duplicate prevention (D-09).

**`telemetry_query.py`** — TimescaleDB daily aggregation:
- `query_daily_summary()`: Parameterized SQL `AVG/MIN/MAX/COUNT GROUP BY topic` with `%s` placeholders (T-13-01). Computes midnight-to-midnight UTC from local time via `ZoneInfo`. Returns dict with None entries for missing topics.

**`report_builder.py`** — Markdown summary builder:
- `build_report_markdown()`: Produces markdown table (Humidity %, Temperature C, CO2 ppm, Humidifier Duty %). Humidifier min/max shown as `—`. None values shown as `N/A`. Anomaly section appended if humidity avg outside `target ± 3×tolerance` or CO2 exceeds warn threshold or any topic has 0 samples.

**Bridge `/camera/latest.jpg`** — Express route alias returning `latestFrame` buffer as JPEG, identical to `/camera/snapshot`. Required by farmos_agent (D-05).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Module-level UUID cache caused test state bleed**
- **Found during:** Task 1 GREEN phase — `test_get_asset_uuid_returns_none_when_not_found` failed because cache hit from previous test
- **Issue:** `_asset_uuid_cache` persisted across tests; second test found UUID cached from first test
- **Fix:** Added `_cache` parameter with default `None` to `get_asset_uuid()` for DI, plus `autouse` fixture in `conftest.py` that clears `_asset_uuid_cache` before/after each test
- **Files modified:** `src/farmos-agent/farmos_agent/farmos_client.py`, `src/farmos-agent/tests/conftest.py`
- **Commit:** a7e527b

## Threat Mitigations Applied

| Threat | Mitigation | Location |
|--------|-----------|----------|
| T-13-01 SQL injection | Parameterized `%s` placeholders in psycopg2 | `telemetry_query.py` |
| T-13-02 Credential disclosure | No credentials hardcoded; load from env/caller | `farmos_client.py` docstring |
| T-13-03 CSRF bypass | X-CSRF-Token from login response on every session | `get_session()` |
| T-13-05 Hung connections | Timeouts on all requests (10s reads, 30s upload, 15s POST) | All farmos_client functions |

## Known Stubs

None — all functions are fully implemented. Plan 02 wires these modules into the ROS2 lifecycle node.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `src/farmos-agent/farmos_agent/farmos_client.py` | FOUND |
| `src/farmos-agent/farmos_agent/telemetry_query.py` | FOUND |
| `src/farmos-agent/farmos_agent/report_builder.py` | FOUND |
| `src/farmos-agent/tests/test_farmos_client.py` | FOUND |
| `src/farmos-agent/tests/test_telemetry_query.py` | FOUND |
| `src/farmos-agent/tests/test_report_builder.py` | FOUND |
| `src/mission-control/bridge/src/index.js` | FOUND |
| Commit d725700 (failing tests) | FOUND |
| Commit a7e527b (implementation) | FOUND |
| Commit c5ee028 (bridge alias) | FOUND |
| 34 tests passing | PASSED |
