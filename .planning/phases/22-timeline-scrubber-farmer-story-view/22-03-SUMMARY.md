---
phase: 22-timeline-scrubber-farmer-story-view
plan: 03
subsystem: bridge
tags: [phase-22, bridge, route, camera-frame, tdd]
dependency_graph:
  requires:
    - SNAPSHOT_BURNT_DIR env + burn-in pipeline (plan 22-02)
    - snapshots hypertable + (camera_id, captured_at DESC) index (Phase 21)
    - SNAPSHOT_INTERVAL_MS env (Phase 21)
  provides:
    - GET /camera/frame?at=<iso>&camera_id=fc1[&raw=true] -> JPEG bytes
    - validateFrameParams pure module (reusable if a future route needs the same shape)
  affects:
    - src/mission-control/bridge/src/index.js (+1 route, +1 const, +1 import)
    - src/mission-control/bridge/src/frame_validate.js (new)
    - src/mission-control/bridge/test/frame_validate.test.js (new)
tech_stack:
  added: []
  patterns:
    - Closest-at-or-before SQL pattern (captured_at <= $2 AND captured_at >= $3, ORDER BY DESC LIMIT 1)
    - Path-prefix swap for burnt twin with startsWith defense-in-depth
    - Strict string match for boolean query flags (no truthy coercion)
    - X-Captured-At response header for honest time-labeling under tolerance window
key_files:
  created:
    - src/mission-control/bridge/src/frame_validate.js
    - src/mission-control/bridge/test/frame_validate.test.js
  modified:
    - src/mission-control/bridge/src/index.js
decisions:
  - "Test file location: test/ not src/ (jest.config.js testMatch is '**/test/**/*.test.js' — carried-forward deviation from plan 22-02)"
  - "FRAME_TOLERANCE_MS = 2 * SNAPSHOT_INTERVAL_MS baked as a top-level const rather than a per-request calc — single source of truth for the 'gap over noise' window"
  - "Burnt missing -> 404 (never silent fallback to raw) — preserves D-05 operator-intent contract"
  - "raw query flag is strict-equal 'true' — '1', 'yes', 'TRUE' all stay burnt (tested)"
  - "No integration/supertest test for the route — deferred to plan 22-04 curl-based live verification (param parsing unit-tested; route body is thin DB + fs.readFile wrapper)"
metrics:
  duration_min: ~10
  tasks_completed: 2
  files_created: 2
  files_modified: 1
  commits: 3
  completed_date: 2026-04-19
---

# Phase 22 Plan 03: GET /camera/frame route

One-liner: bridge now serves a single JPEG by timestamp — burnt-by-default with a `?raw=true` escape hatch — completing the D-02 data surface farmOS needs for the client-side scrubber.

## What shipped

### Task 1 — frame_validate module (commits 8e993ad RED → b73045e GREEN)

**`src/mission-control/bridge/src/frame_validate.js`** (final, 19 lines):

```js
// Phase 22 D-02: pure param validation for GET /camera/frame.
// at = ISO-8601 timestamp (required). camera_id = allowlist (defaults to CAMERA_ID). raw = 'true' flag.
// Deliberately does NOT accept file_path (path-traversal concern — see 22-CONTEXT.md L124-L126).
function validateFrameParams(query, allowedCameraId) {
    if (!query.at) {
        return { ok: false, status: 400, error: 'at query param required (ISO-8601)' };
    }
    const atMs = Date.parse(query.at);
    if (!Number.isFinite(atMs)) {
        return { ok: false, status: 400, error: 'at must be a valid ISO-8601 timestamp' };
    }
    const cameraId = (query.camera_id || allowedCameraId).toString();
    if (cameraId !== allowedCameraId) {
        return { ok: false, status: 400, error: 'Invalid camera_id' };
    }
    const raw = query.raw === 'true';
    return { ok: true, parsed: { at: new Date(atMs), cameraId, raw } };
}
module.exports = { validateFrameParams };
```

**Test coverage (`test/frame_validate.test.js` — 10 cases):**

| # | Case | Outcome |
|---|------|---------|
| 1 | at + camera_id=fc1 happy path | `{ok: true, parsed: {at: Date, cameraId: 'fc1', raw: false}}` |
| 2 | missing at | 400 / "at query param required" |
| 3 | non-ISO at | 400 / "must be a valid ISO-8601 timestamp" |
| 4 | camera_id='evil' | 400 / "Invalid camera_id" |
| 5 | missing camera_id | defaults to allowedCameraId |
| 6 | raw='true' | parsed.raw === true |
| 7 | raw='false' | parsed.raw === false |
| 8 | missing raw | parsed.raw === false |
| 9 | raw='1' / raw='yes' | parsed.raw === false (strict match) |
| 10 | file_path='/etc/passwd' | ignored, not on parsed |

### Task 2 — GET /camera/frame route (commit f238a5a)

**Diff against `src/mission-control/bridge/src/index.js` (additive only — 66 lines inserted, 0 deleted):**

1. New import at top (line 11):
   ```js
   const { validateFrameParams } = require('./frame_validate');
   ```

2. New constant in env cluster (after HISTORY_MAX_RANGE_MS):
   ```js
   // Phase 22 D-02: closest-at-or-before tolerance window.
   const FRAME_TOLERANCE_MS = 2 * SNAPSHOT_INTERVAL_MS;
   ```

3. New route, inserted immediately after `/camera/history`:

```js
// Phase 22 D-02: single-frame retrieval for farmOS scrubber.
//   GET /camera/frame?at=<iso>&camera_id=fc1          -> burnt JPEG (default)
//   GET /camera/frame?at=<iso>&camera_id=fc1&raw=true -> raw JPEG (Phase 24 ML escape hatch)
//   Returns 404 if no snapshot within FRAME_TOLERANCE_MS at-or-before `at`.
app.get('/camera/frame', async (req, res) => {
    const v = validateFrameParams(req.query, CAMERA_ID);
    if (!v.ok) return res.status(v.status).json({ error: v.error });
    if (!dbReady) return res.status(503).json({ error: 'Database not available' });
    const { at, cameraId, raw } = v.parsed;
    const lowerBound = new Date(at.getTime() - FRAME_TOLERANCE_MS);
    try {
        const result = await pool.query(
            "SELECT captured_at, file_path " +
            "FROM snapshots " +
            "WHERE camera_id = $1 AND captured_at <= $2 AND captured_at >= $3 " +
            "ORDER BY captured_at DESC LIMIT 1",
            [cameraId, at, lowerBound]
        );
        if (result.rows.length === 0) {
            return res.status(404).json({ error: 'No frame in tolerance window' });
        }
        const row = result.rows[0];
        let srcPath;
        if (raw) {
            srcPath = row.file_path;
        } else if (row.file_path.startsWith(SNAPSHOT_DIR)) {
            srcPath = SNAPSHOT_BURNT_DIR + row.file_path.slice(SNAPSHOT_DIR.length);
        } else {
            console.error('[camera/frame] row.file_path outside SNAPSHOT_DIR, refusing burnt swap:', row.file_path);
            return res.status(404).json({ error: 'Frame unavailable' });
        }
        fs.readFile(srcPath, (err, buf) => {
            if (err) {
                if (err.code === 'ENOENT') {
                    console.error('[camera/frame] file missing on disk:', srcPath);
                    return res.status(404).json({ error: 'Frame unavailable' });
                }
                console.error('[camera/frame] read failed:', err.message);
                return res.status(500).json({ error: 'Read failed' });
            }
            res.writeHead(200, {
                'Content-Type': 'image/jpeg',
                'Content-Length': buf.length,
                'Cache-Control': 'public, max-age=3600',
                'X-Captured-At': row.captured_at.toISOString()
            });
            res.end(buf);
        });
    } catch (err) {
        console.error('[camera/frame] query failed:', err.message);
        res.status(500).json({ error: 'Query failed' });
    }
});
```

## Must-have coverage

| Must-have | Status | Receipt |
|-----------|--------|---------|
| GET /camera/frame?at=...&camera_id=fc1 returns JPEG | ✓ (code) | res.writeHead 200 with Content-Type: image/jpeg |
| ?raw=true serves RAW from /data/snapshots/ | ✓ | `if (raw) srcPath = row.file_path` |
| Default serves BURNT from /data/snapshots-burnt/ | ✓ | `SNAPSHOT_BURNT_DIR + row.file_path.slice(SNAPSHOT_DIR.length)` |
| Out-of-window (>2× SNAPSHOT_INTERVAL_MS) -> 404 | ✓ | `captured_at >= $3` where `$3 = at - FRAME_TOLERANCE_MS`; empty rows -> 404 |
| Missing at -> 400; invalid camera_id -> 400; DB not ready -> 503; DB error -> 500; row-exists-file-missing -> 404 | ✓ (unit + code) | validateFrameParams tests 2–4; `if (!dbReady) 503`; catch-block 500; `err.code === 'ENOENT'` -> 404 |
| Burnt missing -> 404 (NOT raw fallback) | ✓ | ENOENT branch returns 404 regardless of which path was read |
| No file_path pass-through | ✓ | grep `query.file_path\|req.query.file_path` = 0 in index.js |

## Acceptance-criteria grep receipts

```
grep -c "app.get('/camera/frame'"              -> 1   (== 1)
grep -c "require.*frame_validate"              -> 1   (== 1)
grep -c "FRAME_TOLERANCE_MS"                   -> 3   (>= 2)
grep -c "2 \* SNAPSHOT_INTERVAL_MS"            -> 1   (== 1)
grep -c "captured_at <= \$2 AND captured_at >= \$3" -> 1  (== 1)
grep -c "startsWith(SNAPSHOT_DIR)"             -> 1   (== 1)
grep -c "max-age=3600"                         -> 1   (>= 1)
grep -c "X-Captured-At"                        -> 1   (>= 1)
grep -cE "app\.get\('/camera/"                 -> 5   (mjpeg, snapshot, latest.jpg, history, frame)
grep -c 'query.file_path\|req.query.file_path' -> 0   (== 0)
grep -c 'file_path' frame_validate.js          -> 1   (rejection comment only — plan allows)
grep -c "raw === 'true'" frame_validate.js     -> 1   (== 1)
```

## Test output summary

`cd src/mission-control/bridge && npm test -- --forceExit`:

```
Test Suites: 5 passed, 5 total
Tests:       54 passed, 54 total
Time:        1.8 s
```

Breakdown:
- `test/frame_validate.test.js` — 10 new (all plan `<behavior>` bullets)
- `test/burn_bar.test.js` — 8, pre-existing, pass
- `test/retention.test.js` — 12, pre-existing, pass
- `test/history.test.js` — pre-existing, pass
- `test/snapshot.test.js` — pre-existing, pass

`node -c src/index.js` exits 0.

## Threat Model checks (from plan §threat_model)

| Threat ID | Coverage in this plan |
|-----------|------------------------|
| T-22-11 (`at` SQLi) | `Date.parse` -> 400; parameterized `$2` |
| T-22-12 (`camera_id` SQLi) | strict allowlist -> 400; parameterized `$1` |
| T-22-13 (file_path traversal) | validateFrameParams ignores file_path; no code path reads it |
| T-22-14 (rogue-DB-row traversal) | `startsWith(SNAPSHOT_DIR)` guard refuses swap -> 404 |
| T-22-16 (DoS unbounded scan) | Both `<=` and `>=` bounds + `LIMIT 1`; O(log n) on existing index |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test file path: `test/frame_validate.test.js` not `src/frame_validate.test.js`**
- **Found during:** Task 1 pre-work
- **Issue:** Plan's `<files>` and acceptance criteria listed `src/mission-control/bridge/src/frame_validate.test.js`, but `jest.config.js` has `testMatch: ['**/test/**/*.test.js']` — tests inside `src/` are invisible to the runner. Plan 22-02 logged this same deviation; carrying it forward.
- **Fix:** Placed test at `src/mission-control/bridge/test/frame_validate.test.js` (same dir as `burn_bar.test.js`, `history.test.js`, etc.). Test count (10) exceeds the "≥6" acceptance floor; the functional intent of the criterion is satisfied.
- **Files modified:** `test/frame_validate.test.js` (new, relocated)
- **Commit:** `8e993ad`

### Intentional plan-call-outs honored

- **10 tests, not 6:** plan said "at least 6"; wrote one per `<behavior>` bullet + extras for the `raw='yes'`/`raw='1'` strict-match contract and the file_path-ignored contract. Cheap insurance against silent contract drift.
- **1 occurrence of `file_path` in frame_validate.js:** appears only in the rejection comment. Plan explicitly permits this ("returns 0 or only appears in a rejection comment").
- **No supertest/integration test for the route itself** — plan treated this as optional; the route body is a thin DB + fs.readFile wrapper over already-unit-tested validateFrameParams, and live curl verification is scheduled for plan 22-04 after container rebuild. Keeps this plan a pure source-only change.

## Commits

- `8e993ad` test(22-03): add failing tests for frame_validate module — RED
- `b73045e` feat(22-03): implement frame_validate pure module — GREEN
- `f238a5a` feat(22-03): add GET /camera/frame route to bridge

## TDD Gate Compliance

- RED: `8e993ad` (test-only, module-missing failure) — ✓
- GREEN: `b73045e` (module lands, 10/10 pass) — ✓
- REFACTOR: not needed — module is 19 lines of straight-line validation; no cleanup opportunity that would improve readability

## Deferred (by design)

- **Container rebuild + live curl verification** → plan 22-04 (`docker compose up -d --build bridge` + end-to-end smoke).
- **farmOS CLAUDE-SYNC handoff entry** → plan 22-04.
- **Auth middleware on /camera/frame** → future work; currently same trust level as /camera/mjpeg and /camera/snapshot per D-02 and T-22-15 (accept).

## Self-Check: PASSED

- File `src/mission-control/bridge/src/frame_validate.js` exists ✓
- File `src/mission-control/bridge/test/frame_validate.test.js` exists ✓
- `src/mission-control/bridge/src/index.js` contains `app.get('/camera/frame'` ✓
- `src/mission-control/bridge/src/index.js` contains `require.*frame_validate` ✓
- `git log --oneline` shows commits `8e993ad`, `b73045e`, `f238a5a` ✓
- `cd src/mission-control/bridge && npm test` → 54 passed, 0 failed ✓
- `node -c src/index.js` → exit 0 ✓
