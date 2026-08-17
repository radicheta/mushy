// Phase 28 plan 28-06 — MODE-05 Layer 2 — POST /control/persist.
//
// Layer 2 transport locked: fc_buffer HTTP relay (28-01-SPIKE.md §C, D-B1).
// Bridge POSTs to fc_buffer.py's POST /control/persist; fc_buffer owns the
// atomic write. Allowlist + range bounds enforced on BOTH sides (defense in
// depth — T-28-20).

'use strict';

const yaml = require('js-yaml');
const persist = require('../src/control_persist');

function makeRes() {
    const res = {
        statusCode: 200,
        body: null,
        status(code) { this.statusCode = code; return this; },
        json(payload) { this.body = payload; return this; },
    };
    return res;
}

function makeMockTransport(initial = null) {
    let content = initial;
    const writes = [];
    return {
        writes,
        get content() { return content; },
        async read(_p) { return content; },
        async atomicWrite(p, c) {
            writes.push({ path: p, content: c });
            content = c;
        },
    };
}

describe('mergeOverlay', () => {
    test('empty existing → fresh fc_controller.ros__parameters tree', () => {
        const out = persist.mergeOverlay({}, [{ param: 'pid_kp', value: 0.4 }]);
        expect(out).toEqual({
            fc_controller: { ros__parameters: { pid_kp: 0.4 } },
        });
    });

    test('preserves existing flat dotted keys when adding new ones (D-03)', () => {
        const existing = {
            fc_controller: { ros__parameters: { pid_kp: 0.4 } },
        };
        const out = persist.mergeOverlay(existing, [
            { param: 'modes.fruiting.band_low', value: 0.94 },
        ]);
        expect(out.fc_controller.ros__parameters.pid_kp).toBe(0.4);
        expect(out.fc_controller.ros__parameters['modes.fruiting.band_low']).toBe(0.94);
        // Critically: 'modes' is NOT a nested object — D-03 flat dotted-key contract.
        expect(out.fc_controller.ros__parameters.modes).toBeUndefined();
    });

    test('overwrites existing key when persisting new value', () => {
        const existing = {
            fc_controller: { ros__parameters: { pid_kp: 0.4 } },
        };
        const out = persist.mergeOverlay(existing, [{ param: 'pid_kp', value: 0.35 }]);
        expect(out.fc_controller.ros__parameters.pid_kp).toBe(0.35);
    });

    test('null existing accepted', () => {
        const out = persist.mergeOverlay(null, [{ param: 'pid_kp', value: 0.4 }]);
        expect(out.fc_controller.ros__parameters.pid_kp).toBe(0.4);
    });
});

describe('renderOverlay', () => {
    test('NaN serializes as .nan literal (T-28-24)', () => {
        const obj = {
            fc_controller: {
                ros__parameters: { 'modes.fruiting.t_target': NaN, pid_kp: 0.4 },
            },
        };
        const rendered = persist.renderOverlay(obj, { timestamp: '2026-05-08T00:00:00Z' });
        expect(rendered).toMatch(/^# AUTO-GENERATED/);
        expect(rendered).toMatch(/^# Last write: 2026-05-08T00:00:00Z$/m);
        // .nan literal — ROS2 launch parser requires this exact form.
        expect(rendered).toMatch(/modes\.fruiting\.t_target: \.nan/);
        // Round-trip parses cleanly (yaml.load tolerates `.nan`).
        const reparsed = yaml.load(rendered);
        expect(reparsed.fc_controller.ros__parameters.pid_kp).toBe(0.4);
        expect(Number.isNaN(reparsed.fc_controller.ros__parameters['modes.fruiting.t_target'])).toBe(true);
    });

    test('flat dotted keys are quoted/preserved as-is (no path-segment splitting)', () => {
        const obj = {
            fc_controller: {
                ros__parameters: { 'modes.fruiting.band_low': 0.94 },
            },
        };
        const rendered = persist.renderOverlay(obj, { timestamp: 'X' });
        // The key is emitted literally as a single dotted string — yaml does not
        // split it into a nested map.
        expect(rendered).toMatch(/modes\.fruiting\.band_low: 0\.94/);
        const reparsed = yaml.load(rendered);
        expect(reparsed.fc_controller.ros__parameters['modes.fruiting.band_low']).toBe(0.94);
    });

    // MUSHY-34 — the 2026-06-28 landmine. js-yaml has no int/double distinction,
    // so an integral-valued double round-trips to a bare int and the next
    // fc-core restart dies with InvalidParameterTypeException. Cost the farm a
    // 5h23m open-loop humidifier window.
    test('integral-valued doubles keep a decimal point (MUSHY-34)', () => {
        const obj = {
            fc_controller: {
                ros__parameters: { pid_integrator_decay_tau: 1800.0, pid_kp: 1 },
            },
        };
        const rendered = persist.renderOverlay(obj, { timestamp: 'X' });
        expect(rendered).toMatch(/pid_integrator_decay_tau: 1800\.0$/m);
        expect(rendered).toMatch(/pid_kp: 1\.0$/m);
    });

    test('re-render of a parsed overlay does not demote doubles to ints (MUSHY-34)', () => {
        // The actual 06-28 mechanism: the tau was hand-fixed to 1800.0 in the
        // file, then a LATER persist of an unrelated band change read it back,
        // parsed it to JS number 1800, and re-dumped it as a bare int.
        const onDisk = 'fc_controller:\n  ros__parameters:\n    pid_integrator_decay_tau: 1800.0\n';
        const merged = persist.mergeOverlay(yaml.load(onDisk), [
            { param: 'modes.fruiting.band_low', value: 0.885 },
        ]);
        const rendered = persist.renderOverlay(merged, { timestamp: 'X' });
        expect(rendered).toMatch(/pid_integrator_decay_tau: 1800\.0$/m);
    });

    test('known-integer params stay bare ints (MUSHY-34)', () => {
        // The inverse crash: writing 8.0 for an INTEGER-declared param kills the
        // controller just as dead. These are the Phase 29/30 alerter + scheduler
        // knobs, typed T_INTEGER in the control_param allowlist.
        const obj = {
            fc_controller: {
                ros__parameters: {
                    heartbeat_hour: 7,
                    'modes.fruiting.alerter.oob_window_min': 8,
                    pi_offline_min: 10,
                },
            },
        };
        const rendered = persist.renderOverlay(obj, { timestamp: 'X' });
        expect(rendered).toMatch(/heartbeat_hour: 7$/m);
        expect(rendered).toMatch(/modes\.fruiting\.alerter\.oob_window_min: 8$/m);
        expect(rendered).toMatch(/pi_offline_min: 10$/m);
    });

    test('non-integral doubles, NaN and strings are untouched (MUSHY-34)', () => {
        const obj = {
            fc_controller: {
                ros__parameters: {
                    'modes.fruiting.band_low': 0.885,
                    'modes.fruiting.t_target': NaN,
                    active_mode: 'fruiting',
                },
            },
        };
        const rendered = persist.renderOverlay(obj, { timestamp: 'X' });
        expect(rendered).toMatch(/modes\.fruiting\.band_low: 0\.885$/m);
        expect(rendered).toMatch(/modes\.fruiting\.t_target: \.nan$/m);
        expect(rendered).toMatch(/active_mode: fruiting$/m);
    });

    test('sortKeys produces stable output for idempotency', () => {
        const a = persist.renderOverlay(
            { fc_controller: { ros__parameters: { b: 2, a: 1 } } },
            { timestamp: 'X' },
        );
        const b = persist.renderOverlay(
            { fc_controller: { ros__parameters: { a: 1, b: 2 } } },
            { timestamp: 'X' },
        );
        expect(persist.stripHeader(a)).toBe(persist.stripHeader(b));
    });
});

describe('makeHandler', () => {
    test('happy path: writes overlay yaml with fc_controller.ros__parameters tree', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport, { overlayPath: '/tmp/ov.yaml' });
        const req = { body: { node: 'fc_controller', param: 'pid_kp', value: 0.4 } };
        const res = makeRes();
        await handler(req, res);
        expect(res.statusCode).toBe(200);
        expect(res.body.ok).toBe(true);
        expect(res.body.persisted).toEqual([{ param: 'pid_kp', value: 0.4 }]);
        expect(res.body.path).toBe('/tmp/ov.yaml');
        expect(transport.writes).toHaveLength(1);
        expect(transport.writes[0].path).toBe('/tmp/ov.yaml');
        const written = yaml.load(transport.writes[0].content);
        expect(written.fc_controller.ros__parameters.pid_kp).toBe(0.4);
    });

    test('batched params → single overlay write merges all', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport, { overlayPath: '/tmp/ov.yaml' });
        const req = {
            body: {
                node: 'fc_controller',
                params: [
                    { param: 'modes.fruiting.band_low', value: 0.94 },
                    { param: 'modes.fruiting.band_high', value: 0.98 },
                ],
            },
        };
        const res = makeRes();
        await handler(req, res);
        expect(res.statusCode).toBe(200);
        expect(transport.writes).toHaveLength(1);
        const written = yaml.load(transport.writes[0].content);
        expect(written.fc_controller.ros__parameters['modes.fruiting.band_low']).toBe(0.94);
        expect(written.fc_controller.ros__parameters['modes.fruiting.band_high']).toBe(0.98);
    });

    test('idempotent: posting same payload twice → second yaml byte-equal (sans header)', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport, { overlayPath: '/tmp/ov.yaml' });
        const req = { body: { node: 'fc_controller', param: 'pid_kp', value: 0.4 } };
        await handler(req, makeRes());
        await handler(req, makeRes());
        expect(transport.writes).toHaveLength(2);
        expect(persist.stripHeader(transport.writes[0].content))
            .toBe(persist.stripHeader(transport.writes[1].content));
    });

    test('subsequent persist preserves existing overlay values (round-trip)', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport, { overlayPath: '/tmp/ov.yaml' });
        await handler(
            { body: { node: 'fc_controller', param: 'pid_kp', value: 0.4 } },
            makeRes(),
        );
        await handler(
            { body: { node: 'fc_controller', param: 'modes.fruiting.band_low', value: 0.94 } },
            makeRes(),
        );
        const final = yaml.load(transport.writes[1].content);
        expect(final.fc_controller.ros__parameters.pid_kp).toBe(0.4);
        expect(final.fc_controller.ros__parameters['modes.fruiting.band_low']).toBe(0.94);
    });

    test('rejects non-allowlisted node', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport);
        const req = { body: { node: 'evil_node', param: 'pid_kp', value: 0.4 } };
        const res = makeRes();
        await handler(req, res);
        expect(res.statusCode).toBe(400);
        expect(transport.writes).toHaveLength(0);
    });

    test('rejects non-allowlisted param (path traversal attempt T-28-20)', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport);
        const req = {
            body: { node: 'fc_controller', param: 'modes.../../etc/passwd.target_humidity', value: 0.5 },
        };
        const res = makeRes();
        await handler(req, res);
        expect(res.statusCode).toBe(400);
        expect(res.body.error).toMatch(/not allowlisted/);
        expect(transport.writes).toHaveLength(0);
    });

    test('rejects out-of-range pid_kp (defense in depth)', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport);
        const req = { body: { node: 'fc_controller', param: 'pid_kp', value: 99 } };
        const res = makeRes();
        await handler(req, res);
        expect(res.statusCode).toBe(400);
        expect(res.body.rejected_param).toBe('pid_kp');
        expect(transport.writes).toHaveLength(0);
    });

    test('rejects empty params array', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport);
        const req = { body: { node: 'fc_controller', params: [] } };
        const res = makeRes();
        await handler(req, res);
        expect(res.statusCode).toBe(400);
    });

    test('rejects malformed body (no param + no params)', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport);
        const req = { body: { node: 'fc_controller' } };
        const res = makeRes();
        await handler(req, res);
        expect(res.statusCode).toBe(400);
    });

    test('caps params at MAX_PARAMS', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport);
        const params = Array.from({ length: persist.MAX_PARAMS + 1 }, () => ({
            param: 'pid_kp', value: 0.4,
        }));
        const req = { body: { node: 'fc_controller', params } };
        const res = makeRes();
        await handler(req, res);
        expect(res.statusCode).toBe(400);
        expect(res.body.error).toMatch(/too many/);
    });

    test('transport read failure is tolerated (treats as empty existing)', async () => {
        const transport = {
            read: async () => { throw new Error('ENOENT'); },
            atomicWrite: jest.fn(async () => {}),
        };
        const handler = persist.makeHandler(transport, { overlayPath: '/tmp/ov.yaml' });
        const req = { body: { node: 'fc_controller', param: 'pid_kp', value: 0.4 } };
        const res = makeRes();
        await handler(req, res);
        expect(res.statusCode).toBe(200);
        expect(transport.atomicWrite).toHaveBeenCalledTimes(1);
    });

    test('transport write failure → 500', async () => {
        const transport = {
            read: async () => null,
            atomicWrite: async () => { throw new Error('relay 502'); },
        };
        const handler = persist.makeHandler(transport);
        const req = { body: { node: 'fc_controller', param: 'pid_kp', value: 0.4 } };
        const res = makeRes();
        await handler(req, res);
        expect(res.statusCode).toBe(500);
        expect(res.body.error).toMatch(/relay 502/);
    });
});

describe('makeHttpTransport (Branch B — fc_buffer HTTP relay, D-B1)', () => {
    test('read: GETs /control/overlay with urlencoded path', async () => {
        const calls = [];
        const fakeFetch = async (url, _init) => {
            calls.push(url);
            return { ok: true, status: 200, async text() { return 'pid_kp: 0.4\n'; } };
        };
        const t = persist.makeHttpTransport({ host: '127.0.0.1', port: 9999, fetch: fakeFetch });
        const out = await t.read('/var/lib/fc-core/runtime_overrides.yaml');
        expect(out).toBe('pid_kp: 0.4\n');
        expect(calls[0]).toBe(
            'http://127.0.0.1:9999/control/overlay?path=%2Fvar%2Flib%2Ffc-core%2Fruntime_overrides.yaml',
        );
    });

    test('read: 404 → null (no overlay yet)', async () => {
        const fakeFetch = async () => ({ ok: false, status: 404, async text() { return ''; } });
        const t = persist.makeHttpTransport({ host: 'h', port: 1, fetch: fakeFetch });
        expect(await t.read('/var/lib/fc-core/runtime_overrides.yaml')).toBeNull();
    });

    test('atomicWrite: POSTs to /control/persist with {path, content}', async () => {
        const calls = [];
        const fakeFetch = async (url, init) => {
            calls.push({ url, init });
            return { ok: true, status: 200, async text() { return ''; } };
        };
        const t = persist.makeHttpTransport({ host: 'h', port: 1, fetch: fakeFetch });
        await t.atomicWrite('/var/lib/fc-core/runtime_overrides.yaml', 'pid_kp: 0.4\n');
        expect(calls[0].url).toBe('http://h:1/control/persist');
        expect(calls[0].init.method).toBe('POST');
        const body = JSON.parse(calls[0].init.body);
        expect(body.path).toBe('/var/lib/fc-core/runtime_overrides.yaml');
        expect(body.content).toBe('pid_kp: 0.4\n');
    });

    test('atomicWrite: non-2xx → throws with relay status', async () => {
        const fakeFetch = async () => ({ ok: false, status: 502, async text() { return 'bad gw'; } });
        const t = persist.makeHttpTransport({ host: 'h', port: 1, fetch: fakeFetch });
        await expect(t.atomicWrite('/var/lib/fc-core/runtime_overrides.yaml', 'x'))
            .rejects.toThrow(/persist write 502/);
    });
});

// ---------------------------------------------------------------- Phase 30 SCHED
// Plan 30-02 Task 2 — schedule_windows persists as a flat JSON STRING under
// fc_controller.ros__parameters (NOT pre-parsed into a YAML list).

describe('schedule_windows persistence', () => {
    test('writes flat key with JSON STRING preserved verbatim', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport, { overlayPath: '/tmp/ov.yaml' });
        const scheduleJson = '[{"start":"06:00","end":"22:00","mode":"fruiting"}]';
        const res = makeRes();
        await handler(
            { body: { node: 'fc_controller', param: 'schedule_windows', value: scheduleJson } },
            res,
        );
        expect(res.statusCode).toBe(200);
        expect(transport.writes).toHaveLength(1);
        const written = yaml.load(transport.writes[0].content);
        // The JSON STRING must survive round-trip verbatim — yaml must NOT
        // pre-parse it into a list (D-01: rclpy reads it as STRING param).
        expect(written.fc_controller.ros__parameters.schedule_windows)
            .toBe(scheduleJson);
        expect(typeof written.fc_controller.ros__parameters.schedule_windows)
            .toBe('string');
    });

    test('malformed JSON → 400 (no overlay write)', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport, { overlayPath: '/tmp/ov.yaml' });
        const res = makeRes();
        await handler(
            { body: { node: 'fc_controller', param: 'schedule_windows', value: '{not json' } },
            res,
        );
        expect(res.statusCode).toBe(400);
        expect(res.body.rejected_param).toBe('schedule_windows');
        expect(transport.writes).toHaveLength(0);
    });

    test('merges with existing overlay (preserves prior keys)', async () => {
        const transport = makeMockTransport(null);
        const handler = persist.makeHandler(transport, { overlayPath: '/tmp/ov.yaml' });
        // Seed: write a target_humidity entry first.
        await handler(
            { body: { node: 'fc_controller', param: 'modes.fruiting.target_humidity', value: 0.96 } },
            makeRes(),
        );
        // Now persist schedule_windows.
        const scheduleJson = '[{"start":"06:00","end":"22:00","mode":"fruiting"}]';
        await handler(
            { body: { node: 'fc_controller', param: 'schedule_windows', value: scheduleJson } },
            makeRes(),
        );
        const final = yaml.load(transport.writes[1].content);
        expect(final.fc_controller.ros__parameters['modes.fruiting.target_humidity']).toBe(0.96);
        expect(final.fc_controller.ros__parameters.schedule_windows).toBe(scheduleJson);
    });
});
