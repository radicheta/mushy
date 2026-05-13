'use strict';

// Phase 39 D-04..D-04d: in-process watchdog. Polls every
// DRAFT_WATCHDOG_INTERVAL_MS for awaiting_farmer rows past the nudge / expire
// thresholds. First tick fires immediately on alerter start-up (restart safe).

function createWatchdog({
  pool,
  confirmDb,
  outboundConfirm,
  config,
  logger = console,
  clock = { now: () => Date.now() },
}) {
  const timeoutMin = config.draftPendingTimeoutMin;
  const nudgeMin = Math.round(config.draftPendingTimeoutMin * config.draftNudgeFraction);
  const intervalMs = config.draftWatchdogIntervalMs;
  let timer = null;

  async function _processNudge(row) {
    try {
      const updatedAtMs = new Date(row.updated_at).getTime();
      const elapsedMin = (clock.now() - updatedAtMs) / 60000;
      const minutesRemaining = Math.max(0, timeoutMin - Math.round(elapsedMin));

      const mark = await confirmDb.markNudgeSent(pool, row.id);
      if (!mark.ok || mark.rowCount === 0) {
        // restart-race: another tick/process already nudged
        return;
      }
      await outboundConfirm.dispatch('send_nudge', row, { minutesRemaining });
      await confirmDb.appendEventViaPool(pool, row.id, 'nudge_sent', { minutesRemaining });
    } catch (e) {
      logger.warn && logger.warn(`[watchdog] nudge row ${row && row.id} failed: ${e.message}`);
    }
  }

  async function _processExpire(row) {
    try {
      const exp = await confirmDb.expireDraft(pool, row.id, 'timeout_expired');
      if (!exp.ok || exp.rowCount === 0) {
        // already expired by another tick or process
        return;
      }
      await outboundConfirm.dispatch('send_expired_note', row);
    } catch (e) {
      logger.warn && logger.warn(`[watchdog] expire row ${row && row.id} failed: ${e.message}`);
    }
  }

  async function tickOnce() {
    try {
      const nudgeRows = await confirmDb.findNudgeCandidates(pool, nudgeMin);
      for (const row of (nudgeRows || [])) {
        await _processNudge(row);
      }
      const expireRows = await confirmDb.findExpireCandidates(pool, timeoutMin);
      for (const row of (expireRows || [])) {
        await _processExpire(row);
      }
    } catch (e) {
      logger.warn && logger.warn(`[watchdog] tick error: ${e.message}`);
    }
  }

  async function start() {
    // D-04d restart safety: first tick before scheduling.
    try {
      await tickOnce();
    } catch (e) {
      logger.warn && logger.warn(`[watchdog] initial tick failed: ${e.message}`);
    }
    timer = setInterval(() => {
      tickOnce().catch((e) => logger.warn && logger.warn(`[watchdog] scheduled tick failed: ${e.message}`));
    }, intervalMs);
    logger.info && logger.info(
      `[watchdog] started: timeout=${timeoutMin}min nudge=${nudgeMin}min interval=${intervalMs}ms`
    );
  }

  function stop() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
    logger.info && logger.info('[watchdog] stopped');
  }

  return { start, stop, tickOnce };
}

module.exports = { createWatchdog };
