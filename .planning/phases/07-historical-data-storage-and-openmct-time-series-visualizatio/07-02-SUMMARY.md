---
phase: 07-historical-data-storage-and-openmct-time-series-visualizatio
plan: "02"
subsystem: bridge, frontend
tags: [openmct, timescaledb, nodejs, rest, websocket, history, time-series]
dependency_graph:
  requires: [07-01]
  provides: [history-rest-endpoint, openmct-history-provider, 24h-time-conductor-default]
  affects:
    - src/mission-control/bridge/src/index.js
    - src/mission-control/frontend/plugins/fruiting-chamber/plugin.js
    - src/mission-control/frontend/index.html
    - src/mission-control/bridge/Dockerfile
    - src/mission-control/bridge/package.json
tech_stack:
  added: [rclnodejs@1.9.0]
  patterns: [time_bucket-downsampling, allowlist-validation, datum-dispatch-direct, fixed-time-conductor]
key_files:
  created: []
  modified:
    - src/mission-control/bridge/src/index.js
    - src/mission-control/frontend/plugins/fruiting-chamber/plugin.js
    - src/mission-control/frontend/index.html
    - src/mission-control/bridge/Dockerfile
    - src/mission-control/bridge/package.json
decisions:
  - "Direct datum dispatch in onmessage avoids double-transform: broadcast values already in display units, no extract() call"
  - "ALLOWED_TOPICS allowlist before SQL query satisfies T-07-04 (no topic interpolation in SQL)"
  - "bucketInterval() thresholds: <=2h=1min (~120pts), <=12h=5min (~144pts), >12h=15min (~96pts/day)"
  - "rclnodejs upgraded from 0.3.0 to 1.9.0: old version used unmaintained ref native addon incompatible with Node 20"
  - "build-essential + python3-dev added to Dockerfile for native addon compilation"
  - "ROS env sourced before npm install: rclnodejs needs AMENT_PREFIX_PATH at build time"
  - "msgOrDatum pattern in subscribe handler: accepts pre-built datums OR legacy ROS msgs"
metrics:
  duration: "35min"
  completed_date: "2026-04-07"
  tasks_completed: 2
  files_modified: 5
---

# Phase 07 Plan 02: OpenMCT History Provider + Bridge REST Endpoint Summary

REST history endpoint with time_bucket downsampling added to bridge; OpenMCT plugin.js request() wired to fetch from it; WebSocket onmessage rewritten for raw broadcast format; 24h Fixed added as default time conductor; Docker build fixed for rclnodejs 1.9.0 + Node 20.

## What Was Built

**Bridge (index.js):** Added `GET /history/:topic` REST endpoint with ALLOWED_TOPICS allowlist validation, 30-day max range cap, and TimescaleDB `time_bucket()` downsampling. Returns `[{value, utc}]` format matching OpenMCT datum contract.

**Frontend (plugin.js):** Replaced `request()` stub with fetch to bridge REST endpoint. Replaced rosbridge-protocol `onmessage` handler with `fieldToKey` raw-broadcast dispatcher that emits datums directly (no double-transform). Updated `subscribe` handler to accept pre-built datums (`msgOrDatum` pattern).

**Frontend (index.html):** Added `TWENTY_FOUR_HOURS` constant and `24h Fixed` as first Conductor menu entry (fixed bounds, not realtime clock). Charts default to showing last 24 hours on load.

**Docker (Dockerfile + package.json):** Fixed build failure — upgraded rclnodejs 0.3.0 → 1.9.0, added build-essential + python3-dev, source ROS env before npm install.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add history REST endpoint with time_bucket downsampling | 854ffe9 | src/mission-control/bridge/src/index.js |
| 2 | Wire plugin.js request(), fix WS handler, add 24h conductor | 5a05a46 | plugin.js, index.html |
| 3 (partial) | Docker build fix — rclnodejs upgrade | cdae2f5 | Dockerfile, package.json |

## Key Changes

**index.js:** `ALLOWED_TOPICS` allowlist; `bucketInterval()` function; `GET /history/:topic` with parameterized `time_bucket()` query returning `[{value, utc}]`; 400 for invalid topic/range; 503 when `!dbReady`; 30-day max range cap.

**plugin.js:** `historyUrl` option; `request()` fetches `historyUrl/:key?start=&end=`, `.catch(() => [])` for resilience; `onmessage` replaces rosbridge `op:'publish'` check with `fieldToKey` object mapping raw broadcast fields to sensor keys, emits `{value: data[field], utc: data.timestamp}` directly; subscribe `handler` checks `msgOrDatum.utc !== undefined` to distinguish datum from ROS msg.

**index.html:** `var TWENTY_FOUR_HOURS = 24 * ONE_HOUR`; first Conductor entry `{name: '24h Fixed', timeSystem: 'uyt', bounds: {start: Date.now() - TWENTY_FOUR_HOURS, end: Date.now()}}`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed Docker build: rclnodejs@0.3.0 incompatible with Node 20**
- **Found during:** Task 3 pre-checks (bridge rebuild)
- **Issue:** `rclnodejs@^0.3.0` depends on the unmaintained `ref` native addon which fails to compile against Node 20 V8 headers (`is_lvalue_reference_v` not in std, `string_view`/`optional` missing in gcc's C++ default mode). The bridge container had never been successfully rebuilt since Plan 01 — it was still running the old Python rosbridge image.
- **Fix:** Upgraded to `rclnodejs@^1.9.0` (uses `@rclnodejs/ref-*-di` maintained forks). Added `build-essential` + `python3-dev` to Dockerfile. Sourced `/opt/ros/jazzy/setup.bash` before `npm install` (rclnodejs configure script reads `AMENT_PREFIX_PATH`).
- **Files modified:** src/mission-control/bridge/Dockerfile, src/mission-control/bridge/package.json
- **Commit:** cdae2f5

## Known Stubs

None. The history endpoint is fully wired: DB writes (Plan 01) → REST query → OpenMCT request() → chart rendering.

## Threat Flags

No new threat surface beyond the plan's threat model. T-07-04 (topic injection) mitigated by ALLOWED_TOPICS. T-07-05 (unbounded range) mitigated by 30-day cap.

## Checkpoint: Task 3 — Human Verification Pending

Task 3 is a `checkpoint:human-verify` gate. Automated pre-checks completed:

| Check | Command | Result |
|-------|---------|--------|
| Bridge health | `curl http://localhost:8081/health` (from container) | `{"status":"ok","db":true}` |
| Invalid topic rejection | `curl .../history/invalid.topic?start=1&end=2` | `{"error":"Invalid topic"}` |
| Max range rejection | `curl .../history/fc.humidity?start=1&end=9999999999999` | `{"error":"Max range is 30 days"}` |
| Bridge logs | `docker-compose logs bridge` | `[db] Schema initialized`, `[bridge] HTTP + WebSocket server on port 8081` |

Human verification required: OpenMCT at http://localhost:8080 shows 24h Fixed as default, charts render historical data, live/historical values match (no double-transform).

## Self-Check: PASSED

- [x] src/mission-control/bridge/src/index.js modified — commit 854ffe9 exists
- [x] src/mission-control/frontend/plugins/fruiting-chamber/plugin.js modified — commit 5a05a46 exists
- [x] src/mission-control/frontend/index.html modified — commit 5a05a46 exists
- [x] src/mission-control/bridge/Dockerfile modified — commit cdae2f5 exists
- [x] src/mission-control/bridge/package.json modified — commit cdae2f5 exists
- [x] Bridge container running: `src_bridge_1 Up 8081/tcp`
- [x] Health endpoint returns `{"status":"ok","db":true}`
