const { EventEmitter } = require('events');
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
    test('matches D-04 recipe exactly', () => {
        expect(buildArgs('/tmp/list.txt', '/out/x.mp4', 12)).toEqual([
            '-y', '-f', 'concat', '-safe', '0', '-i', '/tmp/list.txt',
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
