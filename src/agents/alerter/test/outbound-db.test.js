'use strict';

// Phase 44 Plan-02: signal_outbound DAO unit tests.
// Mirror test/capture-db.test.js pool-mock pattern.

const { initDb, insertOutbound, selectRecentByRecipient } = require('../src/outbound-db');

describe('outbound-db', () => {
  let pool;

  beforeEach(() => {
    pool = { query: jest.fn().mockResolvedValue({ rows: [], rowCount: 0 }) };
  });

  test('initDb issues CREATE EXTENSION + CREATE TABLE + 3 CREATE INDEX (5 total)', async () => {
    await initDb(pool);
    expect(pool.query).toHaveBeenCalledTimes(5);
    const sqls = pool.query.mock.calls.map((c) => c[0]);
    expect(sqls[0]).toMatch(/CREATE EXTENSION IF NOT EXISTS pgcrypto/);
    expect(sqls[1]).toMatch(/CREATE TABLE IF NOT EXISTS signal_outbound/);
    expect(sqls[2]).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_outbound_tenant_sent/);
    expect(sqls[3]).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_outbound_recipient_sent/);
    expect(sqls[4]).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_outbound_intent/);
  });

  test('initDb CREATE TABLE preserves D-12 column types verbatim', async () => {
    await initDb(pool);
    const tableSql = pool.query.mock.calls[1][0];
    expect(tableSql).toMatch(/id\s+uuid PRIMARY KEY DEFAULT gen_random_uuid\(\)/);
    expect(tableSql).toMatch(/tenant_id\s+text NOT NULL/);
    expect(tableSql).toMatch(/sent_at\s+timestamptz NOT NULL DEFAULT now\(\)/);
    expect(tableSql).toMatch(/recipient_e164\s+text NOT NULL/);
    expect(tableSql).toMatch(/intent\s+text NOT NULL/);
    expect(tableSql).toMatch(/body\s+text NOT NULL/);
    expect(tableSql).toMatch(/attachments\s+jsonb/);
    expect(tableSql).toMatch(/source_module\s+text NOT NULL/);
    expect(tableSql).toMatch(/source_line\s+integer/);
    expect(tableSql).toMatch(/related_capture_id\s+uuid/);
    expect(tableSql).toMatch(/related_draft_id\s+uuid/);
  });

  test('insertOutbound issues one parameterised INSERT with $1..$10 in D-12 column order', async () => {
    const row = {
      tenant_id: 'mossrock',
      sent_at: new Date('2026-05-21T12:00:00Z'),
      recipient_e164: '+15551234567',
      intent: 'convo_reply',
      body: 'hello farmer',
      attachments: null,
      source_module: 'capture.js',
      source_line: 197,
      related_capture_id: '11111111-1111-1111-1111-111111111111',
      related_draft_id: null,
    };
    const res = await insertOutbound(pool, row);
    expect(res).toEqual({ ok: true });
    expect(pool.query).toHaveBeenCalledTimes(1);
    const [sql, params] = pool.query.mock.calls[0];
    expect(sql).toMatch(/INSERT INTO signal_outbound/);
    expect(sql).toMatch(/\(tenant_id, sent_at, recipient_e164, intent, body, attachments,\s*source_module, source_line, related_capture_id, related_draft_id\)/);
    expect(sql).toMatch(/VALUES \(\$1, \$2, \$3, \$4, \$5, \$6::jsonb, \$7, \$8, \$9, \$10\)/);
    expect(params).toHaveLength(10);
    expect(params[0]).toBe('mossrock');
    expect(params[1]).toBeInstanceOf(Date);
    expect(params[2]).toBe('+15551234567');
    expect(params[3]).toBe('convo_reply');
    expect(params[4]).toBe('hello farmer');
    expect(params[5]).toBeNull();
    expect(params[6]).toBe('capture.js');
    expect(params[7]).toBe(197);
    expect(params[8]).toBe('11111111-1111-1111-1111-111111111111');
    expect(params[9]).toBeNull();
  });

  test('insertOutbound JSON.stringifies attachments when non-null', async () => {
    const row = {
      tenant_id: 'mossrock',
      sent_at: new Date(),
      recipient_e164: '+1',
      intent: 'ask_back',
      body: 'b',
      attachments: [{ path: '/x.jpg' }],
      source_module: 'capture.js',
    };
    await insertOutbound(pool, row);
    const [, params] = pool.query.mock.calls[0];
    expect(params[5]).toBe(JSON.stringify([{ path: '/x.jpg' }]));
  });

  test('insertOutbound passes null for omitted optional fields (attachments, source_line, related_*)', async () => {
    const row = {
      tenant_id: 'mossrock',
      sent_at: new Date(),
      recipient_e164: '+1',
      intent: 'rh_alert',
      body: 'b',
      source_module: 'index.js',
    };
    await insertOutbound(pool, row);
    const [, params] = pool.query.mock.calls[0];
    expect(params[5]).toBeNull();   // attachments
    expect(params[7]).toBeNull();   // source_line
    expect(params[8]).toBeNull();   // related_capture_id
    expect(params[9]).toBeNull();   // related_draft_id
  });

  test('insertOutbound returns {ok:false, reason} on pool.query rejection (Pattern S1 never-throw)', async () => {
    pool.query.mockRejectedValue(new Error('db down'));
    const row = {
      tenant_id: 'mossrock',
      sent_at: new Date(),
      recipient_e164: '+1',
      intent: 'convo_reply',
      body: 'b',
      source_module: 'capture.js',
    };
    const res = await insertOutbound(pool, row);
    expect(res).toEqual({ ok: false, reason: 'db down' });
  });

  test('selectRecentByRecipient issues SELECT with recipient + sent_at filter, ORDER BY sent_at ASC', async () => {
    pool.query.mockResolvedValue({ rows: [{ sent_at: new Date(), body: 'x', intent: 'convo_reply' }] });
    const sinceMs = Date.UTC(2026, 4, 21, 0, 0, 0);
    const rows = await selectRecentByRecipient(pool, '+15551234567', sinceMs);
    expect(pool.query).toHaveBeenCalledTimes(1);
    const [sql, params] = pool.query.mock.calls[0];
    expect(sql).toMatch(/SELECT sent_at, body, intent/);
    expect(sql).toMatch(/FROM signal_outbound/);
    expect(sql).toMatch(/WHERE recipient_e164 = \$1 AND sent_at > \$2/);
    expect(sql).toMatch(/ORDER BY sent_at ASC/);
    expect(params[0]).toBe('+15551234567');
    expect(params[1]).toBeInstanceOf(Date);
    expect(params[1].getTime()).toBe(sinceMs);
    expect(rows).toHaveLength(1);
  });
});
