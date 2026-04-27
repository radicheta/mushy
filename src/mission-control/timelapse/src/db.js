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

// Source: bridge inserts telemetry with topic 'fc.humidity' (dot, not slash).
// RESEARCH.md Pitfall 1 corrects CONTEXT.md D-11.
// Telemetry table uses 'time' column (not 'captured_at') — aliased as captured_at for
// compatibility with nearestRh and composer.js callers.
async function fetchRhForDay(pool, date) {
    const result = await pool.query(
        `SELECT time AS captured_at, value FROM telemetry
         WHERE topic = 'fc.humidity'
           AND time >= $1 AND time < $2
         ORDER BY time ASC`,
        [`${date}T00:00:00Z`, `${date}T23:59:59.999Z`]
    );
    return result.rows;
}

// 30-minute tolerance per D-11.
const RH_TOLERANCE_MS = 30 * 60 * 1000;

function nearestRh(rhRows, frameTsMs, toleranceMs = RH_TOLERANCE_MS) {
    if (!rhRows || rhRows.length === 0) return null;
    let bestVal = null;
    let bestDelta = Infinity;
    for (const row of rhRows) {
        const rowMs = row.captured_at instanceof Date
            ? row.captured_at.getTime()
            : new Date(row.captured_at).getTime();
        const delta = Math.abs(rowMs - frameTsMs);
        if (delta < bestDelta) { bestDelta = delta; bestVal = row.value; }
        else if (delta > bestDelta) break; // sorted ASC — only grows
    }
    return bestDelta <= toleranceMs ? bestVal : null;
}

module.exports = { initDb, insertTimelapse, lookupTimelapse, fetchRhForDay, nearestRh, RH_TOLERANCE_MS };
