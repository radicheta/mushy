// Phase 29 plan 29-01 — shared effective-config fixture for rules/state/message tests.
// Mirrors the runtime shape returned by state.js resolveEffectiveConfig() (29-04).

'use strict';

const BASE_ENV = Object.freeze({
    rhTarget: 90,
    rhBand: 3,
    oobN: 5,
    oobWindowMin: 3,
    cooldownMin: 30,
    criticalCooldownMin: 60,
    piOfflineMin: 5,
    sensorOfflineMin: 5,
    humidifierStuckMin: 30,
    heartbeatHour: 8,
    maxSendsPerHour: 20,
    modeStaleMin: 5,
    modeBootGraceMs: 60_000,
});

function makeFreshEffective(overrides = {}) {
    return {
        ...BASE_ENV,
        ...overrides,
        freshness: { state: 'fresh', source: 'mode' },
    };
}

function makeStaleEffective(overrides = {}) {
    return {
        ...BASE_ENV,
        ...overrides,
        freshness: { state: 'stale', source: 'env' },
    };
}

function makeColdEffective(overrides = {}) {
    return {
        ...BASE_ENV,
        ...overrides,
        freshness: { state: 'cold', source: 'env' },
    };
}

module.exports = { BASE_ENV, makeFreshEffective, makeStaleEffective, makeColdEffective };
