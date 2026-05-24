---
phase: 49-real-session-eval-corpus-may-22-ship-gate-reprocess
plan: 03
subsystem: alerter/scripts
tags: [maintenance-cli, discard-drafts, idempotent, dry-run-default]
requires:
  - signal_draft.discarded_reason + .discarded_at columns (Plan 01)
provides:
  - reusable discard-drafts CLI (Phase 49+; permanent maintenance tool)
  - parseArgs + discardDrafts exported functions
affects:
  - jest.config.js (testMatch widened to include scripts/)
tech_stack:
  added: []
  patterns:
    - "SELECT-first classifier into candidates / alreadyDiscarded / unknown buckets"
    - "Dry-run by default; --apply explicit gate"
    - "BEGIN + UPDATE ... WHERE status != 'discarded' RETURNING + COMMIT (idempotency via the WHERE filter)"
key_files:
  created:
    - src/agents/alerter/scripts/discard-drafts.js
    - src/agents/alerter/scripts/discard-drafts.test.js
  modified:
    - src/agents/alerter/jest.config.js
decisions:
  - "Test file lives next to the script (src/agents/alerter/scripts/) per plan-locked path; jest testMatch widened to discover **/scripts/**/*.test.js (Rule 3 blocking-issue fix)"
  - "Single transaction wraps the UPDATE even when candidates is empty -- keeps idempotent re-runs identical in shape to first apply"
  - "Logger interface is { info, warn }; CLI entry maps info -> stdout and warn -> stderr (one structured line per row + summary)"
metrics:
  duration_minutes: ~10
  completed_date: 2026-05-23
---

# Phase 49 Plan 03: Discard CLI Summary

Ships a standalone idempotent maintenance CLI -- `discard-drafts.js` -- that
marks `signal_draft` rows as discarded by writing the `discarded_reason` +
`discarded_at` columns that Plan 01 added. Default mode is dry-run; only
`--apply` writes. Re-running on already-discarded rows is a logged no-op.
Reusable beyond Phase 49 per CONTEXT Gray Area E. Plan 04's ship-gate runbook
invokes it on the two real May-22 draft UUIDs.

## What was built

### 1. discard-drafts.js (Task 1, GREEN)

CLI contract:

```
Usage: node scripts/discard-drafts.js --uuid <uuid> [--uuid <uuid>...] --reason "<text>" [--apply]

  --uuid <uuid>      Draft id. Repeatable. At least one required.
  --reason "<text>"  Reason string written to discarded_reason. Required, non-empty.
  --apply            Without this flag, dry-run only (no DB write).
  --help             Print this usage and exit 0.

Exit codes:
  0  success (including dry-run + no-op on already-discarded)
  1  pg error
  2  arg parse / usage error
```

Exported-function contract (preferred for in-process callers + tests):

```js
const { parseArgs, discardDrafts } = require('./discard-drafts');

const args = parseArgs(process.argv);   // { uuids, reason, apply, help }
const r = await discardDrafts({
  pool,        // pg Pool or Client with .query()
  uuids,       // string[]
  reason,      // string (non-empty)
  apply,       // boolean
  logger,      // { info(msg), warn(msg) }
});
// r = { dryRun, candidates, updated, alreadyDiscarded, unknown }
```

SQL shapes issued:

```sql
-- 1. Classify (always run).
SELECT id, status, log_type, sender_e164
  FROM signal_draft
 WHERE id = ANY($1::text[]);

-- 2. Apply (only when --apply; wrapped in BEGIN/COMMIT, ROLLBACK on throw).
UPDATE signal_draft
   SET status = 'discarded',
       discarded_reason = $1,
       discarded_at = now(),
       updated_at = now()
 WHERE id = ANY($2::text[])
   AND status != 'discarded'
 RETURNING id, status, discarded_reason, discarded_at;
```

Idempotency property: the `WHERE status != 'discarded'` filter is the gate.
Re-running with the same uuid yields `updated=[]` + `alreadyDiscarded=[row]`
and the first reason stands.

pg pool wiring (CLI entry only -- tests pass their own pool):

```
host     = process.env.PGHOST || 'timescale'
port     = process.env.PGPORT || 5432
user     = process.env.PGUSER || 'postgres'
password = process.env.PGPASSWORD || process.env.TIMESCALE_PASSWORD
database = process.env.PGDATABASE || 'postgres'
```

This matches the env-var shape used by `phase-45-backfill-outcome-acks.js`.

### 2. discard-drafts.test.js (Task 1, RED -> GREEN)

12 tests, all green. The 8 plan-mandated cases plus four extras that fell out
naturally during TDD:

| # | Bucket | Case |
|---|--------|------|
| 1 | parseArgs | happy path: multiple --uuid + --reason + --apply |
| 2 | parseArgs | missing --reason throws usage error |
| 3 | parseArgs | missing --uuid throws usage error |
| 4 | parseArgs | --help returns { help: true } |
| - | parseArgs | rejects empty --reason (defensive) |
| - | parseArgs | rejects unknown args (defensive) |
| 5 | discardDrafts | dry-run: classifies but does not mutate; no BEGIN/UPDATE issued |
| 6 | discardDrafts | apply: writes status=discarded, discarded_reason, discarded_at; BEGIN+COMMIT shape |
| 7 | discardDrafts | idempotent re-run: updated=[]; alreadyDiscarded contains the row; first reason preserved |
| 8 | discardDrafts | unknown uuid: surfaces in unknown[]; no throw |
| - | discardDrafts | mixed batch: candidates + alreadyDiscarded + unknown in one call |
| - | discardDrafts | rollback on UPDATE failure (ROLLBACK issued; error propagates) |

Test harness: an in-memory pool stub recognizes the three SQL shapes the
script issues (BEGIN/COMMIT/ROLLBACK, SELECT classifier, UPDATE RETURNING)
and mutates an in-memory `rows[]` array to mimic real Postgres semantics.
This keeps the test pure-unit (no postgres binary, no jest-pg dep) while
still exercising the WHERE-filter idempotency property end-to-end.

## Verification (from plan)

- `npx jest scripts/discard-drafts.test.js --no-coverage` -- 12 passed
- `node scripts/discard-drafts.js --help` -- exits 0 with usage block
- `grep -P '[\x{2013}\x{2014}]'` of both files -- clean (no em-dashes)
- Full alerter suite (`npx jest --no-coverage`) -- 964 passed / 9 skipped / 0
  failed on a clean run. (One flake observed on a prior run in an unrelated
  suite; reproduced clean on rerun, so not introduced by this plan.)

## Plan 04 handoff

Plan 04's operator-driven ship-gate runbook will invoke this script in the
alerter container on the two real May-22 draft UUIDs once they are pinned:

```
docker exec mushy-alerter-1 node /app/scripts/discard-drafts.js \
  --uuid <UUID_1> --uuid <UUID_2> \
  --reason "phase 49 reprocess: superseded by deterministic reparse" \
  --apply
```

Dry-run first (omit `--apply`); inspect the classify lines; then re-run with
`--apply`. Idempotent if re-invoked.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] jest.config.js testMatch did not cover scripts/**
- **Found during:** Task 1 RED step (jest reported "No tests found" for
  scripts/discard-drafts.test.js).
- **Issue:** The plan's `files_modified` and the must-have artifact path both
  pin the test under `src/agents/alerter/scripts/discard-drafts.test.js`, but
  the alerter's `jest.config.js` testMatch was `['**/test/**/*.test.js']` --
  which excluded everything under `scripts/`. Without a fix, the plan-mandated
  test path would never run.
- **Fix:** Widened testMatch to
  `['**/test/**/*.test.js', '**/scripts/**/*.test.js']`. No new dep, no
  behavior change to other tests (verified: 75 of 77 suites still pass on
  full-suite rerun, identical to pre-change). One alternative considered --
  moving the file to `test/scripts/discard-drafts.test.js` -- was rejected
  because the plan locks the path.
- **Files modified:** `src/agents/alerter/jest.config.js`
- **Commit:** `a3df71b` (bundled with the RED test commit)

### Authentication Gates

None.

### Threat Flags

None new. The plan's threat register T-49-03-01 (accidental mass-discard) is
mitigated as designed: dry-run is default, --apply is the explicit gate, and
SELECT-first classification surfaces unknown UUIDs before any UPDATE runs.
T-49-03-02 (repudiation) is mitigated by the structured one-line-per-row
stdout log plus the persisted `discarded_reason` + `discarded_at` columns.

## Known Stubs

None.

## Self-Check: PASSED

Files verified to exist:
- FOUND: src/agents/alerter/scripts/discard-drafts.js
- FOUND: src/agents/alerter/scripts/discard-drafts.test.js
- FOUND: src/agents/alerter/jest.config.js (modified)

Commits verified:
- FOUND: a3df71b (RED: failing tests + jest config widen)
- FOUND: ba6c748 (GREEN: discard-drafts.js implementation)
