'use strict';

// Phase 44 Plan-02: signal_outbound DAO unit tests.
// Mirror test/capture-db.test.js pool-mock pattern.

const { initDb, insertOutbound, selectRecentByRecipient } = require('../src/outbound-db');

describe('outbound-db', () => {
  let pool;

  beforeEach(() => {
    pool = { query: jest.fn().mockResolvedValue({ rows: [], rowCount: 0 }) };
  });

  test('initDb issues CREATE EXTENSION + CREATE TABLE + 2 idempotent ALTERs + 3 CREATE INDEX + Phase 50 ALTER + partial INDEX (9 total)', async () => {
    await initDb(pool);
    expect(pool.query).toHaveBeenCalledTimes(9);
    const sqls = pool.query.mock.calls.map((c) => c[0]);
    expect(sqls[0]).toMatch(/CREATE EXTENSION IF NOT EXISTS pgcrypto/);
    expect(sqls[1]).toMatch(/CREATE TABLE IF NOT EXISTS signal_outbound/);
    // 2026-05-23 hotfix: idempotent ALTER to migrate older hosts where the
    // FK columns were created as `uuid` (rejected ULID/hex ids at write time).
    expect(sqls[2]).toMatch(/ALTER TABLE signal_outbound ALTER COLUMN related_capture_id TYPE text/);
    expect(sqls[3]).toMatch(/ALTER TABLE signal_outbound ALTER COLUMN related_draft_id TYPE text/);
    expect(sqls[4]).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_outbound_tenant_sent/);
    expect(sqls[5]).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_outbound_recipient_sent/);
    expect(sqls[6]).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_outbound_intent/);
    // Phase 50 Plan-01 D-02: Signal-native msg ts column + partial index for inbound quote resolution.
    expect(sqls[7]).toMatch(/ALTER TABLE signal_outbound ADD COLUMN IF NOT EXISTS signal_msg_ts bigint/);
    expect(sqls[8]).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_outbound_msg_ts ON signal_outbound \(signal_msg_ts\) WHERE signal_msg_ts IS NOT NULL/);
  });

  test('initDb is idempotent: second invocation issues same 9 queries (Phase 50 IF NOT EXISTS semantics)', async () => {
    await initDb(pool);
    await initDb(pool);
    expect(pool.query).toHaveBeenCalledTimes(18);
    const secondAllSql = pool.query.mock.calls.slice(9).map((c) => c[0]).join('\n');
    expect(secondAllSql).toMatch(/ALTER TABLE signal_outbound ADD COLUMN IF NOT EXISTS signal_msg_ts bigint/);
    expect(secondAllSql).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_outbound_msg_ts/);
  });

  test('Plan 50-02: insertOutbound with signal_msg_ts writes it as $11 + signal_msg_ts column appears in INSERT', async () => {
    const row = {
      tenant_id: 'mossrock',
      sent_at: new Date(),
      recipient_e164: '+15551234567',
      intent: 'send_commit_outcome_ack',
      body: 'committed.',
      source_module: 'outbound-confirm.js',
      signal_msg_ts: 1779562666675,
    };
    const res = await insertOutbound(pool, row);
    expect(res).toEqual({ ok: true });
    const [sql, params] = pool.query.mock.calls[0];
    expect(sql).toMatch(/signal_msg_ts/);
    expect(sql).toMatch(/VALUES \(\$1, \$2, \$3, \$4, \$5, \$6::jsonb, \$7, \$8, \$9, \$10, \$11\)/);
    expect(params).toHaveLength(11);
    expect(params[10]).toBe(1779562666675);
  });

  test('Plan 50-02: insertOutbound without signal_msg_ts writes NULL in $11 (back-compat — ~14 callers)', async () => {
    const row = {
      tenant_id: 'mossrock',
      sent_at: new Date(),
      recipient_e164: '+1',
      intent: 'convo_reply',
      body: 'b',
      source_module: 'capture.js',
      // signal_msg_ts intentionally omitted
    };
    const res = await insertOutbound(pool, row);
    expect(res).toEqual({ ok: true });
    const [, params] = pool.query.mock.calls[0];
    expect(params).toHaveLength(11);
    expect(params[10]).toBeNull();
  });

  test('Plan 50-02: insertOutbound with signal_msg_ts=null writes NULL', async () => {
    const row = {
      tenant_id: 'mossrock',
      sent_at: new Date(),
      recipient_e164: '+1',
      intent: 'convo_reply',
      body: 'b',
      source_module: 'capture.js',
      signal_msg_ts: null,
    };
    await insertOutbound(pool, row);
    const [, params] = pool.query.mock.calls[0];
    expect(params[10]).toBeNull();
  });

  test('initDb CREATE TABLE uses text for related_*_id (ULID/hex compat per 2026-05-23 hotfix)', async () => {
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
    expect(tableSql).toMatch(/related_capture_id\s+text/);
    expect(tableSql).toMatch(/related_draft_id\s+text/);
  });

  test('insertOutbound issues one parameterised INSERT with $1..$11 in D-12 + Plan 50-02 column order', async () => {
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
    expect(sql).toMatch(/\(tenant_id, sent_at, recipient_e164, intent, body, attachments,\s*source_module, source_line, related_capture_id, related_draft_id, signal_msg_ts\)/);
    expect(sql).toMatch(/VALUES \(\$1, \$2, \$3, \$4, \$5, \$6::jsonb, \$7, \$8, \$9, \$10, \$11\)/);
    expect(params).toHaveLength(11);
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
    expect(params[10]).toBeNull(); // signal_msg_ts omitted -> NULL
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
