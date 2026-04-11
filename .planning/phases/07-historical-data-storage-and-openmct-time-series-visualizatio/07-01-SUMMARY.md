---
phase: 07-historical-data-storage-and-openmct-time-series-visualizatio
plan: "01"
subsystem: bridge
tags: [timescaledb, nodejs, docker, ros2, telemetry]
dependency_graph:
  requires: []
  provides: [timescaledb-ingestion, bridge-nodejs-runtime, telemetry-hypertable]
  affects: [src/mission-control/bridge, src/docker-compose.yml]
tech_stack:
  added: [pg@8.20.0, express@5.2.1, nodejs-20-lts]
  patterns: [pg-pool, http-createserver-shared-port, try-catch-db-resilience]
key_files:
  created: [src/.env]
  modified:
    - src/docker-compose.yml
    - src/mission-control/bridge/Dockerfile
    - src/mission-control/bridge/entrypoint.sh
    - src/mission-control/bridge/package.json
    - src/mission-control/bridge/src/index.js
decisions:
  - "Single port 8081 shared by Express HTTP and WebSocket via http.createServer — avoids second docker-compose port mapping"
  - "dbReady flag gates all inserts so TimescaleDB outage cannot affect live WebSocket broadcast"
  - "Store topic keys as fc.humidity/fc.temperature/fc.co2/fc.humidifier (plugin.js format) — matches history URL routing 1:1"
  - "CORS set via manual res.setHeader instead of cors npm package — avoids extra dependency"
metrics:
  duration: "15min"
  completed_date: "2026-04-07"
  tasks_completed: 3
  files_modified: 5
---

# Phase 07 Plan 01: Bridge Node.js Runtime + TimescaleDB Ingestion Summary

Switch the bridge container from rosbridge (Python) to Node.js index.js entrypoint, add TimescaleDB ingestion for all 4 ROS topics, and migrate credentials to .env.

## What Was Built

The bridge container now runs a Node.js service (rclnodejs + pg + Express + ws) instead of the Python rosbridge stack. Every ROS message on all 4 topics is written to a TimescaleDB hypertable. Live WebSocket broadcast continues on port 8081 alongside a new HTTP server for future history endpoints.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Migrate credentials to .env and update docker-compose | 0f7f299 | src/docker-compose.yml |
| 2 | Update Dockerfile and entrypoint to run Node.js bridge | 220e27b | src/mission-control/bridge/Dockerfile, entrypoint.sh |
| 3 | Rewrite index.js with pg ingestion for all 4 topics | c6a2a36 | src/mission-control/bridge/src/index.js, package.json |

## Key Changes

**src/.env (gitignored):** Created with TIMESCALE_PASSWORD, TIMESCALE_HOST, TIMESCALE_DB, TIMESCALE_USER.

**src/docker-compose.yml:** TimescaleDB service now reads `POSTGRES_PASSWORD=${TIMESCALE_PASSWORD}`. Bridge service gains full set of TIMESCALE_* env vars and ROS_DOMAIN_ID=69.

**Dockerfile:** Removed ros-jazzy-rosbridge-suite, python3-colcon-common-extensions, python3-pip, colcon build, pip install. Added Node.js 20 LTS via nodesource, npm install --production.

**entrypoint.sh:** Removed ros2 launch and FAKE_SENSORS conditional. Now sources ROS setup, exports RMW_IMPLEMENTATION=rmw_cyclonedds_cpp, and execs `node /opt/bridge/src/index.js`.

**index.js:** Full rewrite. pg Pool from env vars. initDb() creates telemetry table + hypertable (1-day chunk interval) + topic/time index. Subscribes to all 4 topics; each callback broadcasts JSON over WebSocket and inserts a parameterized row into telemetry. All DB operations wrapped in try/catch — never crashes WebSocket. Combined http.createServer shares port 8081 between Express and WebSocket. /health endpoint returns `{status, db}`.

**package.json:** Version bumped to 2.0.0. Added pg@^8.20.0 and express@^5.2.1.

## Decisions Made

- **Single port 8081:** Express and WebSocket share one http.Server. Avoids exposing a second container port in docker-compose. OpenMCT plugin calls `ws://host:8081` for live data and `http://host:8081/history/...` for history.
- **dbReady flag:** Set to true only after initDb() succeeds. All insertTelemetry() calls check this flag first. TimescaleDB can be down at startup or go down mid-run without affecting WebSocket broadcast.
- **Topic key format in DB:** Store as `fc.humidity` (plugin.js key format), not `/fc1/humidity` (ROS topic). History URL routing is a 1:1 match with sensor.identifier.key — no mapping needed in Plan 02.
- **CORS via manual header:** Added `res.setHeader('Access-Control-Allow-Origin', '*')` middleware rather than adding the cors npm package. Sufficient for single-origin internal use (Pitfall 4 from research).

## Deviations from Plan

**1. [Rule 2 - Missing Critical Functionality] CORS headers added**
- **Found during:** Task 3
- **Issue:** Research document (Pitfall 4) identified that OpenMCT at port 8080 fetching from bridge at port 8081 would be blocked by CORS. Plan did not specify adding CORS headers in Plan 01.
- **Fix:** Added global CORS middleware `res.setHeader('Access-Control-Allow-Origin', '*')` to the Express app.
- **Files modified:** src/mission-control/bridge/src/index.js
- **Commit:** c6a2a36

## Known Stubs

None. The /history endpoint is intentionally deferred to Plan 02 (per plan spec). The Express app and http.Server are in place — Plan 02 adds the route handler.

## Threat Flags

No new threat surface beyond what the plan's threat model covers. All SQL queries use parameterized `$1, $2, $3` (T-07-01 mitigated). DB password read from env (T-07-03 accepted).

## Self-Check: PASSED

- [x] src/docker-compose.yml modified — commit 0f7f299 exists
- [x] src/mission-control/bridge/Dockerfile modified — commit 220e27b exists
- [x] src/mission-control/bridge/entrypoint.sh modified — commit 220e27b exists
- [x] src/mission-control/bridge/src/index.js modified — commit c6a2a36 exists
- [x] src/mission-control/bridge/package.json modified — commit c6a2a36 exists
