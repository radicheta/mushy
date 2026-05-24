---
phase: 51
plan: 03
subsystem: alerter/farmos
tags: [upsert, assets, tdd, wave-2]
requires:
  - merge.mergeAssetFields (51-02)
  - merge.IdentityMutationError (51-02)
  - mock-client.patch + revisionIds + force412 (51-01)
provides:
  - assets.upsertFungiAsset
  - assets.isStubAsset
  - assets.STUB_BACKFILL_MARKER
  - assets.__test_isMergeNoop (test hook)
affects:
  - Plan 04 (upsertLog) — independent, but mirrors the return-shape contract
  - Plan 05 (commit-migration) — will replace createFungiAsset / resolveOrCreateAsset call sites in commit-seeding* with upsertFungiAsset
tech_stack_added: []
tech_stack_patterns:
  - "lookup-merge-or-create primitive returning structured {ok, outcome, conflicts, etag_source} on every code path"
  - "Soft revision_id compare via re-GET (farmOS doesn't honor If-Match — degrade-not-block per CONTEXT.md / RESEARCH §3)"
  - "Shared _buildAssetBody helper so POST and PATCH paths emit byte-identical attribute/relationship shapes"
  - "Normalize incoming SCALAR_REL_FIELDS from array form (POST shape) to singleton form (GET shape) so mergeAssetFields sees like-with-like"
key_files_created: []
key_files_modified:
  - src/agents/alerter/src/farmos/assets.js
  - src/agents/alerter/test/farmos/assets.test.js
decisions:
  - "Identity mutation never bubbles the IdentityMutationError throw — caught and surfaced as {ok:false, reason:'identity_mutation', http_status:null}"
  - "Soft revision_id retry budget = exactly 1 (CONTEXT.md lock); a 2nd race surfaces as outcome='noop', reason='concurrency_loss'"
  - "_isMergeNoop normalizes notes to value-only and strips drupal_internal__revision_id from compare — server-injected format / revision metadata cannot trick the engine into a spurious PATCH"
  - "incoming.relationships.{fungi_type,fungi_xing} normalized from {data:[{...}]} (createFungiAsset POST shape) to {data:{...}} (farmOS GET shape) before mergeAssetFields runs; createFungiAsset's POST payload is unchanged for back-compat"
  - "createFungiAsset refactored to use a shared _buildAssetBody helper; all 9 existing assets.test.js cases still pass with no edits"
  - "__test_isMergeNoop exported off module.exports (rename-prefix) so future tests can target the predicate without re-implementing it"
metrics:
  duration_minutes: ~15
  tasks_total: 1
  tasks_completed: 1
  files_modified: 2
  files_created: 0
  test_count_assets_before: 9
  test_count_assets_after: 23
  completed: 2026-05-24
---

# Phase 51 Plan 03: upsertFungiAsset Summary

Add `upsertFungiAsset`, `isStubAsset`, and `STUB_BACKFILL_MARKER` to
`src/agents/alerter/src/farmos/assets.js`. This is the lookup-merge-or-create
primitive that Plan 05's commit-path migration will route through, replacing
the create-only `createFungiAsset` and find-and-return-unchanged
`resolveOrCreateAsset`. Includes soft revision_id concurrency check (degraded
UPSERT-04 — farmOS doesn't honor `If-Match` per 51-RESEARCH §3).

## Tasks Executed

| # | Name | Commits | Outcome |
|---|------|---------|---------|
| 1 | TDD: add isStubAsset + upsertFungiAsset behind UPSERT-01/04/05 contract | `75473ab` (RED), `ed1302f` (GREEN) | 14 new it() blocks added; 23/23 in assets.test.js green |

## Behavior Coverage (all 14 new cases green)

**`isStubAsset` (Phase 51 UPSERT-05) — 6 cases:**

| Behavior | Status |
|----------|--------|
| Marker hit on plain notes.value | green |
| Marker hit when one of several `\n---\n`-separated entries | green |
| Returns false for ordinary notes | green |
| Returns false when notes attribute is absent | green |
| Returns false for null / undefined asset | green |
| `STUB_BACKFILL_MARKER` constant exports the expected literal | green |

**`upsertFungiAsset` (Phase 51 UPSERT-01/04/05) — 8 cases:**

| Branch | Status |
|--------|--------|
| Miss → POST via createFungiAsset, outcome='created' | green |
| Hit-mergeable (new parent[]) → PATCH with merged set-union, outcome='patched', etag_source='soft_compare' | green |
| Hit-noop (incoming already present) → no PATCH, outcome='noop' | green |
| Hit-with-conflicts (fungi_type mismatch) → no PATCH, conflicts populated | green |
| Identity mutation (existing name on disk differs) → {ok:false, reason:'identity_mutation', http_status:null}; never throws | green |
| Soft-compare retry under continuous race → exactly 1 retry, then outcome='noop', reason='concurrency_loss', etag_source='soft_compare', no PATCH | green |
| Stub enrichment → outcome='patched'; merged notes preserves marker; merged parent[] contains incoming parents; conflicts=[] | green |
| Missing revision_id on GET → etag_source='absent', PATCH still issued without If-Match header (degrade-not-block) | green |

## Acceptance Criteria Verification (all pass)

- ✓ `grep -nE "^function upsertFungiAsset|^async function upsertFungiAsset" assets.js` → 1 hit (line 185)
- ✓ `grep -c "STUB_BACKFILL_MARKER" assets.js` → 3 (≥2 required: declaration + export + usage in `isStubAsset`)
- ✓ `grep -c "isStubAsset" assets.js` → 2 (declaration + export)
- ✓ `grep -c "upsertFungiAsset" assets.js` → 4 (declaration + comment refs + export)
- ✓ `module.exports` includes `upsertFungiAsset, isStubAsset, STUB_BACKFILL_MARKER`
- ✓ All 9 existing assets.test.js cases still pass (no edits to existing tests)
- ✓ All 14 new cases pass
- ✓ Soft-compare retry count is exactly 1 (test-enforced via `bumpCounter === 4`: 2 GETs per attempt × 2 attempts)
- ✓ `createFungiAsset` still exported (back-compat preserved; the grep-gate against commit paths is Plan 05's job)

## Regression Check

`cd src/agents/alerter && npx jest test/farmos/ --runInBand`:
- **24 suites passed, 1 skipped, 1 failed (pre-existing)** — 240 passing, 8 skipped
- The single failure is `test/farmos/integration/extractor-to-commit.test.js`: `Cannot find module '@anthropic-ai/sdk'`. This is the same pre-existing resolver issue documented in 51-01-SUMMARY and 51-02-SUMMARY. Unrelated to Plan 03; per the fix-attempt-limit rule (out-of-scope for this task), not touched.

Plan 03's new code paths exercise `mock-client.patch`, `mock-client.delete` (indirectly via `createFungiAsset`'s post path), GET-by-id, and the `revisionIds` seed — i.e. all of Plan 01's Wave-0 infrastructure is now load-bearing for real test cases.

## Deviations from Plan

**None affecting plan intent**, but three small implementation adjustments worth recording so Plan 05 (which consumes this) knows what to expect:

1. **[Rule 2 — missing critical functionality] Normalize incoming `fungi_type`/`fungi_xing` array→singleton before merge.**
   - Found during: GREEN gate first failures (hit-noop, hit-with-conflicts initially returned outcome='patched' instead of 'noop'/'noop'-with-conflicts).
   - Root cause: `createFungiAsset` POSTs scalar singleton relationships in `{data: [{...}]}` array form (existing Phase 40 behavior; covered by the line-35 test assertion `sent.data.relationships.fungi_type.data[0]`). farmOS GET-by-id returns them in singleton `{data: {...}}` form. `mergeAssetFields`'s SCALAR_REL_FIELDS dispatch in `merge.js` reads `rel.data.id` (singleton) — comparing the two shapes would yield `undefined !== 'ft-dt'` and surface false conflicts (or noop misses).
   - Fix: in `upsertFungiAsset`, after `_buildAssetBody` runs, collapse `incoming.relationships.fungi_type` and `.fungi_xing` from `{data:[{...}]}` to `{data:{...}}` before calling `mergeAssetFields`. `createFungiAsset`'s POST payload is unchanged — back-compat preserved.
   - Files: src/agents/alerter/src/farmos/assets.js
   - Commit: `ed1302f`

2. **[Rule 1 — bug] `_isMergeNoop` must normalize notes-format and strip server-side revision metadata.**
   - Found during: hit-noop test still failed after fix #1.
   - Root cause: existing-on-disk notes are `{value: ...}` (no `format` set in mock fixtures, and farmOS GET also commonly omits it). `_buildAssetBody` emits `{value: ..., format: 'plain_text'}` (createFungiAsset legacy). After merge, the merged notes carry `format` while existing did not — a stringify compare flagged the asset as "changed" and triggered a spurious PATCH. Same class of issue applies to `drupal_internal__revision_id`: it lives in existing GET responses but is never something we'd PATCH, so it must be excluded from the noop test.
   - Fix: `_isMergeNoop` projects `attributes.notes` to value-only and deletes `drupal_internal__revision_id` from both sides before stringify compare.
   - Files: src/agents/alerter/src/farmos/assets.js
   - Commit: `ed1302f`

3. **[Plan-clarification] `_buildAssetBody` helper extracted (plan called for this).**
   - The plan explicitly asked for this refactor (Plan §action item 4 sub-bullet "extract to a private helper `_buildAssetBody(opts, client)`"). Implemented as `_buildAssetBody(client, opts)` (consistent param order with the rest of the module). `createFungiAsset` now thin-wraps it; all 9 existing tests still pass.

## Authentication Gates

None.

## Known Stubs

None — the only stub-related work in this plan is the `isStubAsset` *predicate* and `STUB_BACKFILL_MARKER` *constant*, which are explicit features per UPSERT-05. They detect prod stubs (the 4 May-22 UUIDs in `.planning/notes/2026-05-24-prod-write-receipt-uuids.json`); they do not introduce new stubs in the codebase.

## Threat Flags

None — `upsertFungiAsset` does not introduce new network surface beyond what `createFungiAsset` + `findAssetByName` + `client.patch` already expose. The threat register mitigations from the PLAN are in force:

- **T-51-05 (concurrent writer)**: mitigated via soft revision_id re-GET + one-shot retry; concurrency_loss surfaces as `outcome='noop'` + `reason='concurrency_loss'`, never silent.
- **T-51-06 (stub marker erasure)**: mitigated structurally — `mergeAssetFields`'s notes-dedup preserves the marker as just-another-entry; the stub-enrichment test asserts `isStubAsset(merged)` remains true post-PATCH.
- **T-51-07 (information disclosure in conflict log)**: accepted per PLAN.

## Self-Check: PASSED

Files exist:
- ✓ FOUND: src/agents/alerter/src/farmos/assets.js (modified)
- ✓ FOUND: src/agents/alerter/test/farmos/assets.test.js (modified)

Commits exist on branch `worktree-agent-a94ed1f45f2e5fdff`:
- ✓ FOUND: `75473ab` test(51-03): RED — failing tests for upsertFungiAsset + isStubAsset + STUB_BACKFILL_MARKER
- ✓ FOUND: `ed1302f` feat(51-03): GREEN — upsertFungiAsset + isStubAsset + soft revision_id compare

## TDD Gate Compliance

- RED commit: `75473ab` — 14 new failing it() blocks (all `TypeError: assets.upsertFungiAsset is not a function` / missing-export shape, as expected for RED gate)
- GREEN commit: `ed1302f` — 23/23 in assets.test.js green; full farmos suite has no new regressions
- REFACTOR: not needed (initial implementation already compact and per-PATTERNS.md; the two GREEN-gate fixes were correctness adjustments, not cleanup)

Gate sequence intact.

## Downstream Consumption (Plans 04-06)

Plan 04 (upsertLog) — mirrors this return-shape contract:
```javascript
{ ok: true,  assetId, outcome: 'created' | 'patched' | 'noop', conflicts: [], etag_source: 'soft_compare' | 'absent' | null, http_status: 200|201|null, reason?: 'concurrency_loss' }
{ ok: false, reason: 'identity_mutation' | 'http_<N>' | ..., http_status: <N>|null, conflicts: [], etag_source: null }
```

Plan 05 (commit-migration) — call site migrations:
- `createFungiAsset(client, opts)` → `upsertFungiAsset(client, opts)` in commit-seeding-session.js, commit-seeding.js
- `resolveOrCreateAsset(client, opts)` → `upsertFungiAsset(client, opts)` (the `reused: true` flag becomes `outcome === 'noop'` for the equivalent meaning of "no write issued")
- Grep gate from acceptance criteria: `grep -rE "createFungiAsset|resolveOrCreateAsset" src/agents/alerter/src/farmos/commits/` should return zero matches post-migration.
