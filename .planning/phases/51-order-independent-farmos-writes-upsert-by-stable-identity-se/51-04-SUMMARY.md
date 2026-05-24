---
phase: 51
plan: 04
subsystem: alerter / farmos
tags: [upsert, logs, seeding, idempotency, stable-key]
requires: ["51-01", "51-02"]
provides: ["upsertLog", "LOG_STABLE_KEYS", "LogIdentityCollision"]
affects: ["src/agents/alerter/src/farmos/logs.js"]
tech-stack:
  added: []
  patterns: ["lookup-merge-or-create", "soft-compare revision-id", "set-union by id", "split-dedup-join notes"]
key-files:
  created: []
  modified:
    - src/agents/alerter/src/farmos/logs.js
    - src/agents/alerter/test/farmos/logs.test.js
decisions:
  - "warnings:['LogIdentityCollision:N'] returned AND audit event 'log_identity_collision' emitted (belt-and-suspenders)"
  - "Identity-mismatch on asset.data returns structured ok:false (never silently re-bind a seeding log to a different asset)"
  - "Soft-compare retry budget = 1: on 412, re-GET + re-merge once; second failure surfaces http_412"
  - "Empty assetIds for seeding returns ok:false reason:'missing_stable_key' (never POSTs without identity)"
metrics:
  duration: "~25min"
  tasks_completed: 1
  files_modified: 2
  date: 2026-05-24
---

# Phase 51 Plan 04: upsert-log-seeding Summary

One-liner: `upsertLog(client, type, opts)` makes seeding-log writes idempotent by GET-filter-on-asset.id then PATCH-merge-or-POST-create; non-seeding types stay POST-only.

## What Shipped

- **`LOG_STABLE_KEYS` table** in `src/agents/alerter/src/farmos/logs.js`:
  - `seeding`: function returning `{ path: '/api/log/seeding?filter[asset.id][value]=<assetId>' }` or `null` when assetIds is empty
  - `activity`, `input`, `observation`, `harvest`: all `null` (POST-only path preserved)

- **`upsertLog(client, type, opts)`** in same file:
  - Non-native type → throws `UnsupportedLogTypeError` (mirrors `createLog` contract)
  - Null stable key → delegates to `createLog`, wraps success with `outcome:'created'`, `conflicts:[]`, `etag_source:null`
  - Missing stable key (e.g. seeding with empty `assetIds`) → returns `{ok:false, reason:'missing_stable_key'}`
  - Lookup miss → `createLog` (outcome `'created'`)
  - Lookup hit:
    - GETs full canonical body, captures `drupal_internal__revision_id`
    - Asserts byte-equal `asset.data[]` between existing and incoming (sorted-by-id). Mismatch → `{ok:false, reason:'log_identity_mismatch'}` (T-51-08: never re-bind a seeding log to a different asset silently)
    - On `>1` match: sort by `attributes.created` ASC, lex-id ASC tie-break, pick oldest; emit `LogIdentityCollision` audit event AND return `warnings:['LogIdentityCollision:N']` (T-51-09)
    - Merge: `file.data` set-union by id, `notes.value` split-dedup-join on `STABLE_NOTES_SEPARATOR` (from Plan 02 merge.js)
    - Surface scalar conflicts (timestamp/status/name differ) without overwrite
    - No field change → `outcome:'noop'`, no PATCH
    - PATCH with `If-Match:<revision_id>`. On 412, one soft-compare retry: re-GET, re-merge, re-PATCH. `etag_source:'soft_compare'`.

- **`LogIdentityCollision` class** (mirrors `UnsupportedLogTypeError` shape): `{logType, assetId, matchedIds}`.

- **Module exports** updated to expose `upsertLog`, `LOG_STABLE_KEYS`, `LogIdentityCollision`.

## Test Coverage

`src/agents/alerter/test/farmos/logs.test.js`: 26 cases total (7 pre-existing + 19 new across 2 new describe blocks):

- `LOG_STABLE_KEYS table` (7 cases): seeding fn shape, empty-assetIds null, URL-encoding, activity/input/observation/harvest null
- `upsertLog` (12 cases): seeding miss/hit/noop, collision (oldest wins + audit), tie-break (lex id ASC on equal created), 412 retry, identity mismatch, missing stable key, non-seeding pass-through (activity, harvest), non-native rejection, module export shape

A per-test `richMock` was introduced (in-file, not in `mock-client.js`) so this plan does not depend on additional mock-client surface beyond what Plan 01 shipped. The mock supports filter-GET, GET-by-id, POST, and PATCH with optional 412-once protocol.

## Verification

- `cd src/agents/alerter && npx jest test/farmos/logs.test.js --runInBand` → 26/26 pass
- Full farmos suite: 245 pass / 8 skipped / 1 pre-existing failure (`integration/extractor-to-commit.test.js` — missing `@anthropic-ai/sdk` from Phase 43, out of scope)
- Grep gates:
  - `grep -nE "^const LOG_STABLE_KEYS" src/agents/alerter/src/farmos/logs.js` → 1
  - `grep -nE "function upsertLog|async function upsertLog" src/agents/alerter/src/farmos/logs.js` → 1
  - `grep -c "LogIdentityCollision" src/agents/alerter/src/farmos/logs.js` → 4 (class decl, .name, warnings string, export)

## Threat Model Coverage

| Threat ID | Mitigation in this plan |
|-----------|-------------------------|
| T-51-08 (log identity drift) | `_arraysEqualById` on `asset.data` rejects mismatch with `reason:'log_identity_mismatch'`; never silently re-binds. |
| T-51-09 (silent duplicate seeding logs) | `>1` match is observable: audit event `log_identity_collision` + `warnings` array. Oldest deterministically wins by `created` ASC + lex id ASC tie-break. |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Mock-client test regex didn't accept underscore in test ids**
- **Found during:** GREEN phase, collision test failed because `L_OLDER` didn't match `[A-Za-z0-9-]+` in the test-local mock
- **Fix:** Tightened mock GET-by-id and PATCH regex to `[A-Za-z0-9_-]+`
- **Files modified:** `src/agents/alerter/test/farmos/logs.test.js` (test-local richMock only; production mock-client.js unchanged)
- **Commit:** `70fa6f1`

### Plan ambiguities resolved

- Plan said "extract `_buildLogBody` helper if not already factored out" — I extracted it (both `createLog` and `upsertLog` now share it). Net: createLog body unchanged, just delegates to helper.
- Plan said "pick one" between warnings field vs auditLogger event — I implemented both because the plan's behavior block asserts both (`Assert: a warning surfaced (via injectable auditLogger or returned warnings field — pick one, document choice)` — picked both for belt-and-suspenders observability). Audit event uses payload shape `{log_type, asset_id, matched_ids}`; warnings array uses string format `LogIdentityCollision:<count>`.
- Plan referenced `mergeAssetFields`-equivalent but warned "log identity rules differ" — I implemented log-merge helpers inline (`_setUnionRefs`, `_mergeNotes`) rather than extracting shared helpers from merge.js, because the asset-identity-mismatch behavior is different (logs reject; assets throw `IdentityMutationError` for name/type). The notes-merge logic is duplicated; if Plan 05 needs DRYing it can extract `_mergeNotes` to merge.js then.

## Commits

| Hash | Type | Description |
| ---- | ---- | ----------- |
| `fbc88b7` | test | RED — failing tests for upsertLog + LOG_STABLE_KEYS |
| `70fa6f1` | feat | GREEN — UPSERT-02 implementation with stable-key + collision handling |

## Ready For

- Plan 05 (commit-migration-and-property-tests): migrate `commits/commit-seeding-session.js` and `commits/commit-seeding.js` call sites from `logs.createLog(client, 'seeding', ...)` to `logs.upsertLog(client, 'seeding', ...)`.

## Self-Check: PASSED

- FOUND: `src/agents/alerter/src/farmos/logs.js` (modified, 280+ lines, contains `upsertLog`, `LOG_STABLE_KEYS`, `LogIdentityCollision`)
- FOUND: `src/agents/alerter/test/farmos/logs.test.js` (modified, 26 cases pass)
- FOUND: commit `fbc88b7` (RED)
- FOUND: commit `70fa6f1` (GREEN)
- All 26 logs.test.js cases pass; full farmos suite has only 1 pre-existing unrelated failure.
