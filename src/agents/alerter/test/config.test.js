'use strict';

const { load, maskNumber } = require('../src/config');

const BASE_ENV = { SIGNAL_SENDER: '+1', SIGNAL_RECIPIENT: '+2' };

describe('config.load', () => {
  test('Test A: returns object with all fields populated from defaults', () => {
    const cfg = load({ ...BASE_ENV });
    expect(cfg.bridgeWsUrl).toBe('ws://host.docker.internal:8081');
    expect(cfg.bridgeHealthUrl).toBe('http://host.docker.internal:8081/health');
    expect(cfg.signalApiUrl).toBe('http://signal-cli:8080');
    expect(cfg.signalSender).toBe('+1');
    expect(cfg.signalRecipient).toBe('+2');
    expect(cfg.rhTarget).toBe(90);
    expect(cfg.rhBand).toBe(3);
    expect(cfg.oobN).toBe(5);
    expect(cfg.oobWindowMin).toBe(3);
    expect(cfg.cooldownMin).toBe(30);
    expect(cfg.criticalCooldownMin).toBe(60);
    expect(cfg.piOfflineMin).toBe(5);
    expect(cfg.humidifierStuckMin).toBe(30);
    expect(cfg.heartbeatHour).toBe(8);
    expect(cfg.receivePollSec).toBe(30);
    expect(cfg.maxSendsPerHour).toBe(20);
    expect(cfg.timezone).toBe('America/Toronto');
    expect(cfg.dashboardUrl).toBe('http://elder-plops-ts:8081/farmer');
    expect(cfg.logLevel).toBe('info');
  });

  test('Test B: load({}) throws mentioning SIGNAL_SENDER', () => {
    expect(() => load({})).toThrow('SIGNAL_SENDER');
  });

  test('Test C: ALERT_RH_TARGET parsed as float', () => {
    const cfg = load({ ...BASE_ENV, ALERT_RH_TARGET: '92.5' });
    expect(cfg.rhTarget).toBe(92.5);
  });

  test('Test D: non-numeric ALERT_OOB_N throws', () => {
    expect(() => load({ ...BASE_ENV, ALERT_OOB_N: 'not-a-number' })).toThrow();
  });
});

describe('maskNumber', () => {
  test('Test E: masks middle digits, preserves first 2 and last 4, correct length', () => {
    const result = maskNumber('+15551234567');
    expect(result).not.toContain('1234');
    expect(result).toContain('4567');
    expect(result.length).toBe(12);
  });
});
