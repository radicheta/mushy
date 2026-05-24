---
phase: 52-session-entity-via-asset-group-activity-log-membership
plan: 02
subsystem: alerter/farmos
tags: [session, activity-log, is_group_assignment, farmos, primitive]
provides: [createGroupAssignmentLog, deleteActivityLog]
key-files:
  created:
    - src/agents/alerter/src/farmos/activityLogs.js
    - src/agents/alerter/test/farmos/activityLogs.test.js
  modified: []
metrics:
  tasks: 2
  tests_added: 15
---

# Phase 52 Plan 02: activityLogs.js (membership log) Summary

New module providing the single `log--activity` POST primitive with the stock
`is_group_assignment=true` flag (per farmos team correction -- there is NO
`log--group` bundle).

## What shipped

- `createGroupAssignmentLog(client, {childIds, sessionGroupId, eventDate, name, draftId, notes})`
  -- single POST to `/api/log/activity` with the canonical payload: type
  `log--activity`, attributes.is_group_assignment=true (boolean), timestamp from
  YYYY-MM-DD via UTC-midnight epoch helper, status='done', notes trailer,
  relationships.asset[] of all childIds as asset--fungi, relationships.group[]
  = [{type:'asset--group', id:sessionGroupId}]. No file relationship.
- `deleteActivityLog(client, logId)` -- best-effort DELETE for partial-failure
  rollback in Plan 03.
- CREATION-ONLY: no lookup/merge/upsert per 52-CONTEXT.md decision; duplicate
  retries are acceptable in v1.10.1.
- Inlined `epochSecondsForDate` helper (intentional duplication of
  `commit-seeding-session.js:31-36` to keep module independence).

## Verification

- `npx jest test/farmos/activityLogs.test.js` -- 15/15 green
- `npx jest test/farmos/logs.test.js` -- 26/26 still green (no regression in
  the file pattern being mirrored)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Sanity-check constant in test had wrong year**
- **Found during:** Task 1 RED-then-GREEN cycle (initial test failure)
- **Issue:** Test asserted `expect(expected).toBe(1779667200)` for
  `2026-05-22T00:00:00Z`; correct epoch is `1779408000`. The plan file
  inherited the value `1747872000` from a May-22-2025 example.
- **Fix:** Corrected the sanity-check constant to `1779408000`. The primary
  assertion (against `Math.floor(Date.parse(...)/1000)`) was already
  computed dynamically and correct.
- **Files modified:** `src/agents/alerter/test/farmos/activityLogs.test.js`

## Self-Check: PASSED
