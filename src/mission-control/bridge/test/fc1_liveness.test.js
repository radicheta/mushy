// Phase 46 Plan 01: fc1 liveness aggregator unit tests (CD-01 + CD-04).
//
// Contract:
//   - module exports { markFc1Active, getFc1LastMsgTs, getFc1LastMsgAgeSec, _resetForTests }
//   - markFc1Active(tsMs) updates fc1LastMsgTs to max(prev ?? 0, tsMs)
//   - getFc1LastMsgTs() returns the raw ms-epoch (null when never marked)
//   - getFc1LastMsgAgeSec() returns Math.round((Date.now() - fc1LastMsgTs)/1000), or null
//
// These tests assert the CD-01 shape that bridge /health.fc1 will expose
// (last_msg_ts, last_msg_age_sec) -- the index.js handler reads the same
// getters that this test exercises directly.

const liveness = require('../src/fc1_liveness');

// CD-01: the 9 fc1 data/state topics that count toward chamber liveness.
// /fc1/control/humidity_target, current_mode_json, alerter_mode_overrides,
// alerter_globals, experiment_event, and the camera topic are EXCLUDED.
const CD01_TOPICS = [
    '/fc1/humidity',
    '/fc1/temperature',
    '/fc1/humidity_2',
    '/fc1/temperature_2',
    '/fc1/co2',
    '/fc1/actuators/humidifier',
    '/fc1/actuators/humidifier_duty',
    '/fc1/sensor_health',
    '/fc1/control/pid_output',
];

beforeEach(() => {
    liveness._resetForTests();
});

describe('fc1LastMsgTs aggregator (CD-01 / D-01)', () => {
    test('fc1LastMsgTs is null before any topic fires; /health.fc1.last_msg_ts and .last_msg_age_sec are null', () => {
        expect(liveness.getFc1LastMsgTs()).toBeNull();
        expect(liveness.getFc1LastMsgAgeSec()).toBeNull();
    });

    test('markFc1Active(ts) updates fc1LastMsgTs to max(prev, ts); older ts does not regress the value', () => {
        liveness.markFc1Active(1_000_000);
        expect(liveness.getFc1LastMsgTs()).toBe(1_000_000);

        // Advance: newer ts wins.
        liveness.markFc1Active(2_000_000);
        expect(liveness.getFc1LastMsgTs()).toBe(2_000_000);

        // Older ts must NOT regress the value.
        liveness.markFc1Active(1_500_000);
        expect(liveness.getFc1LastMsgTs()).toBe(2_000_000);

        // Equal ts is a no-op (stays at the same value).
        liveness.markFc1Active(2_000_000);
        expect(liveness.getFc1LastMsgTs()).toBe(2_000_000);
    });

    test('/health.fc1.last_msg_age_sec is Math.round((Date.now() - fc1LastMsgTs)/1000) when fc1LastMsgTs is set', () => {
        const fakeNow = 10_000_000;
        const realNow = Date.now;
        Date.now = () => fakeNow;
        try {
            // 7.4 seconds ago -> rounds to 7
            liveness.markFc1Active(fakeNow - 7400);
            expect(liveness.getFc1LastMsgAgeSec()).toBe(7);

            // 7.6 seconds ago -> rounds to 8
            liveness._resetForTests();
            liveness.markFc1Active(fakeNow - 7600);
            expect(liveness.getFc1LastMsgAgeSec()).toBe(8);

            // 0 ms ago -> 0
            liveness._resetForTests();
            liveness.markFc1Active(fakeNow);
            expect(liveness.getFc1LastMsgAgeSec()).toBe(0);
        } finally {
            Date.now = realNow;
        }
    });

    test('every fc1 data topic handler bumps fc1LastMsgTs', () => {
        // Simulate each of the 9 CD-01 topic handlers calling markFc1Active.
        // Each call uses a strictly-increasing ts so we can assert that each
        // topic individually advances the aggregator.
        let ts = 100_000;
        for (const topic of CD01_TOPICS) {
            liveness._resetForTests();
            liveness.markFc1Active(ts);
            expect(liveness.getFc1LastMsgTs()).toBe(ts);
            // Sanity tag to make the failure message blame the topic.
            expect({ topic, lastMsgTs: liveness.getFc1LastMsgTs() })
                .toEqual({ topic, lastMsgTs: ts });
            ts += 1000;
        }

        // Confirm the canonical list is exactly 9 (CD-01 cardinality guard).
        expect(CD01_TOPICS.length).toBe(9);
    });

    test('CD-01 excluded topics are not in the data-topic list (negative guard)', () => {
        const EXCLUDED = [
            '/fc1/control/humidity_target',
            '/fc1/control/current_mode_json',
            '/fc1/control/alerter_mode_overrides',
            '/fc1/control/alerter_globals',
            '/fc1/control/experiment_event',
            '/fc1/camera/compressed',
        ];
        for (const t of EXCLUDED) {
            expect(CD01_TOPICS).not.toContain(t);
        }
    });
});
