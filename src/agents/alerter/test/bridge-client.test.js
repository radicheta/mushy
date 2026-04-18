'use strict';

const http = require('http');
const WebSocket = require('ws');
const { createBridgeClient } = require('../src/bridge-client');

/**
 * Spin up an in-process WebSocket server on an ephemeral port.
 * Returns Promise<{ wss, url, close }>.
 */
function makeWssServer() {
  return new Promise((resolve) => {
    const wss = new WebSocket.Server({ port: 0, host: '127.0.0.1' });
    wss.once('listening', () => {
      const port = wss.address().port;
      const url = `ws://127.0.0.1:${port}`;
      const close = () => new Promise((res) => wss.close(res));
      resolve({ wss, url, close });
    });
  });
}

/**
 * Spin up a minimal HTTP server serving a fixed JSON body on all GET requests.
 * Returns Promise<{ server, url, close, setBody }>.
 */
function makeHealthServer(body) {
  return new Promise((resolve) => {
    let currentBody = body;
    const server = http.createServer((req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(currentBody));
    });
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      const url = `http://127.0.0.1:${port}/health`;
      const close = () => new Promise((res) => server.close(res));
      const setBody = (b) => { currentBody = b; };
      resolve({ server, url, close, setBody });
    });
  });
}

const healthBody = {
  status: 'ok', db: true,
  ros: { connected: true },
  camera: { lastFrame: 1713456000000, last_frame_age_sec: 2, clients: 0, subscribed: false },
  humidifier: { last_msg_ts: 1713456002000 },
};

describe('bridge-client.js', () => {
  let wssInfo;
  let healthInfo;
  let client;

  beforeEach(async () => {
    wssInfo = await makeWssServer();
    healthInfo = await makeHealthServer(healthBody);
  });

  afterEach(async () => {
    if (client) {
      client.close();
      client = null;
    }
    await wssInfo.close();
    await healthInfo.close();
  });

  describe('connect+receive', () => {
    it('receives parsed JSON from server within 500ms', async () => {
      const received = [];
      client = createBridgeClient({
        wsUrl: wssInfo.url,
        healthUrl: healthInfo.url,
        onMessage: (msg) => received.push(msg),
        onLiveness: () => {},
      });
      client.start();

      // Wait for connection
      await new Promise((resolve) => {
        wssInfo.wss.once('connection', resolve);
      });

      // Emit from server
      for (const ws of wssInfo.wss.clients) {
        ws.send(JSON.stringify({ humidity: 90 }));
      }

      await new Promise((r) => setTimeout(r, 100));
      expect(received).toHaveLength(1);
      expect(received[0]).toEqual({ humidity: 90 });
    });

    it('isConnected() returns true once connected', async () => {
      client = createBridgeClient({
        wsUrl: wssInfo.url,
        healthUrl: healthInfo.url,
        onMessage: () => {},
        onLiveness: () => {},
      });
      client.start();
      await new Promise((resolve) => {
        wssInfo.wss.once('connection', resolve);
      });
      // Give the open event a tick to process
      await new Promise((r) => setTimeout(r, 20));
      expect(client.isConnected()).toBe(true);
    });
  });

  describe('health_bootstrap', () => {
    it('calls onLiveness with rosConnected=true BEFORE any onMessage calls', async () => {
      const events = [];

      client = createBridgeClient({
        wsUrl: wssInfo.url,
        healthUrl: healthInfo.url,
        onMessage: (msg) => events.push({ type: 'message', msg }),
        onLiveness: (l) => events.push({ type: 'liveness', l }),
      });
      client.start();

      // Wait for WS connection
      const connectedWs = await new Promise((resolve) => {
        wssInfo.wss.once('connection', (ws) => resolve(ws));
      });

      // Give the client time to poll /health (async after 'open')
      await new Promise((r) => setTimeout(r, 100));

      // Now send a message AFTER health has been polled
      connectedWs.send(JSON.stringify({ humidity: 90 }));
      await new Promise((r) => setTimeout(r, 50));

      const livenessIdx = events.findIndex((e) => e.type === 'liveness' && e.l.wsConnected === true);
      const messageIdx = events.findIndex((e) => e.type === 'message');
      expect(livenessIdx).toBeGreaterThanOrEqual(0);
      expect(messageIdx).toBeGreaterThan(livenessIdx);

      expect(events[livenessIdx].l.rosConnected).toBe(true);
      expect(typeof events[livenessIdx].l.humidifierLastMsgTs).toBe('number');
    });
  });

  describe('reconnect_backoff', () => {
    it('reconnects after server closes the socket', async () => {
      const received = [];
      client = createBridgeClient({
        wsUrl: wssInfo.url,
        healthUrl: healthInfo.url,
        onMessage: (msg) => received.push(msg),
        onLiveness: () => {},
        minBackoffMs: 100,  // fast for tests
        maxBackoffMs: 200,
      });
      client.start();

      // Wait for first connection
      const firstWs = await new Promise((resolve) => {
        wssInfo.wss.once('connection', (ws) => resolve(ws));
      });
      await new Promise((r) => setTimeout(r, 50));

      // Close it from server side
      firstWs.close();

      // Wait for reconnect
      await new Promise((resolve) => {
        wssInfo.wss.once('connection', resolve);
      });
      await new Promise((r) => setTimeout(r, 50));

      // Send a message on the new connection
      for (const ws of wssInfo.wss.clients) {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ humidity: 88 }));
        }
      }

      await new Promise((r) => setTimeout(r, 100));
      expect(received.some((m) => m.humidity === 88)).toBe(true);
    });
  });

  describe('no_process_exit', () => {
    it('does not throw synchronously when server is unreachable', () => {
      // Point at a dead port — must not throw, must not call process.exit
      expect(() => {
        client = createBridgeClient({
          wsUrl: 'ws://127.0.0.1:1',
          healthUrl: 'http://127.0.0.1:1/health',
          onMessage: () => {},
          onLiveness: () => {},
          minBackoffMs: 50000,  // very long so we don't hammer in tests
        });
        client.start();
      }).not.toThrow();
    });
  });

  describe('close_stops_reconnect', () => {
    it('no further reconnects after close()', async () => {
      let connectionCount = 0;
      wssInfo.wss.on('connection', () => { connectionCount++; });

      client = createBridgeClient({
        wsUrl: wssInfo.url,
        healthUrl: healthInfo.url,
        onMessage: () => {},
        onLiveness: () => {},
        minBackoffMs: 50,
        maxBackoffMs: 100,
      });
      client.start();

      // Wait for first connection
      await new Promise((resolve) => {
        wssInfo.wss.once('connection', resolve);
      });
      await new Promise((r) => setTimeout(r, 30));

      client.close();
      client = null;

      const countAfterClose = connectionCount;
      // Wait longer than backoff — no new connections should occur
      await new Promise((r) => setTimeout(r, 200));
      expect(connectionCount).toBe(countAfterClose);
    });
  });

  describe('liveness_on_disconnect', () => {
    it('calls onLiveness({wsConnected:false}) when WS closes', async () => {
      const livenessEvents = [];
      client = createBridgeClient({
        wsUrl: wssInfo.url,
        healthUrl: healthInfo.url,
        onMessage: () => {},
        onLiveness: (l) => livenessEvents.push(l),
        minBackoffMs: 10000,  // prevent reconnect during test
      });
      client.start();

      const connectedWs = await new Promise((resolve) => {
        wssInfo.wss.once('connection', (ws) => resolve(ws));
      });
      await new Promise((r) => setTimeout(r, 100));

      // Close server-side
      connectedWs.close();
      await new Promise((r) => setTimeout(r, 100));

      const disconnectEvent = livenessEvents.find((e) => e.wsConnected === false);
      expect(disconnectEvent).toBeDefined();
    });
  });
});
