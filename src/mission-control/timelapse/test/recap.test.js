const { pickEvenly, composeRecap, runRecap } = require('../src/recap');
const { sendVideo } = require('../src/signal');

const noopLog = { info: () => {}, warn: () => {}, error: () => {} };

function makeFrames(n) {
    const t0 = Date.parse('2026-11-14T11:00:00Z');
    return Array.from({ length: n }, (_, i) => ({
        captured_at: new Date(t0 + i * 60000),
        file_path: `/snap/${i}.jpg`,
    }));
}

function makePool(rows) {
    return { query: jest.fn(async (sql) => (/FROM snapshots/.test(sql) ? { rows } : { rows: [] })) };
}

function baseDeps(overrides = {}) {
    const writes = {};
    const renames = [];
    const fs = {
        writes, renames,
        promises: {
            mkdir: jest.fn(async () => {}),
            readFile: jest.fn(async (p) => Buffer.from(p)),
            writeFile: jest.fn(async (p, b) => { writes[p] = b; }),
            rename: jest.fn(async (a, b) => { renames.push([a, b]); }),
            unlink: jest.fn(async () => {}),
            rm: jest.fn(async () => {}),
        },
    };
    return {
        fs,
        runFfmpeg: jest.fn(async () => {}),
        burnOverlay: jest.fn(async (buf) => buf),
        meanLuma: jest.fn(async () => 120),
        db: { fetchTelemetry: jest.fn(async () => []), nearestValue: jest.fn(() => null) },
        log: noopLog,
        ...overrides,
    };
}

const START = '2026-11-14T11:00:00.000Z';
const END = '2026-11-16T23:30:00.000Z';

describe('pickEvenly', () => {
    test('returns everything when there are no more than n', () => {
        expect(pickEvenly([1, 2, 3], 5)).toEqual([1, 2, 3]);
    });

    test('picks n distinct items in order, first and last included', () => {
        const arr = Array.from({ length: 1000 }, (_, i) => i);
        const out = pickEvenly(arr, 120);
        expect(out).toHaveLength(120);
        expect(out[0]).toBe(0);
        expect(out[119]).toBe(999);
        expect(new Set(out).size).toBe(120);
        expect([...out].sort((a, b) => a - b)).toEqual(out);
    });
});

describe('composeRecap', () => {
    test('rejects bad camera_id', async () => {
        await expect(composeRecap(START, END, '../etc', makePool([]), { deps: baseDeps() }))
            .rejects.toThrow(/Invalid camera_id/);
    });

    test('many frames -> exactly seconds*fps frames, whatever the window length', async () => {
        for (const n of [800, 5000]) {
            const deps = baseDeps();
            const r = await composeRecap(START, END, 'fc1', makePool(makeFrames(n)), {
                deps, seconds: 5, fps: 24, outputPath: '/out/recap.mp4',
            });
            expect(r.frames_used).toBe(120);
            expect(r.duration_sec).toBe(5);
            expect(r.frames_total).toBe(n);
            expect(deps.runFfmpeg).toHaveBeenCalledWith(expect.stringMatching(/filelist\.txt$/), '/out/recap.mp4.tmp', 24);
            expect(deps.fs.renames).toEqual([['/out/recap.mp4.tmp', '/out/recap.mp4']]);
            // luma is only measured on a bounded candidate set, not on every frame
            expect(deps.meanLuma.mock.calls.length).toBeLessThanOrEqual(600);
        }
    });

    test('dark frames are dropped and the lit ones still fill the video', async () => {
        const frames = makeFrames(2000);
        // second half of the window is lights-off
        const deps = baseDeps({
            meanLuma: jest.fn(async (buf) => (Number(/(\d+)\.jpg/.exec(buf.toString())[1]) < 1000 ? 120 : 5)),
        });
        const r = await composeRecap(START, END, 'fc1', makePool(frames), {
            deps, seconds: 5, fps: 24, minLuma: 50, outputPath: '/out/recap.mp4',
        });
        expect(r.frames_used).toBe(120);
        const burned = deps.burnOverlay.mock.calls.map((c) => Number(/(\d+)\.jpg/.exec(c[0].toString())[1]));
        expect(Math.max(...burned)).toBeLessThan(1000);
    });

    test('skips when fewer than 3 usable frames', async () => {
        const deps = baseDeps({ meanLuma: jest.fn(async () => 5) });
        const r = await composeRecap(START, END, 'fc1', makePool(makeFrames(500)), {
            deps, minLuma: 50, outputPath: '/out/recap.mp4',
        });
        expect(r.skipped).toBe(true);
        expect(deps.runFfmpeg).not.toHaveBeenCalled();
    });
});

describe('sendVideo', () => {
    test('posts the file as a base64 attachment to /v2/send', async () => {
        const fetch = jest.fn(async () => ({ ok: true, status: 201, text: async () => '{"timestamp":"1"}' }));
        const fs = { promises: { readFile: jest.fn(async () => Buffer.from('VIDEO')) } };
        await sendVideo({
            apiUrl: 'http://localhost:8085', sender: '+100', recipient: '+200',
            filePath: '/out/2026-11-16.mp4', message: 'hi',
        }, { fetch, fs });
        const [url, init] = fetch.mock.calls[0];
        expect(url).toBe('http://localhost:8085/v2/send');
        const body = JSON.parse(init.body);
        expect(body.number).toBe('+100');
        expect(body.recipients).toEqual(['+200']);
        expect(body.message).toBe('hi');
        expect(body.base64_attachments).toEqual([
            `data:video/mp4;filename=2026-11-16.mp4;base64,${Buffer.from('VIDEO').toString('base64')}`,
        ]);
    });

    test('throws with status and body when signal-cli refuses', async () => {
        const fetch = jest.fn(async () => ({ ok: false, status: 400, text: async () => 'nope' }));
        const fs = { promises: { readFile: jest.fn(async () => Buffer.from('V')) } };
        await expect(sendVideo({ apiUrl: 'http://x', sender: 'a', recipient: 'b', filePath: '/f.mp4', message: '' }, { fetch, fs }))
            .rejects.toThrow(/400.*nope/);
    });
});

describe('runRecap', () => {
    const config = {
        recapStart: '2026-11-14T08:00:00-03:00', recapSeconds: 5, recapRecipient: '+200',
        signalApiUrl: 'http://localhost:8085', signalSender: '+100',
        cameraId: 'fc1', timelapseDir: '/data/timelapse', timezone: 'America/Montevideo', tzLabel: 'UYT', minLuma: 50,
    };
    const now = Date.parse('2026-11-16T23:30:00Z'); // 20:30 UYT

    test('composes [recapStart, now) into recap/<local date>.mp4 and sends it', async () => {
        const compose = jest.fn(async (start, end, cam, pool, opts) => ({ file_path: opts.outputPath, frames_used: 120, duration_sec: 5 }));
        const send = jest.fn(async () => {});
        await runRecap(config, {}, { now, compose, send, log: noopLog });
        const [start, end, cam, , opts] = compose.mock.calls[0];
        expect(start).toBe('2026-11-14T11:00:00.000Z');
        expect(end).toBe('2026-11-16T23:30:00.000Z');
        expect(cam).toBe('fc1');
        expect(opts.outputPath).toBe('/data/timelapse/fc1/recap/2026-11-16.mp4');
        expect(opts.seconds).toBe(5);
        expect(send).toHaveBeenCalledWith(expect.objectContaining({
            apiUrl: 'http://localhost:8085', sender: '+100', recipient: '+200',
            filePath: '/data/timelapse/fc1/recap/2026-11-16.mp4',
            message: 'fc1 recap 2026-11-14 08:00 to 2026-11-16 20:30 UYT (5 s)',
        }));
    });

    test('does not send when the compose was skipped, and throws so the failure is visible', async () => {
        const compose = jest.fn(async () => ({ skipped: true, reason: 'too_few_usable_frames' }));
        const send = jest.fn();
        await expect(runRecap(config, {}, { now, compose, send, log: noopLog })).rejects.toThrow(/too_few_usable_frames/);
        expect(send).not.toHaveBeenCalled();
    });

    test('send:false composes without sending', async () => {
        const compose = jest.fn(async (s, e, c, p, opts) => ({ file_path: opts.outputPath, frames_used: 120, duration_sec: 5 }));
        const send = jest.fn();
        await runRecap(config, {}, { now, compose, send, log: noopLog, noSend: true });
        expect(send).not.toHaveBeenCalled();
    });
});
