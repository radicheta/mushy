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

  // Phase 46 — D-03 third OR-trigger: stale fc1LastMsgTs.
  describe('Phase 46 — fc1LastMsgTs third OR-trigger (D-03)', () => {
    test('stale fc1LastMsgTs fires even though WS+ROS connected', () => {
      // 6 min ago > piOfflineMin=5 min. ws+ros say healthy but fc1 publisher silent.
      expect(isPiOffline({
        wsConnected: true,
        rosConnected: true,
        nowMs: NOW,
        wsLastConnectedMs: NOW - 1000,
        rosDisconnectedSinceMs: null,
        fc1LastMsgTs: NOW - 6 * 60000,
        config: cfg,
      })).toBe(true);
    });

    test('fresh fc1LastMsgTs and WS+ROS connected: false', () => {
      expect(isPiOffline({
        wsConnected: true,
        rosConnected: true,
        nowMs: NOW,
        wsLastConnectedMs: NOW - 1000,
        rosDisconnectedSinceMs: null,
        fc1LastMsgTs: NOW - 30000, // 30s ago — fresh
        config: cfg,
      })).toBe(false);
    });

    test('undefined fc1LastMsgTs (old bridge / pre-46 caller) does not trigger', () => {
      // graceful degradation per CONTEXT.md code_context.Integration Points.
      expect(isPiOffline({
        wsConnected: true,
        rosConnected: true,
        nowMs: NOW,
        wsLastConnectedMs: NOW - 1000,
        rosDisconnectedSinceMs: null,
        // fc1LastMsgTs intentionally omitted (undefined)
        config: cfg,
      })).toBe(false);
    });

    test('null fc1LastMsgTs (bridge present but no fc1 data yet) does not trigger', () => {
      expect(isPiOffline({
        wsConnected: true,
        rosConnected: true,
        nowMs: NOW,
        wsLastConnectedMs: NOW - 1000,
        rosDisconnectedSinceMs: null,
        fc1LastMsgTs: null,
        config: cfg,
      })).toBe(false);
    });

    test('existing wsConnected trigger RETAINED alongside new trigger (D-03)', () => {
      // ws disconnected past threshold, fc1LastMsgTs fresh -- ws path still fires.
      expect(isPiOffline({
        wsConnected: false,
        rosConnected: true,
        nowMs: NOW,
        wsLastConnectedMs: NOW - 6 * 60000,
        rosDisconnectedSinceMs: null,
        fc1LastMsgTs: NOW - 30000,
        config: cfg,
      })).toBe(true);
    });

    test('existing rosConnected trigger RETAINED alongside new trigger (D-03)', () => {
      expect(isPiOffline({
        wsConnected: true,
        rosConnected: false,
        nowMs: NOW,
        wsLastConnectedMs: NOW - 1000,
        rosDisconnectedSinceMs: NOW - 6 * 60000,
        fc1LastMsgTs: NOW - 30000,
        config: cfg,
      })).toBe(true);
    });
  });

  // Phase 46 D-09: fc1LastMsgTs branch uses a hard 3-min threshold, NOT
  // config.piOfflineMin. Surfaced by the 2026-05-21 46-03 live-fire smoke
  // where fc_config.yaml's pi_offline_min=15 global made chamber-dark fire
  // at ~15-23min instead of <5min. The ws+ros branches still honor config.
  describe('Phase 46 — D-09 hard 3-min threshold for fc1LastMsgTs branch', () => {
    const prodCfg = { piOfflineMin: 15 }; // matches fc_config.yaml global

    test('fc1LastMsgTs stale 4min fires even though config piOfflineMin=15', () => {
      expect(isPiOffline({
        wsConnected: true,
        rosConnected: true,
        nowMs: NOW,
        wsLastConnectedMs: NOW - 1000,
        rosDisconnectedSinceMs: null,
        fc1LastMsgTs: NOW - 4 * 60000,
        config: prodCfg,
      })).toBe(true);
    });

    test('fc1LastMsgTs stale 2min does NOT fire (under 3-min hard threshold)', () => {
      expect(isPiOffline({
        wsConnected: true,
        rosConnected: true,
        nowMs: NOW,
        wsLastConnectedMs: NOW - 1000,
        rosDisconnectedSinceMs: null,
        fc1LastMsgTs: NOW - 2 * 60000,
        config: prodCfg,
      })).toBe(false);
    });

    test('ws-disconnect branch still honors config.piOfflineMin (15min) — disconnected 10min does NOT fire', () => {
      // Confirms D-09 only changes the fc1LastMsgTs branch; legacy ws branch unchanged.
      expect(isPiOffline({
        wsConnected: false,
        rosConnected: true,
        nowMs: NOW,
        wsLastConnectedMs: NOW - 10 * 60000,
        rosDisconnectedSinceMs: null,
        fc1LastMsgTs: NOW - 30000,
        config: prodCfg,
      })).toBe(false);
    });
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
