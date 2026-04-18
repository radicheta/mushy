'use strict';

const { createReceiveLoop } = require('../src/receive-loop');
const fakeSignalServer = require('./helpers/fake-signal-server');

const silentLogger = { info: () => {}, warn: () => {}, error: () => {} };

const baseConfig = {
  signalSender: '+1111111111',
  signalRecipient: '+1111111111',
  receivePollSec: 0.05,
};

function makeSignalClient(server) {
  return {
    receive: async () => {
      const res = await fetch(`${server.url}/v1/receive/${encodeURIComponent('+1111111111')}`);
      return await res.json();
    },
    send: async (body) => {
      const res = await fetch(`${server.url}/v2/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: body, number: '+1111111111', recipients: ['+1111111111'] }),
      });
      return { ok: res.ok };
    },
  };
}

describe('createReceiveLoop', () => {
  let server;
  let loop;

  beforeEach(async () => {
    server = await fakeSignalServer.start();
  });

  afterEach(async () => {
    if (loop) loop.stop();
    await server.close();
  });

  test('Test A: valid snooze envelope dispatches snooze event within 500ms', async () => {
    const dispatched = [];
    const nowMs = Date.now();
    const clock = () => nowMs;

    // Push a valid snooze envelope
    server.received.push({
      envelope: { source: '+1111111111', dataMessage: { message: 'snooze rh 4h' } }
    });

    const client = makeSignalClient(server);
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      logger: silentLogger,
      clock,
    });
    loop.start();

    await new Promise((resolve) => setTimeout(resolve, 300));
    loop.stop();

    expect(dispatched).toHaveLength(1);
    expect(dispatched[0].type).toBe('snooze');
    expect(dispatched[0].alertType).toBe('rh');
    expect(dispatched[0].untilMs).toBeGreaterThan(nowMs);
  });

  test('Test B: invalid command triggers help-text reply, no dispatch', async () => {
    const dispatched = [];
    const clock = () => Date.now();

    server.received.push({
      envelope: { source: '+1111111111', dataMessage: { message: 'mute rh' } }
    });

    const client = makeSignalClient(server);
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      logger: silentLogger,
      clock,
    });
    loop.start();

    await new Promise((resolve) => setTimeout(resolve, 300));
    loop.stop();

    expect(dispatched).toHaveLength(0);
    expect(server.sent).toHaveLength(1);
    expect(server.sent[0].message).toMatch(/snooze/i);
  });

  test('Test C: envelope from unrecognized sender is ignored', async () => {
    const dispatched = [];
    const clock = () => Date.now();

    server.received.push({
      envelope: { source: '+9999999999', dataMessage: { message: 'snooze rh 4h' } }
    });

    const client = makeSignalClient(server);
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      logger: silentLogger,
      clock,
    });
    loop.start();

    await new Promise((resolve) => setTimeout(resolve, 300));
    loop.stop();

    expect(dispatched).toHaveLength(0);
    expect(server.sent).toHaveLength(0);
  });

  test('Test D: if receive() throws, loop continues on next tick', async () => {
    const dispatched = [];
    let callCount = 0;
    const clock = () => Date.now();

    const brokenClient = {
      receive: async () => {
        callCount++;
        if (callCount === 1) throw new Error('network error');
        return [];
      },
      send: async () => {},
    };

    loop = createReceiveLoop({
      signalClient: brokenClient,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      logger: silentLogger,
      clock,
    });
    loop.start();

    await new Promise((resolve) => setTimeout(resolve, 300));
    loop.stop();

    // Loop did not die: at least 2 calls were made (first threw, second succeeded)
    expect(callCount).toBeGreaterThanOrEqual(2);
    expect(dispatched).toHaveLength(0); // no valid snooze events
  });

  test('Test E: stop() halts further receive() calls', async () => {
    const clock = () => Date.now();
    let callCount = 0;

    const countingClient = {
      receive: async () => { callCount++; return []; },
      send: async () => {},
    };

    loop = createReceiveLoop({
      signalClient: countingClient,
      dispatch: () => {},
      config: baseConfig,
      logger: silentLogger,
      clock,
    });
    loop.start();
    await new Promise((resolve) => setTimeout(resolve, 100));
    const countAfterStart = callCount;
    loop.stop();
    const countAfterStop = callCount;
    await new Promise((resolve) => setTimeout(resolve, 200));
    const countAfterWait = callCount;

    expect(countAfterStop).toBeGreaterThan(0); // loop ran at least once
    // After stop, no further calls (allow one in-flight tick to complete)
    expect(countAfterWait).toBeLessThanOrEqual(countAfterStop + 1);
  });
});
