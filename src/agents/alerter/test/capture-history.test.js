'use strict';

const { createCaptureHistory } = require('../src/capture-history');

describe('createCaptureHistory', () => {
  let pool;
  let history;

  beforeEach(() => {
    pool = {
      query: jest.fn().mockResolvedValue({
        rows: [
          { captured_at: new Date('2026-04-27T10:00:00Z'), raw_text: 'hi', transcript: null, message_type: 'text' },
        ],
        rowCount: 1,
      }),
    };
    history = createCaptureHistory({ pool });
  });

  test('selectRecentBySender issues SELECT with WHERE sender=$1 AND captured_at > $2 ORDER BY captured_at ASC; returns rows', async () => {
    const sinceMs = Date.now() - 24 * 3600 * 1000;
    const rows = await history.selectRecentBySender('+15551234567', sinceMs);
    expect(pool.query).toHaveBeenCalledTimes(1);
    const [sql, params] = pool.query.mock.calls[0];
    expect(sql).toMatch(/WHERE sender = \$1 AND captured_at > \$2/);
    expect(sql).toMatch(/ORDER BY captured_at ASC/);
    expect(rows).toHaveLength(1);
    expect(rows[0].raw_text).toBe('hi');
  });

  test('param 2 is a Date instance derived from sinceMs', async () => {
    const sinceMs = 1714200000000;
    await history.selectRecentBySender('+15551234567', sinceMs);
    const [, params] = pool.query.mock.calls[0];
    expect(params[0]).toBe('+15551234567');
    expect(params[1]).toBeInstanceOf(Date);
    expect(params[1].getTime()).toBe(sinceMs);
  });

  // Phase 44 Plan-05 Task 5.1 (D-18): outbound sibling query.
  describe('selectRecentOutboundByRecipient', () => {
    let outboundPool;
    let outboundHistory;

    beforeEach(() => {
      outboundPool = {
        query: jest.fn().mockResolvedValue({
          rows: [
            { sent_at: new Date('2026-05-20T10:00:00Z'), body: 'hello back', intent: 'convo_reply' },
          ],
          rowCount: 1,
        }),
      };
      outboundHistory = createCaptureHistory({ pool: outboundPool });
    });

    test('factory returns object containing selectRecentOutboundByRecipient', () => {
      expect(typeof outboundHistory.selectRecentOutboundByRecipient).toBe('function');
    });

    test('issues SELECT FROM signal_outbound WHERE recipient_e164 = $1 AND sent_at > $2 ORDER BY sent_at ASC', async () => {
      const sinceMs = Date.now() - 24 * 3600 * 1000;
      await outboundHistory.selectRecentOutboundByRecipient('+59891840205', sinceMs);
      expect(outboundPool.query).toHaveBeenCalledTimes(1);
      const [sql, params] = outboundPool.query.mock.calls[0];
      expect(sql).toMatch(/FROM signal_outbound/);
      expect(sql).toMatch(/recipient_e164 = \$1/);
      expect(sql).toMatch(/sent_at > \$2/);
      expect(sql).toMatch(/ORDER BY sent_at ASC/);
      expect(params[0]).toBe('+59891840205');
      expect(params[1]).toBeInstanceOf(Date);
      expect(params[1].getTime()).toBe(sinceMs);
    });

    test('returns rows shaped {sent_at, body, intent}', async () => {
      const rows = await outboundHistory.selectRecentOutboundByRecipient('+59891840205', Date.now() - 86400000);
      expect(rows).toHaveLength(1);
      expect(rows[0]).toHaveProperty('sent_at');
      expect(rows[0]).toHaveProperty('body', 'hello back');
      expect(rows[0]).toHaveProperty('intent', 'convo_reply');
    });

    test('SELECT clause projects only sent_at, body, intent columns (D-18)', async () => {
      await outboundHistory.selectRecentOutboundByRecipient('+59891840205', Date.now() - 86400000);
      const [sql] = outboundPool.query.mock.calls[0];
      expect(sql).toMatch(/SELECT\s+sent_at,\s*body,\s*intent/);
    });
  });
});
