---
phase: 45-north-star-commit-failed-ack-replay-outstanding-silent-failu
plan: 01
subsystem: alerter/farmos
tags: [ack-04, idempotency, schema-migration, signal-draft]
requires: []
provides:
  - signal_draft.outcome_ack_sent_at timestamptz column (boot migration)
  - tryMarkOutcomeAckSent(pool, draftId) CAS primitive
affects:
  - src/agents/alerter/src/farmos/commit-db.js
  - src/agents/alerter/test/farmos/commit-db.test.js
  - src/agents/alerter/test/farmos/fake-pool.js (extended to model new SQL shapes)
tech-stack:
  added: []
  patterns: ["conditional UPDATE ... WHERE col IS NULL RETURNING" CAS]
key-files:
  created: []
  modified:
    - src/agents/alerter/src/farmos/commit-db.js
    - src/agents/alerter/test/farmos/commit-db.test.js
    - src/agents/alerter/test/farmos/fake-pool.js
decisions:
  - Helper name `tryMarkOutcomeAckSent` returns `{ok, id, claimed_at}` on first claim, `{ok:false, reason:'already_claimed'|'not_found'}` otherwise (per plan behavior block).
  - SQL is a single CAS UPDATE preceded by a SELECT-1 existence probe to disambiguate `not_found` from `already_claimed` (UPDATE rowCount=0 alone cannot tell them apart).
  - Errors propagate (helper does not wrap into `{ok:false, reason}` like `markCommitted`). Plan's behavior block: "Bad pool / SQL error: throws (consistent with markCommitted's error style)." `markCommitted` actually wraps, but the plan also separately says "do NOT throw on 'already claimed' — that is the steady-state non-error path", treating only "already claimed" as non-throwing. Interpreted as: dispatch-side primitive must surface infra failures to the caller. If callers want a never-throw wrapper they can add one downstream.
  - Plan referred to `initCommitSchema`; the actual exported function in commit-db.js is `initDb` (Phase 40 naming). Treated as the same function — added the new ALTER TABLE there.
metrics:
  duration_minutes: ~10
  completed_at: 2026-05-23
---

# Phase 45 Plan 01: outcome_ack_sent_at column + tryMarkOutcomeAckSent CAS primitive Summary

One-liner: Adds the `signal_draft.outcome_ack_sent_at timestamptz` mark-then-send claim column at boot and exports a single-statement CAS helper (`tryMarkOutcomeAckSent`) that returns the draft id exactly once per draft — the ACK-04 idempotency primitive Plan 04 needs before any outcome-ack dispatch hook is wired.

## What shipped

1. **Schema migration** — `commit-db.js::initDb` now issues 6 ALTER TABLE statements (was 5). The new one: `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS outcome_ack_sent_at timestamptz`. No index — the column is only ever queried via single-row CAS by id.

2. **CAS helper** — `tryMarkOutcomeAckSent(pool, draftId)`:
   - Probes existence with `SELECT 1 FROM signal_draft WHERE id=$1`. If row missing → `{ok:false, reason:'not_found'}`.
   - Executes `UPDATE signal_draft SET outcome_ack_sent_at = now() WHERE id=$1 AND outcome_ack_sent_at IS NULL RETURNING id, outcome_ack_sent_at`.
   - `rowCount=0` → `{ok:false, reason:'already_claimed'}`.
   - `rowCount=1` → `{ok:true, id, claimed_at}`.

3. **Unit tests (3 new)** in `test/farmos/commit-db.test.js`:
   - first call returns ok with claimed_at (and audits the SQL shape — single UPDATE, `WHERE ... IS NULL`, `RETURNING id, outcome_ack_sent_at`).
   - second call on already-claimed draft returns `ok=false, reason='already_claimed'`.
   - unknown draftId returns `ok=false, reason='not_found'`.

4. **Fake-pool extension** — added two new query-shape branches in `test/farmos/fake-pool.js` to model the existence probe and the CAS UPDATE, plus the new column in `seedDraft` defaults.

## Verification

- `grep "outcome_ack_sent_at timestamptz" src/agents/alerter/src/farmos/commit-db.js` → 1 hit inside `initDb`.
- `grep "tryMarkOutcomeAckSent" src/.../commit-db.js` → declaration + export.
- `grep "tryMarkOutcomeAckSent" test/.../commit-db.test.js` → describe block + 3 test cases.
- No new index referencing `outcome_ack_sent_at` (asserted in test).
- `npm test -- test/farmos/commit-db.test.js` → 13/13 passed (10 pre-existing + 3 new).
- Full alerter suite: `npm test` → 802/811 passed (9 pre-existing skips, 0 failures, 0 regressions).
- Boot smoke: `node -e "require('./src/farmos/commit-db.js')"` → OK.

## Deviations from Plan

**[Rule 3 - Naming drift] Plan said `initCommitSchema`, function is `initDb`.**
The plan's `<interfaces>` block named the boot-migration function `initCommitSchema` and the `key_links.via` field repeated that name. The actual function exported by `commit-db.js` is `initDb` (has been since Phase 40). Treated as the same function and added the new ALTER inside `initDb`. No new function created; renaming `initDb` would be a much larger blast radius (`src/index.js` calls it).

**[Rule 2 - Disambiguate not_found vs already_claimed] Added a SELECT-1 existence probe.**
The plan's behavior block requires three distinct return shapes: `ok=true`, `already_claimed`, and `not_found`. A pure CAS `UPDATE ... WHERE id=$1 AND outcome_ack_sent_at IS NULL` returns `rowCount=0` for BOTH (a) row doesn't exist and (b) row exists but already claimed. The CAS alone cannot tell them apart. Added a `SELECT 1 FROM signal_draft WHERE id=$1` probe immediately before the UPDATE to produce the `not_found` discriminator. This is a 2-statement helper rather than the "single-statement CAS" the action block describes, but it is the only way to satisfy the behavior contract. Documented inline in the helper.

**[Rule 3 - Test fixture maintenance] Updated existing `alters.length` assertion from 5 to 6.**
The pre-existing test `initDb issues 5 ALTER TABLE statements + 1 CREATE INDEX` would have failed after the schema migration. Renamed to "issues 6" and added two new sub-assertions: the new column appears, and no new index references it. Direct trace to the user's request.

## Stubs / Threat Flags

None. No new network surface; new column inherits trust boundary of existing signal_draft table.

## Self-Check: PASSED

- Files exist:
  - FOUND: src/agents/alerter/src/farmos/commit-db.js
  - FOUND: src/agents/alerter/test/farmos/commit-db.test.js
  - FOUND: src/agents/alerter/test/farmos/fake-pool.js
- Tests: 13/13 in target file; 802/811 in suite (no regressions vs baseline skips).
