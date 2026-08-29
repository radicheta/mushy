// Phase 999.1 Plan 03: tests for the bridge-side buffer-replay poller.
// No live DB — pool.connect()/client.query is mocked. No live HTTP — fetchFn injected.
// Verifies:
//   - parseNdjson handles empty / multi-line / blank-line inputs
//   - load/save/advance roundtrip on a tmp state file
//   - pollOnce: empty body → 0 rows / no INSERT
//   - pollOnce: 2 rows → INSERTed with `ON CONFLICT (topic, time) DO NOTHING`, time
//     converted from time_ns / 1_000_000 ms, last-ts persisted to max(time_ns)
//   - pollOnce: idempotent — duplicate replays are no-ops at SQL level (the constraint
//     handles dedup; we just confirm pollOnce doesn't blow up when client.query resolves OK)
//   - pollOnce: timeout from fetchFn propagates to caller
//   - pollOnce: URL contains ?ts=<sinceNs>&limit=
//   - advanceLastIngested only advances forward, never backward

const fs = require('fs');
const os = require('os');
const path = require('path');

const {
    loadLastTs,
    saveLastTs,
    advanceLastIngested,
    parseNdjson,
    pollOnce
} = require('../src/buffer_replay');

function tmpStateFile(name) {
    return path.join(os.tmpdir(), `buffer_replay_test_${name}_${process.pid}_${Date.now()}_${Math.random().toString(36).slice(2)}.json`);
}

function makePool() {
    const queries = [];
    const client = {
        query: jest.fn(async (sql, params) => {
            queries.push({ sql, params });
            return { rows: [] };
        }),
        release: jest.fn()
    };
    return {
        queries,
        client,
        connect: jest.fn(async () => client)
    };
}

describe('parseNdjson', () => {
    test('empty string returns empty array', () => {
        expect(parseNdjson('')).toEqual([]);
    });

    test('three lines returns three objects', () => {
        const body = '{"a":1}\n{"a":2}\n{"a":3}\n';
        expect(parseNdjson(body)).toEqual([{ a: 1 }, { a: 2 }, { a: 3 }]);
    });

    test('skips blank lines', () => {
        const body = '{"a":1}\n\n{"a":2}\n\n';
        expect(parseNdjson(body)).toEqual([{ a: 1 }, { a: 2 }]);
    });
});

describe('loadLastTs / saveLastTs', () => {
    test('missing file returns 0', () => {
        const f = tmpStateFile('missing');
        expect(loadLastTs(f)).toBe(0);
    });

    test('save then load roundtrip', () => {
        const f = tmpStateFile('roundtrip');
        try {
            saveLastTs(f, 1234567890);
            expect(loadLastTs(f)).toBe(1234567890);
        } finally {
            try { fs.unlinkSync(f); } catch {}
        }
    });

    test('corrupt file returns 0', () => {
        const f = tmpStateFile('corrupt');
        try {
            fs.writeFileSync(f, 'not-json{{{');
            expect(loadLastTs(f)).toBe(0);
        } finally {
            try { fs.unlinkSync(f); } catch {}
        }
    });
});

describe('advanceLastIngested', () => {
    test('only advances forward', () => {
        const f = tmpStateFile('advance');
        try {
            saveLastTs(f, 1000);
            advanceLastIngested(f, 500);
            expect(loadLastTs(f)).toBe(1000);
            advanceLastIngested(f, 2000);
            expect(loadLastTs(f)).toBe(2000);
        } finally {
            try { fs.unlinkSync(f); } catch {}
        }
    });
});

describe('pollOnce', () => {
    test('empty response returns 0 rows and no inserts', async () => {
        const f = tmpStateFile('poll_empty');
        const pool = makePool();
        const fetchFn = jest.fn(async () => '');
        try {
            const r = await pollOnce({ pool, fc1Url: 'http://fc1:8765', stateFile: f, fetchFn });
            expect(r.rows).toBe(0);
            expect(pool.connect).not.toHaveBeenCalled();
            expect(fetchFn).toHaveBeenCalledTimes(1);
        } finally {
            try { fs.unlinkSync(f); } catch {}
        }
    });

    test('inserts with ON CONFLICT DO NOTHING and advances last-ts', async () => {
        const f = tmpStateFile('poll_insert');
        const pool = makePool();
        const body =
            '{"time_ns":1700000000000000000,"topic":"fc.humidity","value":91.2}\n' +
            '{"time_ns":1700000005000000000,"topic":"fc.temperature","value":22.4}\n';
        const fetchFn = jest.fn(async () => body);
        try {
            const r = await pollOnce({ pool, fc1Url: 'http://fc1:8765', stateFile: f, fetchFn });
            expect(r.rows).toBe(2);
            expect(r.maxTs).toBe(1700000005000000000);

            // BEGIN + 2 INSERTs + COMMIT
            const inserts = pool.queries.filter(q => /INSERT INTO telemetry/.test(q.sql));
            expect(inserts).toHaveLength(2);
            for (const ins of inserts) {
                expect(ins.sql).toMatch(/ON CONFLICT \(topic, time\) DO NOTHING/);
            }
            // MUSHY-118: replay must also skip a row the live path already wrote a
            // few ms earlier under its own clock (headerless topics have no shared
            // stamp, so ON CONFLICT alone cannot see those as the same row).
            for (const ins of inserts) {
                expect(ins.sql).toMatch(/WHERE NOT EXISTS/);
                expect(ins.sql).toMatch(/topic = \$2 AND value = \$3/);
                expect(ins.sql).toMatch(/interval '250 milliseconds'/);
            }
            // First INSERT: tsMs = 1700000000000000000 / 1_000_000 = 1700000000000
            expect(inserts[0].params[0]).toBe(1700000000000);
            expect(inserts[0].params[1]).toBe('fc.humidity');
            expect(inserts[0].params[2]).toBe(91.2);
            expect(inserts[1].params[0]).toBe(1700000005000);

            // last-ts persisted
            expect(loadLastTs(f)).toBe(1700000005000000000);

            // client released
            expect(pool.client.release).toHaveBeenCalled();
        } finally {
            try { fs.unlinkSync(f); } catch {}
        }
    });

    test('duplicate replay is silent (constraint handled server-side)', async () => {
        const f = tmpStateFile('poll_dup');
        const pool = makePool();
        const body = '{"time_ns":1700000000000000000,"topic":"fc.humidity","value":91.2}\n';
        const fetchFn = jest.fn(async () => body);
        try {
            // First poll
            const r1 = await pollOnce({ pool, fc1Url: 'http://fc1:8765', stateFile: f, fetchFn });
            expect(r1.rows).toBe(1);
            // Second identical poll — pool.client.query keeps returning {rows:[]} (no error)
            const r2 = await pollOnce({ pool, fc1Url: 'http://fc1:8765', stateFile: f, fetchFn });
            expect(r2.rows).toBe(1);
            // Did not throw — that's what "silent" means at this layer
        } finally {
            try { fs.unlinkSync(f); } catch {}
        }
    });

    test('fetch timeout propagates to caller', async () => {
        const f = tmpStateFile('poll_timeout');
        const pool = makePool();
        const fetchFn = jest.fn(async () => { throw new Error('timeout'); });
        try {
            await expect(
                pollOnce({ pool, fc1Url: 'http://fc1:8765', stateFile: f, fetchFn })
            ).rejects.toThrow('timeout');
            expect(pool.connect).not.toHaveBeenCalled();
        } finally {
            try { fs.unlinkSync(f); } catch {}
        }
    });

    test('URL contains ?ts=<sinceNs>&limit=', async () => {
        const f = tmpStateFile('poll_url');
        const pool = makePool();
        let capturedUrl = null;
        const fetchFn = jest.fn(async (url) => { capturedUrl = url; return ''; });
        try {
            saveLastTs(f, 42);
            await pollOnce({ pool, fc1Url: 'http://fc1:8765', stateFile: f, fetchFn });
            expect(capturedUrl).toContain('?ts=42');
            expect(capturedUrl).toMatch(/&limit=\d+/);
        } finally {
            try { fs.unlinkSync(f); } catch {}
        }
    });

    test('rolls back on insert failure and surfaces error', async () => {
        const f = tmpStateFile('poll_rollback');
        const pool = makePool();
        // Make INSERT throw to verify ROLLBACK + release
        pool.client.query = jest.fn(async (sql) => {
            pool.queries.push({ sql });
            if (sql.startsWith('INSERT')) throw new Error('db boom');
            return { rows: [] };
        });
        const body = '{"time_ns":1700000000000000000,"topic":"fc.humidity","value":91.2}\n';
        const fetchFn = jest.fn(async () => body);
        try {
            await expect(
                pollOnce({ pool, fc1Url: 'http://fc1:8765', stateFile: f, fetchFn })
            ).rejects.toThrow('db boom');
            const sqls = pool.queries.map(q => q.sql);
            expect(sqls).toContain('BEGIN');
            expect(sqls).toContain('ROLLBACK');
            expect(pool.client.release).toHaveBeenCalled();
            // last-ts NOT advanced on failure
            expect(loadLastTs(f)).toBe(0);
        } finally {
            try { fs.unlinkSync(f); } catch {}
        }
    });
});
