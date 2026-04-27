// Phase 23 D-03: HTTP routes — pure registration. All deps injected for tests.
const SAFE_CAMERA_ID = /^[a-zA-Z0-9_-]+$/;
const MAX_RANGE_DAYS = 7;

function validateQuery({ from, to, camera_id }) {
    if (!camera_id || !SAFE_CAMERA_ID.test(camera_id)) {
        return { ok: false, status: 400, error: 'Invalid camera_id' };
    }
    const fromD = new Date(from);
    const toD = new Date(to);
    if (Number.isNaN(fromD.getTime()) || Number.isNaN(toD.getTime())) {
        return { ok: false, status: 400, error: 'Invalid from/to (must be parseable ISO)' };
    }
    if (toD.getTime() <= fromD.getTime()) {
        return { ok: false, status: 400, error: 'to must be after from' };
    }
    const days = (toD.getTime() - fromD.getTime()) / 86400000;
    if (days > MAX_RANGE_DAYS) {
        return { ok: false, status: 400, error: `Range must be <= ${MAX_RANGE_DAYS} days` };
    }
    return { ok: true, fromD, toD, days };
}

// Returns 'YYYY-MM-DD' if [from, to] is a single calendar UTC day; null otherwise.
function singleDayUtc(fromD, toD) {
    const fromIso = fromD.toISOString();
    const toIso = toD.toISOString();
    if (!fromIso.endsWith('T00:00:00.000Z')) return null;
    const expectedTo = fromIso.slice(0, 10) + 'T23:59:59.999Z';
    if (toIso !== expectedTo) return null;
    return fromIso.slice(0, 10);
}

function registerRoutes(app, { pool, jobs, runComposition, db, healthState, log = console }) {
    app.get('/health', (req, res) => {
        res.json({
            status: 'ok',
            last_nightly_at: healthState.last_nightly_at,
            last_nightly_status: healthState.last_nightly_status,
        });
    });

    app.get('/timelapse', async (req, res) => {
        const v = validateQuery(req.query);
        if (!v.ok) return res.status(v.status).json({ error: v.error });

        const cameraId = req.query.camera_id;
        const dayKey = singleDayUtc(v.fromD, v.toD);
        if (dayKey) {
            const existing = await db.lookupTimelapse(pool, cameraId, dayKey);
            if (existing) {
                return res.json({ file_path: existing.file_path, duration_sec: existing.duration_sec });
            }
        }

        const crypto = require('crypto');
        const jobId = crypto.randomUUID();
        jobs.set(jobId, { status: 'pending' });
        setImmediate(() => runComposition(jobId, { from: req.query.from, to: req.query.to, camera_id: cameraId }));
        res.status(202).json({ job_id: jobId });
    });

    app.get('/timelapse/status/:id', (req, res) => {
        const job = jobs.get(req.params.id);
        if (!job) return res.status(404).json({ error: 'Unknown job' });
        res.json(job);
    });
}

module.exports = { registerRoutes, validateQuery, singleDayUtc, SAFE_CAMERA_ID, MAX_RANGE_DAYS };
