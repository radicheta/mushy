const { bucketInterval, TELEMETRY_MAX_RANGE_MS } = require('../src/history_buckets');

const H = 3600000;
const D = 24 * H;

describe('telemetry /history range cap (MUSHY-179)', () => {
    test('a 42-day range is allowed', () => {
        expect(42 * D).toBeLessThanOrEqual(TELEMETRY_MAX_RANGE_MS);
    });
    test('a full year (leap year included) is allowed', () => {
        expect(366 * D).toBeLessThanOrEqual(TELEMETRY_MAX_RANGE_MS);
    });
    test('more than a year is refused', () => {
        expect(367 * D).toBeGreaterThan(TELEMETRY_MAX_RANGE_MS);
    });
});

describe('bucketInterval', () => {
    test.each([
        [1 * H, '5 seconds'],
        [2 * H, '5 seconds'],
        [12 * H, '1 minute'],
        [24 * H, '1 minute'],
        [3 * D, '10 minutes'],
        [7 * D, '10 minutes'],
        [8 * D, '1 hour'],
        [42 * D, '1 hour'],
        [183 * D, '1 hour'],
        [184 * D, '3 hours'],
        [366 * D, '3 hours'],
    ])('range %d ms -> %s', (range, expected) => {
        expect(bucketInterval(range)).toBe(expected);
    });
});

describe('historyQuery (MUSHY-182)', () => {
    const { historyQuery } = require('../src/history_buckets');
    const start = Date.parse('2026-10-01T00:00:00Z');

    test('7 days or less reads raw telemetry', () => {
        const q = historyQuery('fc.humidity', start, start + 7 * D);
        expect(q.text).toMatch(/FROM telemetry\b/);
        expect(q.text).not.toMatch(/telemetry_hourly/);
        expect(q.values).toEqual(['10 minutes', 'fc.humidity', new Date(start), new Date(start + 7 * D)]);
    });

    test('over 7 days reads the hourly aggregate, weighted by count', () => {
        const q = historyQuery('fc.humidity', start, start + 42 * D);
        expect(q.text).toMatch(/FROM telemetry_hourly\b/);
        expect(q.text).toMatch(/SUM\(sum\)\s*\/\s*SUM\(n\)/);
        expect(q.values).toEqual(['1 hour', 'fc.humidity', new Date(start), new Date(start + 42 * D)]);
    });

    test('over 6 months uses 3 h steps from the aggregate', () => {
        const q = historyQuery('fc.co2', start - 200 * D, start);
        expect(q.text).toMatch(/FROM telemetry_hourly\b/);
        expect(q.values[0]).toBe('3 hours');
    });
});

describe('telemetry_hourly DDL (MUSHY-182)', () => {
    const { HOURLY_DDL } = require('../src/history_buckets');
    test('boot never backfills: the view is created WITH NO DATA', () => {
        expect(HOURLY_DDL[0]).toMatch(/WITH NO DATA\s*$/);
        expect(HOURLY_DDL[0]).toMatch(/IF NOT EXISTS/);
    });
    test('reads stay correct before materialization (real-time aggregation on)', () => {
        expect(HOURLY_DDL[0]).toMatch(/materialized_only = false/);
    });
    test('policy is idempotent', () => {
        expect(HOURLY_DDL[1]).toMatch(/if_not_exists\s*=>\s*TRUE/);
    });
});
