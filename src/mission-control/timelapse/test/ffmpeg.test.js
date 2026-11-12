const { EventEmitter } = require('events');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');
const { createCanvas } = require('@napi-rs/canvas');
const { buildArgs, runFfmpeg } = require('../src/ffmpeg');

function fakeProc(closeCode, stderrChunks = []) {
    const proc = new EventEmitter();
    proc.stderr = new EventEmitter();
    setImmediate(() => {
        for (const c of stderrChunks) proc.stderr.emit('data', Buffer.from(c));
        proc.emit('close', closeCode);
    });
    return proc;
}

describe('buildArgs', () => {
    test('matches D-04 recipe, with frames re-timed to one per output frame', () => {
        expect(buildArgs('/tmp/list.txt', '/out/x.mp4', 12)).toEqual([
            '-y', '-f', 'concat', '-safe', '0', '-i', '/tmp/list.txt',
            '-vf', 'setpts=N/12/TB',
            '-c:v', 'libx264', '-crf', '23', '-preset', 'fast',
            '-pix_fmt', 'yuv420p', '-r', '12', '-f', 'mp4', '/out/x.mp4',
        ]);
    });
    test('default fps is 12', () => {
        const a = buildArgs('a.txt', 'b.mp4');
        expect(a[a.indexOf('-r') + 1]).toBe('12');
    });
});

describe('runFfmpeg', () => {
    test('resolves on exit 0', async () => {
        const spawn = jest.fn(() => fakeProc(0));
        await expect(runFfmpeg('a', 'b', 12, { spawn })).resolves.toBeUndefined();
        expect(spawn).toHaveBeenCalledWith('ffmpeg', expect.any(Array), expect.any(Object));
    });
    test('rejects with stderr tail on non-zero', async () => {
        const spawn = jest.fn(() => fakeProc(1, ['boom: bad input']));
        await expect(runFfmpeg('a', 'b', 12, { spawn })).rejects.toThrow(/exited 1.*boom: bad input/);
    });
});

// MUSHY-188: the concat demuxer gives each still a default 1/25 s, so output
// -r 12 alone dropped ~half the frames (prod 2026-11-11: 1439 in, 692 out).
const haveFfmpeg = spawnSync('ffmpeg', ['-version']).status === 0;
(haveFfmpeg ? describe : describe.skip)('runFfmpeg with real ffmpeg', () => {
    test('every input frame becomes exactly one output frame', async () => {
        const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tl-ffmpeg-'));
        const lines = [];
        for (let i = 0; i < 30; i++) {
            const c = createCanvas(64, 48);
            const ctx = c.getContext('2d');
            ctx.fillStyle = `rgb(${i * 8},0,0)`;
            ctx.fillRect(0, 0, 64, 48);
            const p = path.join(dir, `f${i}.jpg`);
            fs.writeFileSync(p, await c.encode('jpeg', 90));
            lines.push(`file '${p}'`);
        }
        fs.writeFileSync(path.join(dir, 'list.txt'), lines.join('\n') + '\n');
        const out = path.join(dir, 'out.mp4');
        await runFfmpeg(path.join(dir, 'list.txt'), out, 12);
        const frames = execFileSync('ffprobe', ['-v', 'error', '-count_frames', '-select_streams', 'v:0',
            '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', out]).toString().trim();
        expect(Number(frames)).toBe(30);
        fs.rmSync(dir, { recursive: true, force: true });
    }, 30000);
});
