// Phase 31 plan 31-03 — Jest tests for the experiment_event subscriber handler
// (DB INSERT/UPDATE path) + migration idempotency.

const {
    migrateExperimentSchema,
    makeExperimentEventHandler,
    FC_EXPERIMENTS_DDL,
    END_REASON_MAP,
} = require('../src/control_experiment');

// Mock pg pool helper. queryImpl receives (sql, params, callIndex) and returns
// the (sync) result row-shape; the wrapper resolves Promise<result>.
function mkPool(queryImpl = () => ({ rows: [], rowCount: 0 })) {
    const calls = [];
    return {
        _calls: calls,
        query: jest.fn((sql, params) => {
            calls.push({ sql, params });
            return Promise.resolve(queryImpl(sql, params, calls.length - 1));
        }),
    };
}

function mkLogger() {
    return {
        infos: [],
        warns: [],
        errors: [],
        info(...a) { this.infos.push(a.join(' ')); },
        warn(...a) { this.warns.push(a.join(' ')); },
        error(...a) { this.errors.push(a.join(' ')); },
    };
}

// =====================================================================
// migrateExperimentSchema
// =====================================================================

describe('migrateExperimentSchema', () => {
    test('issues CREATE TABLE then CREATE INDEX', async () => {
        const pool = mkPool();
        await migrateExperimentSchema(pool);
        expect(pool._calls).toHaveLength(2);
        expect(pool._calls[0].sql).toMatch(/CREATE TABLE IF NOT EXISTS fc_experiments/);
        expect(pool._calls[1].sql).toMatch(/CREATE INDEX IF NOT EXISTS/);
        expect(pool._calls[1].sql).toMatch(/started_at DESC/);
    });

    test('idempotent — second invocation just re-issues both DDLs', async () => {
        const pool = mkPool();
        await migrateExperimentSchema(pool);
        await migrateExperimentSchema(pool);
        expect(pool._calls).toHaveLength(4);
    });

    test('DDL exports include all 11 columns', () => {
        // Sanity check — schema drift between plan and code should fail this test.
        for (const col of [
            'id', 'started_at', 'ended_at', 'experiment', 'prior_mode',
            'requested_min', 'actual_min', 'baseline_rh', 'final_rh',
            'delta_rh', 'end_reason',
        ]) {
            expect(FC_EXPERIMENTS_DDL).toMatch(new RegExp(col));
        }
    });
});

// =====================================================================
// makeExperimentEventHandler — INSERT on 'started'
// =====================================================================

describe('experiment_event subscriber — started event', () => {
    test('inserts row with baseline_rh from telemetry', async () => {
        const pool = mkPool();
        const cache = [];
        const broadcasts = [];
        const handler = makeExperimentEventHandler({
            pool,
            getLastRh: () => 84.0,
            setLastEventCache: (p) => cache.push(p),
            broadcast: (p) => broadcasts.push(p),
            logger: mkLogger(),
        });
        await handler({
            event: 'started',
            experiment: 'force-condensation',
            prior_mode: 'fruiting',
            requested_minutes: 15,
            actual_minutes: null,
            started_at_iso: '2026-05-08T18:00:00Z',
            ended_at_iso: null,
            reverts_at_iso: '2026-05-08T18:15:00Z',
            wall_clock_iso: '2026-05-08T18:00:00Z',
        });
        expect(pool._calls).toHaveLength(1);
        expect(pool._calls[0].sql).toMatch(/INSERT INTO fc_experiments/);
        expect(pool._calls[0].params).toEqual([
            '2026-05-08T18:00:00Z',
            'force-condensation',
            'fruiting',
            15,
            84.0,
        ]);
        expect(cache).toHaveLength(1);
        expect(cache[0].event).toBe('started');
        expect(broadcasts).toHaveLength(1);
    });

    test('inserts with NULL baseline when getLastRh returns null', async () => {
        const pool = mkPool();
        const handler = makeExperimentEventHandler({
            pool,
            getLastRh: () => null,
            setLastEventCache: () => {},
            broadcast: () => {},
        });
        await handler({
            event: 'started',
            experiment: 'force-evaporation',
            prior_mode: 'pinning',
            requested_minutes: 30,
            started_at_iso: '2026-05-08T18:00:00Z',
            reverts_at_iso: '2026-05-08T18:30:00Z',
        });
        expect(pool._calls[0].params[4]).toBeNull();
    });

    test('started missing experiment field → warn, no INSERT', async () => {
        const pool = mkPool();
        const log = mkLogger();
        const handler = makeExperimentEventHandler({
            pool, getLastRh: () => 90, setLastEventCache: () => {}, broadcast: () => {}, logger: log,
        });
        await handler({ event: 'started', requested_minutes: 15 });
        expect(pool._calls).toHaveLength(0);
        expect(log.warns.some((m) => /missing experiment/.test(m))).toBe(true);
    });
});

// =====================================================================
// makeExperimentEventHandler — UPDATE on terminal events
// =====================================================================

describe('experiment_event subscriber — terminal events', () => {
    function setupForUpdate({ baseline_rh, final_rh, rowCount = 1 }) {
        const pool = mkPool((sql, params, idx) => {
            // First call: SELECT id, baseline_rh ... LIMIT 1
            if (/SELECT id, baseline_rh/.test(sql)) {
                return rowCount === 0
                    ? { rows: [], rowCount: 0 }
                    : { rows: [{ id: 42, baseline_rh }], rowCount: 1 };
            }
            // Second call: UPDATE ...
            return { rows: [], rowCount: 1 };
        });
        const handler = makeExperimentEventHandler({
            pool,
            getLastRh: () => final_rh,
            setLastEventCache: () => {},
            broadcast: () => {},
            logger: mkLogger(),
        });
        return { pool, handler };
    }

    test('ended → UPDATE with end_reason=timeout, computed delta_rh', async () => {
        const { pool, handler } = setupForUpdate({ baseline_rh: 84.0, final_rh: 95.0 });
        await handler({
            event: 'ended',
            experiment: 'force-condensation',
            prior_mode: 'fruiting',
            requested_minutes: 15,
            actual_minutes: 14.97,
            started_at_iso: '2026-05-08T18:00:00Z',
            ended_at_iso: '2026-05-08T18:14:58Z',
            wall_clock_iso: '2026-05-08T18:14:58Z',
        });
        // 1st call SELECT, 2nd UPDATE.
        expect(pool._calls[1].sql).toMatch(/UPDATE fc_experiments/);
        const params = pool._calls[1].params;
        expect(params[0]).toBe(14.97);            // actual_min
        expect(params[1]).toBe(95.0);             // final_rh
        expect(params[2]).toBeCloseTo(11.0, 5);   // delta_rh = 95-84
        expect(params[3]).toBe('timeout');        // end_reason
        expect(params[4]).toBe(42);               // id
    });

    test('cancelled → end_reason=cancelled', async () => {
        const { pool, handler } = setupForUpdate({ baseline_rh: 60, final_rh: 70 });
        await handler({
            event: 'cancelled',
            experiment: 'force-evaporation',
            prior_mode: 'fruiting',
            requested_minutes: 5,
            actual_minutes: 1.2,
        });
        expect(pool._calls[1].params[3]).toBe('cancelled');
    });

    test('truncated → end_reason=truncated_by_restart', async () => {
        const { pool, handler } = setupForUpdate({ baseline_rh: null, final_rh: null });
        await handler({
            event: 'truncated',
            experiment: null,
            prior_mode: null,
            requested_minutes: null,
            actual_minutes: null,
        });
        expect(pool._calls[1].params[3]).toBe('truncated_by_restart');
        // delta_rh NULL when either side is null.
        expect(pool._calls[1].params[2]).toBeNull();
    });

    test('NULL-safe delta_rh when final_rh is null', async () => {
        const { pool, handler } = setupForUpdate({ baseline_rh: 80, final_rh: null });
        await handler({
            event: 'ended',
            actual_minutes: 14.5,
        });
        expect(pool._calls[1].params[2]).toBeNull();
    });

    test('NULL-safe delta_rh when baseline_rh is null', async () => {
        const { pool, handler } = setupForUpdate({ baseline_rh: null, final_rh: 92 });
        await handler({ event: 'ended', actual_minutes: 14.5 });
        expect(pool._calls[1].params[2]).toBeNull();
    });

    test('no open row → warn only, NO update issued', async () => {
        const { pool, handler } = setupForUpdate({ baseline_rh: 80, final_rh: 90, rowCount: 0 });
        await handler({ event: 'ended', actual_minutes: 14.0 });
        // SELECT happened, UPDATE did NOT.
        expect(pool._calls.filter((c) => /UPDATE/.test(c.sql))).toHaveLength(0);
    });
});

// =====================================================================
// makeExperimentEventHandler — defensive (malformed inputs)
// =====================================================================

describe('experiment_event subscriber — defensive', () => {
    test('null payload → warn, no throw', async () => {
        const pool = mkPool();
        const log = mkLogger();
        const handler = makeExperimentEventHandler({ pool, getLastRh: () => 80, logger: log });
        await expect(handler(null)).resolves.toBeUndefined();
        expect(log.warns.some((m) => /malformed/.test(m))).toBe(true);
        expect(pool._calls).toHaveLength(0);
    });

    test('payload missing event field → warn, no throw', async () => {
        const log = mkLogger();
        const handler = makeExperimentEventHandler({
            pool: mkPool(), getLastRh: () => 80, logger: log,
        });
        await handler({ foo: 'bar' });
        expect(log.warns.some((m) => /malformed/.test(m))).toBe(true);
    });

    test('unknown event name → warn, no throw', async () => {
        const log = mkLogger();
        const handler = makeExperimentEventHandler({
            pool: mkPool(), getLastRh: () => 80, logger: log,
        });
        await handler({ event: 'wat' });
        expect(log.warns.some((m) => /unknown event/.test(m))).toBe(true);
    });

    test('DB throws → handler swallows, does not propagate', async () => {
        const pool = {
            query: jest.fn(() => Promise.reject(new Error('pg boom'))),
            _calls: [],
        };
        const log = mkLogger();
        const handler = makeExperimentEventHandler({
            pool, getLastRh: () => 80, logger: log,
        });
        await expect(handler({
            event: 'started',
            experiment: 'force-condensation',
            prior_mode: 'fruiting',
            requested_minutes: 15,
            started_at_iso: '2026-05-08T18:00:00Z',
        })).resolves.toBeUndefined();
        expect(log.warns.some((m) => /pg boom/.test(m))).toBe(true);
    });
});

describe('END_REASON_MAP', () => {
    test('maps all three terminal events', () => {
        expect(END_REASON_MAP.ended).toBe('timeout');
        expect(END_REASON_MAP.cancelled).toBe('cancelled');
        expect(END_REASON_MAP.truncated).toBe('truncated_by_restart');
    });
});
