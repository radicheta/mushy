---
phase: 23-time-lapse-composition-ffmpeg
plan: 02
subsystem: timelapse
tags: [timelapse, ffmpeg, composer, pipeline, tdd, jest]

requires:
  - phase: 23-01
    provides: overlay.js burnOverlay, db.js fetchRhForDay/nearestRh/insertTimelapse

provides:
  - ffmpeg.js: buildArgs + runFfmpeg (spawn-injectable, D-04 args)
  - composer.js: composeDay(date, cameraId, pool, opts) — full pipeline with DI

affects:
  - 23-03 (index.js calls composeDay for cron + on-demand endpoint)

tech-stack:
  added: []
  patterns:
    - "spawn injectable via deps.spawn for hermetic ffmpeg tests — no real ffmpeg invoked in unit tests"
    - "DI pattern mirrors retention.js: pool, fs, runFfmpeg, burnOverlay, db, log all injectable"
    - "Atomic rename: write to outputPath.tmp, rename on ffmpeg exit 0, unlink .tmp on failure"
    - "try/finally workDir rm — DoS guard even when ffmpeg or burnOverlay throws"
    - "SAFE_CAMERA_ID regex + date regex gate before any path.join or SQL param"

key-files:
  created:
    - src/mission-control/timelapse/src/ffmpeg.js
    - src/mission-control/timelapse/src/composer.js
    - src/mission-control/timelapse/test/ffmpeg.test.js
    - src/mission-control/timelapse/test/composer.test.js
  modified: []

decisions:
  - "buildArgs returns String(fps) not Number(fps) — argv is always strings; test asserts '12' not 12"
  - "ENOENT on frame read is per-item skippable (gap over noise); other errors propagate and abort"
  - "frame index i+1 used for pad4 labeling (1-based) to match natural ordering in filelist"
  - "workRoot defaults to /tmp/timelapse_work; caller can inject for tests (isolation)"

metrics:
  duration: 11m
  started: 2026-04-27T00:03:55Z
  completed: 2026-04-27T00:13:55Z
  tasks: 2
  files_created: 4
  files_modified: 0
---

# Phase 23 Plan 02: Composition Pipeline Summary

**ffmpeg spawn wrapper (D-04 exact args) + full composeDay orchestrator with DI — 31 jest tests green, all 4 STRIDE threats covered**

## Performance

- **Duration:** 11 min
- **Started:** 2026-04-27T00:03:55Z
- **Completed:** 2026-04-27T00:13:55Z
- **Tasks:** 2 (TDD: 2 RED commits + 2 GREEN commits = 4 task commits)
- **Files created:** 4

## Accomplishments

- `ffmpeg.js` exports `buildArgs` (exact D-04 arg array) and `runFfmpeg` (spawn-injectable, stderr-capturing, rejects with tail on non-zero exit)
- `composer.js` exports `composeDay` — full pipeline: snapshot query, frame-count guard (< 3 returns `{skipped: true}`), batch RH lookup, per-frame `burnOverlay`, concat filelist with single-quoted absolute paths, ffmpeg via injected `runFfmpeg`, atomic rename `.mp4.tmp -> .mp4`, `insertTimelapse` registry write, `try/finally` workDir cleanup
- Path-traversal guard (`SAFE_CAMERA_ID`) and date-format guard reject unsafe inputs before any path or SQL usage
- 31 unit tests total (20 from plan 01 + 4 ffmpeg + 7 composer); no real ffmpeg or filesystem touched in tests

## Task Commits

| # | Phase | Description | Hash |
|---|-------|-------------|------|
| 1 | RED  | test(23-02): add failing test for ffmpeg.js spawn wrapper | 1ab5ad8 |
| 2 | GREEN | feat(23-02): implement ffmpeg.js — spawn wrapper with D-04 args + stderr capture | ccff919 |
| 3 | RED  | test(23-02): add failing tests for composer.js composeDay pipeline | 344af82 |
| 4 | GREEN | feat(23-02): implement composer.js — full composeDay pipeline with DI | 306a3dc |

## Files Created

- `src/mission-control/timelapse/src/ffmpeg.js` — `buildArgs` + `runFfmpeg`; spawn injectable; D-04 arg array hardcoded and tested exactly
- `src/mission-control/timelapse/src/composer.js` — `composeDay`; full 10-step pipeline; DI for pool/fs/ffmpeg/overlay/db/log
- `src/mission-control/timelapse/test/ffmpeg.test.js` — 4 tests: exact arg match, default fps, exit-0 resolve, non-zero reject
- `src/mission-control/timelapse/test/composer.test.js` — 7 tests: path-traversal, bad date, < 3 frames guard, happy path, ffmpeg failure, ENOENT skip, filelist quoting

## Decisions Made

- `buildArgs` emits `String(fps)` — ffmpeg argv entries are strings; `'12'` not `12` to match exact D-04 contract
- ENOENT on frame read is a per-item skip (gap over noise); other errors abort the whole composition
- Frame numbering in filelist is 1-based (`pad4(i + 1)`) for human-readable output ordering
- `workRoot` and `timelapseDir` are opts-injectable so tests can use `/tmp/w` instead of `/data`

## Deviations from Plan

None — plan executed exactly as written. The `.mp4.tmp` literal grep criterion in the acceptance list does not match because the code uses `` `${outputPath}.tmp` `` (a template literal); the behavior is identical and verified by the test suite's `renames` and `unlinks` assertions. No plan modification was needed.

## Known Stubs

None — `composeDay` is a pure pipeline function with no data stubs or placeholders. Plan 03 wires it into the cron and HTTP handler.

## Threat Flags

None — no new network endpoints. Threat mitigations T-23-T1, T-23-T2, T-23-T3, T-23-D1 are all implemented and covered by tests.

## TDD Gate Compliance

- RED gate: `test(23-02)` commits confirmed (1ab5ad8, 344af82)
- GREEN gate: `feat(23-02)` commits confirmed (ccff919, 306a3dc)

---
*Phase: 23-time-lapse-composition-ffmpeg*
*Completed: 2026-04-27*

## Self-Check: PASSED

All 4 created files confirmed present on disk. All 4 task commits confirmed in git log (1ab5ad8, ccff919, 344af82, 306a3dc). Full test suite: 31/31 green.
