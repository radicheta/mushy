---
phase: 52-session-entity-via-asset-group-activity-log-membership
plan: 04
subsystem: alerter/farmos/tests
tags: [session, integration-tests, hermetic, mock-client]
key-files:
  created: []
  modified:
    - src/agents/alerter/test/farmos/mock-client.js
    - src/agents/alerter/test/farmos/commit-seeding-session.test.js
    - src/agents/alerter/test/farmos/integration/seeding-session-commit-may22.test.js
    - src/agents/alerter/test/farmos/integration/seeding-session-commit-partial-fail.test.js
    - src/agents/alerter/test/farmos/integration/seeding-session-commit-idempotent.test.js
    - src/agents/alerter/test/fixtures/seeding-session-may22-commit/expected-farmos-payloads.json
    - src/agents/alerter/src/farmos/commits/commit-seeding-session.js
metrics:
  tasks: 2
  full_suite: "1133 passed, 9 skipped, 0 failed"
---

# Phase 52 Plan 04: hermetic tests at new counts Summary

Updated the full hermetic test surface to the Phase 52 shape: 17 asset writes
(1 group + 5 source + 11 children), 12 logs (1 activity-with-flag + 11 seeding),
and the expanded reverse-order rollback that now includes the session group.

## What changed

### mock-client.js
- New `knownGroupsByName` option to pre-seed `asset--group` entities (used by
  the collision test).
- GET routing for `/api/asset/group?filter[name][value]=...` and
  `/api/asset/group/<id>`.
- POST routing for `/api/asset/group` -> assigns `group-<n>` ids, registers in
  `_groupById`/`_groupIdByName` so subsequent lookups hit.
- New `_created.groups[]` and `_created.activityLogs[]` parallel indexes.
- `created.logs` still receives ALL log POSTs (preserving the existing
  `commit-activity.test.js` contract); activity-with-flag logs are
  ADDITIONALLY pushed to `activityLogs` for cleaner Phase 52 assertions.

### commit-seeding-session.test.js (was 7 scenarios, now 9)
- Test A: 17/12 counts + new membership-log shape assertions (is_group_assignment,
  asset.data.length=11, group.data=[{type:'asset--group', id}], parent[]=[source] ONLY).
- Test C / Test D: updated to assert 1 session group + 1 activity log alongside
  the existing fungi-asset / seeding-log shape.
- Test E (partial fail on seeding log #4): now expects 9 DELETEs (8 fungi + 1
  session group) in reverse order; session group DELETE is LAST.
- Test F: cleanup-itself-fails now expects 9 orphan_cleanup_failed audit lines.
- **NEW Test E2**: membership log POST fails -> rollback covers ALL children +
  source blocks + session group (17 DELETEs); session group is last in the
  DELETE sequence. Reason surfaces as `farmos_response.original_reason ===
  'membership_log_create_failed'`.
- **NEW Test F2**: same-day collision -> existing `inoc 2026-05-22` with
  foreign draft trailer triggers `#2` allocation; the NEW group POST has
  `attributes.name === 'inoc 2026-05-22 #2'`.
- Test H (idempotency under new shape): second commit reuses session group +
  fungi + seeding logs (zero new POSTs) BUT POSTs a new activity log (creation-
  only per 52-CONTEXT.md); log_ids[0] is the second-tick membership log id.

### integration/*.test.js
- `seeding-session-commit-may22.test.js`: asserts 16+1 assets / 12 logs / 17
  return-shape asset_ids / 12 log_ids.
- `seeding-session-commit-partial-fail.test.js`: 9 DELETEs (was 8); session
  group DELETE is LAST; 9 orphan_cleanup_failed audit lines on rollback failure.
- `seeding-session-commit-idempotent.test.js`: first-tick counts updated to
  16 fungi + 1 group + 12 logs.

### expected-farmos-payloads.json fixture
- Updated `_comment` to point at 52-CONTEXT.md and the session-as-asset-group
  design.
- `happy_path.group_post_count: 1`, `log_post_count: 12` with breakdown
  `{activity_with_flag:1, seeding:11}`.
- `partial_fail_at_log_4.delete_count: 9`.
- `idempotent.second_tick_activity_log_posts: 1` (creation-only behavior).
- `single_parent_legacy.group_post_count: 1`, `log_post_count: 6`.

### commit-seeding-session.js (handler micro-tweak)
- Changed `membershipRes.reason || 'membership_log_create_failed'` to literal
  `'membership_log_create_failed'` so the rollback's `original_reason` surfaces
  the structural-failure label (not the underlying HTTP code). Improves
  observability for callers / audit lines distinguishing seeding-log vs
  membership-log failures.

## Verification

- `cd src/agents/alerter && npx jest test/farmos/commit-seeding-session.test.js`
  -- 9/9 green.
- `cd src/agents/alerter && npx jest` (full suite) -- **1133 passed, 9 skipped,
  0 failed** across 80 suites.
- No regression in `commit-activity.test.js` (existing log--activity callers
  without is_group_assignment still land in `created.logs` unchanged).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] mock-client log routing regression for commit-activity**
- **Found during:** Task 2 (full suite run)
- **Issue:** Initial mock-client extension diverted ALL `/api/log/activity`
  POSTs into a separate `activityLogs[]` array, away from the existing
  `created.logs[]`. This broke `commit-activity.test.js` (3 tests) which
  reads `client._created.logs[0].payload` for ordinary activity logs.
- **Fix:** Keep `created.logs[]` as the universal sink; ADDITIONALLY push to
  `activityLogs[]` only when the payload carries
  `attributes.is_group_assignment === true`. Preserves back-compat with the
  existing commit-activity contract while giving Phase 52 a clean filter.
- **Files modified:** `test/farmos/mock-client.js`

**2. [Rule 1 - Bug] Handler reason surfacing for membership-log failure**
- **Found during:** Test E2 first run
- **Issue:** Handler propagated `membershipRes.reason` (e.g. `http_422`) to
  rollback's `original_reason`, swallowing the structural label that callers
  / audit lines use to distinguish failure modes.
- **Fix:** Use literal `'membership_log_create_failed'` for `original_reason`;
  HTTP status / underlying error still available via the membership-log's own
  return value if needed in the future.
- **Files modified:** `src/agents/alerter/src/farmos/commits/commit-seeding-session.js`

## Self-Check: PASSED
