'use strict';

/**
 * isRhOob(humidity, effective) -> boolean
 * True when abs(humidity - rhTarget) > rhBand.
 *
 * Phase 29 D-03: when freshness is "stale" (mode unknown / fc1 offline),
 * suspend the rule to avoid the 2026-05-07 false-CRITICAL pathology.
 * Backwards-compat: legacy callers passing `{rhTarget, rhBand}` without a
 * `freshness` sub-object are treated as fresh (gate is opt-in via short-circuit).
 */
function isRhOob(humidity, effective) {
  if (effective && effective.freshness && effective.freshness.state === 'stale') return false;
  return Math.abs(humidity - effective.rhTarget) > effective.rhBand;
}

/**
 * isSensorError(sensorHealth) -> boolean
 * True when sensor_health.level === 2 (ERROR).
 */
function isSensorError(sensorHealth) {
  return sensorHealth.level === 2;
}

/**
 * isPiOffline({ wsConnected, rosConnected, nowMs, wsLastConnectedMs,
 *               rosDisconnectedSinceMs, fc1LastMsgTs, config }) -> boolean
 *
 * Fires if any of:
 * - WS has been disconnected for > piOfflineMin minutes, OR
 * - ROS has been disconnected for > piOfflineMin minutes, OR
 * - fc1LastMsgTs is stale by > piOfflineMin minutes (Phase 46 D-03).
 *
 * The fc1LastMsgTs trigger is the actual "chamber dark" signal: fc1 publisher
 * silence inferred from data flow across every subscribed topic. The existing
 * ws/ros triggers are RETAINED (D-03) because they catch real failure modes
 * (alerter<->bridge partition, bridge container ROS init failure) that the
 * data-flow signal alone would not surface.
 *
 * fc1LastMsgTs `undefined` (old caller / pre-46) or `null` (old bridge with
 * no fc1 block in /health) skips the new branch -- graceful degradation.
 */
function isPiOffline({ wsConnected, rosConnected, nowMs, wsLastConnectedMs, rosDisconnectedSinceMs, fc1LastMsgTs, config }) {
  const thresholdMs = config.piOfflineMin * 60000;

  if (!wsConnected && wsLastConnectedMs != null) {
    if (nowMs - wsLastConnectedMs > thresholdMs) return true;
  }

  if (rosConnected === false && rosDisconnectedSinceMs != null) {
    if (nowMs - rosDisconnectedSinceMs > thresholdMs) return true;
  }

  // Phase 46 D-03: third OR-trigger. `!= null` handles both undefined (old
  // caller) and null (old bridge) identically: no trigger, no false positive.
  if (fc1LastMsgTs != null) {
    if (nowMs - fc1LastMsgTs > thresholdMs) return true;
  }

  return false;
}

/**
 * isHumidifierStuck({ humidifierOnSinceMs, rhAtOn, currentRh, nowMs, config }) -> boolean
 *
 * True when humidifier has been ON for > humidifierStuckMin minutes AND
 * RH has risen less than 3% from when it turned on.
 */
function isHumidifierStuck({ humidifierOnSinceMs, rhAtOn, currentRh, nowMs, config, wsConnected, humidifierLastMsgTs }) {
  // Phase 29 D-04 / 999.39 — offline-blindness gate.
  // Liveness inputs are OPT-IN: pre-Phase-29 callers that omitted them keep working
  // (undefined ≠ false / null); post-Phase-29 callers (state.js driveAlertType for
  // humidifier) MUST pass both. The 2026-05-07 false-CRITICAL bug fired during the
  // 11h fc1 outage because cached humidifierOnSinceMs was ancient and currentRh was
  // frozen — the gates suppress the rule when we have no live data.
  if (wsConnected === false) return false;
  if (humidifierLastMsgTs === null) return false;
  if (humidifierLastMsgTs !== undefined && (nowMs - humidifierLastMsgTs) > (config.sensorOfflineMin || 5) * 60000) {
    return false;
  }
  // ---- existing math UNCHANGED below ----
  if (humidifierOnSinceMs == null) return false;
  const onDurationMs = nowMs - humidifierOnSinceMs;
  const thresholdMs = config.humidifierStuckMin * 60000;
  if (onDurationMs <= thresholdMs) return false;
  const rhRise = currentRh - rhAtOn;
  return rhRise < 3.0;
}

/**
 * isSensorSilent({ lastSeenMs, nowMs, config }) -> boolean
 *
 * True when the per-physical-sensor watchdog elapsed past sensorOfflineMin
 * minutes since the last freshness signal.
 */
function isSensorSilent({ lastSeenMs, nowMs, config }) {
  if (lastSeenMs == null) return false;
  const thresholdMs = config.sensorOfflineMin * 60000;
  return nowMs - lastSeenMs > thresholdMs;
}

module.exports = { isRhOob, isSensorError, isPiOffline, isHumidifierStuck, isSensorSilent };
