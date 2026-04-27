---
phase: 23-time-lapse-composition-ffmpeg
verified: 2026-04-27T14:00:00Z
status: human_needed
score: 10/11 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Confirm nightly cron fires correctly at 00:30 America/Toronto on a real calendar day"
    expected: "Container logs show '[cron] firing for YYYY-MM-DD' at 00:30 Toronto time; /health last_nightly_at updates; mp4 for previous day created at /data/timelapse/fc1/YYYY-MM-DD.mp4"
    why_human: "Time-based trigger — cannot verify in <10s without waiting for the next 00:30 Toronto fire. last_nightly_at is currently null (container started 2026-04-27, cron not yet fired)."
  - test: "Visual overlay confirmation — timestamp and RH text are readable in the mp4"
    expected: "Top-left shows timestamp like '2026-04-26 14:30', top-right shows 'RH XX.X%' on frames where Timescale had RH data within 30 min"
    why_human: "Requires playing /data/timelapse/fc1/2026-04-26.mp4 — farmer gave 'looks good' approval 2026-04-27 (SMOKE-LOG.md section 8) but the smoke log notes visual confirmation was pending at time of write. The farmer's verdict is recorded in SMOKE-LOG.md and 23-03-SUMMARY.md as 'Approved — looks good'."
---

# Phase 23: Time-lapse Composition (ffmpeg) Verification Report

**Phase Goal:** Automated daily time-lapse composition from real snapshots with on-demand HTTP access.
**Verified:** 2026-04-27T14:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | timelapse Node.js package exists with Docker image (node:20-alpine + ffmpeg + font-dejavu) | VERIFIED | `Dockerfile` line 2: `RUN apk add --no-cache ffmpeg font-dejavu`; container `mushy-timelapse-1` Up ~1hr |
| 2 | burnOverlay produces a JPEG buffer with timestamp top-left and RH top-right (null omitted) | VERIFIED | `overlay.js` exports `burnOverlay`; 9 overlay tests green including null/undefined RH cases |
| 3 | initDb creates timelapses table with PRIMARY KEY (camera_id, date) | VERIFIED | `db.js` L13 contains `PRIMARY KEY (camera_id, date)`; Timescale table confirmed by SMOKE-LOG row query |
| 4 | lookupTimelapse and insertTimelapse round-trip (camera_id, date, file_path, frames_used, duration_sec) | VERIFIED | `db.js` exports both; smoke log shows registry row inserted: `(fc1, 2026-04-26, 287, 23.92s, /data/timelapse/fc1/2026-04-26.mp4)` |
| 5 | fetchRhForDay queries telemetry on topic='fc.humidity' (NOT 'fc1/humidity') | VERIFIED | `db.js` L43: `WHERE topic = 'fc.humidity'`; grep confirms no `fc1/humidity` in db.js |
| 6 | composeDay returns {skipped: true, reason: 'too_few_frames'} when < 3 frames | VERIFIED | `composer.js` L44-47; composer test 'skips when fewer than 3 frames (D-07)' passes |
| 7 | composeDay executes full pipeline: snapshot query → RH batch → per-frame burn → concat filelist → ffmpeg → atomic rename → timelapses row | VERIFIED | Full pipeline in `composer.js` L36-113; 7 composer tests green including happy-path, ENOENT-tolerance, filelist quoting, atomic rename |
| 8 | Express server listens on port 8888 with GET /health, GET /timelapse, GET /timelapse/status/:id | VERIFIED | `curl http://localhost:8888/health` returns `{"status":"ok",...}`; GET /timelapse returns 200 + file_path for existing entry; 400 for bad camera_id |
| 9 | docker-compose has timelapse service with build context, env, /data bind-mounts, depends_on timescale, restart unless-stopped | VERIFIED | docker-compose.yml timelapse stanza confirmed; `TIMESCALE_HOST=localhost`, `/data/snapshots:/data/snapshots:ro`, `/data/timelapse:/data/timelapse`, `restart: unless-stopped`; override has `network_mode: "host"` |
| 10 | First real mp4 composed end-to-end from fc1 snapshots; playable h264 file at /data/timelapse/fc1/YYYY-MM-DD.mp4 | VERIFIED | `/data/timelapse/fc1/2026-04-26.mp4` (936 KB); ffprobe confirms `Video: h264 (High)`, `640x480`, `12 fps`, `Duration: 00:00:11.58` |
| 11 | Nightly cron fires at 00:30 America/Toronto for previous TZ-local day | HUMAN NEEDED | `index.js` L70: `cron.schedule(config.cronSchedule, ..., { timezone: config.timezone })`; logs show `[cron] scheduled at "30 0 * * *" TZ=America/Toronto` — but `last_nightly_at` is null (cron not yet fired since container start) |

**Score:** 10/11 truths verified (11th requires waiting for cron fire)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/mission-control/timelapse/Dockerfile` | node:20-alpine + ffmpeg + font-dejavu | VERIFIED | `apk add --no-cache ffmpeg font-dejavu` present |
| `src/mission-control/timelapse/package.json` | express, jimp, node-cron, pg deps; jest dev | VERIFIED | All 4 runtime deps + jest present; name=mushy-timelapse |
| `src/mission-control/timelapse/src/overlay.js` | burnOverlay(buffer, {timestamp, rh}) -> Buffer | VERIFIED | Exports burnOverlay + fmtRh; 9 tests green |
| `src/mission-control/timelapse/src/db.js` | initDb, insertTimelapse, lookupTimelapse, fetchRhForDay, nearestRh | VERIFIED | All 5 functions exported; fc.humidity topic correct; time AS captured_at alias applied |
| `src/mission-control/timelapse/src/config.js` | load(env) fail-fast typed config | VERIFIED | process.exit(1) on missing TIMESCALE_PASSWORD; 3 config tests green |
| `src/mission-control/timelapse/src/ffmpeg.js` | buildArgs + runFfmpeg spawn wrapper | VERIFIED | Exports both; D-04 args + `-f mp4` fix; 4 tests green |
| `src/mission-control/timelapse/src/composer.js` | composeDay full pipeline | VERIFIED | Exports composeDay + SAFE_CAMERA_ID; 7 tests green |
| `src/mission-control/timelapse/src/routes.js` | registerRoutes + validateQuery | VERIFIED | Exports registerRoutes, validateQuery, singleDayUtc; 12 routes tests green |
| `src/mission-control/timelapse/src/index.js` | Server bootstrap: pool, initDb, cron, jobs, Express, listen | VERIFIED | All wired; logs confirmed: [db] Schema initialized, [cron] scheduled, [http] listening on 8888 |
| `docker-compose.yml` | timelapse service definition | VERIFIED | Service stanza present with correct env, volumes, depends_on |
| `docker-compose.override.yml` | timelapse override (host networking) | VERIFIED | `network_mode: "host"` present |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| composer.js | overlay.js | `require('./overlay')` | WIRED | L7: `burnOverlay: require('./overlay').burnOverlay` |
| composer.js | db.js | `require('./db')` | WIRED | L8: `db: require('./db')` |
| composer.js | ffmpeg.js | `require('./ffmpeg')` | WIRED | L6: `runFfmpeg: require('./ffmpeg').runFfmpeg` |
| index.js | composer.js | `composeDay(...)` | WIRED | L14 import; L35 cron call; L75 on-demand call |
| index.js | node-cron | `cron.schedule(...)` | WIRED | L70: `cron.schedule(config.cronSchedule, ..., { timezone: config.timezone })` |
| docker-compose.yml timelapse | /data/snapshots + /data/timelapse | volume bind-mounts | WIRED | `/data/snapshots:/data/snapshots:ro` and `/data/timelapse:/data/timelapse` confirmed |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| routes.js GET /timelapse | existing row from `lookupTimelapse` | db.lookupTimelapse → Timescale timelapses table | Yes — smoke log confirms live Timescale row returned 200+file_path | FLOWING |
| composer.js | frames from snapshots table | pool.query SELECT FROM snapshots | Yes — 287 rows returned in smoke run | FLOWING |
| composer.js | rhRows from fetchRhForDay | pool.query SELECT time AS captured_at FROM telemetry WHERE topic='fc.humidity' | Yes — RH data retrieved; nearestRh returned values for frames in smoke run | FLOWING |
| index.js cron | previous-day date string | `previousDayInTz(config.timezone)` via `Intl.DateTimeFormat` | Yes — deterministic; `last_nightly_at` null only because cron not yet fired | FLOWING (pending fire) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| GET /health returns ok | `curl http://localhost:8888/health` | `{"status":"ok","last_nightly_at":null,"last_nightly_status":null}` | PASS |
| GET /timelapse returns 200 for existing mp4 | `curl "http://localhost:8888/timelapse?from=2026-04-26T00:00:00Z&to=2026-04-26T23:59:59.999Z&camera_id=fc1"` | `{"file_path":"/data/timelapse/fc1/2026-04-26.mp4","duration_sec":"23.916666666666668"}` | PASS |
| GET /timelapse returns 400 for bad camera_id | `curl -w "%{http_code}" "...&camera_id=../etc"` | `400` | PASS |
| mp4 is playable h264 | `ffprobe /data/timelapse/fc1/2026-04-26.mp4` | `Video: h264 (High), yuvj420p, 640x480, 12 fps, Duration: 00:00:11.58` | PASS |
| timelapses table has registry row | `psql -tAc "SELECT COUNT(*) FROM timelapses"` | `1` | PASS |
| Full test suite | `cd src/mission-control/timelapse && npm test` | `44 passed, 6 suites, 0 failed` | PASS |
| Container running | `docker compose ps timelapse` | `mushy-timelapse-1 Up About an hour` | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| D-01 | 23-01, 23-03 | New timelapse container (Node.js + ffmpeg, docker-compose) | SATISFIED | Container live, Dockerfile with ffmpeg, docker-compose stanza present |
| D-02 | 23-03 | Nightly trigger at 00:30 local time via node-cron | PARTIALLY VERIFIED | Schedule registered at correct expr+TZ; fire not yet observed (human check pending) |
| D-03 | 23-03 | On-demand GET /timelapse endpoint with 200/202/400 responses | SATISFIED | All three response codes verified via spot-checks and unit tests |
| D-08 | 23-01, 23-02, 23-03 | Output path /data/timelapse/{camera_id}/YYYY-MM-DD.mp4 | SATISFIED | `/data/timelapse/fc1/2026-04-26.mp4` exists, confirmed by smoke |
| D-10 | 23-01, 23-02, 23-03 | timelapses table: (camera_id, date, file_path, frames_used, composed_at, duration_sec) | SATISFIED | Table schema correct; 1 live row with all columns populated |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/mission-control/timelapse/src/ffmpeg.js` | 15-16 | `-f mp4` added after `-pix_fmt yuv420p -r FPS` — not in original D-04 spec | Info | Intentional bug-fix (ffmpeg cannot infer format from `.mp4.tmp`); documented as deviation in 23-03-SUMMARY.md; tests updated to match; no functional issue |
| `src/mission-control/timelapse/src/db.js` | 43 | `time AS captured_at` alias — original plan used `captured_at` column name | Info | Intentional schema correction (telemetry uses `time` not `captured_at`); documented as deviation; callers unaffected via alias |

No blocker anti-patterns found. Both items are documented auto-fixed bugs.

### Human Verification Required

#### 1. Nightly Cron Fire

**Test:** Wait until 00:30 America/Toronto (UTC-04:00 in summer, so 04:30 UTC). Then run:
```bash
docker compose logs timelapse --since 24h | grep -E "cron.*firing|Schema|scheduled"
curl http://localhost:8888/health
```
**Expected:** Logs show `[cron] firing for YYYY-MM-DD`; `/health` response includes non-null `last_nightly_at` and `last_nightly_status: "ok"` (or `skipped: too_few_frames` if snapshots < 3 for that day).
**Why human:** Time-based trigger. Cannot verify in <10s. `last_nightly_at` is currently null — container started on 2026-04-27 and the cron has not fired yet in this session.

#### 2. Visual Overlay Confirmation

**Test:** Play `/data/timelapse/fc1/2026-04-26.mp4` (936 KB, 287 frames, 11.58s).
```bash
scp elder-plops:/data/timelapse/fc1/2026-04-26.mp4 ~/Desktop/
xdg-open ~/Desktop/2026-04-26.mp4
```
**Expected:** Top-left of frames shows timestamp like `2026-04-26 HH:MM`; top-right shows `RH XX.X%` on most frames; frames in chronological order; no visual artifacts.
**Why human:** Requires playing video. The farmer gave "looks good" approval on 2026-04-27 per SMOKE-LOG.md and 23-03-SUMMARY.md — this item is substantially satisfied but is formally a human-verification item per verifier rules since it requires visual inspection. If farmer approval is considered sufficient evidence, this can be waived by the operator.

### Known Open Items (Not Gaps)

The farmer noted **CO2 overlay missing from burn-in** during review on 2026-04-27. This is tracked as an open item in 23-03-SUMMARY.md, not a phase gate. The clip is approved and the phase goal (automated daily time-lapse with on-demand HTTP access) is achieved. CO2 overlay is deferred to a follow-up plan (23-04 or Phase 24 scope).

### Gaps Summary

No blocking gaps. All code artifacts are substantive, wired, and data-flowing. The 44-test suite is green. The container is live on elder-plops with the first real mp4 composed and farmer-approved.

The `human_needed` status comes from:
1. Nightly cron has not yet fired since container start (verifiable at 00:30 Toronto)
2. Farmer overlay visual approval is documented in SMOKE-LOG.md but constitutes a human verification item under verifier rules

The phase goal — *automated daily time-lapse composition from real snapshots with on-demand HTTP access* — is substantively achieved and live in production.

---

_Verified: 2026-04-27T14:00:00Z_
_Verifier: Claude (gsd-verifier)_
