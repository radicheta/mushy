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

  test('Test D: snooze-prefixed malformed command returns help-text reply (legacy fuzzy path)', () => {
    // 25-05: only snooze-prefixed malformed input gets fuzzyReply; bare "mute rh" is
    // a non-snooze message that flows to the capture pipeline (no reply from snooze.js).
    const result = parseSnoozeCommand('snooze rh banana', 0);
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

describe('parseSnoozeCommand — simple grammar (R4 — 25-05)', () => {
  test('R4-A: bare "mute" → 24h all-types mute, ackText set', () => {
    const r = parseSnoozeCommand('mute', 1000);
    expect(r.ok).toBe(true);
    expect(r.alertType).toBe('all');
    expect(r.durationMs).toBe(24 * 3600 * 1000);
    expect(r.untilMs).toBe(1000 + 24 * 3600 * 1000);
    expect(r.ackText).toBe('alerts muted for 24h');
  });

  test('R4-B: bare "snooze" → same shape', () => {
    const r = parseSnoozeCommand('snooze', 0);
    expect(r.ok).toBe(true);
    expect(r.alertType).toBe('all');
    expect(r.durationMs).toBe(24 * 3600 * 1000);
    expect(r.ackText).toBe('alerts muted for 24h');
  });

  test('R4-C: bare "quiet" → same shape', () => {
    const r = parseSnoozeCommand('quiet', 0);
    expect(r.ok).toBe(true);
    expect(r.alertType).toBe('all');
    expect(r.ackText).toBe('alerts muted for 24h');
  });

  test('R4-D: case insensitive + whitespace tolerated', () => {
    expect(parseSnoozeCommand('MUTE', 0).ok).toBe(true);
    expect(parseSnoozeCommand('Snooze ', 0).ok).toBe(true);
    expect(parseSnoozeCommand('quiet  ', 0).ok).toBe(true);
    expect(parseSnoozeCommand('  Mute  ', 0).ok).toBe(true);
  });

  test('R4-E: legacy strict grammar still works', () => {
    const r = parseSnoozeCommand('snooze rh 4h', 1000);
    expect(r.ok).toBe(true);
    expect(r.alertType).toBe('rh');
    expect(r.durationMs).toBe(4 * 3600 * 1000);
  });

  test('R4-F: gibberish text → ok=false, no reply (capture pipeline owns it)', () => {
    const r = parseSnoozeCommand('logged 5 jars in tent A', 0);
    expect(r.ok).toBe(false);
    expect(r.reply == null || r.reply === '').toBe(true);
  });

  test('R4-G: "snooze pi banana" (snooze-prefix-but-malformed) → fuzzyReply with help text', () => {
    const r = parseSnoozeCommand('snooze pi banana', 0);
    expect(r.ok).toBe(false);
    expect(typeof r.reply).toBe('string');
    expect(r.reply.length).toBeGreaterThan(0);
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
