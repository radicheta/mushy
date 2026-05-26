---
phase: 51
plan: 03
type: execute
wave: 2
depends_on: ["51-01", "51-02"]
files_modified:
  - src/agents/alerter/src/farmos/assets.js
  - src/agents/alerter/test/farmos/assets.test.js
autonomous: true
requirements: [UPSERT-01, UPSERT-04, UPSERT-05]
must_haves:
  truths:
    - "upsertFungiAsset(client, opts) returns {ok, assetId, outcome, conflicts, etag_source} on every code path"
    - "Found-and-mergeable → PATCH with merged body; outcome='patched'"
    - "Not-found → POST via createFungiAsset; outcome='created'"
    - "Found-with-conflicts → no PATCH; outcome='noop' with conflicts populated"
    - "isStubAsset detects STUB_BACKFILL_MARKER in notes.value"
    - "Soft revision_id compare: re-GET before PATCH if revision moved, retry merge once; track in etag_source"
  artifacts:
    - path: "src/agents/alerter/src/farmos/assets.js"
      provides: "upsertFungiAsset, isStubAsset, STUB_BACKFILL_MARKER (in addition to existing exports)"
      contains: "function upsertFungiAsset"
    - path: "src/agents/alerter/test/farmos/assets.test.js"
      provides: "upsert hit/miss/conflict/stub coverage; soft-compare retry test"
  key_links:
    - from: "assets.js upsertFungiAsset"
      to: "merge.js mergeAssetFields"
      via: "require('./merge')"
      pattern: "require\\(['\"]\\./merge['\"]\\)"
    - from: "assets.js upsertFungiAsset"
      to: "audit-logger outcome dimension"
      via: "return shape with outcome+conflicts+etag_source"
      pattern: "outcome:"
---

<objective>
Add `upsertFungiAsset`, `isStubAsset`, and `STUB_BACKFILL_MARKER` to assets.js. This is the lookup-merge-or-create primitive that commit-path code (Plan 05) will route through, replacing the create-only `createFungiAsset` and find-and-return-unchanged `resolveOrCreateAsset`. Includes soft revision_id concurrency check (degraded UPSERT-04 — farmOS doesn't honor If-Match per RESEARCH §3).

Purpose: Single entry point that merges existing field state with incoming field state, surfaces conflicts structurally, and never silently discards data.
Output: 3 new exports on assets.js, Jest coverage of all outcome branches.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-SPEC.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-CONTEXT.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-RESEARCH.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-PATTERNS.md
@src/agents/alerter/src/farmos/assets.js
@src/agents/alerter/src/farmos/merge.js

<interfaces>
From src/agents/alerter/src/farmos/merge.js (from Plan 02):
```javascript
module.exports = { mergeAssetFields, IdentityMutationError, STABLE_NOTES_SEPARATOR };
// mergeAssetFields(existing, incoming) → {merged, conflicts}
```

From src/agents/alerter/src/farmos/assets.js (existing):
```javascript
// findAssetByName(client, name) → {found: bool, assetId?: string}
// createFungiAsset(client, opts) → {ok, assetId, http_status, reason?}
// resolveOrCreateAsset(client, opts) → returns existing or creates (DEPRECATED for commits post-51)
// deleteFungiAsset(client, id) → for _cleanup paths
// _clearCache() → test hook
```

From src/agents/alerter/test/farmos/mock-client.js (from Plan 01):
```javascript
// makeMockClient({knownAssetsByName, force412Ids?, revisionIds?}) →
//   {get, post, patch, delete, postBinary, _calls, _created}
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add isStubAsset, STUB_BACKFILL_MARKER, and upsertFungiAsset to assets.js</name>
  <files>src/agents/alerter/src/farmos/assets.js, src/agents/alerter/test/farmos/assets.test.js</files>
  <read_first>
    - src/agents/alerter/src/farmos/assets.js (full file — to understand existing exports, NAME_CACHE, createFungiAsset internals at lines 53-111, module.exports at line 138)
    - src/agents/alerter/src/farmos/merge.js (Plan 02 output — exact export names + return shape)
    - src/agents/alerter/test/farmos/assets.test.js (existing test patterns — preserve all current tests)
    - 51-PATTERNS.md §assets.js (required additions + return shape contract + cache invariant comment)
    - 51-CONTEXT.md §"Module layout" + §"Conflict-surfacing semantics" + §"Etag-guarded PATCH"
    - 51-RESEARCH.md §3 (soft revision_id compare details — degraded UPSERT-04)
    - .planning/notes/2026-05-24-prod-write-receipt-uuids.json (the 4 prod stub UUIDs for test fixtures)
  </read_first>
  <behavior>
    Jest tests in assets.test.js (all NEW, do not modify existing tests):

    **isStubAsset:**
    - returns true for asset with notes.value containing 'STUB - awaits 2025-paper-scan backfill'
    - returns true even when STUB marker is one of several entries separated by '\n---\n'
    - returns false for asset with notes.value='ordinary notes'
    - returns false for asset with no notes attribute
    - returns false for null asset

    **upsertFungiAsset miss path:**
    - findAssetByName returns {found:false} → POST is called via createFungiAsset → returns {ok:true, assetId, outcome:'created', http_status:201}

    **upsertFungiAsset hit-mergeable path:**
    - findAssetByName returns {found:true, assetId:'a1'} → GET fetches existing asset (revision_id=1) → mergeAssetFields returns conflicts=[] and a non-noop merged body → PATCH called → returns {ok:true, assetId:'a1', outcome:'patched', conflicts:[], etag_source:'soft_compare', http_status:200}
    - PATCH body has merged parent[] reflecting set-union

    **upsertFungiAsset hit-noop path:**
    - existing already contains incoming fields → mergeAssetFields returns conflicts=[] and merged equals existing structurally → NO PATCH issued → returns {ok:true, assetId, outcome:'noop', conflicts:[]}
    - Assertion: mockClient.patch was NOT called

    **upsertFungiAsset hit-with-conflicts path:**
    - existing fungi_type='ft-shi', incoming fungi_type='ft-koy' → mergeAssetFields returns conflicts.length===1 → NO PATCH → returns {ok:true, assetId, outcome:'noop', conflicts:[{field:'fungi_type', ...}]}

    **upsertFungiAsset identity-mutation path:**
    - existing name='X', incoming name='Y' → mergeAssetFields throws IdentityMutationError → upsertFungiAsset returns {ok:false, reason:'identity_mutation', http_status:null} (NEVER bubbles the throw — structured error per CONTEXT.md result-object contract)

    **upsertFungiAsset soft-compare retry:**
    - First GET returns asset with revision_id=1
    - Between merge and PATCH, simulate revision moved by configuring mock so second GET returns revision_id=2 (use a counter on mock or call_count hook)
    - upsertFungiAsset detects revision moved (after PATCH would have been issued, re-GET shows revision_id ≠ pre-merge revision_id) → retries merge ONCE → if revision still moves, returns {ok:true, outcome:'noop', etag_source:'soft_compare', reason:'concurrency_loss'}
    - Verify retry count is exactly 1 (not unbounded)

    **upsertFungiAsset stub enrichment:**
    - Existing asset is a stub (notes contains STUB_BACKFILL_MARKER); incoming carries real fungi_type + parents → outcome='patched', merged notes preserves marker, merged parent[] contains incoming parents, conflicts=[]
  </behavior>
  <action>
    **Edits to `src/agents/alerter/src/farmos/assets.js`:**

    1. Add near top (after existing constants):
    ```javascript
    // Phase 51 UPSERT-05: marker string in notes.value identifies hand-stubbed
    // ancestors awaiting 2025-paper-scan backfill. See
    // .planning/notes/2026-05-24-prod-write-receipt.md (4 stubs in prod farmOS).
    const STUB_BACKFILL_MARKER = 'STUB - awaits 2025-paper-scan backfill';
    ```

    2. Add `require('./merge')`:
    ```javascript
    const { mergeAssetFields, IdentityMutationError } = require('./merge');
    ```

    3. Add `isStubAsset(asset)` per PATTERNS.md §assets.js item 2.

    4. Add `upsertFungiAsset(client, opts)`:
       - **Signature:** `async function upsertFungiAsset(client, opts)` where opts mirrors createFungiAsset (name, fungiTypeName, fungiXingName, parentIds, qrCodes, farmIdTag, status, draftId, notes).
       - **Lookup:** `const lookup = await findAssetByName(client, opts.name);`
       - **Miss branch:** if `!lookup.found` → delegate to `createFungiAsset(client, opts)` → on success wrap as `{ok:true, assetId:res.assetId, outcome:'created', conflicts:[], etag_source:null, http_status:res.http_status}`; on failure pass-through `{ok:false, reason, http_status}`.
       - **Hit branch:**
         - GET `/api/asset/fungi/${lookup.assetId}` → existing asset body. Capture `preMergeRevisionId = existing.attributes.drupal_internal__revision_id ?? null`.
         - Build `incoming` from opts using the SAME payload assembly used by createFungiAsset (extract to a private helper `_buildAssetBody(opts, client)` that both createFungiAsset and upsertFungiAsset call — refactor createFungiAsset to use it). The incoming object must match the {attributes, relationships} shape mergeAssetFields expects.
         - Try `const {merged, conflicts} = mergeAssetFields(existing, incoming)`. Catch IdentityMutationError → return `{ok:false, reason:'identity_mutation', http_status:null, conflicts:[], etag_source:null}`.
         - If `conflicts.length > 0` → return `{ok:true, assetId:lookup.assetId, outcome:'noop', conflicts, etag_source:'soft_compare', http_status:null}` (no PATCH).
         - If `merged` deep-equals `existing` (use `_isMergeNoop(existing, merged)` helper — JSON.stringify compare on attributes+relationships subset is sufficient) → return `{ok:true, assetId:lookup.assetId, outcome:'noop', conflicts:[], etag_source:'soft_compare', http_status:null}`.
         - Otherwise issue PATCH:
           - **Soft-compare guard:** before PATCH, re-GET the asset. If `currentRevisionId !== preMergeRevisionId` → retry the full merge cycle ONCE (re-GET → re-merge with same `incoming` → if still moved → return `{ok:true, outcome:'noop', reason:'concurrency_loss', etag_source:'soft_compare', conflicts:[]}`).
           - PATCH path: `client.patch('/api/asset/fungi/' + lookup.assetId, {data:{type:'asset--fungi', id:lookup.assetId, attributes:merged.attributes, relationships:merged.relationships}}, {headers:{'If-Match': preMergeRevisionId != null ? String(preMergeRevisionId) : undefined}})`. If revisionId is null → set `etag_source = 'absent'` and SKIP the If-Match header (degrade-not-block per CONTEXT.md).
           - On success: `{ok:true, assetId:lookup.assetId, outcome:'patched', conflicts:[], etag_source: preMergeRevisionId != null ? 'soft_compare' : 'absent', http_status:200}`
           - On HTTP failure: `{ok:false, reason:'http_'+status, http_status:status, conflicts:[], etag_source:'soft_compare'}`

    5. Add `_isMergeNoop(existing, merged)` private helper (export as `__test_isMergeNoop` for unit-testability if useful).

    6. Update `module.exports`:
    ```javascript
    module.exports = {
      findAssetByName, createFungiAsset, resolveOrCreateAsset, deleteFungiAsset, _clearCache,
      upsertFungiAsset, isStubAsset, STUB_BACKFILL_MARKER,
    };
    ```

    7. Add cache invariant comment near NAME_CACHE block (verbatim per PATTERNS.md):
    ```javascript
    // NAME_CACHE survives PATCH without invalidation because UPSERT-03's
    // IdentityMutationError on name change makes (name -> id) stable. If a future
    // feature adds rename support, the cache MUST be invalidated in upsertFungiAsset.
    ```

    **Edits to `src/agents/alerter/test/farmos/assets.test.js`:**

    Add a new `describe('upsertFungiAsset (Phase 51 UPSERT-01/04/05)', () => { ... })` block covering all behaviors above. Use `makeMockClient` from `./mock-client` (extended in Plan 01). Seed `knownAssetsByName` with assets carrying explicit `attributes.drupal_internal__revision_id` values to drive the soft-compare test.

    Also add `describe('isStubAsset (Phase 51 UPSERT-05)', () => { ... })` block.

    Do NOT modify existing assets.test.js test cases. Only add.

    Commit once when all new tests are green:
    `feat(51-03): UPSERT-01/04/05 — upsertFungiAsset + isStubAsset + soft revision_id compare`

    REMINDER: createFungiAsset stays exported. The grep gate (Plan 05) targets COMMITS dir, not assets.js itself.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/farmos/assets.test.js --runInBand</automated>
  </verify>
  <acceptance_criteria>
    - All existing assets.test.js cases still pass
    - All new isStubAsset cases pass (5+ cases)
    - All new upsertFungiAsset cases pass: miss/hit-mergeable/hit-noop/hit-with-conflicts/identity-mutation/soft-compare-retry/stub-enrichment
    - `grep -nE "^function upsertFungiAsset|^async function upsertFungiAsset" src/agents/alerter/src/farmos/assets.js` returns ≥1
    - `grep -c "STUB_BACKFILL_MARKER" src/agents/alerter/src/farmos/assets.js` returns ≥2 (declaration + export)
    - `grep -c "isStubAsset" src/agents/alerter/src/farmos/assets.js` returns ≥2
    - `grep -c "upsertFungiAsset" src/agents/alerter/src/farmos/assets.js` returns ≥2 (declaration + export)
    - module.exports includes upsertFungiAsset, isStubAsset, STUB_BACKFILL_MARKER
    - No regression: `cd src/agents/alerter && npx jest test/farmos/ --runInBand` exits 0
  </acceptance_criteria>
  <done>upsertFungiAsset live behind the same return-shape contract; Plan 05 can migrate commit call sites.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| alerter → farmOS PATCH | upsert writes flow into farmOS; concurrent writes from manual edits possible |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-51-05 | Tampering | concurrent writer overwrites our merge | mitigate | soft revision_id compare via re-GET; one-shot retry; concurrency_loss surfaces as outcome=noop in audit log (not silent) |
| T-51-06 | Repudiation | stub-asset enrichment loses the STUB marker | mitigate | mergeAssetFields notes-dedup preserves marker as just-another-entry; test #7 of Plan 02 + stub-enrichment test here enforce |
| T-51-07 | Information disclosure | scalar conflict logged includes field values | accept | fungi_type/fungi_xing/status are not sensitive; conflict surfacing required by UPSERT-03 |
</threat_model>

<verification>
- Full farmos suite green
- New code paths exercise mock-client patch + delete + GET-by-id + 412 surface from Plan 01
</verification>

<success_criteria>
- 3 new exports on assets.js
- Jest coverage of all 7+ behaviors
- Soft-compare retry count is exactly 1 (test-enforced)
- createFungiAsset still exported (no break for non-commit callers)
</success_criteria>

<output>
Create `.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-03-SUMMARY.md` when done.
</output>
