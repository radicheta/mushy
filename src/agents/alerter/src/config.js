'use strict';

function mustEnv(env, key) {
  const v = env[key];
  if (!v) throw new Error(`[config] Required env var ${key} is missing`);
  return v;
}

function parseIntEnv(env, key, def) {
  if (env[key] === undefined) return def;
  const n = parseInt(env[key], 10);
  if (Number.isNaN(n)) throw new Error(`[config] ${key}=${env[key]} is not an integer`);
  return n;
}

function parseFloatEnv(env, key, def) {
  if (env[key] === undefined) return def;
  const n = parseFloat(env[key]);
  if (Number.isNaN(n)) throw new Error(`[config] ${key}=${env[key]} is not a number`);
  return n;
}

// Phase 29 (D-03 / D-05) tier classification:
//   Tier A (mode-driven, BOOTSTRAP-ONLY): rhTarget, rhBand
//   Tier B (per-mode override, BOOTSTRAP-ONLY): oobN, oobWindowMin, cooldownMin,
//          criticalCooldownMin, humidifierStuckMin
//   Tier C (global override, BOOTSTRAP-ONLY): piOfflineMin, sensorOfflineMin,
//          heartbeatHour, maxSendsPerHour
//   Tier D (env-only, ALWAYS LIVE): bridgeWsUrl, signalApiUrl, modeStaleMin,
//          modeBootGraceMs, all CAPTURE_*, all TIMESCALE_*
// Tier A/B/C values returned here are FALLBACKS used only during D-03 state-3
// cold-start grace; runtime decisions consume `resolveEffectiveConfig(state, env, now)`
// from state.js (Phase 29 plan 04).
function load(env = process.env) {
  return Object.freeze({
    bridgeWsUrl:         env.BRIDGE_WS_URL      || 'ws://host.docker.internal:8081',
    bridgeHealthUrl:     env.BRIDGE_HEALTH_URL  || 'http://host.docker.internal:8081/health',
    signalApiUrl:        env.SIGNAL_API_URL     || 'http://signal-cli:8080',
    signalSender:        mustEnv(env, 'SIGNAL_SENDER'),
    signalRecipient:     mustEnv(env, 'SIGNAL_RECIPIENT'),
    signalAdditionalSenders: (env.SIGNAL_ADDITIONAL_SENDERS || '')
                              .split(',').map((s) => s.trim()).filter(Boolean),
    rhTarget:            parseFloatEnv(env, 'ALERT_RH_TARGET', 90),
    rhBand:              parseFloatEnv(env, 'ALERT_RH_BAND', 3),
    oobN:                parseIntEnv(env, 'ALERT_OOB_N', 5),
    oobWindowMin:        parseIntEnv(env, 'ALERT_OOB_WINDOW_MIN', 3),
    cooldownMin:         parseIntEnv(env, 'ALERT_COOLDOWN_MIN', 30),
    criticalCooldownMin: parseIntEnv(env, 'ALERT_CRITICAL_COOLDOWN_MIN', 60),
    piOfflineMin:        parseIntEnv(env, 'ALERT_PI_OFFLINE_MIN', 5),
    sensorOfflineMin:    parseIntEnv(env, 'ALERT_SENSOR_OFFLINE_MIN', 5),
    humidifierStuckMin:  parseIntEnv(env, 'ALERT_HUMIDIFIER_STUCK_MIN', 30),
    heartbeatHour:       parseIntEnv(env, 'ALERT_HEARTBEAT_HOUR', 8),
    // Phase 29 plan 29-04 — D-03 freshness ceiling + cold-start grace (Tier D).
    modeStaleMin:        parseIntEnv(env, 'ALERT_MODE_STALE_MIN', 5),
    modeBootGraceMs:     parseIntEnv(env, 'ALERT_MODE_BOOT_GRACE_SEC', 60) * 1000,
    receivePollSec:      parseIntEnv(env, 'ALERT_RECEIVE_POLL_SEC', 30),
    maxSendsPerHour:     parseIntEnv(env, 'ALERT_MAX_SENDS_PER_HOUR', 20),
    timezone:            env.TZ           || 'America/Toronto',
    dashboardUrl:        env.DASHBOARD_URL || 'http://100.96.10.66:8080/',
    logLevel:            env.LOG_LEVEL    || 'info',
    // Phase 25 capture pipeline
    timescaleHost:        env.TIMESCALE_HOST     || 'host.docker.internal',
    timescaleDb:          env.TIMESCALE_DB       || 'postgres',
    timescaleUser:        env.TIMESCALE_USER     || 'postgres',
    timescalePassword:    mustEnv(env, 'TIMESCALE_PASSWORD'),
    whisperUrl:           env.WHISPER_URL        || 'http://host.docker.internal:8090',
    anthropicApiKey:      mustEnv(env, 'ANTHROPIC_API_KEY'),
    captureBaseDir:       env.CAPTURE_BASE_PATH  || '/data/signal-capture',
    bridgeHttpUrl:        env.BRIDGE_HTTP_URL    || 'http://host.docker.internal:8081',
    captureRetentionDays: parseIntEnv(env, 'CAPTURE_RETENTION_DAYS', 30),
    captureRetentionCron: env.CAPTURE_RETENTION_CRON || '15 3 * * *',
  });
}

/**
 * maskNumber('+15551234567') -> '+1XXXXXX4567'
 * Preserves first 2 characters and last 4 characters; masks the rest.
 */
function maskNumber(n) {
  if (typeof n !== 'string' || n.length < 6) return 'XXXX';
  return n.slice(0, 2) + 'X'.repeat(n.length - 6) + n.slice(-4);
}

module.exports = { load, maskNumber };
