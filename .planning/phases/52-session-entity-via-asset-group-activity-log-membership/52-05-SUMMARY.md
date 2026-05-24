---
phase: 52-session-entity-via-asset-group-activity-log-membership
plan: 05
subsystem: alerter/scripts
tags: [live-fire, ship-gate, dev-only, operator-checkpoint]
key-files:
  created:
    - src/agents/alerter/scripts/live-fire-52.js
    - .planning/phases/52-session-entity-via-asset-group-activity-log-membership/52-LIVE-FIRE.md
  modified: []
metrics:
  tasks: "2/3 (Task 3 is operator checkpoint)"
ship_gate_status: "awaiting-operator"
---

# Phase 52 Plan 05: live-fire-52.js + runbook Summary

Wired the ship-gate live-fire harness and the operator runbook. Task 3
(actually running the live-fire against dev farmOS at :18080) is the
operator-driven checkpoint -- credentials are operator-held and the writes
hit a real shared dev instance.

## What shipped

### scripts/live-fire-52.js
Clone of `live-fire-48.js` with Phase 52 extensions:
- **Prod-guard** (top of IIFE): refuses to run if `FARMOS_URL` ends in `:8082`,
  contains `:8082/`, or includes `prod` (case-insensitive). Exit code 3 on
  trip. Enforces 52-CONTEXT.md "NO prod live-fire in this phase".
- **Draft id prefix** `live-fire-52-` (was `live-fire-48-`) so audit logs
  distinguish runs.
- **Output path** default `/tmp/52-live-fire-result.json`.
- **Probe block** after `result.ok`:
  1. Discover `sessionGroupId` by GETting each `asset_ids` entry with the
     /api/asset/group/<id> path; first hit with type 'asset--group' is the
     session.
  2. Discover a `childId` by GETting each remaining asset_id with
     /api/asset/fungi/<id>; prefer one whose name matches the YYMMDD_-prefix
     child pattern.
  3. **Membership walk**: GET
     `/api/log/activity?filter[is_group_assignment]=1&filter[asset.id]=<childId>`;
     assert at least one returned log has `relationships.group.data[0].id ===
     sessionGroupId`. Sets `membership_walk_ok`.
  4. **Lineage walk**: GET `/api/asset/fungi/<childId>`; assert
     `relationships.parent.data` has exactly one entry of type 'asset--fungi'
     and the parent id is NOT the sessionGroupId. Sets `lineage_walk_ok`.
- Exit code 2 if either probe fails -- CI / operator sees the ship-gate failure
  immediately.

### 52-LIVE-FIRE.md (operator runbook)
All 8 numbered sections rendered as Markdown headings:
1. Purpose
2. Pre-flight checklist (curl probe for farm_group, env exports, jest green)
3. Run command (literal block with the env-prefixed node invocation)
4. Expected counts (1 group / 5 source / 11 children / 1 activity / 11 seeding)
5. Verification probes (membership-walk + lineage-walk curl equivalents)
6. Receipt section (operator fills after run)
7. Backfill note (dev's 11 pre-Phase-52 children stay parent-only; deferred)
8. Prod gating reminder (refuses :8082; coord with farmos team for prod cutover)

ASCII-only, no em-dashes (per `[[feedback_no_em_dashes_in_artifacts]]`).

## Verification

- `node -c scripts/live-fire-52.js` -- parses cleanly.
- Grep gate: `REFUSING`, `is_group_assignment`, `live-fire-52-` all present
  in the script.
- Runbook grep: `is_group_assignment=1` and `:8082` both present.

## Operator checkpoint (Task 3) -- HANDED OFF

The operator must run the live-fire on dev farmOS per the runbook. See the
phase-execution summary for the full handoff message.

## Deviations from Plan

None -- plan executed exactly as written through Task 2. Task 3 is
operator-driven and outside agent scope.

## Self-Check: PASSED (for Tasks 1+2; Task 3 awaits operator)
