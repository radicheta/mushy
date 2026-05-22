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

  describe('receive/ignore_attachments', () => {
    it('defaults to ignore_attachments=false', async () => {
      // Extend server to capture the last receive URL
      let capturedUrl = null;
      const origHandler = server._server;
      // Push a message so receive returns something parseable
      server.received.push({ envelope: { source: SENDER, dataMessage: { message: 'hi' } } });
      // We inspect via a spy: override server to record URL
      // Instead, check by using the query param via a custom receive call
      // The fake server drains received[] regardless of query params — we just need
      // to verify the URL shape by calling receive() and checking it doesn't throw.
      const result = await client.receive();
      expect(Array.isArray(result)).toBe(true);
    });

    it('receive() default URL contains ignore_attachments=false', async () => {
      // Use a custom server that captures the request URL
      const http = require('http');
      let receivedUrl = null;
      const spy = http.createServer((req, res) => {
        receivedUrl = req.url;
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end('[]');
      });
      await new Promise((resolve) => spy.listen(0, '127.0.0.1', resolve));
      const { port } = spy.address();
      const spyClient = createSignalClient({
        apiUrl: `http://127.0.0.1:${port}`,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 20,
      });
      await spyClient.receive();
      await new Promise((resolve) => spy.close(resolve));
      expect(receivedUrl).toContain('ignore_attachments=false');
    });

    it('receive({ ignoreAttachments: true }) sends ignore_attachments=true', async () => {
      const http = require('http');
      let receivedUrl = null;
      const spy = http.createServer((req, res) => {
        receivedUrl = req.url;
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end('[]');
      });
      await new Promise((resolve) => spy.listen(0, '127.0.0.1', resolve));
      const { port } = spy.address();
      const spyClient = createSignalClient({
        apiUrl: `http://127.0.0.1:${port}`,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 20,
      });
      await spyClient.receive({ ignoreAttachments: true });
      await new Promise((resolve) => spy.close(resolve));
      expect(receivedUrl).toContain('ignore_attachments=true');
    });
  });

  describe('fetchAttachment', () => {
    it('GETs /v1/attachments/{id} and returns a Buffer', async () => {
      const buf = await client.fetchAttachment('att-img-001');
      expect(Buffer.isBuffer(buf)).toBe(true);
      expect(buf.length).toBeGreaterThan(0);
      // Fake server returns [0x41, 0x42, 0x43] = "ABC"
      expect(buf.toString()).toBe('ABC');
    });

    it('throws on 404 response', async () => {
      await expect(client.fetchAttachment('not-found-sentinel')).rejects.toThrow('404');
    });
  });

  describe('Phase 37: send({to}) + defaultTarget + group recipient', () => {
    it('back-compat: no defaultTarget, recipient passed → recipients=[recipient]', async () => {
      const result = await client.send('hi');
      expect(result.ok).toBe(true);
      expect(server.sent[0]).toMatchObject({ recipients: [RECIPIENT] });
    });

    it('defaultTarget="+15551112222" (no recipient) → recipients=[phone]', async () => {
      const dtClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        defaultTarget: '+15551112222',
        maxSendsPerHour: 20,
      });
      await dtClient.send('hi');
      expect(server.sent[0]).toMatchObject({ recipients: ['+15551112222'] });
    });

    it('defaultTarget={groupId:"ABC="} → recipients=["group.ABC="]', async () => {
      const grpClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        defaultTarget: { groupId: 'ABC=' },
        maxSendsPerHour: 20,
      });
      await grpClient.send('hi');
      expect(server.sent[0]).toMatchObject({ recipients: ['group.ABC='] });
    });

    it('send("hi",{to:{groupId:"XYZ="}}) overrides defaultTarget', async () => {
      const grpClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        defaultTarget: { groupId: 'ABC=' },
        maxSendsPerHour: 20,
      });
      await grpClient.send('hi', { to: { groupId: 'XYZ=' } });
      expect(server.sent[0]).toMatchObject({ recipients: ['group.XYZ='] });
    });

    it('send("hi",{to:"+15553334444"}) overrides defaultTarget', async () => {
      await client.send('hi', { to: '+15553334444' });
      expect(server.sent[0]).toMatchObject({ recipients: ['+15553334444'] });
    });

    it('log line for group send includes "group:" prefix + first 8 chars of groupId', async () => {
      const logLines = [];
      const logger = {
        info: (...a) => logLines.push(a.join(' ')),
        warn: (...a) => logLines.push(a.join(' ')),
        error: (...a) => logLines.push(a.join(' ')),
      };
      const grpClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        defaultTarget: { groupId: 'ABCDEFGHIJKLMNOP=' },
        maxSendsPerHour: 20,
        logger,
      });
      await grpClient.send('hi');
      const sentLine = logLines.find((l) => l.includes('[signal] sent ->'));
      expect(sentLine).toBeDefined();
      expect(sentLine).toContain('group:ABCDEFGH');
      expect(sentLine).not.toContain('ABCDEFGHIJKLMNOP');
    });

    it('log line for DM send still uses maskNumber()', async () => {
      const logLines = [];
      const logger = {
        info: (...a) => logLines.push(a.join(' ')),
        warn: (...a) => logLines.push(a.join(' ')),
        error: (...a) => logLines.push(a.join(' ')),
      };
      const dmClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 20,
        logger,
      });
      await dmClient.send('hi');
      const sentLine = logLines.find((l) => l.includes('[signal] sent ->'));
      expect(sentLine).toBeDefined();
      expect(sentLine).not.toContain(RECIPIENT);
      // maskNumber('+15552222222') -> '+1XXXXXX2222' (first 2 + Xs + last 4)
      expect(sentLine).toMatch(/\+1X+2222/);
    });

    it('bypassCap option still works orthogonally to {to}', async () => {
      const cappedClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 1,
      });
      await cappedClient.send('a');
      const result = await cappedClient.send('hb', { bypassCap: true, to: '+15559998888' });
      expect(result.ok).toBe(true);
      expect(server.sent).toHaveLength(2);
      expect(server.sent[1]).toMatchObject({ recipients: ['+15559998888'] });
    });

    it('construction throws when neither defaultTarget nor recipient is set', () => {
      expect(() => createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        maxSendsPerHour: 20,
      })).toThrow(/defaultTarget or recipient is required/);
    });

    it('send throws on invalid target (empty object)', async () => {
      const badClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 20,
      });
      await expect(badClient.send('hi', { to: {} })).rejects.toThrow(/invalid send target/);
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

  describe('Phase 44 Plan-02: signal_outbound persistence hook (D-14 single hook)', () => {
    function makeFakeOutboundDb() {
      return {
        insertOutbound: jest.fn().mockResolvedValue({ ok: true }),
      };
    }
    function makeFakePool() {
      return { query: jest.fn() };
    }

    it('Test 1: send() with full opts triggers one insertOutbound with matching fields', async () => {
      const outboundDb = makeFakeOutboundDb();
      const pool = makeFakePool();
      const hookClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 20,
        outboundDb,
        pool,
        tenantId: 'mossrock',
      });
      const captureId = '11111111-2222-3333-4444-555555555555';
      const draftId = '99999999-8888-7777-6666-555555555555';
      const result = await hookClient.send('hello', {
        intent: 'rh_alert',
        relatedCaptureId: captureId,
        relatedDraftId: draftId,
        sourceModule: 'state.js',
      });
      expect(result.ok).toBe(true);
      expect(outboundDb.insertOutbound).toHaveBeenCalledTimes(1);
      const [poolArg, row] = outboundDb.insertOutbound.mock.calls[0];
      expect(poolArg).toBe(pool);
      expect(row).toMatchObject({
        tenant_id: 'mossrock',
        recipient_e164: RECIPIENT,
        intent: 'rh_alert',
        body: 'hello',
        source_module: 'state.js',
        related_capture_id: captureId,
        related_draft_id: draftId,
      });
      expect(row.sent_at).toBeInstanceOf(Date);
    });

    it('Test 2: send() WITHOUT intent logs warn and writes intent=unknown (Pitfall 3 shim)', async () => {
      const outboundDb = makeFakeOutboundDb();
      const pool = makeFakePool();
      const logLines = [];
      const logger = {
        info: (...a) => logLines.push(['info', a.join(' ')]),
        warn: (...a) => logLines.push(['warn', a.join(' ')]),
        error: (...a) => logLines.push(['error', a.join(' ')]),
      };
      const hookClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 20,
        outboundDb,
        pool,
        tenantId: 'mossrock',
        logger,
      });
      await hookClient.send('hi');
      const row = outboundDb.insertOutbound.mock.calls[0][1];
      expect(row.intent).toBe('unknown');
      const warned = logLines.some(([lvl, line]) => lvl === 'warn' && /intent/i.test(line));
      expect(warned).toBe(true);
    });

    it('Test 3: group send encodes recipient_e164 as "group:<id>" (prefix encoding — operator decision b)', async () => {
      const outboundDb = makeFakeOutboundDb();
      const pool = makeFakePool();
      const hookClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        defaultTarget: { groupId: 'GRPID12345=' },
        maxSendsPerHour: 20,
        outboundDb,
        pool,
        tenantId: 'mossrock',
      });
      await hookClient.send('hi', { intent: 'rh_alert' });
      const row = outboundDb.insertOutbound.mock.calls[0][1];
      expect(row.recipient_e164).toBe('group:GRPID12345=');
    });

    it('Test 4: insertOutbound returning {ok:false} warns but does NOT throw and send still returns ok', async () => {
      const outboundDb = {
        insertOutbound: jest.fn().mockResolvedValue({ ok: false, reason: 'db down' }),
      };
      const pool = makeFakePool();
      const logLines = [];
      const logger = {
        info: () => {},
        warn: (...a) => logLines.push(a.join(' ')),
        error: () => {},
      };
      const hookClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 20,
        outboundDb,
        pool,
        tenantId: 'mossrock',
        logger,
      });
      const result = await hookClient.send('hi', { intent: 'rh_alert' });
      expect(result.ok).toBe(true);
      expect(logLines.some((l) => /db down/.test(l) || /outbound/i.test(l))).toBe(true);
    });

    it('Test 4b: insertOutbound throwing is swallowed (defense in depth — never block send)', async () => {
      const outboundDb = {
        insertOutbound: jest.fn().mockRejectedValue(new Error('boom')),
      };
      const pool = makeFakePool();
      const hookClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 20,
        outboundDb,
        pool,
        tenantId: 'mossrock',
      });
      const result = await hookClient.send('hi', { intent: 'rh_alert' });
      expect(result.ok).toBe(true);
    });

    it('Test 5: rate-cap path skips insertOutbound (no send happened)', async () => {
      const outboundDb = makeFakeOutboundDb();
      const pool = makeFakePool();
      const cappedClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 1,
        outboundDb,
        pool,
        tenantId: 'mossrock',
      });
      await cappedClient.send('a', { intent: 'rh_alert' });
      const second = await cappedClient.send('b', { intent: 'rh_alert' });
      expect(second).toEqual({ ok: false, reason: 'rate-cap' });
      expect(outboundDb.insertOutbound).toHaveBeenCalledTimes(1);
    });

    it('Test 6: no outboundDb passed → factory still works (back-compat — existing tests rely on this)', async () => {
      const plainClient = createSignalClient({
        apiUrl: server.url,
        sender: SENDER,
        recipient: RECIPIENT,
        maxSendsPerHour: 20,
      });
      const result = await plainClient.send('hi', { intent: 'rh_alert' });
      expect(result.ok).toBe(true);
    });
  });
});
