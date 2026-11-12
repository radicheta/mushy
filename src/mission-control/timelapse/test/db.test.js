const db = require('../src/db');

function makeMockPool() {
    const calls = [];
    return {
        calls,
        query: jest.fn(async (sql, params) => {
            calls.push({ sql, params });
            return { rows: [] };
        }),
    };
}

describe('initDb', () => {
    test('creates timelapses table with composite PK', async () => {
        const pool = makeMockPool();
        await db.initDb(pool);
        expect(pool.calls[0].sql).toMatch(/CREATE TABLE IF NOT EXISTS timelapses/);
        expect(pool.calls[0].sql).toMatch(/PRIMARY KEY \(camera_id, date\)/);
    });
});

describe('insertTimelapse', () => {
    test('issues INSERT ... ON CONFLICT DO UPDATE', async () => {
        const pool = makeMockPool();
        await db.insertTimelapse(pool, { camera_id: 'fc1', date: '2026-04-25', file_path: '/x.mp4', frames_used: 100, duration_sec: 8.3 });
        expect(pool.calls[0].sql).toMatch(/INSERT INTO timelapses/);
        expect(pool.calls[0].sql).toMatch(/ON CONFLICT \(camera_id, date\) DO UPDATE/);
        expect(pool.calls[0].params).toEqual(['fc1', '2026-04-25', '/x.mp4', 100, 8.3]);
    });
});

describe('lookupTimelapse', () => {
    test('issues SELECT with camera_id+date params', async () => {
        const pool = makeMockPool();
        await db.lookupTimelapse(pool, 'fc1', '2026-04-25');
        expect(pool.calls[0].sql).toMatch(/SELECT file_path, duration_sec FROM timelapses/);
        expect(pool.calls[0].params).toEqual(['fc1', '2026-04-25']);
    });
    test('returns null when no rows', async () => {
        const pool = makeMockPool();
        const r = await db.lookupTimelapse(pool, 'fc1', '2026-04-25');
        expect(r).toBeNull();
    });
});

describe('fetchTelemetry', () => {
    test('queries one topic over [start, end) padded by the match tolerance', async () => {
        const pool = makeMockPool();
        await db.fetchTelemetry(pool, 'fc.co2', '2026-11-11T03:00:00.000Z', '2026-11-12T03:00:00.000Z');
        expect(pool.calls[0].sql).toMatch(/FROM telemetry/);
        expect(pool.calls[0].params).toEqual([
            'fc.co2', '2026-11-11T02:30:00.000Z', '2026-11-12T03:30:00.000Z',
        ]);
    });
});

describe('nearestValue', () => {
    const rows = [
        { captured_at: new Date('2026-04-25T12:00:00Z'), value: 80 },
        { captured_at: new Date('2026-04-25T12:05:00Z'), value: 82 },
        { captured_at: new Date('2026-04-25T12:10:00Z'), value: 84 },
    ];
    test('picks nearest by abs delta', () => {
        const ts = new Date('2026-04-25T12:06:00Z').getTime();
        expect(db.nearestValue(rows, ts)).toBe(82);
    });
    test('returns null when nearest > 30min', () => {
        const ts = new Date('2026-04-25T15:00:00Z').getTime();
        expect(db.nearestValue(rows, ts)).toBeNull();
    });
    test('empty rows -> null', () => {
        expect(db.nearestValue([], 0)).toBeNull();
    });
});
