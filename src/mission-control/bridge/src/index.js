const http = require('http');
const express = require('express');
const WebSocket = require('ws');
const rclnodejs = require('rclnodejs');
const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');
const { decideSource } = require('./snapshot_helpers');
const retention = require('./retention');
const migration = require('./schema_migration');
const { validateHistoryParams } = require('./history_validate');
const { validateFrameParams } = require('./frame_validate');
const { burnBar, formatBarText } = require('./burn_bar');
const buffer_replay = require('./buffer_replay');
const control_param = require('./control_param');
const control_persist = require('./control_persist');
const control_experiment = require('./control_experiment');
const { markFc1Active, getFc1LastMsgTs, getFc1LastMsgAgeSec } = require('./fc1_liveness');
const fc_derived = require('./fc_derived');

// Fail fast if database password is not configured
if (!process.env.TIMESCALE_PASSWORD) {
    console.error('[db] TIMESCALE_PASSWORD env var is required');
    process.exit(1);
}

// PostgreSQL connection pool
const pool = new Pool({
    host: process.env.TIMESCALE_HOST || 'timescale',
    database: process.env.TIMESCALE_DB || 'postgres',
    user: process.env.TIMESCALE_USER || 'postgres',
    password: process.env.TIMESCALE_PASSWORD,
    port: 5432
});

// MUSHY-110: an IDLE pooled client that errors has no query to reject, so pg
// surfaces it as an 'error' event on the pool -- and an unhandled 'error' on an
// EventEmitter terminates the process. Without this handler a Timescale restart
// (or failover, or pg_terminate_backend, or an idle timeout) kills the bridge:
// that is what happened on the 2026-08-24 reboot, 'terminating connection due to
// administrator command'. Docker restarted us, but the bridge needs ~4 minutes to
// come back to listening, and the chamber alerter has no frame source for all of
// it. Log and let the pool discard the dead client; the next query checks out a
// fresh one. Deliberately does NOT touch dbReady -- that flag is set once at
// startup and never re-armed, so clearing it here would turn a transient blip
// into a permanent 503 on every DB route.
pool.on('error', (err) => {
    console.error('[db] idle client error (pool will discard it):', err.message);
});

// Track DB availability — live WS continues even if DB is down
let dbReady = false;

// Phase 16: liveness tracking for health panel
let rosReady = false;              // flips true once rclnodejs.init().then() completes
let humidifierLastMsgTs = null;    // ms epoch of most recent /fc1/actuators/humidifier

// Phase 18: latest-value cache for GET /farmer/summary
// Each entry is { value, timestamp } or null. Humidifier stores 0|1.
const latestTelemetry = {
    humidity: null,
    temperature: null,
    co2: null,
    humidifier: null,
    // Derived (computed from temperature + humidity in emitDerived); not from a sensor.
    vpd: null,
    water_vapor: null
};

// Camera MJPEG streaming state
const BOUNDARY = 'frameboundary';
const mjpegClients = new Set();
let latestFrame = null;
let lastFrameTime = null;
const FRAME_MAX_AGE_MS = 2 * 60 * 60 * 1000; // 2 hours

function isFrameStale() {
    return !latestFrame || !lastFrameTime || (Date.now() - lastFrameTime > FRAME_MAX_AGE_MS);
}

// Camera ROS2 subscription — conditional on MJPEG client presence (Phase 12)
let cameraSubscription = null;
let rosNode = null;  // set inside rclnodejs.init().then()

// Phase 21 D-01: keep ROS subscription alive for continuous persistence regardless of viewers.
// Flipped true after initDb + ROS ready in the startup block.
let persistenceKeepalive = false;

// Snapshot config from environment
const SNAPSHOT_DIR = process.env.SNAPSHOT_DIR || '/data/snapshots';
// Phase 22 D-03: burnt-twin root. MUST differ from SNAPSHOT_DIR (guard below) to
// prevent the burnt write from overwriting the raw file on disk.
const SNAPSHOT_BURNT_DIR = process.env.SNAPSHOT_BURNT_DIR || '/data/snapshots-burnt';
if (SNAPSHOT_BURNT_DIR === SNAPSHOT_DIR) {
    console.error('[camera/burnt] SNAPSHOT_BURNT_DIR must differ from SNAPSHOT_DIR');
    process.exit(1);
}
const SNAPSHOT_INTERVAL_MS = parseInt(process.env.SNAPSHOT_INTERVAL_MIN || '15', 10) * 60 * 1000;
const CAMERA_ID = process.env.CAMERA_ID || 'fc1';

// Phase 21 D-04: retention config. clampRetentionDays enforces MIN_RETENTION_DAYS=30
// (Pitfall 2 belt-and-suspenders) before runPrune's 30-day grace guard kicks in.
const RETENTION_DAYS = retention.clampRetentionDays(process.env.RETENTION_DAYS || retention.DEFAULT_RETENTION_DAYS);
const RETENTION_GRACE_DAYS = parseInt(process.env.RETENTION_GRACE_DAYS || retention.DEFAULT_GRACE_DAYS, 10);
const PRUNE_INTERVAL_MS = 24 * 3600 * 1000;

// Phase 21 D-06a: /camera/history bounds (match /history/:topic precedent + scrubber cap)
const HISTORY_MAX_ROWS = 5000;
const HISTORY_MAX_RANGE_MS = 30 * 24 * 3600000;

// Phase 22 D-02: closest-at-or-before tolerance window.
// Frames outside 2x SNAPSHOT_INTERVAL_MS are considered "no coverage in this window"
// -> 404 so farmOS renders "no frame in this window" (gap over noise).
const FRAME_TOLERANCE_MS = 2 * SNAPSHOT_INTERVAL_MS;

function pushFrame(jpegBuffer) {
    latestFrame = jpegBuffer;
    lastFrameTime = Date.now();
    const header = [
        `--${BOUNDARY}`,
        'Content-Type: image/jpeg',
        `Content-Length: ${jpegBuffer.length}`,
        '',
        ''
    ].join('\r\n');

    mjpegClients.forEach(res => {
        if (!res.writable) {
            mjpegClients.delete(res);
            return;
        }
        try {
            res.write(header, 'ascii');
            res.write(jpegBuffer);
            res.write('\r\n', 'ascii');
        } catch (e) {
            mjpegClients.delete(res);
        }
    });
}

function ensureCameraSubscribed() {
    if (cameraSubscription !== null || rosNode === null) return;
    cameraSubscription = rosNode.createSubscription(
        'sensor_msgs/msg/CompressedImage',
        '/fc1/camera/compressed',
        (msg) => {
            const buf = Buffer.from(msg.data);
            pushFrame(buf);
        }
    );
    console.log('[camera] subscribed to /fc1/camera/compressed');
}

function maybeCameraUnsubscribe() {
    if (mjpegClients.size > 0 || persistenceKeepalive || cameraSubscription === null) return;
    rosNode.destroySubscription(cameraSubscription);
    cameraSubscription = null;
    console.log('[camera] unsubscribed from /fc1/camera/compressed');
}

function saveSnapshot() {
    // Phase 21 Pitfall 1: refuse to persist stale frames. isFrameStale covers
    // the null-latestFrame case too, so the old `if (!latestFrame) return` is redundant.
    if (isFrameStale()) {
        console.log('[camera] snapshot skipped — frame is stale or missing');
        return;
    }
    const capturedAt = new Date();
    const bytes = latestFrame.length;
    const source = decideSource(mjpegClients.size);
    const dateDir = capturedAt.toISOString().slice(0, 10);
    const dir = path.join(SNAPSHOT_DIR, CAMERA_ID, dateDir);
    fs.mkdirSync(dir, { recursive: true });
    const filename = `${capturedAt.toISOString().replace(/[:.]/g, '-')}.jpg`;
    const filepath = path.join(dir, filename);
    // Phase 22 D-03: pin the raw buffer reference NOW. latestFrame may rotate by the
    // time burnBar resolves (threat T-22-09 mitigation via snapshot pin).
    const rawBuf = latestFrame;
    fs.writeFile(filepath, latestFrame, async (err) => {
        if (err) {
            console.error('[camera] snapshot write failed:', err.message);
            return;
        }
        console.log(`[camera] snapshot saved: ${filepath} (${source}, ${bytes} bytes)`);

        // Phase 22 D-03: fire-and-forget burnt twin. Errors logged, never block raw
        // write or DB insert. No await on the IIFE — the callback chain continues
        // regardless of burn outcome.
        const burntDir = path.join(SNAPSHOT_BURNT_DIR, CAMERA_ID, dateDir);
        const burntPath = path.join(burntDir, filename);
        const barText = formatBarText({
            capturedAt,
            rh:   latestTelemetry.humidity?.value,
            temp: latestTelemetry.temperature?.value,
            co2:  latestTelemetry.co2?.value,
            hum:  latestTelemetry.humidifier?.value
        });
        (async () => {
            try {
                fs.mkdirSync(burntDir, { recursive: true });
                const burnt = await burnBar(rawBuf, barText);
                fs.writeFile(burntPath, burnt, (werr) => {
                    if (werr) console.error('[camera/burnt] write failed:', werr.message);
                });
            } catch (e) {
                console.error('[camera/burnt] burn failed:', e.message);
            }
        })();

        if (!dbReady) return;
        try {
            await pool.query(
                `INSERT INTO snapshots (captured_at, camera_id, file_path, bytes, source, fps)
                 VALUES ($1, $2, $3, $4, $5, $6)`,
                [capturedAt, CAMERA_ID, filepath, bytes, source, null]
            );
        } catch (e) {
            // File exists on disk but row missing — retention sweep will eventually
            // orphan-cleanup. See RESEARCH.md §Pattern 3 note.
            console.error('[snapshots] insert failed:', e.message);
        }
    });
}

// Schema init: create telemetry hypertable on startup
async function initDb() {
    try {
        await pool.query(`
            CREATE TABLE IF NOT EXISTS telemetry (
                time   TIMESTAMPTZ      NOT NULL,
                topic  TEXT             NOT NULL,
                value  DOUBLE PRECISION NOT NULL
            )
        `);
        await pool.query(`
            SELECT create_hypertable('telemetry', 'time',
                if_not_exists        => TRUE,
                chunk_time_interval  => INTERVAL '1 day'
            )
        `);
        await pool.query(`
            CREATE INDEX IF NOT EXISTS idx_telemetry_topic_time
            ON telemetry (topic, time DESC)
        `);
        // Phase 999.1 Plan 01: pre-flight dedupe scan + idempotent UNIQUE constraint.
        // Backfill in Plan 03 uses ON CONFLICT (topic, time) DO NOTHING which requires this constraint.
        const dupes = await migration.findTopicTimeDuplicates(pool, 5);
        if (dupes.length > 0) {
            console.error('[db] BLOCKING: telemetry has duplicate (topic, time) rows; cannot add UNIQUE. First few:', dupes);
            throw new Error('telemetry duplicates present — manual dedupe required before UNIQUE migration');
        }
        await migration.applyTelemetryUniqueConstraint(pool);
        console.log('[db] telemetry_topic_time_unique constraint ensured');
        await pool.query(`
            CREATE TABLE IF NOT EXISTS snapshots (
                captured_at TIMESTAMPTZ NOT NULL,
                camera_id   TEXT        NOT NULL,
                file_path   TEXT        NOT NULL,
                bytes       INTEGER     NOT NULL,
                source      TEXT        NOT NULL CHECK (source IN ('viewer','idle','manual')),
                fps         NUMERIC
            )
        `);
        await pool.query(`
            SELECT create_hypertable('snapshots', 'captured_at',
                if_not_exists        => TRUE,
                chunk_time_interval  => INTERVAL '1 day'
            )
        `);
        await pool.query(`
            CREATE INDEX IF NOT EXISTS idx_snapshots_camera_captured
            ON snapshots (camera_id, captured_at DESC)
        `);
        // Phase 31 D-21: idempotent fc_experiments table + index. Runs on
        // every bridge boot; no-op if the table already exists.
        await control_experiment.migrateExperimentSchema(pool);
        console.log('[db] fc_experiments schema ensured');
        console.log('[db] Schema initialized');
    } catch (err) {
        console.error('[db] Schema init failed:', err.message);
        // Continue anyway — live WS still works without DB
    }
}

// HTTP + WebSocket on single port (avoids extra docker-compose port mapping)
const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

// CORS — restrict to the configured OpenMCT origin(s). Accepts either a
// single origin or a comma-separated list (T-07-04 — still an allowlist,
// no wildcards, no reflection of arbitrary origins).
const CORS_ALLOWED = (process.env.CORS_ORIGIN || 'http://localhost:8080')
    .split(',')
    .map(s => s.trim())
    .filter(Boolean);
app.use((req, res, next) => {
    const origin = req.headers.origin;
    if (origin && CORS_ALLOWED.includes(origin)) {
        res.setHeader('Access-Control-Allow-Origin', origin);
        res.setHeader('Vary', 'Origin');
    }
    next();
});

// Health check route — Phase 14 adds last_frame_age_sec (HFIX-03).
// Server-side age avoids client clock-skew; null when no frame has ever arrived.
// Phase 21 D-06b: adds snapshots.{last_24h, oldest_at} + flat aliases for the
// Mission Control "Snapshots" chip. DB failures are swallowed — /health always
// returns 200 (gap-over-noise: chip goes grey, not a 5xx).
app.get('/health', async (req, res) => {
    const lastFrameAgeSec = lastFrameTime === null
        ? null
        : Math.round((Date.now() - lastFrameTime) / 1000);

    let snapshotsLast24h = null;
    let oldestSnapshotAt = null;
    if (dbReady) {
        try {
            const [countRow, oldestRow] = await Promise.all([
                pool.query("SELECT COUNT(*)::int AS n FROM snapshots WHERE captured_at > NOW() - INTERVAL '24 hours'"),
                pool.query("SELECT MIN(captured_at) AS oldest FROM snapshots")
            ]);
            snapshotsLast24h = countRow.rows[0].n;
            oldestSnapshotAt = oldestRow.rows[0].oldest === null
                ? null
                : oldestRow.rows[0].oldest.toISOString();
        } catch (e) {
            console.error('[health] snapshots stats failed:', e.message);
        }
    }

    res.json({
        status: 'ok',
        db: dbReady,
        ros: {
            connected: rosReady
        },
        camera: {
            lastFrame: lastFrameTime,               // ms epoch or null — existing consumers
            last_frame_age_sec: lastFrameAgeSec,    // Phase 14 HFIX-03: integer seconds or null
            clients: mjpegClients.size,
            subscribed: cameraSubscription !== null
        },
        humidifier: {
            last_msg_ts: humidifierLastMsgTs
        },
        // Phase 46 Plan 01 (CD-01 / CD-04): expose fc1LastMsgTs -- the
        // aggregate liveness signal computed by the fc1_liveness module
        // across the 9 subscribed fc1 data/state topics. Alerter (plan
        // 46-02) consumes last_msg_age_sec as a third OR-trigger for
        // isPiOffline. Per CONTEXT.md D-01, fc1LastMsgTs lives in the
        // shared helper (markFc1Active) instead of inline module state;
        // semantics are identical to a top-level `let fc1LastMsgTs`.
        fc1: {
            last_msg_ts: getFc1LastMsgTs(),
            last_msg_age_sec: getFc1LastMsgAgeSec()
        },
        snapshots: { last_24h: snapshotsLast24h, oldest_at: oldestSnapshotAt },
        snapshots_last_24h: snapshotsLast24h,
        oldest_snapshot_at: oldestSnapshotAt
    });
});

// Phase 18: farmer dashboard read-only snapshot.
// Consumed by the farmOS-hosted farmer UI (delegated to Zoy-side). Shape is
// stable-by-convention; breaking changes require a farmOS-side sync first.
app.get('/farmer/summary', (req, res) => {
    const lastFrameAgeSec = lastFrameTime === null
        ? null
        : Math.round((Date.now() - lastFrameTime) / 1000);
    res.json({
        chamber_id: CAMERA_ID,
        timestamp: Date.now(),
        sensors: {
            humidity: latestTelemetry.humidity,       // { value, timestamp } | null
            temperature: latestTelemetry.temperature,
            co2: latestTelemetry.co2
        },
        actuators: {
            humidifier: latestTelemetry.humidifier    // { value: 0|1, timestamp } | null
        },
        sensor_health: lastSensorHealthBroadcast === null
            ? null
            : lastSensorHealthBroadcast.sensor_health,
        camera: {
            last_frame_age_sec: lastFrameAgeSec,
            subscribed: cameraSubscription !== null
        }
    });
});

// Allowlist for history endpoint topics — prevents SQL injection via topic param (T-07-04)
const ALLOWED_TOPICS = ['fc.humidity', 'fc.temperature', 'fc.co2', 'fc.humidifier', 'fc.humidity_2', 'fc.temperature_2',
                         'fc.humidifier_duty', 'fc.humidity_target', 'fc.pid_output',
                         'fc.vpd', 'fc.water_vapor'];

// Server-side downsampling: choose bucket interval based on requested time range (D-06)
// <=2h -> ~1440 pts at 5s; <=24h -> ~1440 pts at 1min; <=7d -> ~1008 pts at 10min; >7d -> 1hr
function bucketInterval(rangeMs) {
    const ONE_HOUR = 3600000;
    if (rangeMs <= 2  * ONE_HOUR)  return '5 seconds';
    if (rangeMs <= 24 * ONE_HOUR)  return '1 minute';
    if (rangeMs <= 7  * 24 * ONE_HOUR) return '10 minutes';
    return '1 hour';
}

// History endpoint — returns downsampled time-series for OpenMCT request() (D-04)
app.get('/history/:topic', async (req, res) => {
    const { topic } = req.params;

    // Validate topic against allowlist (prevents SQL injection via topic — T-07-04)
    if (!ALLOWED_TOPICS.includes(topic)) {
        return res.status(400).json({ error: 'Invalid topic' });
    }

    const start = parseInt(req.query.start, 10);
    const end   = parseInt(req.query.end,   10);
    if (isNaN(start) || isNaN(end)) {
        return res.status(400).json({ error: 'start and end query params required (ms epoch)' });
    }

    // Cap max range at 30 days to prevent unbounded queries (T-07-05 mitigation)
    const MAX_RANGE = 30 * 24 * 3600000;
    if (end - start > MAX_RANGE) {
        return res.status(400).json({ error: 'Max range is 30 days' });
    }

    if (!dbReady) {
        return res.status(503).json({ error: 'Database not available' });
    }

    const rangeMs  = end - start;
    const interval = bucketInterval(rangeMs);

    try {
        const result = await pool.query(
            `SELECT time_bucket($1::interval, time) AS bucket,
                    AVG(value) AS value
             FROM telemetry
             WHERE topic = $2
               AND time >= $3
               AND time <= $4
             GROUP BY bucket
             ORDER BY bucket ASC`,
            [interval, topic, new Date(start), new Date(end)]
        );
        const datums = result.rows.map(row => ({
            value: parseFloat(row.value),
            utc:   new Date(row.bucket).getTime()
        }));
        res.json(datums);
    } catch (err) {
        console.error('[db] history query failed:', err.message);
        res.status(500).json({ error: 'Query failed' });
    }
});

// Phase 21 D-06a: read-only camera history index for Phase 22 scrubber consumption.
app.get('/camera/history', async (req, res) => {
    const v = validateHistoryParams(req.query, CAMERA_ID, HISTORY_MAX_RANGE_MS);
    if (!v.ok) return res.status(v.status).json({ error: v.error });
    if (!dbReady) return res.status(503).json({ error: 'Database not available' });
    const { from, to, cameraId, fromIso, toIso } = v.parsed;
    try {
        const result = await pool.query(
            "SELECT captured_at, camera_id, file_path, bytes, source, fps " +
            "FROM snapshots " +
            "WHERE camera_id = $1 AND captured_at >= $2 AND captured_at <= $3 " +
            "ORDER BY captured_at ASC LIMIT $4",
            [cameraId, new Date(from), new Date(to), HISTORY_MAX_ROWS + 1]
        );
        const hasMore = result.rows.length > HISTORY_MAX_ROWS;
        const rows = hasMore ? result.rows.slice(0, HISTORY_MAX_ROWS) : result.rows;
        res.json({
            camera_id: cameraId,
            from: fromIso,
            to: toIso,
            count: rows.length,
            has_more: hasMore,
            items: rows.map(r => ({
                captured_at: r.captured_at.toISOString(),
                camera_id: r.camera_id,
                file_path: r.file_path,
                bytes: r.bytes,
                source: r.source,
                fps: r.fps === null ? null : parseFloat(r.fps)
            }))
        });
    } catch (err) {
        console.error('[snapshots] history query failed:', err.message);
        res.status(500).json({ error: 'Query failed' });
    }
});

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
        // Path derivation: DB stores raw path; burnt twin = same filename under SNAPSHOT_BURNT_DIR.
        // raw=true -> serve as-stored. Default -> swap root dir.
        // Safety: only strip the SNAPSHOT_DIR prefix if file_path actually starts with it
        // (defense-in-depth against a rogue DB row inserted outside the managed tree).
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
                // Frames are immutable once written — safe to cache aggressively.
                // Use the captured_at as implicit versioning via the `at` query.
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

// Camera MJPEG stream endpoint (D-03)
app.get('/camera/mjpeg', (req, res) => {
    res.writeHead(200, {
        'Content-Type': `multipart/x-mixed-replace; boundary="${BOUNDARY}"`,
        'Cache-Control': 'no-cache, no-store',
        'Connection': 'close',
        'Pragma': 'no-cache'
    });
    mjpegClients.add(res);
    ensureCameraSubscribed();
    console.log(`[camera] MJPEG client connected (${mjpegClients.size} total)`);
    req.on('close', () => {
        mjpegClients.delete(res);
        maybeCameraUnsubscribe();
        console.log(`[camera] MJPEG client disconnected (${mjpegClients.size} total)`);
    });
});

// Camera latest frame endpoint (single JPEG for testing)
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

// Alias for /camera/snapshot — used by farmos_agent daily report (D-05)
app.get('/camera/latest.jpg', (req, res) => {
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

// Phase 28 D-17 Layer 1: runtime param tuning hot path.
// Implementation lives entirely in src/control_param.js (Pitfall 8 — keep the
// buffer-replay path at index.js:613 untouched). The rosNode used here is the
// same instance the buffer-replay / telemetry subscribers spin; it's set inside
// rclnodejs.init().then() below, so a thin wrapper reads it lazily at request time.
app.post('/control/param', express.json(), async (req, res) => {
    if (!rosNode) {
        return res.status(503).json({ error: 'rclnodejs not ready' });
    }
    const handler = control_param.makeHandler(rosNode, { timeoutMs: 3000 });
    return handler(req, res);
});

// Phase 28 D-17 Layer 2: explicit Save-to-repo (D-19). Separate endpoint from
// /control/param so the farmOS UI surfaces it as an explicit button, not an
// auto-debounced side effect of every slider drag. Transport locked in
// 28-01-SPIKE.md §C / D-B1: fc_buffer HTTP relay (bridge container has no ssh
// binary; fc_buffer already runs on fc1 and owns /var/lib/fc-core/).
const persistTransport = control_persist.makeHttpTransport({});
app.post('/control/persist', express.json(), control_persist.makeHandler(persistTransport, {}));

// Phase 31 D-18: experiment trigger + cancel + state endpoints.
// rosNode is set inside rclnodejs.init().then() below; the lazy wrapper-at-
// request-time pattern matches /control/param.
app.post('/control/experiment', express.json(), async (req, res) => {
    if (!rosNode) return res.status(503).json({ error: 'rclnodejs not ready' });
    const handler = control_experiment.makeStartHandler(rosNode, { timeoutMs: 5000 });
    return handler(req, res);
});
app.post('/control/cancel-experiment', express.json(), async (req, res) => {
    if (!rosNode) return res.status(503).json({ error: 'rclnodejs not ready' });
    const handler = control_experiment.makeCancelHandler(rosNode, { timeoutMs: 5000 });
    return handler(req, res);
});
app.get('/control/experiment', (req, res) => {
    const handler = control_experiment.makeStateHandler({
        // Cache shape stored in lastExperimentEventBroadcast is the wrapped
        // {topic, value} envelope; unwrap to the inner JSON the handler expects.
        getLastEvent: () => (lastExperimentEventBroadcast && lastExperimentEventBroadcast.value) || null,
    });
    return handler(req, res);
});

// Phase 33 D-09: heartbeat alert relay. VPS heartbeat receiver POSTs here
// over wg-hub when a monitored source (fc1, elder-plops, …) goes silent.
// Bridge forwards to signal-cli on host loopback (127.0.0.1:8085, mapped from
// the signal-cli compose container; see docker-compose.override.yml).
// Mirrors src/agents/alerter/src/signal.js POST shape (/v2/send).
const HEARTBEAT_SIGNAL_URL = process.env.SIGNAL_API_URL || 'http://localhost:8085';
const HEARTBEAT_SIGNAL_SENDER = process.env.SIGNAL_SENDER;
const HEARTBEAT_SIGNAL_RECIPIENT = process.env.SIGNAL_RECIPIENT;
app.post('/heartbeat-alert', express.json(), async (req, res) => {
    const { source, message } = req.body || {};
    if (!source || !message) {
        return res.status(400).json({ ok: false, error: 'source and message required' });
    }
    if (!HEARTBEAT_SIGNAL_SENDER || !HEARTBEAT_SIGNAL_RECIPIENT) {
        console.error('[heartbeat-alert] SIGNAL_SENDER/SIGNAL_RECIPIENT not configured');
        return res.status(503).json({ ok: false, error: 'signal not configured' });
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
        const r = await fetch(`${HEARTBEAT_SIGNAL_URL}/v2/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message,
                number: HEARTBEAT_SIGNAL_SENDER,
                recipients: [HEARTBEAT_SIGNAL_RECIPIENT],
            }),
            signal: ctrl.signal,
        });
        if (!r.ok) {
            const text = await r.text().catch(() => '');
            console.error(`[heartbeat-alert] signal-cli ${r.status}: ${text.slice(0, 200)}`);
            return res.status(502).json({ ok: false, error: `signal-cli ${r.status}` });
        }
        const json = await r.json().catch(() => ({}));
        console.log(`[heartbeat-alert] dispatched source=${source} (${message.length} chars)`);
        return res.json({ ok: true, timestamp: json.timestamp || Date.now() });
    } catch (e) {
        console.error(`[heartbeat-alert] dispatch failed: ${e.message}`);
        return res.status(502).json({ ok: false, error: e.message });
    } finally {
        clearTimeout(timer);
    }
});

// Store connected WebSocket clients
const clients = new Set();

// Phase 16.1: cache last sensor_health broadcast so new WS clients see current state
// before the next fc_controller state transition (addresses grey-until-tick UX).
let lastSensorHealthBroadcast = null;

// Phase 29-02: cache last mode + alerter Tier B/C config broadcasts for on-connect
// replay so freshly-connecting WS clients (notably the alerter) see current
// state within one handshake without waiting for the next controller publish.
let lastModeBroadcast = null;
let lastAlerterModeOverridesBroadcast = null;
let lastAlerterGlobalsBroadcast = null;

// Phase 31 D-22: cache last experiment_event broadcast for on-connect replay
// (mirrors lastModeBroadcast pattern). null when no experiment has fired
// since bridge boot. Populated from /fc1/control/experiment_event subscriber
// in the rclnodejs.init().then() block below.
let lastExperimentEventBroadcast = null;

wss.on('connection', (ws) => {
    console.log('[bridge] Client connected');
    clients.add(ws);

    if (lastSensorHealthBroadcast && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(lastSensorHealthBroadcast));
    }
    if (lastModeBroadcast && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(lastModeBroadcast));
    }
    if (lastAlerterModeOverridesBroadcast && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(lastAlerterModeOverridesBroadcast));
    }
    if (lastAlerterGlobalsBroadcast && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(lastAlerterGlobalsBroadcast));
    }
    // Phase 31 D-22: replay cached experiment_event so a tab opened mid-flight
    // sees current experiment state without waiting for the next state change.
    if (lastExperimentEventBroadcast && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(lastExperimentEventBroadcast));
    }

    ws.on('close', () => {
        console.log('[bridge] Client disconnected');
        clients.delete(ws);
    });
});

// Broadcast data to all connected WebSocket clients
function broadcast(data) {
    const payload = JSON.stringify(data);
    clients.forEach((client) => {
        if (client.readyState === WebSocket.OPEN) {
            client.send(payload);
        }
    });
}

// Insert a telemetry row — never throws; DB errors are logged only.
// Phase 999.1 Plan 03: tsMs/tsNs are optional. When passed, tsMs is written to
// the time column instead of new Date() (so backfilled rows from buffer_replay
// land at their original DDS timestamp). Live ON CONFLICT DO NOTHING is
// required because backfill races with live inserts when reconnect happens
// mid-second (the unique constraint added in Plan 01 would otherwise raise on
// the live insert too).
//
// 999.36 fix (2026-05-11): live-insert cursor advance REMOVED. The original
// "advance on every successful insert" was an optimization to skip the 24h
// buffer on cold start, but it defeated reconnect-replay during the exact
// scenario buffer_replay was designed for: bridge reconnects after a long
// gap, the first live message (timestamped *now*) jumped the cursor past the
// entire gap, and the next /telemetry/since poll asked fc_buffer for
// "newer than now" — getting only the latest 3 rows. The 2026-05-07 11h
// outage saw zero of ~199k buffered rows backfill until manual psql recovery.
// Cursor now advances only inside buffer_replay.js on successful poll batches
// (which already track maxTs and call saveLastTs). The tsNs param is retained
// for API stability; callers still pass it but it's no longer used here.
async function insertTelemetry(topic, value, tsMs, _tsNs) {
    if (!dbReady) return;
    const tsMsResolved = tsMs || Date.now();
    try {
        await pool.query(
            'INSERT INTO telemetry (time, topic, value) VALUES (to_timestamp($1::double precision / 1000), $2, $3) ON CONFLICT (topic, time) DO NOTHING',
            [tsMsResolved, topic, value]
        );
    } catch (err) {
        console.error('[db] insert failed:', err.message);
    }
}

// Derived telemetry: recompute VPD + chamber water-vapor from the latest
// temperature + humidity, then broadcast + persist. Called from both the
// temperature and humidity subscriptions so it refreshes whenever either
// input moves. No-op until both inputs have been seen. Uses the caller's
// timestamp (the sample that triggered the update) for DB alignment.
async function emitDerived(ts) {
    if (!latestTelemetry.temperature || !latestTelemetry.humidity) return;
    const derived = fc_derived.computeDerived(
        latestTelemetry.temperature.value,
        latestTelemetry.humidity.value
    );
    if (!derived) return;
    const tsNs = ts * 1_000_000;
    latestTelemetry.vpd = { value: derived.vpd, timestamp: ts };
    latestTelemetry.water_vapor = { value: derived.water_vapor, timestamp: ts };
    broadcast({ vpd: derived.vpd, water_vapor: derived.water_vapor, timestamp: ts });
    await insertTelemetry('fc.vpd', derived.vpd, ts, tsNs);
    await insertTelemetry('fc.water_vapor', derived.water_vapor, ts, tsNs);
}

// MUSHY-112: bind the socket BEFORE rclnodejs.init(), not inside its .then().
// rclnodejs.init() blocks on DDS discovery for ~160s, and with listen() inside
// the .then() nothing answered on 8081 for that whole window -- farm-agent saw
// ConnectionRefused and the chamber alerter had no frame source for ~3min after
// every restart. The HTTP/WS server has no real dependency on ROS: rosReady and
// dbReady already gate the routes that need them (503), /health reports both
// truthfully, and the ros-using routes read rosNode lazily at request time. A
// refused connection is indistinguishable from a dead bridge; {ros:false} is not.
server.listen(8081, () => {
    console.log('[bridge] HTTP + WebSocket server on port 8081 (ROS not ready yet)');
});

// Main startup sequence
rclnodejs.init().then(async () => {
    const node = new rclnodejs.Node('mission_control_bridge');
    rosNode = node;

    // Try DB init — non-fatal if it fails
    try {
        await initDb();
        dbReady = true;
    } catch (err) {
        console.error('[db] Init failed, continuing without DB:', err.message);
    }

    // Subscribe: fc1/humidity -> fc.humidity
    // 999.1 Plan 03: pass msg.header.stamp so DB time matches the original DDS sample.
    node.createSubscription(
        'sensor_msgs/msg/RelativeHumidity',
        '/fc1/humidity',
        async (msg) => {
            const value = msg.relative_humidity * 100;
            const tsMs = msg.header.stamp.sec * 1000 + Math.floor(msg.header.stamp.nanosec / 1e6);
            const tsNs = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec;
            const ts = tsMs || Date.now();
            latestTelemetry.humidity = { value, timestamp: ts };
            markFc1Active(Date.now());
            broadcast({ humidity: value, timestamp: ts });
            await insertTelemetry('fc.humidity', value, tsMs, tsNs);
            await emitDerived(ts);
        }
    );

    // Subscribe: fc1/temperature -> fc.temperature
    // 999.1 Plan 03: pass msg.header.stamp so DB time matches the original DDS sample.
    node.createSubscription(
        'sensor_msgs/msg/Temperature',
        '/fc1/temperature',
        async (msg) => {
            const value = msg.temperature;
            const tsMs = msg.header.stamp.sec * 1000 + Math.floor(msg.header.stamp.nanosec / 1e6);
            const tsNs = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec;
            const ts = tsMs || Date.now();
            latestTelemetry.temperature = { value, timestamp: ts };
            markFc1Active(Date.now());
            broadcast({ temperature: value, timestamp: ts });
            await insertTelemetry('fc.temperature', value, tsMs, tsNs);
            await emitDerived(ts);
        }
    );

    // Phase 26 D-02: subscribe to slot-2 SCD41-only topics.
    // Default VOLATILE QoS — DO NOT use TRANSIENT_LOCAL here. Slot-2 publishes
    // are gappy by design (D-03); TRANSIENT_LOCAL would replay a stale value
    // to late-joining clients during a real sensor outage (Phase 26 RESEARCH
    // §Common Pitfalls Pitfall 2).
    node.createSubscription(
        'sensor_msgs/msg/Temperature',
        '/fc1/temperature_2',
        async (msg) => {
            const value = msg.temperature;
            const tsMs = msg.header.stamp.sec * 1000 + Math.floor(msg.header.stamp.nanosec / 1e6);
            const tsNs = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec;
            const ts = tsMs || Date.now();
            latestTelemetry.temperature_2 = { value, timestamp: ts };
            markFc1Active(Date.now());
            broadcast({ temperature_2: value, timestamp: ts });
            await insertTelemetry('fc.temperature_2', value, tsMs, tsNs);
        }
    );

    node.createSubscription(
        'sensor_msgs/msg/RelativeHumidity',
        '/fc1/humidity_2',
        async (msg) => {
            const value = msg.relative_humidity * 100;
            const tsMs = msg.header.stamp.sec * 1000 + Math.floor(msg.header.stamp.nanosec / 1e6);
            const tsNs = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec;
            const ts = tsMs || Date.now();
            latestTelemetry.humidity_2 = { value, timestamp: ts };
            markFc1Active(Date.now());
            broadcast({ humidity_2: value, timestamp: ts });
            await insertTelemetry('fc.humidity_2', value, tsMs, tsNs);
        }
    );

    // Subscribe: fc1/co2 -> fc.co2
    node.createSubscription(
        'std_msgs/msg/Float32',
        '/fc1/co2',
        async (msg) => {
            const value = msg.data;
            const ts = Date.now();
            const tsNs = ts * 1_000_000;
            latestTelemetry.co2 = { value, timestamp: ts };
            markFc1Active(Date.now());
            broadcast({ co2: value, timestamp: ts });
            await insertTelemetry('fc.co2', value, ts, tsNs);
        }
    );

    // Shared TRANSIENT_LOCAL/RELIABLE/depth=1 QoS profile — matches fc_controller.py
    // publisher side (TDEBT-01). Reused for: humidifier, humidifier_duty, humidity_target,
    // pid_output, sensor_health, current_mode_json, alerter_mode_overrides, alerter_globals,
    // experiment_event. 999.40 dedup'd from two byte-identical inline copies.
    const transientLocalQos = new rclnodejs.QoS(
        rclnodejs.QoS.HistoryPolicy.RMW_QOS_POLICY_HISTORY_KEEP_LAST,
        1,
        rclnodejs.QoS.ReliabilityPolicy.RMW_QOS_POLICY_RELIABILITY_RELIABLE,
        rclnodejs.QoS.DurabilityPolicy.RMW_QOS_POLICY_DURABILITY_TRANSIENT_LOCAL,
        rclnodejs.QoS.LivelinessPolicy.RMW_QOS_POLICY_LIVELINESS_SYSTEM_DEFAULT,
        false
    );

    // Subscribe: fc1/actuators/humidifier -> fc.humidifier  (TRANSIENT_LOCAL — replays last state on restart)
    node.createSubscription(
        'std_msgs/msg/Bool',
        '/fc1/actuators/humidifier',
        { qos: transientLocalQos },
        async (msg) => {
            const ts = Date.now();
            const tsNs = ts * 1_000_000;
            humidifierLastMsgTs = ts;
            const value = msg.data ? 1 : 0;
            latestTelemetry.humidifier = { value, timestamp: ts };
            markFc1Active(Date.now());
            broadcast({ humidifier: value, timestamp: ts });
            await insertTelemetry('fc.humidifier', value, ts, tsNs);
        }
    );
    console.log('[bridge] Humidifier subscription: TRANSIENT_LOCAL QoS (replays last state on restart)');

    // Phase 27: subscribe to fc1/actuators/humidifier_duty -> fc.humidifier_duty
    // TRANSIENT_LOCAL matches fc_controller publisher (Pitfall 5).
    // Value is 0.0–1.0 per D-02 — do NOT rescale to 0–100%.
    node.createSubscription(
        'std_msgs/msg/Float32',
        '/fc1/actuators/humidifier_duty',
        { qos: transientLocalQos },
        async (msg) => {
            const value = msg.data;
            const ts = Date.now();
            const tsNs = ts * 1_000_000;
            latestTelemetry.humidifier_duty = { value, timestamp: ts };
            markFc1Active(Date.now());
            broadcast({ humidifier_duty: value, timestamp: ts });
            await insertTelemetry('fc.humidifier_duty', value, ts, tsNs);
        }
    );
    console.log('[bridge] Humidifier-duty subscription: TRANSIENT_LOCAL QoS');

    // Phase 27: subscribe to fc1/control/humidity_target -> fc.humidity_target
    // TRANSIENT_LOCAL matches fc_controller publisher.
    // Effective post-ramp setpoint for PID tuning visibility in OpenMCT.
    node.createSubscription(
        'std_msgs/msg/Float32',
        '/fc1/control/humidity_target',
        { qos: transientLocalQos },
        async (msg) => {
            const value = msg.data;
            const ts = Date.now();
            const tsNs = ts * 1_000_000;
            latestTelemetry.humidity_target = { value, timestamp: ts };
            broadcast({ humidity_target: value, timestamp: ts });
            await insertTelemetry('fc.humidity_target', value, ts, tsNs);
        }
    );
    console.log('[bridge] Humidity-target subscription: TRANSIENT_LOCAL QoS');

    // Phase 27: subscribe to fc1/control/pid_output -> fc.pid_output
    // TRANSIENT_LOCAL matches fc_controller publisher.
    // Raw PID output (pre-clamp) for PID tuning visibility in OpenMCT.
    node.createSubscription(
        'std_msgs/msg/Float32',
        '/fc1/control/pid_output',
        { qos: transientLocalQos },
        async (msg) => {
            const value = msg.data;
            const ts = Date.now();
            const tsNs = ts * 1_000_000;
            latestTelemetry.pid_output = { value, timestamp: ts };
            markFc1Active(Date.now());
            broadcast({ pid_output: value, timestamp: ts });
            await insertTelemetry('fc.pid_output', value, ts, tsNs);
        }
    );
    console.log('[bridge] PID-output subscription: TRANSIENT_LOCAL QoS');

    // Phase 16: forward /fc1/sensor_health (DiagnosticStatus, TRANSIENT_LOCAL) to WS clients
    node.createSubscription(
        'diagnostic_msgs/msg/DiagnosticStatus',
        '/fc1/sensor_health',
        { qos: transientLocalQos },
        (msg) => {
            // Flatten KeyValue[] into a plain object for easy browser consumption
            const values = {};
            (msg.values || []).forEach((kv) => { values[kv.key] = kv.value; });
            const payload = {
                sensor_health: {
                    level: msg.level,           // 0=OK, 1=WARN, 2=ERROR
                    name: msg.name,
                    message: msg.message,
                    values: values              // { grace_elapsed_sec, grace_total_sec, ... } when WARN
                },
                timestamp: Date.now()
            };
            lastSensorHealthBroadcast = payload;
            markFc1Active(Date.now());
            broadcast(payload);
        }
    );
    console.log('[bridge] Sensor health subscription: TRANSIENT_LOCAL QoS (/fc1/sensor_health)');

    // Phase 29-02 (D-01/D-02/D-06): subscribe to /fc1/control/current_mode +
    // /fc1/control/alerter_mode_overrides + /fc1/control/alerter_globals.
    // All three use TRANSIENT_LOCAL/RELIABLE/depth=1 to match the controller-side
    // publishers — fresh subscribers (e.g. alerter cold-start) get the latest
    // value within one DDS handshake. Each callback updates a module-scope cache
    // so on-connect WS replay (above) can deliver to freshly-connecting clients.
    // Phase 29-07 deploy fix: bridge container ships ros:jazzy-ros-core only
    // (no fc_msgs build), so rclnodejs cannot generate JS bindings for
    // fc_msgs/msg/Mode. Subscribe to the JSON-in-String sibling published by
    // fc_controller alongside the typed Mode topic. Same TRANSIENT_LOCAL QoS.
    node.createSubscription(
        'std_msgs/msg/String',
        '/fc1/control/current_mode_json',
        { qos: transientLocalQos },
        (msg) => {
            let parsed;
            try {
                parsed = JSON.parse(msg.data);
            } catch (e) {
                console.warn('[bridge] current_mode_json: malformed JSON, dropping:', e.message);
                return;
            }
            const payload = {
                current_mode: {
                    name:             parsed.name,
                    target_humidity:  parsed.target_humidity,
                    band_low:         parsed.band_low,
                    band_high:        parsed.band_high,
                    defend_side:      parsed.defend_side,
                    t_target:         parsed.t_target,
                    effective_since:  parsed.effective_since,
                    source:           parsed.source,
                },
                timestamp: Date.now(),
            };
            lastModeBroadcast = payload;
            broadcast(payload);
        }
    );
    console.log('[bridge] Phase 29: current_mode subscription (TRANSIENT_LOCAL) — /fc1/control/current_mode_json');

    node.createSubscription(
        'std_msgs/msg/String',
        '/fc1/control/alerter_mode_overrides',
        { qos: transientLocalQos },
        (msg) => {
            let parsed;
            try {
                parsed = JSON.parse(msg.data);
            } catch (e) {
                console.warn('[bridge] alerter_mode_overrides: malformed JSON, dropping:', e.message);
                return;
            }
            const payload = { alerter_overrides: parsed, timestamp: Date.now() };
            lastAlerterModeOverridesBroadcast = payload;
            broadcast(payload);
        }
    );
    console.log('[bridge] Phase 29: alerter_mode_overrides subscription (TRANSIENT_LOCAL)');

    node.createSubscription(
        'std_msgs/msg/String',
        '/fc1/control/alerter_globals',
        { qos: transientLocalQos },
        (msg) => {
            let parsed;
            try {
                parsed = JSON.parse(msg.data);
            } catch (e) {
                console.warn('[bridge] alerter_globals: malformed JSON, dropping:', e.message);
                return;
            }
            const payload = { alerter_globals: parsed, timestamp: Date.now() };
            lastAlerterGlobalsBroadcast = payload;
            broadcast(payload);
        }
    );
    console.log('[bridge] Phase 29: alerter_globals subscription (TRANSIENT_LOCAL)');

    // Phase 31 D-22: subscribe to /fc1/control/experiment_event (JSON-in-String,
    // TRANSIENT_LOCAL/RELIABLE/depth=1). Bridge persists started/ended/cancelled
    // /truncated events to fc_experiments and broadcasts the JSON envelope to
    // WS clients (with on-connect replay via lastExperimentEventBroadcast).
    const _experimentEventHandler = control_experiment.makeExperimentEventHandler({
        pool,
        // baseline_rh / final_rh come from the live humidity telemetry buffer.
        // latestTelemetry.humidity stores the last RH value as a *percent*
        // (the humidity subscriber multiplies relative_humidity * 100). null
        // when no humidity has arrived since boot.
        getLastRh: () => (latestTelemetry.humidity != null ? latestTelemetry.humidity.value : null),
        setLastEventCache: (payload) => {
            lastExperimentEventBroadcast = { topic: 'fc.experiment_event', value: payload };
        },
        broadcast: (payload) => {
            broadcast({ topic: 'fc.experiment_event', value: payload, timestamp: Date.now() });
        },
        logger: console,
    });
    node.createSubscription(
        'std_msgs/msg/String',
        '/fc1/control/experiment_event',
        { qos: transientLocalQos },   // reuse TRANSIENT_LOCAL/RELIABLE/depth=1 profile
        (msg) => {
            let parsed;
            try {
                parsed = JSON.parse(msg.data);
            } catch (e) {
                console.warn('[bridge] experiment_event: malformed JSON, dropping:', e.message);
                return;
            }
            // Fire-and-forget; handler swallows DB errors so the subscription
            // thread never crashes on a bad message.
            _experimentEventHandler(parsed);
        }
    );
    console.log('[bridge] Phase 31: experiment_event subscription (TRANSIENT_LOCAL) — /fc1/control/experiment_event');

    // Phase 21 D-01: activate continuous-persistence keepalive and prime the subscription
    // so we capture idle-cadence frames even with zero MJPEG viewers.
    persistenceKeepalive = true;
    ensureCameraSubscribed();

    // Start snapshot timer (D-10: periodic snapshots, default 15 min)
    setInterval(saveSnapshot, SNAPSHOT_INTERVAL_MS);
    console.log(`[camera] Snapshot timer started: every ${SNAPSHOT_INTERVAL_MS / 60000} min to ${SNAPSHOT_DIR}/${CAMERA_ID}/`);

    // Phase 999.1 Plan 03: start the buffer-replay poller — fetches buffered
    // points from fc1's /telemetry/since every 30s with a 15s HTTP timeout
    // and INSERTs with ON CONFLICT DO NOTHING. Only meaningful when dbReady
    // (otherwise pollOnce's INSERT would fail; the loop survives because
    // start() catches errors per tick).
    if (dbReady) {
        buffer_replay.start({ pool });
    } else {
        console.warn('[buffer-replay] DB not ready — skipping poller start');
    }

    // Phase 21 D-04: daily retention tick + startup shot 60s after bridge comes up.
    // Runs in-process (no new container) per D-01.
    const prunerArgs = () => ({
        pool, fs, now: () => Date.now(),
        retentionDays: RETENTION_DAYS, graceDays: RETENTION_GRACE_DAYS,
        rawDir: SNAPSHOT_DIR, burntDir: SNAPSHOT_BURNT_DIR
    });
    setInterval(() => {
        if (!dbReady) return;
        retention.runPrune(prunerArgs()).catch(e => console.error('[retention] tick failed:', e.message));
    }, PRUNE_INTERVAL_MS);
    setTimeout(() => {
        if (!dbReady) return;
        retention.runPrune(prunerArgs()).catch(e => console.error('[retention] startup tick failed:', e.message));
    }, 60 * 1000);
    console.log('[retention] scheduled — retain ' + RETENTION_DAYS + ' days, grace ' + RETENTION_GRACE_DAYS + ' days');

    rosReady = true;
    node.spin();
}).catch((err) => {
    console.error('Failed to initialize ROS:', err);
    process.exit(1);
});
