const { validateHistoryParams } = require('../src/history_validate');
const MAX = 30 * 24 * 3600000;
const T0 = '2026-04-01T00:00:00.000Z';
const T0_MS = Date.parse(T0);
const T1 = '2026-04-02T00:00:00.000Z';
const T1_MS = Date.parse(T1);
const T30 = '2026-05-01T00:00:00.000Z';
const T31 = '2026-05-02T00:00:00.000Z';

describe('validateHistoryParams', () => {
    test('rejects missing from', () => {
        const r = validateHistoryParams({ to: T1 }, 'fc1', MAX);
        expect(r.ok).toBe(false);
        expect(r.status).toBe(400);
        expect(r.error).toMatch(/from and to/);
    });
    test('rejects missing to', () => {
        const r = validateHistoryParams({ from: T0 }, 'fc1', MAX);
        expect(r.ok).toBe(false);
        expect(r.status).toBe(400);
    });
    test('rejects non-ISO from', () => {
        const r = validateHistoryParams({ from: 'not-a-date', to: T1 }, 'fc1', MAX);
        expect(r.ok).toBe(false);
        expect(r.error).toMatch(/ISO-8601/);
    });
    test('rejects non-ISO to', () => {
        const r = validateHistoryParams({ from: T0, to: 'xyz' }, 'fc1', MAX);
        expect(r.ok).toBe(false);
    });
    test('rejects to < from', () => {
        const r = validateHistoryParams({ from: T1, to: T0 }, 'fc1', MAX);
        expect(r.ok).toBe(false);
        expect(r.error).toBe('to must be >= from');
    });
    test('rejects range > 30 days', () => {
        const r = validateHistoryParams({ from: T0, to: T31 }, 'fc1', MAX);
        expect(r.ok).toBe(false);
        expect(r.error).toBe('Max range is 30 days');
    });
    test('rejects unknown camera_id', () => {
        const r = validateHistoryParams({ from: T0, to: T1, camera_id: 'evil' }, 'fc1', MAX);
        expect(r.ok).toBe(false);
        expect(r.error).toBe('Invalid camera_id');
    });
    test('accepts default camera_id (omitted)', () => {
        const r = validateHistoryParams({ from: T0, to: T1 }, 'fc1', MAX);
        expect(r.ok).toBe(true);
        expect(r.parsed.from).toBe(T0_MS);
        expect(r.parsed.to).toBe(T1_MS);
        expect(r.parsed.cameraId).toBe('fc1');
        expect(r.parsed.fromIso).toBe(T0);
        expect(r.parsed.toIso).toBe(T1);
    });
    test('accepts explicit matching camera_id', () => {
        const r = validateHistoryParams({ from: T0, to: T1, camera_id: 'fc1' }, 'fc1', MAX);
        expect(r.ok).toBe(true);
    });
    test('boundary: exactly 30d range accepted', () => {
        const r = validateHistoryParams({ from: T0, to: T30 }, 'fc1', MAX);
        expect(r.ok).toBe(true);
    });
    test('boundary: from === to accepted', () => {
        const r = validateHistoryParams({ from: T0, to: T0 }, 'fc1', MAX);
        expect(r.ok).toBe(true);
    });
});
