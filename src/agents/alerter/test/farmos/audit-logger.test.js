'use strict';

const { createAuditLogger } = require('../../src/farmos/audit-logger');

describe('audit-logger (Phase 40 Plan 05)', () => {
  function build({ throwOnEvent } = {}) {
    const infoCalls = [];
    const warnCalls = [];
    const eventCalls = [];
    const logger = { info: (...a) => infoCalls.push(a.join(' ')), warn: (...a) => warnCalls.push(a.join(' ')) };
    const confirmDb = {
      appendEventViaPool: jest.fn(async (pool, id, ev, payload) => {
        eventCalls.push({ id, ev, payload });
        if (throwOnEvent) throw new Error('audit row write failed');
        return { ok: true };
      }),
    };
    const al = createAuditLogger({ pool: {}, logger, farmosUrl: 'http://farmos.test', confirmDb });
    return { al, infoCalls, warnCalls, eventCalls };
  }

  it('emits one JSON line with 13 named keys', async () => {
    const { al, infoCalls } = build();
    await al.logCommit('commit_success', {
      id: 'd1', sender_e164: '+15550001234', log_type: 'seeding',
    }, {
      asset_ids: ['a1'], log_ids: ['l1'], file_ids: ['f1'],
      http_status: 201, latency_ms: 432, attempt: 1,
    });
    expect(infoCalls.length).toBe(1);
    const obj = JSON.parse(infoCalls[0]);
    expect(Object.keys(obj).sort()).toEqual([
      'asset_ids','attempt','draft_id','event','farmer','farmos_url','file_ids',
      'http_status','latency_ms','log_ids','log_type','reason','ts',
    ]);
  });

  it('latency_ms 432.7 -> 433 (Math.round)', async () => {
    const { al, infoCalls } = build();
    await al.logCommit('commit_success', { id: 'd1' }, { latency_ms: 432.7 });
    const obj = JSON.parse(infoCalls[0]);
    expect(obj.latency_ms).toBe(433);
  });

  it('appendEventViaPool throw is swallowed', async () => {
    const { al, warnCalls } = build({ throwOnEvent: true });
    await expect(al.logCommit('commit_failed', { id: 'd1' }, {})).resolves.toBeDefined();
    expect(warnCalls.some((w) => /event-row write failed/.test(w))).toBe(true);
  });

  it('null result fields default to [] / null', async () => {
    const { al, infoCalls } = build();
    await al.logCommit('commit_attempt', { id: 'd1' }, null);
    const obj = JSON.parse(infoCalls[0]);
    expect(obj.asset_ids).toEqual([]);
    expect(obj.log_ids).toEqual([]);
    expect(obj.file_ids).toEqual([]);
    expect(obj.http_status).toBeNull();
    expect(obj.latency_ms).toBeNull();
  });

  it('ts is ISO-8601', async () => {
    const { al, infoCalls } = build();
    await al.logCommit('commit_attempt', { id: 'd1' }, {});
    const obj = JSON.parse(infoCalls[0]);
    expect(obj.ts).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  });
});
