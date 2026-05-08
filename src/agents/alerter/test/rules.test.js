'use strict';

const { isRhOob, isSensorError, isPiOffline, isHumidifierStuck } = require('../src/rules');
const {
  makeFreshEffective,
  makeStaleEffective,
  makeColdEffective,
} = require('./fixtures/effective-config');

const NOW = 1000000;

describe('isRhOob', () => {
  const cfg = { rhTarget: 90, rhBand: 3 };

  test('exactly on target: false', () => {
    expect(isRhOob(90, cfg)).toBe(false);
  });

  test('83.2 is OOB (|90-83.2|=6.8 > 3): true', () => {
    expect(isRhOob(83.2, cfg)).toBe(true);
  });

  test('92.9 is in band (edge: 2.9 < 3): false', () => {
    expect(isRhOob(92.9, cfg)).toBe(false);
  });

  test('93.1 is OOB (3.1 > 3): true', () => {
    expect(isRhOob(93.1, cfg)).toBe(true);
  });
});

describe('isSensorError', () => {
  test('level 2: true', () => expect(isSensorError({ level: 2 })).toBe(true));
  test('level 1: false', () => expect(isSensorError({ level: 1 })).toBe(false));
  test('level 0: false', () => expect(isSensorError({ level: 0 })).toBe(false));
});

describe('isPiOffline', () => {
  const cfg = { piOfflineMin: 5 };
  const offlinePast = NOW - 6 * 60000; // 6 min ago

  test('ws disconnected for >5min: true', () => {
    expect(isPiOffline({
      wsConnected: false,
      nowMs: NOW,
      wsLastConnectedMs: offlinePast,
      config: cfg,
    })).toBe(true);
  });

  test('ros disconnected for >5min: true', () => {
    expect(isPiOffline({
      wsConnected: true,
      rosConnected: false,
      nowMs: NOW,
      rosDisconnectedSinceMs: offlinePast,
      config: cfg,
    })).toBe(true);
  });

  test('freshly connected: false', () => {
    expect(isPiOffline({
      wsConnected: true,
      rosConnected: true,
      nowMs: NOW,
      wsLastConnectedMs: NOW - 1000,
      rosDisconnectedSinceMs: null,
      config: cfg,
    })).toBe(false);
  });
});

describe('isHumidifierStuck', () => {
  const cfg = { humidifierStuckMin: 30 };

  test('on for 31min with RH rise only 1%: true', () => {
    expect(isHumidifierStuck({
      humidifierOnSinceMs: NOW - 31 * 60000,
      rhAtOn: 82,
      currentRh: 83,
      nowMs: NOW,
      config: cfg,
    })).toBe(true);
  });

  test('on for 31min but RH rose 6%: false (6% > 3% threshold)', () => {
    expect(isHumidifierStuck({
      humidifierOnSinceMs: NOW - 31 * 60000,
      rhAtOn: 82,
      currentRh: 88,
      nowMs: NOW,
      config: cfg,
    })).toBe(false);
  });

  test('on for only 10min: false (not past threshold)', () => {
    expect(isHumidifierStuck({
      humidifierOnSinceMs: NOW - 10 * 60000,
      rhAtOn: 82,
      currentRh: 83,
      nowMs: NOW,
      config: cfg,
    })).toBe(false);
  });
});

describe('Phase 29 — freshness gating + offline blindness', () => {
  describe('isRhOob freshness gate (D-03)', () => {
    test('Test 1: stale freshness suspends rule even with humidity wildly OOB', () => {
      const eff = makeStaleEffective({ rhTarget: 90, rhBand: 3 });
      expect(isRhOob(70, eff)).toBe(false);
    });

    test('Test 2: cold freshness still evaluates math (env fallback)', () => {
      const eff = makeColdEffective({ rhTarget: 90, rhBand: 3 });
      expect(isRhOob(80, eff)).toBe(true);
    });

    test('Test 3: fresh freshness still evaluates math', () => {
      const eff = makeFreshEffective({ rhTarget: 90, rhBand: 3 });
      expect(isRhOob(83.2, eff)).toBe(true);
    });

    test('Test 4: backwards-compat — legacy plain-object config without freshness still works', () => {
      expect(isRhOob(83.2, { rhTarget: 90, rhBand: 3 })).toBe(true);
    });
  });

  describe('isHumidifierStuck offline-blindness gate (D-04 / 999.39)', () => {
    const cfg = { humidifierStuckMin: 30, sensorOfflineMin: 5 };

    test('Test 5: returns false when wsConnected=false', () => {
      expect(isHumidifierStuck({
        humidifierOnSinceMs: 1000,
        rhAtOn: 80,
        currentRh: 80,
        nowMs: 2_000_000,
        config: cfg,
        wsConnected: false,
        humidifierLastMsgTs: 1_999_000,
      })).toBe(false);
    });

    test('Test 6: returns false when humidifierLastMsgTs older than sensorOfflineMin', () => {
      const nowMs = NOW;
      expect(isHumidifierStuck({
        humidifierOnSinceMs: nowMs - 31 * 60000,
        rhAtOn: 82,
        currentRh: 83,
        nowMs,
        config: cfg,
        wsConnected: true,
        humidifierLastMsgTs: nowMs - 10 * 60000,
      })).toBe(false);
    });

    test('Test 7: returns false when humidifierLastMsgTs is null even if wsConnected=true', () => {
      expect(isHumidifierStuck({
        humidifierOnSinceMs: NOW - 31 * 60000,
        rhAtOn: 82,
        currentRh: 83,
        nowMs: NOW,
        config: cfg,
        wsConnected: true,
        humidifierLastMsgTs: null,
      })).toBe(false);
    });

    test('Test 8: returns true when freshness inputs OK and existing math triggers', () => {
      expect(isHumidifierStuck({
        humidifierOnSinceMs: NOW - 31 * 60000,
        rhAtOn: 82,
        currentRh: 83,
        nowMs: NOW,
        config: cfg,
        wsConnected: true,
        humidifierLastMsgTs: NOW - 30 * 1000,
      })).toBe(true);
    });

    test('Test 9: backwards-compat — pre-Phase-29 callers without liveness inputs still work', () => {
      expect(isHumidifierStuck({
        humidifierOnSinceMs: NOW - 31 * 60000,
        rhAtOn: 82,
        currentRh: 83,
        nowMs: NOW,
        config: cfg,
      })).toBe(true);
    });
  });
});
