// MUSHY-188: rebuild daily timelapses for a range of LOCAL dates.
//
//   node src/rebuild.js                    # first snapshot day .. yesterday
//   node src/rebuild.js 2026-11-01 2026-11-11
//
// Run inside the container (same env as the service):
//   docker compose exec timelapse node src/rebuild.js
// Each day overwrites <TIMELAPSE_DIR>/<camera>/<date>.mp4 and its registry row.
const { nextDate, localDateOf } = require('./localday');

async function rebuildRange(from, to, compose, log = console) {
    const summary = { ok: 0, skipped: 0, failed: [] };
    for (let d = from; d <= to; d = nextDate(d)) {
        try {
            const r = await compose(d);
            if (r && r.skipped) {
                summary.skipped++;
                log.info(`[rebuild] ${d}: skipped (${r.reason})`);
            } else {
                summary.ok++;
            }
        } catch (e) {
            summary.failed.push({ date: d, error: e.message });
            log.error(`[rebuild] ${d}: failed: ${e.message}`);
        }
    }
    return summary;
}

async function main(argv) {
    const { Pool } = require('pg');
    const config = require('./config').load();
    const db = require('./db');
    const { composeDay } = require('./composer');
    const pool = new Pool({
        host: config.timescaleHost, database: config.timescaleDb,
        user: config.timescaleUser, password: config.timescalePassword, port: 5432,
    });
    try {
        await db.initDb(pool);
        let [from, to] = argv;
        if (!from) {
            const r = await pool.query('SELECT min(captured_at) AS t FROM snapshots WHERE camera_id=$1', [config.cameraId]);
            if (!r.rows[0].t) throw new Error(`no snapshots for ${config.cameraId}`);
            from = localDateOf(r.rows[0].t, config.timezone);
        }
        if (!to) to = localDateOf(Date.now() - 24 * 60 * 60 * 1000, config.timezone);
        console.log(`[rebuild] ${config.cameraId} ${from} .. ${to} (${config.timezone}, min_luma ${config.minLuma})`);
        const summary = await rebuildRange(from, to, (d) => composeDay(d, config.cameraId, pool, {
            fps: config.fps, timelapseDir: config.timelapseDir,
            timezone: config.timezone, tzLabel: config.tzLabel, minLuma: config.minLuma,
        }));
        console.log(`[rebuild] done: ${JSON.stringify(summary)}`);
        process.exitCode = summary.failed.length ? 1 : 0;
    } finally {
        await pool.end();
    }
}

if (require.main === module) {
    main(process.argv.slice(2)).catch((e) => { console.error('[rebuild] fatal:', e); process.exit(1); });
}

module.exports = { rebuildRange };
