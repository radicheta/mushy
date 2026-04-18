'use strict';

/**
 * isRhOob(humidity, config) -> boolean
 * True when abs(humidity - rhTarget) > rhBand.
 */
function isRhOob(humidity, config) {
  return Math.abs(humidity - config.rhTarget) > config.rhBand;
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
 *               rosDisconnectedSinceMs, config }) -> boolean
 *
 * Fires if:
 * - WS has been disconnected for > piOfflineMin minutes, OR
 * - ROS has been disconnected for > piOfflineMin minutes
 */
function isPiOffline({ wsConnected, rosConnected, nowMs, wsLastConnectedMs, rosDisconnectedSinceMs, config }) {
  const thresholdMs = config.piOfflineMin * 60000;

  if (!wsConnected && wsLastConnectedMs != null) {
    if (nowMs - wsLastConnectedMs > thresholdMs) return true;
  }

  if (rosConnected === false && rosDisconnectedSinceMs != null) {
    if (nowMs - rosDisconnectedSinceMs > thresholdMs) return true;
  }

  return false;
}

/**
 * isHumidifierStuck({ humidifierOnSinceMs, rhAtOn, currentRh, nowMs, config }) -> boolean
 *
 * True when humidifier has been ON for > humidifierStuckMin minutes AND
 * RH has risen less than 3% from when it turned on.
 */
function isHumidifierStuck({ humidifierOnSinceMs, rhAtOn, currentRh, nowMs, config }) {
  if (humidifierOnSinceMs == null) return false;
  const onDurationMs = nowMs - humidifierOnSinceMs;
  const thresholdMs = config.humidifierStuckMin * 60000;
  if (onDurationMs <= thresholdMs) return false;
  const rhRise = currentRh - rhAtOn;
  return rhRise < 3.0;
}

module.exports = { isRhOob, isSensorError, isPiOffline, isHumidifierStuck };
