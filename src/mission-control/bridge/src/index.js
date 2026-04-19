const http = require('http');
const express = require('express');
const WebSocket = require('ws');
const rclnodejs = require('rclnodejs');
const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');
const { decideSource } = require('./snapshot_helpers');
const retention = require('./retention');

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
const SNAPSHOT_INTERVAL_MS = parseInt(process.env.SNAPSHOT_INTERVAL_MIN || '15', 10) * 60 * 1000;
const CAMERA_ID = process.env.CAMERA_ID || 'fc1';

// Phase 21 D-04: retention config. clampRetentionDays enforces MIN_RETENTION_DAYS=30
// (Pitfall 2 belt-and-suspenders) before runPrune's 30-day grace guard kicks in.
const RETENTION_DAYS = retention.clampRetentionDays(process.env.RETENTION_DAYS || retention.DEFAULT_RETENTION_DAYS);
const RETENTION_GRACE_DAYS = parseInt(process.env.RETENTION_GRACE_DAYS || retention.DEFAULT_GRACE_DAYS, 10);
const PRUNE_INTERVAL_MS = 24 * 3600 * 1000;

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
app.get('/health', (req, res) => {
    const lastFrameAgeSec = lastFrameTime === null
        ? null
        : Math.round((Date.now() - lastFrameTime) / 1000);
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
        }
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
const ALLOWED_TOPICS = ['fc.humidity', 'fc.temperature', 'fc.co2', 'fc.humidifier'];

// Server-side downsampling: choose bucket interval based on requested time range (D-06)
// <=2h -> ~120 points at 1min; <=12h -> ~144 points at 5min; >12h -> ~96/day at 15min
function bucketInterval(rangeMs) {
    const ONE_HOUR = 3600000;
    if (rangeMs <= 2 * ONE_HOUR)  return '1 minute';
    if (rangeMs <= 12 * ONE_HOUR) return '5 minutes';
    return '15 minutes';
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
        retentionDays: RETENTION_DAYS, graceDays: RETENTION_GRACE_DAYS
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
