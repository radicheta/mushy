// Phase 28 plan 28-05 — D-17 Layer 1: live param tuning hot path.
//
// Allowlist hardcoded here (Threat T-28-15: never load from disk).
// All bridge SetParameters traffic flows through this module — index.js does
// not touch rclnodejs SetParameters directly (Pitfall 8 — keep the
// buffer-replay path at index.js:613 untouched).
//
// rclnodejs request shape locked in 28-01-SPIKE.md §A:
//   { parameters: [{ name, value: { type: int, <X>_value } }] }
//   response:    { results:    [{ successful: bool, reason: string }, ...] }
//
// Range bounds mirror the rclpy on_set_parameters_callback validator landed
// in plan 28-04 (defense in depth — T-28-09).

'use strict';

const ALLOWED_NODES = new Set(['fc_controller']);

// rcl_interfaces/msg/ParameterType — canonical ROS2 enum (D-A3).
const T_BOOL = 1;
const T_INTEGER = 2;
const T_DOUBLE = 3;
const T_STRING = 4;

// Hardcoded; new modes are deploys (CONTEXT D-03).
const DECLARED_MODES = ['fruiting', 'pinning'];
const DEFEND_SIDES = new Set(['low', 'high', 'both']);

// T-28-18 cap on params batch size to bound DoS surface.
// Controller has ~15 allowlistable params total; 20 is a comfortable ceiling.
const MAX_PARAMS_PER_REQUEST = 20;

const DEFAULT_TIMEOUT_MS = 3000;

function inRange(v, lo, hi) {
    return typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi;
}
function inRangeOrNaN(v, lo, hi) {
    return (typeof v === 'number' && Number.isNaN(v)) || inRange(v, lo, hi);
}

// Per-param entry: { type, validate(v) -> {ok, reason?} }.
function entryUnitDouble(label) {
    return {
        type: T_DOUBLE,
        validate: (v) => inRange(v, 0, 1)
            ? { ok: true }
            : { ok: false, reason: `${label} out of [0,1]` },
    };
}
function entryDefendSide() {
    return {
        type: T_STRING,
        validate: (v) => DEFEND_SIDES.has(v)
            ? { ok: true }
            : { ok: false, reason: 'defend_side must be low|high|both' },
    };
}
function entryTtarget() {
    return {
        type: T_DOUBLE,
        validate: (v) => inRangeOrNaN(v, 0, 40)
            ? { ok: true }
            : { ok: false, reason: 't_target must be NaN or in [0,40]' },
    };
}
function entryDoubleRange(label, lo, hi) {
    return {
        type: T_DOUBLE,
        validate: (v) => inRange(v, lo, hi)
            ? { ok: true }
            : { ok: false, reason: `${label} out of [${lo},${hi}]` },
    };
}

const ALLOWLIST = (() => {
    const a = Object.create(null);

    a['active_mode'] = {
        type: T_STRING,
        validate: (v) => DECLARED_MODES.includes(v)
            ? { ok: true }
            : { ok: false, reason: `active_mode ${JSON.stringify(v)} not in ${JSON.stringify(DECLARED_MODES)}` },
    };

    for (const m of DECLARED_MODES) {
        a[`modes.${m}.target_humidity`] = entryUnitDouble('target_humidity');
        a[`modes.${m}.band_low`]        = entryUnitDouble('band_low');
        a[`modes.${m}.band_high`]       = entryUnitDouble('band_high');
        a[`modes.${m}.defend_side`]     = entryDefendSide();
        a[`modes.${m}.t_target`]        = entryTtarget();
    }

    // PID range bounds — mirror Phase 28-04 controller validator (T-28-09).
    a['pid_kp'] = entryDoubleRange('pid_kp', 0, 5);
    a['pid_ki'] = entryDoubleRange('pid_ki', 0, 1);
    a['pid_kd'] = entryDoubleRange('pid_kd', 0, 20);

    return a;
})();

function validate(param, value) {
    const spec = ALLOWLIST[param];
    if (!spec) return { ok: false, reason: `param ${param} not allowlisted` };
    return spec.validate(value);
}

function toParamValue(param, value) {
    const spec = ALLOWLIST[param];
    if (!spec) throw new Error(`toParamValue called for non-allowlisted param ${param}`);
    switch (spec.type) {
        case T_BOOL:    return { type: T_BOOL,    bool_value: !!value };
        case T_INTEGER: return { type: T_INTEGER, integer_value: Math.trunc(value) };
        case T_DOUBLE:  return { type: T_DOUBLE,  double_value: Number(value) };
        case T_STRING:  return { type: T_STRING,  string_value: String(value) };
        default:        throw new Error(`unknown type ${spec.type} for ${param}`);
    }
}

// Handler factory — accepts the (already-spinning) rclnodejs Node so callers
// reuse the bridge's existing rosNode. Tests inject a mock node.
function makeHandler(rosNode, opts = {}) {
    const timeoutMs = opts.timeoutMs || DEFAULT_TIMEOUT_MS;

    return async function handle(req, res) {
        const body = req.body || {};
        const node = body.node;
        if (!ALLOWED_NODES.has(node)) {
            return res.status(400).json({ error: `node ${JSON.stringify(node)} not allowlisted` });
        }

        // Normalize single + batched forms.
        let params;
        if (Array.isArray(body.params)) {
            params = body.params;
        } else if (body.param != null) {
            params = [{ param: body.param, value: body.value }];
        } else {
            return res.status(400).json({ error: 'body must include `param`+`value` or `params: []`' });
        }
        if (params.length === 0) {
            return res.status(400).json({ error: 'params array is empty' });
        }
        if (params.length > MAX_PARAMS_PER_REQUEST) {
            return res.status(400).json({
                error: `too many params (max ${MAX_PARAMS_PER_REQUEST})`,
            });
        }

        // Validate every entry BEFORE sending — atomicity at the bridge mirrors
        // rclpy whole-batch atomicity (Pitfall 4).
        for (const { param, value } of params) {
            const v = validate(param, value);
            if (!v.ok) return res.status(400).json({ error: v.reason, rejected_param: param });
        }

        // Build ONE SetParameters request with all params (Pitfall 4 atomicity).
        const reqMsg = {
            parameters: params.map(({ param, value }) => ({
                name: param,
                value: toParamValue(param, value),
            })),
        };

        let cli;
        try {
            cli = rosNode.createClient(
                'rcl_interfaces/srv/SetParameters',
                `/${node}/set_parameters`
            );
        } catch (e) {
            return res.status(500).json({ error: `createClient failed: ${e.message}` });
        }

        try {
            const resp = await new Promise((resolve, reject) => {
                let settled = false;
                const timer = setTimeout(() => {
                    if (settled) return;
                    settled = true;
                    reject(new Error(`SetParameters timeout after ${timeoutMs}ms`));
                }, timeoutMs);

                try {
                    cli.sendRequest(reqMsg, (r) => {
                        if (settled) return;
                        settled = true;
                        clearTimeout(timer);
                        if (r) resolve(r);
                        else reject(new Error('rclnodejs returned no response'));
                    });
                } catch (e) {
                    if (settled) return;
                    settled = true;
                    clearTimeout(timer);
                    reject(e);
                }
            });

            // resp.results: [{successful, reason}, ...] in same order as request.parameters.
            const results = resp.results || [];
            for (let i = 0; i < results.length; i++) {
                const r = results[i];
                if (!r.successful) {
                    return res.status(422).json({
                        error: r.reason || 'controller rejected',
                        rejected_param: params[i].param,
                    });
                }
            }

            return res.json({
                ok: true,
                applied: params.map(({ param, value }) => ({ param, value })),
            });
        } catch (e) {
            return res.status(500).json({ error: e.message });
        }
    };
}

module.exports = {
    ALLOWLIST,
    DECLARED_MODES,
    MAX_PARAMS_PER_REQUEST,
    validate,
    toParamValue,
    makeHandler,
};
