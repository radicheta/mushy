// Phase 999.1 Plan 03: bridge-side replay poller for fc1 edge buffer.
//
// fc1 buffers telemetry locally (Plan 02) at /telemetry/since?ts=<ns>&limit=N
// returning JSONL of {time_ns, topic, value, extra}. This module polls every 30s
// with a 15s HTTP timeout (Pitfall 5: a hung fc1 must not stall the loop) and
// INSERTs each row into Timescale at its ORIGINAL DDS timestamp. The
// `ON CONFLICT (topic, time) DO NOTHING` clause (Plan 01 added the unique
// constraint named telemetry_topic_time_unique) makes idempotent replay safe.
//
// State (last_ingested_ns) is persisted to a host-mounted volume so it survives
// `docker compose up -d --build bridge`. Loss is recoverable (one extra full
// 24h refetch) but graceful (RESEARCH §Q3).
//
// `extra` from fc1 is intentionally NOT propagated — live insert path in
// index.js writes only (time, topic, value); backfill must match to keep
// the two paths semantically identical (RESEARCH §Q4).

const http = require('http');
const fs = require('fs');
const path = require('path');

const DEFAULT_FC1_URL = process.env.FC1_BUFFER_URL || 'http://100.96.239.75:8765';
const DEFAULT_STATE_FILE = process.env.BUFFER_REPLAY_STATE || '/var/lib/bridge/buffer-replay.state.json';
const DEFAULT_INTERVAL_MS = 30 * 1000;
const HTTP_TIMEOUT_MS = 15 * 1000;
const BATCH_LIMIT = 10000;

// MUSHY-118: fc_buffer and the bridge are two independent writers of the same
// event. For header-bearing messages both read msg.header.stamp, so they agree
// on `time` and the telemetry_topic_time_unique constraint collapses them. For
// headerless std_msgs (Bool/Float32 — humidifier, duty, humidity_target,
// pid_output, co2) neither side has a publisher stamp: fc_buffer uses
// time.time_ns() on fc1, index.js uses Date.now() on elder-plops. The two land
// 1-5ms apart and every such row was stored twice, doubling the relay-edge
// count MUSHY-116 is measured by. Replay arrives second, so it is the side that
// skips a row already present at a near-identical time with the same value. The
// live row survives, so a broken replay cannot silently erase the record.
// ponytail: 250ms window, not a shared event id. Every buffered topic publishes
// at <=1Hz, so genuine samples are >=1s apart and cannot be merged; a >250ms
// fc1->bridge delay degrades to an occasional duplicate, never to data loss.
// The real fix is a publisher-set timestamp (DDS source_timestamp or stamped
// message types) — do that if the topic set ever exceeds 1Hz.
const NEAR_DUP_MS = 250;

function loadLastTs(stateFile) {
    try {
        const raw = fs.readFileSync(stateFile, 'utf8');
        const parsed = JSON.parse(raw);
        return Number(parsed.last_ingested_ns) || 0;
    } catch {
        return 0;
    }
}

function saveLastTs(stateFile, ns) {
    try {
        fs.mkdirSync(path.dirname(stateFile), { recursive: true });
        fs.writeFileSync(
            stateFile,
            JSON.stringify({ last_ingested_ns: ns, updated_at: Date.now() })
        );
    } catch (e) {
        console.error('[buffer-replay] saveLastTs failed:', e.message);
    }
}

function advanceLastIngested(stateFile, ns) {
    const current = loadLastTs(stateFile);
    if (ns > current) saveLastTs(stateFile, ns);
}

function parseNdjson(body) {
    if (!body) return [];
    return body
        .split('\n')
        .map(l => l.trim())
        .filter(l => l.length > 0)
        .map(l => JSON.parse(l));
}

// Default HTTP fetch — Node stdlib http with a hard 15s timeout (Pitfall 5).
// A hung fc1 (still TCP-reachable but not responding) must not stall the loop.
function defaultFetchFn(url) {
    return new Promise((resolve, reject) => {
        const req = http.get(url, (res) => {
            if (res.statusCode !== 200) {
                res.resume();
                return reject(new Error(`HTTP ${res.statusCode}`));
            }
            let body = '';
            res.setEncoding('utf8');
            res.on('data', (chunk) => { body += chunk; });
            res.on('end', () => resolve(body));
        });
        req.setTimeout(HTTP_TIMEOUT_MS, () => req.destroy(new Error('timeout')));
        req.on('error', reject);
    });
}

async function pollOnce({
    pool,
    fc1Url = DEFAULT_FC1_URL,
    stateFile = DEFAULT_STATE_FILE,
    fetchFn = defaultFetchFn
}) {
    const sinceNs = loadLastTs(stateFile);
    const url = `${fc1Url}/telemetry/since?ts=${sinceNs}&limit=${BATCH_LIMIT}`;
    const body = await fetchFn(url);
    const lines = parseNdjson(body);
    if (lines.length === 0) return { rows: 0, maxTs: sinceNs };

    let maxTs = sinceNs;
    const client = await pool.connect();
    try {
        await client.query('BEGIN');
        for (const r of lines) {
            // Convert DDS ns → ms (Timescale `time` column is timestamptz).
            // r.extra is intentionally dropped — live path doesn't write it either.
            const tsMs = Math.floor(r.time_ns / 1_000_000);
            await client.query(
                `INSERT INTO telemetry (time, topic, value)
                 SELECT to_timestamp($1::double precision / 1000), $2, $3
                 WHERE NOT EXISTS (
                     SELECT 1 FROM telemetry
                     WHERE topic = $2 AND value = $3
                       AND time BETWEEN to_timestamp($1::double precision / 1000) - interval '${NEAR_DUP_MS} milliseconds'
                                    AND to_timestamp($1::double precision / 1000) + interval '${NEAR_DUP_MS} milliseconds'
                 )
                 ON CONFLICT (topic, time) DO NOTHING`,
                [tsMs, r.topic, r.value]
            );
            if (r.time_ns > maxTs) maxTs = r.time_ns;
        }
        await client.query('COMMIT');
    } catch (e) {
        try { await client.query('ROLLBACK'); } catch {}
        throw e;
    } finally {
        client.release();
    }

    saveLastTs(stateFile, maxTs);
    return { rows: lines.length, maxTs };
}

function start({
    pool,
    fc1Url = DEFAULT_FC1_URL,
    stateFile = DEFAULT_STATE_FILE,
    intervalMs = DEFAULT_INTERVAL_MS
}) {
    console.log(
        `[buffer-replay] polling ${fc1Url}/telemetry/since every ${intervalMs}ms, state=${stateFile}`
    );
    return setInterval(() => {
        pollOnce({ pool, fc1Url, stateFile })
            .then(r => {
                if (r.rows > 0) {
                    console.log(
                        `[buffer-replay] backfilled ${r.rows} rows up to ts_ns=${r.maxTs}`
                    );
                }
            })
            .catch(e => console.error('[buffer-replay] poll failed:', e.message));
    }, intervalMs);
}

module.exports = {
    loadLastTs,
    saveLastTs,
    advanceLastIngested,
    parseNdjson,
    pollOnce,
    start,
    DEFAULT_FC1_URL,
    DEFAULT_STATE_FILE,
    HTTP_TIMEOUT_MS
};
