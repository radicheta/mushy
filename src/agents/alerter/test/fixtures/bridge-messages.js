// Bridge WS message fixtures for alerter tests.
// Phase 29 plan 29-01 — appended factories matching new bridge broadcasts (29-02 plan).

'use strict';

const humidityInBand = { humidity: 90.0, timestamp: 1713456000000 };
const humidityOob = { humidity: 83.2, timestamp: 1713456001000 };     // 90-83.2 = 6.8 > band=3
const humidifierOn = { humidifier: 1, timestamp: 1713456002000 };
const humidifierOff = { humidifier: 0, timestamp: 1713456003000 };
const sensorHealthOk = {
  sensor_health: { level: 0, name: 'fc1_sensor_health', message: 'ok', values: {} },
  timestamp: 1713456004000
};
const sensorHealthWarmup = {
  sensor_health: { level: 1, name: 'fc1_sensor_health', message: 'warming up',
                   values: { grace_elapsed_sec: '5', grace_total_sec: '20' } },
  timestamp: 1713456005000
};
const sensorHealthError = {
  sensor_health: { level: 2, name: 'fc1_sensor_health', message: 'SHT30 offline',
                   values: { sht30: 'offline' } },
  timestamp: 1713456006000
};
const healthPayloadRosConnected = {
  status: 'ok', db: true, ros: { connected: true },
  camera: { lastFrame: 1713456000000, last_frame_age_sec: 2, clients: 0, subscribed: false },
  humidifier: { last_msg_ts: 1713456002000 }
};
const healthPayloadRosDisconnected = {
  status: 'ok', db: true, ros: { connected: false },
  camera: { lastFrame: null, last_frame_age_sec: null, clients: 0, subscribed: false },
  humidifier: { last_msg_ts: null }
};

// ---- Phase 29 factories — bridge broadcasts for current_mode + alerter overrides/globals.
// Pitfall 5: t_target defaults to null (not NaN) because JSON.stringify(NaN) === 'null';
// the bridge will emit `null` on the wire even though the controller sends NaN.

function currentModeMsg({
  name = 'fruiting',
  target_humidity = 0.96,
  band_low = 0.945,
  band_high = 0.975,
  defend_side = 'both',
  t_target = null,
  source = 'config_default',
  effective_since_sec = 1714000000,
  effective_since_nsec = 0,
} = {}) {
  return {
    current_mode: {
      name, target_humidity, band_low, band_high, defend_side, t_target,
      effective_since: { sec: effective_since_sec, nanosec: effective_since_nsec },
      source,
    },
    timestamp: 1714000000_000,
  };
}

function alerterOverridesMsg(modes = { fruiting: { cooldown_min: 30 }, pinning: { cooldown_min: 60 } }) {
  return { alerter_overrides: modes, timestamp: 1714000000_000 };
}

function alerterGlobalsMsg(globals = { pi_offline_min: 5, sensor_offline_min: 5, heartbeat_hour: 8, max_sends_per_hour: 20 }) {
  return { alerter_globals: globals, timestamp: 1714000000_000 };
}

module.exports = {
  // Pre-Phase-29 fixtures (preserved verbatim).
  humidityInBand,
  humidityOob,
  humidifierOn,
  humidifierOff,
  sensorHealthOk,
  sensorHealthWarmup,
  sensorHealthError,
  healthPayloadRosConnected,
  healthPayloadRosDisconnected,
  // Phase 29 — new factories.
  currentModeMsg,
  alerterOverridesMsg,
  alerterGlobalsMsg,
};
