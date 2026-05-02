// Phase 999.1 Plan 01: idempotent schema migration helpers.
//
// Adds a UNIQUE (topic, time) constraint to the `telemetry` hypertable so the
// Plan 03 backfill can use ON CONFLICT (topic, time) DO NOTHING. Without this
// constraint Postgres raises:
//   "there is no unique or exclusion constraint matching the ON CONFLICT specification"
//
// Hypertable rule: a UNIQUE/PK on a hypertable must include the partitioning
// column (`time`). The (topic, time) tuple satisfies this. See RESEARCH §Pitfall 1.
//
// This module is intentionally side-effect free at require() time so jest can
// load it without booting rclnodejs / opening a pg pool. Pattern matches
// retention.js / snapshot_helpers.js.

async function findTopicTimeDuplicates(pool, limit = 5) {
    const r = await pool.query(
        'SELECT topic, time, COUNT(*) AS n FROM telemetry ' +
        'GROUP BY 1,2 HAVING COUNT(*) > 1 ORDER BY n DESC LIMIT $1',
        [limit]
    );
    return r.rows;
}

async function applyTelemetryUniqueConstraint(pool) {
    // Idempotent — safe to run on every bridge boot. ALTER TABLE ADD CONSTRAINT
    // is NOT idempotent on its own; the DO $$ ... IF NOT EXISTS ... END $$
    // wrapper makes it a no-op on subsequent runs.
    await pool.query(`
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'telemetry_topic_time_unique'
            ) THEN
                ALTER TABLE telemetry
                    ADD CONSTRAINT telemetry_topic_time_unique UNIQUE (topic, time);
            END IF;
        END $$;
    `);
}

module.exports = {
    findTopicTimeDuplicates,
    applyTelemetryUniqueConstraint
};
