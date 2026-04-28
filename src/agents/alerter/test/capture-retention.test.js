'use strict';

// Mock node-cron BEFORE require so we can capture the scheduled callback
jest.mock('node-cron', () => {
  const scheduled = [];
  return {
    schedule: jest.fn((expr, cb, opts) => {
      const task = { expr, cb, opts, stop: jest.fn(), _stopped: false };
      task.stop = jest.fn(() => { task._stopped = true; });
      scheduled.push(task);
      return task;
    }),
    _scheduled: scheduled,
    _reset: () => { scheduled.length = 0; },
  };
});

const cron = require('node-cron');
const { createRetentionJob } = require('../src/capture-retention');
const { createCaptureHealth } = require('../src/state');

const silent = { info: () => {}, warn: () => {}, error: () => {} };

function makeConfig(overrides = {}) {
  return {
    captureRetentionDays: 30,
    captureRetentionCron: '15 3 * * *',
    timezone: 'America/Toronto',
    ...overrides,
  };
}

beforeEach(() => {
  cron._reset();
  jest.clearAllMocks();
});

describe('createRetentionJob', () => {
  test('factory returns { start, stop, _run }', () => {
    const job = createRetentionJob({
      pool: { query: jest.fn() }, config: makeConfig(),
      state: createCaptureHealth(), logger: silent,
    });
    expect(typeof job.start).toBe('function');
    expect(typeof job.stop).toBe('function');
    expect(typeof job._run).toBe('function');
  });

  test('start() schedules a node-cron task with the configured cron string', () => {
    const job = createRetentionJob({
      pool: { query: jest.fn() }, config: makeConfig({ captureRetentionCron: '0 4 * * *' }),
      state: createCaptureHealth(), logger: silent,
    });
    job.start();
    expect(cron.schedule).toHaveBeenCalledTimes(1);
    expect(cron.schedule.mock.calls[0][0]).toBe('0 4 * * *');
  });

  test('cron callback calls markExpiredOlderThan with retentionDays * 86400 * 1000', async () => {
    const queryFn = jest.fn().mockResolvedValue({ rowCount: 7 });
    const pool = { query: queryFn };
    const state = createCaptureHealth();
    const job = createRetentionJob({ pool, config: makeConfig({ captureRetentionDays: 14 }), state, logger: silent });
    job.start();
    // invoke the captured cron callback directly
    await cron._scheduled[0].cb();
    // capture-db markExpiredOlderThan does an UPDATE — first arg is the SQL
    expect(queryFn).toHaveBeenCalled();
    const sqlArg = queryFn.mock.calls[0][0];
    expect(sqlArg).toMatch(/UPDATE\s+signal_capture/i);
    expect(sqlArg).toMatch(/expired\s*=\s*true/i);
    // State recorded
    expect(state.last_retention_status).toBe('ok');
    expect(state.last_retention_rows).toBe(7);
    expect(typeof state.last_retention_at).toBe('number');
  });

  test('success → state.last_retention_status === "ok" and rows >= 0', async () => {
    const pool = { query: jest.fn().mockResolvedValue({ rowCount: 0 }) };
    const state = createCaptureHealth();
    const job = createRetentionJob({ pool, config: makeConfig(), state, logger: silent });
    await job._run();
    expect(state.last_retention_status).toBe('ok');
    expect(state.last_retention_rows).toBe(0);
  });

  test('failure → state.last_retention_status starts with "failed:" and cron does not throw', async () => {
    const pool = { query: jest.fn().mockRejectedValue(new Error('db down')) };
    const state = createCaptureHealth();
    const job = createRetentionJob({ pool, config: makeConfig(), state, logger: silent });
    await expect(job._run()).resolves.toBeUndefined();
    expect(state.last_retention_status).toMatch(/^failed:/);
    expect(state.last_retention_status).toMatch(/db down/);
  });

  test('stop() calls task.stop() and prevents future runs', () => {
    const pool = { query: jest.fn().mockResolvedValue({ rowCount: 0 }) };
    const job = createRetentionJob({ pool, config: makeConfig(), state: createCaptureHealth(), logger: silent });
    job.start();
    const task = cron._scheduled[0];
    job.stop();
    expect(task.stop).toHaveBeenCalledTimes(1);
  });
});

describe('captureHealth recorders', () => {
  const { recordCaptureSuccess, recordCaptureError, recordRetentionRun } = require('../src/state');

  test('createCaptureHealth() returns expected slot shape', () => {
    const h = createCaptureHealth();
    expect(h).toHaveProperty('last_capture_at', null);
    expect(h).toHaveProperty('last_capture_status', null);
    expect(h).toHaveProperty('last_capture_error_at', null);
    expect(h).toHaveProperty('last_retention_at', null);
    expect(h).toHaveProperty('last_retention_status', null);
    expect(h).toHaveProperty('last_retention_rows', null);
  });

  test('recordCaptureSuccess sets last_capture_at + status=ok', () => {
    const h = createCaptureHealth();
    recordCaptureSuccess(h, 12345);
    expect(h.last_capture_at).toBe(12345);
    expect(h.last_capture_status).toBe('ok');
  });

  test('recordCaptureError sets last_capture_error_at + status=degraded + truncated reason', () => {
    const h = createCaptureHealth();
    const longReason = 'x'.repeat(500);
    recordCaptureError(h, 6789, longReason);
    expect(h.last_capture_error_at).toBe(6789);
    expect(h.last_capture_status).toBe('degraded');
    expect(h.last_capture_error).toBeDefined();
    expect(h.last_capture_error.length).toBeLessThanOrEqual(200);
  });

  test('recordRetentionRun sets retention slots', () => {
    const h = createCaptureHealth();
    recordRetentionRun(h, 999, 'ok', 5);
    expect(h.last_retention_at).toBe(999);
    expect(h.last_retention_status).toBe('ok');
    expect(h.last_retention_rows).toBe(5);
  });
});
