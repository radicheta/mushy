---
phase: 23-time-lapse-composition-ffmpeg
plan: 01
subsystem: infra
tags: [timelapse, ffmpeg, jimp, node, jest, timescale, docker]

requires:
  - phase: 22-burn-in-sidecar
    provides: burn_bar.js jimp v1 pattern (overlay, loadFont, img.print, getBuffer)

provides:
  - mushy-timelapse Node.js package scaffold (Dockerfile, package.json, jest config, lockfile)
  - overlay.js: burnOverlay(buffer, {timestamp, rh}) -> JPEG Buffer; fmtRh null-safe formatter
  - db.js: initDb, insertTimelapse, lookupTimelapse, fetchRhForDay, nearestRh, RH_TOLERANCE_MS
  - config.js: load(env) fail-fast typed config object

affects:
  - 23-02 (composer.js imports overlay.js and db.js)
  - 23-03 (index.js imports config.js and db.js)

tech-stack:
  added:
    - jimp@1.6.1 (per-frame JPEG overlay)
    - express@5.2.1 (HTTP server, plan 03)
    - node-cron@4.2.1 (nightly schedule, plan 03)
    - pg@8.20.0 (Timescale queries)
    - jest@29.7.0 (test runner)
  patterns:
    - "--experimental-vm-modules required for jimp v1 in Jest (ESM dynamic import internals)"
    - "Pool-injected db functions (testable without live Timescale)"
    - "fmtRh null/undefined/NaN -> null; omit segment (gap over noise, not RH NaN%)"
    - "nearestRh breaks early when sorted-ASC delta starts growing"

key-files:
  created:
    - src/mission-control/timelapse/Dockerfile
    - src/mission-control/timelapse/package.json
    - src/mission-control/timelapse/package-lock.json
    - src/mission-control/timelapse/jest.config.js
    - src/mission-control/timelapse/.dockerignore
    - src/mission-control/timelapse/src/overlay.js
    - src/mission-control/timelapse/src/db.js
    - src/mission-control/timelapse/src/config.js
    - src/mission-control/timelapse/test/overlay.test.js
    - src/mission-control/timelapse/test/db.test.js
    - src/mission-control/timelapse/test/config.test.js
  modified: []

key-decisions:
  - "node --experimental-vm-modules required for jest + jimp v1 — mirrors bridge test script exactly"
  - "fmtRh returns null (not empty string) so burnOverlay can omit RH segment entirely — gap over noise"
  - "fetchRhForDay queries topic='fc.humidity' (dot notation, NOT 'fc1/humidity') per RESEARCH.md Pitfall 1"
  - "nearestRh exported as pure function; RH_TOLERANCE_MS exported constant for downstream reuse"
  - "config.js load(env) accepts env arg for testability; process.exit(1) on missing TIMESCALE_PASSWORD"

requirements-completed: [D-01, D-06, D-08, D-10, D-11]

duration: 5m
completed: 2026-04-27
---

# Phase 23 Plan 01: Timelapse Package Scaffold Summary

**mushy-timelapse Node.js package scaffolded with docker build verified, jimp overlay module, Timescale db helpers, and env config — 20 jest tests green**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-27T00:03:03Z
- **Completed:** 2026-04-27T00:08:17Z
- **Tasks:** 3
- **Files modified:** 11 created

## Accomplishments

- New `src/mission-control/timelapse/` package builds as `node:20-alpine + ffmpeg + font-dejavu` Docker image (verified exit 0)
- `overlay.js` exports `burnOverlay` (jimp v1 JPEG buffer round-trip, timestamp top-left + RH top-right, null RH omitted) and `fmtRh` null-safe formatter
- `db.js` exports `initDb`, `insertTimelapse`, `lookupTimelapse`, `fetchRhForDay` (using `fc.humidity` topic), `nearestRh` with 30-min tolerance
- `config.js` fail-fast on missing `TIMESCALE_PASSWORD`; typed defaults matching CONTEXT.md
- 20 unit tests across 3 suites, all green

## Task Commits

Each task was committed atomically:

1. **Task 1: Scaffold package, Dockerfile, jest config** — `7c15394` (chore)
2. **Task 2: overlay.js RED** — `4574ccc` (test)
3. **Task 2: overlay.js GREEN** — `97be517` (feat)
4. **Task 3: db.js + config.js RED** — `97b46ed` (test)
5. **Task 3: db.js + config.js GREEN** — `e3be207` (feat)

_TDD tasks have separate RED (test) and GREEN (feat) commits._

## Files Created/Modified

- `src/mission-control/timelapse/Dockerfile` — node:20-alpine + apk add ffmpeg font-dejavu
- `src/mission-control/timelapse/package.json` — mushy-timelapse; express, jimp, node-cron, pg deps; --experimental-vm-modules test script
- `src/mission-control/timelapse/package-lock.json` — dependency lockfile
- `src/mission-control/timelapse/jest.config.js` — verbatim copy of bridge jest config
- `src/mission-control/timelapse/.dockerignore` — excludes node_modules, test, .git
- `src/mission-control/timelapse/src/overlay.js` — burnOverlay + fmtRh
- `src/mission-control/timelapse/src/db.js` — timelapses table CRUD + RH lookup
- `src/mission-control/timelapse/src/config.js` — env loader with fail-fast
- `src/mission-control/timelapse/test/overlay.test.js` — 9 tests
- `src/mission-control/timelapse/test/db.test.js` — 8 tests
- `src/mission-control/timelapse/test/config.test.js` — 3 tests

## Decisions Made

- `--experimental-vm-modules` added to test script — jimp v1 uses dynamic imports internally; Jest 29 requires this flag to avoid "A dynamic import callback was invoked without --experimental-vm-modules" error. Bridge already uses this exact pattern.
- `fmtRh` returns `null` (not a placeholder string) so the caller can distinguish "no data" from "zero RH" and omit the RH segment cleanly (gap over noise principle).
- `fetchRhForDay` uses `fc.humidity` (Timescale dot-notation) not `fc1/humidity` (ROS topic) — RESEARCH.md Pitfall 1 explicitly corrects CONTEXT.md D-11.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added --experimental-vm-modules to npm test script**
- **Found during:** Task 2 (overlay.js GREEN implementation)
- **Issue:** Jest 29 + jimp v1.6.1 fails with "A dynamic import callback was invoked without --experimental-vm-modules" — jimp v1 ESM internals trigger dynamic imports that Jest's default CommonJS runner can't handle
- **Fix:** Changed `"test": "jest"` to `"test": "node --experimental-vm-modules node_modules/.bin/jest"` in package.json — mirrors the bridge's exact test script which already has this pattern
- **Files modified:** `src/mission-control/timelapse/package.json`
- **Verification:** All 9 overlay tests pass; all 20 tests pass in full suite
- **Committed in:** `97be517` (Task 2 feat commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug)
**Impact on plan:** Required for any test involving jimp. No scope creep — bridge already used this pattern, plan just didn't carry it forward to the test script spec.

## Issues Encountered

None beyond the --experimental-vm-modules deviation documented above.

## User Setup Required

None — no external service configuration required. The package is a library scaffold; the docker-compose wiring lands in plan 03.

## Next Phase Readiness

- Plan 02 (composer.js) can import `overlay.js` and `db.js` directly — both are import-ready with stable APIs
- Plan 03 (index.js + cron + HTTP server) can import `config.js` and `db.js`
- Docker image builds clean — plan 03 adds compose stanza to wire it into the stack

## Known Stubs

None — this plan delivers pure utility modules (no HTTP handlers, no cron, no ffmpeg invocation). No stub patterns found.

## Threat Flags

None — no new network endpoints, auth paths, or trust boundaries introduced in this plan.

---
*Phase: 23-time-lapse-composition-ffmpeg*
*Completed: 2026-04-27*
