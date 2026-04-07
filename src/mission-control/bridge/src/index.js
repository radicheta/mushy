const http = require('http');
const express = require('express');
const WebSocket = require('ws');
const rclnodejs = require('rclnodejs');
const { Pool } = require('pg');

// PostgreSQL connection pool
const pool = new Pool({
    host: process.env.TIMESCALE_HOST || 'timescale',
    database: process.env.TIMESCALE_DB || 'postgres',
    user: process.env.TIMESCALE_USER || 'postgres',
    password: process.env.TIMESCALE_PASSWORD || 'mysecretpassword',
    port: 5432
});

// Track DB availability — live WS continues even if DB is down
let dbReady = false;

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

// CORS — allow OpenMCT frontend (port 8080) to call history endpoint
app.use((req, res, next) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    next();
});

// Health check route
app.get('/health', (req, res) => {
    res.json({ status: 'ok', db: dbReady });
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
        'fc1/humidity',
        async (msg) => {
            const value = msg.relative_humidity * 100;
            broadcast({ humidity: value, timestamp: Date.now() });
            await insertTelemetry('fc.humidity', value);
        }
    );

    // Subscribe: fc1/temperature -> fc.temperature
    node.createSubscription(
        'sensor_msgs/msg/Temperature',
        'fc1/temperature',
        async (msg) => {
            const value = msg.temperature;
            broadcast({ temperature: value, timestamp: Date.now() });
            await insertTelemetry('fc.temperature', value);
        }
    );

    // Subscribe: fc1/co2 -> fc.co2
    node.createSubscription(
        'std_msgs/msg/Float32',
        'fc1/co2',
        async (msg) => {
            const value = msg.data;
            broadcast({ co2: value, timestamp: Date.now() });
            await insertTelemetry('fc.co2', value);
        }
    );

    // Subscribe: fc1/actuators/humidifier -> fc.humidifier
    node.createSubscription(
        'std_msgs/msg/Bool',
        'fc1/actuators/humidifier',
        async (msg) => {
            const value = msg.data ? 1 : 0;
            broadcast({ humidifier: value, timestamp: Date.now() });
            await insertTelemetry('fc.humidifier', value);
        }
    );

    // Start HTTP + WebSocket server
    server.listen(8081, () => {
        console.log('[bridge] HTTP + WebSocket server on port 8081');
    });

    node.spin();
}).catch((err) => {
    console.error('Failed to initialize ROS:', err);
    process.exit(1);
});
