const fixtures = require('./fixtures/bridge-messages');
const { start } = require('./helpers/fake-signal-server');

describe('Wave 0 scaffold smoke', () => {
  test('bridge fixtures are well-formed', () => {
    expect(fixtures.humidityOob.humidity).toBe(83.2);
    expect(fixtures.sensorHealthWarmup.sensor_health.level).toBe(1);
    expect(fixtures.sensorHealthError.sensor_health.level).toBe(2);
    expect(fixtures.healthPayloadRosDisconnected.ros.connected).toBe(false);
  });

  test('fake signal server captures sends and drains receives', async () => {
    const server = await start();
    try {
      const sendRes = await fetch(`${server.url}/v2/send`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ message: 'hi', number: '+1', recipients: ['+2'] })
      });
      expect(sendRes.status).toBe(201);
      expect(server.sent[0].message).toBe('hi');

      server.received.push({ envelope: { source: '+1', dataMessage: { message: 'snooze rh 4h' } } });
      const recvRes = await fetch(`${server.url}/v1/receive/%2B1?timeout=1`);
      const recvBody = await recvRes.json();
      expect(recvBody[0].envelope.dataMessage.message).toBe('snooze rh 4h');
      expect(server.received.length).toBe(0);
    } finally {
      await server.close();
    }
  });
});
