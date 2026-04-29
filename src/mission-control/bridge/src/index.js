const http = require('http');
const express = require('express');
const WebSocket = require('ws');
const rclnodejs = require('rclnodejs');
const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');
const { decideSource } = require('./snapshot_helpers');
const retention = require('./retention');
const { validateHistoryParams } = require('./history_validate');
const { validateFrameParams } = require('./frame_validate');
const { burnBar, formatBarText } = require('./burn_bar');

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
    humidifier: null
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
const ALLOWED_TOPICS = ['fc.humidity', 'fc.temperature', 'fc.co2', 'fc.humidifier', 'fc.humidity_2', 'fc.temperature_2'];

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

// Store connected WebSocket clients
const clients = new Set();

// Phase 16.1: cache last sensor_health broadcast so new WS clients see current state
// before the next fc_controller state transition (addresses grey-until-tick UX).
let lastSensorHealthBroadcast = null;

wss.on('connection', (ws) => {
    console.log('[bridge] Client connected');
    clients.add(ws);

    if (lastSensorHealthBroadcast && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(lastSensorHealthBroadcast));
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

// Insert a telemetry row — never throws; DB errors are logged only
async function insertTelemetry(topic, value) {
    if (!dbReady) return;
    try {
        await pool.query(
            'INSERT INTO telemetry (time, topic, value) VALUES ($1, $2, $3)',
            [new Date(), topic, value]
        );
    } catch (err) {
        console.error('[db] insert failed:', err.message);
    }
}

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
    node.createSubscription(
        'sensor_msgs/msg/RelativeHumidity',
        '/fc1/humidity',
        async (msg) => {
            const value = msg.relative_humidity * 100;
            const ts = Date.now();
            latestTelemetry.humidity = { value, timestamp: ts };
            broadcast({ humidity: value, timestamp: ts });
            await insertTelemetry('fc.humidity', value);
        }
    );

    // Subscribe: fc1/temperature -> fc.temperature
    node.createSubscription(
        'sensor_msgs/msg/Temperature',
        '/fc1/temperature',
        async (msg) => {
            const value = msg.temperature;
            const ts = Date.now();
            latestTelemetry.temperature = { value, timestamp: ts };
            broadcast({ temperature: value, timestamp: ts });
            await insertTelemetry('fc.temperature', value);
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
            const ts = Date.now();
            latestTelemetry.temperature_2 = { value, timestamp: ts };
            broadcast({ temperature_2: value, timestamp: ts });
            await insertTelemetry('fc.temperature_2', value);
        }
    );

    node.createSubscription(
        'sensor_msgs/msg/RelativeHumidity',
        '/fc1/humidity_2',
        async (msg) => {
            const value = msg.relative_humidity * 100;
            const ts = Date.now();
            latestTelemetry.humidity_2 = { value, timestamp: ts };
            broadcast({ humidity_2: value, timestamp: ts });
            await insertTelemetry('fc.humidity_2', value);
        }
    );

    // Subscribe: fc1/co2 -> fc.co2
    node.createSubscription(
        'std_msgs/msg/Float32',
        '/fc1/co2',
        async (msg) => {
            const value = msg.data;
            const ts = Date.now();
            latestTelemetry.co2 = { value, timestamp: ts };
            broadcast({ co2: value, timestamp: ts });
            await insertTelemetry('fc.co2', value);
        }
    );

    // QoS profile for humidifier — matches fc_controller.py TRANSIENT_LOCAL publisher (TDEBT-01)
    const humidifierQos = new rclnodejs.QoS(
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
        { qos: humidifierQos },
        async (msg) => {
            const ts = Date.now();
            humidifierLastMsgTs = ts;
            const value = msg.data ? 1 : 0;
            latestTelemetry.humidifier = { value, timestamp: ts };
            broadcast({ humidifier: value, timestamp: ts });
            await insertTelemetry('fc.humidifier', value);
        }
    );
    console.log('[bridge] Humidifier subscription: TRANSIENT_LOCAL QoS (replays last state on restart)');

    // Phase 16: forward /fc1/sensor_health (DiagnosticStatus, TRANSIENT_LOCAL) to WS clients
    const sensorHealthQos = new rclnodejs.QoS(
        rclnodejs.QoS.HistoryPolicy.RMW_QOS_POLICY_HISTORY_KEEP_LAST,
        1,
        rclnodejs.QoS.ReliabilityPolicy.RMW_QOS_POLICY_RELIABILITY_RELIABLE,
        rclnodejs.QoS.DurabilityPolicy.RMW_QOS_POLICY_DURABILITY_TRANSIENT_LOCAL,
        rclnodejs.QoS.LivelinessPolicy.RMW_QOS_POLICY_LIVELINESS_SYSTEM_DEFAULT,
        false
    );
    node.createSubscription(
        'diagnostic_msgs/msg/DiagnosticStatus',
        '/fc1/sensor_health',
        { qos: sensorHealthQos },
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
            broadcast(payload);
        }
    );
    console.log('[bridge] Sensor health subscription: TRANSIENT_LOCAL QoS (/fc1/sensor_health)');

    // Phase 21 D-01: activate continuous-persistence keepalive and prime the subscription
    // so we capture idle-cadence frames even with zero MJPEG viewers.
    persistenceKeepalive = true;
    ensureCameraSubscribed();

    // Start snapshot timer (D-10: periodic snapshots, default 15 min)
    setInterval(saveSnapshot, SNAPSHOT_INTERVAL_MS);
    console.log(`[camera] Snapshot timer started: every ${SNAPSHOT_INTERVAL_MS / 60000} min to ${SNAPSHOT_DIR}/${CAMERA_ID}/`);

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

    // Start HTTP + WebSocket server
    server.listen(8081, () => {
        console.log('[bridge] HTTP + WebSocket server on port 8081');
    });

    rosReady = true;
    node.spin();
}).catch((err) => {
    console.error('Failed to initialize ROS:', err);
    process.exit(1);
});
