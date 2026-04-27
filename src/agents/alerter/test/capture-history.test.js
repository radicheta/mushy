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
});
