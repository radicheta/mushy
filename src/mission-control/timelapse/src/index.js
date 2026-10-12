// Phase 23: timelapse server bootstrap.
// - Loads config (fail-fast on missing TIMESCALE_PASSWORD)
// - Creates pg Pool
// - initDb (creates timelapses table)
// - Registers Express routes (/health, /timelapse, /timelapse/status/:id)
// - Schedules node-cron at config.cronSchedule with config.timezone (D-02)
// - Listens on config.port
const express = require('express');
const cron = require('node-cron');
const { Pool } = require('pg');

const config = require('./config').load();
const db = require('./db');
const { composeDay } = require('./composer');
const { registerRoutes } = require('./routes');

const pool = new Pool({
    host: config.timescaleHost,
    database: config.timescaleDb,
    user: config.timescaleUser,
    password: config.timescalePassword,
    port: 5432,
});

const jobs = new Map();
const healthState = { last_nightly_at: null, last_nightly_status: null };
const DB_RETRY_MS = 5000;

async function runComposition(jobId, { from, to, camera_id }) {
    const job = jobs.get(jobId);
    if (!job) return;
    job.status = 'running';
    try {
        // On-demand handles single-day ranges (D-03). Multi-day stitch is future work.
        const date = new Date(from).toISOString().slice(0, 10);
        const r = await composeDay(date, camera_id, pool, {
            fps: config.fps,
            timelapseDir: config.timelapseDir,
        });
        if (r.skipped) {
            job.status = 'failed';
            job.error = `skipped: ${r.reason}`;
        } else {
            job.status = 'done';
            job.file_path = r.file_path;
            job.duration_sec = r.duration_sec;
        }
    } catch (e) {
        job.status = 'failed';
        job.error = e.message;
        console.error('[job] composition failed:', e.message);
    }
}

function previousDayInTz(timezone) {
    const fmt = new Intl.DateTimeFormat('en-CA', {
        timeZone: timezone,
        year: 'numeric', month: '2-digit', day: '2-digit',
    });
    const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000);
    return fmt.format(yesterday);
}

// Timescale can take minutes to accept connections after a host reboot.
// Wait for it here instead of exiting into docker's restart loop (BONE-22).
async function initDbWhenReady() {
    for (;;) {
        try {
            return await db.initDb(pool);
        } catch (e) {
            console.error(`[db] not ready (${e.message}); retrying in ${DB_RETRY_MS / 1000}s`);
            await new Promise((resolve) => setTimeout(resolve, DB_RETRY_MS));
        }
    }
}

async function main() {
    await initDbWhenReady();
    console.log('[db] Schema initialized');

    const app = express();
    registerRoutes(app, { pool, jobs, runComposition, db, healthState });

    cron.schedule(config.cronSchedule, async () => {
        const date = previousDayInTz(config.timezone);
        console.log(`[cron] firing for ${date}`);
        try {
            const r = await composeDay(date, config.cameraId, pool, {
                fps: config.fps,
                timelapseDir: config.timelapseDir,
            });
            healthState.last_nightly_at = new Date().toISOString();
            healthState.last_nightly_status = r.skipped ? `skipped: ${r.reason}` : 'ok';
        } catch (e) {
            healthState.last_nightly_at = new Date().toISOString();
            healthState.last_nightly_status = `failed: ${e.message}`;
            console.error('[cron] nightly composition failed:', e.message);
        }
    }, { timezone: config.timezone });
    console.log(`[cron] scheduled at "${config.cronSchedule}" TZ=${config.timezone}`);

    app.listen(config.port, () => {
        console.log(`[http] listening on ${config.port}`);
    });
}

main().catch((e) => { console.error('[boot] fatal:', e); process.exit(1); });
