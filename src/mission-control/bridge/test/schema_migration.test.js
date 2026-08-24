// Phase 999.1 Plan 01: tests for the telemetry UNIQUE (topic, time) migration.
// No live DB — pool.query is mocked. Verifies:
//   1. applyTelemetryUniqueConstraint runs the named-constraint DDL.
//   2. Running it twice does not throw (idempotent — relies on the pg DO $$ IF NOT EXISTS guard).
//   3. findTopicTimeDuplicates returns rows for (topic, time) duplicates, [] otherwise.

const fs = require('fs');
const path = require('path');
const {
    applyTelemetryUniqueConstraint,
    findTopicTimeDuplicates,
    telemetryUniqueConstraintExists
} = require('../src/schema_migration');

function makePool(rowsByPattern = {}) {
    const calls = [];
    return {
        calls,
        query: jest.fn(async (sql, params) => {
            calls.push({ sql, params });
            for (const [pattern, rows] of Object.entries(rowsByPattern)) {
                if (sql.includes(pattern)) return { rows };
            }
            return { rows: [] };
        })
    };
}

describe('applyTelemetryUniqueConstraint', () => {
    test('runs migration SQL referencing the named constraint', async () => {
        const pool = makePool();
        await applyTelemetryUniqueConstraint(pool);
        expect(pool.query).toHaveBeenCalledTimes(1);
        const sql = pool.calls[0].sql;
        expect(sql).toContain('telemetry_topic_time_unique');
        expect(sql).toContain('UNIQUE (topic, time)');
        // Wrapped in DO $$ ... IF NOT EXISTS ... END $$ idempotency block
        expect(sql).toMatch(/DO \$\$/);
        expect(sql).toContain('IF NOT EXISTS');
        expect(sql).toContain('pg_constraint');
    });

    test('is idempotent — running twice does not throw', async () => {
        const pool = makePool();
        await applyTelemetryUniqueConstraint(pool);
        await expect(applyTelemetryUniqueConstraint(pool)).resolves.not.toThrow();
        expect(pool.query).toHaveBeenCalledTimes(2);
    });
});

describe('findTopicTimeDuplicates', () => {
    test('returns [] when no duplicates', async () => {
        const pool = makePool({ 'GROUP BY 1,2': [] });
        const out = await findTopicTimeDuplicates(pool, 5);
        expect(out).toEqual([]);
    });

    test('returns rows when duplicates present', async () => {
        const dupRows = [
            { topic: 'fc.humidity', time: '2026-05-01T00:00:00Z', n: 3 },
            { topic: 'fc.co2',      time: '2026-05-01T00:00:01Z', n: 2 }
        ];
        const pool = makePool({ 'GROUP BY 1,2': dupRows });
        const out = await findTopicTimeDuplicates(pool, 5);
        expect(out).toEqual(dupRows);
    });

    test('issues the documented HAVING/COUNT query with limit param', async () => {
        const pool = makePool();
        await findTopicTimeDuplicates(pool, 7);
        const { sql, params } = pool.calls[0];
        expect(sql).toContain('SELECT topic, time, COUNT(*) AS n FROM telemetry');
        expect(sql).toContain('GROUP BY 1,2 HAVING COUNT(*) > 1');
        expect(sql).toContain('ORDER BY n DESC LIMIT $1');
        expect(params).toEqual([7]);
    });

    test('default limit is 5', async () => {
        const pool = makePool();
        await findTopicTimeDuplicates(pool);
        expect(pool.calls[0].params).toEqual([5]);
    });
});

// MUSHY-113 -- the dedupe scan is a full GROUP BY over the telemetry hypertable
// (155s measured on 91M rows / 21GB) and was running on every bridge boot. Once
// the UNIQUE constraint exists the database makes duplicates impossible, so the
// scan cannot find anything and must be skipped.
describe('MUSHY-113 dedupe scan is skipped once the constraint exists', () => {
    test('telemetryUniqueConstraintExists is true when pg_constraint has the row', async () => {
        const pool = makePool({ 'pg_constraint': [{ '?column?': 1 }] });
        await expect(telemetryUniqueConstraintExists(pool)).resolves.toBe(true);
    });

    test('telemetryUniqueConstraintExists is false when it does not', async () => {
        const pool = makePool();
        await expect(telemetryUniqueConstraintExists(pool)).resolves.toBe(false);
    });

    test('it asks the catalog by constraint name, not by scanning telemetry', async () => {
        const pool = makePool();
        await telemetryUniqueConstraintExists(pool);
        const sql = pool.calls[0].sql;
        expect(sql).toContain('pg_constraint');
        expect(sql).toContain('telemetry_topic_time_unique');
        expect(sql).not.toMatch(/FROM telemetry/i);
        expect(sql).not.toMatch(/GROUP BY/i);
    });

    // Source-level, same reason as the other index.js guards: index.js opens
    // sockets at require() time and cannot be imported. Without this, deleting
    // the gate would leave every unit test above passing and restore the 155s.
    test('index.js gates the dedupe scan on the constraint check', () => {
        const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'index.js'), 'utf8');
        const gate = src.indexOf('migration.telemetryUniqueConstraintExists(pool)');
        const scan = src.indexOf('migration.findTopicTimeDuplicates(pool');
        expect(gate).toBeGreaterThan(-1);
        expect(scan).toBeGreaterThan(gate);
        // The scan sits in the else branch, so it is unreachable when the
        // constraint is already there.
        expect(src.slice(gate, scan)).toContain('} else {');
    });
});
