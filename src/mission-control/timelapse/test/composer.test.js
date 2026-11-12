const { composeDay } = require('../src/composer');

function makePool(snapshotRows) {
    return {
        query: jest.fn(async (sql) => {
            if (/FROM snapshots/.test(sql)) return { rows: snapshotRows };
            return { rows: [] };
        }),
    };
}

function makeFs() {
    const writes = {};
    const renames = [];
    const unlinks = [];
    const rms = [];
    const mkdirs = [];
    return {
        writes, renames, unlinks, rms, mkdirs,
        promises: {
            mkdir: jest.fn(async (dir) => { mkdirs.push(dir); }),
            readFile: jest.fn(async (p) => Buffer.from(`fake-jpeg-${p}`)),
            writeFile: jest.fn(async (p, b) => { writes[p] = b; }),
            rename: jest.fn(async (a, b) => { renames.push([a, b]); }),
            unlink: jest.fn(async (p) => { unlinks.push(p); }),
            rm: jest.fn(async (p) => { rms.push(p); }),
        },
    };
}

const noopLog = { info: () => {}, warn: () => {}, error: () => {} };

function baseDeps(overrides = {}) {
    const fs = makeFs();
    const runFfmpeg = jest.fn(async () => {});
    const burnOverlay = jest.fn(async (buf) => Buffer.concat([buf, Buffer.from('-burned')]));
    const db = {
        fetchTelemetry: jest.fn(async (pool, topic) => [{ topic }]),
        nearestValue: jest.fn((rows) => ({ 'fc.humidity': 88.5, 'fc.temperature': 19.4, 'fc.co2': 603 })[rows[0].topic]),
        insertTimelapse: jest.fn(async () => {}),
    };
    const meanLuma = jest.fn(async () => 120);
    return { fs, runFfmpeg, burnOverlay, meanLuma, db, log: noopLog, ...overrides };
}

describe('composeDay', () => {
    test('rejects bad camera_id (path traversal)', async () => {
        const pool = makePool([]);
        await expect(composeDay('2026-04-25', '../etc', pool, { deps: baseDeps() }))
            .rejects.toThrow(/Invalid camera_id/);
    });

    test('rejects bad date format', async () => {
        const pool = makePool([]);
        await expect(composeDay('not-a-date', 'fc1', pool, { deps: baseDeps() }))
            .rejects.toThrow(/Invalid date/);
    });

    test('skips when fewer than 3 frames (D-07)', async () => {
        const pool = makePool([
            { captured_at: new Date('2026-04-25T01:00:00Z'), file_path: '/x/a.jpg' },
            { captured_at: new Date('2026-04-25T02:00:00Z'), file_path: '/x/b.jpg' },
        ]);
        const deps = baseDeps();
        const r = await composeDay('2026-04-25', 'fc1', pool, { deps });
        expect(r.skipped).toBe(true);
        expect(r.reason).toBe('too_few_frames');
        expect(deps.runFfmpeg).not.toHaveBeenCalled();
        expect(deps.db.insertTimelapse).not.toHaveBeenCalled();
    });

    test('happy path composes 3+ frames, atomic-renames, inserts row', async () => {
        const rows = [
            { captured_at: new Date('2026-04-25T01:00:00Z'), file_path: '/x/a.jpg' },
            { captured_at: new Date('2026-04-25T02:00:00Z'), file_path: '/x/b.jpg' },
            { captured_at: new Date('2026-04-25T03:00:00Z'), file_path: '/x/c.jpg' },
        ];
        const pool = makePool(rows);
        const deps = baseDeps();
        const r = await composeDay('2026-04-25', 'fc1', pool, {
            deps,
            timelapseDir: '/data/timelapse',
            workRoot: '/tmp/work',
            fps: 12,
        });

        expect(deps.burnOverlay).toHaveBeenCalledTimes(3);
        expect(deps.runFfmpeg).toHaveBeenCalledTimes(1);
        // Atomic rename: tmp -> final
        expect(deps.fs.renames).toEqual([
            ['/data/timelapse/fc1/2026-04-25.mp4.tmp', '/data/timelapse/fc1/2026-04-25.mp4'],
        ]);
        // Registry insert
        expect(deps.db.insertTimelapse).toHaveBeenCalledWith(pool, {
            camera_id: 'fc1',
            date: '2026-04-25',
            file_path: '/data/timelapse/fc1/2026-04-25.mp4',
            frames_used: 3,
            duration_sec: 3 / 12,
        });
        // Workdir cleaned
        expect(deps.fs.rms.length).toBeGreaterThanOrEqual(1);

        expect(r.frames_used).toBe(3);
        expect(r.file_path).toBe('/data/timelapse/fc1/2026-04-25.mp4');
    });

    test('ffmpeg failure cleans .tmp and rethrows', async () => {
        const rows = [
            { captured_at: new Date('2026-04-25T01:00:00Z'), file_path: '/x/a.jpg' },
            { captured_at: new Date('2026-04-25T02:00:00Z'), file_path: '/x/b.jpg' },
            { captured_at: new Date('2026-04-25T03:00:00Z'), file_path: '/x/c.jpg' },
        ];
        const pool = makePool(rows);
        const deps = baseDeps({ runFfmpeg: jest.fn(async () => { throw new Error('ffmpeg boom'); }) });
        await expect(composeDay('2026-04-25', 'fc1', pool, { deps, workRoot: '/tmp/w' }))
            .rejects.toThrow(/ffmpeg boom/);
        expect(deps.fs.unlinks).toContain('/data/timelapse/fc1/2026-04-25.mp4.tmp');
        expect(deps.db.insertTimelapse).not.toHaveBeenCalled();
        // Workdir still cleaned (try/finally)
        expect(deps.fs.rms.length).toBeGreaterThanOrEqual(1);
    });

    test('missing frame file (ENOENT) is skipped, others compose', async () => {
        const rows = [
            { captured_at: new Date('2026-04-25T01:00:00Z'), file_path: '/x/a.jpg' },
            { captured_at: new Date('2026-04-25T02:00:00Z'), file_path: '/x/b.jpg' },
            { captured_at: new Date('2026-04-25T03:00:00Z'), file_path: '/x/c.jpg' },
            { captured_at: new Date('2026-04-25T04:00:00Z'), file_path: '/x/d.jpg' },
        ];
        const pool = makePool(rows);
        const deps = baseDeps();
        deps.fs.promises.readFile = jest.fn(async (p) => {
            if (p === '/x/b.jpg') { const e = new Error('nope'); e.code = 'ENOENT'; throw e; }
            return Buffer.from('ok');
        });
        const r = await composeDay('2026-04-25', 'fc1', pool, { deps });
        expect(r.frames_used).toBe(3);
        expect(deps.burnOverlay).toHaveBeenCalledTimes(3);
    });

    test('writes correctly-quoted concat filelist', async () => {
        const rows = [
            { captured_at: new Date('2026-04-25T01:00:00Z'), file_path: '/x/a.jpg' },
            { captured_at: new Date('2026-04-25T02:00:00Z'), file_path: '/x/b.jpg' },
            { captured_at: new Date('2026-04-25T03:00:00Z'), file_path: '/x/c.jpg' },
        ];
        const pool = makePool(rows);
        const deps = baseDeps();
        await composeDay('2026-04-25', 'fc1', pool, { deps, workRoot: '/tmp/w' });
        const filelistEntry = Object.entries(deps.fs.writes).find(([k]) => k.endsWith('filelist.txt'));
        expect(filelistEntry).toBeDefined();
        const content = filelistEntry[1].toString();
        expect(content).toMatch(/^file '\/tmp\/w\/fc1\/2026-04-25\/frame_0001\.jpg'\nfile '\/tmp\/w\/fc1\/2026-04-25\/frame_0002\.jpg'\nfile '\/tmp\/w\/fc1\/2026-04-25\/frame_0003\.jpg'\n$/);
    });

    // MUSHY-188 ---------------------------------------------------------------
    const threeRows = () => [
        { captured_at: new Date('2026-11-11T21:00:00Z'), file_path: '/x/a.jpg' },
        { captured_at: new Date('2026-11-11T21:01:00Z'), file_path: '/x/b.jpg' },
        { captured_at: new Date('2026-11-11T21:02:00Z'), file_path: '/x/c.jpg' },
    ];

    test('selects snapshots by LOCAL day bounds', async () => {
        const pool = makePool(threeRows());
        await composeDay('2026-11-11', 'fc1', pool, { deps: baseDeps(), timezone: 'America/Montevideo' });
        const snapCall = pool.query.mock.calls.find(([sql]) => /FROM snapshots/.test(sql));
        expect(snapCall[1]).toEqual(['fc1', '2026-11-11T03:00:00.000Z', '2026-11-12T03:00:00.000Z']);
    });

    test('fetches RH, T and CO2 over the same local day', async () => {
        const pool = makePool(threeRows());
        const deps = baseDeps();
        await composeDay('2026-11-11', 'fc1', pool, { deps, timezone: 'America/Montevideo' });
        const topics = deps.db.fetchTelemetry.mock.calls.map((c) => [c[1], c[2], c[3]]);
        expect(topics).toEqual([
            ['fc.humidity', '2026-11-11T03:00:00.000Z', '2026-11-12T03:00:00.000Z'],
            ['fc.temperature', '2026-11-11T03:00:00.000Z', '2026-11-12T03:00:00.000Z'],
            ['fc.co2', '2026-11-11T03:00:00.000Z', '2026-11-12T03:00:00.000Z'],
        ]);
    });

    test('burns local time + label + readings', async () => {
        const pool = makePool(threeRows());
        const deps = baseDeps();
        await composeDay('2026-11-11', 'fc1', pool, { deps, timezone: 'America/Montevideo', tzLabel: 'UYT' });
        expect(deps.burnOverlay.mock.calls[0][1]).toEqual({
            text: '2026-11-11 18:00 UYT  RH 88.5%  T 19.4°C  CO₂ 603 ppm',
        });
    });

    test('drops frames darker than minLuma before burning', async () => {
        const rows = [...threeRows(), { captured_at: new Date('2026-11-11T21:03:00Z'), file_path: '/x/dark.jpg' }];
        const pool = makePool(rows);
        const deps = baseDeps();
        deps.fs.promises.readFile = jest.fn(async (p) => Buffer.from(p));
        deps.meanLuma = jest.fn(async (buf) => (buf.toString() === '/x/dark.jpg' ? 8 : 120));
        const r = await composeDay('2026-11-11', 'fc1', pool, { deps, minLuma: 50 });
        expect(deps.burnOverlay).toHaveBeenCalledTimes(3);
        expect(r.frames_used).toBe(3);
        expect(r.frames_dark).toBe(1);
    });

    test('an all-dark day is skipped, not encoded', async () => {
        const pool = makePool(threeRows());
        const deps = baseDeps({ meanLuma: jest.fn(async () => 3) });
        const r = await composeDay('2026-11-11', 'fc1', pool, { deps, minLuma: 50 });
        expect(r).toMatchObject({ skipped: true, reason: 'too_few_usable_frames' });
        expect(deps.runFfmpeg).not.toHaveBeenCalled();
    });

    test('minLuma 0 keeps every frame and never measures', async () => {
        const pool = makePool(threeRows());
        const deps = baseDeps({ meanLuma: jest.fn(async () => 0) });
        const r = await composeDay('2026-11-11', 'fc1', pool, { deps, minLuma: 0 });
        expect(r.frames_used).toBe(3);
        expect(deps.meanLuma).not.toHaveBeenCalled();
    });
});

