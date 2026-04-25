'use strict';

const VALID_ALERT_TYPES = ['rh', 'sensor', 'pi', 'humidifier', 'sht30', 'scd41', 'all'];

const VALID_DURATIONS = {
  '30m': 30 * 60000,
  '1h':  3600000,
  '2h':  7200000,
  '4h':  14400000,
  '8h':  28800000,
  '24h': 86400000,
};

// Strict whitelist regex — anchored start/end, no extra content allowed.
const STRICT = /^snooze\s+(rh|sensor|pi|humidifier|sht30|scd41|all)\s+(30m|1h|2h|4h|8h|24h)\s*$/i;

function fuzzyReply() {
  return {
    ok: false,
    reply:
      'Sorry, didn\'t get that. Try: snooze rh 4h\n' +
      'Valid alert types: rh, sensor, pi, humidifier, sht30, scd41, all\n' +
      'Valid durations: 30m, 1h, 2h, 4h, 8h, 24h',
  };
}

/**
 * parseSnoozeCommand(text, nowMs) ->
 *   { ok: true, alertType, durationMs, untilMs }
 *   | { ok: false, reply: string }
 */
function parseSnoozeCommand(text, nowMs) {
  if (typeof text !== 'string') return fuzzyReply();
  const m = text.trim().match(STRICT);
  if (m) {
    const alertType = m[1].toLowerCase();
    const durationMs = VALID_DURATIONS[m[2].toLowerCase()];
    return { ok: true, alertType, durationMs, untilMs: nowMs + durationMs };
  }
  // Anything else — return helpful error with fuzzy reply.
  return fuzzyReply();
}

module.exports = { parseSnoozeCommand, VALID_ALERT_TYPES, VALID_DURATIONS };
