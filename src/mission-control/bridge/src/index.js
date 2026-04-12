const http = require('http');
const express = require('express');
const WebSocket = require('ws');
const rclnodejs = require('rclnodejs');
const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');

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

// Camera MJPEG streaming state
const BOUNDARY = 'frameboundary';
const mjpegClients = new Set();
let latestFrame = null;
let lastFrameTime = null;

// Snapshot config from environment
const SNAPSHOT_DIR = process.env.SNAPSHOT_DIR || '/data/snapshots';
const SNAPSHOT_INTERVAL_MS = parseInt(process.env.SNAPSHOT_INTERVAL_MIN || '15', 10) * 60 * 1000;
const CAMERA_ID = process.env.CAMERA_ID || 'fc1';

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

function saveSnapshot() {
    if (!latestFrame) return;
    const now = new Date();
    const dateDir = now.toISOString().slice(0, 10); // YYYY-MM-DD
    const dir = path.join(SNAPSHOT_DIR, CAMERA_ID, dateDir);
    fs.mkdirSync(dir, { recursive: true });
    const filename = `${now.toISOString().replace(/[:.]/g, '-')}.jpg`;
    const filepath = path.join(dir, filename);
    fs.writeFile(filepath, latestFrame, (err) => {
        if (err) console.error('[camera] snapshot write failed:', err.message);
        else console.log(`[camera] snapshot saved: ${filepath} (${CAMERA_ID}, ${latestFrame.length} bytes)`);
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

// Health check route
app.get('/health', (req, res) => {
    res.json({
        status: 'ok',
        db: dbReady,
        camera: {
            lastFrame: lastFrameTime,
            clients: mjpegClients.size
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
    console.log(`[camera] MJPEG client connected (${mjpegClients.size} total)`);
    req.on('close', () => {
        mjpegClients.delete(res);
        console.log(`[camera] MJPEG client disconnected (${mjpegClients.size} total)`);
    });
});

// Camera latest frame endpoint (single JPEG for testing)
app.get('/camera/snapshot', (req, res) => {
    if (!latestFrame) {
        return res.status(503).json({ error: 'No camera frame available' });
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

wss.on('connection', (ws) => {
    console.log('[bridge] Client connected');
    clients.add(ws);

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
            broadcast({ humidity: value, timestamp: Date.now() });
            await insertTelemetry('fc.humidity', value);
        }
    );

    // Subscribe: fc1/temperature -> fc.temperature
    node.createSubscription(
        'sensor_msgs/msg/Temperature',
        '/fc1/temperature',
        async (msg) => {
            const value = msg.temperature;
            broadcast({ temperature: value, timestamp: Date.now() });
            await insertTelemetry('fc.temperature', value);
        }
    );

    // Subscribe: fc1/co2 -> fc.co2
    node.createSubscription(
        'std_msgs/msg/Float32',
        '/fc1/co2',
        async (msg) => {
            const value = msg.data;
            broadcast({ co2: value, timestamp: Date.now() });
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
            const value = msg.data ? 1 : 0;
            broadcast({ humidifier: value, timestamp: Date.now() });
            await insertTelemetry('fc.humidifier', value);
        }
    );
    console.log('[bridge] Humidifier subscription: TRANSIENT_LOCAL QoS (replays last state on restart)');

    // Subscribe: fc1/camera/compressed -> MJPEG stream (D-03)
    node.createSubscription(
        'sensor_msgs/msg/CompressedImage',
        '/fc1/camera/compressed',
        (msg) => {
            const buf = Buffer.from(msg.data);
            pushFrame(buf);
        }
    );

    // Start snapshot timer (D-10: periodic snapshots, default 15 min)
    setInterval(saveSnapshot, SNAPSHOT_INTERVAL_MS);
    console.log(`[camera] Snapshot timer started: every ${SNAPSHOT_INTERVAL_MS / 60000} min to ${SNAPSHOT_DIR}/${CAMERA_ID}/`);

    // Start HTTP + WebSocket server
    server.listen(8081, () => {
        console.log('[bridge] HTTP + WebSocket server on port 8081');
    });

    node.spin();
}).catch((err) => {
    console.error('Failed to initialize ROS:', err);
    process.exit(1);
});
