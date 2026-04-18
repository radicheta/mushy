'use strict';

const { isRhOob, isSensorError, isPiOffline, isHumidifierStuck } = require('../src/rules');

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
