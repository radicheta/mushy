---
phase: 21-camera-history-continuous-persistence
verified: 2026-04-19T16:00:00Z
status: passed
score: 11/11 must-haves verified
overrides_applied: 0
---

# Phase 21: Camera history continuous persistence — Verification Report

**Phase Goal:** Close the "blank hours" gap in fc1 camera history. Bridge becomes the continuous-rate persister keeping ROS subscription alive regardless of viewer. New Timescale `snapshots` hypertable (D-03 columns). 365-day retention with 30-day grace. `GET /camera/history` endpoint (ISO params, items array, 5000 cap, has_more). `/health` exposes `snapshots.last_24h` + `oldest_at`. Mission Control system-health panel gains "Snapshots" chip.

**Verified:** 2026-04-19T16:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (merged from CONTEXT D-01..D-06b and PLAN must_haves)

| # | Truth (Decision) | Status | Evidence |
|---|------------------|--------|----------|
| 1 | **D-01** — Bridge stays subscribed to `/fc1/camera/compressed` regardless of viewer presence | ✓ VERIFIED | `persistenceKeepalive` flag at index.js:60; guard in `maybeCameraUnsubscribe` at line 117; flipped true + prime at startup line 603-604. Live `/health`: `camera.subscribed: true, clients: 0` |
| 2 | **D-02** — Idle cadence 1 frame / 5 min, tagged `source='idle'` | ✓ VERIFIED | `decideSource(mjpegClients.size)` in `saveSnapshot` line 132; `SNAPSHOT_INTERVAL_MIN=5` in docker-compose.yml:24; live evidence: idle row landed at t+5min, `source='idle'` in DB |
| 3 | **D-03** — `snapshots` hypertable exists with 6 D-03 columns, CHECK constraint, 1-day chunk, (camera_id, captured_at DESC) index | ✓ VERIFIED | initDb() lines 180-198: CREATE TABLE w/ all 6 columns + CHECK, `create_hypertable('snapshots','captured_at', chunk_time_interval => INTERVAL '1 day')`, `CREATE INDEX idx_snapshots_camera_captured` |
| 4 | **D-04** — 365-day retention with 30-day grace, atomic file+row prune | ✓ VERIFIED | retention.js runPrune: SELECT→unlink(ENOENT-OK)→DELETE per row; grace guard via shouldPrune; clampRetentionDays floor=30. Live log: `[retention] skip — oldest snapshot null days (grace 30)` |
| 5 | **D-05** — Viewer-connected cadence = same 5-min, tagged `source='viewer'` | ✓ VERIFIED | `decideSource(mjpegClients.size > 0 ? 'viewer' : 'idle')` in snapshot_helpers.js; saveSnapshot uses it line 132 |
| 6 | **D-06a** — `GET /camera/history?from=&to=&camera_id=` returns ISO-params + items array, 5000 cap, has_more | ✓ VERIFIED | Route at index.js:367-401: ISO-string params (via validateHistoryParams/Date.parse), returns `{camera_id, from, to, count, has_more, items: [...]}` ORDER BY captured_at ASC, LIMIT 5001 with slice-and-flag pattern. Live curl returned correct shape |
| 7 | **D-06b** — `/health` exposes `snapshots.last_24h` + `oldest_at` | ✓ VERIFIED | async /health handler at index.js:232-273: nested `snapshots: {last_24h, oldest_at}` + flat aliases `snapshots_last_24h`, `oldest_snapshot_at`. Try/catch swallows DB errors → null fields, 200 status. Live: `snapshots: {last_24h: 3, oldest_at: "2026-04-19T15:34:30.785Z"}` |
| 8 | **D-06b.UI** — Mission Control system-health panel gains "Snapshots" chip | ✓ VERIFIED | plugin.js:570 `lights.snapshots = makeStatusLight(container, 'Snapshots')`; thresholds at lines 619-631 (green ≥200, red ==0, grey 1..199/null); grey fallback on bridge unreachable line 641. Farmer confirmed chip renders in expected grey initial state |
| 9 | **Pitfall 1** — saveSnapshot skips write+INSERT when isFrameStale() true | ✓ VERIFIED | saveSnapshot line 126: `if (isFrameStale()) { log; return; }` before fs.writeFile + INSERT |
| 10 | **SNAPSHOT_INTERVAL_MIN default 15 → 5 in runtime compose** | ✓ VERIFIED | docker-compose.yml line 24: `SNAPSHOT_INTERVAL_MIN=5` (old value absent) |
| 11 | **Test suite green (persistence, retention, history)** | ✓ VERIFIED | 33/33 jest tests pass per orchestrator evidence; test files present at test/{snapshot,retention,history}.test.js |

**Score:** 11/11 truths verified

### Required Artifacts (Levels 1–3)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/mission-control/bridge/src/index.js` | persister keepalive, hypertable DDL, /camera/history route, /health extension, retention wiring | ✓ VERIFIED | All call-sites present and wired: require('./retention'), require('./history_validate'), require('./snapshot_helpers') |
| `src/mission-control/bridge/src/snapshot_helpers.js` | decideSource + shouldSkipSnapshot pure fns | ✓ VERIFIED | 11 lines, CommonJS exports, imported at index.js:8 |
| `src/mission-control/bridge/src/retention.js` | clampRetentionDays, shouldPrune, runPrune | ✓ VERIFIED | 61 lines, CommonJS exports, imported at index.js:9 and wired via setInterval/setTimeout lines 616-623 |
| `src/mission-control/bridge/src/history_validate.js` | validateHistoryParams (ISO-8601) | ✓ VERIFIED | 25 lines, ISO-string based per RESEARCH Q3 resolution + fix commit 53a530c; imported at index.js:10 |
| `src/mission-control/bridge/test/{snapshot,retention,history}.test.js` | Unit tests for helpers | ✓ VERIFIED | All 3 files present; history.test.js updated to match ISO implementation; 33/33 passing |
| `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` | "Snapshots" chip + pollHealth wiring | ✓ VERIFIED | lights.snapshots chip + all 4 state branches (green/red/grey-degraded/grey-unknown) + bridge-unreachable fallback |
| `docker-compose.yml` | SNAPSHOT_INTERVAL_MIN=5, RETENTION_DAYS, RETENTION_GRACE_DAYS | ✓ VERIFIED | Lines 24, 27, 28 confirmed; no stale `=15` value |
| `scripts/verify/phase-21-smoke.sh` | Live-stack smoke | ✓ VERIFIED | Present, executable (orchestrator evidence) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `maybeCameraUnsubscribe()` | `persistenceKeepalive` flag | early-return guard | ✓ WIRED | index.js:117 `mjpegClients.size > 0 \|\| persistenceKeepalive \|\| ...` |
| startup block | `persistenceKeepalive = true` + `ensureCameraSubscribed()` | rclnodejs.init().then | ✓ WIRED | index.js:603-604 |
| `saveSnapshot()` | snapshots table INSERT | parameterized pool.query inside fs.writeFile callback | ✓ WIRED | index.js:146-150 |
| `initDb()` | snapshots hypertable + index | CREATE TABLE IF NOT EXISTS + create_hypertable + CREATE INDEX | ✓ WIRED | index.js:180-198 |
| bridge startup | `retention.runPrune` | setInterval 24h + setTimeout 60s | ✓ WIRED | index.js:616-623 |
| `app.get('/camera/history')` | snapshots SELECT | parameterized query with camera_id/from/to/LIMIT N+1 | ✓ WIRED | index.js:373-378 |
| `app.get('/health')` | snapshots aggregates | Promise.all [COUNT 24h, MIN captured_at] | ✓ WIRED | index.js:241-244 |
| plugin.js `pollHealth()` | `/health.snapshots` | fetch().then → `data.snapshots` branches | ✓ WIRED | plugin.js:619-631 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `/health` snapshots fields | `snapshotsLast24h`, `oldestSnapshotAt` | `pool.query` against live snapshots hypertable | YES (live: last_24h=3, oldest_at ISO) | ✓ FLOWING |
| `/camera/history` items | `result.rows` | `pool.query` SELECT from snapshots | YES (live curl returned inserted row in correct shape) | ✓ FLOWING |
| snapshots hypertable | per-row INSERT from saveSnapshot | ROS `/fc1/camera/compressed` → `latestFrame` → fs.writeFile → INSERT | YES (live: idle row landed at t+5min) | ✓ FLOWING |
| Mission Control "Snapshots" chip | `data.snapshots.last_24h` from /health | fetch polling | YES (farmer-confirmed chip renders grey — expected for 1-row DB) | ✓ FLOWING |

### Behavioral Spot-Checks (from orchestrator live-verification evidence)

| Behavior | Check | Result | Status |
|----------|-------|--------|--------|
| Persister invariant live | `/health` → `camera.subscribed: true, clients: 0` | confirmed pre→post transition | ✓ PASS |
| Idle snapshot lands at 5-min cadence | first idle row at t+5min, `source='idle'` | confirmed | ✓ PASS |
| `/health` snapshots stats exposed | `snapshots: {last_24h: 3, oldest_at: ISO}` after 10+ min | confirmed | ✓ PASS |
| `/camera/history` ISO params + items key | curl returned `{items:[{captured_at ISO, ...}], count, has_more, from, to}` | confirmed (post-fix 53a530c) | ✓ PASS |
| Retention grace guard | Log `[retention] skip — oldest snapshot null days (grace 30)` | confirmed | ✓ PASS |
| Test suite | 33/33 jest tests green | confirmed | ✓ PASS |
| Mission Control chip | Farmer-confirmed "Snapshots" chip renders in expected grey state | confirmed | ✓ PASS |

### Requirements Coverage (CONTEXT D-01..D-06b)

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| D-01 | 21-02 | Bridge persister invariant | ✓ SATISFIED | persistenceKeepalive + guard + startup prime (live-verified) |
| D-02 | 21-02 | Idle cadence 1/5min + source='idle' | ✓ SATISFIED | SNAPSHOT_INTERVAL_MIN=5 + decideSource + live row |
| D-03 | 21-02 | snapshots hypertable schema | ✓ SATISFIED | DDL in initDb, all 6 columns + CHECK + index |
| D-04 | 21-03 | 365-day retention + 30-day grace | ✓ SATISFIED | retention.js + live skip-log |
| D-05 | 21-02 | Viewer cadence = same 5min, source='viewer' | ✓ SATISFIED | decideSource branches on mjpegClients.size |
| D-06a | 21-03 | /camera/history endpoint | ✓ SATISFIED | ISO params + items key + cap + has_more (live-verified post 53a530c) |
| D-06b | 21-04 | /health snapshots + MC chip | ✓ SATISFIED | /health fields + Snapshots chip (farmer-confirmed) |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No blocking anti-patterns detected | — | — |

Notes:
- `console.log` in saveSnapshot/retention are intentional operator signals (logged liveness).
- No TODO/FIXME/placeholder/hardcoded-empty-render patterns detected in Phase 21 files.
- Stall-safety gate (`isFrameStale()`) correctly prevents the duplicate-stale-frame DoS class (Pitfall 1 / T-21-04).

### Human Verification Required

None. Farmer UAT approval (2026-04-19) satisfies Plan 21-04's human checkpoint — "Snapshots chip renders in expected grey initial state" observed and accepted. No additional human gating requested.

### Observations (out of phase scope)

- Farmer-observed Sensors chip flicker is Phase 16 scope (sensor_health TRANSIENT_LOCAL vs 10s plugin threshold), not a Phase 21 regression. Recorded here for completeness; not a Phase 21 gap.
- Fix commit `53a530c` corrected a plan-03 deviation (ms-epoch + `rows` key) to align `/camera/history` with CONTEXT D-06a + RESEARCH Q3 (ISO strings + `items` key). Fix is merged; tests were updated to match.

### Gaps Summary

None. All 7 CONTEXT decisions (D-01..D-06b) are implemented, wired, live-verified, and farmer-approved. All supporting artifacts exist, are substantive, are correctly linked, and flow real data.

---

*Verified: 2026-04-19T16:00:00Z*
*Verifier: Claude (gsd-verifier)*
