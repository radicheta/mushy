#!/usr/bin/env node
'use strict';

/*
 * discard-drafts.js -- standalone maintenance CLI to mark signal_draft rows
 * as discarded.
 *
 * Phase 49 Plan 03. Reusable beyond Phase 49 (Gray Area E: permanent tool).
 * Writes the discarded_reason + discarded_at columns added in Plan 01.
 *
 * Usage:
 *   node scripts/discard-drafts.js --uuid <uuid> [--uuid <uuid>...] --reason "<text>" [--apply]
 *
 *   --uuid <uuid>      Draft id. Repeatable.
 *   --reason "<text>"  Reason string written to discarded_reason. Required.
 *   --apply            Without this flag, dry-run only (SELECT + log, no write).
 *   --help             Print usage + exit 0.
 *
 * Exit codes:
 *   0 -- success (including dry-run + no-op on already-discarded)
 *   1 -- pg error
 *   2 -- arg parse / usage error
 *
 * Idempotency: re-running with the same uuid is a no-op. The UPDATE filters on
 * `WHERE status != 'discarded'`, so an already-discarded row is classified as
 * `alreadyDiscarded` and not re-written; the first reason stands.
 *
 * In container:
 *   docker exec mushy-alerter-1 node /app/scripts/discard-drafts.js \
 *     --uuid <hex> --reason "wrong session" --apply
 */

const USAGE = [
  'Usage: node scripts/discard-drafts.js --uuid <uuid> [--uuid <uuid>...] --reason "<text>" [--apply]',
  '',
  '  --uuid <uuid>      Draft id. Repeatable. At least one required.',
  '  --reason "<text>"  Reason string written to discarded_reason. Required, non-empty.',
  '  --apply            Without this flag, dry-run only (no DB write).',
  '  --help             Print this usage and exit 0.',
].join('\n');

function parseArgs(argv) {
  const out = { uuids: [], reason: null, apply: false, help: false };
  // argv shape: [node, scriptpath, ...flags]
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') {
      out.help = true;
    } else if (a === '--apply') {
      out.apply = true;
    } else if (a === '--uuid') {
      const v = argv[++i];
      if (v === undefined || v === '') {
        throw new Error(`--uuid requires a value\n${USAGE}`);
      }
      out.uuids.push(v);
    } else if (a === '--reason') {
      const v = argv[++i];
      if (v === undefined || v === '') {
        throw new Error(`--reason requires a non-empty value\n${USAGE}`);
      }
      out.reason = v;
    } else {
      throw new Error(`unknown arg: ${a}\n${USAGE}`);
    }
  }
  if (out.help) return out;
  if (out.uuids.length === 0) {
    throw new Error(`at least one --uuid is required\n${USAGE}`);
  }
  if (out.reason === null) {
    throw new Error(`--reason is required\n${USAGE}`);
  }
  return out;
}

/**
 * discardDrafts -- classify the supplied uuids against signal_draft, then,
 * when apply=true, mark non-discarded matches as discarded inside a
 * transaction.
 *
 * Returns { dryRun, candidates, updated, alreadyDiscarded, unknown }:
 *   candidates        rows present + not yet discarded (would be updated)
 *   updated           rows actually updated (apply=true only)
 *   alreadyDiscarded  rows present + already status='discarded' (no-op)
 *   unknown           uuids not present in signal_draft at all
 */
async function discardDrafts({ pool, uuids, reason, apply, logger }) {
  const log = logger || { info: () => {}, warn: () => {} };
  const dryRun = !apply;

  // 1. Classify.
  const sel = await pool.query(
    'SELECT id, status, log_type, sender_e164 FROM signal_draft WHERE id = ANY($1::text[])',
    [uuids],
  );
  const present = new Map();
  for (const r of sel.rows) present.set(r.id, r);

  const candidates = [];
  const alreadyDiscarded = [];
  const unknown = [];
  for (const u of uuids) {
    const row = present.get(u);
    if (!row) {
      unknown.push(u);
      log.info(`classify uuid=${u} state=unknown`);
      continue;
    }
    if (row.status === 'discarded') {
      alreadyDiscarded.push(row);
      log.info(`classify uuid=${u} state=already-discarded log_type=${row.log_type} sender=${row.sender_e164}`);
      continue;
    }
    candidates.push(row);
    log.info(`classify uuid=${u} state=candidate status=${row.status} log_type=${row.log_type} sender=${row.sender_e164}`);
  }

  let updated = [];
  if (dryRun) {
    log.info(`dry-run summary: ${candidates.length} would-update, ${alreadyDiscarded.length} already-discarded, ${unknown.length} unknown`);
    return { dryRun, candidates, updated, alreadyDiscarded, unknown };
  }

  // 2. Apply -- one transaction even when candidates is empty (keeps the
  //    audit trail uniform and ensures the WHERE filter sees a consistent
  //    snapshot of the rows we just classified).
  await pool.query('BEGIN');
  try {
    const upd = await pool.query(
      `UPDATE signal_draft
         SET status = 'discarded',
             discarded_reason = $1,
             discarded_at = now(),
             updated_at = now()
       WHERE id = ANY($2::text[])
         AND status != 'discarded'
       RETURNING id, status, discarded_reason, discarded_at`,
      [reason, uuids],
    );
    updated = upd.rows;
    await pool.query('COMMIT');
  } catch (e) {
    await pool.query('ROLLBACK').catch(() => {});
    throw e;
  }

  for (const r of updated) {
    log.info(`updated uuid=${r.id} prev=candidate new=${r.status} reason="${r.discarded_reason}" at=${r.discarded_at && r.discarded_at.toISOString ? r.discarded_at.toISOString() : r.discarded_at}`);
  }
  log.info(`apply summary: ${updated.length} updated, ${alreadyDiscarded.length} already-discarded, ${unknown.length} unknown`);

  return { dryRun, candidates, updated, alreadyDiscarded, unknown };
}

module.exports = { parseArgs, discardDrafts, USAGE };

if (require.main === module) {
  (async () => {
    let args;
    try {
      args = parseArgs(process.argv);
    } catch (e) {
      process.stderr.write(`${e.message}\n`);
      process.exit(2);
    }
    if (args.help) {
      process.stdout.write(`${USAGE}\n`);
      process.exit(0);
    }
    const { Pool } = require('pg');
    const pool = new Pool({
      host: process.env.PGHOST || 'timescale',
      port: process.env.PGPORT ? Number(process.env.PGPORT) : 5432,
      user: process.env.PGUSER || 'postgres',
      password: process.env.PGPASSWORD || process.env.TIMESCALE_PASSWORD,
      database: process.env.PGDATABASE || 'postgres',
    });
    const logger = {
      info: (m) => process.stdout.write(`${m}\n`),
      warn: (m) => process.stderr.write(`WARN ${m}\n`),
    };
    try {
      await discardDrafts({
        pool,
        uuids: args.uuids,
        reason: args.reason,
        apply: args.apply,
        logger,
      });
      await pool.end();
      process.exit(0);
    } catch (e) {
      process.stderr.write(`pg error: ${e.message}\n`);
      await pool.end().catch(() => {});
      process.exit(1);
    }
  })();
}
