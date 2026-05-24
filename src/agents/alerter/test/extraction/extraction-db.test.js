'use strict';

const {
  initDb,
  insertDraft,
  getInFlightForSender,
  getDraftsForCapture,
  updateDraftStatus,
  advanceAskbackTurn,
  expireIdle,
  computeDraftId,
} = require('../../src/extraction/extraction-db');

describe('extraction-db', () => {
  let pool;

  beforeEach(() => {
    pool = { query: jest.fn().mockResolvedValue({ rows: [], rowCount: 0 }) };
  });

  describe('initDb', () => {
    test('issues exactly 6 queries: CREATE TABLE + 2 CREATE INDEX + 3 ALTER TABLE ADD COLUMN IF NOT EXISTS', async () => {
      await initDb(pool);
      expect(pool.query).toHaveBeenCalledTimes(6);
      const sql0 = pool.query.mock.calls[0][0];
      expect(sql0).toMatch(/CREATE TABLE IF NOT EXISTS signal_draft/);
      // Required columns from CONTEXT D-02/D-02a/D-02b
      expect(sql0).toMatch(/id\s+text PRIMARY KEY/);
      expect(sql0).toMatch(/sender_e164\s+text NOT NULL/);
      expect(sql0).toMatch(/source_capture_ids\s+text\[\]/);
      expect(sql0).toMatch(/status\s+text NOT NULL/);
      expect(sql0).toMatch(/askback_turns\s+integer NOT NULL DEFAULT 0/);
      expect(sql0).toMatch(/draft_json\s+jsonb/);
      expect(sql0).toMatch(/per_field_confidence\s+jsonb/);

      const sql1 = pool.query.mock.calls[1][0];
      expect(sql1).toMatch(/CREATE INDEX IF NOT EXISTS idx_signal_draft_sender_status/);

      const sql2 = pool.query.mock.calls[2][0];
      expect(sql2).toMatch(/CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_draft_in_flight_per_sender/);

      const sql3 = pool.query.mock.calls[3][0];
      expect(sql3).toMatch(/ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS needs_review_reason text/);

      // Phase 49 Plan 01: discarded_reason + discarded_at for the discard-drafts script.
      const sql4 = pool.query.mock.calls[4][0];
      expect(sql4).toMatch(/ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS discarded_reason text/);
      const sql5 = pool.query.mock.calls[5][0];
      expect(sql5).toMatch(/ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS discarded_at timestamptz/);
    });

    test('partial unique index restricts to in-flight statuses (D-02c)', async () => {
      await initDb(pool);
      const sql2 = pool.query.mock.calls[2][0];
      expect(sql2).toMatch(/WHERE status IN \('pending','awaiting_farmer'\)/);
    });

    test('is idempotent -- second invocation yields 12 total queries with same shape', async () => {
      await initDb(pool);
      await initDb(pool);
      expect(pool.query).toHaveBeenCalledTimes(12);
      const secondAllSql = pool.query.mock.calls.slice(6).map((c) => c[0]).join('\n');
      expect(secondAllSql).toMatch(/CREATE TABLE IF NOT EXISTS signal_draft/);
      expect(secondAllSql).toMatch(/idx_signal_draft_in_flight_per_sender/);
      expect(secondAllSql).toMatch(/discarded_reason text/);
      expect(secondAllSql).toMatch(/discarded_at timestamptz/);
    });

    test('Phase 49: discard columns added idempotently with IF NOT EXISTS', async () => {
      await initDb(pool);
      const allSql = pool.query.mock.calls.map((c) => c[0]).join('\n');
      expect(allSql).toMatch(/ADD COLUMN IF NOT EXISTS discarded_reason text/);
      expect(allSql).toMatch(/ADD COLUMN IF NOT EXISTS discarded_at timestamptz/);
    });
  });

  describe('computeDraftId', () => {
    test('is deterministic regardless of input order (D-02a replay-safe)', () => {
      expect(computeDraftId(['a', 'b', 'c'])).toBe(computeDraftId(['c', 'b', 'a']));
    });

    test('differs for different sets', () => {
      expect(computeDraftId(['a', 'b'])).not.toBe(computeDraftId(['a', 'b', 'c']));
    });

    test('emits 64-char hex (sha256)', () => {
      const id = computeDraftId(['cap-1']);
      expect(id).toMatch(/^[0-9a-f]{64}$/);
    });

    test('draftIndex=undefined|0 yields the same legacy id (back-compat)', () => {
      const legacy = computeDraftId(['cap-1', 'cap-2']);
      expect(computeDraftId(['cap-1', 'cap-2'], 0)).toBe(legacy);
      expect(computeDraftId(['cap-1', 'cap-2'], undefined)).toBe(legacy);
    });

    test('Plan 08 batch mode: non-zero draftIndex disambiguates ids for same captures', () => {
      const a0 = computeDraftId(['cap-1'], 0);
      const a1 = computeDraftId(['cap-1'], 1);
      const a2 = computeDraftId(['cap-1'], 2);
      expect(a0).not.toBe(a1);
      expect(a1).not.toBe(a2);
      expect(a0).not.toBe(a2);
    });
  });

  describe('insertDraft', () => {
    test('returns {ok:true, id} on success', async () => {
      pool.query.mockResolvedValueOnce({ rows: [], rowCount: 1 });
      const row = {
        id: 'abc',
        sender_e164: '+15551234567',
        source_capture_ids: ['cap-1'],
        status: 'pending',
        draft_json: { foo: 'bar' },
      };
      const res = await insertDraft(pool, row);
      expect(res).toEqual({ ok: true, id: 'abc' });
      expect(pool.query).toHaveBeenCalledTimes(1);
      const [sql, params] = pool.query.mock.calls[0];
      expect(sql).toMatch(/INSERT INTO signal_draft/);
      expect(params[0]).toBe('abc');
    });

    test('returns {ok:false, reason:"in_flight_conflict"} on Postgres 23505 unique violation (D-02c)', async () => {
      const e = new Error('duplicate key value violates unique constraint');
      e.code = '23505';
      pool.query.mockRejectedValueOnce(e);
      const res = await insertDraft(pool, {
        id: 'abc',
        sender_e164: '+15551234567',
        source_capture_ids: ['cap-1'],
        status: 'pending',
      });
      expect(res).toEqual({ ok: false, reason: 'in_flight_conflict' });
    });

    test('returns {ok:false, reason:<msg>} on other errors (never-throw)', async () => {
      pool.query.mockRejectedValueOnce(new Error('connection refused'));
      const res = await insertDraft(pool, {
        id: 'abc',
        sender_e164: '+15551234567',
        source_capture_ids: ['cap-1'],
        status: 'pending',
      });
      expect(res.ok).toBe(false);
      expect(res.reason).toBe('connection refused');
    });
  });

  describe('getInFlightForSender', () => {
    test('returns null when no rows match', async () => {
      pool.query.mockResolvedValueOnce({ rows: [], rowCount: 0 });
      const r = await getInFlightForSender(pool, '+15551234567');
      expect(r).toBeNull();
      const [sql, params] = pool.query.mock.calls[0];
      expect(sql).toMatch(/SELECT \* FROM signal_draft/);
      expect(sql).toMatch(/sender_e164 = \$1/);
      expect(sql).toMatch(/status IN \('pending','awaiting_farmer'\)/);
      expect(params).toEqual(['+15551234567']);
    });

    test('returns the row when one matches', async () => {
      const row = { id: 'abc', sender_e164: '+1', status: 'awaiting_farmer' };
      pool.query.mockResolvedValueOnce({ rows: [row], rowCount: 1 });
      const r = await getInFlightForSender(pool, '+1');
      expect(r).toEqual(row);
    });
  });

  describe('updateDraftStatus', () => {
    test('issues UPDATE with status + updated_at = now()', async () => {
      pool.query.mockResolvedValueOnce({ rows: [], rowCount: 1 });
      const res = await updateDraftStatus(pool, 'abc', 'awaiting_farmer');
      expect(res).toEqual({ ok: true, rowCount: 1 });
      const [sql, params] = pool.query.mock.calls[0];
      expect(sql).toMatch(/UPDATE signal_draft/);
      expect(sql).toMatch(/SET status = \$2/);
      expect(sql).toMatch(/updated_at = now\(\)/);
      expect(sql).toMatch(/WHERE id = \$1/);
      expect(params).toEqual(['abc', 'awaiting_farmer']);
    });

    test('accepts optional jsonb extras and includes them in SET clause', async () => {
      pool.query.mockResolvedValueOnce({ rows: [], rowCount: 1 });
      await updateDraftStatus(pool, 'abc', 'needs_review', {
        needs_review_reason: 'max askback turns',
      });
      const [sql, params] = pool.query.mock.calls[0];
      expect(sql).toMatch(/needs_review_reason/);
      expect(params).toContain('max askback turns');
    });
  });

  describe('advanceAskbackTurn', () => {
    test('increments askback_turns and returns new count via RETURNING', async () => {
      pool.query.mockResolvedValueOnce({ rows: [{ askback_turns: 2 }], rowCount: 1 });
      const r = await advanceAskbackTurn(pool, 'abc');
      expect(r).toEqual({ ok: true, askback_turns: 2 });
      const [sql, params] = pool.query.mock.calls[0];
      expect(sql).toMatch(/UPDATE signal_draft/);
      expect(sql).toMatch(/askback_turns = askback_turns \+ 1/);
      expect(sql).toMatch(/RETURNING askback_turns/);
      expect(params).toEqual(['abc']);
    });
  });

  describe('getDraftsForCapture (Phase 54 Plan 02)', () => {
    test('queries via source_capture_ids @> ARRAY[$1] ordered ASC', async () => {
      const rows = [{ id: 'd1' }, { id: 'd2' }, { id: 'd3' }];
      pool.query.mockResolvedValueOnce({ rows, rowCount: rows.length });
      const r = await getDraftsForCapture(pool, 'cap-1');
      expect(r).toEqual(rows);
      const [sql, params] = pool.query.mock.calls[0];
      expect(sql).toMatch(/SELECT \* FROM signal_draft/);
      expect(sql).toMatch(/source_capture_ids @> ARRAY\[\$1\]::text\[\]/);
      expect(sql).toMatch(/ORDER BY created_at ASC/);
      expect(params).toEqual(['cap-1']);
    });

    test('returns [] on query error (never-throw)', async () => {
      pool.query.mockRejectedValueOnce(new Error('boom'));
      const r = await getDraftsForCapture(pool, 'cap-x');
      expect(r).toEqual([]);
    });
  });

  describe('expireIdle', () => {
    test('updates in-flight rows older than gapMinutes to expired', async () => {
      pool.query.mockResolvedValueOnce({ rows: [], rowCount: 4 });
      const r = await expireIdle(pool, 30);
      expect(r).toEqual({ ok: true, rowCount: 4 });
      const [sql, params] = pool.query.mock.calls[0];
      expect(sql).toMatch(/UPDATE signal_draft/);
      expect(sql).toMatch(/SET status = 'expired'/);
      expect(sql).toMatch(/status IN \('pending','awaiting_farmer'\)/);
      expect(sql).toMatch(/updated_at < now\(\) - \(\$1 \|\| ' minutes'\)::interval/);
      expect(params).toEqual([30]);
    });
  });
});
