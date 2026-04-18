'use strict';

const { start: startFakeServer } = require('./helpers/fake-signal-server');
const { createSignalClient } = require('../src/signal');

describe('signal.js', () => {
  let server;
  let client;

  const SENDER = '+15551111111';
  const RECIPIENT = '+15552222222';

  beforeEach(async () => {
    server = await startFakeServer();
    client = createSignalClient({
      apiUrl: server.url,
      sender: SENDER,
      recipient: RECIPIENT,
      maxSendsPerHour: 20,
    });
  });

  afterEach(async () => {
    await server.close();
  });

  describe('send/success', () => {
    it('resolves with {ok:true, timestamp} and posts correct body', async () => {
      const result = await client.send('hello');
      expect(result.ok).toBe(true);
      expect(typeof result.timestamp).toBe('number');
      expect(server.sent).toHaveLength(1);
      expect(server.sent[0]).toMatchObject({
        message: 'hello',
        number: SENDER,
        recipients: [RECIPIENT],
      });
    });
  });

  describe('send/non-2xx throws', () => {
    it('rejects with Error containing "signal-cli 500" on server error', async () => {
      // Extend server to return 500 for the next send via statusOverride
      server.statusOverride = 500;
      await expect(client.send('x')).rejects.toThrow('signal-cli 500');
    });
  });

  describe('send/timeout', () => {
    it('rejects with AbortError-like error within 100ms when server is slow', async () => {
      server.delayMs = 2000;
      const fastClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 20,
        timeoutMs: 50,
      });
      const start = Date.now();
      await expect(fastClient.send('x')).rejects.toThrow();
      expect(Date.now() - start).toBeLessThan(200);
    });
  });

  describe('send/cap', () => {
    it('returns {ok:false, reason:"rate-cap"} when cap exceeded (no HTTP)', async () => {
      const cappedClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 2,
      });
      await cappedClient.send('a');
      await cappedClient.send('b');
      const result = await cappedClient.send('c');
      expect(result).toEqual({ ok: false, reason: 'rate-cap' });
      // Only 2 HTTP requests were made
      expect(server.sent).toHaveLength(2);
    });

    it('bypassCap:true still sends even when cap is reached', async () => {
      const cappedClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 1,
      });
      await cappedClient.send('a');
      const result = await cappedClient.send('heartbeat', { bypassCap: true });
      expect(result.ok).toBe(true);
      expect(server.sent).toHaveLength(2);
    });

    it('sendsThisHour() returns current count', async () => {
      const cappedClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 10,
      });
      expect(cappedClient.sendsThisHour()).toBe(0);
      await cappedClient.send('a');
      await cappedClient.send('b');
      expect(cappedClient.sendsThisHour()).toBe(2);
    });
  });

  describe('receive/empty', () => {
    it('returns [] when server queue is empty', async () => {
      const result = await client.receive();
      expect(result).toEqual([]);
    });
  });

  describe('receive/drains', () => {
    it('returns queued envelopes in order and drains the queue', async () => {
      server.received.push({ envelope: { source: SENDER, dataMessage: { message: 'snooze rh 4h' } } });
      server.received.push({ envelope: { source: SENDER, dataMessage: { message: 'snooze all 1h' } } });
      const result = await client.receive();
      expect(result).toHaveLength(2);
      expect(result[0].envelope.dataMessage.message).toBe('snooze rh 4h');
      expect(result[1].envelope.dataMessage.message).toBe('snooze all 1h');
      // Queue drained
      const result2 = await client.receive();
      expect(result2).toEqual([]);
    });
  });

  describe('accounts', () => {
    it('returns account numbers array from /v1/accounts', async () => {
      const result = await client.accounts();
      expect(Array.isArray(result)).toBe(true);
      expect(result).toContain('+15551234567');
    });
  });

  describe('no-full-number-in-log', () => {
    it('does not log full sender or recipient phone numbers', async () => {
      const logLines = [];
      const logger = {
        info: (...args) => logLines.push(args.join(' ')),
        warn: (...args) => logLines.push(args.join(' ')),
        error: (...args) => logLines.push(args.join(' ')),
      };
      const trackedClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 20,
        logger,
      });
      await trackedClient.send('test message');
      for (const line of logLines) {
        expect(line).not.toContain(SENDER);
        expect(line).not.toContain(RECIPIENT);
      }
      // Confirm something was logged
      expect(logLines.length).toBeGreaterThan(0);
    });
  });
});
