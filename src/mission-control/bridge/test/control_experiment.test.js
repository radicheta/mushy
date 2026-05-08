// Phase 31 plan 31-03 — Jest tests for control_experiment.js (HTTP layer).
//
// Mirrors the control_param.test.js pattern: mkRes, mkRosNode helpers; mocked
// rclnodejs Node injected; no rclnodejs import at the top level.

const {
    VALID_NAMES,
    HARD_CAP_MIN,
    DEFAULT_DURATION_MIN,
    validate,
    makeStartHandler,
    makeCancelHandler,
    makeStateHandler,
} = require('../src/control_experiment');

function mkRes() {
    return {
        _status: 200,
        _body: null,
        status(c) { this._status = c; return this; },
        json(b) { this._body = b; return this; },
    };
}

function mkRosNode(sendRequestImpl, opts = {}) {
    const calls = [];
    const node = {
        _calls: calls,
        createClient: jest.fn((srvType, srvName) => {
            calls.push({ srvType, srvName });
            return {
                sendRequest: (req, cb) => sendRequestImpl(req, cb),
            };
        }),
    };
    if (opts.createClientThrows) {
        node.createClient = jest.fn(() => { throw new Error(opts.createClientThrows); });
    }
    return node;
}

// =====================================================================
// validate()
// =====================================================================

describe('validate()', () => {
    test('name=force-condensation accepted', () => {
        const v = validate('force-condensation', 15);
        expect(v.ok).toBe(true);
        expect(v.duration_minutes).toBe(15);
    });
    test('name=force-evaporation accepted', () => {
        const v = validate('force-evaporation', 30);
        expect(v.ok).toBe(true);
        expect(v.duration_minutes).toBe(30);
    });
    test('unknown name rejected', () => {
        const v = validate('turbo-mode', 15);
        expect(v.ok).toBe(false);
        expect(v.reason).toMatch(/name/);
    });
    test('missing name rejected', () => {
        const v = validate(undefined, 15);
        expect(v.ok).toBe(false);
        expect(v.reason).toMatch(/name/);
    });
    test.each([1, 15, 60, 120])('duration %i within range accepted', (d) => {
        expect(validate('force-condensation', d).ok).toBe(true);
    });
    test('duration zero rejected', () => {
        const v = validate('force-condensation', 0);
        expect(v.ok).toBe(false);
        expect(v.reason).toMatch(/duration/);
    });
    test('duration negative rejected', () => {
        expect(validate('force-condensation', -5).ok).toBe(false);
    });
    test('duration over cap rejected with /120/ message', () => {
        const v = validate('force-condensation', 121);
        expect(v.ok).toBe(false);
        expect(v.reason).toMatch(/120/);
    });
    test('duration non-integer rejected', () => {
        const v = validate('force-condensation', 15.5);
        expect(v.ok).toBe(false);
        expect(v.reason).toMatch(/integer/);
    });
    test('duration missing uses default 15', () => {
        const v = validate('force-condensation', undefined);
        expect(v.ok).toBe(true);
        expect(v.duration_minutes).toBe(DEFAULT_DURATION_MIN);
    });
    test('exports HARD_CAP_MIN=120', () => {
        expect(HARD_CAP_MIN).toBe(120);
    });
    test('exports VALID_NAMES set', () => {
        expect(VALID_NAMES.has('force-condensation')).toBe(true);
        expect(VALID_NAMES.has('force-evaporation')).toBe(true);
        expect(VALID_NAMES.size).toBe(2);
    });
});

// =====================================================================
// makeStartHandler()
// =====================================================================

describe('makeStartHandler', () => {
    test('happy path returns 200 with controller fields', async () => {
        const node = mkRosNode((req, cb) => cb({
            ok: true,
            message: '',
            started_at_iso: '2026-05-08T18:00:00Z',
            reverts_at_iso: '2026-05-08T18:15:00Z',
            prior_mode: 'fruiting',
        }));
        const res = mkRes();
        const handler = makeStartHandler(node);
        await handler({ body: { name: 'force-condensation', duration_minutes: 15 } }, res);
        expect(res._status).toBe(200);
        expect(res._body.ok).toBe(true);
        expect(res._body.started_at_iso).toBe('2026-05-08T18:00:00Z');
        expect(res._body.reverts_at_iso).toBe('2026-05-08T18:15:00Z');
        expect(res._body.prior_mode).toBe('fruiting');
        expect(node._calls[0].srvName).toBe('/fc_controller/start_experiment');
    });

    test('default duration_minutes=15 when omitted', async () => {
        let captured;
        const node = mkRosNode((req, cb) => {
            captured = req;
            cb({ ok: true, message: '', started_at_iso: 'x', reverts_at_iso: 'y', prior_mode: 'fruiting' });
        });
        const res = mkRes();
        const handler = makeStartHandler(node);
        await handler({ body: { name: 'force-condensation' } }, res);
        expect(captured.duration_minutes).toBe(15);
    });

    test('invalid name → 400, rclnodejs not called', async () => {
        const node = mkRosNode(() => { throw new Error('should not be called'); });
        const res = mkRes();
        const handler = makeStartHandler(node);
        await handler({ body: { name: 'turbo' } }, res);
        expect(res._status).toBe(400);
        expect(res._body.error).toMatch(/name/);
        expect(node.createClient).not.toHaveBeenCalled();
    });

    test('invalid duration → 400 with /120/ message', async () => {
        const node = mkRosNode(() => { throw new Error('should not be called'); });
        const res = mkRes();
        const handler = makeStartHandler(node);
        await handler({ body: { name: 'force-condensation', duration_minutes: 200 } }, res);
        expect(res._status).toBe(400);
        expect(res._body.error).toMatch(/120/);
        expect(node.createClient).not.toHaveBeenCalled();
    });

    test('controller rejects with ok:false → 400 with error', async () => {
        const node = mkRosNode((req, cb) => cb({ ok: false, message: 'experiment_in_progress', started_at_iso: '', reverts_at_iso: '', prior_mode: '' }));
        const res = mkRes();
        const handler = makeStartHandler(node);
        await handler({ body: { name: 'force-condensation', duration_minutes: 15 } }, res);
        expect(res._status).toBe(400);
        expect(res._body.ok).toBe(false);
        expect(res._body.error).toBe('experiment_in_progress');
    });

    test('rclnodejs timeout → 504', async () => {
        // Never call the callback; rely on real setTimeout with a short timeout.
        const node = mkRosNode((req, cb) => { /* never call */ });
        const res = mkRes();
        const handler = makeStartHandler(node, { timeoutMs: 5 });
        await handler({ body: { name: 'force-condensation', duration_minutes: 15 } }, res);
        expect(res._status).toBe(504);
        expect(res._body.error).toMatch(/timeout/i);
    });

    test('createClient throws → 500', async () => {
        const node = mkRosNode(() => {}, { createClientThrows: 'rcl boom' });
        const res = mkRes();
        const handler = makeStartHandler(node);
        await handler({ body: { name: 'force-condensation', duration_minutes: 15 } }, res);
        expect(res._status).toBe(500);
        expect(res._body.error).toMatch(/rcl boom/);
    });

    test('null rosNode → 503', async () => {
        const res = mkRes();
        const handler = makeStartHandler(null);
        await handler({ body: { name: 'force-condensation', duration_minutes: 15 } }, res);
        expect(res._status).toBe(503);
        expect(res._body.error).toMatch(/not ready/);
    });
});

// =====================================================================
// makeCancelHandler()
// =====================================================================

describe('makeCancelHandler', () => {
    test('happy path returns 200 ok:true', async () => {
        const node = mkRosNode((req, cb) => cb({
            ok: true,
            message: '',
            ended_at_iso: '2026-05-08T18:05:00Z',
        }));
        const res = mkRes();
        const handler = makeCancelHandler(node);
        await handler({ body: {} }, res);
        expect(res._status).toBe(200);
        expect(res._body.ok).toBe(true);
        expect(res._body.ended_at_iso).toBe('2026-05-08T18:05:00Z');
        expect(node._calls[0].srvName).toBe('/fc_controller/cancel_experiment');
    });

    test('no_experiment_active → 400', async () => {
        const node = mkRosNode((req, cb) => cb({ ok: false, message: 'no_experiment_active', ended_at_iso: '' }));
        const res = mkRes();
        const handler = makeCancelHandler(node);
        await handler({ body: {} }, res);
        expect(res._status).toBe(400);
        expect(res._body.error).toBe('no_experiment_active');
    });

    test('rclnodejs timeout → 504', async () => {
        const node = mkRosNode(() => {});
        const res = mkRes();
        const handler = makeCancelHandler(node, { timeoutMs: 5 });
        await handler({ body: {} }, res);
        expect(res._status).toBe(504);
    });
});

// =====================================================================
// makeStateHandler()
// =====================================================================

describe('makeStateHandler', () => {
    test('idle when no cached event → {active:false}', () => {
        const handler = makeStateHandler({ getLastEvent: () => null });
        const res = mkRes();
        handler({}, res);
        expect(res._status).toBe(200);
        expect(res._body).toEqual({ active: false });
    });

    test('active started → seconds_remaining math', () => {
        const ev = {
            event: 'started',
            experiment: 'force-condensation',
            prior_mode: 'fruiting',
            requested_minutes: 15,
            started_at_iso: '2026-05-08T18:00:00Z',
            reverts_at_iso: '2026-05-08T18:15:00Z',
            wall_clock_iso: '2026-05-08T18:00:00Z',
        };
        // "now" = 5 minutes in → 600 seconds remaining.
        const now = () => Date.parse('2026-05-08T18:05:00Z');
        const handler = makeStateHandler({ getLastEvent: () => ev, now });
        const res = mkRes();
        handler({}, res);
        expect(res._body).toMatchObject({
            active: true,
            experiment: 'force-condensation',
            prior_mode: 'fruiting',
            requested_minutes: 15,
            seconds_remaining: 600,
        });
    });

    test('after ended event → {active:false}', () => {
        const ev = { event: 'ended', experiment: 'force-condensation' };
        const handler = makeStateHandler({ getLastEvent: () => ev });
        const res = mkRes();
        handler({}, res);
        expect(res._body).toEqual({ active: false });
    });

    test('after cancelled → {active:false}', () => {
        const handler = makeStateHandler({ getLastEvent: () => ({ event: 'cancelled' }) });
        const res = mkRes();
        handler({}, res);
        expect(res._body).toEqual({ active: false });
    });

    test('seconds_remaining floors at zero past reverts_at', () => {
        const ev = {
            event: 'started',
            experiment: 'force-condensation',
            prior_mode: 'fruiting',
            requested_minutes: 1,
            started_at_iso: '2026-05-08T18:00:00Z',
            reverts_at_iso: '2026-05-08T18:01:00Z',
            wall_clock_iso: '2026-05-08T18:00:00Z',
        };
        // "now" = well past reverts_at.
        const now = () => Date.parse('2026-05-08T19:00:00Z');
        const handler = makeStateHandler({ getLastEvent: () => ev, now });
        const res = mkRes();
        handler({}, res);
        expect(res._body.seconds_remaining).toBe(0);
    });
});
