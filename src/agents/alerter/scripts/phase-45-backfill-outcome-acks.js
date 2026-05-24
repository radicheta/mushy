#!/usr/bin/env node
'use strict';

// Phase 45 Plan 05: live-fire backfill of outstanding silent-failure / silent-success
// drafts through the now-shipping outcome-ack path.
//
// Honors the deployed tryMarkOutcomeAckSent claim (does NOT bypass). Per-draft state
// determines outcome:
//   - status='commit_failed' → outcome='failed', reason=commit_failed_reason
//   - status='committed'     → outcome='success' (T4 backfill — pre-Plan-45 silent commit)
//
// Emits NDJSON to stdout, one line per phase event. Operator redirects to named
// sibling JSONL under the phase dir per [[feedback_persist_paid_results_default]].
//
// Usage:
//   node scripts/phase-45-backfill-outcome-acks.js --draft-id <hex> [--draft-id <hex> ...] [--dry-run]
//
// Inside container:
//   docker exec mushy-alerter-1 node /app/scripts/phase-45-backfill-outcome-acks.js \
//     --draft-id <id> [--dry-run]

const { Pool } = require('pg');
const config = require('../src/config');
const { createSignalClient } = require('../src/signal');
const confirm = require('../src/confirm');
const commitDb = require('../src/farmos/commit-db');
const outboundDb = require('../src/outbound-db');
const { renderOutcomeAck } = require('../src/farmos/commit-outcome-preview');

function emit(phase, payload) {
  const line = Object.assign({ ts: new Date().toISOString(), phase }, payload);
  process.stdout.write(JSON.stringify(line) + '\n');
}

function parseArgs(argv) {
  const out = { draftIds: [], dryRun: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--dry-run') out.dryRun = true;
    else if (a === '--draft-id') { out.draftIds.push(argv[++i]); }
    else if (a === '--help' || a === '-h') {
      process.stderr.write('Usage: --draft-id <hex> [--draft-id <hex> ...] [--dry-run]\n');
      process.exit(0);
    } else {
      process.stderr.write(`Unknown arg: ${a}\n`);
      process.exit(2);
    }
  }
  if (out.draftIds.length === 0) {
    process.stderr.write('At least one --draft-id is required\n');
    process.exit(2);
  }
  return out;
}

function outcomeFromStatus(status) {
  if (status === 'commit_failed') return 'failed';
  if (status === 'committed') return 'success';
  return null;
}

// Renderer reads draftRow.sender_name; signal_draft has no such column today,
// so look up the slug from SIGNAL_FARMER_MAP and capitalize for the greeting.
// Runtime dispatch path (commit-watchdog) has the same gap — track as follow-on.
function senderNameFromMap(senderE164, farmerMap) {
  if (!farmerMap || typeof farmerMap.get !== 'function') return undefined;
  const slug = farmerMap.get(senderE164);
  if (!slug || typeof slug !== 'string' || slug.length === 0) return undefined;
  return slug[0].toUpperCase() + slug.slice(1);
}

(async () => {
  const args = parseArgs(process.argv);
  const cfg = config.load();
  const pool = new Pool({
    host: process.env.PGHOST || 'timescale',
    port: process.env.PGPORT ? Number(process.env.PGPORT) : 5432,
    user: process.env.PGUSER || 'postgres',
    password: process.env.PGPASSWORD || process.env.TIMESCALE_PASSWORD,
    database: process.env.PGDATABASE || 'postgres',
  });

  const logger = {
    info: (m) => process.stderr.write(`[backfill] ${m}\n`),
    warn: (m) => process.stderr.write(`[backfill WARN] ${m}\n`),
  };

  // Build the minimal signal stack mirroring index.js so dispatch path is identical.
  const signalClient = createSignalClient({
    apiUrl: cfg.signalApiUrl,
    sender: cfg.signalSender,
    recipient: cfg.signalRecipient,
    defaultTarget: cfg.signalGroupId ? { groupId: cfg.signalGroupId } : cfg.signalRecipient,
    maxSendsPerHour: cfg.maxSendsPerHour,
    getMaxSendsPerHour: () => cfg.maxSendsPerHour,
    logger,
    outboundDb,
    pool,
    tenantId: cfg.tenantId,
  });

  const confirmOutbound = confirm.createConfirmOutbound({
    signalClient,
    previewBuilderConfirm: confirm.preview,
    operatorRecipient: cfg.signalRecipient,
    logger,
  });

  emit('boot', {
    dry_run: args.dryRun,
    draft_ids: args.draftIds,
    signal_sender: cfg.signalSender,
    tenant_id: cfg.tenantId,
  });

  let exitCode = 0;
  for (const draftId of args.draftIds) {
    try {
      const { rows } = await pool.query('SELECT * FROM signal_draft WHERE id=$1', [draftId]);
      if (rows.length === 0) {
        emit('not_found', { draft_id: draftId });
        exitCode = 1;
        continue;
      }
      const row = rows[0];
      row.sender_name = senderNameFromMap(row.sender_e164, cfg.signalFarmerMap);
      const outcome = outcomeFromStatus(row.status);
      if (!outcome) {
        emit('skip_unsupported_status', { draft_id: draftId, status: row.status });
        continue;
      }
      const reason = outcome === 'failed'
        ? (row.commit_failed_reason || 'generic_validation_error')
        : undefined;

      // Pre snapshot (minimal — id + status + ack timestamp + e164 + log_type)
      emit('pre', {
        draft_id: draftId,
        row_snapshot: {
          id: row.id,
          status: row.status,
          log_type: row.log_type,
          sender_e164: row.sender_e164,
          commit_failed_reason: row.commit_failed_reason,
          outcome_ack_sent_at: row.outcome_ack_sent_at,
          created_at: row.created_at,
        },
        derived_outcome: outcome,
        derived_reason: reason,
      });

      if (args.dryRun) {
        let farmosLink;
        const resp = row.farmos_response;
        if (resp && typeof resp === 'object' && typeof resp.link === 'string' && resp.link.trim() !== '') {
          farmosLink = resp.link.trim();
        }
        const body = renderOutcomeAck(row, { outcome, reason, farmosLink });
        emit('dry_run_rendered', { draft_id: draftId, outcome, reason, body });
        continue;
      }

      // Claim
      const claim = await commitDb.tryMarkOutcomeAckSent(pool, draftId);
      if (!claim || claim.ok !== true) {
        emit('idempotency_recheck', {
          draft_id: draftId,
          result: claim ? (claim.already_claimed ? 'already_sent_skip' : 'not_found') : 'unknown',
          claim,
        });
        continue;
      }

      // Dispatch through deployed outbound-confirm
      const dispatchResult = await confirmOutbound.dispatch('send_commit_outcome_ack', row, {
        outcome,
        reason,
      });
      emit('dispatch', { draft_id: draftId, outcome, reason, dispatch_result: dispatchResult });

      // Post snapshot
      const { rows: postRows } = await pool.query(
        'SELECT outcome_ack_sent_at, status FROM signal_draft WHERE id=$1',
        [draftId],
      );
      emit('post', {
        draft_id: draftId,
        post_snapshot: postRows[0] || null,
      });
    } catch (e) {
      emit('error', { draft_id: draftId, message: e.message, stack: e.stack });
      exitCode = 1;
    }
  }

  await pool.end();
  process.exit(exitCode);
})();
