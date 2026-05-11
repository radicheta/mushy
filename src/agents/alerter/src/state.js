'use strict';

const { isRhOob, isSensorError, isPiOffline, isHumidifierStuck, isSensorSilent } = require('./rules');
// Phase 29 plan 29-04: keep message module reference (not destructure) so jest
// spies on `formatProblem` intercept calls from state.js (BLOCKER 2 piFields tests).
const messageLib = require('./message');
const { formatProblem, formatRecovery, formatHeartbeat } = messageLib;

const STATES = Object.freeze({ OK: 'OK', PENDING: 'PENDING', FIRING: 'FIRING', SNOOZED: 'SNOOZED' });

const ALERT_TYPES = ['rh', 'sensor', 'pi', 'humidifier', 'sht30', 'scd41'];

// Severity per alert type
const SEVERITY = {
  rh: 'WARN',
  sensor: 'CRITICAL',
  pi: 'CRITICAL',
  humidifier: 'WARN',
  sht30: 'CRITICAL',
  scd41: 'CRITICAL',
};

function initialState(nowMs = Date.now()) {
  const perType = {};
  for (const t of ALERT_TYPES) {
    perType[t] = {
      state: STATES.OK,
      oobCount: 0,
      firstOobAt: null,
      lastFiredAt: null,
      snoozedUntil: null,
      ctx: {},
    };
  }
  return {
    bootedAtMs: nowMs,
    // Phase 29 plan 29-04 — mode + Tier B/C runtime overrides cache slots.
    currentMode: null,
    modeReceivedAtMs: null,
    alerterOverrides: null,
    overridesReceivedAtMs: null,
    alerterGlobals: null,
    globalsReceivedAtMs: null,
    warmingUp: false,
    lastHeartbeatDay: null,
    wsConnected: false,
    wsLastConnectedMs: nowMs,
    rosConnected: false,
    rosDisconnectedSinceMs: null,
    humidifierLastMsgTs: null,
    humidifierOnSinceMs: null,
    rhAtOn: null,
    currentRh: null,
    lastRhMsgTs: null,
    currentTemp: null,         // store-only; consumed by Plan 04 heartbeat summary
    currentCo2: null,          // store-only; consumed by Plan 04 heartbeat summary
    humidifierCyclesLast24h: 0,
    humidifierCycleLog: [],    // timestamps of ON transitions; pruned to last 24h on tick
    // Phase 26 Plan 03: per-physical-sensor freshness watchdogs.
    // Initialize to bootedAtMs (NEVER null) so a never-seen sensor doesn't
    // fire spuriously before the 60s grace + sensorOfflineMin window.
    sht30LastSeenMs: nowMs,
    scd41LastSeenMs: nowMs,
    perType,
  };
}

/**
 * Returns the cooldown threshold in ms for the given alert type.
 */
function cooldownMs(alertType, config) {
  const severity = SEVERITY[alertType];
  return (severity === 'CRITICAL' ? config.criticalCooldownMin : config.cooldownMin) * 60000;
}

/**
 * Returns true if the alert type is currently snoozed.
 */
function isSnoozed(perTypeEntry, now) {
  return perTypeEntry.snoozedUntil != null && now < perTypeEntry.snoozedUntil;
}

/**
 * Drive a generic OOB-style detector for a single alert type.
 * Returns { next: perTypeEntry, actions } where perTypeEntry is a mutated copy.
 *
 * oobNow: boolean — is the condition OOB right now?
 * fields: passed to formatProblem / formatRecovery
 */
function driveAlertType(entry, alertType, oobNow, fields, now, config) {
  const actions = [];
  const next = { ...entry, ctx: { ...entry.ctx } };
  const severity = SEVERITY[alertType];

  if (oobNow) {
    if (next.state === STATES.OK) {
      next.state = STATES.PENDING;
      next.oobCount = 1;
      next.firstOobAt = now;
      next.ctx.inBandCount = 0;
      // Check immediately — handles oobN=1 case
      const windowElapsed = (now - next.firstOobAt) >= config.oobWindowMin * 60000;
      if (next.oobCount >= config.oobN && windowElapsed) {
        next.state = STATES.FIRING;
        next.lastFiredAt = now;
        if (!isSnoozed(next, now)) {
          actions.push({
            kind: 'send',
            alertType,
            severity,
            body: messageLib.formatProblem({ alertType, severity, fields, config, nowMs: now }),
          });
        }
      }
    } else if (next.state === STATES.PENDING) {
      next.oobCount += 1;
      next.ctx.inBandCount = 0;
      // Check if we can transition to FIRING
      const windowElapsed = (now - next.firstOobAt) >= config.oobWindowMin * 60000;
      if (next.oobCount >= config.oobN && windowElapsed) {
        next.state = STATES.FIRING;
        next.lastFiredAt = now;
        if (!isSnoozed(next, now)) {
          actions.push({
            kind: 'send',
            alertType,
            severity,
            body: messageLib.formatProblem({ alertType, severity, fields, config, nowMs: now }),
          });
        }
      }
    } else if (next.state === STATES.FIRING) {
      next.ctx.inBandCount = 0;
      // Repeat send if cooldown elapsed and not snoozed
      if (!isSnoozed(next, now) && now - next.lastFiredAt > cooldownMs(alertType, config)) {
        next.lastFiredAt = now;
        actions.push({
          kind: 'send',
          alertType,
          severity,
          body: messageLib.formatProblem({ alertType, severity, fields, config, nowMs: now }),
        });
      }
    }
    // SNOOZED: state stays SNOOZED, no sends; natural resume when snoozedUntil passes
  } else {
    // In-band
    if (next.state === STATES.PENDING) {
      // Reset back to OK
      next.state = STATES.OK;
      next.oobCount = 0;
      next.firstOobAt = null;
      next.ctx.inBandCount = 0;
    } else if (next.state === STATES.FIRING) {
      next.ctx.inBandCount = (next.ctx.inBandCount || 0) + 1;
      if (next.ctx.inBandCount >= config.oobN) {
        const durationMs = next.firstOobAt != null ? now - next.firstOobAt : 0;
        next.state = STATES.OK;
        next.oobCount = 0;
        next.firstOobAt = null;
        next.lastFiredAt = null;
        next.ctx.inBandCount = 0;
        actions.push({
          kind: 'recovery',
          alertType,
          body: formatRecovery({ alertType, fields, durationMs, config }),
          durationMs,
        });
      }
    }
  }

  return { next, actions };
}

/**
 * resolveEffectiveConfig(state, envConfig, nowMs) -> effectiveConfig
 *
 * Phase 29 plan 29-04 (D-03 / D-05). Returns a config-shaped object whose
 * Tier A (rhTarget/rhBand), Tier B (oobN, oobWindowMin, cooldownMin,
 * criticalCooldownMin, humidifierStuckMin) and Tier C (piOfflineMin,
 * sensorOfflineMin, heartbeatHour, maxSendsPerHour) values reflect the
 * currently-cached runtime mode + alerter overrides + alerter globals when
 * mode is FRESH; otherwise falls back to envConfig.
 *
 * freshness = { state: 'fresh'|'stale'|'cold', source: 'mode'|'env' }
 */
function resolveEffectiveConfig(state, envConfig, nowMs) {
  const MODE_STALE_MS = (envConfig.modeStaleMin || 5) * 60 * 1000;
  const COLD_GRACE_MS = envConfig.modeBootGraceMs || 60000;
  const wsConnected = state.wsConnected !== false; // tolerate undefined as connected (existing tests)
  const modeAge = state.modeReceivedAtMs != null ? (nowMs - state.modeReceivedAtMs) : Infinity;
  const globals = state.alerterGlobals || {};

  // Tier C globals (process-global runtime overrides) are independent of mode
  // freshness — they apply even when ws is disconnected (e.g. piOfflineMin must
  // be honored precisely when fc1 is offline).
  const globalLayer = {
    piOfflineMin:     globals.pi_offline_min     != null ? globals.pi_offline_min     : envConfig.piOfflineMin,
    sensorOfflineMin: globals.sensor_offline_min != null ? globals.sensor_offline_min : envConfig.sensorOfflineMin,
    heartbeatHour:    globals.heartbeat_hour     != null ? globals.heartbeat_hour     : envConfig.heartbeatHour,
    maxSendsPerHour:  globals.max_sends_per_hour != null ? globals.max_sends_per_hour : envConfig.maxSendsPerHour,
  };

  // D-03 state 1: mode known and fresh — Tier A (mode-anchored) + Tier B (per-mode overrides) apply.
  if (state.currentMode && wsConnected && modeAge <= MODE_STALE_MS) {
    const m = state.currentMode;
    const overrides = (state.alerterOverrides && state.alerterOverrides[m.name]) || {};
    return {
      ...envConfig,
      ...globalLayer,
      rhTarget: m.target_humidity * 100,
      rhBand: ((m.band_high - m.band_low) / 2) * 100,
      bandLow: m.band_low * 100,
      bandHigh: m.band_high * 100,
      defendSide: m.defend_side,
      modeName: m.name,
      oobN:                overrides.oob_n              != null ? overrides.oob_n              : envConfig.oobN,
      oobWindowMin:        overrides.oob_window_min     != null ? overrides.oob_window_min     : envConfig.oobWindowMin,
      cooldownMin:         overrides.cooldown_min       != null ? overrides.cooldown_min       : envConfig.cooldownMin,
      criticalCooldownMin: overrides.critical_cooldown_min != null ? overrides.critical_cooldown_min : envConfig.criticalCooldownMin,
      humidifierStuckMin:  overrides.humidifier_stuck_min  != null ? overrides.humidifier_stuck_min  : envConfig.humidifierStuckMin,
      freshness: { state: 'fresh', source: 'mode' },
    };
  }
  // D-03 state 3: cold start grace.
  const bootAge = state.bootedAtMs != null ? (nowMs - state.bootedAtMs) : Infinity;
  if (state.currentMode == null && bootAge <= COLD_GRACE_MS) {
    return { ...envConfig, ...globalLayer, freshness: { state: 'cold', source: 'env' } };
  }
  // D-03 state 2: stale or never-arrived past grace.
  return { ...envConfig, ...globalLayer, freshness: { state: 'stale', source: 'env' } };
}

/**
 * Internal: returns true once the alerter has observed any mode/overrides/globals
 * envelope. Used to gate effective-config wiring so pre-Phase-29 tests / pre-29
 * deployments retain their pre-effective behavior (raw envConfig fed to rules).
 */
function hasModeContext(state) {
  return state.modeReceivedAtMs != null
      || state.overridesReceivedAtMs != null
      || state.globalsReceivedAtMs != null;
}

/**
 * transition(prev, event, now, config) -> { next, actions }
 */
function transition(prev, event, now, config) {
  const next = JSON.parse(JSON.stringify(prev)); // deep clone (structuredClone not available in older Node)
  const actions = [];

  switch (event.type) {
    case 'humidity': {
      next.currentRh = event.value;
      next.lastRhMsgTs = now;

      // Phase 29 plan 29-04: when mode/overrides/globals have arrived, route
      // rules through the effective config so Tier B overrides apply. Pre-29
      // call sites (no mode context yet) keep using raw envConfig — preserves
      // pre-existing test behavior and pre-29 production semantics.
      const effective = hasModeContext(next) ? resolveEffectiveConfig(next, config, now) : config;

      // RH alert (suppressed during warm-up)
      if (!next.warmingUp) {
        const oobNow = isRhOob(event.value, effective);
        const rhFields = { value: event.value, firstOobMs: next.perType.rh.firstOobAt };
        const r = driveAlertType(next.perType.rh, 'rh', oobNow, rhFields, now, effective);
        next.perType.rh = r.next;
        actions.push(...r.actions);

        // Humidifier stuck check (also suppressed during warm-up)
        if (next.humidifierOnSinceMs != null) {
          const stuck = isHumidifierStuck({
            humidifierOnSinceMs: next.humidifierOnSinceMs,
            rhAtOn: next.rhAtOn,
            currentRh: event.value,
            nowMs: now,
            config: effective,
          });
          const humFields = { onSinceMs: next.humidifierOnSinceMs, rhAtOn: next.rhAtOn, currentRh: event.value };
          const rh = driveAlertType(next.perType.humidifier, 'humidifier', stuck, humFields, now, effective);
          next.perType.humidifier = rh.next;
          actions.push(...rh.actions);
        }
      }
      break;
    }

    case 'mode_update': {
      next.currentMode = event.mode;
      next.modeReceivedAtMs = now;
      // D-09: reset in-progress dedup but PRESERVE lastFiredAt.
      // Pitfall 4 — first mode_update after cold start ALSO resets dedup
      // (env-fallback OOB accumulated during boot grace must not bleed into
      // mode-anchored decisions).
      for (const t of ['rh', 'humidifier']) {
        if (next.perType[t]) {
          next.perType[t].oobCount = 0;
          next.perType[t].firstOobAt = null;
          if (next.perType[t].ctx) {
            next.perType[t].ctx.inBandCount = 0;
          }
          // lastFiredAt INTENTIONALLY NOT reset — cooldown carries across mode swaps.
        }
      }
      break;
    }

    case 'overrides_update': {
      next.alerterOverrides = event.overrides;
      next.overridesReceivedAtMs = now;
      break;
    }

    case 'globals_update': {
      next.alerterGlobals = event.globals;
      next.globalsReceivedAtMs = now;
      break;
    }

    case 'temperature': {
      // Store-only; no alert transitions
      next.currentTemp = event.value;
      break;
    }

    case 'co2': {
      // Store-only; no alert transitions
      next.currentCo2 = event.value;
      break;
    }

    case 'sensor_health': {
      const { level } = event;
      if (level === 1) {
        next.warmingUp = true;
      } else if (level === 0) {
        next.warmingUp = false;
      }

      // Sensor ERROR detection — NOT suppressed by warm-up (ALRT-05)
      const isError = isSensorError(event);
      const sensorFields = { message: event.message };

      if (isError) {
        // sensor fires on first ERROR event (oobN=1, oobWindowMin=0)
        const sensorCfg = { ...config, oobN: 1, oobWindowMin: 0 };
        const r = driveAlertType(next.perType.sensor, 'sensor', true, sensorFields, now, sensorCfg);
        next.perType.sensor = r.next;
        actions.push(...r.actions);
      } else if (level === 0 || level === 1) {
        // Not an error — drive in-band for sensor alert
        const r = driveAlertType(next.perType.sensor, 'sensor', false, sensorFields, now, config);
        next.perType.sensor = r.next;
        actions.push(...r.actions);
      }

      // Phase 26 Plan 03: per-physical-sensor freshness from KeyValues.
      // Strict equality on string-bool from Pi side (Pitfall 4 — order-tolerant
      // but values are always 'true'/'false'). Unknown values fail-safe (no
      // refresh → eventually trips the watchdog).
      const v = event.values || {};
      if (v.sht30_fresh === 'true') {
        next.sht30LastSeenMs = now;
      }
      if (v.scd41_fresh === 'true') {
        next.scd41LastSeenMs = now;
      }
      // Drive sht30/scd41 alerts when value is explicitly 'false' (Pi-side
      // authoritative) OR alerter-side staleness exceeds threshold (Option C
      // hybrid — belt-and-braces). Skip during 60s startup grace.
      // 999.42: per-sensor enable flags allow muting a permanently-disconnected
      // sensor's watchdog (e.g. SHT30 since 2026-04-11) without blanket env
      // band-aids that also mask real SCD41 outages.
      if (now - next.bootedAtMs >= 60000) {
        const sensorCfg = { ...config, oobN: 1, oobWindowMin: 0 };

        if (config.sht30Enabled !== false) {
          const sht30Stale = v.sht30_fresh === 'false'
            || isSensorSilent({ lastSeenMs: next.sht30LastSeenMs, nowMs: now, config });
          const sht30Fields = { lastSeenMs: next.sht30LastSeenMs };
          const r = driveAlertType(next.perType.sht30, 'sht30', sht30Stale, sht30Fields, now, sensorCfg);
          next.perType.sht30 = r.next;
          actions.push(...r.actions);
        }

        if (config.scd41Enabled !== false) {
          const scd41Stale = v.scd41_fresh === 'false'
            || isSensorSilent({ lastSeenMs: next.scd41LastSeenMs, nowMs: now, config });
          const scd41Fields = { lastSeenMs: next.scd41LastSeenMs };
          const r = driveAlertType(next.perType.scd41, 'scd41', scd41Stale, scd41Fields, now, sensorCfg);
          next.perType.scd41 = r.next;
          actions.push(...r.actions);
        }
      }
      break;
    }

    case 'sensor_freshness': {
      // Phase 26 Plan 03: slot-2 WS arrival refreshes scd41LastSeenMs (and the
      // sht30 path in case index.js ever wires slot-1 frame_id arrivals here).
      const { sensor, lastSeenMs } = event;
      if (sensor === 'sht30') {
        next.sht30LastSeenMs = lastSeenMs != null ? lastSeenMs : now;
      } else if (sensor === 'scd41') {
        next.scd41LastSeenMs = lastSeenMs != null ? lastSeenMs : now;
      } else {
        break;
      }
      // Re-evaluate immediately so an arrival can clear a FIRING state — but
      // only post-grace, mirroring pi_liveness. 999.42: respect per-sensor
      // enable flags so a muted sensor doesn't get re-evaluated either.
      const sensorEnabled = (sensor === 'sht30')
        ? (config.sht30Enabled !== false)
        : (config.scd41Enabled !== false);
      if (sensorEnabled && now - next.bootedAtMs >= 60000) {
        const sensorCfg = { ...config, oobN: 1, oobWindowMin: 0 };
        const lastMs = (sensor === 'sht30') ? next.sht30LastSeenMs : next.scd41LastSeenMs;
        const stale = isSensorSilent({ lastSeenMs: lastMs, nowMs: now, config });
        const fields = { lastSeenMs: lastMs };
        const r = driveAlertType(next.perType[sensor], sensor, stale, fields, now, sensorCfg);
        next.perType[sensor] = r.next;
        actions.push(...r.actions);
      }
      break;
    }

    case 'humidifier': {
      const prevValue = next.humidifierOnSinceMs != null ? 1 : 0;
      const newValue = event.value;

      if (prevValue === 0 && newValue === 1) {
        // 0->1 transition: start tracking
        next.humidifierOnSinceMs = now;
        next.rhAtOn = next.currentRh;
        next.humidifierCycleLog.push(now);
        // Prune log to last 24h
        next.humidifierCycleLog = next.humidifierCycleLog.filter(ts => now - ts <= 86400000);
        next.humidifierCyclesLast24h = next.humidifierCycleLog.length;
      } else if (prevValue === 1 && newValue === 0) {
        // 1->0 transition: clear snapshot
        next.humidifierOnSinceMs = null;
        next.rhAtOn = null;

        // If humidifier alert was FIRING, emit recovery
        if (next.perType.humidifier.state === STATES.FIRING) {
          const durationMs = next.perType.humidifier.firstOobAt != null ? now - next.perType.humidifier.firstOobAt : 0;
          next.perType.humidifier.state = STATES.OK;
          next.perType.humidifier.oobCount = 0;
          next.perType.humidifier.firstOobAt = null;
          next.perType.humidifier.lastFiredAt = null;
          next.perType.humidifier.ctx = {};
          actions.push({
            kind: 'recovery',
            alertType: 'humidifier',
            body: formatRecovery({ alertType: 'humidifier', fields: {}, durationMs, config }),
            durationMs,
          });
        }
      }
      next.humidifierLastMsgTs = now;
      break;
    }

    case 'pi_liveness': {
      const { wsConnected, rosConnected, humidifierLastMsgTs } = event;

      // Update connectivity state
      if (wsConnected !== next.wsConnected) {
        if (wsConnected) {
          next.wsLastConnectedMs = now;
        }
        next.wsConnected = wsConnected;
      }
      if (rosConnected !== next.rosConnected) {
        if (!rosConnected) {
          next.rosDisconnectedSinceMs = now;
        } else {
          next.rosDisconnectedSinceMs = null;
        }
        next.rosConnected = rosConnected;
      }
      if (humidifierLastMsgTs != null) {
        next.humidifierLastMsgTs = humidifierLastMsgTs;
      }

      // Startup grace: skip Pi-offline evaluation for first 60s
      if (now - next.bootedAtMs < 60000) break;

      const effective = hasModeContext(next) ? resolveEffectiveConfig(next, config, now) : config;
      const offline = isPiOffline({
        wsConnected: next.wsConnected,
        rosConnected: next.rosConnected,
        nowMs: now,
        wsLastConnectedMs: next.wsLastConnectedMs,
        rosDisconnectedSinceMs: next.rosDisconnectedSinceMs,
        config: effective,
      });

      // Phase 29 plan 29-04 BLOCKER 2 (999.39): build last-known sample summary
      // for pi-alert message body. Schema mirrors 29-05 message.js
      // formatProblem(pi) lastKnown shape.
      const lastKnown = (next.currentRh != null && next.currentTemp != null && next.lastRhMsgTs != null)
        ? {
            rh: next.currentRh,
            temp: next.currentTemp,
            humidifier: next.humidifierOnSinceMs != null ? 'ON' : 'OFF',
            tsMs: next.lastRhMsgTs,
          }
        : null;
      const piFields = { lastSeenMs: next.wsLastConnectedMs, lastKnown };
      const r = driveAlertType(next.perType.pi, 'pi', offline, piFields, now, effective);
      next.perType.pi = r.next;
      actions.push(...r.actions);
      break;
    }

    case 'tick': {
      // Prune humidifier cycle log
      next.humidifierCycleLog = next.humidifierCycleLog.filter(ts => now - ts <= 86400000);
      next.humidifierCyclesLast24h = next.humidifierCycleLog.length;

      // Re-evaluate Pi offline (Phase 29 plan 29-04 — effective config + lastKnown)
      if (now - next.bootedAtMs >= 60000) {
        const effective = hasModeContext(next) ? resolveEffectiveConfig(next, config, now) : config;
        const offline = isPiOffline({
          wsConnected: next.wsConnected,
          rosConnected: next.rosConnected,
          nowMs: now,
          wsLastConnectedMs: next.wsLastConnectedMs,
          rosDisconnectedSinceMs: next.rosDisconnectedSinceMs,
          config: effective,
        });
        const lastKnown = (next.currentRh != null && next.currentTemp != null && next.lastRhMsgTs != null)
          ? {
              rh: next.currentRh,
              temp: next.currentTemp,
              humidifier: next.humidifierOnSinceMs != null ? 'ON' : 'OFF',
              tsMs: next.lastRhMsgTs,
            }
          : null;
        const piFields = { lastSeenMs: next.wsLastConnectedMs, lastKnown };
        const r = driveAlertType(next.perType.pi, 'pi', offline, piFields, now, effective);
        next.perType.pi = r.next;
        actions.push(...r.actions);
      }

      // Re-evaluate humidifier stuck (Phase 29 plan 29-04 — effective.humidifierStuckMin)
      if (!next.warmingUp && next.humidifierOnSinceMs != null && next.currentRh != null) {
        const effective = hasModeContext(next) ? resolveEffectiveConfig(next, config, now) : config;
        const stuck = isHumidifierStuck({
          humidifierOnSinceMs: next.humidifierOnSinceMs,
          rhAtOn: next.rhAtOn,
          currentRh: next.currentRh,
          nowMs: now,
          config: effective,
        });
        const humFields = { onSinceMs: next.humidifierOnSinceMs, rhAtOn: next.rhAtOn, currentRh: next.currentRh };
        const r = driveAlertType(next.perType.humidifier, 'humidifier', stuck, humFields, now, effective);
        next.perType.humidifier = r.next;
        actions.push(...r.actions);
      }

      // Phase 26 Plan 03: re-evaluate per-physical-sensor freshness watchdog.
      // Required because during prolonged silence no sensor_health/
      // sensor_freshness events arrive — without periodic tick re-evaluation,
      // the FIRING transition would never happen.
      if (now - next.bootedAtMs >= 60000) {
        const sensorCfg = { ...config, oobN: 1, oobWindowMin: 0 };
        for (const sensor of ['sht30', 'scd41']) {
          const lastMs = sensor === 'sht30' ? next.sht30LastSeenMs : next.scd41LastSeenMs;
          const stale = isSensorSilent({ lastSeenMs: lastMs, nowMs: now, config });
          const fields = { lastSeenMs: lastMs };
          const r = driveAlertType(next.perType[sensor], sensor, stale, fields, now, sensorCfg);
          next.perType[sensor] = r.next;
          actions.push(...r.actions);
        }
      }
      break;
    }

    case 'snooze': {
      const { alertType, untilMs } = event;
      if (alertType === 'all') {
        for (const t of ALERT_TYPES) {
          next.perType[t].snoozedUntil = untilMs;
        }
      } else {
        if (next.perType[alertType]) {
          next.perType[alertType].snoozedUntil = untilMs;
        }
      }
      break;
    }

    case 'heartbeat_tick': {
      // Determine current local date at heartbeatHour
      const localDate = new Intl.DateTimeFormat('en-CA', {
        timeZone: config.timezone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      }).format(new Date(now));

      const localHour = new Intl.DateTimeFormat('en-CA', {
        timeZone: config.timezone,
        hour: 'numeric',
        hour12: false,
      }).formatToParts(new Date(now)).find(p => p.type === 'hour');

      const hour = localHour ? parseInt(localHour.value, 10) : -1;

      if (hour === config.heartbeatHour && next.lastHeartbeatDay !== localDate) {
        next.lastHeartbeatDay = localDate;
        // Heartbeat bypasses ALL snoozes
        actions.push({
          kind: 'heartbeat',
          body: formatHeartbeat({ summary: event.summary, config, nowMs: now }),
        });
      }
      break;
    }

    default:
      break;
  }

  return { next, actions };
}

// Phase 25 Plan 05 (D-03 / D-06): capture-pipeline health slot.
// Mutable, in-process, in-memory (T-25-05-05 accept — restart resets).
// Pattern mirrors timelapse healthState (src/mission-control/timelapse/src/index.js).
function createCaptureHealth() {
  return {
    last_capture_at: null,
    last_capture_status: null,
    last_capture_error_at: null,
    last_capture_error: null,
    last_retention_at: null,
    last_retention_status: null,
    last_retention_rows: null,
  };
}

function recordCaptureSuccess(health, nowMs) {
  health.last_capture_at = nowMs;
  health.last_capture_status = 'ok';
}

function recordCaptureError(health, nowMs, reason) {
  health.last_capture_error_at = nowMs;
  health.last_capture_status = 'degraded';
  health.last_capture_error = String(reason || '').slice(0, 200);
}

function recordRetentionRun(health, nowMs, status, rowCount) {
  health.last_retention_at = nowMs;
  health.last_retention_status = status;
  health.last_retention_rows = rowCount;
}

module.exports = {
  transition, initialState, STATES, ALERT_TYPES, SEVERITY,
  // Phase 29 plan 29-04 — effective config resolver (mode + Tier B/C overrides)
  resolveEffectiveConfig,
  // captureHealth (Phase 25 Plan 05)
  createCaptureHealth, recordCaptureSuccess, recordCaptureError, recordRetentionRun,
};
