'use strict';

const { isRhOob, isSensorError, isPiOffline, isHumidifierStuck } = require('./rules');
const { formatProblem, formatRecovery, formatHeartbeat } = require('./message');

const STATES = Object.freeze({ OK: 'OK', PENDING: 'PENDING', FIRING: 'FIRING', SNOOZED: 'SNOOZED' });

const ALERT_TYPES = ['rh', 'sensor', 'pi', 'humidifier'];

// Severity per alert type
const SEVERITY = { rh: 'WARN', sensor: 'CRITICAL', pi: 'CRITICAL', humidifier: 'WARN' };

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
            body: formatProblem({ alertType, severity, fields, config, nowMs: now }),
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
            body: formatProblem({ alertType, severity, fields, config, nowMs: now }),
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
          body: formatProblem({ alertType, severity, fields, config, nowMs: now }),
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
 * transition(prev, event, now, config) -> { next, actions }
 */
function transition(prev, event, now, config) {
  const next = JSON.parse(JSON.stringify(prev)); // deep clone (structuredClone not available in older Node)
  const actions = [];

  switch (event.type) {
    case 'humidity': {
      next.currentRh = event.value;
      next.lastRhMsgTs = now;

      // RH alert (suppressed during warm-up)
      if (!next.warmingUp) {
        const oobNow = isRhOob(event.value, config);
        const rhFields = { value: event.value, firstOobMs: next.perType.rh.firstOobAt };
        const r = driveAlertType(next.perType.rh, 'rh', oobNow, rhFields, now, config);
        next.perType.rh = r.next;
        actions.push(...r.actions);

        // Humidifier stuck check (also suppressed during warm-up)
        if (next.humidifierOnSinceMs != null) {
          const stuck = isHumidifierStuck({
            humidifierOnSinceMs: next.humidifierOnSinceMs,
            rhAtOn: next.rhAtOn,
            currentRh: event.value,
            nowMs: now,
            config,
          });
          const humFields = { onSinceMs: next.humidifierOnSinceMs, rhAtOn: next.rhAtOn, currentRh: event.value };
          const rh = driveAlertType(next.perType.humidifier, 'humidifier', stuck, humFields, now, config);
          next.perType.humidifier = rh.next;
          actions.push(...rh.actions);
        }
      }
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

      const offline = isPiOffline({
        wsConnected: next.wsConnected,
        rosConnected: next.rosConnected,
        nowMs: now,
        wsLastConnectedMs: next.wsLastConnectedMs,
        rosDisconnectedSinceMs: next.rosDisconnectedSinceMs,
        config,
      });

      const piFields = { lastSeenMs: next.wsLastConnectedMs };
      const r = driveAlertType(next.perType.pi, 'pi', offline, piFields, now, config);
      next.perType.pi = r.next;
      actions.push(...r.actions);
      break;
    }

    case 'tick': {
      // Prune humidifier cycle log
      next.humidifierCycleLog = next.humidifierCycleLog.filter(ts => now - ts <= 86400000);
      next.humidifierCyclesLast24h = next.humidifierCycleLog.length;

      // Re-evaluate Pi offline
      if (now - next.bootedAtMs >= 60000) {
        const offline = isPiOffline({
          wsConnected: next.wsConnected,
          rosConnected: next.rosConnected,
          nowMs: now,
          wsLastConnectedMs: next.wsLastConnectedMs,
          rosDisconnectedSinceMs: next.rosDisconnectedSinceMs,
          config,
        });
        const piFields = { lastSeenMs: next.wsLastConnectedMs };
        const r = driveAlertType(next.perType.pi, 'pi', offline, piFields, now, config);
        next.perType.pi = r.next;
        actions.push(...r.actions);
      }

      // Re-evaluate humidifier stuck
      if (!next.warmingUp && next.humidifierOnSinceMs != null && next.currentRh != null) {
        const stuck = isHumidifierStuck({
          humidifierOnSinceMs: next.humidifierOnSinceMs,
          rhAtOn: next.rhAtOn,
          currentRh: next.currentRh,
          nowMs: now,
          config,
        });
        const humFields = { onSinceMs: next.humidifierOnSinceMs, rhAtOn: next.rhAtOn, currentRh: next.currentRh };
        const r = driveAlertType(next.perType.humidifier, 'humidifier', stuck, humFields, now, config);
        next.perType.humidifier = r.next;
        actions.push(...r.actions);
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

module.exports = { transition, initialState, STATES, ALERT_TYPES, SEVERITY };
