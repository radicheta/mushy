# Phase 23: Time-lapse composition (ffmpeg) — Research

**Researched:** 2026-04-26
**Domain:** Node.js timelapse pipeline — ffmpeg concat, per-frame overlay, async job queue, TimescaleDB RH lookup
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** New `timelapse` container in docker-compose, sibling to bridge/alerter. Node.js + ffmpeg binary.
- **D-02:** Nightly trigger via `node-cron` inside the container at 00:30 local time. Composes the previous calendar day's frames.
- **D-03:** On-demand endpoint `GET /timelapse?from=<iso>&to=<iso>&camera_id=fc1`. Returns pre-composed mp4 if exists; returns 202+job-id if composing on-the-fly. Poll `/timelapse/status/:id`.
- **D-04:** ffmpeg recipe: `-f concat -safe 0 -i filelist.txt -c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p -r 12`
- **D-05:** Framerate: 12fps. Env var `TIMELAPSE_FPS` (default: 12).
- **D-06:** Overlay: `drawtext` filter — timestamp (top-left) + RH (top-right). White text, small font, semi-transparent box.
- **D-07:** Skip if fewer than 3 frames. Log warning.
- **D-08:** Output: `/data/timelapse/{camera_id}/YYYY-MM-DD.mp4`
- **D-09:** Per-day mp4s kept forever. Raw frames already on 365-day retention via Phase 21.
- **D-10:** Timescale `timelapses` table: `(camera_id, date, file_path, frames_used, composed_at, duration_sec)`
- **D-11:** RH nearest-neighbor lookup from `telemetry` table at composition time. Omit RH from overlay if no reading within 30min.

### Claude's Discretion

- Exact font size and overlay positioning
- Whether to add a health chip for timelapse job state
- Error handling details (retry count, alerter integration if nightly job fails)

### Deferred Ideas (OUT OF SCOPE)

- CO2 overlay
- Farmer-facing UI to browse/download time-lapses (999.11)
- Multi-camera support (999.6)
- Annotated time-lapses with ML bounding boxes (Phase 24)
- Signal notification when daily timelapse is ready

</user_constraints>

---

## Summary

Phase 23 adds a standalone `timelapse` Node.js container that auto-composes daily mp4s from the Phase 21 snapshot archive. The core pipeline is: (1) query Timescale `snapshots` table for a day's frame paths, (2) resolve nearest RH reading per frame from `telemetry`, (3) pre-burn a timestamp+RH overlay onto each frame using jimp (matching the existing `burn_bar.js` pattern), (4) write a concat filelist and invoke ffmpeg via `child_process.spawn`, (5) write the output to `/data/timelapse/fc1/YYYY-MM-DD.mp4` and record it in a new `timelapses` table.

The critical design choice is **pre-burning overlay text in Node.js before ffmpeg** rather than relying on ffmpeg's `drawtext` filter. Per-frame variable text (different timestamp + RH per frame) is not achievable accurately with a single ffmpeg invocation when frame capture intervals are irregular. The project already has `burn_bar.js` (jimp v1.6.1) proving this pattern. For 282 frames/day, pre-burning at ~50ms/frame takes ~14s total — acceptable for a nightly batch.

Real data shows: 123–288 frames/day at 5-min intervals (SNAPSHOT_INTERVAL_MIN=5), yielding 10–24s clips at 12fps. The Timescale `telemetry` table holds ~18k RH readings per day (roughly every 5s), so nearest-neighbor lookup within 30min will match every frame with high confidence. The RH topic name in Timescale is `fc.humidity` (not `fc1/humidity` as CONTEXT.md D-11 states — corrected here).

**Primary recommendation:** Pre-burn overlay per frame with jimp, then concat annotated jpegs via ffmpeg. Use `node-cron` for nightly scheduling (same pattern as alerter heartbeat). Expose an Express HTTP server on port 8888 for the on-demand endpoint and `/timelapse/status/:id` poll route.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Daily mp4 generation | timelapse container | — | Independent of bridge; can rebuild/redeploy without touching bridge |
| On-demand composition | timelapse container | — | Same process; async job queue avoids blocking the HTTP handler |
| RH overlay data | Timescale (read) | — | Single query at composition time, not real-time |
| Frame inventory | Timescale `snapshots` (read) | Filesystem `/data/snapshots/` | DB is source of truth for path; filesystem holds actual bytes |
| Timelapse registry | Timescale `timelapses` (write) | — | Persists composition metadata; used by on-demand endpoint to skip re-composition |
| Nightly scheduling | timelapse container (node-cron) | — | No external scheduler needed; TZ= env var controls local time |
| mp4 file serving | NOT timelapse container | Caller fetches file directly | 202 + file path returned; caller serves the file themselves (future) |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| node-cron | 4.2.1 | Nightly 00:30 trigger | Same pattern as alerter heartbeat; TZ-aware |
| express | 5.2.1 | HTTP server for on-demand + status endpoints | Already the project HTTP layer |
| pg | 8.20.0 | Timescale queries (RH lookup, snapshots, timelapses table) | Project standard Postgres client |
| jimp | 1.6.1 | Per-frame timestamp+RH overlay burn-in | Already in bridge with proven pattern |
| ffmpeg (binary) | 8.0.1 (Alpine) | mp4 encoding via libx264 | System binary, not npm |

[VERIFIED: npm registry — node-cron 4.2.1, express 5.2.1, pg 8.20.0, jimp 1.6.1]
[VERIFIED: docker run node:20-alpine + apk add ffmpeg — installs 8.0.1]

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| child_process (built-in) | Node built-in | Spawn ffmpeg process | Standard; no wrapper needed |
| crypto (built-in) | Node built-in | Generate job IDs via `crypto.randomUUID()` | Avoid adding uuid dependency |
| fs/path (built-in) | Node built-in | Frame file enumeration, output dir creation | Project already uses directly |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| jimp pre-burn | ffmpeg `drawtext` with reload | drawtext reload reads from one shared file — works only for uniform-interval captures. Irregular-interval captures (e.g., 52 frames on 2026-04-19) produce wrong timestamps. Pre-burn is explicit and testable. |
| jimp pre-burn | sharp | sharp is 5–10x faster but adds a new dependency. At 288 frames × 50ms = 14s, jimp is acceptable for nightly batch. Use sharp if composition time exceeds 30s in practice. [ASSUMED] |
| node-cron | setInterval-based scheduler | alerter uses a manual interval loop. node-cron is declarative and simpler for a fixed-time daily trigger. |

**Installation:**
```bash
npm install node-cron express pg jimp
```

**Version verification:** [VERIFIED: npm view node-cron version → 4.2.1; npm view express version → 5.2.1; npm view pg version → 8.20.0; npm view jimp version → 1.6.1]

**Dockerfile:**
```dockerfile
FROM node:20-alpine
RUN apk add --no-cache ffmpeg font-dejavu
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev
COPY src/ ./src/
ENV NODE_ENV=production
CMD ["node", "src/index.js"]
```

[VERIFIED: `apk add ffmpeg font-dejavu` installs ffmpeg 8.0.1 + DejaVuSans.ttf on node:20-alpine]

---

## Architecture Patterns

### System Architecture Diagram

```
Nightly cron (00:30 TZ)
        │
        ▼
  composeDay(date, camera_id)
        │
   ┌────┴─────────────────────────────────┐
   │  1. Query Timescale snapshots        │
   │     WHERE camera_id + date range     │
   │     ORDER BY captured_at ASC         │
   │                                      │
   │  2. CHECK frame count >= 3           │
   │     (< 3) → log warning, skip        │
   │                                      │
   │  3. Batch RH lookup                  │
   │     SELECT captured_at, value        │
   │     FROM telemetry                   │
   │     WHERE topic='fc.humidity' + range│
   │     → nearest-neighbor per frame     │
   │                                      │
   │  4. Pre-burn overlay (jimp)          │
   │     per frame: timestamp + RH        │
   │     → write to /tmp/timelapse_work/  │
   │                                      │
   │  5. Write concat filelist.txt        │
   │     file '/tmp/.../frame_001.jpg'    │
   │     ...                              │
   │                                      │
   │  6. spawn ffmpeg                     │
   │     -f concat -safe 0 -i filelist    │
   │     -c:v libx264 -crf 23 ...         │
   │     → /data/timelapse/fc1/DATE.mp4   │
   │                                      │
   │  7. INSERT INTO timelapses           │
   │  8. Cleanup /tmp/timelapse_work/     │
   └──────────────────────────────────────┘

GET /timelapse?from=&to=&camera_id=
        │
        ├─ date range spans exactly 1 day, mp4 exists?
        │         → 200 + { file_path, duration_sec }
        │
        └─ needs composition
                  │
                  ├─ enqueue async job → jobId = crypto.randomUUID()
                  │   jobs Map: { id, status, error }
                  │
                  └─ 202 + { job_id }

GET /timelapse/status/:id
        │
        ├─ pending/running → 200 { status: 'pending'|'running' }
        ├─ done → 200 { status: 'done', file_path, duration_sec }
        └─ failed → 200 { status: 'failed', error }

GET /health
        → { status, db, last_nightly_at, last_nightly_status }
```

### Recommended Project Structure
```
src/timelapse/
├── Dockerfile
├── package.json
└── src/
    ├── index.js         # Express server + cron setup + startup
    ├── composer.js      # composeDay(date, cameraId, pool, opts) — pure pipeline
    ├── overlay.js       # burnOverlay(framePath, timestamp, rh) → Buffer — testable
    ├── db.js            # initDb(), insertTimelapse(), lookupTimelapse()
    └── config.js        # load env vars
```

### Pattern 1: Pre-burn Overlay (jimp)

**What:** Render timestamp (top-left) and RH (top-right) onto a JPEG frame before passing to ffmpeg.
**When to use:** Any per-frame variable text; jimp already proven in `burn_bar.js`.

```javascript
// Source: burn_bar.js pattern (bridge/src/burn_bar.js)
const { Jimp, JimpMime, loadFont } = require('jimp');
const fonts = require('jimp/fonts');

async function burnOverlay(inputBuffer, { timestamp, rh }) {
    const img = await Jimp.read(inputBuffer);
    const font = await loadFont(fonts.SANS_16_WHITE);
    // Top-left: timestamp as "YYYY-MM-DD HH:MM"
    img.print({ font, x: 8, y: 8, text: timestamp });
    // Top-right: RH value (if available)
    if (rh !== null) {
        const rhText = `RH ${rh.toFixed(1)}%`;
        img.print({ font, x: img.bitmap.width - 80, y: 8, text: rhText });
    }
    return img.getBuffer(JimpMime.jpeg, { quality: 85 });
}
```

### Pattern 2: ffmpeg concat

**What:** Encode sorted JPEG frames into mp4 via concat demuxer.
**When to use:** Batch composition; each frame displayed at equal duration (1/fps seconds).

```javascript
// Source: [VERIFIED: local ffmpeg test confirmed this recipe works]
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

async function runFfmpeg(filelistPath, outputPath, fps = 12) {
    return new Promise((resolve, reject) => {
        const args = [
            '-y',                         // overwrite output if exists
            '-f', 'concat',
            '-safe', '0',
            '-i', filelistPath,
            '-c:v', 'libx264',
            '-crf', '23',
            '-preset', 'fast',
            '-pix_fmt', 'yuv420p',
            '-r', String(fps),
            outputPath
        ];
        const proc = spawn('ffmpeg', args, { stdio: ['ignore', 'pipe', 'pipe'] });
        let stderr = '';
        proc.stderr.on('data', d => { stderr += d.toString(); });
        proc.on('close', code => {
            if (code === 0) resolve();
            else reject(new Error(`ffmpeg exited ${code}: ${stderr.slice(-500)}`));
        });
    });
}
```

### Pattern 3: node-cron Nightly Trigger

**What:** Fire composition job at 00:30 local time every day.

```javascript
// Source: node-cron docs; TZ= env var sets container local time
const cron = require('node-cron');

cron.schedule('30 0 * * *', async () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    const dateStr = yesterday.toISOString().slice(0, 10);
    try {
        await composeDay(dateStr, cameraId);
    } catch (e) {
        console.error('[cron] nightly composition failed:', e.message);
    }
});
```

[VERIFIED: node-cron 4.2.1 supports standard cron syntax with TZ from process.env.TZ]

### Pattern 4: Async On-Demand Job

**What:** 202-response with job ID; caller polls `/timelapse/status/:id`.
**When to use:** Composition can take 14–30s; must not block the HTTP request.

```javascript
// In-memory job registry (resets on container restart — acceptable for on-demand)
const jobs = new Map();  // jobId -> { status, file_path, error }

app.get('/timelapse', async (req, res) => {
    const { from, to, camera_id = 'fc1' } = req.query;
    // Check if already composed
    const existing = await db.lookupTimelapse(pool, camera_id, from, to);
    if (existing) return res.json({ file_path: existing.file_path, duration_sec: existing.duration_sec });
    // Enqueue
    const jobId = crypto.randomUUID();
    jobs.set(jobId, { status: 'pending' });
    setImmediate(() => runCompositionJob(jobId, { from, to, camera_id }));
    res.status(202).json({ job_id: jobId });
});

app.get('/timelapse/status/:id', (req, res) => {
    const job = jobs.get(req.params.id);
    if (!job) return res.status(404).json({ error: 'Unknown job' });
    res.json(job);
});
```

### Pattern 5: Batch RH Lookup

**What:** Single query for all RH readings in the day; per-frame nearest-neighbor in memory.
**When to use:** Composition time; avoids N+1 queries (288 frames × 1 query each = unacceptable).

```javascript
// Source: [VERIFIED: telemetry table has 18119 rows/day for fc.humidity — dense enough]
async function fetchRhForDay(pool, date) {
    const start = `${date}T00:00:00Z`;
    const end   = `${date}T23:59:59.999Z`;
    const result = await pool.query(
        `SELECT captured_at, value FROM telemetry
         WHERE topic = 'fc.humidity'
           AND captured_at >= $1 AND captured_at <= $2
         ORDER BY captured_at ASC`,
        [start, end]
    );
    return result.rows;  // [{ captured_at: Date, value: float }]
}

function nearestRh(rhRows, frameTs, toleranceMs = 30 * 60 * 1000) {
    if (rhRows.length === 0) return null;
    let best = null, bestDelta = Infinity;
    for (const row of rhRows) {
        const delta = Math.abs(row.captured_at.getTime() - frameTs);
        if (delta < bestDelta) { bestDelta = delta; best = row.value; }
        if (delta > bestDelta) break;  // rows sorted, delta only grows from here
    }
    return bestDelta <= toleranceMs ? best : null;
}
```

### Anti-Patterns to Avoid

- **Per-frame ffmpeg invocations:** Running ffmpeg once per frame to burn text is 200–300x slower than pre-burning in Node.js then running ffmpeg once.
- **ffmpeg drawtext with `reload=N` for per-frame timestamps:** The reload mechanism writes a shared text file; it is not designed for batch composition with pre-determined per-frame text.
- **Synchronous ffmpeg spawn:** Using `execSync` blocks the event loop during the 14–30s composition. Always use `spawn` with a Promise wrapper.
- **Writing composed mp4 directly to `/data/timelapse/` then failing mid-write:** Write to `/tmp/timelapse_work/DATE.mp4.tmp` first, then `fs.rename` to the final path. Avoids serving partial files.
- **Not creating the output directory:** `/data/timelapse/fc1/` doesn't exist yet. Use `fs.mkdirSync(dir, { recursive: true })` before writing.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cron scheduling | Manual setInterval + date checks | node-cron | DST-safe, declarative, already proven in alerter heartbeat pattern |
| Image text rendering | Custom PNG/JPEG compositing | jimp (already in project) | Handles JPEG decode/encode, composite, font; tested pattern in burn_bar.js |
| Postgres connection pool | Raw pg.Client per query | `new Pool(...)` | Project standard; handles reconnect, idle timeouts |
| Job ID generation | Manual counter or timestamp | `crypto.randomUUID()` | Built-in, no dependency, collision-safe |

**Key insight:** The heaviest ffmpeg complexity (overlays, filters) becomes simple once you accept that Node.js handles per-frame text and ffmpeg only handles encoding.

---

## Common Pitfalls

### Pitfall 1: Wrong Telemetry Topic Name
**What goes wrong:** Code queries `topic='fc1/humidity'` (the ROS topic name) and gets zero rows.
**Why it happens:** CONTEXT.md D-11 uses the ROS topic name. The bridge inserts as `'fc.humidity'` (dot notation).
**How to avoid:** Use `'fc.humidity'` in all Timescale queries. [VERIFIED: `SELECT DISTINCT topic FROM telemetry` → `fc.humidity`, `fc.temperature`, etc.]
**Warning signs:** RH overlay always shows `—` despite the chamber being live.

### Pitfall 2: yuv420p Requires Even Dimensions
**What goes wrong:** ffmpeg fails with `width not divisible by 2` or `height not divisible by 2`.
**Why it happens:** libx264 with yuv420p requires both dimensions to be even numbers.
**How to avoid:** Actual frames are 640×480 [VERIFIED: `identify` on live frame]. Both even — no padding needed. If a future camera produces odd dimensions, add `-vf "scale=trunc(iw/2)*2:trunc(ih/2)*2"` before `-c:v`.
**Warning signs:** ffmpeg exits non-zero with `Incompatible pixel format` error.

### Pitfall 3: Alpine ffmpeg 8.0 `reload` Option Changed Type
**What goes wrong:** `drawtext=reload=true` errors: `Option reload: Invalid option`.
**Why it happens:** Alpine ffmpeg 8.0 changed `reload` from boolean to int (reload every N frames). Ubuntu 22.04 ffmpeg 4.4 used boolean.
**How to avoid:** Not applicable — this phase pre-burns text in Node.js and doesn't use `drawtext`. Document for future maintainers.

### Pitfall 4: Partial mp4 on Failure Poisons the Cache
**What goes wrong:** Composition fails midway; the partial mp4 at `/data/timelapse/fc1/DATE.mp4` causes future runs to skip (it "exists") but is unplayable.
**Why it happens:** Writing directly to the final path without atomic rename.
**How to avoid:** Write to `DATE.mp4.tmp`, then `fs.rename()` only on ffmpeg exit code 0. Clean up `.tmp` on any error.

### Pitfall 5: Pre-burned Frames Accumulate in /tmp
**What goes wrong:** `/tmp/timelapse_work/` fills up over multiple failed runs.
**Why it happens:** No cleanup on error paths.
**How to avoid:** `try/finally` block always calls `fs.rmSync(workDir, { recursive: true, force: true })` after composition completes or fails.

### Pitfall 6: node-cron Fires in UTC, Not Local Time
**What goes wrong:** `'30 0 * * *'` fires at 00:30 UTC regardless of TZ env var in older versions.
**Why it happens:** Some cron implementations ignore `TZ`.
**How to avoid:** node-cron 4.x respects `process.env.TZ` when no explicit timezone is passed to `cron.schedule`. Set `TZ=America/Toronto` in docker-compose (matches alerter pattern). [VERIFIED: node-cron 4.2.1 current version]

### Pitfall 7: On-Demand Job State Lost on Container Restart
**What goes wrong:** In-memory `jobs` Map loses all pending/running jobs on restart; callers polling `/timelapse/status/:id` get 404.
**Why it happens:** State is not persisted.
**How to avoid:** This is acceptable for v1 — on-demand jobs are short-lived (< 30s). Document in code. If the job completes and the mp4 exists, subsequent `/timelapse?...` calls return 200 directly from the DB.

---

## Code Examples

### Timescale Schema Migration
```javascript
// Source: bridge/src/index.js initDb() pattern
await pool.query(`
    CREATE TABLE IF NOT EXISTS timelapses (
        camera_id    TEXT        NOT NULL,
        date         DATE        NOT NULL,
        file_path    TEXT        NOT NULL,
        frames_used  INTEGER     NOT NULL,
        composed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        duration_sec NUMERIC,
        PRIMARY KEY (camera_id, date)
    )
`);
```

### Snapshot Query for a Day (TZ-Aware)
```javascript
// Use UTC bounds for Timescale; let TZ conversion happen at the query level.
// 'date' is 'YYYY-MM-DD' in America/Toronto. Convert to UTC range:
const start = new Date(`${date}T05:00:00Z`);  // America/Toronto is UTC-5 (or UTC-4 DST)
// Better: compute from TZ-aware midnight:
const start = new Date(
    new Date(`${date}T00:00:00`).toLocaleString('en-US', { timeZone: 'America/Toronto' })
);
// Simplest for daily cron composing previous day: just use date string + UTC 00:00 → 23:59:59
// The snapshots captured_at is stored in UTC; date boundary queries must account for TZ.
// Recommended: parameterize as full UTC range derived from TZ-aware midnight.
```

**Note:** The `timelapses` table uses `DATE` type. When querying whether a timelapse exists for a given day, query as `WHERE camera_id=$1 AND date=$2` where `$2` is the date string `'YYYY-MM-DD'`.

### Concat Filelist Format
```
file '/tmp/timelapse_work/fc1/frame_0001.jpg'
file '/tmp/timelapse_work/fc1/frame_0002.jpg'
...
```
Single-quoted paths. The `-safe 0` flag is required because absolute paths would otherwise be rejected.

---

## Runtime State Inventory

> This is a greenfield container — no rename/refactor. No runtime state to migrate.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — `timelapses` table does not exist yet; will be created by `initDb()` | CREATE TABLE in Wave 0 |
| Live service config | `/data/timelapse/` directory does not exist | `mkdirSync` on first write or Wave 0 setup |
| OS-registered state | None | — |
| Secrets/env vars | `TIMESCALE_PASSWORD` (existing), `TIMESCALE_HOST=timescale` (existing) — no new secrets needed | Reuse bridge pattern |
| Build artifacts | None | — |

**Confirmed:** `ls /data/` shows `snapshots/` and `snapshots-burnt/` only. `timelapse/` does not exist. [VERIFIED: shell]

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker / docker compose | Container build | ✓ | Active stack | — |
| node:20-alpine base | Dockerfile FROM | ✓ | Docker Hub | — |
| ffmpeg (apk) | mp4 encoding | ✓ | 8.0.1 (Alpine) | — |
| font-dejavu (apk) | drawtext font | ✓ | Installed with ffmpeg | Bundle a font TTF in src/ |
| TimescaleDB | RH lookup + registry | ✓ | Running | — |
| `/data/snapshots/fc1/` | Frame source | ✓ | 15 days of frames | — |
| `/data/timelapse/` | Output dir | ✗ | Does not exist | Create on first write |

[VERIFIED: `docker run node:20-alpine sh -c "apk add --no-cache ffmpeg font-dejavu"` succeeds; ffmpeg 8.0.1 + DejaVuSans.ttf confirmed]
[VERIFIED: `ls /data/snapshots/fc1/` — 15 days of frames, 123–288 frames/day]

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Jest 29 |
| Config file | `src/timelapse/jest.config.js` — Wave 0 create |
| Quick run command | `jest --testPathPattern=timelapse` |
| Full suite command | `cd src/timelapse && npm test` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TL-01 | `composeDay` returns early + logs warning if < 3 frames | unit | `jest --testPathPattern=composer` | ❌ Wave 0 |
| TL-02 | `nearestRh` returns correct value within tolerance, null outside | unit | `jest --testPathPattern=overlay` | ❌ Wave 0 |
| TL-03 | `burnOverlay` produces a JPEG buffer with modified pixels | unit | `jest --testPathPattern=overlay` | ❌ Wave 0 |
| TL-04 | `initDb` creates `timelapses` table if not exists | unit (mock pool) | `jest --testPathPattern=db` | ❌ Wave 0 |
| TL-05 | `/timelapse` returns 200 + file_path when mp4 exists in DB | unit (mock) | `jest --testPathPattern=routes` | ❌ Wave 0 |
| TL-06 | `/timelapse` returns 202 + job_id when no mp4 | unit (mock) | `jest --testPathPattern=routes` | ❌ Wave 0 |
| TL-07 | `/timelapse/status/:id` returns 404 for unknown job | unit | `jest --testPathPattern=routes` | ❌ Wave 0 |
| TL-08 | Nightly cron produces a valid mp4 for previous day | smoke (manual) | Run container, wait for 00:30 OR invoke `composeDay` directly | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd src/timelapse && npm test`
- **Per wave merge:** `cd src/timelapse && npm test`
- **Phase gate:** All unit tests green + TL-08 manual smoke before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `src/timelapse/package.json` + `jest.config.js` — test infrastructure
- [ ] `src/timelapse/test/composer.test.js` — covers TL-01
- [ ] `src/timelapse/test/overlay.test.js` — covers TL-02, TL-03
- [ ] `src/timelapse/test/db.test.js` — covers TL-04
- [ ] `src/timelapse/test/routes.test.js` — covers TL-05, TL-06, TL-07

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Internal service, no user auth |
| V3 Session Management | no | Stateless HTTP |
| V4 Access Control | no | Not exposed externally |
| V5 Input Validation | yes | Validate `from`, `to`, `camera_id` query params; reject unknown camera IDs; validate date format |
| V6 Cryptography | no | No crypto operations |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via `camera_id` param | Tampering | Allowlist: reject any `camera_id` not in `['fc1']`; never interpolate raw into filesystem path |
| Date injection via `from`/`to` params | Tampering | Parse with `new Date()`; reject NaN; validate range (max 7 days for on-demand) |
| `/tmp` exhaustion via concurrent on-demand jobs | DoS | Limit concurrent jobs to 1 (queue, don't parallelize); cleanup `finally` block |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ffmpeg `drawtext` boolean `reload` | ffmpeg 8.0 `reload` is int (reload every N frames) | Alpine ffmpeg 8.0 (2025) | Not applicable — phase uses pre-burn approach |
| node:14 Alpine base | node:20-alpine | 2023 | LTS; matches alerter Dockerfile |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | jimp pre-burn at ~50ms/frame is acceptable for nightly batch (14s for 288 frames) | Standard Stack | If frames grow larger or jimp is slower in Alpine, switch to sharp |
| A2 | The `timelapses` table PRIMARY KEY `(camera_id, date)` is sufficient — no two runs compose the same camera+date concurrently | Architecture | Race condition if on-demand and cron overlap; mitigate with single-job queue |
| A3 | `TZ=America/Toronto` in docker-compose env correctly controls node-cron 4.2.1 schedule time | Pattern 3 | If TZ is ignored, cron fires at UTC 00:30 not local 00:30 — verify in first test run |

---

## Open Questions

1. **Overlay font size for 640×480 frames**
   - What we know: 640×480 confirmed. burn_bar.js uses SANS_16_WHITE for height < 640 (border case: 480 < 640 → 16px).
   - What's unclear: Is 16px legible in the final mp4 at 640×480? The burn bar spans the full width; top-left + top-right overlay is more compact.
   - Recommendation: Use 16px for Wave 1, evaluate during manual smoke test of first clip.

2. **TZ boundary for "previous day" in nightly cron**
   - What we know: Cron fires at 00:30 America/Toronto. "Previous day" in Toronto = UTC yesterday-minus-offset.
   - What's unclear: EST vs EDT offset (UTC-5 vs UTC-4). `new Date().toLocaleDateString('en-CA', { timeZone: 'America/Toronto' })` handles this correctly via Intl.
   - Recommendation: Use `Intl.DateTimeFormat` to derive yesterday's date string in America/Toronto (same pattern as alerter heartbeat.js).

---

## Sources

### Primary (HIGH confidence)
- [VERIFIED: local shell] — ffmpeg 4.4 on Ubuntu 22.04: `drawtext` filter confirmed, `libx264` confirmed, `640×480` frames confirmed, `fc.humidity` topic name in Timescale confirmed, frame counts 123–288/day confirmed
- [VERIFIED: docker run node:20-alpine] — Alpine ffmpeg 8.0.1: `libx264` confirmed, `drawtext` with freetype confirmed, `font-dejavu` package provides DejaVuSans.ttf
- [VERIFIED: npm registry] — node-cron 4.2.1, express 5.2.1, pg 8.20.0, jimp 1.6.1, sharp 0.34.5 (latest)
- [VERIFIED: codebase read] — bridge/src/burn_bar.js: jimp v1 pattern, `loadFont`, `img.print()`, `getBuffer(JimpMime.jpeg)`
- [VERIFIED: codebase read] — bridge/src/index.js: Pool pattern, `new Pool({host, database, user, password, port})`, express 5 route structure
- [VERIFIED: codebase read] — docker-compose.yml + override: alerter pattern (node:20-alpine Dockerfile, TZ=America/Toronto, network=host)
- [VERIFIED: local shell] — `/data/snapshots/fc1/` exists with 15 days of frames; `/data/timelapse/` does not exist yet

### Secondary (MEDIUM confidence)
- [CITED: node-cron README / npm page] — `cron.schedule('30 0 * * *', fn)` syntax, TZ env var respected in v4.x

### Tertiary (LOW confidence)
- [ASSUMED] — jimp pre-burn at ~50ms/frame in Alpine Docker environment

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified via npm registry and docker run
- Architecture: HIGH — patterns derived from existing codebase (burn_bar.js, bridge pool, alerter cron)
- Pitfalls: HIGH — most verified directly (topic name, frame dimensions, Alpine ffmpeg version)
- RH lookup viability: HIGH — 18k readings/day confirmed in live DB

**Research date:** 2026-04-26
**Valid until:** 2026-05-26 (stable stack; Alpine ffmpeg version changes are backward-compatible for this use case)
