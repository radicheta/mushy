const { clampRetentionDays, shouldPrune, runPrune } = require('../src/retention');
const silent = { log: () => {}, error: () => {} };

describe('clampRetentionDays', () => {
    test('29 -> 30', () => expect(clampRetentionDays(29)).toBe(30));
    test('365 -> 365', () => expect(clampRetentionDays(365)).toBe(365));
    test('0 -> 30', () => expect(clampRetentionDays(0)).toBe(30));
    test('NaN -> 30', () => expect(clampRetentionDays('abc')).toBe(30));
    test('"365" -> 365', () => expect(clampRetentionDays('365')).toBe(365));
});

describe('shouldPrune', () => {
    test('null -> false', () => expect(shouldPrune({ oldestDays: null, graceDays: 30 })).toBe(false));
    test('undefined -> false', () => expect(shouldPrune({ oldestDays: undefined, graceDays: 30 })).toBe(false));
    test('15 days under grace -> false', () => expect(shouldPrune({ oldestDays: 15, graceDays: 30 })).toBe(false));
    test('30 days boundary -> true', () => expect(shouldPrune({ oldestDays: 30, graceDays: 30 })).toBe(true));
    test('40 days -> true', () => expect(shouldPrune({ oldestDays: 40, graceDays: 30 })).toBe(true));
});

function makePool(oldestDays, expiredPaths) {
    const calls = [];
    return {
        calls,
        query: jest.fn(async (sql) => {
            calls.push(sql.trim().slice(0, 40));
            if (sql.includes('MIN(captured_at)')) return { rows: [{ days: oldestDays }] };
            if (sql.includes('WHERE captured_at <')) return { rows: expiredPaths.map(p => ({ file_path: p })) };
            if (sql.startsWith('DELETE FROM snapshots')) return { rowCount: 1 };
            return { rows: [] };
        })
    };
}
function makeFs(behavior) {
    return {
        promises: {
            unlink: jest.fn(async (p) => {
                const b = behavior[p];
                if (b === 'ENOENT') { const e = new Error('nope'); e.code = 'ENOENT'; throw e; }
                if (b === 'EACCES') { const e = new Error('denied'); e.code = 'EACCES'; throw e; }
            })
        }
    };
}
const now = () => new Date('2026-04-19T00:00:00Z').getTime();

describe('runPrune', () => {
    test('skips under grace', async () => {
        const pool = makePool(10, ['/a.jpg']);
        const fs = makeFs({});
        const r = await runPrune({ pool, fs, now, retentionDays: 365, graceDays: 30, log: silent });
        expect(r.skipped).toBe(true);
        expect(fs.promises.unlink).not.toHaveBeenCalled();
    });

    test('deletes file then row for each expired', async () => {
        const paths = ['/a.jpg', '/b.jpg', '/c.jpg'];
        const pool = makePool(400, paths);
        const fs = makeFs({ '/a.jpg': 'ok', '/b.jpg': 'ok', '/c.jpg': 'ok' });
        const r = await runPrune({ pool, fs, now, retentionDays: 365, graceDays: 30, log: silent });
        expect(r.deleted).toBe(3);
        expect(r.failed).toBe(0);
        expect(fs.promises.unlink).toHaveBeenCalledTimes(3);
        const deletes = pool.calls.filter(s => s.startsWith('DELETE FROM snapshots'));
        expect(deletes).toHaveLength(3);
    });

    test('ENOENT treated as success', async () => {
        const pool = makePool(400, ['/gone.jpg']);
        const fs = makeFs({ '/gone.jpg': 'ENOENT' });
        const r = await runPrune({ pool, fs, now, retentionDays: 365, graceDays: 30, log: silent });
        expect(r.deleted).toBe(1);
        expect(r.failed).toBe(0);
        const deletes = pool.calls.filter(s => s.startsWith('DELETE FROM snapshots'));
        expect(deletes).toHaveLength(1);
    });

    test('EACCES keeps row', async () => {
        const pool = makePool(400, ['/locked.jpg']);
        const fs = makeFs({ '/locked.jpg': 'EACCES' });
        const r = await runPrune({ pool, fs, now, retentionDays: 365, graceDays: 30, log: silent });
        expect(r.deleted).toBe(0);
        expect(r.failed).toBe(1);
        const deletes = pool.calls.filter(s => s.startsWith('DELETE FROM snapshots'));
        expect(deletes).toHaveLength(0);
    });
});
