---
phase: 13-farmos-daily-report
plan: "03"
subsystem: farmos-agent, bridge
tags: [bug-fix, gap-closure, tests, humidity-units, auth, staleness-guard]
dependency_graph:
  requires: ["13-01", "13-02"]
  provides: ["FMOS-03-fix", "CR-01-fix", "CR-02-fix", "WR-01-fix", "test-coverage"]
  affects: ["farmos-agent container", "bridge camera endpoints"]
tech_stack:
  added: []
  patterns: ["session.post for authenticated uploads", "isFrameStale() staleness guard", "percentage-scale telemetry fixtures"]
key_files:
  modified:
    - src/farmos-agent/farmos_agent/report_builder.py
    - src/farmos-agent/farmos_agent/farmos_client.py
    - src/farmos-agent/tests/conftest.py
    - src/mission-control/bridge/src/index.js
  created:
    - src/farmos-agent/tests/test_farmos_client.py
    - src/farmos-agent/tests/test_telemetry_query.py
    - src/farmos-agent/tests/test_report_builder.py
decisions:
  - "Use session.post with explicit headers= dict for upload_photo — requests.Session merges headers so cookies+CSRF token are preserved while Content-Type is overridden for this one call"
  - "FRAME_MAX_AGE_MS = 2 hours — farmos-agent already handles 503 via disk snapshot fallback, so this is a safe gate"
  - "Humidity default target updated to 82.0 (percentage scale) and tolerance to 1.0 — matches empirically chosen ±1% operating band (RH operating band memory note)"
metrics:
  duration_minutes: 25
  completed_date: "2026-04-13"
  tasks_total: 2
  tasks_completed: 2
  files_modified: 4
  files_created: 3
  tests_added: 25
---

# Phase 13 Plan 03: Gap Closure Summary

**One-liner:** Fixed humidity 100x display bug, wired upload_photo to authenticated session, added 2-hour staleness guard to bridge camera endpoints, and committed 25 unit tests that were missing from HEAD.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Fix humidity units, upload_photo auth, CONTAINS filter, commit test files | da27f67 | report_builder.py, farmos_client.py, conftest.py, test_farmos_client.py, test_telemetry_query.py, test_report_builder.py |
| 2 | Add staleness guard to bridge camera endpoints | 7e33477 | index.js |

## Bugs Fixed

### FMOS-03 / IN-01: Humidity values 100x wrong
`report_builder.py` was multiplying humidity by 100 assuming a 0-1 decimal fraction input. The bridge stores `fc.humidity` as a percentage (e.g., `94.07` for 94.07% RH). Three locations fixed:
- `_TOPIC_DISPLAY` formatter: `round(avg * 100, 1)` → `round(avg, 1)`
- `_fmt_metric`: same change
- `_detect_anomalies`: anomaly message simplified; `_DEFAULT_CONFIG_TARGETS` updated to `humidity_target: 82.0` and `humidity_tolerance: 1.0` (percentage scale)

### CR-01: upload_photo drops session cookies
`upload_photo` was calling `requests.post(...)` directly, manually copying headers but not the session's cookie jar. FarmOS requires the session cookie for authentication. Fixed to use `session.post(...)` with an explicit `headers=` dict — `requests.Session` merges these with session headers so cookies and CSRF token are preserved.

### WR-01: CONTAINS filter can false-positive
`observation_exists_for_date` used `filter[name][operator]=CONTAINS` — an exact-date log name like `FC-1 Daily Report 2026-04-10` could in theory match unrelated observations. Changed to `'='` for precise duplicate detection.

### CR-02: Bridge serves stale camera frames
Both `/camera/snapshot` and `/camera/latest.jpg` served `latestFrame` with no age check. If the camera disconnected while the bridge stayed running, a days-old frame would be posted to FarmOS with no warning. Added `FRAME_MAX_AGE_MS = 2 * 60 * 60 * 1000` constant and `isFrameStale()` helper. Both endpoints now return `503` when the frame is null, has no timestamp, or is older than 2 hours. The farmos-agent already handles 503 via its disk snapshot fallback.

### Test files missing from HEAD
`test_farmos_client.py`, `test_telemetry_query.py`, and `test_report_builder.py` were referenced in Plan 01 SUMMARY but never committed to HEAD. All three are now created and pass (25 tests total). `conftest.py` fixtures updated from decimal-fraction humidity (`0.823`) to percentage-scale (`82.3`) to match actual DB storage.

## Verification Results

```
25 passed in 0.04s
```

All plan verification checks pass:
- `grep "round(avg, 1)" report_builder.py` — humidity not multiplied
- `grep "session.post" farmos_client.py` — upload uses session
- `grep "FRAME_MAX_AGE_MS" index.js` — staleness constant exists
- `grep "'='" farmos_client.py` — exact match operator
- Test files committed and passing

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_get_session_sets_headers mock setup**
- **Found during:** Task 1 test run
- **Issue:** Test assigned `session_instance.headers = {}` (plain dict), causing `dict.update.assert_called_once()` to raise `AttributeError` since `dict.update` is a real method, not a mock
- **Fix:** Removed manual `session_instance.headers = {}` assignment — let `MagicMock` auto-generate a mock headers attribute with trackable `.update()`
- **Files modified:** `src/farmos-agent/tests/test_farmos_client.py`
- **Commit:** da27f67

## Known Stubs

None — all data paths are wired to real sources.

## Threat Flags

None — all changes close existing mitigations (T-13-10, T-13-11, T-13-12) with no new surface introduced.

## Self-Check: PASSED
