'use strict';

// Phase 54 Cycle-1 wiring: hermetic tests for createBackfillContext. The deps
// seam lets us prove the pool + extractor + pipeline wiring with zero real
// Postgres / Anthropic connections.

const { createBackfillContext, buildPool } = require('./backfill-context');

function fakeConfig(overrides = {}) {
  return {
    anthropicApiKey: 'sk-test',
    timescaleHost: 'th',
    timescaleDb: 'tdb',
    timescaleUser: 'tu',
    timescalePassword: 'tp',
    extractionConfidenceThreshold: 0.7,
    draftIdleGapMin: 30,
    maxAskbackTurns: 2,
    ...overrides,
  };
}

function makeDeps(env, extra = {}) {
  const calls = { PoolArgs: [], extractorArgs: [], pipelineArgs: [], initPools: [] };
  const fakePool = { id: 'fake-pool' };
  const deps = {
    Pool: function FakePool(opts) { calls.PoolArgs.push(opts); return fakePool; },
    load: jest.fn(() => fakeConfig()),
    createExtractor: jest.fn((a) => { calls.extractorArgs.push(a); return { id: 'fake-extractor' }; }),
    createExtractionPipeline: jest.fn((a) => { calls.pipelineArgs.push(a); return { enqueue: jest.fn() }; }),
    initSchemas: jest.fn(async (pool) => { calls.initPools.push(pool); }),
    ...extra,
  };
  return { deps, calls, fakePool };
}

describe('createBackfillContext / poolFactory', () => {
  test('builds pool from DATABASE_URL connectionString when set', async () => {
    const env = { DATABASE_URL: 'postgres://u:p@h:5432/db' };
    const { deps, calls, fakePool } = makeDeps(env);
    const ctx = createBackfillContext({ env, logger: { log() {}, warn() {} }, deps });
    const pool = await ctx.poolFactory();
    expect(pool).toBe(fakePool);
    expect(calls.PoolArgs[0]).toEqual({ connectionString: 'postgres://u:p@h:5432/db' });
    expect(calls.initPools).toContain(fakePool);
  });

  test('falls back to canonical TIMESCALE_* fields when DATABASE_URL unset', async () => {
    const env = {};
    const { deps, calls } = makeDeps(env);
    const ctx = createBackfillContext({ env, logger: { log() {}, warn() {} }, deps });
    await ctx.poolFactory();
    expect(calls.PoolArgs[0]).toEqual({
      host: 'th', database: 'tdb', user: 'tu', password: 'tp', port: 5432,
    });
  });

  test('runs schema init against the new pool', async () => {
    const env = { DATABASE_URL: 'x' };
    const { deps, calls } = makeDeps(env);
    const ctx = createBackfillContext({ env, logger: { log() {}, warn() {} }, deps });
    await ctx.poolFactory();
    expect(deps.initSchemas).toHaveBeenCalledTimes(1);
  });
});

describe('createBackfillContext / pipelineFactory', () => {
  test('threads onLlmCall into the extractor', async () => {
    const env = { DATABASE_URL: 'x' };
    const { deps, calls } = makeDeps(env);
    const ctx = createBackfillContext({ env, logger: { log() {}, warn() {} }, deps });
    const onLlmCall = () => {};
    await ctx.pipelineFactory({ pool: { id: 'p' }, onLlmCall });
    expect(calls.extractorArgs[0].onLlmCall).toBe(onLlmCall);
    expect(calls.extractorArgs[0].apiKey).toBe('sk-test');
  });

  test('passes pool + shared config + no-op outboundDispatcher to the pipeline', async () => {
    const env = { DATABASE_URL: 'x' };
    const { deps, calls } = makeDeps(env);
    const ctx = createBackfillContext({ env, logger: { log() {}, warn() {} }, deps });
    const pool = { id: 'p' };
    await ctx.pipelineFactory({ pool, onLlmCall: null });
    const arg = calls.pipelineArgs[0];
    expect(arg.pool).toBe(pool);
    expect(arg.config).toBe(ctx._config);
    expect(typeof arg.outboundDispatcher.dispatch).toBe('function');
    // no-op dispatcher must not throw
    expect(() => arg.outboundDispatcher.dispatch('send_batch_review_summary', {})).not.toThrow();
  });

  test('throws when called without a pool', async () => {
    const env = { DATABASE_URL: 'x' };
    const { deps } = makeDeps(env);
    const ctx = createBackfillContext({ env, logger: { log() {}, warn() {} }, deps });
    await expect(ctx.pipelineFactory({ pool: null })).rejects.toThrow(/requires pool/);
  });
});

describe('createBackfillContext / config sharing', () => {
  test('resolves config.load exactly once and shares it across factories', async () => {
    const env = { DATABASE_URL: 'x' };
    const { deps } = makeDeps(env);
    const ctx = createBackfillContext({ env, logger: { log() {}, warn() {} }, deps });
    await ctx.poolFactory();
    await ctx.pipelineFactory({ pool: { id: 'p' } });
    expect(deps.load).toHaveBeenCalledTimes(1);
  });
});

describe('buildPool', () => {
  test('prefers DATABASE_URL over config fields', () => {
    const seen = [];
    const FakePool = function (o) { seen.push(o); };
    buildPool({ DATABASE_URL: 'conn' }, { Pool: FakePool, config: fakeConfig() });
    expect(seen[0]).toEqual({ connectionString: 'conn' });
  });
});
