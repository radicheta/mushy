// Phase 23: timelapses registry + RH lookup helpers.
// Pure module — pool injected by caller.

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

// 30-minute tolerance per D-11.
const TOLERANCE_MS = 30 * 60 * 1000;

// Rows for one telemetry topic over [start, end), padded by the match tolerance
// so frames at the day edges still find a neighbour. Topics are dotted
// ('fc.humidity'); the table's time column is aliased captured_at for nearestValue.
async function fetchTelemetry(pool, topic, start, end) {
    const from = new Date(new Date(start).getTime() - TOLERANCE_MS).toISOString();
    const to = new Date(new Date(end).getTime() + TOLERANCE_MS).toISOString();
    const result = await pool.query(
        `SELECT time AS captured_at, value FROM telemetry
         WHERE topic = $1 AND time >= $2 AND time < $3
         ORDER BY time ASC`,
        [topic, from, to]
    );
    return result.rows;
}

function nearestValue(rows, frameTsMs, toleranceMs = TOLERANCE_MS) {
    if (!rows || rows.length === 0) return null;
    let bestVal = null;
    let bestDelta = Infinity;
    for (const row of rows) {
        const rowMs = row.captured_at instanceof Date
            ? row.captured_at.getTime()
            : new Date(row.captured_at).getTime();
        const delta = Math.abs(rowMs - frameTsMs);
        if (delta < bestDelta) { bestDelta = delta; bestVal = row.value; }
        else if (delta > bestDelta) break; // sorted ASC — only grows
    }
    return bestDelta <= toleranceMs ? bestVal : null;
}

module.exports = { initDb, insertTimelapse, lookupTimelapse, fetchTelemetry, nearestValue, TOLERANCE_MS };
