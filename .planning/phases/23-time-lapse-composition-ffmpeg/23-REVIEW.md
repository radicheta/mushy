---
phase: 23-time-lapse-composition-ffmpeg
reviewed: 2026-04-27T00:00:00Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - src/mission-control/timelapse/src/overlay.js
  - src/mission-control/timelapse/src/db.js
  - src/mission-control/timelapse/src/config.js
  - src/mission-control/timelapse/src/ffmpeg.js
  - src/mission-control/timelapse/src/composer.js
  - src/mission-control/timelapse/src/routes.js
  - src/mission-control/timelapse/src/index.js
  - src/mission-control/timelapse/test/overlay.test.js
  - src/mission-control/timelapse/test/db.test.js
  - src/mission-control/timelapse/test/config.test.js
  - src/mission-control/timelapse/test/ffmpeg.test.js
  - src/mission-control/timelapse/test/composer.test.js
  - src/mission-control/timelapse/test/routes.test.js
  - src/mission-control/timelapse/Dockerfile
  - src/mission-control/timelapse/package.json
  - src/mission-control/timelapse/jest.config.js
  - docker-compose.yml
  - docker-compose.override.yml
findings:
  critical: 0
  warning: 4
  info: 3
  total: 7
status: issues_found
---

# Phase 23: Code Review Report

**Reviewed:** 2026-04-27
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

The Phase 23 timelapse composition service is well-structured. The pipeline correctly separates concerns (overlay burn, ffmpeg spawn, DB registry, HTTP routes), uses dependency injection throughout for testability, and the test suite covers the main happy path and key failure modes. The atomic-rename + workdir cleanup pattern in `composer.js` is solid.

Four warnings and three info items found. No critical issues (no injection vulnerabilities, no hardcoded secrets, no auth bypasses). The most consequential finding is a filelist injection vector via single-quoted frame paths (#WR-01) and an unbounded in-memory job store (#WR-02). The remaining warnings are correctness-adjacent edge cases.

---

## Warnings

### WR-01: Frame path with single-quote breaks ffmpeg filelist syntax

**File:** `src/mission-control/timelapse/src/composer.js:83`
**Issue:** Each burned frame path is written into `filelist.txt` as `file '<path>'`. The `cameraId` and `date` are validated (no special chars), but `workRoot` and `timelapseDir` are injected by the caller from config/opts and are never sanitised. More concretely, `path.join(workRoot, cameraId, date)` produces the workDir, and individual frame filenames use a zero-padded integer (`frame_0001.jpg`) so no injection there. However the risk surface is `workRoot` itself: if a path component ever contains a single quote (e.g. a future config value or a test override), the resulting `file '/tmp/my's_dir/...'` is syntactically broken ffmpeg input and will cause a confusing parse failure rather than a clear error. The guard currently applied to `cameraId` and `date` is not applied to `workRoot` or `timelapseDir`.

**Fix:** Either validate that `workRoot` and `timelapseDir` contain no single-quote characters at the top of `composeDay`, or escape single-quotes inside `filelistLines.push` by replacing `'` with `'\''`:
```javascript
filelistLines.push(`file '${burnedPath.replace(/'/g, "'\\''")}'`);
```

---

### WR-02: In-memory `jobs` Map grows without bound

**File:** `src/mission-control/timelapse/src/index.js:25`
**Issue:** `jobs` is a plain `Map` that entries are added to in `/timelapse` (`routes.js:58`) but never removed. Every `GET /timelapse` request that triggers a new composition adds a UUID entry. After extended uptime (nightly crons + manual re-triggers over weeks) this is a minor memory leak. More practically, `GET /timelapse/status/:id` will return stale completed jobs indefinitely. There is no TTL, eviction, or size cap.

**Fix:** A simple bounded eviction is sufficient for this use case. After a job reaches a terminal state (`done` or `failed`), schedule its removal:
```javascript
// In runComposition, after updating job.status to 'done' or 'failed':
setTimeout(() => jobs.delete(jobId), 10 * 60 * 1000); // evict after 10 min
```

---

### WR-03: `fetchRhForDay` end-of-day bound excludes the last second

**File:** `src/mission-control/timelapse/src/db.js:47`
**Issue:** The query uses `time < $2` with `$2 = '${date}T23:59:59.999Z'`. The `<` (not `<=`) operator excludes exactly the value `23:59:59.999Z`. Any telemetry row timestamped at precisely that millisecond is silently dropped. This is an extremely unlikely scenario but the pattern is inconsistent with `composer.js` line 37-40 which uses `captured_at >= $2 AND captured_at < $3` with `$3 = '${date}T23:59:59.999Z'` (same trailing bound, `<` is consistent). The real risk is the snapshot query in `composer.js` shares the same bound format — if the two files diverge (one uses `<`, one `<=`) a late-day frame could have its RH match silently excluded while the frame is still composed. As-is both are `<` so they are at least consistent.

**Fix:** Use an exclusive-upper-bound pattern that is unambiguous — either `< '${date}T24:00:00.000Z'` (ISO 8601 end of day) or equivalently add one day:
```javascript
const nextDate = new Date(new Date(`${date}T00:00:00Z`).getTime() + 86400000).toISOString().slice(0, 10);
// then: AND time >= $1 AND time < $2   with $2 = `${nextDate}T00:00:00Z`
```
This eliminates the 23:59:59.999 edge and makes the intent unambiguous.

---

### WR-04: `runComposition` in `index.js` ignores multi-day ranges

**File:** `src/mission-control/timelapse/src/index.js:34`
**Issue:** When `GET /timelapse` receives a multi-day range (validated as up to 7 days by `routes.js`), `runComposition` silently reduces it to `new Date(from).toISOString().slice(0, 10)` — the start date only. The caller receives a `202` and a `job_id` with no indication that the `to` parameter was ignored. This silent truncation could confuse a future caller who passes a 3-day range expecting a multi-day stitch. The comment says "Multi-day stitch is future work" but the API contract does not surface this limitation.

**Fix:** Either reject multi-day requests at the route level with a clear 400 error (preferred until the feature is built), or at minimum log a warning when `to` spans more than one day:
```javascript
// In routes.js, after validateQuery succeeds:
if (!singleDayUtc(v.fromD, v.toD)) {
    return res.status(400).json({ error: 'Multi-day timelapse not yet supported; request a single calendar day' });
}
```

---

## Info

### IN-01: `require('crypto')` inside request handler — move to module scope

**File:** `src/mission-control/timelapse/src/routes.js:56`
**Issue:** `const crypto = require('crypto')` is called on every `GET /timelapse` request that enqueues a job. Node.js caches `require` results so there is no real cost, but the pattern is unusual and will confuse readers who expect module-level imports.

**Fix:** Move to the top of `routes.js` alongside other requires:
```javascript
const crypto = require('crypto');
```

---

### IN-02: Dockerfile falls back to `npm install` if `package-lock.json` absent

**File:** `src/mission-control/timelapse/Dockerfile:5`
**Issue:** `RUN npm ci --omit=dev || npm install --omit=dev` silently falls back to `npm install` if `npm ci` fails (e.g., missing lockfile). `npm install` does not enforce lockfile integrity — it may resolve different transitive dependency versions and will generate a new `package-lock.json` inside the container that is never committed. The intent is likely "use `npm ci` for reproducible builds".

**Fix:** Drop the fallback and ensure `package-lock.json` is always committed and present in the build context:
```dockerfile
RUN npm ci --omit=dev
```
If `package-lock.json` is currently absent from the repo, commit it first.

---

### IN-03: `nearestRh` early-exit assumes strictly sorted input

**File:** `src/mission-control/timelapse/src/db.js:64`
**Issue:** The comment "sorted ASC — only grows" justifies the `else if (delta > bestDelta) break` early exit. The `fetchRhForDay` query does `ORDER BY time ASC` so this is correct. However the `nearestRh` function is a pure utility that accepts any `rhRows` array — nothing in its signature or docstring documents this sort precondition. A future caller who passes unsorted rows would silently get a wrong (possibly null) result.

**Fix:** Add a precondition comment to the function signature:
```javascript
// rhRows MUST be sorted ascending by captured_at — relies on this for early-exit.
function nearestRh(rhRows, frameTsMs, toleranceMs = RH_TOLERANCE_MS) {
```
No code change required; documentation only.

---

_Reviewed: 2026-04-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
