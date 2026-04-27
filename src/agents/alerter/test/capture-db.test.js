'use strict';

const { initDb, insertCapture, markExpiredOlderThan } = require('../src/capture-db');

describe('capture-db', () => {
  let pool;

  beforeEach(() => {
    pool = { query: jest.fn().mockResolvedValue({ rows: [], rowCount: 0 }) };
  });

  test('initDb issues CREATE TABLE IF NOT EXISTS signal_capture and two CREATE INDEX calls (no create_hypertable)', async () => {
    await initDb(pool);
    expect(pool.query).toHaveBeenCalledTimes(3);
    const sql0 = pool.query.mock.calls[0][0];
    expect(sql0).toMatch(/CREATE TABLE IF NOT EXISTS signal_capture/);
    const sql1 = pool.query.mock.calls[1][0];
    expect(sql1).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_capture_sender_time/);
    const sql2 = pool.query.mock.calls[2][0];
    expect(sql2).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_capture_expired/);
    // Must NOT call create_hypertable (regular table per RESEARCH Open Q #1)
    const allSql = pool.query.mock.calls.map((c) => c[0]).join('\n');
    expect(allSql).not.toMatch(/create_hypertable/);
  });

  test('insertCapture calls pool.query once with 10 parameterized placeholders; row.id first, row.degraded last', async () => {
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
    expect(sql).toMatch(/VALUES \(\$1, \$2, \$3, \$4, \$5, \$6, \$7, \$8, \$9, \$10\)/);
    expect(params).toHaveLength(10);
    expect(params[0]).toBe('ulid-test-01');   // id first
    expect(params[9]).toBe(false);             // degraded last
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
