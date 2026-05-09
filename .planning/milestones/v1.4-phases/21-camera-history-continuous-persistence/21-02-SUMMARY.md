---
phase: 21-camera-history-continuous-persistence
plan: 02
subsystem: bridge-persistence
tags: [bridge, timescale, hypertable, camera, persistence, jest]

requires:
  - phase: 21-camera-history-continuous-persistence
    plan: 01
    provides: jest 29.x + test/ scaffold for bridge unit tests
  - phase: 12-subscriber-aware-camera
    provides: ensureCameraSubscribed / maybeCameraUnsubscribe invariant (now relaxed for persister)
  - phase: 14-fc-camera-idle-stall-hotfix
    provides: isFrameStale() primitive reused as Pitfall 1 gate
provides:
  - snapshots hypertable in Timescale (D-03 schema, 1-day chunks, camera_id+captured_at DESC index)
  - persistenceKeepalive flag — bridge stays subscribed to /fc1/camera/compressed with 0 viewers (D-01)
  - source-tagged saveSnapshot() with stall-safety gate and DB INSERT (D-02 idle, D-05 viewer)
  - decideSource + shouldSkipSnapshot pure helpers + 8 unit tests
  - SNAPSHOT_INTERVAL_MIN default 15 → 5 in runtime docker-compose
affects: [21-03, 21-04]

tech-stack:
  added: []
  patterns:
    - "Pure decision helpers extracted to snapshot_helpers.js — unit-testable without ROS side effects"
    - "Hypertable DDL appended to existing initDb() mirroring telemetry pattern (CREATE TABLE IF NOT EXISTS + create_hypertable with if_not_exists + CREATE INDEX IF NOT EXISTS)"
    - "INSERT runs inside fs.writeFile callback — file-first, row-second; row-failure leaves file on disk for retention sweep"

key-files:
  created:
    - src/mission-control/bridge/src/snapshot_helpers.js
    - src/mission-control/bridge/test/snapshot.test.js
  modified:
    - src/mission-control/bridge/src/index.js
    - docker-compose.yml

key-decisions:
  - "persistenceKeepalive added as early-return guard in maybeCameraUnsubscribe(), preserving Phase 12 viewer semantics (no viewer path change)"
  - "fps column stored as null for both idle and viewer snapshots — fc_camera publish rate not tracked at bridge today; D-03 column is nullable"
  - "captured_at = new Date() at write-decision time (not ROS message header stamp) — matches telemetry clock source, Pitfall 6 consistency"
  - "On INSERT failure, file stays on disk (no rollback); retention sweep handles orphans"

patterns-established:
  - "Pure helper extraction pattern: src/snapshot_helpers.js lets tests import without triggering rclnodejs.init() side effects in index.js"
  - "Stall-safety gate via isFrameStale() in the snapshot path — mandatory for any future periodic persister"

requirements-completed: [D-01, D-02, D-03, D-05]

duration: ~84s
completed: 2026-04-19
---

# Phase 21 Plan 02: Continuous-persistence invariant + snapshots hypertable Summary

**Bridge now subscribes to /fc1/camera/compressed at startup and stays subscribed with zero viewers; each 5-min tick writes a source-tagged row into a new Timescale `snapshots` hypertable, gated on isFrameStale() to prevent Phase-14-class stale-frame regressions.**

## Performance

- **Duration:** ~84 seconds (1 min 24 s)
- **Started:** 2026-04-19T15:20:02Z
- **Completed:** 2026-04-19T15:21:26Z
- **Tasks:** 2
- **Files:** 4 (2 created + 2 modified)

## Accomplishments

- `persistenceKeepalive` flag added to module scope; flipped true + `ensureCameraSubscribed()` primed immediately before the snapshot `setInterval` in the startup block, so the bridge is subscribed the moment ROS + DB are ready.
- `maybeCameraUnsubscribe()` gained a second early-return guard (`|| persistenceKeepalive`) — Phase 12 viewer code path is untouched.
- `initDb()` extended (before the `Schema initialized` log) with the D-03 `snapshots` DDL: 6 columns, `CHECK (source IN ('viewer','idle','manual'))`, `create_hypertable(chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)`, and `CREATE INDEX IF NOT EXISTS idx_snapshots_camera_captured ON snapshots (camera_id, captured_at DESC)`. Fully idempotent.
- `saveSnapshot()` rewritten: drops `if (!latestFrame) return` in favor of `if (isFrameStale()) return` (covers both null-frame and >2h-old cases); captures `capturedAt` / `bytes` / `source = decideSource(mjpegClients.size)` before the async write; after `fs.writeFile` succeeds, runs a parameterized `INSERT INTO snapshots (...) VALUES ($1..$6)` with `fps=null`. INSERT failure is logged and swallowed — file stays on disk.
- Pure helpers `decideSource(size)` and `shouldSkipSnapshot({latestFrame, lastFrameTime, now, maxAgeMs})` extracted to `src/mission-control/bridge/src/snapshot_helpers.js` so tests can require them without triggering the bridge's `rclnodejs.init()` side effects.
- 8 jest cases across 2 describes cover the source-tagging matrix (idle / single viewer / many viewers) and the stall-safety gate (null-frame, null-time, fresh, stale, exact-boundary). Run in ~0.2s.
- Runtime `docker-compose.yml` line 24 changed from `SNAPSHOT_INTERVAL_MIN=15` to `SNAPSHOT_INTERVAL_MIN=5` (D-02).

## Task Commits

1. **Task 1: Add snapshots hypertable + persister invariant + source-tagged saveSnapshot** — `ae7ac6c` (feat)
2. **Task 2: Unit tests for source-tagging + stall-safety decision logic** — `c7ab493` (test)

## Files Created/Modified

- `src/mission-control/bridge/src/index.js` — +persistenceKeepalive flag, `require('./snapshot_helpers')`, maybeCameraUnsubscribe guard, initDb snapshots DDL block, saveSnapshot rewrite with stall gate + source tag + INSERT, startup-block keepalive flip + prime
- `src/mission-control/bridge/src/snapshot_helpers.js` (new) — `decideSource`, `shouldSkipSnapshot` pure functions + CommonJS exports
- `src/mission-control/bridge/test/snapshot.test.js` (new) — 8 jest cases (3 decideSource + 5 shouldSkipSnapshot)
- `docker-compose.yml` — SNAPSHOT_INTERVAL_MIN 15 → 5

## Decisions Made

- **Helper extraction over inline source-tag ternary:** The plan called for `decideSource(mjpegClients.size)` precisely so Task 2's jest tests could import without loading the bridge (which calls `rclnodejs.init()` at module load). Keeping the helper file purely functional and side-effect-free (no `require` of any bridge code) is what makes the 0.2s test turnaround possible.
- **`fs.writeFile` callback owns the INSERT, not a parallel `Promise.all`:** File-first / row-second ordering means a file on disk without a row is recoverable (retention will orphan-cleanup), while a row without a file would be worse (farmer sees phantom timeline entries). The plan's pattern is correct; we followed it verbatim.
- **No change to the existing telemetry DDL in initDb:** The snapshots block is appended, not interleaved — if a future hotfix needs to revert the snapshots feature, a single contiguous block is easier to remove.

## Deviations from Plan

None. Plan executed exactly as written — every code edit matches the action snippets in 21-02-PLAN.md.

## Threat Flags

None. All new surface (snapshots INSERT SQL, snapshots table, bytes/file_path/source payload) was already enumerated in the plan's `<threat_model>` (T-21-03..T-21-07). Mitigations in place:

- T-21-03 (Tampering — SQL injection on INSERT): parameterized `$1..$6` query, no dynamic SQL.
- T-21-04 (DoS — stale-frame loop): `isFrameStale()` gate at the top of `saveSnapshot` returns before file/DB work.
- T-21-07 (Tampering — idempotent DDL): `CREATE TABLE IF NOT EXISTS` + `if_not_exists => TRUE` + `CREATE INDEX IF NOT EXISTS`.

## Issues Encountered

- None. Task 1 and Task 2 both passed their automated acceptance grep panels + `node --check` on first attempt. Jest suite went 8/8 green on first run.

## Deferred Issues

- **Live-stack verification (curl /health, wait 6 min, SELECT count(*) FROM snapshots GROUP BY source)** is not runnable from this execute-plan session because it requires `docker compose up -d --build bridge` against the live elder-plops stack. Orchestrator or Plan 04 owner to run this against the runtime compose. All static and unit checks pass.
- **`persistenceKeepalive = true` fires only once** in the startup block. If a future phase needs to toggle it on/off (e.g., a debug endpoint to drop the persister subscription), a setter function is the natural extension point — deferred, not needed for Phase 21.

## User Setup Required

None beyond the standard post-commit deploy step (`docker compose up -d --build bridge` from repo root) owned by the next wave / verification step.

## Next Phase Readiness

- Plan 03 (`21-03`) can now build `GET /camera/history` against a populated `snapshots` table. Schema shape matches D-06a (`captured_at, camera_id, file_path, bytes, source, fps`).
- Plan 04 (`21-04`) can extend `/health` with `snapshots_last_24h` and `oldest_snapshot_at` — the table exists, rows accumulate every 5 min.
- `scripts/verify/phase-21-smoke.sh` (from Plan 01) will now stop returning the "snapshots table missing" branch once the bridge is rebuilt and has run `initDb` once.

## Self-Check: PASSED

- FOUND: src/mission-control/bridge/src/snapshot_helpers.js
- FOUND: src/mission-control/bridge/test/snapshot.test.js
- FOUND: modifications to src/mission-control/bridge/src/index.js (persistenceKeepalive, decideSource require, CREATE TABLE snapshots, INSERT INTO snapshots, isFrameStale() gate)
- FOUND: docker-compose.yml SNAPSHOT_INTERVAL_MIN=5 (SNAPSHOT_INTERVAL_MIN=15 absent)
- FOUND: commit ae7ac6c (Task 1)
- FOUND: commit c7ab493 (Task 2)
- VERIFIED: `node --check src/mission-control/bridge/src/index.js` exits 0
- VERIFIED: `cd src/mission-control/bridge && npx jest test/snapshot.test.js` — 8/8 passed in 0.199s

---
*Phase: 21-camera-history-continuous-persistence*
*Completed: 2026-04-19*
