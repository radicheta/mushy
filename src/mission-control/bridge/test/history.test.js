const { validateHistoryParams } = require('../src/history_validate');
const MAX = 30 * 24 * 3600000;

describe('validateHistoryParams', () => {
    test('rejects non-numeric from', () => {
        const r = validateHistoryParams({ from: 'abc', to: '1000' }, 'fc1', MAX);
        expect(r.ok).toBe(false);
        expect(r.status).toBe(400);
        expect(r.error).toMatch(/from and to/);
    });
    test('rejects non-numeric to', () => {
        const r = validateHistoryParams({ from: '0', to: 'xyz' }, 'fc1', MAX);
        expect(r.ok).toBe(false);
        expect(r.status).toBe(400);
    });
    test('rejects to < from', () => {
        const r = validateHistoryParams({ from: '100', to: '50' }, 'fc1', MAX);
        expect(r.ok).toBe(false);
        expect(r.error).toBe('to must be >= from');
    });
    test('rejects range > 30 days', () => {
        const r = validateHistoryParams({ from: '0', to: String(31 * 86400000) }, 'fc1', MAX);
        expect(r.ok).toBe(false);
        expect(r.error).toBe('Max range is 30 days');
    });
    test('rejects unknown camera_id', () => {
        const r = validateHistoryParams({ from: '0', to: '1000', camera_id: 'evil' }, 'fc1', MAX);
        expect(r.ok).toBe(false);
        expect(r.error).toBe('Invalid camera_id');
    });
    test('accepts default camera_id (omitted)', () => {
        const r = validateHistoryParams({ from: '0', to: '1000' }, 'fc1', MAX);
        expect(r.ok).toBe(true);
        expect(r.parsed).toEqual({ from: 0, to: 1000, cameraId: 'fc1' });
    });
    test('accepts explicit matching camera_id', () => {
        const r = validateHistoryParams({ from: '0', to: '1000', camera_id: 'fc1' }, 'fc1', MAX);
        expect(r.ok).toBe(true);
    });
    test('boundary: exactly 30d range accepted', () => {
        const r = validateHistoryParams({ from: '0', to: String(30 * 86400000) }, 'fc1', MAX);
        expect(r.ok).toBe(true);
    });
    test('boundary: from === to accepted', () => {
        const r = validateHistoryParams({ from: '5000', to: '5000' }, 'fc1', MAX);
        expect(r.ok).toBe(true);
    });
});
