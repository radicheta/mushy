// Phase 23 D-04: ffmpeg concat wrapper. Pure, spawn injectable for tests.
const { spawn: realSpawn } = require('child_process');

// Exact arg list per D-04 (VERIFIED in RESEARCH.md Pattern 2).
function buildArgs(filelistPath, outputPath, fps = 12) {
    return [
        '-y',
        '-f', 'concat',
        '-safe', '0',
        '-i', filelistPath,
        '-c:v', 'libx264',
        '-crf', '23',
        '-preset', 'fast',
        '-pix_fmt', 'yuv420p',
        '-r', String(fps),
        outputPath,
    ];
}

function runFfmpeg(filelistPath, outputPath, fps = 12, deps = {}) {
    const spawnFn = deps.spawn || realSpawn;
    const args = buildArgs(filelistPath, outputPath, fps);
    return new Promise((resolve, reject) => {
        const proc = spawnFn('ffmpeg', args, { stdio: ['ignore', 'pipe', 'pipe'] });
        let stderr = '';
        proc.stderr.on('data', (d) => { stderr += d.toString(); });
        proc.on('error', (err) => reject(err));
        proc.on('close', (code) => {
            if (code === 0) resolve();
            else reject(new Error(`ffmpeg exited ${code}: ${stderr.slice(-500)}`));
        });
    });
}

module.exports = { buildArgs, runFfmpeg };
