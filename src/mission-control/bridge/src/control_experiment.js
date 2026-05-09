// Phase 31 D-18/D-19: experiment control endpoints.
//
// Bridge-side surface for forcing experiments. Mirrors control_param.js style:
//   - dependency injection (rosNode passed in via factory)
//   - handler-factory pattern with Promise-wrapped service calls + timeout
//   - defense-in-depth validation (D-19) duplicating controller's D-11 rules
//
// Three HTTP endpoints (wired in index.js):
//   POST /control/experiment           — start a force experiment with TTL
//   POST /control/cancel-experiment    — early-revert
//   GET  /control/experiment           — current state (server-computed seconds_remaining)
//
// One topic subscriber (wired in index.js):
//   /fc1/control/experiment_event (std_msgs/String JSON-in-String, TRANSIENT_LOCAL)
//     → INSERT/UPDATE rows in fc_experiments per CONTEXT D-22.
//
// One DB migration:
//   migrateExperimentSchema(pool) — idempotent fc_experiments table per D-21.

'use strict';

const VALID_NAMES = new Set(['force-condensation', 'force-evaporation']);
const HARD_CAP_MIN = 120;        // CONTEXT D-14
const DEFAULT_DURATION_MIN = 15; // CONTEXT D-14
const DEFAULT_TIMEOUT_MS = 3000;

// =====================================================================
// HTTP layer — validation + service-call handlers
// =====================================================================

function validate(name, duration_minutes) {
    if (!name || !VALID_NAMES.has(name)) {
        return {
            ok: false,
            reason: `name must be force-condensation or force-evaporation; got ${JSON.stringify(name)}`,
        };
    }
    const dur = (duration_minutes === undefined || duration_minutes === null)
        ? DEFAULT_DURATION_MIN
        : duration_minutes;
    if (typeof dur !== 'number' || !Number.isInteger(dur)) {
        return { ok: false, reason: `duration_minutes must be an integer; got ${JSON.stringify(duration_minutes)}` };
    }
    if (dur < 1 || dur > HARD_CAP_MIN) {
        return { ok: false, reason: `duration_minutes must be in [1, ${HARD_CAP_MIN}]; got ${dur}` };
    }
    return { ok: true, duration_minutes: dur };
}

function _callService(rosNode, srvType, srvName, request, timeoutMs) {
    return new Promise((resolve, reject) => {
        let cli;
        try {
            cli = rosNode.createClient(srvType, srvName);
        } catch (e) {
            return reject(new Error(`createClient failed: ${e.message}`));
        }
        let settled = false;
        const timer = setTimeout(() => {
            if (settled) return;
            settled = true;
            reject(new Error(`${srvName} timeout after ${timeoutMs}ms`));
        }, timeoutMs);
        try {
            cli.sendRequest(request, (r) => {
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
}

function makeStartHandler(rosNode, opts = {}) {
    const timeoutMs = opts.timeoutMs || DEFAULT_TIMEOUT_MS;
    return async function handle(req, res) {
        if (!rosNode) return res.status(503).json({ error: 'rclnodejs not ready' });
        const body = req.body || {};
        const v = validate(body.name, body.duration_minutes);
        if (!v.ok) return res.status(400).json({ error: v.reason });
        try {
            const resp = await _callService(
                rosNode,
                'fc_msgs/srv/StartExperiment',
                // 2026-05-09 lab: namespaced path /fc_controller/start_experiment hangs at service-discovery
                // even from local CLI; un-namespaced /start_experiment works. Both appear in `ros2 service list`.
                '/start_experiment',
                { experiment_name: body.name, duration_minutes: v.duration_minutes },
                timeoutMs,
            );
            if (resp.ok) {
                return res.status(200).json({
                    ok: true,
                    started_at_iso: resp.started_at_iso,
                    reverts_at_iso: resp.reverts_at_iso,
                    prior_mode: resp.prior_mode,
                });
            }
            return res.status(400).json({ ok: false, error: resp.message || 'rejected' });
        } catch (e) {
            const status = /timeout/i.test(e.message) ? 504 : 500;
            return res.status(status).json({ error: e.message });
        }
    };
}

function makeCancelHandler(rosNode, opts = {}) {
    const timeoutMs = opts.timeoutMs || DEFAULT_TIMEOUT_MS;
    return async function handle(req, res) {
        if (!rosNode) return res.status(503).json({ error: 'rclnodejs not ready' });
        try {
            const resp = await _callService(
                rosNode,
                'fc_msgs/srv/CancelExperiment',
                // see start_experiment note above — un-namespaced path is the working one
                '/cancel_experiment',
                {},
                timeoutMs,
            );
            if (resp.ok) {
                return res.status(200).json({ ok: true, ended_at_iso: resp.ended_at_iso });
            }
            return res.status(400).json({ ok: false, error: resp.message || 'rejected' });
        } catch (e) {
            const status = /timeout/i.test(e.message) ? 504 : 500;
            return res.status(status).json({ error: e.message });
        }
    };
}

function makeStateHandler(opts = {}) {
    // opts.getLastEvent() — () => last experiment_event JSON or null. Test seam.
    // opts.now()          — () => ms since epoch. Test seam — defaults to Date.now.
    const getLastEvent = opts.getLastEvent || (() => null);
    const now = opts.now || (() => Date.now());
    return function handle(req, res) {
        const ev = getLastEvent();
        if (!ev || ev.event !== 'started') {
            return res.status(200).json({ active: false });
        }
        const reverts_ms = Date.parse(ev.reverts_at_iso);
        const seconds_remaining = Math.max(0, Math.floor((reverts_ms - now()) / 1000));
        return res.status(200).json({
            active: true,
            experiment: ev.experiment,
            prior_mode: ev.prior_mode,
            started_at_iso: ev.started_at_iso,
            reverts_at_iso: ev.reverts_at_iso,
            requested_minutes: ev.requested_minutes,
            seconds_remaining,
        });
    };
}

// =====================================================================
// DB layer — schema migration + experiment_event subscriber handler
// =====================================================================

const FC_EXPERIMENTS_DDL = `
    CREATE TABLE IF NOT EXISTS fc_experiments (
        id            BIGSERIAL PRIMARY KEY,
        started_at    TIMESTAMPTZ NOT NULL,
        ended_at      TIMESTAMPTZ,
        experiment    TEXT NOT NULL,
        prior_mode    TEXT NOT NULL,
        requested_min INT NOT NULL,
        actual_min    REAL,
        baseline_rh   REAL,
        final_rh      REAL,
        delta_rh      REAL,
        end_reason    TEXT
    )
`;
const FC_EXPERIMENTS_INDEX_DDL = `
    CREATE INDEX IF NOT EXISTS idx_fc_experiments_started_at
    ON fc_experiments (started_at DESC)
`;

async function migrateExperimentSchema(pool) {
    await pool.query(FC_EXPERIMENTS_DDL);
    await pool.query(FC_EXPERIMENTS_INDEX_DDL);
}

const END_REASON_MAP = {
    ended: 'timeout',
    cancelled: 'cancelled',
    truncated: 'truncated_by_restart',
};

function makeExperimentEventHandler({
    pool,
    getLastRh,         // () => number | null (last live RH from telemetry buffer)
    setLastEventCache, // (payload) => void
    broadcast,         // (payload) => void
    logger = console,
}) {
    const _setLastEventCache = setLastEventCache || (() => {});
    const _broadcast = broadcast || (() => {});
    const _getLastRh = getLastRh || (() => null);

    return async function handle(payload) {
        try {
            if (!payload || typeof payload.event !== 'string') {
                logger.warn('[experiment_event] malformed payload (no event field)');
                return;
            }
            if (payload.event === 'started') {
                if (!payload.experiment || !payload.prior_mode) {
                    logger.warn('[experiment_event] started payload missing experiment/prior_mode');
                    return;
                }
                const baseline_rh = _getLastRh();
                await pool.query(
                    `INSERT INTO fc_experiments
                       (started_at, experiment, prior_mode, requested_min, baseline_rh)
                     VALUES ($1::timestamptz, $2, $3, $4, $5)`,
                    [
                        payload.started_at_iso,
                        payload.experiment,
                        payload.prior_mode,
                        payload.requested_minutes,
                        baseline_rh,
                    ],
                );
                _setLastEventCache(payload);
                _broadcast(payload);
                logger.info(`[experiment_event] started: ${payload.experiment} (${payload.requested_minutes}min, baseline_rh=${baseline_rh})`);
                return;
            }
            if (END_REASON_MAP[payload.event]) {
                const final_rh = _getLastRh();
                const sel = await pool.query(
                    `SELECT id, baseline_rh
                     FROM fc_experiments
                     WHERE ended_at IS NULL
                     ORDER BY started_at DESC
                     LIMIT 1`,
                );
                if (sel.rows.length === 0) {
                    logger.warn(`[experiment_event] ${payload.event} but no open row — late-arriving event?`);
                    _setLastEventCache(payload);
                    _broadcast(payload);
                    return;
                }
                const { id, baseline_rh } = sel.rows[0];
                const delta_rh = (
                    final_rh != null && baseline_rh != null
                        ? final_rh - baseline_rh
                        : null
                );
                await pool.query(
                    `UPDATE fc_experiments
                     SET ended_at  = NOW(),
                         actual_min = $1,
                         final_rh   = $2,
                         delta_rh   = $3,
                         end_reason = $4
                     WHERE id = $5`,
                    [
                        payload.actual_minutes,
                        final_rh,
                        delta_rh,
                        END_REASON_MAP[payload.event],
                        id,
                    ],
                );
                _setLastEventCache(payload);
                _broadcast(payload);
                logger.info(`[experiment_event] ${payload.event}: id=${id}, actual=${payload.actual_minutes}min, final_rh=${final_rh}, delta=${delta_rh}`);
                return;
            }
            logger.warn(`[experiment_event] unknown event ${JSON.stringify(payload.event)}`);
        } catch (e) {
            // NEVER let DB errors crash the rclnodejs subscription thread.
            logger.warn(`[experiment_event] handler error: ${e.message}`);
        }
    };
}

module.exports = {
    VALID_NAMES,
    HARD_CAP_MIN,
    DEFAULT_DURATION_MIN,
    validate,
    makeStartHandler,
    makeCancelHandler,
    makeStateHandler,
    migrateExperimentSchema,
    makeExperimentEventHandler,
    FC_EXPERIMENTS_DDL,
    FC_EXPERIMENTS_INDEX_DDL,
    END_REASON_MAP,
};
