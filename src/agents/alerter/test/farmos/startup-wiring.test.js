'use strict';

// Phase 40 Plan 06 wiring smoke test. We don't boot the whole alerter (too
// much wiring); instead we exercise the conditional construction shape via
// a tiny local factory that mirrors the src/index.js logic. This catches
// regressions in env-gated construction + helper signatures without
// requiring docker/db/signal mocks.

const farmos = require('../../src/farmos');
const captureDb = require('../../src/capture-db');

function buildCommitStack({ config, pool, logger, confirmDb }) {
  let commitWatchdog = null;
  if (config.farmosUsername && config.farmosPassword) {
    const farmosClient = farmos.createFarmosClient({
      farmosUrl: config.farmosUrl,
      username: config.farmosUsername,
      password: config.farmosPassword,
      logger,
      backoffMs: config.commitRetryBackoffMs,
      retryMax: config.commitRetryMax,
      fetchImpl: async () => ({ ok: true, status: 200, headers: { get: () => '' }, json: async () => ({}), text: async () => '' }),
    });
    const auditLogger = farmos.createAuditLogger({ pool, logger, farmosUrl: config.farmosUrl, confirmDb });
    const ctx = {
      commitDb: farmos.commitDb,
      capturePathsFor: async (ids) => {
        const r = await captureDb.getAttachmentPathsForIds(pool, ids);
        return r.ok ? r.paths : [];
      },
      logger,
      clock: { now: () => Date.now() },
    };
    commitWatchdog = farmos.createCommitWatchdog({
      pool, commitDb: farmos.commitDb, farmosClient, commitRouter: farmos.commitRouter,
      ctx, config, auditLogger, logger,
    });
    return { commitWatchdog, auditLogger, farmosClient, ctx };
  }
  logger.warn('[commit-watchdog] disabled: farmOS credentials missing');
  return { commitWatchdog: null };
}

function makeConfig(overrides) {
  return Object.assign({
    farmosUrl: 'http://farmos.test',
    farmosUsername: 'u',
    farmosPassword: 'p',
    commitWatchdogIntervalMs: 30000,
    commitWatchdogBatchCap: 10,
    commitRetryMax: 3,
    commitRetryBackoffMs: [1000, 4000, 16000],
    commitLockStaleMin: 5,
  }, overrides || {});
}

function makeLogger() {
  const calls = { info: [], warn: [] };
  return { info: (...a) => calls.info.push(a.join(' ')), warn: (...a) => calls.warn.push(a.join(' ')), _calls: calls };
}

describe('Phase 40 startup wiring (Plan 06)', () => {
  it('credentials present: commitWatchdog + ctx assembled', () => {
    const logger = makeLogger();
    const stack = buildCommitStack({
      config: makeConfig(),
      pool: { query: async () => ({ rows: [], rowCount: 0 }) },
      logger,
      confirmDb: { appendEventViaPool: async () => ({ ok: true }) },
    });
    expect(stack.commitWatchdog).not.toBeNull();
    expect(typeof stack.commitWatchdog.start).toBe('function');
    expect(typeof stack.commitWatchdog.stop).toBe('function');
    expect(typeof stack.ctx.capturePathsFor).toBe('function');
    expect(stack.ctx.commitDb).toBe(farmos.commitDb);
  });

  it('credentials missing: commitWatchdog stays null + WARN logged', () => {
    const logger = makeLogger();
    const stack = buildCommitStack({
      config: makeConfig({ farmosUsername: '', farmosPassword: '' }),
      pool: {}, logger, confirmDb: {},
    });
    expect(stack.commitWatchdog).toBeNull();
    expect(logger._calls.warn.some((w) => /commit-watchdog.*disabled.*credentials missing/.test(w))).toBe(true);
  });

  it('capturePathsFor wires through captureDb.getAttachmentPathsForIds', async () => {
    const queries = [];
    const pool = { query: async (sql, params) => { queries.push({ sql, params }); return { rows: [{ attachment_paths: ['/a.jpg', '/b.jpg'] }] }; } };
    const logger = makeLogger();
    const stack = buildCommitStack({
      config: makeConfig(), pool, logger, confirmDb: {},
    });
    const paths = await stack.ctx.capturePathsFor(['cap-1']);
    expect(paths).toEqual(['/a.jpg', '/b.jpg']);
    expect(queries.length).toBe(1);
    expect(queries[0].sql).toMatch(/SELECT attachment_paths FROM signal_capture/);
  });

  it('start ordering: commitWatchdog.start triggers releaseStaleLocks before findConfirmedCandidates', async () => {
    const calls = [];
    const pool = {
      query: async (sql) => {
        if (/UPDATE signal_draft[\s\S]+WHERE status='committing'/i.test(sql)) {
          calls.push('releaseStaleLocks');
          return { rows: [], rowCount: 0 };
        }
        if (/SELECT \* FROM signal_draft\s+WHERE status='confirmed'/i.test(sql)) {
          calls.push('findConfirmedCandidates');
          return { rows: [], rowCount: 0 };
        }
        return { rows: [], rowCount: 0 };
      },
    };
    const logger = makeLogger();
    const stack = buildCommitStack({
      config: makeConfig(), pool, logger, confirmDb: { appendEventViaPool: async () => ({ ok: true }) },
    });
    await stack.commitWatchdog.tickOnce();
    expect(calls).toEqual(['releaseStaleLocks', 'findConfirmedCandidates']);
    stack.commitWatchdog.stop();
  });
});

describe('Phase 54.1 startup wiring (Plan 03 live strain ask-back)', () => {
  // The live strain-pending intercept in receive-loop.js is dead unless
  // src/index.js forwards extractionDb into createReceiveLoop. Unit tests
  // inject extractionDb directly, so they cannot catch a boot-wiring drop.
  // This source-level guard asserts the real index.js call site, per the
  // gap caught in 54.1-VERIFICATION.md.
  const fs = require('fs');
  const path = require('path');
  const indexSrc = fs.readFileSync(path.join(__dirname, '../../src/index.js'), 'utf8');

  it('src/index.js forwards extractionDb into createReceiveLoop', () => {
    const call = indexSrc.match(/createReceiveLoop\(\{([\s\S]*?)\}\)/);
    expect(call).not.toBeNull();
    expect(call[1]).toMatch(/(^|[\s,{])extractionDb\s*[,}]/);
  });
});
