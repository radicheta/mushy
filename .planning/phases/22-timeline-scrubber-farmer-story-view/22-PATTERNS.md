# Phase 22: Timeline scrubber + farmer story view — Pattern Map

**Mapped:** 2026-04-19
**Files analyzed:** 4
**Analogs found:** 4 / 4 (all in-tree, direct)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/mission-control/bridge/src/index.js` (add `/camera/frame` + wrap `saveSnapshot`) | route + service | binary file I/O, CRUD lookup | same file — `/camera/history` (L367), `/camera/snapshot` (L422), `saveSnapshot` (L123) | exact |
| `docker-compose.override.yml` (repo root) | config | — | `docker-compose.yml` bridge block (L7–L30) — `SNAPSHOT_DIR` env + `/data/snapshots` volume | exact |
| `/mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md` (append entry) | coordination doc | — | Phase 18 entry at L43–L60; Phase 22 draft already at L9–L39 | exact |
| `src/mission-control/bridge/package.json` (add JPEG lib dep) | config | — | existing `dependencies` block (L10–L15) | exact |

All analogs are in the same file or directly adjacent, so no cross-module analog search was needed.

---

## Pattern Assignments

### `src/mission-control/bridge/src/index.js` — `/camera/frame` route (new)

**Role:** Express route serving binary JPEG (file-on-disk → HTTP response).

**Analog:** `/camera/snapshot` (L422–L432) for binary JPEG response; `/camera/history` (L367–L401) for param validation + `pool` query; `/history/:topic` (L316–L364) for param parsing + range cap.

**Imports (already present, no new imports needed unless adding JPEG lib):**
```js
// src/mission-control/bridge/src/index.js:1-10
const http = require('http');
const express = require('express');
const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');
const { validateHistoryParams } = require('./history_validate');
```

**Param validation + range cap pattern** (copy from `/history/:topic` L324–L334):
```js
const start = parseInt(req.query.start, 10);
const end   = parseInt(req.query.end,   10);
if (isNaN(start) || isNaN(end)) {
    return res.status(400).json({ error: 'start and end query params required (ms epoch)' });
}
const MAX_RANGE = 30 * 24 * 3600000;
if (end - start > MAX_RANGE) {
    return res.status(400).json({ error: 'Max range is 30 days' });
}
```
For `/camera/frame` the equivalent is: parse `at` as ISO (or ms), default `camera_id` to `CAMERA_ID`, reject missing `at` with 400. Reuse `validateHistoryParams` convention but you'll likely need a small `validateFrameParams` sibling — keep it stylistically identical (return `{ok, status, error, parsed}`).

**DB "closest row at-or-before" query** (adapt `/camera/history` L373–L379):
```js
// reference — current /camera/history range query
const result = await pool.query(
    "SELECT captured_at, camera_id, file_path, bytes, source, fps " +
    "FROM snapshots " +
    "WHERE camera_id = $1 AND captured_at >= $2 AND captured_at <= $3 " +
    "ORDER BY captured_at ASC LIMIT $4",
    [cameraId, new Date(from), new Date(to), HISTORY_MAX_ROWS + 1]
);
```
For `/camera/frame`, swap to `captured_at <= $2 ORDER BY captured_at DESC LIMIT 1` with a tolerance window (D-02 suggests ≤ 2× `SNAPSHOT_INTERVAL_MS`). Index `idx_snapshots_camera_captured (camera_id, captured_at DESC)` (L196–L198) already makes this O(log n).

**Binary JPEG response pattern** (copy from `/camera/snapshot` L422–L432):
```js
// src/mission-control/bridge/src/index.js:422-432
app.get('/camera/snapshot', (req, res) => {
    if (isFrameStale()) {
        return res.status(503).json({ error: 'No recent camera frame available' });
    }
    res.writeHead(200, {
        'Content-Type': 'image/jpeg',
        'Content-Length': latestFrame.length,
        'Cache-Control': 'no-cache'
    });
    res.end(latestFrame);
});
```
For `/camera/frame`: read bytes from disk via `fs.readFile` (async) — do NOT stream through `pipe()` unless frame size grows; JPEGs at 1080p are ~200–500 KB and `res.end(buf)` is simpler. Set `Cache-Control: public, max-age=...` — frames are immutable once written (safe to cache); keep `Content-Length` set from `buf.length`.

**Path resolution for burnt-vs-raw:**
```js
// derived from Phase 22 D-03 — same filename, different root
const rawDir   = process.env.SNAPSHOT_DIR      || '/data/snapshots';
const burntDir = process.env.SNAPSHOT_BURNT_DIR || '/data/snapshots-burnt';
const srcPath  = req.query.raw === 'true'
    ? row.file_path                                // raw path as stored in DB
    : row.file_path.replace(rawDir, burntDir);    // derive burnt twin
```
Note: `file_path` in the DB is absolute (see `saveSnapshot` L137: `path.join(dir, filename)` where `dir = path.join(SNAPSHOT_DIR, CAMERA_ID, dateDir)`). The twin-path swap works as long as `SNAPSHOT_DIR` is the strict prefix — which it is, by construction. Planner: guard against `SNAPSHOT_BURNT_DIR` ending up equal to `SNAPSHOT_DIR` (reject at startup).

**Error handling pattern** (match `/camera/history` L397–L400):
```js
} catch (err) {
    console.error('[snapshots] history query failed:', err.message);
    res.status(500).json({ error: 'Query failed' });
}
```
For `/camera/frame`: 404 if no row in tolerance window; 503 if `!dbReady`; 500 on DB error; 404 if row exists but file missing on disk (log `[camera/frame] file missing:` — orphaned row, surface gracefully per gap-over-noise).

---

### `src/mission-control/bridge/src/index.js` — burn-in sidecar inside `saveSnapshot()` (modify)

**Role:** Async transform of JPEG buffer → JPEG buffer with overlay, followed by second filesystem write.

**Analog:** the existing `saveSnapshot()` at L123–L157 itself — it already does async `fs.writeFile` after a sync `mkdirSync`. Extend, don't replace.

**Current write path** (L130–L156, reference — planner's modification target):
```js
// src/mission-control/bridge/src/index.js:130-157
const capturedAt = new Date();
const bytes = latestFrame.length;
const source = decideSource(mjpegClients.size);
const dateDir = capturedAt.toISOString().slice(0, 10);
const dir = path.join(SNAPSHOT_DIR, CAMERA_ID, dateDir);
fs.mkdirSync(dir, { recursive: true });
const filename = `${capturedAt.toISOString().replace(/[:.]/g, '-')}.jpg`;
const filepath = path.join(dir, filename);
fs.writeFile(filepath, latestFrame, async (err) => {
    if (err) {
        console.error('[camera] snapshot write failed:', err.message);
        return;
    }
    console.log(`[camera] snapshot saved: ${filepath} (${source}, ${bytes} bytes)`);
    if (!dbReady) return;
    try {
        await pool.query(
            `INSERT INTO snapshots (captured_at, camera_id, file_path, bytes, source, fps)
             VALUES ($1, $2, $3, $4, $5, $6)`,
            [capturedAt, CAMERA_ID, filepath, bytes, source, null]
        );
    } catch (e) {
        console.error('[snapshots] insert failed:', e.message);
    }
});
```

**Extension pattern — parallel burnt write:**
1. Compute `burntDir = path.join(SNAPSHOT_BURNT_DIR, CAMERA_ID, dateDir)`, `mkdirSync` it. Same filename.
2. Build overlay text from `latestTelemetry` (L36–L41 cache, Phase 18 source-of-truth):
   ```js
   // read-only access — already populated by subscription callbacks
   const rh   = latestTelemetry.humidity?.value;
   const temp = latestTelemetry.temperature?.value;
   const co2  = latestTelemetry.co2?.value;
   const hum  = latestTelemetry.humidifier?.value; // 0 | 1 | undefined
   const fmt  = v => (v === null || v === undefined) ? '—' : v.toFixed(1);
   const humStr = hum === undefined || hum === null ? '—' : (hum ? 'ON' : 'OFF');
   const bar = `${capturedAt.toISOString()} · RH ${fmt(rh)}% · T ${fmt(temp)}°C · CO₂ ${fmt(co2)}ppm · HUM ${humStr}`;
   ```
   Null → `—` en-dash is the **gap-over-noise** rule (`feedback_gap_over_noise.md`).
3. Burn with JPEG lib (planner picks — `sharp` recommended for speed at minimal code; `jimp` acceptable for zero native deps). Pseudocode:
   ```js
   const burnt = await burnBar(latestFrame, bar); // Buffer -> Buffer
   fs.writeFile(burntPath, burnt, (err) => { if (err) console.error('[camera/burnt] write failed:', err.message); });
   ```
4. **Do not block** the raw write or DB insert on the burn. Fire-and-forget; log failures. DB row still references `file_path` (raw), unchanged — Phase 21 schema is preserved.
5. **Must not slow the write path enough to drop frames** (cadence is 5 min, plenty of headroom — but keep burn async and off the ROS callback thread).

**Error handling:** burnt-write failures are logged, non-fatal. Raw write + DB row are the source of truth; a missing burnt file just causes `/camera/frame` (default mode) to 404 for that exact timestamp — acceptable (gap over noise).

---

### `docker-compose.override.yml` — burnt volume + env var (modify)

**Role:** Bind-mount the burnt tree into the bridge container; set `SNAPSHOT_BURNT_DIR`.

**Analog:** `docker-compose.yml` bridge block (L7–L30) — already sets `SNAPSHOT_DIR=/data/snapshots` (L23) and mounts `/data/snapshots:/data/snapshots` (L30).

**Existing pattern to mirror** (`docker-compose.yml` L22–L30):
```yaml
      - SNAPSHOT_DIR=/data/snapshots
      - SNAPSHOT_INTERVAL_MIN=5
      - CAMERA_ID=fc1
      # Phase 21 retention defaults (optional; in-process daily prune)
      - RETENTION_DAYS=${RETENTION_DAYS:-365}
      - RETENTION_GRACE_DAYS=${RETENTION_GRACE_DAYS:-30}
    volumes:
      - /data/snapshots:/data/snapshots
```

**Override addition** (fits into existing `bridge:` block in `docker-compose.override.yml` L8–L15):
```yaml
  bridge:
    environment:
      - SNAPSHOT_BURNT_DIR=/data/snapshots-burnt
    volumes:
      - /data/snapshots-burnt:/data/snapshots-burnt
```
Note: the override already contains a `bridge:` block with `network_mode`, `environment`, and `volumes` — merge into the same keys (docker-compose deep-merges lists, so appending is safe). Host-side `/data/snapshots-burnt` must exist before `docker compose up -d --build bridge`; planner adds a one-liner to the deploy path or to Phase 22 Phase 1 task-0 setup.

**Runtime-compose gotcha (`feedback_verify_runtime_compose.md`):** the live stack runs from repo-root `docker-compose.yml` + `docker-compose.override.yml`. `src/docker-compose.yml` is deprecated — do NOT edit it.

---

### `src/mission-control/bridge/package.json` — JPEG lib dep (modify)

**Role:** Add one JPEG-manipulation dependency.

**Analog:** existing `dependencies` block (L10–L15):
```json
  "dependencies": {
    "express": "^5.2.1",
    "pg": "^8.20.0",
    "rclnodejs": "^1.9.0",
    "ws": "^8.16.0"
  },
```

**Addition (planner picks one):**
- **`sharp` (recommended):** fast libvips-based; ~9 MB native binary per platform; `sharp(buf).composite([{input: svgOverlay, gravity: 'south'}]).jpeg().toBuffer()` is the idiomatic bottom-bar pattern. Needs libvips in the bridge Dockerfile base (check Dockerfile; if `node:20-slim` — sharp prebuilds cover linux/arm64 and linux/amd64).
- **`jimp`:** pure JS, no native deps, simpler Dockerfile, slower (~10× for composite). At 1 frame / 5 min cadence, speed is irrelevant; size is — jimp is ~700 KB, sharp pulls ~20 MB node_modules.
- **`@napi-rs/canvas`:** mid-ground; gives full Canvas API (text rendering, fonts). Heaviest.

**Match existing style** — no dev-only, caret-pinned major. Example:
```json
  "dependencies": {
    "express": "^5.2.1",
    "pg": "^8.20.0",
    "rclnodejs": "^1.9.0",
    "sharp": "^0.34.0",
    "ws": "^8.16.0"
  },
```

**Dockerfile side-effect:** check `src/mission-control/bridge/Dockerfile` — if switching to `sharp`, confirm the base image has glibc (not Alpine/musl) or add `apk add vips-dev` / use `node:20-bookworm-slim`. Planner verifies during planning, not here.

---

### `/mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md` — append coordination entry (modify)

**Role:** Append one markdown section documenting the new endpoint shape for Zoy-side.

**Analog:** Phase 18 entry at L43–L60 — and a **draft Phase 22 entry already exists at L9–L39** (added during the discuss phase). Verify-before-append:

**Existing Phase 22 entry (L9–L39 — already there, planner just confirms content matches final plan):**
```markdown
## 2026-04-19 — radicheta-side — Phase 22 (story view) delegated to your side + new endpoints

Same delegation posture as Phase 18: ... [full entry already present at L9–L39]
```

If the planner lands a deviation from the discuss-phase draft (e.g., different tolerance window, added `?file_path=` param, Cache-Control header set), edit the existing entry in place rather than appending a duplicate. The file is newest-on-top; do not re-order.

**Style conventions** (copied from file's own preamble L3–L5 + Phase 18 entry L43–L60):
- Newest entry on top (above `---` separators).
- Sign with `— radicheta-side Claude`.
- Mark stale entries `[resolved]` — do not delete.
- Section header pattern: `## YYYY-MM-DD — radicheta-side — <short subject>`.

---

## Shared Patterns

### Express route conventions
**Source:** `src/mission-control/bridge/src/index.js` (all existing routes)
**Apply to:** `/camera/frame`

- Plain JSON responses via `res.json({...})` — no wrapper envelope (e.g., `/farmer/summary` L278–L301, `/camera/history` L382–L396).
- Binary responses via `res.writeHead + res.end(buffer)` — see `/camera/snapshot` L425–L431.
- Timestamps: ISO strings for HTTP boundaries (`/camera/history` L389), ms epoch for WS broadcasts and `/farmer/summary` payload (`timestamp: Date.now()` L284). `/camera/frame` takes `at=<iso>` per D-02 → ISO is the right choice.
- 4xx for bad client input, 503 for "DB not ready / frame stale", 500 for server-side DB exceptions. No custom error class; plain `{error: '...'}` literal.

### Env-var-driven config
**Source:** L62–L75 (bridge knobs cluster)
**Apply to:** `SNAPSHOT_BURNT_DIR`

- Read once at module top with a default: `const SNAPSHOT_BURNT_DIR = process.env.SNAPSHOT_BURNT_DIR || '/data/snapshots-burnt';`
- No YAML config for bridge-only knobs (Phase 21 D-"Environment-variable config").
- Wire into both `docker-compose.yml` (base env) and `docker-compose.override.yml` (mount) — mirror the `SNAPSHOT_DIR` pair.

### Gap-over-noise (`feedback_gap_over_noise.md`)
**Source:** `/farmer/summary` null handling (L286–L295), D-03 null rendering rule
**Apply to:** burn-in bar text rendering + `/camera/frame` 404-on-missing

- Null sensor → `—` en-dash in the burnt bar, never a fabricated "0.0" or "N/A".
- File-missing on disk but DB row present → 404 with `{error: 'frame unavailable'}`, not a served placeholder image.
- Burnt-write failure → log and move on; do not re-use stale burnt frame from a prior capture.

### Postgres pool reuse
**Source:** L19–L25 (pool construction), L146 / L344 / L373 (query callsites)
**Apply to:** `/camera/frame` closest-row lookup

- Single `pool` module-level — no per-request connection.
- Parameterized queries only (`$1, $2, …`); no template interpolation of user input.
- Query errors: `catch (e) { console.error('[component] ... failed:', e.message); res.status(500).json({error: 'Query failed'}); }` — match L397–L400 tone.

### Retention coupling
**Source:** L612–L624 (prune scheduling), `retention.js` (sweep logic, see D-03 disk-symmetry note in CONTEXT)
**Apply to:** burnt tree

- The Phase 21 prune job sweeps `SNAPSHOT_DIR` by DB row → file deletion. Burnt files are **not** indexed in DB. Planner picks one of:
  1. Sweep the burnt tree by mirroring raw deletions (delete burnt twin whenever raw is deleted — 1-line in `retention.js` sweep loop).
  2. Separate age-based sweep of burnt tree (directory-walk + `stat.mtime < cutoff`).
- Option 1 is simpler and keeps the two trees lockstep. Recommended to planner.

---

## No Analog Found

None. Every file has a direct in-tree analog; nothing requires RESEARCH.md fallback.

---

## Metadata

**Analog search scope:** `src/mission-control/bridge/src/`, repo-root `docker-compose*.yml`, `/mnt/slime-kingdom/shared/farmos/`.
**Files scanned:** `src/index.js` (L1–L637, full), `docker-compose.yml`, `docker-compose.override.yml`, `package.json`, `CLAUDE-SYNC.md`, `21-CONTEXT.md`, `22-CONTEXT.md`, `18-CONTEXT.md`.
**Pattern extraction date:** 2026-04-19.
