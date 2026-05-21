// Phase 46 Plan 01 (CD-01 / CD-04): fc1 liveness aggregator.
//
// Tracks fc1LastMsgTs = max(ts) across the 9 subscribed fc1 data/state
// topics (humidity, temperature, humidity_2, temperature_2, co2,
// actuators/humidifier, actuators/humidifier_duty, sensor_health,
// control/pid_output). The 5 control/* JSON topics + the camera topic
// are intentionally EXCLUDED -- per CONTEXT.md D-01 they don't count
// toward chamber liveness.
//
// Bridge index.js calls markFc1Active(Date.now()) inside each of those
// 9 subscriber callbacks; GET /health reads fc1LastMsgTs +
// fc1LastMsgAgeSec to surface a real chamber-dark signal that the
// alerter will consume in plan 46-02.
//
// Wall-clock arrival time at the bridge is used (Date.now()), NOT
// msg.header.stamp, mirroring how humidifierLastMsgTs is tracked
// today. Rationale: header.stamp is set by the publisher on the Pi;
// during a chamber-dark outage we want "the bridge stopped hearing
// from fc1", not "the Pi clock paused".

let fc1LastMsgTs = null;

function markFc1Active(tsMs) {
    if (typeof tsMs !== 'number' || !Number.isFinite(tsMs)) {
        return;
    }
    fc1LastMsgTs = Math.max(fc1LastMsgTs ?? 0, tsMs);
}

function getFc1LastMsgTs() {
    return fc1LastMsgTs;
}

function getFc1LastMsgAgeSec() {
    if (fc1LastMsgTs === null) return null;
    return Math.round((Date.now() - fc1LastMsgTs) / 1000);
}

// Test-only: reset module-level state between tests. Production code
// must never call this.
function _resetForTests() {
    fc1LastMsgTs = null;
}

module.exports = {
    markFc1Active,
    getFc1LastMsgTs,
    getFc1LastMsgAgeSec,
    _resetForTests,
};
