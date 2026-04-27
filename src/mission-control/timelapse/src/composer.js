// Phase 23: composeDay pipeline. Pure DI module — pool, fs, runFfmpeg, burnOverlay injected.
const path = require('path');

const defaultDeps = {
    fs: require('fs'),
    runFfmpeg: require('./ffmpeg').runFfmpeg,
    burnOverlay: require('./overlay').burnOverlay,
    db: require('./db'),
    log: console,
};

const SAFE_CAMERA_ID = /^[a-zA-Z0-9_-]+$/;

function dayBoundsUtc(date) {
    return [`${date}T00:00:00.000Z`, `${date}T23:59:59.999Z`];
}

function pad4(n) { return String(n).padStart(4, '0'); }

async function composeDay(date, cameraId, pool, opts = {}) {
    const deps = { ...defaultDeps, ...(opts.deps || {}) };
    const { fs, runFfmpeg, burnOverlay, db, log } = deps;
    const fps = opts.fps || 12;
    const timelapseDir = opts.timelapseDir || '/data/timelapse';
    const workRoot = opts.workRoot || '/tmp/timelapse_work';

    // T-23-T1: path-traversal guard.
    if (!SAFE_CAMERA_ID.test(cameraId)) {
        throw new Error(`Invalid camera_id: ${cameraId}`);
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
        throw new Error(`Invalid date: ${date}`);
    }

    const [start, end] = dayBoundsUtc(date);
    const snapResult = await pool.query(
        `SELECT captured_at, file_path FROM snapshots
         WHERE camera_id=$1 AND captured_at >= $2 AND captured_at < $3
         ORDER BY captured_at ASC`,
        [cameraId, start, end]
    );
    const frames = snapResult.rows;

    if (frames.length < 3) {
        log.warn(`[composer] ${cameraId} ${date}: only ${frames.length} frames, skipping (D-07)`);
        return { skipped: true, reason: 'too_few_frames', frames_found: frames.length };
    }

    const rhRows = await db.fetchRhForDay(pool, date);

    const workDir = path.join(workRoot, cameraId, date);
    const outputDir = path.join(timelapseDir, cameraId);
    const outputPath = path.join(outputDir, `${date}.mp4`);
    const tmpOutPath = `${outputPath}.tmp`;

    try {
        await fs.promises.mkdir(workDir, { recursive: true });
        await fs.promises.mkdir(outputDir, { recursive: true });

        const filelistLines = [];
        for (let i = 0; i < frames.length; i++) {
            const f = frames[i];
            const frameTsMs = f.captured_at instanceof Date
                ? f.captured_at.getTime()
                : new Date(f.captured_at).getTime();
            const rh = db.nearestRh(rhRows, frameTsMs);

            const tsLabel = new Date(frameTsMs).toISOString().slice(0, 16).replace('T', ' ');
            let burned;
            try {
                const inputBuf = await fs.promises.readFile(f.file_path);
                burned = await burnOverlay(inputBuf, { timestamp: tsLabel, rh });
            } catch (e) {
                if (e.code === 'ENOENT') {
                    log.warn(`[composer] missing frame ${f.file_path}, skipping`);
                    continue;
                }
                throw e;
            }

            const burnedPath = path.join(workDir, `frame_${pad4(i + 1)}.jpg`);
            await fs.promises.writeFile(burnedPath, burned);
            filelistLines.push(`file '${burnedPath}'`);
        }

        if (filelistLines.length < 3) {
            log.warn(`[composer] ${cameraId} ${date}: only ${filelistLines.length} usable frames after read, skipping`);
            return { skipped: true, reason: 'too_few_usable_frames', frames_found: filelistLines.length };
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

        const framesUsed = filelistLines.length;
        const durationSec = framesUsed / fps;
        await db.insertTimelapse(pool, {
            camera_id: cameraId,
            date,
            file_path: outputPath,
            frames_used: framesUsed,
            duration_sec: durationSec,
        });

        log.info(`[composer] ${cameraId} ${date}: ${framesUsed} frames -> ${outputPath} (${durationSec.toFixed(2)}s)`);
        return { frames_used: framesUsed, duration_sec: durationSec, file_path: outputPath };
    } finally {
        try { await fs.promises.rm(workDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
    }
}

module.exports = { composeDay, SAFE_CAMERA_ID };
