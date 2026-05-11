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

describe('Phase 29 — pi alert last-known summary (999.39)', () => {
  test('Test 1: pi alert with lastKnown emits a "Last sample:" line', () => {
    const body = formatProblem({
      alertType: 'pi',
      severity: 'CRITICAL',
      fields: {
        lastSeenMs: 1700000000000,
        lastKnown: { rh: 87.2, temp: 21.4, humidifier: 'ON', tsMs: 1699999000000 },
      },
      config,
      nowMs: 1700000500000,
    });
    expect(body).toContain('Last seen:');
    expect(body).toContain('Last sample: RH 87.2% · T 21.4°C · humidifier ON');
  });

  test('Test 2: pi alert without lastKnown omits "Last sample:" line', () => {
    const body = formatProblem({
      alertType: 'pi',
      severity: 'CRITICAL',
      fields: { lastSeenMs: 1700000000000 },
      config,
      nowMs: 1700000500000,
    });
    expect(body).toContain('Last seen:');
    expect(body).not.toContain('Last sample:');
  });

  test('Test 3: lastKnown.humidifier OFF appears in the body', () => {
    const body = formatProblem({
      alertType: 'pi',
      severity: 'CRITICAL',
      fields: {
        lastSeenMs: 1700000000000,
        lastKnown: { rh: 90.0, temp: 22.0, humidifier: 'OFF', tsMs: 1699999000000 },
      },
      config,
      nowMs: 1700000500000,
    });
    expect(body).toContain('humidifier OFF');
  });

  test('Test 4: lastKnown with lastSeenMs=null omits Last seen but includes Last sample', () => {
    const body = formatProblem({
      alertType: 'pi',
      severity: 'CRITICAL',
      fields: {
        lastSeenMs: null,
        lastKnown: { rh: 87.2, temp: 21.4, humidifier: 'ON', tsMs: 1699999000000 },
      },
      config,
      nowMs: 1700000500000,
    });
    expect(body).not.toContain('Last seen:');
    expect(body).toContain('Last sample:');
  });

  test('Test 5: dashboardUrl appears exactly once when lastKnown is provided', () => {
    const body = formatProblem({
      alertType: 'pi',
      severity: 'CRITICAL',
      fields: {
        lastSeenMs: 1700000000000,
        lastKnown: { rh: 87.2, temp: 21.4, humidifier: 'ON', tsMs: 1699999000000 },
      },
      config,
      nowMs: 1700000500000,
    });
    const count = (body.match(new RegExp(config.dashboardUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length;
    expect(count).toBe(1);
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

describe('numeric formatting (round to 1 decimal, strip trailing .0)', () => {
  test('RH PROBLEM rounds floaty value and band to 1 decimal', () => {
    const body = formatProblem({
      alertType: 'rh',
      severity: 'WARN',
      fields: { value: 94.3999389639124, firstOobMs: 1 },
      config: { ...config, rhTarget: 96, rhBand: 1.5000000000000013 },
      nowMs: 60000,
    });
    expect(body).toContain('Now: 94.4%');
    expect(body).toContain('target 96±1.5%');
    expect(body).not.toContain('94.3999');
    expect(body).not.toContain('1.5000000000000013');
  });

  test('RH RECOVERY rounds floaty value to 1 decimal', () => {
    const body = formatRecovery({
      alertType: 'rh',
      fields: { value: 94.4151979858091 },
      durationMs: 4 * 60000 + 54000,
      config,
    });
    expect(body).toContain('Now: 94.4%');
    expect(body).not.toContain('94.4151979858091');
  });

  test('HEARTBEAT renders null/undefined fields as em-dash, not "null"', () => {
    const body = formatHeartbeat({
      summary: { rh: null, temp: undefined, co2: null, humidifier: 'OFF', humidifierCycles: 0, piLastSeenSec: null },
      config,
      nowMs: Date.now(),
    });
    expect(body).not.toContain('null');
    expect(body).not.toContain('undefined');
    expect(body).toContain('RH: —%');
    expect(body).toContain('Temp: —°C');
    expect(body).toContain('CO2: — ppm');
  });

  test('integer values render without trailing .0', () => {
    const body = formatProblem({
      alertType: 'rh',
      severity: 'WARN',
      fields: { value: 83, firstOobMs: 1 },
      config,
      nowMs: 60000,
    });
    expect(body).toContain('Now: 83%');
    expect(body).toContain('target 90±3%');
    expect(body).not.toContain('83.0');
    expect(body).not.toContain('90.0');
  });
});
