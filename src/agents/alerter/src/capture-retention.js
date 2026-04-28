'use strict';
// Phase 25 Plan 05 (D-06): in-process daily retention cron.
// Soft-flag only — markExpiredOlderThan does UPDATE expired=true (NEVER DELETE).
// Failures are recorded into the captureHealth slot but never throw out of the cron.

const cron = require('node-cron');
const { markExpiredOlderThan } = require('./capture-db');
const { recordRetentionRun } = require('./state');

function createRetentionJob({ pool, config, state, logger = console }) {
  let task = null;

  async function run() {
    const ageMs = config.captureRetentionDays * 86400 * 1000;
    try {
      const r = await markExpiredOlderThan(pool, ageMs);
      recordRetentionRun(state, Date.now(), 'ok', r.rowCount);
      logger.info(`[retention] flagged ${r.rowCount} rows expired (>${config.captureRetentionDays}d)`);
    } catch (e) {
      recordRetentionRun(state, Date.now(), `failed: ${e.message}`, 0);
      logger.warn(`[retention] failed: ${e.message}`);
    }
  }

  return {
    start() {
      task = cron.schedule(
        config.captureRetentionCron,
        run,
        { timezone: config.timezone || 'America/Toronto' }
      );
    },
    stop() {
      if (task) {
        task.stop();
        task = null;
      }
    },
    _run: run, // exposed for tests
  };
}

module.exports = { createRetentionJob };
