'use strict';

const { initDb, insertCapture, markExpiredOlderThan } = require('../src/capture-db');

describe('capture-db', () => {
  let pool;

  beforeEach(() => {
    pool = { query: jest.fn().mockResolvedValue({ rows: [], rowCount: 0 }) };
  });

  test('initDb issues CREATE TABLE + 2 CREATE INDEX + 3 ALTER TABLE ADD COLUMN IF NOT EXISTS (no create_hypertable)', async () => {
    await initDb(pool);
    expect(pool.query).toHaveBeenCalledTimes(6);
    const sql0 = pool.query.mock.calls[0][0];
    expect(sql0).toMatch(/CREATE TABLE IF NOT EXISTS signal_capture/);
    const sql1 = pool.query.mock.calls[1][0];
    expect(sql1).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_capture_sender_time/);
    const sql2 = pool.query.mock.calls[2][0];
    expect(sql2).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_capture_expired/);
    // Phase 37 D-14/D-15: three new nullable columns idempotently added.
    const allSql = pool.query.mock.calls.map((c) => c[0]).join('\n');
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS group_id text/);
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS farmos_person text/);
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS reply_target_kind text/);
    // Must NOT call create_hypertable (regular table per RESEARCH Open Q #1)
    expect(allSql).not.toMatch(/create_hypertable/);
  });

  test('initDb is idempotent — second invocation also issues 6 queries with same shape', async () => {
    await initDb(pool);
    await initDb(pool);
    expect(pool.query).toHaveBeenCalledTimes(12);
    const secondAllSql = pool.query.mock.calls.slice(6).map((c) => c[0]).join('\n');
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS group_id text/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS farmos_person text/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS reply_target_kind text/);
  });

  test('insertCapture calls pool.query once with 13 parameterized placeholders; row.id first, three new fields last', async () => {
    const row = {
      id: 'ulid-test-01',
      captured_at: new Date('2026-04-27T12:00:00Z'),
      sender: '+15551234567',
      message_type: 'text',
      raw_text: 'hello',
      attachment_paths: [],
      transcript: null,
      llm_session_tag: null,
      llm_reply: null,
      degraded: false,
    };
    await insertCapture(pool, row);
    expect(pool.query).toHaveBeenCalledTimes(1);
    const [sql, params] = pool.query.mock.calls[0];
    expect(sql).toMatch(/VALUES \(\$1, \$2, \$3, \$4, \$5, \$6, \$7, \$8, \$9, \$10, \$11, \$12, \$13\)/);
    expect(params).toHaveLength(13);
    expect(params[0]).toBe('ulid-test-01');   // id first
    expect(params[9]).toBe(false);             // degraded
    // Phase 37: three new fields default to null when row omits them.
    expect(params[10]).toBeNull();             // group_id
    expect(params[11]).toBeNull();             // farmos_person
    expect(params[12]).toBeNull();             // reply_target_kind
  });

  test('insertCapture writes provided group_id, farmos_person, reply_target_kind at positions 11..13', async () => {
    const row = {
      id: 'ulid-test-02',
      captured_at: new Date('2026-04-27T12:00:00Z'),
      sender: '+15551234567',
      message_type: 'text',
      raw_text: 'hello group',
      attachment_paths: [],
      transcript: null,
      llm_session_tag: null,
      llm_reply: null,
      degraded: false,
      group_id: 'ABC=',
      farmos_person: 'f2',
      reply_target_kind: 'group',
    };
    await insertCapture(pool, row);
    const [, params] = pool.query.mock.calls[0];
    expect(params[10]).toBe('ABC=');
    expect(params[11]).toBe('f2');
    expect(params[12]).toBe('group');
  });

  test('insertCapture SQL column list includes group_id, farmos_person, reply_target_kind', async () => {
    const row = {
      id: 'x', captured_at: new Date(), sender: '+1', message_type: 'text',
      raw_text: null, attachment_paths: [], transcript: null,
      llm_session_tag: null, llm_reply: null, degraded: false,
    };
    await insertCapture(pool, row);
    const [sql] = pool.query.mock.calls[0];
    expect(sql).toMatch(/group_id, farmos_person, reply_target_kind/);
  });

  test('insertCapture rejects when pool.query rejects', async () => {
    pool.query.mockRejectedValue(new Error('db error'));
    const row = {
      id: 'x', captured_at: new Date(), sender: '+1', message_type: 'text',
      raw_text: null, attachment_paths: [], transcript: null,
      llm_session_tag: null, llm_reply: null, degraded: false,
    };
    await expect(insertCapture(pool, row)).rejects.toThrow('db error');
  });

  test('markExpiredOlderThan calls UPDATE with captured_at < cutoff and expired=false; returns rowCount', async () => {
    pool.query.mockResolvedValue({ rowCount: 3 });
    const ageMs = 30 * 86400 * 1000;
    const result = await markExpiredOlderThan(pool, ageMs);
    expect(pool.query).toHaveBeenCalledTimes(1);
    const [sql, params] = pool.query.mock.calls[0];
    expect(sql).toMatch(/UPDATE signal_capture SET expired = true/);
    expect(sql).toMatch(/WHERE captured_at < \$1 AND expired = false/);
    expect(params).toHaveLength(1);
    expect(params[0]).toBeInstanceOf(Date);
    expect(result).toEqual({ rowCount: 3 });
  });
});
