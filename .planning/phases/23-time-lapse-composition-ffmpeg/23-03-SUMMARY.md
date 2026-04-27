---
phase: 23-time-lapse-composition-ffmpeg
plan: 03
subsystem: timelapse
tags: [timelapse, http, cron, docker-compose, deploy, express, node-cron]

requires:
  - phase: 23-01
    provides: config.js, db.js (initDb, lookupTimelapse, fetchRhForDay, nearestRh)
  - phase: 23-02
    provides: composer.js composeDay pipeline, ffmpeg.js buildArgs+runFfmpeg

provides:
  - routes.js: registerRoutes(app, deps) + validateQuery + singleDayUtc — testable Express 5 routes
  - index.js: server bootstrap with pg Pool, initDb, cron, jobs Map, Express listen
  - docker-compose.yml timelapse service: build, env, volumes, depends_on, restart
  - docker-compose.override.yml timelapse: network_mode host
  - Live timelapse container on elder-plops, first mp4 at /data/timelapse/fc1/2026-04-26.mp4

affects:
  - 23-04 (farmer verification — this plan's output is the thing farmer reviews)

tech-stack:
  added: []
  patterns:
    - "Express 5 app.router.stack (not app._router.stack) for route handler lookup in tests"
    - "validateQuery pure function — all validation before any DB or FS touch (T-23-T1, T-23-T2)"
    - "crypto.randomUUID() for job IDs — no external dep"
    - "setImmediate for async job dispatch — returns 202 before composition starts"
    - "Intl.DateTimeFormat en-CA TZ-aware previous-day calculation (matches alerter heartbeat pattern)"
    - "ffmpeg -f mp4 explicit format flag — required when output path has non-.mp4 extension (.mp4.tmp)"
    - "telemetry column is 'time' aliased as captured_at for downstream caller compatibility"

key-files:
  created:
    - src/mission-control/timelapse/src/routes.js
    - src/mission-control/timelapse/src/index.js
    - src/mission-control/timelapse/test/routes.test.js
    - .planning/phases/23-time-lapse-composition-ffmpeg/23-SMOKE-LOG.md
  modified:
    - docker-compose.yml
    - docker-compose.override.yml
    - src/mission-control/timelapse/src/db.js
    - src/mission-control/timelapse/src/ffmpeg.js
    - src/mission-control/timelapse/test/ffmpeg.test.js

key-decisions:
  - "Express 5 exposes app.router (not app._router) — test helper updated to use app.router.stack"
  - "ffmpeg -f mp4 added to buildArgs — atomic rename writes to .mp4.tmp which ffmpeg cannot infer format from"
  - "telemetry uses 'time' column not 'captured_at' — fixed fetchRhForDay with alias for caller compat"
  - "network_mode: host on timelapse matches alerter pattern — Timescale at localhost:5432 without compose network"
  - "TIMESCALE_HOST=localhost in base stanza (not 'timescale') because host networking puts container on host namespace"

metrics:
  duration: ~25min
  started: 2026-04-27T12:00:00Z
  completed: 2026-04-27T12:23:26Z
  tasks: 3 (task 4 is checkpoint:human-verify — not executed)
  files_created: 4
  files_modified: 5
---

# Phase 23 Plan 03: HTTP Server + Deploy Summary

**Express server + cron + docker-compose timelapse service live on elder-plops — first 287-frame mp4 composed end-to-end at /data/timelapse/fc1/2026-04-26.mp4, all HTTP endpoints verified**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-27T12:00:00Z
- **Completed:** 2026-04-27T12:23:26Z
- **Tasks:** 3 of 4 complete (Task 4 is farmer checkpoint)
- **Files created:** 4
- **Files modified:** 5

## Accomplishments

- `routes.js` exports `registerRoutes` (GET /health, GET /timelapse, GET /timelapse/status/:id) and `validateQuery` — pure DI, testable without HTTP stack
- `index.js` bootstraps pg Pool, calls `initDb`, registers cron at `30 0 * * *` TZ=America/Toronto, starts Express on port 8888
- `docker-compose.yml` timelapse service with build context, env (TIMESCALE_HOST=localhost, TZ, FPS), /data/snapshots:ro + /data/timelapse:rw volumes
- `docker-compose.override.yml` timelapse with `network_mode: "host"` — matches alerter pattern
- Container live on elder-plops: `[db] Schema initialized`, `[cron] scheduled at "30 0 * * *" TZ=America/Toronto`, `[http] listening on 8888`
- `timelapses` table created in Timescale with correct schema
- Smoke: 287 frames from 2026-04-26, composed to 11.58s h264/yuvj420p/12fps mp4 at /data/timelapse/fc1/2026-04-26.mp4
- HTTP endpoints: GET /timelapse returns 200 + file_path for existing day, 400 for bad camera_id; GET /health returns ok
- 44/44 unit tests green

## Task Commits

| # | Type | Description | Hash |
|---|------|-------------|------|
| 1 RED | test | add failing tests for routes.js Express handlers | bffcfab |
| 1 GREEN | feat | implement routes.js + index.js — Express server with cron and HTTP handlers | f2d497b |
| 2 | feat | add timelapse service to docker-compose — host network, /data bind-mounts, cron 00:30 Toronto | 1246de4 |
| 3a | fix | fix telemetry column name and ffmpeg output format | e8506bd |
| 3b | docs | add smoke log for 2026-04-26 composition — 287 frames, 11.58s mp4 | 16b5853 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Express 5 uses `app.router` not `app._router` for stack inspection**
- **Found during:** Task 1 GREEN (routes test run)
- **Issue:** Plan's test template used `app._router.stack` (Express 4 pattern). Express 5 (installed: 5.2.1) exposes `app.router` instead; `app._router` is `undefined` until the first request triggers lazy init.
- **Fix:** Added `findRoute(app, path)` helper in routes.test.js that uses `app.router.stack`.
- **Files modified:** `src/mission-control/timelapse/test/routes.test.js`
- **Commit:** f2d497b

**2. [Rule 1 - Bug] `fetchRhForDay` queried `captured_at` but telemetry table uses `time` column**
- **Found during:** Task 3 smoke (first composeDay run, error: "column captured_at does not exist")
- **Issue:** `db.js` written assuming `telemetry.captured_at` matching `snapshots.captured_at` convention. The actual `telemetry` schema uses `time` as the timestamp column.
- **Fix:** Changed query to `SELECT time AS captured_at, value FROM telemetry WHERE ... AND time >= $1`. Alias preserves the `captured_at` name for `nearestRh` and `composer.js` callers without changing their code.
- **Files modified:** `src/mission-control/timelapse/src/db.js`
- **Commit:** e8506bd

**3. [Rule 1 - Bug] ffmpeg cannot determine output format from `.mp4.tmp` extension**
- **Found during:** Task 3 smoke (second composeDay run after fix 2, error: "Unable to choose an output format for '...mp4.tmp'")
- **Issue:** ffmpeg uses file extension for format detection. The atomic rename pattern writes to `outputPath + '.tmp'` (e.g. `2026-04-26.mp4.tmp`) — ffmpeg cannot infer `mp4` from `.tmp`.
- **Fix:** Added `-f mp4` flag before the output path in `buildArgs`. ffmpeg now uses explicit format flag regardless of extension. Updated `ffmpeg.test.js` exact arg assertion accordingly.
- **Files modified:** `src/mission-control/timelapse/src/ffmpeg.js`, `src/mission-control/timelapse/test/ffmpeg.test.js`
- **Commit:** e8506bd

### Not a deviation: yuvj420p vs yuv420p

ffprobe reports `yuvj420p` (JPEG full-range 4:2:0) rather than `yuv420p` (limited-range). Both are h264-compatible; the difference is the color range flag set by the JPEG encoder. The `-pix_fmt yuv420p` ffmpeg arg constrains the chroma subsampling but the JPEG input source sets full-range metadata. This is cosmetic — the clip plays correctly in all tested players.

## Known Stubs

None — all endpoints are wired end-to-end. The `last_nightly_at` field in `/health` will be `null` until the cron fires at 00:30 Toronto (expected behavior, not a stub).

## Threat Flags

None — no new trust boundaries beyond those documented in the plan's threat model (T-23-T1, T-23-T2 mitigated by validateQuery; T-23-I1 mitigated by host networking behind pfSense+Tailscale).

---

*Phase: 23-time-lapse-composition-ffmpeg*
*Completed: 2026-04-27*
*Awaiting: Task 4 farmer checkpoint (visual mp4 review)*
