'use strict';

const router = require('../../src/farmos/commits/commit-router');

// We test the router by replacing the dispatch table entries directly via the
// exported DISPATCH object reference -- ergonomic for unit-level isolation.

describe('commit-router (Phase 40 Plan 04)', () => {
  it('unsupported log_type returns ok:false with NO fetch issued', async () => {
    const client = { get: jest.fn(), post: jest.fn() };
    const draft = { id: 'd1', log_type: 'garbage' };
    const r = await router.commit(client, draft, { clock: { now: () => 0 } });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('unsupported_log_type');
    expect(client.get).not.toHaveBeenCalled();
    expect(client.post).not.toHaveBeenCalled();
  });

  it('supported log_type dispatches to the right module', async () => {
    const fake = jest.fn(async () => ({ ok: true, asset_ids: ['a'], log_ids: ['l'], file_ids: [], http_status: 201 }));
    const orig = router.DISPATCH.seeding;
    router.DISPATCH.seeding = fake;
    try {
      const r = await router.commit({}, { id: 'd1', log_type: 'seeding' }, { clock: { now: () => 5 } });
      expect(fake).toHaveBeenCalled();
      expect(r.ok).toBe(true);
      expect(r.asset_ids).toEqual(['a']);
    } finally {
      router.DISPATCH.seeding = orig;
    }
  });

  it('thrown error inside dispatch surfaces as ok:false', async () => {
    const orig = router.DISPATCH.seeding;
    router.DISPATCH.seeding = async () => { throw new Error('boom'); };
    try {
      const r = await router.commit({}, { id: 'd1', log_type: 'seeding' }, { clock: { now: () => 0 } });
      expect(r.ok).toBe(false);
      expect(r.reason).toBe('boom');
    } finally {
      router.DISPATCH.seeding = orig;
    }
  });

  // Phase 48 Plan 01: LOG_TYPES allow-list extended to include 'seeding_session'.
  // The router guard MUST NOT bounce it with unsupported_log_type. Plan 02 will
  // wire the actual DISPATCH entry; until then the dispatch lookup returns
  // undefined and commit() blows up with a TypeError when calling fn(...) -- the
  // try/catch wraps it as ok:false with a non-'unsupported_log_type' reason.
  it("LOG_TYPES accepts 'seeding_session' (Phase 48 Plan 01 foundation)", async () => {
    const router = require('../../src/farmos/commits/commit-router');
    const { LOG_TYPES } = require('../../src/farmos/logs');
    expect(LOG_TYPES.includes('seeding_session')).toBe(true);
    // No DISPATCH entry yet (Plan 02 ships it). The guard MUST pass; the
    // failure mode is a downstream TypeError, NOT unsupported_log_type.
    expect(router.DISPATCH.seeding_session).toBeUndefined();
    const r = await router.commit({}, { id: 'd1', log_type: 'seeding_session' }, { clock: { now: () => 0 } });
    expect(r.ok).toBe(false);
    expect(r.reason).not.toBe('unsupported_log_type');
  });

  it('latency_ms populated on success', async () => {
    const orig = router.DISPATCH.activity;
    router.DISPATCH.activity = async () => ({ ok: true, asset_ids: [], log_ids: ['l'], file_ids: [], http_status: 201 });
    let t = 0;
    try {
      const r = await router.commit({}, { id: 'd1', log_type: 'activity' }, { clock: { now: () => (t += 50) } });
      expect(r.latency_ms).toBeGreaterThanOrEqual(0);
    } finally {
      router.DISPATCH.activity = orig;
    }
  });
});
