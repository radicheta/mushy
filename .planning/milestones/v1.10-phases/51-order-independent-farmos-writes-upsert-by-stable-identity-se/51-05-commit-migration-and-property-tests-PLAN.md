---
phase: 51
plan: 05
type: execute
wave: 3
depends_on: ["51-01", "51-02", "51-03", "51-04"]
files_modified:
  - src/agents/alerter/src/farmos/commits/commit-seeding-session.js
  - src/agents/alerter/src/farmos/commits/commit-seeding.js
  - src/agents/alerter/src/farmos/commits/commit-observation.js
  - src/agents/alerter/test/farmos/commit-seeding-session.test.js
  - src/agents/alerter/test/farmos/commit-seeding.test.js
  - src/agents/alerter/test/farmos/upsert-property.test.js
autonomous: true
requirements: [UPSERT-01, UPSERT-02, UPSERT-06]
must_haves:
  truths:
    - "Every farmOS asset write in commits/ flows through upsertFungiAsset"
    - "Every seeding log write in commits/ flows through upsertLog"
    - "grep gate: zero matches for createFungiAsset|resolveOrCreateAsset in commits/"
    - "Replaying the May-22 seeding session against an already-populated farmOS produces zero net new assets and zero net new logs"
    - "20 random permutations of (May-22, Jan-18, Mar-04) inoc events converge to byte-equivalent final state"
    - "(stub-mint, real-inoc-write) sequence equals (real-inoc-write only) at the asset field level"
    - "fungi_type conflict (incoming KOY vs existing SHI) surfaces as structured conflict; merged asset retains existing value"
  artifacts:
    - path: "src/agents/alerter/src/farmos/commits/commit-seeding-session.js"
      provides: "migrated to upsertFungiAsset + upsertLog"
    - path: "src/agents/alerter/src/farmos/commits/commit-seeding.js"
      provides: "migrated to upsertFungiAsset + upsertLog"
    - path: "src/agents/alerter/test/farmos/upsert-property.test.js"
      provides: "3 property tests (order-independence, stub-enrichment, conflict-surfacing) with 20× permutations"
      min_lines: 120
  key_links:
    - from: "commit-seeding-session.js"
      to: "assets.js upsertFungiAsset"
      via: "require('../assets').upsertFungiAsset"
      pattern: "upsertFungiAsset"
    - from: "commit-seeding-session.js"
      to: "logs.js upsertLog"
      via: "require('../logs').upsertLog"
      pattern: "upsertLog"
    - from: "upsert-property.test.js"
      to: "fixtures/multi-parent-inoc-trio.json"
      via: "require('./fixtures/multi-parent-inoc-trio.json')"
      pattern: "multi-parent-inoc-trio"
---

<objective>
Migrate every commit-path call site to the upsert primitives, prove the grep gate clean, and ship the property test suite that attests order independence + stub enrichment + conflict surfacing. This is the requirement-coverage wave for UPSERT-01/02/06 acceptance criteria.

Purpose: Without commit-path migration the upsert primitives are dormant. Without property tests the order-independence claim is unattested.
Output: 3 migrated commit files (1 of them review-only), 2 updated commit test files, 1 new property test file with ≥3 properties × 20 permutations.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-SPEC.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-CONTEXT.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-PATTERNS.md
@src/agents/alerter/src/farmos/commits/commit-seeding-session.js
@src/agents/alerter/src/farmos/commits/commit-seeding.js
@src/agents/alerter/src/farmos/commits/commit-observation.js

<interfaces>
From Plan 03 (assets.js):
```javascript
// upsertFungiAsset(client, opts) → {ok, assetId, outcome, conflicts, etag_source, http_status, reason?}
// Same opts shape as createFungiAsset; same return ok/assetId contract for callers.
```

From Plan 04 (logs.js):
```javascript
// upsertLog(client, type, opts) → {ok, logId, outcome, conflicts, etag_source, http_status, warnings?, reason?}
```

From Plan 01 fixture:
```javascript
// require('./fixtures/multi-parent-inoc-trio.json') → {events, expected_final, stub_uuids}
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Migrate commit-seeding-session.js + commit-seeding.js to upsert primitives</name>
  <files>src/agents/alerter/src/farmos/commits/commit-seeding-session.js, src/agents/alerter/src/farmos/commits/commit-seeding.js, src/agents/alerter/src/farmos/commits/commit-observation.js, src/agents/alerter/test/farmos/commit-seeding-session.test.js, src/agents/alerter/test/farmos/commit-seeding.test.js</files>
  <read_first>
    - src/agents/alerter/src/farmos/commits/commit-seeding-session.js (full file — call sites at lines 121-137, 147-160, 162-168)
    - src/agents/alerter/src/farmos/commits/commit-seeding.js (full file — call sites at lines 49-58, 69-75)
    - src/agents/alerter/src/farmos/commits/commit-observation.js (full file — confirm no createFungiAsset/resolveOrCreateAsset calls)
    - src/agents/alerter/test/farmos/commit-seeding-session.test.js (full file — existing assertions that may now reference `outcome`)
    - src/agents/alerter/test/farmos/commit-seeding.test.js (full file)
    - 51-PATTERNS.md §commit-seeding-session.js (the three call-site rewrites)
  </read_first>
  <action>
    **commit-seeding-session.js:**

    1. Swap require: ensure `const { upsertFungiAsset } = require('../assets')` and `const { upsertLog } = require('../logs')` (keep existing imports intact, just add the upsert names).

    2. **Call site 1** (lines 121-137 — source-block resolve-or-create). Replace the entire `if (found.found) {...} else {...}` block with the upsert pattern from PATTERNS.md §commit-seeding-session.js call site 1:
       ```javascript
       const r = await upsertFungiAsset(client, { name: parentName, fungiTypeName: species, fungiXingName: 'block', draftId });
       if (!r.ok) return _cleanup(client, ctx, draft, createdAssetIds, r.reason || 'source_block_upsert_failed', childIndex);
       sourceBlockId = r.assetId;
       if (r.outcome === 'created') createdAssetIds.push(sourceBlockId);  // only created assets roll back
       // emit audit outcome
       if (ctx.auditLogger && typeof ctx.auditLogger.logCommit === 'function') {
         try { await ctx.auditLogger.logCommit('upsert_outcome', draft, { asset_ids:[sourceBlockId], outcome:r.outcome, conflicts:r.conflicts, etag_source:r.etag_source }); } catch (_) {}
       }
       ```

    3. **Call site 2** (lines 147-160 — child block create). Swap createFungiAsset → upsertFungiAsset. Push to createdAssetIds ONLY when outcome === 'created'.

    4. **Call site 3** (lines 162-168 — seeding log create). Swap `logs.createLog(client, 'seeding', ...)` → `logs.upsertLog(client, 'seeding', ...)`. Add the same audit-log emit for log outcome.

    **commit-seeding.js:** Same mechanical swap at lines 49-58 (asset) and 69-75 (log). No _cleanup branch (single-asset path).

    **commit-observation.js:** Confirm via grep that no `createFungiAsset` or `resolveOrCreateAsset` is called. The only farmOS write is `logs.createLog(client, 'observation', ...)` at ~line 36-38, which STAYS as createLog (observation is not in LOG_STABLE_KEYS' seeding-only migration scope this phase). Add a 1-line comment above that call:
    ```javascript
    // Phase 51 review: observation log stays POST-only (LOG_STABLE_KEYS.observation === null per CONTEXT.md).
    ```

    **Test updates:**
    - In commit-seeding-session.test.js: Existing tests that asserted `assets.createFungiAsset` was called must now assert `assets.upsertFungiAsset`. Existing tests asserting return shapes are unchanged because `{ok, assetId}` is preserved. Add ONE new test: replaying the same seeding session twice (call commit fn twice with same draft) produces only 1 set of assets/logs in mockClient._created (idempotency proof).
    - In commit-seeding.test.js: Same swap + same idempotency test for the single-asset path.

    Run the grep gate before committing:
    ```bash
    grep -nE "createFungiAsset|resolveOrCreateAsset" src/agents/alerter/src/farmos/commits/
    ```
    MUST return zero matches. If any remain → fix before committing.

    Commit:
    `refactor(51-05): migrate commit-* to upsertFungiAsset/upsertLog — grep gate clean`
  </action>
  <verify>
    <automated>cd src/agents/alerter && (grep -nE "createFungiAsset|resolveOrCreateAsset" src/farmos/commits/ && exit 1; npx jest test/farmos/commit-seeding-session.test.js test/farmos/commit-seeding.test.js test/farmos/commit-observation.test.js --runInBand)</automated>
  </verify>
  <acceptance_criteria>
    - `grep -nE "createFungiAsset|resolveOrCreateAsset" src/agents/alerter/src/farmos/commits/` returns ZERO matches (SPEC.md:107)
    - `grep -nE "upsertFungiAsset" src/agents/alerter/src/farmos/commits/commit-seeding-session.js` returns ≥2 matches
    - `grep -nE "upsertFungiAsset" src/agents/alerter/src/farmos/commits/commit-seeding.js` returns ≥1 match
    - `grep -nE "upsertLog" src/agents/alerter/src/farmos/commits/` returns ≥2 matches
    - `grep -nE "Phase 51 review:" src/agents/alerter/src/farmos/commits/commit-observation.js` returns 1 match
    - commit-seeding-session.test.js, commit-seeding.test.js, commit-observation.test.js all green
    - Idempotency test (replay twice → same final state) passes for both seeding-session and seeding
    - No regression: `cd src/agents/alerter && npx jest test/farmos/ --runInBand` exits 0
  </acceptance_criteria>
  <done>Commits migrated, grep gate clean, idempotency proved at unit level.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Author upsert-property.test.js (3 properties × 20 permutations)</name>
  <files>src/agents/alerter/test/farmos/upsert-property.test.js</files>
  <read_first>
    - src/agents/alerter/test/farmos/fixtures/multi-parent-inoc-trio.json (Plan 01 output)
    - src/agents/alerter/test/farmos/logs.test.js (table-driven for-loop pattern)
    - src/agents/alerter/test/farmos/mock-client.js (Plan 01 extended factory)
    - 51-PATTERNS.md §upsert-property.test.js (permutation pattern, fixture loading, describe shape)
    - 51-SPEC.md UPSERT-06 (acceptance: 3 properties, ≥20 permutations, all green)
    - 51-CONTEXT.md §"Property-test seeding strategy"
  </read_first>
  <behavior>
    Three property tests under `describe('upsert order independence (Phase 51 UPSERT-06)', ...)`:

    **Property 1: Order independence**
    - Load fixture {events, expected_final}
    - replay(events) is a helper that creates a fresh mockClient, walks each event, calls the asset+log upsert sequence for each child, returns a canonicalized snapshot {assetById sorted, logById sorted, parent_lineage map sorted}.
    - baseline = replay(events) in chronological order (events as given in fixture)
    - For 20 random permutations seeded via crypto.randomInt: replay(permuted) → canonical snapshot → expect deep equal to baseline
    - Print the seed on assertion failure for repro

    **Property 2: Stub enrichment**
    - Construct stub asset for `260118_KOY_12` (notes contains STUB_BACKFILL_MARKER, no parents, no fungi_type)
    - sequence_A = [stub-mint, real-inoc-write-for-260522_KOY_1-citing-260118_KOY_12-as-parent]
    - sequence_B = [real-inoc-write-only] (no prior stub)
    - replay(sequence_A) and replay(sequence_B) should produce identical asset field states for 260118_KOY_12 EXCEPT the stub-marker entry survives in notes for sequence_A — assert that fungi_type, parent[], qr_codes[] are equal between the two, and that sequence_A's final notes value CONTAINS both the marker AND the real entry.

    **Property 3: Conflict surfacing**
    - Seed mockClient with existing asset name='260118_KOY_12' fungi_type='ft-shi' (deliberately wrong species for test)
    - Call upsertFungiAsset with name='260118_KOY_12' fungi_type='ft-koy'
    - Assert: returned outcome === 'noop', conflicts.length === 1, conflicts[0].field === 'fungi_type', conflicts[0].existing === 'ft-shi', conflicts[0].incoming === 'ft-koy'
    - Assert: mockClient.patch was NOT called (no silent overwrite)
    - Assert: no thrown unhandled exception (function returned, did not throw)
  </behavior>
  <action>
    Create `src/agents/alerter/test/farmos/upsert-property.test.js` per PATTERNS.md §upsert-property.test.js.

    Header verbatim:
    ```javascript
    'use strict';

    const crypto = require('node:crypto');
    const { makeMockClient } = require('./mock-client');
    const assets = require('../../src/farmos/assets');
    const logs = require('../../src/farmos/logs');
    const fixture = require('./fixtures/multi-parent-inoc-trio.json');
    ```

    Implement `function permute(arr)` using Fisher-Yates with `crypto.randomInt`. Capture and return the seed (use `crypto.randomBytes(8).toString('hex')` as a seed identifier logged per iteration so failures are reproducible — there's no `crypto.randomInt` seeding API, so the alternative is to log the permutation order itself for each failing run).

    Implement `async function replay(events, opts = {})`:
      - Build a fresh mockClient seeded with `opts.preExisting` assets/logs (default empty)
      - For each event in events: iterate event.groups; for each group, for each child name in child_block_names: call `assets.upsertFungiAsset(client, {name: childName, fungiTypeName: species, fungiXingName: 'block', parentIds: [parentAssetId(s)], draftId: 'd-'+event.event_date})`, then `logs.upsertLog(client, 'seeding', {assetIds: [childAssetId], ...})`. Also upsert the parent asset(s) before each child so they exist.
      - Returns canonical snapshot: `{assets: sortedByName, logs: sortedByAssetId, lineage: parentMap}`. Strip volatile fields (timestamps, drupal_internal__revision_id) before comparison.

    Implement 3 it() blocks per <behavior> above. Use `expect(canonicalize(permuted)).toEqual(canonicalize(baseline))`.

    For Property 1: loop 20× with `for (let i = 0; i < 20; i++)`. On failure, the test runner will surface which iteration failed — also add `console.error('seed seq:', JSON.stringify(permuted.map(e=>e.label)))` inside a try/catch around the expect, then re-throw, so the permutation that caused failure prints to the test output.

    Use Jest 29 syntax. NEVER node:test.

    Commit:
    `test(51-05): UPSERT-06 — property tests (order-independence + stub-enrichment + conflict-surfacing)`
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/farmos/upsert-property.test.js --runInBand</automated>
  </verify>
  <acceptance_criteria>
    - 3 it() blocks exist under the Phase 51 UPSERT-06 describe
    - Property 1 runs ≥20 iterations (grep `N_PERMUTATIONS = 20` or equivalent loop bound)
    - All 3 properties pass
    - File length ≥120 lines (real implementation, not a stub)
    - `grep -c "permute\\|crypto.randomInt" src/agents/alerter/test/farmos/upsert-property.test.js` returns ≥2
    - No regression: full farmos suite green
  </acceptance_criteria>
  <done>Property tests green; order-independence + stub-enrichment + conflict-surfacing all attested offline.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| draft commit pipeline → farmOS write surface | commit-* code is the chokepoint where signal_draft.id idempotency meets per-entity upsert idempotency |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-51-10 | Tampering | rollback list (_cleanup) deletes assets that were merely patched, not created | mitigate | only push to createdAssetIds when outcome==='created'; covered by idempotency test (replay twice → no extra rollback entries) |
| T-51-11 | DoS | property test runtime explodes (20 × N children) | accept | mock-client is in-memory; full suite estimate ~15s; if budget breached, reduce permutations to 10 and note in audit |
</threat_model>

<verification>
- Grep gate clean (zero createFungiAsset|resolveOrCreateAsset in commits/)
- Full farmos suite green
- Idempotency proved at unit level (commit replay) AND property level (random permutation)
</verification>

<success_criteria>
- 3 commit files migrated (commit-observation.js review-only)
- 3 properties × 20 permutations all green
- SPEC.md:107 grep gate satisfied
</success_criteria>

<output>
Create `.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-05-SUMMARY.md` when done.
</output>
