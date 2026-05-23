'use strict';

// Phase 48 Plan 05: shared hermetic harness for the three seeding_session
// commit-pipeline integration tests.
//
// Wires the REAL commit-router + REAL commit-seeding-session against a mock
// farmOS client (from test/farmos/mock-client.js, extended here with the
// DELETE verb that commit-seeding-session's orphan cleanup requires). The
// pg pool is replaced with an in-memory commitDb identical in shape to the
// one already used by test/farmos/commit-watchdog.test.js.
//
// This is the producer-to-consumer chain the unit tests in 48-02 and 48-04
// cannot exercise (per [[feedback_unit_tests_dont_catch_wiring]]):
//
//   commit-watchdog.tickOnce()
//     -> commitDb.findConfirmedCandidates / acquireCommitLock
//     -> commit-router.commit
//     -> commit-seeding-session.commitSeedingSession (REAL)
//     -> assets/logs (REAL) -> mock farmosClient.post/get/delete
//     -> commitDb.markCommitted / markFailed
//     -> outboundConfirm.dispatch('send_commit_outcome_ack', ...)
//     -> auditLogger.logCommit(...)

const path = require('path');
const fs = require('fs');

const { createCommitWatchdog } = require('../../../src/farmos/commit-watchdog');
const commitRouter = require('../../../src/farmos/commits/commit-router');
const assets = require('../../../src/farmos/assets');
const fungiTypeCache = require('../../../src/farmos/fungi-type-cache');
const fungiXingCache = require('../../../src/farmos/fungi-xing-cache');
const { makeMockClient } = require('../mock-client');

const FIXTURE_DIR = path.join(__dirname, '..', '..', 'fixtures', 'seeding-session-may22-commit');

function loadMay22Draft() {
  return JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, 'draft.json'), 'utf8'));
}

function makeCommitDb(initialRows) {
  // initialRows: array of [id, row] pairs
  const drafts = new Map(initialRows || []);
  const calls = [];
  const ackClaimed = new Set();
  return {
    _drafts: drafts,
    _calls: calls,
    _ackClaimed: ackClaimed,
    async releaseStaleLocks() {
      calls.push({ fn: 'releaseStaleLocks' });
      return { ok: true, rowCount: 0, released_ids: [] };
    },
    async findConfirmedCandidates(pool, batchCap) {
      calls.push({ fn: 'findConfirmedCandidates' });
      return Array.from(drafts.values()).filter((r) => r.status === 'confirmed').slice(0, batchCap);
    },
    async getCachedResponse(pool, id) {
      const r = drafts.get(id);
      if (!r) return { ok: false };
      return {
        ok: true,
        status: r.status,
        farmos_response: r.farmos_response,
        commit_failed_reason: r.commit_failed_reason,
      };
    },
    async acquireCommitLock(pool, id) {
      calls.push({ fn: 'acquireCommitLock', id });
      const r = drafts.get(id);
      if (!r || r.status !== 'confirmed') return { ok: true, rowCount: 0, row: null };
      r.status = 'committing';
      r.commit_attempt_count = (r.commit_attempt_count || 0) + 1;
      r.committed_at_attempt = new Date();
      return { ok: true, rowCount: 1, row: Object.assign({}, r) };
    },
    async markCommitted(pool, id, resp) {
      calls.push({ fn: 'markCommitted', id, resp });
      const r = drafts.get(id);
      if (r) { r.status = 'committed'; r.farmos_response = resp; }
      return { ok: true, rowCount: 1 };
    },
    async markFailed(pool, id, reason) {
      calls.push({ fn: 'markFailed', id, reason });
      const r = drafts.get(id);
      if (r) { r.status = 'commit_failed'; r.commit_failed_reason = reason; }
      return { ok: true, rowCount: 1 };
    },
    async requeueForRetry(pool, id) {
      calls.push({ fn: 'requeueForRetry', id });
      const r = drafts.get(id);
      if (r) { r.status = 'confirmed'; r.committed_at_attempt = null; }
      return { ok: true, rowCount: 1 };
    },
    async tryMarkOutcomeAckSent(pool, id) {
      calls.push({ fn: 'tryMarkOutcomeAckSent', id });
      if (!drafts.has(id)) return { ok: false, reason: 'not_found' };
      if (ackClaimed.has(id)) return { ok: false, reason: 'already_claimed' };
      ackClaimed.add(id);
      return { ok: true, id, claimed_at: new Date() };
    },
  };
}

function makeAuditLogger() {
  const events = [];
  return {
    _events: events,
    logCommit: jest.fn(async (event, draft, result) => {
      events.push({ event, draft_id: draft && draft.id, result });
    }),
  };
}

function makeOutboundConfirm() {
  return { dispatch: jest.fn().mockResolvedValue({ ok: true }) };
}

function extendClientWithDelete(client, opts = {}) {
  const { deleteResponse = null, failLogIndex = -1, failLogStatus = 422 } = opts;
  client._deletes = [];

  // Wrap .post to support failLogIndex (1-based count of log POSTs).
  const origPost = client.post;
  let logPostCount = 0;
  client.post = jest.fn(async (p, body, o) => {
    if (/^\/api\/log\//.test(p)) {
      logPostCount += 1;
      if (failLogIndex > 0 && logPostCount === failLogIndex) {
        return { ok: false, status: failLogStatus, body: { errors: [{ detail: 'validation' }] } };
      }
    }
    return origPost(p, body, o);
  });

  client.delete = jest.fn(async (p) => {
    client._deletes.push(p);
    if (typeof deleteResponse === 'function') return deleteResponse(p);
    return { ok: true, status: 204, body: null };
  });

  return client;
}

function buildSeedRow(draftJson, overrides) {
  return Object.assign({
    id: 'd-session-may22',
    log_type: 'seeding_session',
    status: 'confirmed',
    commit_attempt_count: 0,
    committed_at_attempt: null,
    sender_e164: '+59891840205',
    sender_name: 'Santi',
    draft_json: draftJson,
  }, overrides || {});
}

function buildHarness({
  draft,
  failLogIndex = -1,
  deleteResponse = null,
  knownAssetsByName = {},
  rowOverrides = {},
} = {}) {
  // Clear module-level caches so cross-test pollution is impossible.
  assets._clearCache && assets._clearCache();
  fungiTypeCache._clear && fungiTypeCache._clear();
  fungiXingCache._clear && fungiXingCache._clear();

  const draftJson = draft || loadMay22Draft();
  const row = buildSeedRow(draftJson, rowOverrides);

  const farmosClient = extendClientWithDelete(
    makeMockClient({ knownAssetsByName }),
    { failLogIndex, deleteResponse },
  );

  const commitDb = makeCommitDb([[row.id, row]]);
  const auditLogger = makeAuditLogger();
  const outboundConfirm = makeOutboundConfirm();

  const config = {
    commitWatchdogIntervalMs: 30000,
    commitWatchdogBatchCap: 10,
    commitRetryMax: 0, // force terminal-failure on first attempt (no retries)
    commitRetryBackoffMs: [1000, 4000, 16000],
    commitLockStaleMin: 5,
  };

  const watchdog = createCommitWatchdog({
    pool: {},
    commitDb,
    farmosClient,
    commitRouter,
    ctx: { auditLogger },
    config,
    auditLogger,
    outboundConfirm,
    logger: { info() {}, warn() {} },
    clock: { now: () => 100000 },
  });

  return { watchdog, commitDb, farmosClient, auditLogger, outboundConfirm, row };
}

module.exports = {
  loadMay22Draft,
  buildHarness,
  buildSeedRow,
  FIXTURE_DIR,
};
