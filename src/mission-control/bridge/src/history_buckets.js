// Telemetry GET /history: range cap and server-side downsampling step (D-06).
// MUSHY-179: cap raised from 30 days to a year. Above that the request is
// refused; the step keeps a plot to roughly 1000-1500 points.
const HOUR = 3600000;
const DAY = 24 * HOUR;

const TELEMETRY_MAX_RANGE_MS = 366 * DAY;

// <=2h 5s; <=24h 1min; <=7d 10min; <=6 months 1h; up to a year 3h
function bucketInterval(rangeMs) {
    if (rangeMs <= 2 * HOUR) return '5 seconds';
    if (rangeMs <= DAY) return '1 minute';
    if (rangeMs <= 7 * DAY) return '10 minutes';
    if (rangeMs <= 183 * DAY) return '1 hour';
    return '3 hours';
}

// MUSHY-182: ranges over 7 days read the hourly continuous aggregate instead
// of raw rows. A cold one-year read of raw rows took 81 s. The aggregate keeps
// sum and count so 3 h steps are weighted by readings, the same as AVG over raw.
function historyQuery(topic, start, end) {
    const interval = bucketInterval(end - start);
    const values = [interval, topic, new Date(start), new Date(end)];
    if (end - start <= 7 * DAY) {
        return {
            text: `SELECT time_bucket($1::interval, time) AS bucket,
                          AVG(value) AS value
                   FROM telemetry
                   WHERE topic = $2 AND time >= $3 AND time <= $4
                   GROUP BY bucket
                   ORDER BY bucket ASC`,
            values,
        };
    }
    // bucket >= the hour holding $3, so the first partial hour is kept as the
    // raw query keeps it.
    return {
        text: `SELECT time_bucket($1::interval, bucket) AS bucket,
                      SUM(sum) / SUM(n) AS value
               FROM telemetry_hourly
               WHERE topic = $2
                 AND bucket >= time_bucket('1 hour', $3::timestamptz)
                 AND bucket <= $4
               GROUP BY 1
               ORDER BY 1 ASC`,
        values,
    };
}

// Created WITH NO DATA so bridge boot never waits on a backfill (29 GB of raw
// rows; see MUSHY-113 for what a boot-time full scan costs). The policy's
// first run backfills in a Timescale background job. materialized_only=false
// means hours not yet materialized are computed from raw rows at query time,
// so reads stay correct while the backfill runs.
const HOURLY_DDL = [
    `CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_hourly
     WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
     SELECT topic, time_bucket('1 hour', time) AS bucket,
            SUM(value) AS sum, COUNT(*) AS n
     FROM telemetry
     GROUP BY topic, bucket
     WITH NO DATA`,
    `SELECT add_continuous_aggregate_policy('telemetry_hourly',
         start_offset      => NULL,
         end_offset        => INTERVAL '1 hour',
         schedule_interval => INTERVAL '30 minutes',
         if_not_exists     => TRUE)`,
];

async function ensureTelemetryHourly(pool) {
    for (const sql of HOURLY_DDL) await pool.query(sql);
}

module.exports = { bucketInterval, historyQuery, ensureTelemetryHourly, HOURLY_DDL, TELEMETRY_MAX_RANGE_MS };
