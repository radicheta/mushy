---
phase: 52-session-entity-via-asset-group-activity-log-membership
plan: 03
subsystem: alerter/farmos/commits
tags: [session, commit-handler, asset-group, activity-log, rewire]
key-files:
  created: []
  modified:
    - src/agents/alerter/src/farmos/commits/commit-seeding-session.js
metrics:
  tasks: 1
---

# Phase 52 Plan 03: commit-seeding-session.js rewire Summary

Re-introduced session-entity preflight in the seeding_session handler using
the Plan 01/02 primitives. Handler now mints exactly one session entity per
draft (asset--group, idempotent by name + draft-id-trailer match) and exactly
one membership log per session (log--activity with is_group_assignment=true)
after all children land.

## What changed

- Imports added: `../groupAssets`, `../activityLogs`.
- New helper `_resolveSessionName(client, eventDate, draftId)` -- probes
  `inoc <date>`, then `#2` ... `#9`, picking the first name that misses OR
  hits an existing group with matching draft-id trailer. Returns null on
  COLLISION_MAX=9 exhaustion.
- PREFLIGHT: after validating the draft, resolve the session name, then call
  `upsertGroupAsset`. Track whether it was just-created so cleanup knows
  whether to roll it back.
- CHILDREN LOOP: unchanged. Children still carry `parent=[sourceBlockId]`
  ONLY -- NO secondary edge to the session group (honors C4).
- POST-LOOP: call `createGroupAssignmentLog` with all childBlockIds + the
  sessionGroupId. On failure, run expanded `_cleanup`.
- `_cleanup` extended: optional `membershipLogId` deleted FIRST, then the
  fungi assets in reverse order (existing behavior), then the session group
  asset LAST if it was just-created. Each delete best-effort with
  `orphan_cleanup_failed` audit on failure.
- Return shape: `asset_ids[0]` is the session group id (when newly created);
  `log_ids[0]` is the membership log id followed by the N seeding log ids.
- Deleted the stale Phase 48 reversal comment block (lines 89-99 of the
  prior file) and replaced with a header comment pointing to 52-CONTEXT.md.

## Verification

- Shape grep gate: `upsertGroupAsset`, `createGroupAssignmentLog`,
  `_resolveSessionName`, `deleteGroupAsset`, `deleteActivityLog` all present.
- `node -e "require('./src/farmos/commits/commit-seeding-session')"` loads
  without throwing.
- Existing handler-level tests in `commit-seeding-session.test.js` will be
  updated in Plan 04 to match the new counts + assertions.

## Deviations from Plan

None -- plan executed exactly as written.

## Self-Check: PASSED
