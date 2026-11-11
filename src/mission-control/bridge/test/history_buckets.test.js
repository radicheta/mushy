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
