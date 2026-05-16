'use strict';

// Phase 40 D-03 / D-03c: dispatch one signal_draft.log_type to one B7 commit
// module. Single guard on log_type validity (defense-in-depth; Phase 38 already
// validates). Uniform result envelope.

const { LOG_TYPES, UnsupportedLogTypeError } = require('../logs');
const { normalize } = require('./normalize');
const commitSeeding = require('./commit-seeding');
const commitActivity = require('./commit-activity');
const commitInput = require('./commit-input');
const commitObservation = require('./commit-observation');
const commitHarvest = require('./commit-harvest');

const DISPATCH = {
  seeding: commitSeeding,
  activity: commitActivity,
  input: commitInput,
  observation: commitObservation,
  harvest: commitHarvest,
};

async function commit(client, draft, ctx) {
  const clock = (ctx && ctx.clock) || { now: () => Date.now() };
  const t0 = clock.now();
  const logType = draft && draft.log_type;
  if (!logType || !LOG_TYPES.includes(logType)) {
    return {
      ok: false,
      reason: 'unsupported_log_type',
      log_type: logType,
      asset_ids: [], log_ids: [], file_ids: [],
      latency_ms: clock.now() - t0,
    };
  }
  const fn = DISPATCH[logType];
  try {
    // Phase 43 D-02: normalize extractor-shape -> commit-shape before dispatch.
    // Original signal_draft.draft_json is NOT mutated; normalized copy is local only.
    const r = await fn(client, normalize(draft), ctx);
    return {
      ok: !!r.ok,
      asset_ids: r.asset_ids || [],
      log_ids: r.log_ids || [],
      file_ids: r.file_ids || [],
      http_status: r.http_status,
      latency_ms: clock.now() - t0,
      reason: r.reason,
    };
  } catch (e) {
    if (e instanceof UnsupportedLogTypeError) {
      return {
        ok: false, reason: 'unsupported_log_type', log_type: e.logType,
        asset_ids: [], log_ids: [], file_ids: [],
        latency_ms: clock.now() - t0,
      };
    }
    return {
      ok: false, reason: e.message || 'commit_error',
      asset_ids: [], log_ids: [], file_ids: [],
      latency_ms: clock.now() - t0,
    };
  }
}

module.exports = { commit, DISPATCH };
