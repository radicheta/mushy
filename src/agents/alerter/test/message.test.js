'use strict';

const { formatProblem, formatRecovery, formatHeartbeat } = require('../src/message');

const config = {
  dashboardUrl: 'http://elder-plops-ts:8081/farmer',
  rhTarget: 90,
  rhBand: 3,
};

describe('formatProblem', () => {
  test('Test A: Pi offline CRITICAL message contains required elements', () => {
    const body = formatProblem({
      alertType: 'pi',
      severity: 'CRITICAL',
      fields: { lastSeenMs: 1 },
      config,
      nowMs: 10,
    });
    expect(body).toContain('[PROBLEM · CRITICAL]');
    expect(body).toContain('FC-1');
    expect(body).toContain('Pi offline');
    expect(body).toContain(config.dashboardUrl);
  });

  test('Test B: RH WARN message contains value, target, and dashboard URL', () => {
    const body = formatProblem({
      alertType: 'rh',
      severity: 'WARN',
      fields: { value: 83.2, firstOobMs: 100 },
      config,
      nowMs: 460000,
    });
    expect(body).toContain('[PROBLEM · WARN]');
    expect(body).toContain('83.2%');
    expect(body).toContain('target 90±3%');
    expect(body).toContain(config.dashboardUrl);
  });
});

describe('formatRecovery', () => {
  test('Test C: RH recovery message contains value, duration, dashboard URL', () => {
    const body = formatRecovery({
      alertType: 'rh',
      fields: { value: 89.6 },
      durationMs: 12 * 60000 + 4000,
      config,
    });
    expect(body).toContain('[RECOVERY]');
    expect(body).toContain('89.6');
    expect(body).toContain('12m 04s');
    expect(body).toContain(config.dashboardUrl);
  });
});

describe('formatHeartbeat', () => {
  test('Test D: heartbeat contains all sensor values and dashboard URL', () => {
    const body = formatHeartbeat({
      summary: {
        rh: 90.1,
        temp: 23.1,
        co2: 812,
        humidifier: 'OFF',
        humidifierCycles: 14,
        piLastSeenSec: 8,
      },
      config,
      nowMs: Date.now(),
    });
    expect(body).toContain('[HEARTBEAT]');
    expect(body).toContain('90.1');
    expect(body).toContain('23.1');
    expect(body).toContain('812');
    expect(body).toContain('cycled 14×');
    expect(body).toContain(config.dashboardUrl);
  });
});

describe('ALRT-08: every message contains dashboard URL exactly once', () => {
  test('Test E: PROBLEM contains dashboardUrl exactly once', () => {
    const body = formatProblem({
      alertType: 'rh',
      severity: 'WARN',
      fields: { value: 83.2, firstOobMs: 0 },
      config,
      nowMs: 60000,
    });
    const count = (body.match(new RegExp(config.dashboardUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length;
    expect(count).toBe(1);
  });

  test('Test E: RECOVERY contains dashboardUrl exactly once', () => {
    const body = formatRecovery({
      alertType: 'rh',
      fields: { value: 89.6 },
      durationMs: 60000,
      config,
    });
    const count = (body.match(new RegExp(config.dashboardUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length;
    expect(count).toBe(1);
  });

  test('Test E: HEARTBEAT contains dashboardUrl exactly once', () => {
    const body = formatHeartbeat({
      summary: { rh: 90, temp: 22, co2: 800, humidifier: 'OFF', humidifierCycles: 0, piLastSeenSec: 5 },
      config,
      nowMs: Date.now(),
    });
    const count = (body.match(new RegExp(config.dashboardUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length;
    expect(count).toBe(1);
  });
});
