// Phase 23: composeDay pipeline. Pure DI module — pool, fs, runFfmpeg, burnOverlay injected.
const path = require('path');

const { localDayBounds, formatLocal } = require('./localday');
const overlay = require('./overlay');

const defaultDeps = {
    fs: require('fs'),
    runFfmpeg: require('./ffmpeg').runFfmpeg,
    burnOverlay: overlay.burnOverlay,
    meanLuma: overlay.meanLuma,
    db: require('./db'),
    log: console,
};

const SAFE_CAMERA_ID = /^[a-zA-Z0-9_-]+$/;

const TOPICS = { rh: 'fc.humidity', temp: 'fc.temperature', co2: 'fc.co2' };

function pad4(n) { return String(n).padStart(4, '0'); }

async function composeDay(date, cameraId, pool, opts = {}) {
    const deps = { ...defaultDeps, ...(opts.deps || {}) };
    const { fs, runFfmpeg, burnOverlay, meanLuma, db, log } = deps;
    const fps = opts.fps || 12;
    const timezone = opts.timezone || 'America/Montevideo';
    const tzLabel = opts.tzLabel || 'UYT';
    const minLuma = opts.minLuma ?? 0;
    const timelapseDir = opts.timelapseDir || '/data/timelapse';
    const workRoot = opts.workRoot || '/tmp/timelapse_work';

    // T-23-T1: path-traversal guard.
    if (!SAFE_CAMERA_ID.test(cameraId)) {
        throw new Error(`Invalid camera_id: ${cameraId}`);
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
        throw new Error(`Invalid date: ${date}`);
    }

    // MUSHY-188: `date` is a LOCAL date; the file is named after it.
    const [start, end] = localDayBounds(date, timezone);
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

    const series = {};
    for (const [key, topic] of Object.entries(TOPICS)) {
        series[key] = await db.fetchTelemetry(pool, topic, start, end);
    }

    const workDir = path.join(workRoot, cameraId, date);
    const outputDir = path.join(timelapseDir, cameraId);
    const outputPath = path.join(outputDir, `${date}.mp4`);
    const tmpOutPath = `${outputPath}.tmp`;

    try {
        await fs.promises.mkdir(workDir, { recursive: true });
        await fs.promises.mkdir(outputDir, { recursive: true });

        const filelistLines = [];
        let framesDark = 0;
        for (let i = 0; i < frames.length; i++) {
            const f = frames[i];
            const frameTsMs = f.captured_at instanceof Date
                ? f.captured_at.getTime()
                : new Date(f.captured_at).getTime();

            let burned;
            try {
                const inputBuf = await fs.promises.readFile(f.file_path);
                // MUSHY-188: drop lights-off frames. File size can't tell them apart
                // (dim dawn frames outweigh foggy lit ones); mean luma can.
                if (minLuma > 0 && await meanLuma(inputBuf) < minLuma) {
                    framesDark++;
                    continue;
                }
                const text = overlay.barText({
                    timestamp: formatLocal(frameTsMs, timezone),
                    tzLabel,
                    rh: db.nearestValue(series.rh, frameTsMs),
                    temp: db.nearestValue(series.temp, frameTsMs),
                    co2: db.nearestValue(series.co2, frameTsMs),
                });
                burned = await burnOverlay(inputBuf, { text });
            } catch (e) {
                if (e.code === 'ENOENT') {
                    log.warn(`[composer] missing frame ${f.file_path}, skipping`);
                    continue;
                }
                throw e;
            }

            const burnedPath = path.join(workDir, `frame_${pad4(filelistLines.length + 1)}.jpg`);
            await fs.promises.writeFile(burnedPath, burned);
            filelistLines.push(`file '${burnedPath}'`);
        }

        if (filelistLines.length < 3) {
            log.warn(`[composer] ${cameraId} ${date}: only ${filelistLines.length} usable frames (${framesDark} dark), skipping`);
            return { skipped: true, reason: 'too_few_usable_frames', frames_found: filelistLines.length, frames_dark: framesDark };
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

        log.info(`[composer] ${cameraId} ${date}: ${framesUsed} frames (${framesDark} dark dropped) -> ${outputPath} (${durationSec.toFixed(2)}s)`);
        return { frames_used: framesUsed, frames_dark: framesDark, duration_sec: durationSec, file_path: outputPath };
    } finally {
        try { await fs.promises.rm(workDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
    }
}

module.exports = { composeDay, SAFE_CAMERA_ID };
