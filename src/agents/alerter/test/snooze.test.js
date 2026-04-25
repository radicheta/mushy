'use strict';

const { parseSnoozeCommand, VALID_ALERT_TYPES, VALID_DURATIONS } = require('../src/snooze');

describe('parseSnoozeCommand', () => {
  test('Test A: valid rh 4h command', () => {
    const result = parseSnoozeCommand('snooze rh 4h', 1000);
    expect(result.ok).toBe(true);
    expect(result.alertType).toBe('rh');
    expect(result.durationMs).toBe(4 * 3600 * 1000);
    expect(result.untilMs).toBe(1000 + 4 * 3600 * 1000);
  });

  test('Test B: valid all 8h command', () => {
    const result = parseSnoozeCommand('snooze all 8h', 0);
    expect(result.ok).toBe(true);
    expect(result.alertType).toBe('all');
  });

  test('Test C: invalid duration 99h returns {ok:false} with valid durations in reply', () => {
    const result = parseSnoozeCommand('snooze rh 99h', 0);
    expect(result.ok).toBe(false);
    expect(result.reply).toMatch(/30m|1h|2h|4h|8h|24h/);
  });

  test('Test D: unrecognized command returns {ok:false} with example in reply', () => {
    const result = parseSnoozeCommand('mute rh', 0);
    expect(result.ok).toBe(false);
    expect(result.reply).toContain('snooze rh 4h');
  });

  test('Test E: unknown alert type returns {ok:false} with valid types in reply', () => {
    const result = parseSnoozeCommand('snooze xxx 1h', 0);
    expect(result.ok).toBe(false);
    expect(result.reply).toContain('rh, sensor, pi, humidifier, sht30, scd41, all');
  });

  test('Test F: injection attempt rejected', () => {
    const result = parseSnoozeCommand('snooze rh 4h; rm -rf /', 0);
    expect(result.ok).toBe(false);
  });
});

describe('exports', () => {
  test('VALID_ALERT_TYPES is an array with expected types', () => {
    expect(VALID_ALERT_TYPES).toContain('rh');
    expect(VALID_ALERT_TYPES).toContain('sensor');
    expect(VALID_ALERT_TYPES).toContain('pi');
    expect(VALID_ALERT_TYPES).toContain('humidifier');
    expect(VALID_ALERT_TYPES).toContain('all');
  });

  test('VALID_DURATIONS is an object with expected keys', () => {
    expect(VALID_DURATIONS).toHaveProperty('30m');
    expect(VALID_DURATIONS).toHaveProperty('1h');
    expect(VALID_DURATIONS).toHaveProperty('4h');
    expect(VALID_DURATIONS).toHaveProperty('24h');
  });
});
