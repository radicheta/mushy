const express = require('express');
const { registerRoutes, validateQuery, singleDayUtc } = require('../src/routes');

function makeApp({ pool, jobs, runComposition, db, healthState }) {
    const app = express();
    registerRoutes(app, { pool, jobs, runComposition, db, healthState, log: { info: () => {}, warn: () => {}, error: () => {} } });
    return app;
}

function reqMock(query, params = {}) {
    return { query, params };
}
function resMock() {
    const r = { _status: 200, _body: undefined };
    r.status = (code) => { r._status = code; return r; };
    r.json = (b) => { r._body = b; return r; };
    return r;
}

// Helper: find route handler from Express 5 app.router.stack
function findRoute(app, path) {
    const layer = app.router.stack.find((l) => l.route && l.route.path === path);
    return layer.route.stack[0].handle;
}

describe('validateQuery', () => {
    test('rejects bad camera_id', () => {
        const v = validateQuery({ from: '2026-04-25T00:00:00Z', to: '2026-04-25T23:59:59.999Z', camera_id: '../etc' });
        expect(v.ok).toBe(false); expect(v.status).toBe(400);
    });
    test('rejects bad date', () => {
        const v = validateQuery({ from: 'nope', to: 'nope', camera_id: 'fc1' });
        expect(v.ok).toBe(false);
    });
    test('rejects to <= from', () => {
        const v = validateQuery({ from: '2026-04-25T00:00:00Z', to: '2026-04-25T00:00:00Z', camera_id: 'fc1' });
        expect(v.ok).toBe(false);
    });
    test('rejects range > 7 days', () => {
        const v = validateQuery({ from: '2026-04-01T00:00:00Z', to: '2026-04-15T00:00:00Z', camera_id: 'fc1' });
        expect(v.ok).toBe(false);
    });
    test('accepts a one-day range', () => {
        const v = validateQuery({ from: '2026-04-25T00:00:00Z', to: '2026-04-25T23:59:59.999Z', camera_id: 'fc1' });
        expect(v.ok).toBe(true);
    });
});

describe('singleDayUtc', () => {
    test('detects a calendar-day range', () => {
        expect(singleDayUtc(new Date('2026-04-25T00:00:00Z'), new Date('2026-04-25T23:59:59.999Z')))
            .toBe('2026-04-25');
    });
    test('returns null for non-day range', () => {
        expect(singleDayUtc(new Date('2026-04-25T01:00:00Z'), new Date('2026-04-25T23:59:59.999Z')))
            .toBeNull();
    });
});

describe('GET /timelapse', () => {
    test('returns existing mp4 (200) when found in DB', async () => {
        const pool = {};
        const jobs = new Map();
        const db = { lookupTimelapse: jest.fn(async () => ({ file_path: '/data/timelapse/fc1/2026-04-25.mp4', duration_sec: 8.3 })) };
        const runComposition = jest.fn();
        const healthState = {};

        const app = makeApp({ pool, jobs, runComposition, db, healthState });
        const handler = findRoute(app, '/timelapse');

        const req = reqMock({ from: '2026-04-25T00:00:00Z', to: '2026-04-25T23:59:59.999Z', camera_id: 'fc1' });
        const res = resMock();
        await handler(req, res);

        expect(res._status).toBe(200);
        expect(res._body).toEqual({ file_path: '/data/timelapse/fc1/2026-04-25.mp4', duration_sec: 8.3 });
        expect(runComposition).not.toHaveBeenCalled();
    });

    test('enqueues job (202) when not in DB', async () => {
        const pool = {};
        const jobs = new Map();
        const db = { lookupTimelapse: jest.fn(async () => null) };
        const runComposition = jest.fn();
        const healthState = {};

        const app = makeApp({ pool, jobs, runComposition, db, healthState });
        const handler = findRoute(app, '/timelapse');

        const req = reqMock({ from: '2026-04-25T00:00:00Z', to: '2026-04-25T23:59:59.999Z', camera_id: 'fc1' });
        const res = resMock();
        await handler(req, res);

        expect(res._status).toBe(202);
        expect(res._body.job_id).toMatch(/^[0-9a-f-]{36}$/);
        expect(jobs.size).toBe(1);
    });

    test('rejects bad camera_id with 400', async () => {
        const pool = {};
        const jobs = new Map();
        const db = { lookupTimelapse: jest.fn() };
        const runComposition = jest.fn();
        const healthState = {};

        const app = makeApp({ pool, jobs, runComposition, db, healthState });
        const handler = findRoute(app, '/timelapse');

        const req = reqMock({ from: '2026-04-25T00:00:00Z', to: '2026-04-25T23:59:59.999Z', camera_id: '../etc' });
        const res = resMock();
        await handler(req, res);

        expect(res._status).toBe(400);
    });
});

describe('GET /timelapse/status/:id', () => {
    test('404 for unknown id', () => {
        const jobs = new Map();
        const app = makeApp({ pool: {}, jobs, runComposition: () => {}, db: {}, healthState: {} });
        const handler = findRoute(app, '/timelapse/status/:id');
        const req = reqMock({}, { id: 'unknown' });
        const res = resMock();
        handler(req, res);
        expect(res._status).toBe(404);
    });

    test('200 + state for known id', () => {
        const jobs = new Map();
        jobs.set('abc', { status: 'done', file_path: '/x.mp4' });
        const app = makeApp({ pool: {}, jobs, runComposition: () => {}, db: {}, healthState: {} });
        const handler = findRoute(app, '/timelapse/status/:id');
        const req = reqMock({}, { id: 'abc' });
        const res = resMock();
        handler(req, res);
        expect(res._status).toBe(200);
        expect(res._body).toEqual({ status: 'done', file_path: '/x.mp4' });
    });
});

describe('GET /health', () => {
    test('returns last_nightly state', () => {
        const healthState = { last_nightly_at: '2026-04-26T04:30:00Z', last_nightly_status: 'ok' };
        const app = makeApp({ pool: {}, jobs: new Map(), runComposition: () => {}, db: {}, healthState });
        const handler = findRoute(app, '/health');
        const res = resMock();
        handler({}, res);
        expect(res._body).toMatchObject({ status: 'ok', last_nightly_at: '2026-04-26T04:30:00Z', last_nightly_status: 'ok' });
    });
});
