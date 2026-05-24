# 52-LIVE-FIRE -- Operator runbook

## Purpose

Ship-gate for Phase 52. Confirms that:

1. The `farm_group` module is live on dev farmOS (asset--group POSTs accepted).
2. `log--activity` accepts `is_group_assignment: true` and binds children + group.
3. The membership-walk query resolves any child back to its session group.
4. The lineage walk on a child returns ONLY its source-block strain parent
   (NO secondary edge to the session group, honoring C4: lineage-as-event).

Hermetic tests cover the wiring shape; only a real farmOS write can confirm
that the stock `farm_group` bundle is enabled and that the JSON:API payload
is accepted as-emitted.

## Pre-flight checklist

1. Dev farmOS reachable AND farm_group enabled:
   ```
   curl -s http://10.68.155.50:18080/api/ | jq '."links"."asset--group"'
   ```
   Returns non-null when the bundle is live (farmos repo commit `1857037`).

2. `mushy-bot` credentials available as env vars:
   ```
   export FARMOS_USERNAME=mushy-bot
   export FARMOS_PASSWORD='<...>'
   ```

3. Full alerter jest suite is GREEN (Plan 04 attestation):
   ```
   cd src/agents/alerter && npx jest
   ```
   Expected: 1133 passed, 9 skipped, 0 failed.

## Run command

```
cd src/agents/alerter
FARMOS_URL=http://10.68.155.50:18080 \
FARMOS_USERNAME=mushy-bot \
FARMOS_PASSWORD='<...>' \
node scripts/live-fire-52.js
```

The script will refuse to run if `FARMOS_URL` contains `:8082` or `prod`
(per 52-CONTEXT.md "NO prod live-fire in this phase"). Exit code 3 = prod-guard
tripped.

## Expected counts (first run against an empty dev farmOS)

- 1 `asset--group` POST (session named `inoc 2026-05-22`)
- 5 `asset--fungi` source-block touches (POST first run; PATCH/noop on
  subsequent runs per Phase 51 upsert)
- 11 `asset--fungi` child-block touches (POST first run; noop on subsequent runs)
- 1 `log--activity` POST (membership, `is_group_assignment: true`)
- 11 `log--seeding` touches (POST first run; noop on subsequent runs)
- Total elapsed: under 10 seconds on a healthy network

## Verification probes

The harness runs these automatically and surfaces `membership_walk_ok` and
`lineage_walk_ok` booleans in the JSON output. Equivalent curl commands for
forensic spot-checks:

Membership walk (child -> session group via activity log, filter is_group_assignment=1):
```
curl -s "http://10.68.155.50:18080/api/log/activity?filter[is_group_assignment]=1&filter[asset.id]=<childId>" \
  -b cookies.txt | jq '.data[0].relationships.group.data'
```
Expected: `[{"type":"asset--group", "id":"<sessionGroupId>"}]`

Lineage walk (child -> strain parent, NO session group):
```
curl -s "http://10.68.155.50:18080/api/asset/fungi/<childId>" \
  -b cookies.txt | jq '.data.relationships.parent.data'
```
Expected: exactly one entry with `type:"asset--fungi"` (the source block).
The session group id MUST NOT appear in this list.

## Receipt section

(operator fills after run)

```
[ ] First run timestamp: __________
[ ] PASS / FAIL: __________
[ ] Session group id: __________
[ ] Sample child id used for probes: __________
[ ] Spot-check in farmOS UI: navigate to /asset/<groupId>;
    "Group members" view shows all 11 children -- [ ] confirmed
[ ] JSON receipt pasted below:

```
<paste /tmp/52-live-fire-result.json here>
```
```

## Backfill note (deferred per CONTEXT.md)

The 11 dev-farmOS children from the 2026-05-24 48-LIVE-FIRE run are NOT in
scope for this phase. They keep their parent-only lineage and have no session
group. A separate cleanup phase covers them.

## Prod gating reminder

Prod is NOT in scope for Phase 52. The harness refuses to run against `:8082`.
Prod cutover is a separate decision gated on `FARMOS_INTEGRATION` per the
2026-05-24 UAT findings. Coordinate with the farmos team on permissions for
`asset/group` + `log/activity` CRUD before flipping.
