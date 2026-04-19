---
phase: 21-camera-history-continuous-persistence
plan: 03
subsystem: bridge-retention-history
tags: [bridge, retention, camera, history, endpoint, jest]

requires:
  - phase: 21-camera-history-continuous-persistence
    plan: 02
    provides: snapshots hypertable + source-tagged INSERTs on every 5-min tick
provides:
  - retention.js — pure clampRetentionDays, shouldPrune, runPrune(pool, fs, now, ...) with ENOENT-as-success + 30-day grace
  - Daily setInterval prune tick + 60s one-shot startup tick wired into bridge startup block
  - history_validate.js — pure validateHistoryParams({from,to,camera_id}, CAMERA_ID, maxRangeMs)
  - GET /camera/history returning {camera_id, from, to, count, has_more, rows:[...]} ordered captured_at ASC, 5000-row cap via LIMIT N+1
  - docker-compose.yml documents RETENTION_DAYS / RETENTION_GRACE_DAYS optional env
affects: [21-04, 22]

tech-stack:
  added: []
  patterns:
    - "Pure helper extraction — retention.js and history_validate.js have zero bridge-runtime deps so tests import them without touching rclnodejs/pg"
    - "LIMIT N+1 pagination detection — fetch cap+1, set has_more if length > cap, slice(0, cap)"
    - "ENOENT-as-success atomic prune — unlink first; if file already gone, still DELETE row; other errors leave both in place for next tick"
    - "Dual-guard DoS prevention — clampRetentionDays floor=30 + runPrune grace=30 (Pitfall 2 belt-and-suspenders)"

key-files:
  created:
    - src/mission-control/bridge/src/retention.js
    - src/mission-control/bridge/src/history_validate.js
    - src/mission-control/bridge/test/retention.test.js
    - src/mission-control/bridge/test/history.test.js
  modified:
    - src/mission-control/bridge/src/index.js
    - docker-compose.yml

key-decisions:
  - "Retention job runs in-process via setInterval (D-01 no-new-container) rather than a host cron or sidecar — composes with the existing /data volume mount and always-on bridge lifecycle"
  - "Per-row unlink+DELETE loop (not bulk) — narrows crash window to a single row and makes the retry path idempotent via ENOENT-as-success semantics"
  - "ISO string for captured_at in /camera/history response (not ms epoch) — /farmer/summary uses ms, /history/:topic uses ms; /camera/history is new shape and TIMESTAMPTZ→JS Date→toISOString() is the natural serialization for Phase 22's scrubber labels"
  - "Static equality check of camera_id against env CAMERA_ID — multi-chamber allowlist deferred to Phase 999.6; today fc1 is the only valid value"
  - "60s startup pruner shot — lets initDb settle before the first tick; surfaces the '[retention] skip — oldest snapshot <N> days (grace 30)' line in logs as a liveness signal on fresh installs"

patterns-established:
  - "validateHistoryParams is importable as a pure function — future endpoints needing from/to/camera_id bounds can reuse it without cloning the parseInt/range/allowlist trio"
  - "retention.runPrune dependency-injects pool/fs/now — makes the EACCES, ENOENT, and grace paths testable without filesystem fixtures or a real Postgres"

requirements-completed: [D-04, D-06a]

duration: ~112s
completed: 2026-04-19
---

# Phase 21 Plan 03: Retention job + /camera/history endpoint Summary

**Bridge now prunes snapshots >365 days old daily (with a 30-day grace) and exposes the D-06a read-only `GET /camera/history` endpoint that Phase 22's scrubber will consume; all logic extracted into pure helpers with 23 new jest cases.**

## Performance

- **Duration:** ~112 seconds (~1 min 52 s)
- **Started:** 2026-04-19T15:23:27Z
- **Completed:** 2026-04-19T15:25:19Z
- **Tasks:** 2
- **Files:** 6 (4 created + 2 modified)

## Accomplishments

- `retention.js` ships three pure functions:
  - `clampRetentionDays(n, floor=30)` — parses input, forces >=30 (Pitfall 2 guard).
  - `shouldPrune({oldestDays, graceDays})` — returns false on null/undefined/below-grace.
  - `runPrune({pool, fs, now, retentionDays, graceDays, batchLimit=10000, log})` — queries `MIN(captured_at)` for grace check, then selects expired paths with `LIMIT`, and per-row unlinks (ENOENT→still DELETE; EACCES→skip, row stays for retry) then DELETEs.
- Bridge startup block now:
  - Reads `RETENTION_DAYS` / `RETENTION_GRACE_DAYS` env (via `retention.clampRetentionDays`).
  - After the snapshot `setInterval`, schedules `setInterval(runPrune, 24h)` + `setTimeout(runPrune, 60s)` one-shot — both guarded by `dbReady` check and promise `.catch` so retention failures don't crash the bridge.
  - Logs `[retention] scheduled — retain N days, grace M days` at startup.
- `history_validate.js` provides `validateHistoryParams(query, allowedCameraId, maxRangeMs)` returning `{ok, status?, error?, parsed?}` — rejects non-numeric from/to, to<from, range>30d, unknown camera_id.
- `GET /camera/history` route (inserted before `/camera/mjpeg`): runs validateHistoryParams → 503 on !dbReady → parameterized SELECT with `LIMIT HISTORY_MAX_ROWS + 1` → slices to 5000 and sets `has_more: true` when `rows.length > 5000` → maps each row to `{captured_at: ISO string, camera_id, file_path, bytes, source, fps}`.
- `docker-compose.yml` bridge env block adds `RETENTION_DAYS=${RETENTION_DAYS:-365}` and `RETENTION_GRACE_DAYS=${RETENTION_GRACE_DAYS:-30}`.
- `test/retention.test.js` — 14 cases: 5 clamp, 5 shouldPrune, 4 runPrune (grace-skip, happy-path 3-row, ENOENT, EACCES). Uses dependency-injected fake pool + fake fs; no real DB/fs required.
- `test/history.test.js` — 9 cases: non-numeric from, non-numeric to, to<from, range>30d, unknown camera_id, default camera_id, explicit fc1, 30d boundary, from===to boundary.

## Task Commits

1. **Task 1: Retention helpers + daily setInterval + unit tests** — `6d06742` (feat)
2. **Task 2: GET /camera/history endpoint + validation helper + tests** — `6b4b94e` (feat)

## Files Created/Modified

- `src/mission-control/bridge/src/retention.js` (new) — 3 pure fns + constants; CommonJS export; no bridge-runtime imports.
- `src/mission-control/bridge/src/history_validate.js` (new) — `validateHistoryParams` + CommonJS export.
- `src/mission-control/bridge/test/retention.test.js` (new) — 14 jest cases via fake pool + fake fs.
- `src/mission-control/bridge/test/history.test.js` (new) — 9 jest cases.
- `src/mission-control/bridge/src/index.js` — +require('./retention'), +{validateHistoryParams}, +RETENTION_DAYS/RETENTION_GRACE_DAYS/PRUNE_INTERVAL_MS/HISTORY_MAX_ROWS/HISTORY_MAX_RANGE_MS constants, +GET /camera/history route, +setInterval/setTimeout wiring in startup block after saveSnapshot timer.
- `docker-compose.yml` — +2 env lines on the bridge service.

## Decisions Made

- **Pure helpers over inline logic:** Both retention and history validation were lifted out of index.js so they can be tested without bringing up `rclnodejs.init()` or a live pg pool. Same pattern Plan 02 established with `snapshot_helpers.js`.
- **LIMIT N+1 for has_more:** The alternative (COUNT(*) OVER() window function) needs a second sort pass; N+1 slices at array-length-compare cost. Matches RESEARCH.md Pattern 5 verbatim.
- **60s startup delay on the one-shot:** Gives `initDb` room to idempotently re-create the `snapshots` hypertable on cold container restarts. If `dbReady` is still false after 60s, the tick is a no-op.
- **No `catch` swallowing in runPrune's inner DELETE:** If the SELECT→unlink sequence succeeded but DELETE throws, the exception propagates up through the `setInterval`'s `.catch` logger. Next run will see the file gone (ENOENT) and retry the DELETE. Idempotent by construction.

## Deviations from Plan

None. Plan executed exactly as written — every code snippet in `<action>` blocks matches what landed. All 23 new jest cases are verbatim from the plan. docker-compose.yml received the two env lines specified.

## Threat Flags

None. The plan's `<threat_model>` enumerated T-21-08..T-21-14 covering every new surface:

- T-21-08 (SQL injection via camera_id): mitigated by allowlist equality in `validateHistoryParams` + parameterized `$1` query.
- T-21-09 (SQL injection via from/to): mitigated by `parseInt` + `Number.isFinite` gate + `$2, $3` with Date wrapping.
- T-21-10 (Unbounded range DoS): 30-day range cap + 5000 row cap + LIMIT N+1.
- T-21-12 (Retention wrong-file unlink): `unlink` paths sourced only from `SELECT WHERE captured_at < cutoff` — never client/env.
- T-21-13 (Retention nukes half-populated install): clampRetentionDays floor=30 + runPrune graceDays=30 double-guard. Covered by `skips under grace` test.
- T-21-14 (Retention tick hangs bridge): `LIMIT 10000` per run + promise `.catch` on the `setInterval` body.

## Issues Encountered

- **Read-before-Edit hook fired 4× on already-read files.** index.js and docker-compose.yml were both read in the initial files_to_read batch, but the hook runs per-call and doesn't see historical reads as "already read" for subsequent Edit calls within the same message. Edits succeeded regardless (hook is a reminder, not a gate). Noting this so a future read-only session doesn't waste context re-reading.
- No actual code/test issues. Jest suite went 14/14 (retention) and 9/9 (history) on first run.

## Deferred Issues

- **Live-stack verification** (`docker compose up -d --build bridge` + `docker compose logs bridge | grep '[retention] scheduled'` + seed-row curl against `/camera/history`) is deferred to the orchestrator / Plan 04 verify step. All static checks (node --check, jest, acceptance greps) pass locally.
- **Empty-directory cleanup after prune unlinks the last file in a YYYY-MM-DD bucket.** Not load-bearing (Phase 22 queries the DB index, not the filesystem). Deferred per CONTEXT Open Question 4.
- **Bulk DELETE path for large backfilled installs.** Current per-row loop handles Phase 21 volumes (~288 rows/day) trivially. If a future ML phase pushes 10×+ row counts, batch deletes are a straightforward refactor — `DELETE FROM snapshots WHERE file_path = ANY($1)` after all unlinks succeed.

## User Setup Required

None inside the plan. The standard post-plan deploy (`docker compose up -d --build bridge` from repo root) will surface the `[retention] scheduled` log line and make `/camera/history` reachable on port 8081. Owned by the orchestrator/verifier.

## Next Phase Readiness

- Plan 04 (`21-04`) can add `snapshots_last_24h` and `oldest_snapshot_at` to `/health` — the `snapshots` table is populated by the Plan 02 persister and pruned by this plan's retention tick.
- Phase 22 (scrubber UI) can now hit `GET /camera/history?from=...&to=...&camera_id=fc1` and receive the D-06a shape (`count`, `has_more`, `rows[].captured_at` ISO string).
- `scripts/verify/phase-21-smoke.sh` (Plan 01) can now assert a live `/camera/history` response shape instead of the "not yet available" placeholder branch.

## Self-Check: PASSED

- FOUND: src/mission-control/bridge/src/retention.js
- FOUND: src/mission-control/bridge/src/history_validate.js
- FOUND: src/mission-control/bridge/test/retention.test.js
- FOUND: src/mission-control/bridge/test/history.test.js
- FOUND: modifications to src/mission-control/bridge/src/index.js (require retention, require history_validate, RETENTION_DAYS const, HISTORY_MAX_ROWS = 5000, app.get('/camera/history', ..., setInterval runPrune, setTimeout runPrune)
- FOUND: docker-compose.yml RETENTION_DAYS + RETENTION_GRACE_DAYS env lines
- FOUND: commit 6d06742 (Task 1)
- FOUND: commit 6b4b94e (Task 2)
- VERIFIED: `node --check src/mission-control/bridge/src/index.js` exits 0
- VERIFIED: `cd src/mission-control/bridge && npx jest` — 31/31 passed (14 retention + 9 history + 8 snapshot carry-over from Plan 02) in 0.265s

---
*Phase: 21-camera-history-continuous-persistence*
*Completed: 2026-04-19*
