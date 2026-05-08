// Phase 28 plan 28-05 — MODE-05 Layer 1 GREEN tests
// (POST /control/param → rclnodejs SetParameters via /fc_controller/set_parameters).
//
// Wire shape locked in 28-01-SPIKE.md §A:
//   { parameters: [{ name, value: { type: int, <X>_value } }] }
//   response: { results: [{ successful: bool, reason: string }, ...] }
//
// Defense-in-depth: range bounds here mirror the rclpy on_set_parameters_callback
// validator landed in plan 28-04 (pid_kp ∈ [0,5], pid_ki ∈ [0,1], pid_kd ∈ [0,20]).

const {
    ALLOWLIST,
    DECLARED_MODES,
    validate,
    toParamValue,
    makeHandler,
} = require('../src/control_param');

function mkRes() {
    return {
        _status: 200,
        _body: null,
        status(c) { this._status = c; return this; },
        json(b) { this._body = b; return this; },
    };
}

// Mock rclnodejs Node: createClient -> { sendRequest(req, cb) }.
// `sendRequestImpl(req, cb)` is the test-controlled per-test stub.
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

// ---------------------------------------------------------------- ALLOWLIST shape

describe('ALLOWLIST + DECLARED_MODES', () => {
    test('declared modes hardcoded to {fruiting, pinning}', () => {
        expect(new Set(DECLARED_MODES)).toEqual(new Set(['fruiting', 'pinning']));
    });

    test.each([
        'humidifier_pin',
        'light_pin',
        'dht_pin',
        'fan_pwm_channel',
        'fan_pwm_freq',
        'actuator_simulation_mode',
        'sensor_simulation_mode',
        'sht30_i2c_address',
        'sht30_temperature_offset_c',
    ])('hardware/sim/offset param %s is NOT allowlisted', (name) => {
        expect(ALLOWLIST[name]).toBeUndefined();
    });

    test.each([
        'active_mode',
        'modes.fruiting.target_humidity',
        'modes.fruiting.band_low',
        'modes.fruiting.band_high',
        'modes.fruiting.defend_side',
        'modes.fruiting.t_target',
        'modes.pinning.target_humidity',
        'modes.pinning.band_low',
        'modes.pinning.band_high',
        'modes.pinning.defend_side',
        'modes.pinning.t_target',
        'pid_kp', 'pid_ki', 'pid_kd',
    ])('expected allowlist entry: %s', (name) => {
        expect(ALLOWLIST[name]).toBeDefined();
        expect(typeof ALLOWLIST[name].type).toBe('number');
    });
});

// ---------------------------------------------------------------- validate()

describe('validate', () => {
    test('active_mode=pinning → ok', () => {
        expect(validate('active_mode', 'pinning')).toEqual({ ok: true });
    });
    test('active_mode=fruiting → ok', () => {
        expect(validate('active_mode', 'fruiting')).toEqual({ ok: true });
    });
    test('active_mode=incubation → reject (best-effort; controller is final)', () => {
        const r = validate('active_mode', 'incubation');
        expect(r.ok).toBe(false);
        expect(r.reason).toMatch(/active_mode/);
    });

    test('humidifier_pin not in allowlist → reject', () => {
        const r = validate('humidifier_pin', 17);
        expect(r.ok).toBe(false);
        expect(r.reason).toMatch(/not allowlisted/);
    });

    test('pid_kp=99 → out of [0,5]', () => {
        const r = validate('pid_kp', 99);
        expect(r.ok).toBe(false);
        expect(r.reason).toMatch(/pid_kp/);
    });
    test('pid_kp=0.35 → ok', () => { expect(validate('pid_kp', 0.35)).toEqual({ ok: true }); });
    test('pid_ki=2 → out of [0,1]', () => { expect(validate('pid_ki', 2).ok).toBe(false); });
    test('pid_kd=21 → out of [0,20]', () => { expect(validate('pid_kd', 21).ok).toBe(false); });
    test('pid_kd=20 → ok (inclusive)', () => { expect(validate('pid_kd', 20)).toEqual({ ok: true }); });

    test('modes.fruiting.t_target=NaN → ok (D-02 sentinel)', () => {
        expect(validate('modes.fruiting.t_target', NaN)).toEqual({ ok: true });
    });
    test('modes.fruiting.t_target=50 → reject (out of [0,40])', () => {
        expect(validate('modes.fruiting.t_target', 50.0).ok).toBe(false);
    });
    test('modes.fruiting.t_target=18 → ok', () => {
        expect(validate('modes.fruiting.t_target', 18.0)).toEqual({ ok: true });
    });

    test('defend_side=upward → reject', () => {
        expect(validate('modes.fruiting.defend_side', 'upward').ok).toBe(false);
    });
    test.each(['low', 'high', 'both'])('defend_side=%s → ok', (s) => {
        expect(validate('modes.pinning.defend_side', s)).toEqual({ ok: true });
    });

    test('band_low=0.85 → ok; band_low=1.5 → reject', () => {
        expect(validate('modes.pinning.band_low', 0.85)).toEqual({ ok: true });
        expect(validate('modes.pinning.band_low', 1.5).ok).toBe(false);
    });

    test('target_humidity=-0.1 → reject', () => {
        expect(validate('modes.fruiting.target_humidity', -0.1).ok).toBe(false);
    });
});

// ---------------------------------------------------------------- toParamValue()

describe('toParamValue', () => {
    test('active_mode → STRING (type:4)', () => {
        expect(toParamValue('active_mode', 'pinning')).toEqual({ type: 4, string_value: 'pinning' });
    });

    test('pid_kp=0.35 → DOUBLE (type:3, double_value), not coerced to integer', () => {
        const v = toParamValue('pid_kp', 0.35);
        expect(v.type).toBe(3);
        expect(v.double_value).toBe(0.35);
        expect(v.integer_value).toBeUndefined();
    });

    test('pid_kp=2 (whole-number JS Number) still serializes as DOUBLE', () => {
        // Pitfall §Pattern 4 type-coercion footgun: type carries from allowlist, NOT from typeof.
        const v = toParamValue('pid_kp', 2);
        expect(v.type).toBe(3);
        expect(v.double_value).toBe(2);
        expect(v.integer_value).toBeUndefined();
    });

    test('modes.pinning.band_low=0.85 → DOUBLE', () => {
        expect(toParamValue('modes.pinning.band_low', 0.85)).toEqual({ type: 3, double_value: 0.85 });
    });

    test('modes.fruiting.defend_side=both → STRING', () => {
        expect(toParamValue('modes.fruiting.defend_side', 'both')).toEqual({ type: 4, string_value: 'both' });
    });

    test('non-allowlisted param throws', () => {
        expect(() => toParamValue('humidifier_pin', 17)).toThrow();
    });
});

// ---------------------------------------------------------------- handler()

describe('handler', () => {
    test('happy path: single param active_mode=pinning → 200', async () => {
        const ros = mkRosNode((req, cb) => cb({ results: [{ successful: true, reason: '' }] }));
        const h = makeHandler(ros);
        const res = mkRes();
        await h({ body: { node: 'fc_controller', param: 'active_mode', value: 'pinning' } }, res);

        expect(res._status).toBe(200);
        expect(res._body.ok).toBe(true);
        expect(res._body.applied).toEqual([{ param: 'active_mode', value: 'pinning' }]);
        expect(ros.createClient).toHaveBeenCalledWith(
            'rcl_interfaces/srv/SetParameters',
            '/fc_controller/set_parameters'
        );
    });

    test('SetParameters request shape matches SPIKE §A: parameters[].value.{type, <X>_value}', async () => {
        let captured = null;
        const ros = mkRosNode((req, cb) => {
            captured = req;
            cb({ results: [{ successful: true, reason: '' }] });
        });
        const h = makeHandler(ros);
        await h({ body: { node: 'fc_controller', param: 'pid_kp', value: 0.35 } }, mkRes());

        expect(captured).toEqual({
            parameters: [{ name: 'pid_kp', value: { type: 3, double_value: 0.35 } }],
        });
    });

    test('batched band_low+band_high in ONE SetParameters call (Pitfall 4 atomicity)', async () => {
        let captured = null;
        const ros = mkRosNode((req, cb) => {
            captured = req;
            cb({ results: [
                { successful: true, reason: '' },
                { successful: true, reason: '' },
            ] });
        });
        const h = makeHandler(ros);
        const res = mkRes();
        await h({
            body: {
                node: 'fc_controller',
                params: [
                    { param: 'modes.pinning.band_low', value: 0.85 },
                    { param: 'modes.pinning.band_high', value: 0.99 },
                ],
            },
        }, res);

        expect(res._status).toBe(200);
        expect(captured.parameters).toHaveLength(2);
        expect(captured.parameters[0].name).toBe('modes.pinning.band_low');
        expect(captured.parameters[1].name).toBe('modes.pinning.band_high');
        // Single sendRequest call — verified by single capture.
        expect(ros.createClient).toHaveBeenCalledTimes(1);
    });

    test('rejects unknown node → 400', async () => {
        const ros = mkRosNode(() => { throw new Error('should not reach'); });
        const h = makeHandler(ros);
        const res = mkRes();
        await h({ body: { node: 'evil_node', param: 'active_mode', value: 'pinning' } }, res);
        expect(res._status).toBe(400);
        expect(res._body.error).toMatch(/node/);
    });

    test('rejects non-allowlisted param humidifier_pin → 400 (T-28-14)', async () => {
        const ros = mkRosNode(() => { throw new Error('should not reach'); });
        const h = makeHandler(ros);
        const res = mkRes();
        await h({ body: { node: 'fc_controller', param: 'humidifier_pin', value: 99 } }, res);
        expect(res._status).toBe(400);
        expect(res._body.rejected_param).toBe('humidifier_pin');
        expect(ros.createClient).not.toHaveBeenCalled();
    });

    test('rejects out-of-range pid_kp=99 → 400 with rejected_param', async () => {
        const ros = mkRosNode(() => { throw new Error('should not reach'); });
        const h = makeHandler(ros);
        const res = mkRes();
        await h({ body: { node: 'fc_controller', param: 'pid_kp', value: 99 } }, res);
        expect(res._status).toBe(400);
        expect(res._body.rejected_param).toBe('pid_kp');
        expect(ros.createClient).not.toHaveBeenCalled();
    });

    test('rejects empty body → 400', async () => {
        const ros = mkRosNode(() => {});
        const h = makeHandler(ros);
        const res = mkRes();
        await h({ body: { node: 'fc_controller' } }, res);
        expect(res._status).toBe(400);
    });

    test('rejects empty params array → 400', async () => {
        const ros = mkRosNode(() => {});
        const h = makeHandler(ros);
        const res = mkRes();
        await h({ body: { node: 'fc_controller', params: [] } }, res);
        expect(res._status).toBe(400);
    });

    test('rejects oversized params array (T-28-18 DoS cap) → 400', async () => {
        const ros = mkRosNode(() => {});
        const h = makeHandler(ros);
        const res = mkRes();
        const big = Array.from({ length: 50 }, () => ({ param: 'pid_kp', value: 0.1 }));
        await h({ body: { node: 'fc_controller', params: big } }, res);
        expect(res._status).toBe(400);
        expect(res._body.error).toMatch(/too many|max/i);
    });

    test('returns 422 with controller reason when rclpy callback rejects', async () => {
        const ros = mkRosNode((req, cb) => cb({
            results: [{ successful: false, reason: 'band_low must be < band_high' }],
        }));
        const h = makeHandler(ros);
        const res = mkRes();
        await h({
            body: { node: 'fc_controller', param: 'modes.pinning.band_low', value: 0.999 },
        }, res);
        expect(res._status).toBe(422);
        expect(res._body.error).toMatch(/band_low/);
        expect(res._body.rejected_param).toBe('modes.pinning.band_low');
    });

    test('returns 500 on createClient throw', async () => {
        const ros = mkRosNode(null, { createClientThrows: 'service not available' });
        const h = makeHandler(ros);
        const res = mkRes();
        await h({ body: { node: 'fc_controller', param: 'active_mode', value: 'pinning' } }, res);
        expect(res._status).toBe(500);
        expect(res._body.error).toMatch(/service not available/);
    });

    test('returns 500 on SetParameters timeout', async () => {
        // sendRequest never invokes callback — handler races with timeout.
        const ros = mkRosNode((req, cb) => { /* never fires */ });
        const h = makeHandler(ros, { timeoutMs: 50 });
        const res = mkRes();
        await h({ body: { node: 'fc_controller', param: 'active_mode', value: 'pinning' } }, res);
        expect(res._status).toBe(500);
        expect(res._body.error).toMatch(/timeout/i);
    });
});

// ---------------------------------------------------------------- Phase 29 ALRT keys
// Phase 29 plan 29-01 — Tier B per-mode alerter overrides + Tier C globals.
// Range bounds mirror fc_controller _validate_params extension (29-03 plan).

describe('Phase 29 ALRT keys', () => {
    test('Test 1: validate(modes.fruiting.alerter.cooldown_min, 30) -> ok', () => {
        expect(validate('modes.fruiting.alerter.cooldown_min', 30)).toEqual({ ok: true });
    });

    test('Test 2: validate(modes.pinning.alerter.cooldown_min, 0) -> not ok (out of [1,240])', () => {
        const r = validate('modes.pinning.alerter.cooldown_min', 0);
        expect(r.ok).toBe(false);
    });

    test('Test 3: validate(modes.fruiting.alerter.cooldown_min, 241) -> not ok', () => {
        const r = validate('modes.fruiting.alerter.cooldown_min', 241);
        expect(r.ok).toBe(false);
    });

    test('Test 4: validate(modes.fruiting.alerter.critical_cooldown_min, 60) -> ok', () => {
        expect(validate('modes.fruiting.alerter.critical_cooldown_min', 60)).toEqual({ ok: true });
    });

    test('Test 5: validate(modes.fruiting.alerter.humidifier_stuck_min, 30) -> ok', () => {
        expect(validate('modes.fruiting.alerter.humidifier_stuck_min', 30)).toEqual({ ok: true });
    });

    test('Test 6: validate(modes.pinning.alerter.oob_n, 5) -> ok', () => {
        expect(validate('modes.pinning.alerter.oob_n', 5)).toEqual({ ok: true });
    });

    test('Test 7: validate(modes.fruiting.alerter.oob_window_min, 3) -> ok', () => {
        expect(validate('modes.fruiting.alerter.oob_window_min', 3)).toEqual({ ok: true });
    });

    test('Test 8: pi_offline_min: 5 ok, 61 not ok (range [1,60])', () => {
        expect(validate('pi_offline_min', 5)).toEqual({ ok: true });
        expect(validate('pi_offline_min', 61).ok).toBe(false);
    });

    test('Test 9: sensor_offline_min: 5 ok, range [1,60]', () => {
        expect(validate('sensor_offline_min', 5)).toEqual({ ok: true });
        expect(validate('sensor_offline_min', 0).ok).toBe(false);
        expect(validate('sensor_offline_min', 61).ok).toBe(false);
    });

    test('Test 10: heartbeat_hour: 8 ok, 24 not ok (range [0,23])', () => {
        expect(validate('heartbeat_hour', 8)).toEqual({ ok: true });
        expect(validate('heartbeat_hour', 0)).toEqual({ ok: true });
        expect(validate('heartbeat_hour', 24).ok).toBe(false);
    });

    test('Test 11: max_sends_per_hour: 20 ok, 0 not ok (range [1,200])', () => {
        expect(validate('max_sends_per_hour', 20)).toEqual({ ok: true });
        expect(validate('max_sends_per_hour', 0).ok).toBe(false);
        expect(validate('max_sends_per_hour', 201).ok).toBe(false);
    });

    test('Test 12: validate(modes.unknown.alerter.cooldown_min, 30) -> not ok (unknown mode)', () => {
        const r = validate('modes.unknown.alerter.cooldown_min', 30);
        expect(r.ok).toBe(false);
    });

    test('Test 13: toParamValue(pi_offline_min, 5) -> integer wire shape', () => {
        expect(toParamValue('pi_offline_min', 5)).toEqual({ type: 2, integer_value: 5 });
    });

    test('Test 14: toParamValue(modes.fruiting.alerter.cooldown_min, 30) -> integer wire shape', () => {
        expect(toParamValue('modes.fruiting.alerter.cooldown_min', 30))
            .toEqual({ type: 2, integer_value: 30 });
    });

    // Defense-in-depth (T-29-01): fractional doubles must be rejected, not silently truncated.
    test('Bonus: fractional value (5.5) rejected for integer-typed key', () => {
        expect(validate('pi_offline_min', 5.5).ok).toBe(false);
    });
});

// ---------------------------------------------------------------- Phase 30 SCHED keys
// Plan 30-02 — schedule_windows JSON-encoded list. Mirrors the rclpy controller
// validator from Plan 30-01 (defense in depth — T-30-06).

describe('schedule_windows', () => {
    test('schedule_windows is allowlisted', () => {
        expect(ALLOWLIST['schedule_windows']).toBeDefined();
        expect(ALLOWLIST['schedule_windows'].type).toBe(4); // T_STRING
    });

    test('empty array → ok', () => {
        expect(validate('schedule_windows', '[]')).toEqual({ ok: true });
    });

    test('valid two-window schedule → ok', () => {
        const v = '[{"start":"06:00","end":"22:00","mode":"fruiting"},{"start":"22:00","end":"06:00","mode":"pinning"}]';
        expect(validate('schedule_windows', v)).toEqual({ ok: true });
    });

    test('wraparound window end<start → ok (D-02 wraparound is valid)', () => {
        const v = '[{"start":"22:00","end":"06:00","mode":"pinning"}]';
        expect(validate('schedule_windows', v)).toEqual({ ok: true });
    });

    test('malformed JSON → reject', () => {
        const r = validate('schedule_windows', '{not json');
        expect(r.ok).toBe(false);
        expect(r.reason).toMatch(/JSON/);
    });

    test('non-array root → reject', () => {
        const r = validate('schedule_windows', '{"start":"06:00"}');
        expect(r.ok).toBe(false);
        expect(r.reason).toMatch(/array/);
    });

    test('missing key (mode) → reject', () => {
        const r = validate('schedule_windows', '[{"start":"06:00","end":"22:00"}]');
        expect(r.ok).toBe(false);
        expect(r.reason).toMatch(/missing key mode/);
    });

    test('bad HH:MM (single-digit hour) → reject', () => {
        const r = validate('schedule_windows', '[{"start":"6:00","end":"22:00","mode":"fruiting"}]');
        expect(r.ok).toBe(false);
        expect(r.reason).toMatch(/HH:MM/);
    });

    test('bad minutes (06:60) → reject', () => {
        const r = validate('schedule_windows', '[{"start":"06:60","end":"22:00","mode":"fruiting"}]');
        expect(r.ok).toBe(false);
    });

    test('hour out of range (24:00 as start) → reject', () => {
        const r = validate('schedule_windows', '[{"start":"24:00","end":"22:00","mode":"fruiting"}]');
        expect(r.ok).toBe(false);
    });

    test('unknown mode → reject', () => {
        const r = validate('schedule_windows', '[{"start":"06:00","end":"22:00","mode":"composting"}]');
        expect(r.ok).toBe(false);
        expect(r.reason).toMatch(/declared|not in/);
    });

    test('non-string value (raw number) → reject', () => {
        const r = validate('schedule_windows', 42);
        expect(r.ok).toBe(false);
    });

    test('element not an object → reject', () => {
        const r = validate('schedule_windows', '["fruiting"]');
        expect(r.ok).toBe(false);
    });
});

describe('schedule_windows handler', () => {
    test('POST schedule_windows=[] forwards as STRING via SetParameters', async () => {
        let captured = null;
        const ros = mkRosNode((req, cb) => {
            captured = req;
            cb({ results: [{ successful: true, reason: '' }] });
        });
        const h = makeHandler(ros);
        const res = mkRes();
        await h({
            body: { node: 'fc_controller', param: 'schedule_windows', value: '[]' },
        }, res);

        expect(res._status).toBe(200);
        expect(res._body.ok).toBe(true);
        expect(res._body.applied).toEqual([{ param: 'schedule_windows', value: '[]' }]);
        expect(captured).toEqual({
            parameters: [{ name: 'schedule_windows', value: { type: 4, string_value: '[]' } }],
        });
    });
});
