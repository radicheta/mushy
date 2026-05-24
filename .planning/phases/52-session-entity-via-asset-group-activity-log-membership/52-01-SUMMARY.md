---
phase: 52-session-entity-via-asset-group-activity-log-membership
plan: 01
subsystem: alerter/farmos
tags: [session, asset-group, farmos, primitive]
provides: [findGroupAssetByName, upsertGroupAsset, deleteGroupAsset]
key-files:
  created:
    - src/agents/alerter/src/farmos/groupAssets.js
    - src/agents/alerter/test/farmos/groupAssets.test.js
  modified: []
metrics:
  tasks: 2
  tests_added: 13
---

# Phase 52 Plan 01: groupAssets.js (asset--group primitives) Summary

New module `groupAssets.js` providing the lookup-or-create primitive for the stock
farmOS `asset--group` bundle (farm_group module, enabled by farmos commit `1857037`
on dev + prod).

## What shipped

- `findGroupAssetByName(client, name)` -- LRU-cached lookup by attributes.name via
  `GET /api/asset/group?filter[name][value]=<encoded>`. Cache cap 32, mirrors
  `assets.js` verbatim.
- `upsertGroupAsset(client, {name, draftId, notes})` -- lookup-or-create. Miss
  POSTs the canonical shape (`type:'asset--group'`, `status:'active'`, notes with
  `mushy:draft:<draftId>` trailer, NO relationships). Hit returns the existing
  UUID with `outcome:'reused'`. NO merge layer per 52-CONTEXT.md.
- `deleteGroupAsset(client, assetId)` -- best-effort DELETE with name-cache
  invalidation (linear scan, cache cap 32).
- `_clearCache()` -- test-only.

## Verification

- `npx jest test/farmos/groupAssets.test.js` -- 13/13 green
- `npx jest test/farmos/assets.test.js` -- 23/23 still green (no regression in
  the file pattern being mirrored)

## Deviations from Plan

None -- plan executed exactly as written.

## Self-Check: PASSED
