module.exports = {
  humidityInBand: { humidity: 90.0, timestamp: 1713456000000 },
  humidityOob: { humidity: 83.2, timestamp: 1713456001000 },     // 90-83.2 = 6.8 > band=3
  humidifierOn: { humidifier: 1, timestamp: 1713456002000 },
  humidifierOff: { humidifier: 0, timestamp: 1713456003000 },
  sensorHealthOk: {
    sensor_health: { level: 0, name: 'fc1_sensor_health', message: 'ok', values: {} },
    timestamp: 1713456004000
  },
  sensorHealthWarmup: {
    sensor_health: { level: 1, name: 'fc1_sensor_health', message: 'warming up',
                     values: { grace_elapsed_sec: '5', grace_total_sec: '20' } },
    timestamp: 1713456005000
  },
  sensorHealthError: {
    sensor_health: { level: 2, name: 'fc1_sensor_health', message: 'SHT30 offline',
                     values: { sht30: 'offline' } },
    timestamp: 1713456006000
  },
  healthPayloadRosConnected: {
    status: 'ok', db: true, ros: { connected: true },
    camera: { lastFrame: 1713456000000, last_frame_age_sec: 2, clients: 0, subscribed: false },
    humidifier: { last_msg_ts: 1713456002000 }
  },
  healthPayloadRosDisconnected: {
    status: 'ok', db: true, ros: { connected: false },
    camera: { lastFrame: null, last_frame_age_sec: null, clients: 0, subscribed: false },
    humidifier: { last_msg_ts: null }
  }
};
