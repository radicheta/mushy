'use strict';

// Phase 40 D-07/D-07a/D-07b: in-process commit watchdog. Mirrors Phase 39
// confirm watchdog shape. Per tick: releaseStaleLocks -> findConfirmedCandidates
// -> per-row idempotency probe -> acquireCommitLock -> commitRouter.commit ->
// markCommitted | requeueForRetry (transient + attempts<max) | markFailed.

function _isTransient(result) {
  if (!result) return true;
  if (result.http_status == null) return true; // network/abort: no status
  if (result.http_status >= 500) return true;
  const reason = String(result.reason || '');
  return /timeout|abort|econnreset|econnrefused/i.test(reason);
}

function createCommitWatchdog({
  pool,
  commitDb,
  farmosClient,
  commitRouter,
  ctx,
  config,
  auditLogger,
  outboundConfirm = null,
  logger = console,
  clock = { now: () => Date.now() },
}) {
  const intervalMs = config.commitWatchdogIntervalMs;
  const batchCap = config.commitWatchdogBatchCap;
  const retryMax = config.commitRetryMax;
  const backoffMs = config.commitRetryBackoffMs || [1000, 4000, 16000];
  const staleMin = config.commitLockStaleMin;
  let timer = null;

  // Phase 45 Plan 04: terminal-state ack dispatch helper. Gated by Plan 01's
  // CAS claim (tryMarkOutcomeAckSent) for ACK-04 idempotency. Two concurrent
  // ticks on the same draft converge to exactly one ack send. A crash between
  // mark and send leaves the draft marked (accepted <=1 dropped ack trade-off).
  async function _maybeDispatchOutcomeAck(lockedRow, outcome, reason) {
    if (typeof commitDb.tryMarkOutcomeAckSent !== 'function') {
      // commit-db without Plan 01 helper (older tests). Degrade silently.
      return;
    }
    let claim;
    try {
      claim = await commitDb.tryMarkOutcomeAckSent(pool, lockedRow.id);
    } catch (e) {
      logger.warn && logger.warn(`[commit-watchdog] tryMarkOutcomeAckSent threw for draft=${lockedRow.id}: ${e.message}`);
      return;
    }
    if (!claim || !claim.ok) return; // already claimed / not found / other tick won
    if (!outboundConfirm || typeof outboundConfirm.dispatch !== 'function') {
      logger.warn && logger.warn(`[commit-watchdog] outboundConfirm not wired; skipping ack for draft=${lockedRow.id}`);
      return;
    }
    try {
      const extras = outcome === 'failed' ? { outcome, reason } : { outcome };
      await outboundConfirm.dispatch('send_commit_outcome_ack', lockedRow, extras);
    } catch (e) {
      logger.warn && logger.warn(`[commit-watchdog] outcome ack dispatch failed draft=${lockedRow.id}: ${e.message}`);
    }
  }

  async function _processRow(row) {
    // Idempotency probe (D-02a).
    const cache = await commitDb.getCachedResponse(pool, row.id);
    if (cache && cache.ok && cache.status === 'committed' && cache.farmos_response) {
      await auditLogger.logCommit('commit_idempotent_noop', row, { http_status: 200 });
      return;
    }

    // Pre-lock backoff gate: if this row has been attempted before AND we are
    // still inside the backoff window, skip without taking the lock. The lock
    // would just be requeued anyway, and burning attempt_count on a no-op
    // would shorten the retry budget unfairly. committed_at_attempt is
    // preserved across requeueForRetry (commit-db) for this exact check.
    const prevAttempts = row.commit_attempt_count || 0;
    if (prevAttempts >= 1 && row.committed_at_attempt) {
      const prevMs = new Date(row.committed_at_attempt).getTime();
      const waitIdx = Math.min(prevAttempts - 1, backoffMs.length - 1);
      const wait = backoffMs[waitIdx];
      if (clock.now() - prevMs < wait) {
        return; // back off; next tick will re-evaluate
      }
    }

    const lock = await commitDb.acquireCommitLock(pool, row.id);
    if (!lock.ok || lock.rowCount === 0) {
      return; // race lost
    }
    const lockedRow = lock.row || row;
    const attempt = lockedRow.commit_attempt_count;

    await auditLogger.logCommit('commit_attempt', lockedRow, { attempt });

    const result = await commitRouter.commit(farmosClient, lockedRow, ctx);

    if (result.ok) {
      await commitDb.markCommitted(pool, lockedRow.id, {
        asset_ids: result.asset_ids,
        log_ids: result.log_ids,
        file_ids: result.file_ids,
        http_status: result.http_status,
        latency_ms: result.latency_ms,
      });
      await auditLogger.logCommit('commit_success', lockedRow, Object.assign({ attempt }, result));
      // Phase 45 Plan 04 T4: dispatch send_commit_outcome_ack (success).
      await _maybeDispatchOutcomeAck(lockedRow, 'success');
      return;
    }

    if (_isTransient(result) && attempt < retryMax) {
      await commitDb.requeueForRetry(pool, lockedRow.id);
      await auditLogger.logCommit('commit_attempt_retry', lockedRow, Object.assign({ attempt }, result));
      return;
    }

    await commitDb.markFailed(pool, lockedRow.id, result.reason || 'unknown');
    await auditLogger.logCommit('commit_failed', lockedRow, Object.assign({ attempt }, result));
    // Phase 45 Plan 04 T6: dispatch send_commit_outcome_ack (failed) for terminal failure.
    // commit_attempt_retry (T5, above) is intentionally NOT hooked: transient.
    const failureReason = result.reason || 'generic_validation_error';
    await _maybeDispatchOutcomeAck(lockedRow, 'failed', failureReason);
  }

  async function tickOnce() {
    try {
      const released = await commitDb.releaseStaleLocks(pool, staleMin);
      if (released && released.released_ids && released.released_ids.length > 0) {
        for (const id of released.released_ids) {
          await auditLogger.logCommit('commit_stale_released', { id, sender_e164: null, log_type: null }, { reason: 'stale_lock_timeout' });
        }
      }
      const rows = await commitDb.findConfirmedCandidates(pool, batchCap);
      for (const row of (rows || [])) {
        try {
          await _processRow(row);
        } catch (e) {
          logger.warn && logger.warn(`[commit-watchdog] row ${row && row.id} threw: ${e.message}`);
        }
      }
    } catch (e) {
      logger.warn && logger.warn(`[commit-watchdog] tick error: ${e.message}`);
    }
  }

  async function start() {
    try {
      await tickOnce();
    } catch (e) {
      logger.warn && logger.warn(`[commit-watchdog] initial tick failed: ${e.message}`);
    }
    timer = setInterval(() => {
      tickOnce().catch((e) => logger.warn && logger.warn(`[commit-watchdog] scheduled tick failed: ${e.message}`));
    }, intervalMs);
    logger.info && logger.info(
      `[commit-watchdog] started: interval=${intervalMs}ms batchCap=${batchCap} retryMax=${retryMax} staleMin=${staleMin}`
    );
  }

  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
    logger.info && logger.info('[commit-watchdog] stopped');
  }

  return { start, stop, tickOnce, _isTransient };
}

module.exports = { createCommitWatchdog, _isTransient };
