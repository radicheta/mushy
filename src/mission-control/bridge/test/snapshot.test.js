const { decideSource, shouldSkipSnapshot } = require('../src/snapshot_helpers');

describe('decideSource (D-02 idle / D-05 viewer tag)', () => {
    test('zero viewers → idle', () => {
        expect(decideSource(0)).toBe('idle');
    });
    test('one viewer → viewer', () => {
        expect(decideSource(1)).toBe('viewer');
    });
    test('many viewers → viewer', () => {
        expect(decideSource(17)).toBe('viewer');
    });
});

describe('shouldSkipSnapshot (Pitfall 1 stall-safety gate)', () => {
    const MAX = 2 * 60 * 60 * 1000; // 2h — matches FRAME_MAX_AGE_MS

    test('null latestFrame → skip', () => {
        expect(shouldSkipSnapshot({ latestFrame: null, lastFrameTime: Date.now(), now: Date.now(), maxAgeMs: MAX })).toBe(true);
    });
    test('null lastFrameTime → skip', () => {
        expect(shouldSkipSnapshot({ latestFrame: Buffer.from([1]), lastFrameTime: null, now: Date.now(), maxAgeMs: MAX })).toBe(true);
    });
    test('fresh frame (1s old) → do not skip', () => {
        const now = Date.now();
        expect(shouldSkipSnapshot({ latestFrame: Buffer.from([1]), lastFrameTime: now - 1000, now, maxAgeMs: MAX })).toBe(false);
    });
    test('frame older than maxAgeMs → skip', () => {
        const now = Date.now();
        expect(shouldSkipSnapshot({ latestFrame: Buffer.from([1]), lastFrameTime: now - MAX - 1, now, maxAgeMs: MAX })).toBe(true);
    });
    test('exactly maxAgeMs old → do not skip (boundary)', () => {
        const now = Date.now();
        expect(shouldSkipSnapshot({ latestFrame: Buffer.from([1]), lastFrameTime: now - MAX, now, maxAgeMs: MAX })).toBe(false);
    });
});
