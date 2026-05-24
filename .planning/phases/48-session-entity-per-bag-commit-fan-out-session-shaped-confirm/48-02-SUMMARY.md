---
phase: 48-session-entity-per-bag-commit-fan-out-session-shaped-confirm
plan: 02
subsystem: alerter / farmOS commit pipeline
tags: [seeding_session, commit-fanout, session-asset, lineage, orphan-cleanup, idempotency-adjacent]
requires:
  - "48-01 (LOG_TYPES allow-list now contains 'seeding_session'; createLog narrowed to NATIVE_LOG_TYPES)"
provides:
  - "commitSeedingSession(client, draft, ctx) implementing asset-first preflight + per-child fan-out + all-or-nothing orphan cleanup"
  - "DISPATCH.seeding_session = commitSeedingSession wired in commit-router.js"
  - "assets.createFungiAsset({ allowNoFungiType: true }) -- omits fungi_type relationship for anonymous session assets"
  - "assets.deleteFungiAsset(client, assetId) -- best-effort orphan cleanup primitive; invalidates name-cache entry"
  - "farmosClient.delete(path) -- new DELETE verb on the HTTP client; mirrors get/post/patch/head"
affects:
  - "src/agents/alerter/src/farmos/assets.js (allowNoFungiType flag + deleteFungiAsset export)"
  - "src/agents/alerter/src/farmos/client.js (delete verb)"
  - "src/agents/alerter/src/farmos/commits/commit-router.js (DISPATCH.seeding_session wiring)"
tech-stack:
  added: []
  patterns:
    - "Asset-first preflight: create the session asset BEFORE any child writes so a single rollback id is known up-front. Child loop tracks every newly-created asset in createdAssetIds[]; on first child-side failure the cleanup branch DELETEs all of them in reverse-order (children first, then source blocks, then session) so we never orphan a parent ahead of its children."
    - "allowNoFungiType escape hatch: anonymous session asset has no strain (multi-strain bundle). createFungiAsset extended with a boolean flag rather than a separate primitive -- preserves the single create-asset code path and keeps the change footprint surgical."
    - "fungiXingName='block' re-used for the session asset (no new 'session' xing term). Acceptable because xing is structural and 'block' already encodes 'this is a substrate-bearing physical thing'. Flagged for operator review in case a 'session' xing better fits the lineage walker UX (deferred to v2.0)."
    - "deleteFungiAsset wraps client.delete and invalidates the asset-name cache by reverse-lookup so a re-commit attempt does not reuse a stale UUID."
    - "Lineage encoding: [source_block, session_asset] lives on the CHILD BLOCK ASSET's parent[] (asset-->asset) per the existing assets.createFungiAsset parentIds path, NOT on the seeding log entity. CONTEXT.md Gray Area B verbiage said 'taxonomy_term--fungi refs' which is a minor naming misstatement (parents are asset--fungi, not taxonomy_term--fungi). See Decisions below."
key-files:
  created:
    - src/agents/alerter/src/farmos/commits/commit-seeding-session.js
    - src/agents/alerter/test/farmos/commit-seeding-session.test.js
  modified:
    - src/agents/alerter/src/farmos/assets.js
    - src/agents/alerter/src/farmos/client.js
    - src/agents/alerter/src/farmos/commits/commit-router.js
    - src/agents/alerter/test/farmos/commit-router.test.js
decisions:
  - "Session-asset fungi_type path: extended assets.createFungiAsset with allowNoFungiType: true (the option B path the plan offered). Rationale: simpler than minting a sentinel 'session' taxonomy term (which would require a one-time farmOS prereq + a fungi-type-cache lookup that returns reason='not_found' until the term exists). Single boolean flag preserves the existing create-asset code path; relationships.fungi_type is omitted only when the caller opts in. The legacy callers (Phase 40 commit-seeding) never pass the flag, so behavior is unchanged for them."
  - "Session-asset fungi_xing path: re-used the existing 'block' xing term (already provisioned in farmOS dev per Phase 40 schema lock 2026-05-11). Avoids a 'session' xing taxonomy provisioning step ahead of the live-fire ship-gate in Plan 05. If the live-fire reveals that 'block' is the wrong structural classifier for a session bundle, switch to a new 'session' xing term in a follow-up plan."
  - "Lineage encoding correction: CONTEXT.md Gray Area B describes child seeding log entity.parent[] as carrying two taxonomy_term--fungi refs. The actual schema (Phase 40 assets.js line 81 / line 85) encodes asset-->asset lineage via relationships.parent.data on the CHILD BLOCK ASSET, with each entry being { type: 'asset--fungi', id }. taxonomy_term--fungi does not exist as a JSON:API resource type; only taxonomy_term--fungi_type and taxonomy_term--fungi_xing do. The plan's <interfaces> block called this out and pre-authorized the executor to proceed on the asset-level encoding. Phase 48-02 ships the asset-level encoding; minor naming correction logged here."
  - "Partial-failure cleanup runs in REVERSE order (children first, then source blocks, then session). Matches the asset-creation stack and ensures we never DELETE a parent while its child still exists in farmOS, which would otherwise reject with FK violation on some schemas. Audit-logger emits one orphan_cleanup_failed line per failed DELETE; the handler returns ok=false either way without throwing."
  - "asset_ids returned as [] on partial failure (not the list of orphans). Rationale: from the caller's perspective (commit-watchdog + farmer-ack), the commit either succeeded or it didn't; orphans are an operator-sweep concern handled via the audit log, not via the success envelope. The orphan UUIDs are still surfaced in farmos_response.orphan_cleanup_failed_ids for the failure path."
metrics:
  duration_min: 15
  completed: 2026-05-23
---

# Phase 48 Plan 02: commitSeedingSession + per-child fan-out + orphan cleanup

One-liner: Ship `commitSeedingSession(client, draft, ctx)` plus the supporting `deleteFungiAsset` + `client.delete` primitives, wire the router DISPATCH, and prove the handler emits 1 session asset + N child assets + N seeding logs with `[source_block, session]` parent[] order, rolling back all-or-nothing on partial failure.

## What shipped

1. **`src/farmos/commits/commit-seeding-session.js`** (new, 178 lines)
   - Asset-first preflight: resolve a non-colliding session name (`inoc YYYY-MM-DD` -> `#2` -> ... -> `#9`); return `session_name_exhausted` if all 9 collide.
   - Create the anonymous session asset via `createFungiAsset({ allowNoFungiType: true, fungiXingName: 'block' })`.
   - Iterate groups; per group resolve-or-create the source block (skip for `NO_PARENT` sentinel); per child create child block with `parentIds = [sourceBlockId, sessionAssetId]` (or `[sessionAssetId]` for `NO_PARENT`) then create the seeding log referencing the child block.
   - On first failure (any source-block create, child-block create, or seeding-log create returning ok=false), reverse-order DELETE every asset created this run + emit `orphan_cleanup_failed` audit lines for each DELETE that itself fails.
   - Success envelope: `{ ok: true, asset_ids: [session, ...sources, ...children], log_ids: [...child_logs], file_ids: [], http_status: 201 }`.
   - Failure envelope: `{ ok: false, reason: 'partial_commit_failed', asset_ids: [], log_ids: [], file_ids: [], farmos_response: { original_reason, failed_at_child_index, orphan_attempted_count, orphan_cleanup_failed_count, orphan_cleanup_failed_ids } }`.
   - Whole body wrapped in try/catch -> never throws; unexpected error surfaces as `ok=false, reason=<message>`.

2. **`src/farmos/assets.js`** (modified)
   - `createFungiAsset` accepts `allowNoFungiType: true` -- omits `relationships.fungi_type` when set; the `fungiTypeName` becomes optional under that flag. Legacy callers unaffected.
   - New `deleteFungiAsset(client, assetId)` -- best-effort DELETE; invalidates the name-cache entries that pointed at the deleted UUID by reverse scan (cache is capped at 32 so scan is O(32)).

3. **`src/farmos/client.js`** (modified)
   - Added `delete(path, opts)` -- thin wrapper on `_request('DELETE', ...)`. farmOS returns 204 on a successful asset DELETE; `_request` parses no body and surfaces `ok=true`.

4. **`src/farmos/commits/commit-router.js`** (modified)
   - One-line `require('./commit-seeding-session')` + `DISPATCH.seeding_session = commitSeedingSession`. Normalize passthrough already works (the normalize() switch's default case is a no-op, which is the correct behavior for `seeding_session` -- the handler reads the groups-shape draft directly without any commit-shape translation).

5. **`test/farmos/commit-seeding-session.test.js`** (new, 7 tests, hermetic)
   - Test A: happy path on 2026-05-22 fixture (5 groups, 11 children). Assert 17 asset POSTs (1 session + 5 source blocks + 11 children), 11 seeding log POSTs, every child's `parent[]` ends with the session asset UUID.
   - Test B: name collision (`inoc 2026-05-22` already exists) -> `#2` suffix.
   - Test C: single-parent legacy (1 group, 5 children) -> still creates 1 session + 1 source + 5 children + 5 logs.
   - Test D: NO_PARENT sentinel -> child blocks get `parent[] = [sessionId]` only (no source block resolution).
   - Test E: log #4 fails (422). At that point 1 session + 4 source blocks + 4 child blocks exist = 9 assets. Reverse-order DELETE on all 9, last DELETE is the session asset. Return envelope has `failed_at_child_index: 3` (0-based), `orphan_attempted_count: 9`, `orphan_cleanup_failed_count: 0`. No audit `orphan_cleanup_failed` calls (all DELETEs succeeded).
   - Test F: same as E but every DELETE returns 500. Assert 9 audit `orphan_cleanup_failed` lines, each carrying one orphan UUID.
   - Test G: router dispatch (`commitRouter.DISPATCH.seeding_session === commitSeedingSession`).

6. **`test/farmos/commit-router.test.js`** (modified)
   - Replaced the Plan 01 placeholder test (which asserted `DISPATCH.seeding_session` is `undefined`) with a Plan 02 test that asserts it IS a function and dispatches correctly through `router.commit(...)`.

## Test E expected-count math (plan-checker correction)

The plan body's behavior block said "5 source blocks (if newly created)" for the Test E cleanup count. That overcounted: at log #4 failure (1-based; child index 3 in 0-based across the whole session), we have created source blocks for groups 1-4 only (group 5's parent has not been touched yet because we never reached child index 4). Final cleanup count: **1 session + 4 source blocks + 4 child blocks = 9 DELETEs**. The 0-based `failed_at_child_index` is 3 (the 4th child overall is index 3). The plan author flagged this as a Test E count correction; the test asserts the corrected 9 (and `failed_at_child_index: 3`).

## CONTEXT.md naming correction (Gray Area B)

CONTEXT.md Gray Area B says "each child seeding log's entity.parent[] array contains TWO taxonomy_term--fungi refs". Two issues:

1. `taxonomy_term--fungi` is not a real JSON:API resource type in the farmOS schema. Only `taxonomy_term--fungi_type` and `taxonomy_term--fungi_xing` exist. Parents on a `asset--fungi` are themselves `asset--fungi`.
2. Lineage encoding lives on the CHILD BLOCK ASSET's `relationships.parent.data`, not on the seeding log. Phase 40's `assets.createFungiAsset` already accepts `parentIds: []` and emits the correct JSON:API shape; the seeding log only carries a single-element `relationships.asset` pointing at the child block (one log = one block).

This handler ships the actual encoding (asset-->asset on the child block). Future CONTEXT.md edits should swap "taxonomy_term--fungi" -> "asset--fungi" and "each child seeding log's entity.parent[]" -> "each child block asset's relationships.parent[]".

## Verification

Per the plan's `<verification>` block:

- `npx jest test/farmos/commit-seeding-session test/farmos/commit-router --no-coverage` -> **12 passed (7 + 5), 0 failed**.
- `grep -c "commit-seeding-session" src/farmos/commits/commit-router.js` -> **1** (>= 1, target met).
- `grep -v '^//' src/farmos/commits/commit-seeding-session.js | grep -c "sessionAssetId"` -> **4** (>= 3, target met).

Full farmos suite (regression sweep on assets.js + client.js modifications):

```
PASS test/farmos/assets.test.js
PASS test/farmos/client.test.js
PASS test/farmos/commit-seeding.test.js
PASS test/farmos/commit-activity.test.js
PASS test/farmos/commit-input.test.js
PASS test/farmos/commit-observation.test.js
PASS test/farmos/commit-harvest.test.js
PASS test/farmos/commit-watchdog.test.js
PASS test/farmos/commit-db.test.js
PASS test/farmos/commit-router.test.js     (+1 updated test)
PASS test/farmos/commit-seeding-session.test.js   (+7 new tests)
PASS test/farmos/logs.test.js
... (20 suites passed, 187 tests, 8 skipped)
```

## Deviations from Plan

**1. [Rule 2 - Critical correctness] Client.delete was missing; added the verb**

- **Found during:** writing commit-seeding-session.js, when designing the orphan-cleanup branch.
- **Issue:** `assets.deleteFungiAsset` needs `client.delete(path)` to issue a DELETE against `/api/asset/fungi/{uuid}`. The existing `client.js` only exposed `get/post/patch/postBinary/head` -- there was no DELETE verb. Without one, the all-or-nothing rollback contract cannot be implemented.
- **Fix:** Added a 1-line `del = (p, o) => _request('DELETE', p, null, o)` wrapper and exposed it as `delete`. farmOS returns 204 on a successful asset DELETE; `_request` already handles no-body responses.
- **Rationale:** Rule 2 -- the partial-failure cleanup contract IS the plan's must-have-truth #4 ("if any child seeding log POST returns 4xx, the handler issues a DELETE on the session asset"). Without a DELETE verb on the client, that truth cannot ship. The plan's `<files>` block listed `assets.js` for `deleteFungiAsset` and the `<read_first>` block called out "client.js (the underlying http client; check whether it exposes a delete method)" -- the executor was pre-authorized to add the verb when not present.

**2. [Naming correction, not a behavior change] CONTEXT.md Gray Area B "taxonomy_term--fungi" -> "asset--fungi"**

- **Found during:** designing the parent[] encoding for child blocks.
- **Issue:** CONTEXT.md describes lineage parents as `taxonomy_term--fungi` refs. That resource type does not exist; child block parents are themselves `asset--fungi`.
- **Fix:** Ship the actual encoding (asset-->asset). Logged the correction in the SUMMARY's Decisions block; the plan's `<interfaces>` block had already pre-authorized this resolution ("the actual encoding is on asset--fungi.parent[]. PROCEED on the asset-level encoding").

No other deviations. No auth gates. No blockers.

## Out-of-scope items observed (NOT touched per Rule 3)

While executing Plan 02 I observed the following uncommitted edits in the working tree, which were NOT part of Plan 02's `<files>` block and which I left untouched:

- `src/extraction/preview-builder.js` (modified)
- `test/extraction/sanitize.test.js` (modified)
- `test/extraction/preview-builder-session.test.js` (new, untracked)

These appear to be Plan 03 / Plan 04 work-in-progress on the seeding-session preview renderer (Phase 48 Plan 03 is "preview-builder seeding_session branch" per the phase plan index). Per CLAUDE.md Rule 3 (Surgical Changes) I did not stage or commit them; subsequent plans will handle.

A related side effect: the unrelated WIP causes two extraction-integration test failures that surface in a full `npx jest` run:

- `test/extraction/integration/seeding-session-may22.test.js` -- asserts on the Phase 47 placeholder preview text which the WIP renderer has already replaced.
- `test/extraction/integration/seeding-session-photo-absent.test.js` -- same root cause.

I confirmed via `git stash` -> rerun -> `git stash pop` that **both failures pre-exist Plan 02's changes** (they stem from the unrelated `preview-builder.js` WIP). Plan 02's targeted verification (`test/farmos/commit-seeding-session`, `test/farmos/commit-router`) is 100% green; the failing suites are out-of-scope for this plan.

## Self-Check

- `src/agents/alerter/src/farmos/commits/commit-seeding-session.js` exists. FOUND.
- `src/agents/alerter/src/farmos/commits/commit-router.js` contains `commit-seeding-session` require. FOUND.
- `src/agents/alerter/src/farmos/assets.js` exports `deleteFungiAsset`. FOUND.
- `src/agents/alerter/src/farmos/client.js` exposes `delete`. FOUND.
- `src/agents/alerter/test/farmos/commit-seeding-session.test.js` exists, 7 tests pass. FOUND.
- `src/agents/alerter/test/farmos/commit-router.test.js` Plan-02-updated test passes. FOUND.
- Targeted command `npx jest test/farmos/commit-seeding-session test/farmos/commit-router --no-coverage` -> 12 passed, 0 failed. FOUND.
- Full `test/farmos` suite -> 187 passed, 8 skipped, 0 failed. FOUND.

## Self-Check: PASSED
