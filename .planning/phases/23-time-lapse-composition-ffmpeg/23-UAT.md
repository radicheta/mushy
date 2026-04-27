---
status: partial
phase: 23-time-lapse-composition-ffmpeg
source: [23-01-SUMMARY.md, 23-02-SUMMARY.md, 23-03-SUMMARY.md]
started: 2026-04-27T17:00:00Z
updated: 2026-04-27T17:45:00Z
---

## Current Test

[testing complete — test 6 deferred to 2026-04-28 morning]

## Tests

### 1. Cold Start Smoke Test
expected: Container restarts and logs show [db] Schema initialized, [cron] scheduled, [http] listening on 8888
result: pass

### 2. GET /health
expected: 200 + {status:'ok', last_nightly_at: null (cron not yet fired)}
result: pass

### 3. GET /timelapse — existing day returns mp4
expected: 200 + {file_path, duration_sec} for 2026-04-26
result: pass

### 4. Security: bad camera_id rejected
expected: 400 for camera_id=../etc
result: pass

### 5. mp4 overlay quality
expected: |
  Play /data/timelapse/fc1/2026-04-26.mp4
  Timestamp visible top-left, RH top-right on most frames, chronological order, no artifacts.
  Note: CO2 missing by design — logged as follow-up.
result: pass

### 6. Nightly cron fire
expected: |
  Tomorrow morning: GET /health shows last_nightly_at non-null (~00:30 Toronto).
  docker compose logs timelapse | grep '[cron] firing' shows entry for 2026-04-27.
result: blocked
blocked_by: time-gated
reason: "Check 2026-04-28 morning after 00:30 America/Toronto"

## Summary

total: 6
passed: 5
issues: 0
pending: 0
skipped: 0
blocked: 1

## Gaps
