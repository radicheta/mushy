# Phase 23: Time-lapse composition (ffmpeg) — Pattern Map

**Mapped:** 2026-04-26
**Files analyzed:** 9 new files
**Analogs found:** 8 / 9

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/timelapse/Dockerfile` | config | — | `src/agents/alerter/Dockerfile` | exact |
| `src/timelapse/package.json` | config | — | `src/agents/alerter/package.json` | exact |
| `src/timelapse/jest.config.js` | config | — | `src/mission-control/bridge/jest.config.js` | exact |
| `src/timelapse/src/index.js` | service | request-response | `src/mission-control/bridge/src/index.js` | role-match |
| `src/timelapse/src/composer.js` | service | batch/transform | `src/mission-control/bridge/src/retention.js` | role-match |
| `src/timelapse/src/overlay.js` | utility | transform | `src/mission-control/bridge/src/burn_bar.js` | exact |
| `src/timelapse/src/db.js` | service | CRUD | `src/mission-control/bridge/src/index.js` (initDb + pool) | role-match |
| `src/timelapse/src/config.js` | utility | — | `src/agents/alerter/src/index.js` (load pattern) | partial |
| `docker-compose.yml` + `docker-compose.override.yml` | config | — | existing alerter service stanzas | exact |

---

## Pattern Assignments

### `src/timelapse/Dockerfile` (config)

**Analog:** `src/agents/alerter/Dockerfile` (lines 1–7)

**Dockerfile pattern** (lines 1–7):
```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev || npm install --omit=dev
COPY src/ ./src/
ENV NODE_ENV=production
CMD ["node", "src/index.js"]
```

**Timelapse delta — add ffmpeg and font before npm ci:**
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

---

### `src/timelapse/package.json` (config)

**Analog:** `src/agents/alerter/package.json` (full file)

**Package pattern:**
```json
{
  "name": "mushy-timelapse",
  "version": "0.1.0",
  "main": "src/index.js",
  "scripts": {
    "start": "node src/index.js",
    "test": "jest",
    "test:watch": "jest --watch"
  },
  "dependencies": {
    "express": "^5.2.1",
    "jimp": "^1.6.1",
    "node-cron": "^4.2.1",
    "pg": "^8.20.0"
  },
  "devDependencies": {
    "jest": "^29.7.0"
  }
}
```

---

### `src/timelapse/jest.config.js` (config)

**Analog:** `src/mission-control/bridge/jest.config.js` (full file, 6 lines)

**Jest config pattern** (copy verbatim):
```javascript
module.exports = {
  testEnvironment: 'node',
  testMatch: ['**/test/**/*.test.js'],
  testPathIgnorePatterns: ['/node_modules/'],
  verbose: true
};
```

---

### `src/timelapse/src/index.js` (service, request-response + cron)

**Analog:** `src/mission-control/bridge/src/index.js`

**Imports + pool pattern** (bridge/src/index.js lines 1–27):
```javascript
const express = require('express');
const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');

if (!process.env.TIMESCALE_PASSWORD) {
    console.error('[db] TIMESCALE_PASSWORD env var is required');
    process.exit(1);
}

const pool = new Pool({
    host: process.env.TIMESCALE_HOST || 'timescale',
    database: process.env.TIMESCALE_DB || 'postgres',
    user: process.env.TIMESCALE_USER || 'postgres',
    password: process.env.TIMESCALE_PASSWORD,
    port: 5432
});
```

**Alerter heartbeat TZ-aware date pattern** (heartbeat.js lines 32–48):
```javascript
// Intl formatter for TZ-aware date+hour extraction.
// 'en-CA' gives YYYY-MM-DD for date parts — easy string key.
const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: config.timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    hour12: false,
});

const parts = Object.fromEntries(
    fmt.formatToParts(new Date(nowMs)).map((p) => [p.type, p.value])
);
const day = `${parts.year}-${parts.month}-${parts.day}`;
```

**node-cron nightly trigger pattern** (from RESEARCH.md Pattern 3):
```javascript
const cron = require('node-cron');

cron.schedule('30 0 * * *', async () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    const dateStr = new Intl.DateTimeFormat('en-CA', {
        timeZone: process.env.TZ || 'America/Toronto',
        year: 'numeric', month: '2-digit', day: '2-digit'
    }).format(yesterday);
    try {
        await composeDay(dateStr, 'fc1', pool);
    } catch (e) {
        console.error('[cron] nightly composition failed:', e.message);
    }
});
```

**Async on-demand job pattern** (from RESEARCH.md Pattern 4):
```javascript
const jobs = new Map();  // jobId -> { status, file_path, error }

app.get('/timelapse', async (req, res) => {
    const { from, to, camera_id = 'fc1' } = req.query;
    const existing = await db.lookupTimelapse(pool, camera_id, from, to);
    if (existing) return res.json({ file_path: existing.file_path, duration_sec: existing.duration_sec });
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

---

### `src/timelapse/src/composer.js` (service, batch/transform)

**Analog:** `src/mission-control/bridge/src/retention.js`

**Batch pipeline module pattern** (retention.js lines 19–68 — note the injected deps signature):
```javascript
// Pure pipeline function — pool, fs, now injected for testability.
async function runPrune({
    pool, fs, now,
    retentionDays = DEFAULT_RETENTION_DAYS,
    graceDays = DEFAULT_GRACE_DAYS,
    batchLimit = DEFAULT_BATCH_LIMIT,
    rawDir = null,
    burntDir = null,
    log = console
}) {
    // ... early-exit guard ...
    // ... query ...
    // ... loop with try/catch per item ...
    // ... return { skipped, deleted, failed } ...
}
module.exports = { runPrune, ... };
```

**Apply same signature to composeDay:**
```javascript
async function composeDay(date, cameraId, pool, opts = {}) {
    // opts: { fps, workDir, outputDir, log }
    // 1. Query snapshots from Timescale
    // 2. Guard: < 3 frames → log warning, return { skipped: true }
    // 3. Batch RH lookup from telemetry
    // 4. Per-frame burnOverlay (jimp)
    // 5. Write concat filelist
    // 6. spawn ffmpeg (RESEARCH.md Pattern 2)
    // 7. fs.rename tmp → final path (atomic)
    // 8. insertTimelapse(pool, ...)
    // 9. cleanup workDir (try/finally)
    return { frames_used, duration_sec, file_path };
}
```

**ffmpeg spawn pattern** (from RESEARCH.md Pattern 2):
```javascript
const { spawn } = require('child_process');

async function runFfmpeg(filelistPath, outputPath, fps = 12) {
    return new Promise((resolve, reject) => {
        const args = [
            '-y', '-f', 'concat', '-safe', '0', '-i', filelistPath,
            '-c:v', 'libx264', '-crf', '23', '-preset', 'fast',
            '-pix_fmt', 'yuv420p', '-r', String(fps), outputPath
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

**Error handling pattern** (retention.js lines 44–55 — ENOENT-tolerant, per-item try/catch):
```javascript
for (const r of expired.rows) {
    try { await fs.promises.unlink(rawPath); }
    catch (e) {
        if (e.code !== 'ENOENT') {
            log.error('[retention] unlink failed for ' + rawPath + ': ' + e.message);
            failed++; continue;
        }
    }
}
```

---

### `src/timelapse/src/overlay.js` (utility, transform)

**Analog:** `src/mission-control/bridge/src/burn_bar.js` (full file, 59 lines)

**Imports pattern** (burn_bar.js lines 1–4):
```javascript
const { Jimp, JimpMime, loadFont } = require('jimp');
const fonts = require('jimp/fonts');
```

**Core jimp burn pattern** (burn_bar.js lines 28–57):
```javascript
async function burnBar(inputBuffer, barText) {
    const img = await Jimp.read(inputBuffer);
    const width = img.bitmap.width;
    const height = img.bitmap.height;
    const barH = Math.max(32, Math.round(height * 0.10));
    const barY = height - barH;

    const bar = new Jimp({ width, height: barH, color: 0x000000ff });
    bar.opacity(0.55);
    img.composite(bar, 0, barY);

    const fontKey = height >= 640 ? 'SANS_32_WHITE' : 'SANS_16_WHITE';
    const font = await loadFont(fonts[fontKey]);
    const lineHeight = (font.common && font.common.lineHeight) || (height >= 640 ? 32 : 16);
    const textY = barY + Math.max(0, Math.round((barH - lineHeight) / 2));

    img.print({ font, x: 8, y: textY, text: barText, maxWidth: width - 16 });
    return await img.getBuffer(JimpMime.jpeg, { quality: 85 });
}
```

**Adapt for overlay.js — top-left timestamp + top-right RH:**
```javascript
async function burnOverlay(inputBuffer, { timestamp, rh }) {
    const img = await Jimp.read(inputBuffer);
    const height = img.bitmap.height;
    const fontKey = height >= 640 ? 'SANS_32_WHITE' : 'SANS_16_WHITE';
    const font = await loadFont(fonts[fontKey]);

    // Top-left: timestamp as "YYYY-MM-DD HH:MM"
    img.print({ font, x: 8, y: 8, text: timestamp });

    // Top-right: RH (omit if null — gap over noise)
    if (rh !== null && rh !== undefined) {
        const rhText = `RH ${Number(rh).toFixed(1)}%`;
        img.print({ font, x: img.bitmap.width - 100, y: 8, text: rhText });
    }
    return await img.getBuffer(JimpMime.jpeg, { quality: 85 });
}
module.exports = { burnOverlay };
```

**Null-safe formatting pattern** (burn_bar.js lines 8–13):
```javascript
function fmtNum(v) {
    if (v === null || v === undefined) return '—';
    const n = Number(v);
    if (Number.isNaN(n)) return '—';
    return n.toFixed(1);
}
```

---

### `src/timelapse/src/db.js` (service, CRUD)

**Analog:** `src/mission-control/bridge/src/index.js` — `initDb()` function (lines 201–246)

**initDb pattern** (bridge/src/index.js lines 201–246):
```javascript
async function initDb() {
    try {
        await pool.query(`
            CREATE TABLE IF NOT EXISTS snapshots (
                captured_at TIMESTAMPTZ NOT NULL,
                camera_id   TEXT        NOT NULL,
                ...
            )
        `);
        await pool.query(`
            SELECT create_hypertable('snapshots', 'captured_at',
                if_not_exists       => TRUE,
                chunk_time_interval => INTERVAL '1 day'
            )
        `);
        await pool.query(`CREATE INDEX IF NOT EXISTS ...`);
        console.log('[db] Schema initialized');
    } catch (err) {
        console.error('[db] Schema init failed:', err.message);
        // Continue anyway
    }
}
```

**Apply to db.js — timelapses table:**
```javascript
async function initDb(pool) {
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
}

async function insertTimelapse(pool, { camera_id, date, file_path, frames_used, duration_sec }) {
    await pool.query(
        `INSERT INTO timelapses (camera_id, date, file_path, frames_used, duration_sec)
         VALUES ($1, $2, $3, $4, $5)
         ON CONFLICT (camera_id, date) DO UPDATE
           SET file_path=$3, frames_used=$4, composed_at=NOW(), duration_sec=$5`,
        [camera_id, date, file_path, frames_used, duration_sec]
    );
}

async function lookupTimelapse(pool, camera_id, date) {
    const r = await pool.query(
        `SELECT file_path, duration_sec FROM timelapses WHERE camera_id=$1 AND date=$2`,
        [camera_id, date]
    );
    return r.rows[0] || null;
}
```

**RH batch query** (from RESEARCH.md Pattern 5 — topic name corrected to `fc.humidity`):
```javascript
async function fetchRhForDay(pool, date) {
    const result = await pool.query(
        `SELECT captured_at, value FROM telemetry
         WHERE topic = 'fc.humidity'
           AND captured_at >= $1 AND captured_at < $2
         ORDER BY captured_at ASC`,
        [`${date}T00:00:00Z`, `${date}T23:59:59.999Z`]
    );
    return result.rows;
}
```

---

### `src/timelapse/src/config.js` (utility)

**Analog:** `src/agents/alerter/src/index.js` — env loading pattern (lines 28–31)

**Fail-fast env guard pattern** (bridge/src/index.js lines 14–18):
```javascript
if (!process.env.TIMESCALE_PASSWORD) {
    console.error('[db] TIMESCALE_PASSWORD env var is required');
    process.exit(1);
}
```

**Config module pattern:**
```javascript
function load(env = process.env) {
    if (!env.TIMESCALE_PASSWORD) {
        console.error('[config] TIMESCALE_PASSWORD is required');
        process.exit(1);
    }
    return {
        timescaleHost:     env.TIMESCALE_HOST || 'timescale',
        timescaleDb:       env.TIMESCALE_DB || 'postgres',
        timescaleUser:     env.TIMESCALE_USER || 'postgres',
        timescalePassword: env.TIMESCALE_PASSWORD,
        snapshotDir:       env.SNAPSHOT_DIR || '/data/snapshots',
        timelapseDir:      env.TIMELAPSE_DIR || '/data/timelapse',
        cameraId:          env.CAMERA_ID || 'fc1',
        fps:               parseInt(env.TIMELAPSE_FPS || '12', 10),
        timezone:          env.TZ || 'America/Toronto',
        port:              parseInt(env.PORT || '8888', 10),
    };
}
module.exports = { load };
```

---

### `docker-compose.yml` and `docker-compose.override.yml` modifications

**Analog:** existing `alerter` and `farmos-agent` service stanzas in both files

**Base compose stanza pattern** (docker-compose.yml — farmos-agent lines 46–64):
```yaml
  farmos-agent:
    build:
      context: ./src/farmos-agent
      dockerfile: Dockerfile
    depends_on:
      - timescale
      - bridge
    environment:
      - TIMESCALE_HOST=localhost
      - TIMESCALE_PASSWORD=${TIMESCALE_PASSWORD}
      - TZ=America/Toronto
    volumes:
      - /data/snapshots:/data/snapshots:ro
    restart: unless-stopped
```

**New timelapse stanza for docker-compose.yml (template):**
```yaml
  timelapse:
    build:
      context: ./src/timelapse
      dockerfile: Dockerfile
    depends_on:
      - timescale
    environment:
      - TIMESCALE_HOST=localhost
      - TIMESCALE_PASSWORD=${TIMESCALE_PASSWORD}
      - SNAPSHOT_DIR=/data/snapshots
      - TIMELAPSE_DIR=/data/timelapse
      - CAMERA_ID=fc1
      - TIMELAPSE_FPS=${TIMELAPSE_FPS:-12}
      - TZ=America/Toronto
    volumes:
      - /data/snapshots:/data/snapshots:ro
      - /data/timelapse:/data/timelapse
    restart: unless-stopped
```

**Override stanza pattern** (docker-compose.override.yml — alerter lines 38–67):
```yaml
# alerter uses signal-net and extra_hosts; timelapse needs host networking for Timescale
  timelapse:
    network_mode: "host"
```

---

## Shared Patterns

### Pool Construction
**Source:** `src/mission-control/bridge/src/index.js` lines 21–27
**Apply to:** `src/timelapse/src/db.js`, `src/timelapse/src/index.js`
```javascript
const pool = new Pool({
    host: process.env.TIMESCALE_HOST || 'timescale',
    database: process.env.TIMESCALE_DB || 'postgres',
    user: process.env.TIMESCALE_USER || 'postgres',
    password: process.env.TIMESCALE_PASSWORD,
    port: 5432
});
```

### Fail-Fast Env Guard
**Source:** `src/mission-control/bridge/src/index.js` lines 14–18
**Apply to:** `src/timelapse/src/config.js`
```javascript
if (!process.env.TIMESCALE_PASSWORD) {
    console.error('[db] TIMESCALE_PASSWORD env var is required');
    process.exit(1);
}
```

### mkdirSync Recursive
**Source:** `src/mission-control/bridge/src/index.js` lines 148–149
**Apply to:** `src/timelapse/src/composer.js` (output dir + tmp work dir)
```javascript
fs.mkdirSync(dir, { recursive: true });
```

### jimp Buffer Round-Trip
**Source:** `src/mission-control/bridge/src/burn_bar.js` lines 29 + 56
**Apply to:** `src/timelapse/src/overlay.js`
```javascript
const img = await Jimp.read(inputBuffer);
// ... mutations ...
return await img.getBuffer(JimpMime.jpeg, { quality: 85 });
```

### Module Exports Pattern (pure functions + constants)
**Source:** `src/mission-control/bridge/src/retention.js` lines 71–74
**Apply to:** `src/timelapse/src/composer.js`, `src/timelapse/src/overlay.js`, `src/timelapse/src/db.js`
```javascript
module.exports = {
    clampRetentionDays, shouldPrune, runPrune,
    DEFAULT_RETENTION_DAYS, DEFAULT_GRACE_DAYS, MIN_RETENTION_DAYS
};
```

### Test File Structure
**Source:** `src/mission-control/bridge/test/burn_bar.test.js`
**Apply to:** `src/timelapse/test/*.test.js`
```javascript
const { functionUnderTest } = require('../src/module');

describe('functionUnderTest', () => {
    test('specific behavior', () => {
        // Arrange → Act → Assert
        expect(result).toBe(expected);
    });

    test('async case', async () => {
        const out = await functionUnderTest(input);
        expect(Buffer.isBuffer(out)).toBe(true);
    });
});
```

### TZ-Aware Date Extraction
**Source:** `src/agents/alerter/src/heartbeat.js` lines 32–48
**Apply to:** `src/timelapse/src/index.js` (nightly cron — compute "previous day" in America/Toronto)
```javascript
const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: config.timezone,
    year: 'numeric', month: '2-digit', day: '2-digit',
});
// Returns 'YYYY-MM-DD' string in local TZ
const dateStr = fmt.format(new Date());
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/timelapse/src/composer.js` (ffmpeg spawn portion) | service | batch/transform | No existing ffmpeg invocation in the codebase — use RESEARCH.md Pattern 2 |

Note: The overall `composer.js` module structure has analogs (`retention.js`), but the ffmpeg child_process.spawn section is novel to this codebase. RESEARCH.md Pattern 2 (verified recipe) is the reference.

---

## Metadata

**Analog search scope:** `src/mission-control/bridge/src/`, `src/agents/alerter/src/`, `docker-compose.yml`, `docker-compose.override.yml`
**Files scanned:** 9 (burn_bar.js, index.js, retention.js, alerter/index.js, alerter/heartbeat.js, alerter/Dockerfile, bridge/Dockerfile, bridge/jest.config.js, alerter/package.json)
**Pattern extraction date:** 2026-04-26
