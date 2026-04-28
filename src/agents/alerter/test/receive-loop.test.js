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

  test('Test B: snooze-prefixed malformed command triggers help-text reply, no dispatch', async () => {
    // 25-05: only snooze-prefixed malformed text triggers fuzzy help; arbitrary text
    // ("mute rh") now flows to the capture pipeline (covered by capture-fanout test below).
    const dispatched = [];
    const clock = () => Date.now();

    server.received.push({
      envelope: { source: '+1111111111', dataMessage: { message: 'snooze rh banana' } }
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

  test('R4-fastpath: bare "mute" dispatches snooze, capturePipeline.handle NOT called, ack sent', async () => {
    const dispatched = [];
    const captureCalls = [];
    const sent = [];
    const clock = () => 1000;
    const client = {
      receive: (() => {
        let n = 0;
        return async () => {
          n++;
          if (n === 1) return [{ envelope: { source: '+1111111111', dataMessage: { message: 'mute' } } }];
          return [];
        };
      })(),
      send: async (body) => { sent.push(body); return { ok: true }; },
    };
    const capturePipeline = { handle: async (env) => { captureCalls.push(env); } };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      capturePipeline,
      logger: silentLogger,
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 200));
    loop.stop();

    expect(dispatched).toHaveLength(1);
    expect(dispatched[0].type).toBe('snooze');
    expect(dispatched[0].alertType).toBe('all');
    expect(captureCalls).toHaveLength(0);
    expect(sent.some((b) => /muted for 24h/i.test(b))).toBe(true);
  });

  test('R6-budget: snooze fast-path NOT awaiting capturePipeline.handle (never-resolves capture)', async () => {
    const dispatched = [];
    const clock = () => 1000;
    let receiveCalls = 0;
    const client = {
      receive: async () => {
        receiveCalls++;
        return [{ envelope: { source: '+1111111111', dataMessage: { message: 'mute' } } }];
      },
      send: async () => ({ ok: true }),
    };
    // capture handle returns a promise that never resolves
    const capturePipeline = { handle: () => new Promise(() => {}) };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      capturePipeline,
      logger: silentLogger,
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 250));
    loop.stop();
    // Two ticks at 50ms poll → at least 2 dispatches (proves loop did NOT block on capture)
    expect(dispatched.length).toBeGreaterThanOrEqual(2);
    expect(dispatched[0].type).toBe('snooze');
  });

  test('R7: non-whitelisted sender → no dispatch, no capture, logger.warn fired', async () => {
    const dispatched = [];
    const captureCalls = [];
    const warnings = [];
    const clock = () => 1000;
    const client = {
      receive: (() => {
        let n = 0;
        return async () => {
          n++;
          if (n === 1) return [{ envelope: { source: '+99999999999', dataMessage: { message: 'mute' } } }];
          return [];
        };
      })(),
      send: async () => ({ ok: true }),
    };
    const capturePipeline = { handle: async (env) => { captureCalls.push(env); } };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      capturePipeline,
      logger: { info: () => {}, warn: (m) => warnings.push(m), error: () => {} },
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 200));
    loop.stop();

    expect(dispatched).toHaveLength(0);
    expect(captureCalls).toHaveLength(0);
    expect(warnings.some((w) => /rejected sender/i.test(w))).toBe(true);
  });

  test('capture-fanout: text-only non-snooze envelope → capturePipeline.handle called, no dispatch', async () => {
    const dispatched = [];
    const captureCalls = [];
    const clock = () => 1000;
    const client = {
      receive: (() => {
        let n = 0;
        return async () => {
          n++;
          if (n === 1) return [{ envelope: { source: '+1111111111', dataMessage: { message: 'hello' } } }];
          return [];
        };
      })(),
      send: async () => ({ ok: true }),
    };
    const capturePipeline = { handle: async (env) => { captureCalls.push(env); } };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      capturePipeline,
      logger: silentLogger,
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 200));
    loop.stop();

    expect(dispatched).toHaveLength(0);
    expect(captureCalls).toHaveLength(1);
    expect(captureCalls[0].source).toBe('+1111111111');
    expect(captureCalls[0].text).toBe('hello');
    expect(Array.isArray(captureCalls[0].attachments)).toBe(true);
  });

  test('capture-fanout: attachment-only (no text) → capturePipeline.handle called', async () => {
    const dispatched = [];
    const captureCalls = [];
    const clock = () => 1000;
    const att = { id: 'att1', contentType: 'image/jpeg' };
    const client = {
      receive: (() => {
        let n = 0;
        return async () => {
          n++;
          if (n === 1) return [{ envelope: { source: '+1111111111', dataMessage: { message: null, attachments: [att] } } }];
          return [];
        };
      })(),
      send: async () => ({ ok: true }),
    };
    const capturePipeline = { handle: async (env) => { captureCalls.push(env); } };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      capturePipeline,
      logger: silentLogger,
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 200));
    loop.stop();

    expect(dispatched).toHaveLength(0);
    expect(captureCalls).toHaveLength(1);
    expect(captureCalls[0].attachments).toHaveLength(1);
    expect(captureCalls[0].text).toBe(null);
  });

  test('capture-fanout: pipeline rejection is caught (logger.warn), loop continues', async () => {
    const warnings = [];
    let receiveCalls = 0;
    const clock = () => 1000;
    const client = {
      receive: async () => {
        receiveCalls++;
        return [{ envelope: { source: '+1111111111', dataMessage: { message: 'hello' } } }];
      },
      send: async () => ({ ok: true }),
    };
    const capturePipeline = { handle: async () => { throw new Error('boom'); } };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: () => {},
      config: baseConfig,
      capturePipeline,
      logger: { info: () => {}, warn: (m) => warnings.push(m), error: () => {} },
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 250));
    loop.stop();

    expect(receiveCalls).toBeGreaterThanOrEqual(2); // loop kept ticking
    expect(warnings.some((w) => /capture/i.test(w) && /boom/.test(w))).toBe(true);
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
