'use strict';

const fs = require('fs');
const path = require('path');
const YAML = require('yaml');

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

// Phase 37 D-11: parse "+phone:slug,+phone:slug,..." into Map<E164,slug>.
// Splits on FIRST colon only (phones contain no ':'; defensive for future slugs).
// Silently drops malformed entries — operator notices via missing farmer_map size
// in startup log (added in Plan 04 wire-up).
function parseFarmerMap(raw) {
  const m = new Map();
  for (const entry of String(raw).split(',').map((s) => s.trim()).filter(Boolean)) {
    const idx = entry.indexOf(':');
    if (idx <= 0) continue;
    const phone = entry.slice(0, idx).trim();
    const slug = entry.slice(idx + 1).trim();
    if (phone && slug) m.set(phone, slug);
  }
  return m;
}

// Phase 44 D-11: layered tenant-config loader. Reads tenants/<tenantId>/<filename>
// relative to repo root. Returns {} on missing dir, missing file, malformed YAML
// (graceful degradation per threat T-44-06-04). Path-traversal sanity check
// (T-44-06-02): resolved path MUST stay under the tenants/ base; otherwise {}.
const TENANTS_BASE = path.resolve(__dirname, '..', '..', '..', '..', 'tenants');

function loadTenantFile(tenantId, filename) {
  const p = path.resolve(TENANTS_BASE, tenantId, filename);
  // Boundary-safe containment check: not glob-prefix (would allow siblings like
  // tenants-evil/...). Either equals base (impossible — file required) or starts
  // with base + path separator.
  if (p !== TENANTS_BASE && !p.startsWith(TENANTS_BASE + path.sep)) return {};
  if (!fs.existsSync(p)) return {};
  try {
    const parsed = YAML.parse(fs.readFileSync(p, 'utf8'));
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn(`[config] ${p} parse failed: ${e.message}`);
    return {};
  }
}

// Phase 44 D-11: layered get — tenant file → env → default.
function pick(tenantConfig, env, key, def) {
  if (tenantConfig[key] !== undefined && tenantConfig[key] !== null) return tenantConfig[key];
  if (env[key] !== undefined) return env[key];
  return def;
}

// Normalise SIGNAL_FARMER_MAP from either source-shape: a tenant-YAML object
// (preferred — D-11) or the legacy "+phone:slug,..." string (env fallback).
function resolveFarmerMap(tenantConfig, env) {
  const fromTenant = tenantConfig.SIGNAL_FARMER_MAP;
  if (fromTenant && typeof fromTenant === 'object' && !Array.isArray(fromTenant)) {
    const m = new Map();
    for (const [phone, slug] of Object.entries(fromTenant)) {
      if (phone && slug) m.set(String(phone), String(slug));
    }
    return m;
  }
  return parseFarmerMap(env.SIGNAL_FARMER_MAP || '');
}

// Normalise FARMOS_INTEGRATION across shapes: YAML boolean true/false, legacy
// env string '1'/'0', or absent (default false).
function resolveFarmosIntegration(tenantConfig, env) {
  if (tenantConfig.FARMOS_INTEGRATION !== undefined && tenantConfig.FARMOS_INTEGRATION !== null) {
    return tenantConfig.FARMOS_INTEGRATION === true || tenantConfig.FARMOS_INTEGRATION === 'true' || tenantConfig.FARMOS_INTEGRATION === '1';
  }
  return (env.FARMOS_INTEGRATION || '0') === '1';
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
//
// Phase 44 D-11: added layered tenant-file loader in front of env. SECRETS
// (anthropicApiKey, farmosPassword, signalSender) MUST resolve via mustEnv()
// only — never from tenant YAML (W9 policy). NON-SECRETS resolve via
// pick(tenantConfig, env, key, default).
function load(env = process.env) {
  const tenantId = env.TENANT_ID || 'mossrock';
  const tenantConfig = {
    ...loadTenantFile(tenantId, 'config.yaml'),
    ...loadTenantFile(tenantId, 'strains.yaml'),
  };

  return Object.freeze({
    // Phase 44 D-11: tenant identity (consumed by signal.js Plan-02 for
    // signal_outbound.tenant_id writes).
    tenantId,
    // Phase 44 D-11: strain vocab (Foray α — extractor regex + Haiku gate
    // classifier read from here). Default [] keeps legacy synthetic-env tests
    // sane when TENANT_ID=__none__.
    strains: pick(tenantConfig, env, 'STRAIN_CODES', []),
    // Phase 44 D-06: convo-silence behavior. silent | negative_only | off.
    eventGateConvoMode: pick(tenantConfig, env, 'EVENT_GATE_CONVO_MODE', 'silent'),

    bridgeWsUrl:         env.BRIDGE_WS_URL      || 'ws://host.docker.internal:8081',
    bridgeHealthUrl:     env.BRIDGE_HEALTH_URL  || 'http://host.docker.internal:8081/health',
    signalApiUrl:        env.SIGNAL_API_URL     || 'http://signal-cli:8080',
    // W9: secret — env-only via mustEnv. Never sourced from tenant YAML.
    signalSender:        mustEnv(env, 'SIGNAL_SENDER'),
    signalRecipient:     pick(tenantConfig, env, 'SIGNAL_RECIPIENT', undefined) || mustEnv(env, 'SIGNAL_RECIPIENT'),
    signalAdditionalSenders: (env.SIGNAL_ADDITIONAL_SENDERS || '')
                              .split(',').map((s) => s.trim()).filter(Boolean),
    // Phase 37 D-16 — bare base64; signal.js prepends 'group.' at send time.
    // Tenant YAML may set "" (empty string) — treat as null for back-compat.
    signalGroupId:       (() => {
      const v = pick(tenantConfig, env, 'SIGNAL_GROUP_ID', null);
      return v === '' || v === undefined ? null : v;
    })(),
    // Phase 37 D-11 — boot-time static map; reload requires alerter restart.
    // Phase 44 D-11 — prefer tenant YAML object shape; fall back to env string.
    signalFarmerMap:     resolveFarmerMap(tenantConfig, env),
    rhTarget:            parseFloatEnv(env, 'ALERT_RH_TARGET', 90),
    rhBand:              parseFloatEnv(env, 'ALERT_RH_BAND', 3),
    oobN:                parseIntEnv(env, 'ALERT_OOB_N', 5),
    oobWindowMin:        parseIntEnv(env, 'ALERT_OOB_WINDOW_MIN', 3),
    cooldownMin:         parseIntEnv(env, 'ALERT_COOLDOWN_MIN', 30),
    criticalCooldownMin: parseIntEnv(env, 'ALERT_CRITICAL_COOLDOWN_MIN', 60),
    piOfflineMin:        parseIntEnv(env, 'ALERT_PI_OFFLINE_MIN', 5),
    sensorOfflineMin:    parseIntEnv(env, 'ALERT_SENSOR_OFFLINE_MIN', 5),
    // 999.42: per-sensor enable flags. SHT30 has been physically disconnected
    // since 2026-04-11 (SCD41 is the sole humidity source); the sht30 watchdog
    // would otherwise fire hourly false alarms. Operator sets ALERT_SHT30_ENABLED=false
    // in elder-plops .env to mute it without the blanket sensorOfflineMin=1440
    // band-aid that also masks real SCD41 outages. Default true preserves test
    // invariants and matches the legacy on-by-default behavior.
    sht30Enabled:        (env.ALERT_SHT30_ENABLED || 'true').toLowerCase() !== 'false',
    scd41Enabled:        (env.ALERT_SCD41_ENABLED || 'true').toLowerCase() !== 'false',
    // 2026-05-12: Pi-flag flap floor. Suppresses single-tick `xxx_fresh=false`
    // transients (I2C glitches, controller cleanup races) from firing instant
    // alarms. Watchdog only fires when the flag has stayed false for
    // sensorFlapMinSec seconds. Slow-silence path (sensorOfflineMin) still
    // catches hard failures via its own timeout.
    sensorFlapMinSec:    parseIntEnv(env, 'ALERT_SENSOR_FLAP_MIN_SEC', 60),
    humidifierStuckMin:  parseIntEnv(env, 'ALERT_HUMIDIFIER_STUCK_MIN', 30),
    heartbeatHour:       parseIntEnv(env, 'ALERT_HEARTBEAT_HOUR', 8),
    // Phase 29 plan 29-04 — D-03 freshness ceiling + cold-start grace (Tier D).
    modeStaleMin:        parseIntEnv(env, 'ALERT_MODE_STALE_MIN', 5),
    modeBootGraceMs:     parseIntEnv(env, 'ALERT_MODE_BOOT_GRACE_SEC', 60) * 1000,
    receivePollSec:      parseIntEnv(env, 'ALERT_RECEIVE_POLL_SEC', 30),
    maxSendsPerHour:     parseIntEnv(env, 'ALERT_MAX_SENDS_PER_HOUR', 20),
    timezone:            env.TZ           || 'America/Toronto',
    dashboardUrl:        env.DASHBOARD_URL || 'http://elder-plops-ts:8081/farmer',
    logLevel:            env.LOG_LEVEL    || 'info',
    // Phase 25 capture pipeline
    timescaleHost:        env.TIMESCALE_HOST     || 'host.docker.internal',
    timescaleDb:          env.TIMESCALE_DB       || 'postgres',
    timescaleUser:        env.TIMESCALE_USER     || 'postgres',
    timescalePassword:    mustEnv(env, 'TIMESCALE_PASSWORD'),
    whisperUrl:           env.WHISPER_URL        || 'http://host.docker.internal:8090',
    // W9: secret — env-only via mustEnv. Never sourced from tenant YAML.
    anthropicApiKey:      mustEnv(env, 'ANTHROPIC_API_KEY'),
    captureBaseDir:       env.CAPTURE_BASE_PATH  || '/data/signal-capture',
    bridgeHttpUrl:        env.BRIDGE_HTTP_URL    || 'http://host.docker.internal:8081',
    captureRetentionDays: parseIntEnv(env, 'CAPTURE_RETENTION_DAYS', 30),
    captureRetentionCron: env.CAPTURE_RETENTION_CRON || '15 3 * * *',
    // Phase 38 extraction-pipeline knobs.
    // D-03: per-field confidence ask-back threshold. Range [0,1]; out-of-range
    // values fall back to default 0.7 (logger.warn surfaces the override miss).
    extractionConfidenceThreshold: clampThreshold(
      parseFloatEnv(env, 'EXTRACTION_CONFIDENCE_THRESHOLD', 0.7),
      env.EXTRACTION_CONFIDENCE_THRESHOLD,
    ),
    // D-01a: idle-gap cap (minutes). Any new message after this much silence
    // forces continuity_decision='start_new' regardless of LLM judgment.
    draftIdleGapMin: parseIntEnv(env, 'DRAFT_IDLE_GAP_MIN', 30),
    // D-05: hard cap on ask-back turns before status -> needs_review.
    maxAskbackTurns: parseIntEnv(env, 'MAX_ASKBACK_TURNS', 3),
    // Phase 39 (D-03a, D-04..D-04c): confirm-loop timeouts + edit cap. See
    // docker-compose.override.yml for matching env passthrough.
    draftPendingTimeoutMin: parseIntEnv(env, 'DRAFT_PENDING_TIMEOUT_MIN', 30),
    draftNudgeFraction: clampFraction(
      parseFloatEnv(env, 'DRAFT_NUDGE_FRACTION', 0.8),
      env.DRAFT_NUDGE_FRACTION,
    ),
    draftWatchdogIntervalMs: parseIntEnv(env, 'DRAFT_WATCHDOG_INTERVAL_MS', 60000),
    maxEditTurns: parseIntEnv(env, 'MAX_EDIT_TURNS', 3),
    // Phase 40 (D-01b, D-07, D-07a): farmOS write path + commit watchdog knobs.
    // Compose env passthrough lives in docker-compose.override.yml alerter block.
    farmosUrl:               pick(tenantConfig, env, 'FARMOS_URL', 'http://10.68.155.50:18080'),
    farmosUsername:          pick(tenantConfig, env, 'FARMOS_USERNAME', ''),
    // W9: secret — env-only. Default '' preserves back-compat for tests not
    // setting FARMOS_PASSWORD; production paths gate on farmosIntegration.
    farmosPassword:          env.FARMOS_PASSWORD || '',
    commitWatchdogIntervalMs: parseIntEnv(env, 'COMMIT_WATCHDOG_INTERVAL_MS', 30000),
    commitWatchdogBatchCap:   parseIntEnv(env, 'COMMIT_WATCHDOG_BATCH_CAP', 10),
    commitRetryMax:           parseIntEnv(env, 'COMMIT_RETRY_MAX', 3),
    commitRetryBackoffMs:     parseBackoffCsv(env.COMMIT_RETRY_BACKOFF_MS, [1000, 4000, 16000]),
    commitLockStaleMin:       parseIntEnv(env, 'COMMIT_LOCK_STALE_MIN', 5),
    farmosIntegration:        resolveFarmosIntegration(tenantConfig, env),
  });
}

function parseBackoffCsv(raw, def) {
  if (raw == null || raw === '') return def.slice();
  const parts = String(raw).split(',').map((s) => parseInt(s.trim(), 10));
  if (parts.some((n) => Number.isNaN(n) || n < 0)) {
    // eslint-disable-next-line no-console
    console.warn(`[config] COMMIT_RETRY_BACKOFF_MS=${raw} malformed; using default`);
    return def.slice();
  }
  return parts;
}

function clampFraction(parsed, raw) {
  if (parsed > 0 && parsed < 1) return parsed;
  // eslint-disable-next-line no-console
  console.warn(`[config] DRAFT_NUDGE_FRACTION=${raw} out of (0,1); using default 0.8`);
  return 0.8;
}

function clampThreshold(parsed, raw) {
  if (parsed >= 0 && parsed <= 1) return parsed;
  // Out-of-range: fall back to default; surface to logs so an operator notices.
  // eslint-disable-next-line no-console
  console.warn(`[config] EXTRACTION_CONFIDENCE_THRESHOLD=${raw} out of [0,1]; using default 0.7`);
  return 0.7;
}

/**
 * maskNumber('+15551234567') -> '+1XXXXXX4567'
 * Preserves first 2 characters and last 4 characters; masks the rest.
 */
function maskNumber(n) {
  if (typeof n !== 'string' || n.length < 6) return 'XXXX';
  return n.slice(0, 2) + 'X'.repeat(n.length - 6) + n.slice(-4);
}

module.exports = { load, maskNumber, loadTenantFile, pick };
