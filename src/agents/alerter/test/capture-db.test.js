'use strict';

const { initDb, insertCapture, markExpiredOlderThan } = require('../src/capture-db');

describe('capture-db', () => {
  let pool;

  beforeEach(() => {
    pool = { query: jest.fn().mockResolvedValue({ rows: [], rowCount: 0 }) };
  });

  test('initDb issues CREATE TABLE + 2 CREATE INDEX + 12 ALTER TABLE ADD COLUMN IF NOT EXISTS + 1 CREATE VIEW (no create_hypertable)', async () => {
    await initDb(pool);
    // 1 CREATE TABLE + 2 CREATE INDEX + 3 Phase 37 ALTERs + 5 backlog-999.53 ALTERs
    // + 1 Phase 44 D-04 ALTER (extraction_gate) + 3 Phase 50 Plan-01 ALTERs + 1 CREATE VIEW = 16
    expect(pool.query).toHaveBeenCalledTimes(16);
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
    // Backlog 999.53: 5 token/model cols + per-day cost view.
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS input_tokens int/);
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS output_tokens int/);
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS cache_creation_input_tokens int/);
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS cache_read_input_tokens int/);
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS model text/);
    // Phase 44 Plan-04 D-04: event-gate audit column (VARCHAR(32) verbatim per locked decision).
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS extraction_gate VARCHAR\(32\)/);
    // Phase 50 Plan-01: three nullable columns for Signal-native quote threading.
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS signal_msg_ts bigint/);
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS quote_msg_ts bigint/);
    expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS quote_author_e164 text/);
    expect(allSql).toMatch(/CREATE OR REPLACE VIEW v_llm_cost_daily/);
    // Must NOT call create_hypertable (regular table per RESEARCH Open Q #1)
    expect(allSql).not.toMatch(/create_hypertable/);
  });

  test('initDb is idempotent: second invocation also issues 16 queries with same shape', async () => {
    await initDb(pool);
    await initDb(pool);
    expect(pool.query).toHaveBeenCalledTimes(32);
    const secondAllSql = pool.query.mock.calls.slice(16).map((c) => c[0]).join('\n');
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS group_id text/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS farmos_person text/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS reply_target_kind text/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS input_tokens int/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS output_tokens int/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS cache_creation_input_tokens int/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS cache_read_input_tokens int/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS model text/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS signal_msg_ts bigint/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS quote_msg_ts bigint/);
    expect(secondAllSql).toMatch(/ADD COLUMN IF NOT EXISTS quote_author_e164 text/);
    expect(secondAllSql).toMatch(/CREATE OR REPLACE VIEW v_llm_cost_daily/);
  });

  // Phase 50 Plan-04: extend insertCapture signature with three new fields.
  // Back-compat: callers that omit these fields still succeed; columns store NULL.
  test('Plan 50-04: insertCapture omitting signal_msg_ts/quote_* still succeeds, params 14..16 are null', async () => {
    const row = {
      id: 'ulid-p50-04-bc', captured_at: new Date(), sender: '+1', message_type: 'text',
      raw_text: null, attachment_paths: [], transcript: null,
      llm_session_tag: null, llm_reply: null, degraded: false,
    };
    await insertCapture(pool, row);
    const [sql, params] = pool.query.mock.calls[0];
    expect(sql).toMatch(/signal_msg_ts/);
    expect(sql).toMatch(/quote_msg_ts/);
    expect(sql).toMatch(/quote_author_e164/);
    expect(params).toHaveLength(16);
    expect(params[13]).toBeNull();   // signal_msg_ts
    expect(params[14]).toBeNull();   // quote_msg_ts
    expect(params[15]).toBeNull();   // quote_author_e164
  });

  test('Plan 50-04: insertCapture writes provided signal_msg_ts + quote_msg_ts + quote_author_e164 at positions 14..16', async () => {
    const row = {
      id: 'ulid-p50-04-q', captured_at: new Date(), sender: '+59892893012', message_type: 'text',
      raw_text: 'EDIT block 260415_LIMA_1', attachment_paths: [], transcript: null,
      llm_session_tag: null, llm_reply: null, degraded: false,
      signal_msg_ts: 1779562666675,
      quote_msg_ts: 1779560111000,
      quote_author_e164: '+59891840205',
    };
    await insertCapture(pool, row);
    const [, params] = pool.query.mock.calls[0];
    expect(params).toHaveLength(16);
    expect(params[13]).toBe(1779562666675);
    expect(params[14]).toBe(1779560111000);
    expect(params[15]).toBe('+59891840205');
  });

  test('insertCapture calls pool.query once with 16 parameterized placeholders (13 base + 3 Phase 50)', async () => {
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
    expect(sql).toMatch(/VALUES \(\$1, \$2, \$3, \$4, \$5, \$6, \$7, \$8, \$9, \$10, \$11, \$12, \$13, \$14, \$15, \$16\)/);
    expect(params).toHaveLength(16);
    expect(params[0]).toBe('ulid-test-01');   // id first
    expect(params[9]).toBe(false);             // degraded
    // Phase 37: three new fields default to null when row omits them.
    expect(params[10]).toBeNull();             // group_id
    expect(params[11]).toBeNull();             // farmos_person
    expect(params[12]).toBeNull();             // reply_target_kind
    // Phase 50 Plan-04: three quote-thread fields default to null.
    expect(params[13]).toBeNull();             // signal_msg_ts
    expect(params[14]).toBeNull();             // quote_msg_ts
    expect(params[15]).toBeNull();             // quote_author_e164
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
