'use strict';

/**
 * Tests for sensor-snapshot fetcher (Phase 25-04, R5/D-11).
 * Drives a tiny http.createServer to cover: 200, 500, timeout, invalid JSON, custom timeoutMs.
 */

const http = require('http');
const { createSensorSnapshotFetcher } = require('../src/sensor-snapshot');

function startServer(handler) {
  return new Promise((resolve, reject) => {
    const server = http.createServer(handler);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({
        url: `http://127.0.0.1:${port}`,
        close: () => new Promise((r) => server.close(r)),
      });
    });
    server.on('error', reject);
  });
}

const silentLogger = { warn: () => {}, info: () => {}, error: () => {} };

describe('createSensorSnapshotFetcher', () => {
  let server;

  afterEach(async () => {
    if (server) await server.close();
    server = null;
  });

  test('200 OK with JSON → resolved to parsed body', async () => {
    const payload = {
      sensors: { humidity: 89.4, temperature: 22.1, co2: 612 },
      sensor_health: { status: 'OK' },
    };
    server = await startServer((req, res) => {
      expect(req.url).toBe('/farmer/summary');
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(payload));
    });
    const fetchSnapshot = createSensorSnapshotFetcher({ bridgeUrl: server.url, logger: silentLogger });
    const out = await fetchSnapshot();
    expect(out).toEqual(payload);
  });

  test('500 → null', async () => {
    server = await startServer((req, res) => {
      res.writeHead(500);
      res.end('internal error');
    });
    const fetchSnapshot = createSensorSnapshotFetcher({ bridgeUrl: server.url, logger: silentLogger });
    expect(await fetchSnapshot()).toBeNull();
  });

  test('server delay > timeoutMs → null (no throw)', async () => {
    server = await startServer((req, res) => {
      // Never respond within budget.
      setTimeout(() => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end('{}');
      }, 1000);
    });
    const fetchSnapshot = createSensorSnapshotFetcher({
      bridgeUrl: server.url,
      timeoutMs: 50,
      logger: silentLogger,
    });
    expect(await fetchSnapshot()).toBeNull();
  });

  test('invalid JSON body → null (no throw)', async () => {
    server = await startServer((req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end('this is not json {');
    });
    const fetchSnapshot = createSensorSnapshotFetcher({ bridgeUrl: server.url, logger: silentLogger });
    expect(await fetchSnapshot()).toBeNull();
  });

  test('factory accepts custom timeoutMs and uses AbortSignal.timeout(ms)', async () => {
    // Verify by behavior: a 200ms server delay with a 500ms timeout should still resolve.
    server = await startServer((req, res) => {
      setTimeout(() => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ sensors: { humidity: 50 } }));
      }, 100);
    });
    const fetchSnapshot = createSensorSnapshotFetcher({
      bridgeUrl: server.url,
      timeoutMs: 500,
      logger: silentLogger,
    });
    const out = await fetchSnapshot();
    expect(out).toEqual({ sensors: { humidity: 50 } });
  });
});
