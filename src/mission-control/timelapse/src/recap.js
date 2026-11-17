// MUSHY-192: cumulative recap. One fixed-length video covering [start, now),
// sent on Signal every evening. The length never changes, so each day plays
// faster than the one before: the point is to see when growth becomes visible.
//
// Run once by hand inside the container:
//   docker compose exec timelapse node src/recap.js            # compose + send
//   docker compose exec timelapse node src/recap.js --no-send  # compose only
const path = require('path');

const { localDateOf, formatLocal } = require('./localday');
const overlay = require('./overlay');
const { SAFE_CAMERA_ID } = require('./composer');

const defaultDeps = {
    fs: require('fs'),
    runFfmpeg: require('./ffmpeg').runFfmpeg,
    burnOverlay: overlay.burnOverlay,
    meanLuma: overlay.meanLuma,
    db: require('./db'),
    log: console,
};

const TOPICS = { rh: 'fc.humidity', temp: 'fc.temperature', co2: 'fc.co2' };

// Luma is measured on this many candidates per output frame, so the cost of a
// recap stays flat as the window grows. Half the day is dark; 5x leaves room.
const CANDIDATE_FACTOR = 5;

// n items spread evenly across arr, first and last included.
function pickEvenly(arr, n) {
    if (arr.length <= n) return arr;
    return Array.from({ length: n }, (_, i) => arr[Math.round(i * (arr.length - 1) / (n - 1))]);
}

function tsMs(f) {
    return f.captured_at instanceof Date ? f.captured_at.getTime() : new Date(f.captured_at).getTime();
}

async function composeRecap(start, end, cameraId, pool, opts = {}) {
    const deps = { ...defaultDeps, ...(opts.deps || {}) };
    const { fs, runFfmpeg, burnOverlay, meanLuma, db, log } = deps;
    const seconds = opts.seconds || 5;
    const fps = opts.fps || 24;
    const timezone = opts.timezone || 'America/Montevideo';
    const tzLabel = opts.tzLabel || 'UYT';
    const minLuma = opts.minLuma ?? 0;
    const outputPath = opts.outputPath;
    const workDir = opts.workDir || '/tmp/timelapse_work/recap';
    const target = Math.round(seconds * fps);

    if (!SAFE_CAMERA_ID.test(cameraId)) throw new Error(`Invalid camera_id: ${cameraId}`);

    const snap = await pool.query(
        `SELECT captured_at, file_path FROM snapshots
         WHERE camera_id=$1 AND captured_at >= $2 AND captured_at < $3
         ORDER BY captured_at ASC`,
        [cameraId, start, end]
    );
    const frames = snap.rows;

    // Lit frames among an evenly spread candidate set.
    const lit = [];
    for (const f of pickEvenly(frames, target * CANDIDATE_FACTOR)) {
        try {
            const buf = await fs.promises.readFile(f.file_path);
            if (minLuma > 0 && await meanLuma(buf) < minLuma) continue;
            lit.push(f);
        } catch (e) {
            if (e.code !== 'ENOENT') throw e;
            log.warn(`[recap] missing frame ${f.file_path}, skipping`);
        }
    }
    const chosen = pickEvenly(lit, target);

    if (chosen.length < 3) {
        log.warn(`[recap] ${cameraId}: only ${chosen.length} usable frames of ${frames.length}, skipping`);
        return { skipped: true, reason: 'too_few_usable_frames', frames_found: frames.length };
    }

    const tmpOutPath = `${outputPath}.tmp`;
    try {
        await fs.promises.mkdir(workDir, { recursive: true });
        await fs.promises.mkdir(path.dirname(outputPath), { recursive: true });

        const filelistLines = [];
        for (const f of chosen) {
            const ms = tsMs(f);
            const iso = new Date(ms).toISOString();
            const reading = {};
            for (const [key, topic] of Object.entries(TOPICS)) {
                // one small query per frame: the window is days long, the frames are few
                reading[key] = db.nearestValue(await db.fetchTelemetry(pool, topic, iso, iso), ms);
            }
            const text = overlay.barText({ timestamp: formatLocal(ms, timezone), tzLabel, ...reading });
            const burned = await burnOverlay(await fs.promises.readFile(f.file_path), { text });
            const burnedPath = path.join(workDir, `frame_${String(filelistLines.length + 1).padStart(4, '0')}.jpg`);
            await fs.promises.writeFile(burnedPath, burned);
            filelistLines.push(`file '${burnedPath}'`);
        }

        const filelistPath = path.join(workDir, 'filelist.txt');
        await fs.promises.writeFile(filelistPath, filelistLines.join('\n') + '\n');

        try {
            await runFfmpeg(filelistPath, tmpOutPath, fps);
            await fs.promises.rename(tmpOutPath, outputPath);
        } catch (e) {
            try { await fs.promises.unlink(tmpOutPath); } catch (_) { /* ignore */ }
            throw e;
        }

        const durationSec = chosen.length / fps;
        log.info(`[recap] ${cameraId} ${start} .. ${end}: ${chosen.length} of ${frames.length} frames -> ${outputPath} (${durationSec.toFixed(2)}s)`);
        return { file_path: outputPath, frames_used: chosen.length, frames_total: frames.length, duration_sec: durationSec };
    } finally {
        try { await fs.promises.rm(workDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
    }
}

// Compose [config.recapStart, now) and send it. Throws on any failure.
async function runRecap(config, pool, opts = {}) {
    const now = opts.now ?? Date.now();
    const compose = opts.compose || composeRecap;
    const send = opts.send || require('./signal').sendVideo;
    const log = opts.log || console;

    const startMs = Date.parse(config.recapStart);
    if (Number.isNaN(startMs)) throw new Error(`Invalid RECAP_START: ${config.recapStart}`);
    const outputPath = path.join(config.timelapseDir, config.cameraId, 'recap', `${localDateOf(now, config.timezone)}.mp4`);

    const r = await compose(new Date(startMs).toISOString(), new Date(now).toISOString(), config.cameraId, pool, {
        seconds: config.recapSeconds,
        timezone: config.timezone,
        tzLabel: config.tzLabel,
        minLuma: config.minLuma,
        outputPath,
    });
    if (r.skipped) throw new Error(`recap skipped: ${r.reason}`);

    if (!opts.noSend) {
        await send({
            apiUrl: config.signalApiUrl,
            sender: config.signalSender,
            recipient: config.recapRecipient,
            filePath: r.file_path,
            message: `${config.cameraId} recap ${formatLocal(startMs, config.timezone)} to ${formatLocal(now, config.timezone)} ${config.tzLabel} (${config.recapSeconds} s)`,
        });
        log.info(`[recap] sent ${r.file_path}`);
    }
    return r;
}

async function main(argv) {
    const { Pool } = require('pg');
    const config = require('./config').load();
    const pool = new Pool({
        host: config.timescaleHost, database: config.timescaleDb,
        user: config.timescaleUser, password: config.timescalePassword, port: 5432,
    });
    try {
        const r = await runRecap(config, pool, { noSend: argv.includes('--no-send') });
        console.log(`[recap] done: ${JSON.stringify(r)}`);
    } finally {
        await pool.end();
    }
}

if (require.main === module) {
    main(process.argv.slice(2)).catch((e) => { console.error('[recap] fatal:', e); process.exit(1); });
}

module.exports = { pickEvenly, composeRecap, runRecap };
