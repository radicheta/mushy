'use strict';

const ALERT_TITLES = {
  pi:         'Pi offline',
  sensor:     'Sensor ERROR',
  rh:         'RH out of band',
  humidifier: 'Humidifier stuck',
  sht30:      'Primary Humidity Sensor offline',
  scd41:      'CO2 Sensor offline',
};

// Round a number to 1 decimal and strip trailing ".0".
// e.g. 94.39994 -> "94.4", 90 -> "90", 1.5000000000000013 -> "1.5".
// Null/undefined/NaN render as "?" so farmer-facing strings never expose raw
// "null"/"undefined" when upstream state hasn't populated yet.
function fmtNum(n) {
  if (n == null || Number.isNaN(Number(n))) return '?';
  return String(+Number(n).toFixed(1));
}

/**
 * Format elapsed milliseconds as "Xm YYs" (or "Xh YYm" for >= 60 min).
 */
function fmtDuration(ms) {
  const totalSec = Math.round(ms / 1000);
  const totalMin = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  if (totalMin < 60) {
    return `${totalMin}m ${String(sec).padStart(2, '0')}s`;
  }
  const hours = Math.floor(totalMin / 60);
  const min = totalMin % 60;
  return `${hours}h ${String(min).padStart(2, '0')}m`;
}

/**
 * Format a relative time from a past timestamp to now.
 * e.g. "12m ago" or "5s ago"
 */
function fmtRelative(pastMs, nowMs) {
  const diffMs = nowMs - pastMs;
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  return `${diffMin}m ago`;
}

/**
 * formatProblem({alertType, severity, fields, config, nowMs}) -> string
 *
 * Produces a PROBLEM message. Every template includes `config.dashboardUrl` exactly once.
 *
 * fields per alertType:
 *   rh:         { value: number, firstOobMs: number }
 *   pi:         { lastSeenMs: number }
 *   sensor:     { message: string }
 *   humidifier: { onSinceMs: number, rhAtOn: number, currentRh: number }
 */
function formatProblem({ alertType, severity, fields, config, nowMs }) {
  const title = ALERT_TITLES[alertType] || alertType;
  let body = `[PROBLEM · ${severity}] FC-1 · ${title}\n`;

  if (alertType === 'rh') {
    const { value, firstOobMs } = fields;
    body += `Now: ${fmtNum(value)}% · target ${fmtNum(config.rhTarget)}±${fmtNum(config.rhBand)}%\n`;
    if (firstOobMs != null) {
      body += `First OOB: ${fmtRelative(firstOobMs, nowMs)}\n`;
    }
  } else if (alertType === 'pi') {
    const { lastSeenMs, lastKnown } = fields;
    if (lastSeenMs != null) {
      body += `Last seen: ${fmtRelative(lastSeenMs, nowMs)}\n`;
    }
    if (lastKnown) {
      // Phase 29 / 999.39 — situational context for offline alarms.
      // Schema: { rh: number, temp: number, humidifier: 'ON'|'OFF', tsMs: number|null }
      body += `Last sample: RH ${fmtNum(lastKnown.rh)}% · T ${fmtNum(lastKnown.temp)}°C · humidifier ${lastKnown.humidifier}\n`;
      if (lastKnown.tsMs != null) {
        body += `(captured ${fmtRelative(lastKnown.tsMs, nowMs)})\n`;
      }
    }
  } else if (alertType === 'sht30' || alertType === 'scd41') {
    // Hidden 2026-04-25 pending backlog 999.18: lastSeenMs is bootstrapped from
    // alerter boot, not the actual sensor outage onset, so any number we'd print
    // is misleading. Suppress until fc_controller publishes a true wall-clock
    // last-fresh timestamp we can read from.
  } else if (alertType === 'sensor') {
    if (fields && fields.message) {
      body += `${fields.message}\n`;
    }
  } else if (alertType === 'humidifier') {
    const { onSinceMs, rhAtOn, currentRh } = fields || {};
    if (onSinceMs != null) {
      body += `On for: ${fmtDuration(nowMs - onSinceMs)}\n`;
    }
    if (rhAtOn != null && currentRh != null) {
      body += `RH at ON: ${fmtNum(rhAtOn)}% · Now: ${fmtNum(currentRh)}%\n`;
    }
  }

  body += `Open: ${config.dashboardUrl}`;
  return body;
}

/**
 * formatRecovery({alertType, fields, durationMs, config}) -> string
 *
 * fields per alertType:
 *   rh:         { value: number }
 *   pi:         {}
 *   sensor:     {}
 *   humidifier: {}
 */
function formatRecovery({ alertType, fields, durationMs, config }) {
  const title = ALERT_TITLES[alertType] || alertType;
  let body = `[RECOVERY] FC-1 · ${title} back\n`;

  if (alertType === 'rh' && fields && fields.value != null) {
    body += `Now: ${fmtNum(fields.value)}%\n`;
  }

  if (durationMs != null) {
    body += `Was OOB for ${fmtDuration(durationMs)}\n`;
  }

  body += `Open: ${config.dashboardUrl}`;
  return body;
}

/**
 * formatHeartbeat({summary, config, nowMs}) -> string
 *
 * summary: { rh, temp, co2, humidifier, humidifierCycles, piLastSeenSec }
 */
function formatHeartbeat({ summary, config, nowMs: _nowMs }) {
  const { rh, temp, co2, humidifier, humidifierCycles, piLastSeenSec } = summary;
  let body = '[HEARTBEAT] FC-1 watchdog alive\n';
  body += `RH: ${fmtNum(rh)}%  ·  Temp: ${fmtNum(temp)}°C  ·  CO2: ${co2 == null ? '?' : co2} ppm\n`;
  body += `Humidifier: ${humidifier} (cycled ${humidifierCycles}× in last 24h)\n`;
  if (piLastSeenSec != null) {
    body += `Pi last seen: ${piLastSeenSec} seconds ago\n`;
  }
  body += `Open: ${config.dashboardUrl}`;
  return body;
}

module.exports = { formatProblem, formatRecovery, formatHeartbeat, fmtNum, fmtDuration, fmtRelative };
