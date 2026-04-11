---
phase: 07-historical-data-storage-and-openmct-time-series-visualizatio
verified: 2026-04-07T20:00:00Z
status: human_needed
score: 10/10 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Open OpenMCT at http://localhost:8080 and verify charts render historical data"
    expected: "Time conductor shows '24h Fixed' as default. Charts for humidity, temperature, CO2, humidifier show historical data points covering the last 24 hours."
    why_human: "Visual rendering, chart population, and time conductor default behavior cannot be verified programmatically without a running browser."
  - test: "Switch time conductor to '5m Realtime' and back to '24h Fixed'"
    expected: "Live streaming works in realtime mode. Switching back to 24h Fixed reloads historical data."
    why_human: "Real-time WebSocket streaming and chart mode switching require interactive browser testing."
  - test: "Verify no double-transform: compare live humidity chart value with REST endpoint value"
    expected: "Both values should be in percentage (e.g., 72.5, not 0.725). curl the REST endpoint and compare with chart display."
    why_human: "Value correlation between live and historical display requires visual comparison."
---

# Phase 7: Historical Data Storage & OpenMCT Time-Series Visualization Verification Report

**Phase Goal:** Wire up the existing TimescaleDB container to ingest ROS telemetry from the bridge service and serve historical data to OpenMCT, enabling time-series charts of past sensor/actuator readings.
**Verified:** 2026-04-07T20:00:00Z
**Status:** human_needed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Bridge container runs Node.js (index.js), not rosbridge Python | VERIFIED | `entrypoint.sh` line 9: `exec node /opt/bridge/src/index.js`; Dockerfile installs Node.js 20 LTS; no `rosbridge`, `colcon build`, or `ros2 launch` in Dockerfile or entrypoint |
| 2 | Bridge connects to TimescaleDB and creates telemetry hypertable on startup | VERIFIED | `index.js` lines 8-14: `new Pool()` with env vars; lines 20-44: `initDb()` with `CREATE TABLE IF NOT EXISTS telemetry`, `create_hypertable`, `CREATE INDEX`; called at line 167 |
| 3 | Every ROS message on the 4 topics inserts a row into the telemetry table | VERIFIED | 4 `createSubscription` calls (lines 174, 185, 196, 207) each call `insertTelemetry()` (line 149) which runs parameterized INSERT |
| 4 | DB failure does not crash the bridge -- WebSocket live data keeps working | VERIFIED | `dbReady` flag (line 17) gates all inserts (line 150); `initDb()` catch logs but continues (line 42); `insertTelemetry()` catch logs only (line 157); WebSocket broadcast is independent |
| 5 | TimescaleDB password is read from .env, not hardcoded in docker-compose | VERIFIED | `src/.env` contains `TIMESCALE_PASSWORD=mysecretpassword`; `docker-compose.yml` line 92: `POSTGRES_PASSWORD=${TIMESCALE_PASSWORD}`; no `mysecretpassword` string in docker-compose; `.env` is gitignored |
| 6 | User can view past sensor readings as time-series charts in OpenMCT | VERIFIED (code-level) | `plugin.js` `request()` (lines 241-258) fetches from `historyUrl/:key?start=&end=`; returns `[{value, utc}]` datums. Requires human verification for visual chart rendering. |
| 7 | History endpoint returns downsampled data using time_bucket for longer ranges | VERIFIED | `index.js` lines 67-72: `bucketInterval()` with 1min/5min/15min thresholds; lines 75-123: `GET /history/:topic` with `time_bucket($1::interval, time)` + `AVG(value)` |
| 8 | OpenMCT time conductor includes a 24h Fixed option that is the default | VERIFIED | `index.html` line 32: `TWENTY_FOUR_HOURS = 24 * ONE_HOUR`; lines 51-58: first `menuOptions` entry `{name: '24h Fixed', bounds: {start: Date.now() - TWENTY_FOUR_HOURS, end: Date.now()}}` |
| 9 | Plugin WebSocket handler works with index.js broadcast format (not rosbridge protocol) | VERIFIED | `plugin.js` lines 174-179: `fieldToKey` mapping dispatches raw `{humidity, temperature, co2, humidifier, timestamp}` objects; no `data.op === 'publish'` check exists |
| 10 | Live values displayed in charts match DB-stored values (no double-transform corruption) | VERIFIED (code-level) | `plugin.js` line 192: datum built as `{value: data[field], utc: data.timestamp}` -- uses broadcast value directly, no `extract()` call; lines 265-276: `msgOrDatum` pattern checks `.utc !== undefined` to skip extract. Requires human verification for visual confirmation. |

**Score:** 10/10 truths verified (code-level; 3 require human visual confirmation)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/mission-control/bridge/src/index.js` | Full bridge with pg writes, history endpoint, WebSocket broadcast | VERIFIED | 227 lines; pg Pool, initDb, insertTelemetry, 4 subscriptions, GET /history/:topic, CORS, health check |
| `src/mission-control/bridge/Dockerfile` | Node.js runtime, npm install | VERIFIED | Node.js 20 LTS via nodesource, build-essential, npm install --production, ROS env sourced |
| `src/mission-control/bridge/entrypoint.sh` | Node.js entrypoint | VERIFIED | `exec node /opt/bridge/src/index.js`; RMW_IMPLEMENTATION set; no rosbridge/ros2 launch |
| `src/.env` | TimescaleDB credentials | VERIFIED | Contains TIMESCALE_PASSWORD, HOST, DB, USER; gitignored |
| `src/docker-compose.yml` | Env var reference for password | VERIFIED | `POSTGRES_PASSWORD=${TIMESCALE_PASSWORD}` on timescale; bridge has full TIMESCALE_* env vars |
| `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` | request() wired, onmessage updated | VERIFIED | request() fetches from history endpoint; fieldToKey dispatcher; msgOrDatum pattern |
| `src/mission-control/frontend/index.html` | 24h Fixed time conductor | VERIFIED | TWENTY_FOUR_HOURS constant; first menuOptions entry with fixed bounds |
| `src/mission-control/bridge/package.json` | pg, express, rclnodejs deps | VERIFIED | pg@^8.20.0, express@^5.2.1, rclnodejs@^1.9.0, ws@^8.16.0 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| index.js | TimescaleDB | pg Pool with env vars | WIRED | `new Pool({host: process.env.TIMESCALE_HOST ...})` at line 8 |
| index.js | ROS2 topics | rclnodejs subscriptions | WIRED | 4 `createSubscription` calls for humidity, temperature, co2, humidifier |
| docker-compose.yml | .env | Variable substitution | WIRED | `${TIMESCALE_PASSWORD}` in both timescale and bridge services |
| plugin.js | index.js REST | fetch('/history/' + key) | WIRED | request() at line 247 constructs URL with sensor.identifier.key |
| index.js | TimescaleDB | time_bucket query | WIRED | History endpoint line 104: `time_bucket($1::interval, time)` |
| plugin.js | index.js WS | fieldToKey dispatch | WIRED | onmessage at line 174 maps field names to sensor keys; dispatches datums |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| plugin.js request() | fetch response | index.js GET /history/:topic | Yes -- parameterized pool.query on telemetry table with time_bucket | FLOWING |
| plugin.js onmessage | datum from WS | index.js broadcast() in ROS callbacks | Yes -- rclnodejs subscriptions feed real sensor data | FLOWING |
| index.js insertTelemetry | pool.query INSERT | ROS message callbacks | Yes -- parameterized INSERT from live sensor values | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| pool.query calls present (>=4) | `grep -c 'pool.query' index.js` | 5 | PASS |
| 4 ROS subscriptions | `grep -c 'createSubscription' index.js` | 4 | PASS |
| All 4 topic keys present | `grep -c 'fc\.' index.js` | 9 | PASS |
| Dockerfile has no rosbridge | `grep 'rosbridge' Dockerfile` | no matches | PASS |
| entrypoint.sh runs node | `grep 'node.*index.js' entrypoint.sh` | match at line 9 | PASS |
| Commits exist | `git log --oneline` for 6 hashes | all 6 verified | PASS |
| .env not tracked | `git ls-files src/.env` | empty (not tracked) | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| HIST-01 | 07-01 | Bridge ingests all 4 ROS topics into TimescaleDB | SATISFIED | 4 createSubscription + insertTelemetry calls in index.js |
| HIST-02 | 07-01 | TimescaleDB schema auto-initialized on bridge startup | SATISFIED | initDb() with CREATE TABLE IF NOT EXISTS + create_hypertable + CREATE INDEX |
| HIST-03 | 07-01 | Database credentials via .env, not hardcoded | SATISFIED | src/.env with TIMESCALE_PASSWORD; docker-compose uses ${TIMESCALE_PASSWORD}; no hardcoded password |
| HIST-04 | 07-02 | REST history endpoint with time-bucketed downsampling | SATISFIED | GET /history/:topic with time_bucket, bucketInterval(), ALLOWED_TOPICS validation |
| HIST-05 | 07-02 | OpenMCT defaults to 24h, charts display historical data | SATISFIED (code) | 24h Fixed first menuOption; request() wired to fetch. Needs human visual confirmation. |
| HIST-06 | 07-02 | Bridge runs Node.js, live WS works when DB unavailable | SATISFIED | entrypoint.sh runs node; dbReady flag gates DB ops; WS broadcast independent |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| -- | -- | No anti-patterns found | -- | -- |

No TODO/FIXME, no placeholder returns, no hardcoded passwords, no empty implementations. The `return []` in plugin.js catch handlers is intentional error resilience.

### Human Verification Required

### 1. OpenMCT Historical Chart Rendering

**Test:** Open http://localhost:8080, navigate to Fruiting Chamber FC-1, open Humidity chart.
**Expected:** Time conductor shows "24h Fixed" as default. Chart displays historical data points from the last 24 hours (not just live streaming).
**Why human:** Visual chart rendering and OpenMCT UI behavior cannot be verified without a running browser.

### 2. Live + Historical Mode Switching

**Test:** Switch time conductor from "24h Fixed" to "5m Realtime" and back.
**Expected:** Live streaming works in realtime mode. Switching to 24h Fixed reloads historical data. All 4 sensor/actuator charts work.
**Why human:** Real-time WebSocket streaming and chart mode transitions require interactive browser testing.

### 3. No Double-Transform Value Corruption

**Test:** Compare a live humidity value shown in the chart with the value returned by `curl "http://localhost:8081/history/fc.humidity?start=$(date -d '1 minute ago' +%s%3N)&end=$(date +%s%3N)"`.
**Expected:** Both values should be in percentage (e.g., 72.5), not raw (0.725) or double-transformed (7250).
**Why human:** Value correlation between live display and REST endpoint requires visual comparison in the running system.

### Gaps Summary

No code-level gaps found. All 10 observable truths are verified at the code level. All 6 requirements (HIST-01 through HIST-06) are satisfied. All artifacts exist, are substantive, and are wired. Data flows are traced from ROS subscriptions through DB inserts through REST queries to OpenMCT chart rendering.

Three items require human visual confirmation in the running system: chart rendering, mode switching, and value accuracy. These are inherently visual behaviors that cannot be verified through static code analysis.

---

_Verified: 2026-04-07T20:00:00Z_
_Verifier: Claude (gsd-verifier)_
