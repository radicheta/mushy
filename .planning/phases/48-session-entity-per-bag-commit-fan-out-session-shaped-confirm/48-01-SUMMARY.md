---
phase: 48-session-entity-per-bag-commit-fan-out-session-shaped-confirm
plan: 01
subsystem: alerter / farmOS commit pipeline
tags: [foundation, log_types, idempotency, signal_draft, seeding_session]
requires: []
provides:
  - "LOG_TYPES allow-list extended with 'seeding_session' (router guard accepts it)"
  - "NATIVE_LOG_TYPES export (createLog allow-list; the 5 native farmOS log types)"
  - "Regression coverage proving signal_draft.farmos_response round-trips multi-asset / multi-log shape"
  - "Regression coverage proving idempotent re-commit on committed draft returns cached response (rowCount=0 lock)"
affects:
  - src/agents/alerter/src/farmos/commits/commit-router.js (guard now accepts seeding_session; DISPATCH entry deferred to Plan 02)
tech-stack:
  added: []
  patterns:
    - "Composite vs native log_type split: LOG_TYPES (router guard, 6 entries) vs NATIVE_LOG_TYPES (createLog allow-list, 5 entries). seeding_session is composite -- the seeding_session handler (Plan 02) writes 1 asset + N child seeding logs via createLog(client, 'seeding', ...)"
key-files:
  created: []
  modified:
    - src/agents/alerter/src/farmos/logs.js
    - src/agents/alerter/test/farmos/logs.test.js
    - src/agents/alerter/test/farmos/commit-db.test.js
    - src/agents/alerter/test/farmos/commit-router.test.js
decisions:
  - "Idempotency surface is signal_draft.id + signal_draft.farmos_response (JSONB cache) -- there is NO separate signal_commit table. CONTEXT.md uses the signal_commit name; that is a memory-drift from the actual Phase 40 implementation. Reconciled silently per the friction policy (mismatch silent, missing-data ask)."
  - "Introduced NATIVE_LOG_TYPES alongside LOG_TYPES to prevent createLog from being callable with seeding_session (which has no /api/log/seeding_session endpoint). Composite types live in LOG_TYPES so the router guard passes; createLog narrows to NATIVE_LOG_TYPES."
  - "seeding_session appended to LOG_TYPES (no positional consumers found across src/ and test/; grep was the gate)."
metrics:
  duration_min: 5
  completed: 2026-05-23
---

# Phase 48 Plan 01: Foundation -- extend LOG_TYPES + regression-proof multi-asset/multi-log farmos_response

One-liner: Extend the alerter's commit-router LOG_TYPES allow-list to accept the new composite log type `seeding_session`, and add regression tests proving the existing Phase 40 commit-db primitives (markCommitted, getCachedResponse, acquireCommitLock) already round-trip the 1-asset / N-log farmos_response shape unchanged.

## What shipped

1. `src/agents/alerter/src/farmos/logs.js`
   - Added `NATIVE_LOG_TYPES = ['seeding','activity','input','observation','harvest']` (createLog allow-list, unchanged behavior).
   - `LOG_TYPES` now equals `[...NATIVE_LOG_TYPES, 'seeding_session']` (router guard allow-list).
   - `createLog` narrowed to check `NATIVE_LOG_TYPES.includes` so it cannot be called with the composite type by mistake.
   - Exported `NATIVE_LOG_TYPES` alongside `LOG_TYPES`.

2. `src/agents/alerter/test/farmos/logs.test.js`
   - Parametric createLog iteration switched from `LOG_TYPES` to `NATIVE_LOG_TYPES` so seeding_session is not asserted as a callable native target.

3. `src/agents/alerter/test/farmos/commit-router.test.js`
   - New test: "LOG_TYPES accepts 'seeding_session' (Phase 48 Plan 01 foundation)". Asserts the guard passes, DISPATCH entry is currently undefined (Plan 02 ships it), and the failure mode is downstream (not `unsupported_log_type`).

4. `src/agents/alerter/test/farmos/commit-db.test.js`
   - New test: "markCommitted + getCachedResponse round-trip multi-asset multi-log shape" -- caches `{asset_ids:['asset-uuid-a'], log_ids:['log-uuid-1','log-uuid-2','log-uuid-3'], ...}` and reads it back intact.
   - New test: "idempotent re-commit on committed draft yields rowCount=0 lock + intact cache" -- proves the existing `acquireCommitLock` guard (`WHERE status='confirmed'`) is the idempotency choke point. Watchdog must short-circuit on the cached `farmos_response` instead of re-dispatching.

## Schema-reconciliation note (CONTEXT.md naming drift)

CONTEXT.md references a `signal_commit` table as the idempotency surface. **No such table exists.** Phase 40 (D-02 / D-02a / D-07) shipped idempotency by extending `signal_draft` with:

- `status` value `'committed'` (validated in JS, not pg CHECK)
- `farmos_response jsonb` -- the cache (asset_ids[], log_ids[], file_ids[], http_status, latency_ms)
- `committed_at`, `commit_failed_reason`, `commit_attempt_count`, `committed_at_attempt`
- `outcome_ack_sent_at` (Phase 45 D-01 / ACK-04, mark-then-send CAS)

The idempotency key is **`signal_draft.id`** (UUID); the cache is **`signal_draft.farmos_response`** (JSONB). Per the friction policy (`feedback_friction_policy_missing_vs_mismatch`): when sources merely disagree about a name, pick the canonical source silently. Canonical source = the code on disk. Plan 02 should read `signal_draft.farmos_response` for the cached response on idempotent re-commit; no new table is needed.

## Tenant-aware

No new persisted columns introduced. The `signal_draft` table already carries tenant identity via existing Phase 38/39 columns; nothing in this plan changes the tenant story.

## Test results

```
Test Suites: 2 skipped, 69 passed, 69 of 71 total
Tests:       9 skipped, 922 passed, 931 total
```

Targeted suite (Plan 01 verification command):

```
PASS test/farmos/commit-router.test.js    (5 tests, +1 new)
PASS test/farmos/commit-db.test.js        (18 tests, +2 new)
PASS test/farmos/logs.test.js             (7 tests, iteration narrowed to NATIVE_LOG_TYPES)
```

## Deviations from Plan

**1. [Rule 2 - Critical correctness] Split LOG_TYPES into LOG_TYPES + NATIVE_LOG_TYPES**

- **Found during:** Task 1 implementation.
- **Issue:** Appending `seeding_session` to a single `LOG_TYPES` array makes `createLog(client, 'seeding_session', ...)` pass the guard and POST to `/api/log/seeding_session` -- a non-existent farmOS endpoint. The unit-test mock client returns ok regardless of URL, so the existing parametric `for (const t of logs.LOG_TYPES)` test would have silently asserted that `seeding_session` is a callable native log type. That is misleading regression coverage that would mask a real production 404 the day someone wires the seeding_session handler incorrectly.
- **Fix:** Introduced `NATIVE_LOG_TYPES` (5 entries; createLog allow-list) alongside `LOG_TYPES` (6 entries; router guard allow-list). Narrowed `createLog`'s internal check to `NATIVE_LOG_TYPES.includes`. Updated `logs.test.js` to iterate `NATIVE_LOG_TYPES` for the parametric createLog assertion.
- **Files modified:** `src/farmos/logs.js`, `test/farmos/logs.test.js`.
- **Rationale:** Rule 2 (auto-add missing critical functionality for correctness). The plan body anticipated this with "grep first for positional uses; if none, append" -- the narrower issue is semantic, not positional, so a slightly stronger guard ships. This also matches the plan's stated intent: "seeding_session is a COMPOSITE log_type recognized by the commit-router but NOT a native farmOS log type".

No other deviations. No auth gates. No blockers.

## Self-Check: PASSED

- `src/agents/alerter/src/farmos/logs.js` exists; `grep -c seeding_session` = 3 (in comment, in array, and via comment again) -- target was >= 1.
- `src/agents/alerter/test/farmos/commit-db.test.js` exists; 18 tests pass (was 16, +2 Plan 01).
- `src/agents/alerter/test/farmos/commit-router.test.js` exists; 5 tests pass (was 4, +1 Plan 01).
- Targeted command `npx jest test/farmos/commit-db test/farmos/commit-router` green.
- Full alerter suite (`npx jest`) green: 922 passed, 9 skipped.
