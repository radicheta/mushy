// Phase 22 D-02: unit tests for validateFrameParams.
// Written RED-first — module does not exist yet at commit time.
const { validateFrameParams } = require('../src/frame_validate');

const AT = '2026-04-19T12:00:00.000Z';
const AT_MS = Date.parse(AT);

describe('validateFrameParams', () => {
    test('happy path: at + camera_id=fc1 returns ok with parsed Date + raw=false', () => {
        const r = validateFrameParams({ at: AT, camera_id: 'fc1' }, 'fc1');
        expect(r.ok).toBe(true);
        expect(r.parsed.at).toBeInstanceOf(Date);
        expect(r.parsed.at.getTime()).toBe(AT_MS);
        expect(r.parsed.cameraId).toBe('fc1');
        expect(r.parsed.raw).toBe(false);
    });

    test('missing at -> 400 with "at query param required"', () => {
        const r = validateFrameParams({}, 'fc1');
        expect(r.ok).toBe(false);
        expect(r.status).toBe(400);
        expect(r.error).toMatch(/at query param required/);
    });

    test('non-ISO at -> 400 with "must be a valid ISO-8601 timestamp"', () => {
        const r = validateFrameParams({ at: 'not-a-date', camera_id: 'fc1' }, 'fc1');
        expect(r.ok).toBe(false);
        expect(r.status).toBe(400);
        expect(r.error).toMatch(/must be a valid ISO-8601 timestamp/);
    });

    test('wrong camera_id -> 400 with "Invalid camera_id"', () => {
        const r = validateFrameParams({ at: AT, camera_id: 'evil' }, 'fc1');
        expect(r.ok).toBe(false);
        expect(r.status).toBe(400);
        expect(r.error).toMatch(/Invalid camera_id/);
    });

    test('missing camera_id defaults to allowedCameraId', () => {
        const r = validateFrameParams({ at: AT }, 'fc1');
        expect(r.ok).toBe(true);
        expect(r.parsed.cameraId).toBe('fc1');
    });

    test("raw='true' -> parsed.raw === true", () => {
        const r = validateFrameParams({ at: AT, raw: 'true' }, 'fc1');
        expect(r.ok).toBe(true);
        expect(r.parsed.raw).toBe(true);
    });

    test("raw='false' -> parsed.raw === false", () => {
        const r = validateFrameParams({ at: AT, raw: 'false' }, 'fc1');
        expect(r.ok).toBe(true);
        expect(r.parsed.raw).toBe(false);
    });

    test("missing raw -> parsed.raw === false", () => {
        const r = validateFrameParams({ at: AT }, 'fc1');
        expect(r.ok).toBe(true);
        expect(r.parsed.raw).toBe(false);
    });

    test("raw='1' and raw='yes' are NOT coerced to true (strict string match)", () => {
        const r1 = validateFrameParams({ at: AT, raw: '1' }, 'fc1');
        expect(r1.parsed.raw).toBe(false);
        const r2 = validateFrameParams({ at: AT, raw: 'yes' }, 'fc1');
        expect(r2.parsed.raw).toBe(false);
    });

    test('no file_path passthrough: file_path query is ignored and not present on parsed', () => {
        const r = validateFrameParams({ at: AT, file_path: '/etc/passwd' }, 'fc1');
        expect(r.ok).toBe(true);
        expect(r.parsed).not.toHaveProperty('file_path');
    });
});
