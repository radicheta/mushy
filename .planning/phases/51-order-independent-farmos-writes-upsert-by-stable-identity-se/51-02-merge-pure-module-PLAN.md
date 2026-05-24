---
phase: 51
plan: 02
type: tdd
wave: 1
depends_on: []
files_modified:
  - src/agents/alerter/src/farmos/merge.js
  - src/agents/alerter/test/farmos/merge.test.js
autonomous: true
requirements: [UPSERT-03, UPSERT-05]
must_haves:
  truths:
    - "mergeAssetFields(existing, incoming) returns {merged, conflicts} for all rule classes"
    - "Array-ref fields (parent, qr_codes, farm_id_tag) set-union by id preserving existing-first order"
    - "Identity-field mutation (name, type) throws IdentityMutationError"
    - "Scalar non-identity differences surface in conflicts[] without mutating merged"
    - "Notes split on '\\n---\\n', exact-string dedup, append-only"
    - "STUB_BACKFILL_MARKER text survives merge unstripped"
  artifacts:
    - path: "src/agents/alerter/src/farmos/merge.js"
      provides: "mergeAssetFields, IdentityMutationError, STABLE_NOTES_SEPARATOR"
      min_lines: 80
      exports: ["mergeAssetFields", "IdentityMutationError", "STABLE_NOTES_SEPARATOR"]
    - path: "src/agents/alerter/test/farmos/merge.test.js"
      provides: "Jest unit coverage of all 5 rule classes + stub-marker preservation"
      min_lines: 100
  key_links:
    - from: "merge.js"
      to: "assets.js upsertFungiAsset (Plan 03)"
      via: "require('./merge')"
      pattern: "require\\(['\"]\\./merge['\"]\\)"
---

<objective>
Create the pure `_mergeAssetFields` function as a standalone module `src/agents/alerter/src/farmos/merge.js` with zero client / network dependencies. This is the load-bearing transform for UPSERT-03 — every set-union, conflict-surface, and notes-dedup decision flows through here. Plans 03 (assets upsert) and 05 (property tests) require this module ready and tested.

Purpose: Property-test isolation; the merge function gets exercised hundreds of times across 20 permutations × multiple properties in Plan 05, so it must be fast and side-effect free.
Output: merge.js + Jest tests covering all 5 rule classes from SPEC UPSERT-03.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-SPEC.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-CONTEXT.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-PATTERNS.md

<interfaces>
From src/agents/alerter/src/farmos/logs.js:16-22 — error-class pattern to mirror:
```javascript
class UnsupportedLogTypeError extends Error {
  constructor(logType) {
    super('unsupported_log_type:' + logType);
    this.name = 'UnsupportedLogTypeError';
    this.logType = logType;
  }
}
```

From farmOS JSON:API — asset shape received by mergeAssetFields:
```
{
  id: '<uuid>',
  type: 'asset--fungi',
  attributes: { name, status, notes:{value, format}, fungi_type? (sometimes attr, sometimes rel) },
  relationships: {
    parent: { data: [{type:'asset--fungi', id:'<uuid>'}, ...] },
    qr_codes: { data: [{type:'taxonomy_term--qr_code', id:'<uuid>'}, ...] },
    farm_id_tag: { data: [...] },
    fungi_type: { data: {type:'taxonomy_term--fungi_type', id:'<uuid>'} },
    fungi_xing: { data: {type:'taxonomy_term--fungi_xing', id:'<uuid>'} }
  }
}
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: RED — Author failing Jest tests for merge.js</name>
  <files>src/agents/alerter/test/farmos/merge.test.js</files>
  <read_first>
    - src/agents/alerter/test/farmos/logs.test.js (table-driven test shape — header pattern, describe/it style)
    - src/agents/alerter/test/farmos/qr.test.js (pure-function test analog)
    - 51-PATTERNS.md §merge.test.js (required test cases enumerated)
    - 51-SPEC.md UPSERT-03 acceptance criteria
  </read_first>
  <behavior>
    Seven required Jest test cases (one it() block each) under `describe('mergeAssetFields (Phase 51 UPSERT-03)', ...)`:
    1. set-union on relationships.parent.data: existing=[{id:'p1',type:'asset--fungi'}], incoming=[{id:'p2',type:'asset--fungi'}] → merged.relationships.parent.data has both ids in existing-first order, conflicts=[]
    2. set-union dedup: existing=[p1,p2], incoming=[p2,p3] → merged has [p1,p2,p3] (no duplicate p2), conflicts=[]
    3. identity mutation throws: existing.attributes.name='X', incoming.attributes.name='Y' → throws IdentityMutationError with .field='name', .existing='X', .incoming='Y'
    4. scalar equal noop: existing.relationships.fungi_type.data.id='ft-shi', incoming same → no entry in conflicts, merged equals existing for that field
    5. scalar conflict surface: existing fungi_type id='ft-shi', incoming fungi_type id='ft-koy' → conflicts.length===1, conflicts[0]={field:'fungi_type', existing:'ft-shi', incoming:'ft-koy', kind:'scalar_conflict'}, merged retains existing value (NOT overwritten)
    6. notes dedup: existing.attributes.notes.value='entry_A\n---\nentry_B', incoming.notes.value='entry_B\n---\nentry_C' → merged.notes.value='entry_A\n---\nentry_B\n---\nentry_C' (entry_B not double-appended)
    7. STUB marker preservation: existing notes='STUB - awaits 2025-paper-scan backfill', incoming notes='real inoc 2026-05-22' → merged.notes.value contains BOTH the STUB marker AND the new entry (marker not stripped)
  </behavior>
  <action>
    Create `src/agents/alerter/test/farmos/merge.test.js` following the Jest patterns in test/farmos/logs.test.js and qr.test.js.

    Header (verbatim per PATTERNS.md):
    ```javascript
    'use strict';
    const { mergeAssetFields, IdentityMutationError, STABLE_NOTES_SEPARATOR } = require('../../src/farmos/merge');
    ```

    Use a small helper at the top of the file `function asset(overrides) { return {id:'a1', type:'asset--fungi', attributes:{name:'X', notes:{value:'', format:'plain_text'}}, relationships:{parent:{data:[]}, qr_codes:{data:[]}, farm_id_tag:{data:[]}, fungi_type:{data:null}, fungi_xing:{data:null}}, ...overrides}; }` so each it() block stays under 10 lines.

    All seven test cases above MUST be expressed as separate `it(...)` blocks. Use `expect(...).toEqual(...)` for structural assertions and `expect(() => mergeAssetFields(...)).toThrow(IdentityMutationError)` for case 3.

    Run the test file now (RED step) — all 7 should fail because merge.js does not exist yet. Commit:
    `test(51-02): RED — failing merge.test.js for UPSERT-03 rule table (7 cases)`

    NEVER use node:test. Jest only.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/farmos/merge.test.js --runInBand 2>&1 | grep -E "Cannot find module.*merge|7 failed|FAIL"</automated>
  </verify>
  <acceptance_criteria>
    - File exists with 7 it() blocks
    - All 7 fail (RED step) — verified via grep above
    - Commit message starts with `test(51-02): RED`
  </acceptance_criteria>
  <done>Tests authored, all failing as expected; commit landed.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: GREEN — Implement merge.js to pass all 7 tests</name>
  <files>src/agents/alerter/src/farmos/merge.js</files>
  <read_first>
    - src/agents/alerter/src/farmos/logs.js (lines 1-22 — module header + error class shape)
    - src/agents/alerter/src/farmos/assets.js (lines 1-15 — module header pattern)
    - 51-PATTERNS.md §merge.js (full section — module header, export shape, set-union one-liner, conflict-surfacing shape)
    - 51-CONTEXT.md §"Notes-field representation" (dedup rule)
    - 51-CONTEXT.md §"Conflict-surfacing semantics"
  </read_first>
  <action>
    Create `src/agents/alerter/src/farmos/merge.js` exporting:

    1. `STABLE_NOTES_SEPARATOR = '\n---\n'` (top-level const). If Plan 01 Task 4 round-trip probe revealed a different round-tripped separator, USE THAT INSTEAD — read `.planning/notes/2026-05-XX-phase-51-notes-roundtrip-probe.md` for the verdict before locking the literal.

    2. `class IdentityMutationError extends Error` mirroring logs.js:16-22 — fields: name, field, existing, incoming. Message: `'identity_mutation:' + field`.

    3. `function mergeAssetFields(existing, incoming)` returning `{merged, conflicts}`:
       - **Identity check first:** if existing.attributes.name !== incoming.attributes.name AND incoming.attributes.name != null → throw IdentityMutationError('name', existing, incoming). Same for `existing.type !== incoming.type`.
       - **Initialize:** merged = deep-clone of existing (use `JSON.parse(JSON.stringify(existing))` — pure data, no functions). conflicts = [].
       - **Array-ref union** for each of `relationships.parent.data`, `relationships.qr_codes.data`, `relationships.farm_id_tag.data`: if incoming has the relationship, build `existingIds = existing[...].data.map(r=>r.id)`, `incomingIds = incoming[...].data.map(r=>r.id)`, `mergedIds = Array.from(new Set([...existingIds, ...incomingIds]))`. Reconstitute as `{data: mergedIds.map(id => existingById.get(id) || incomingById.get(id))}` preserving the `{type, id}` shape. Helper iterates over a const list `ARRAY_REF_FIELDS = ['parent', 'qr_codes', 'farm_id_tag']`.
       - **Scalar relationship singletons** (`relationships.fungi_type.data.id`, `relationships.fungi_xing.data.id`): if existing is null/undefined → take incoming (no conflict). If both present and equal → noop. If both present and differ → push `{field, existing:<id>, incoming:<id>, kind:'scalar_conflict'}` to conflicts; do NOT mutate merged for that field. Helper iterates over `SCALAR_REL_FIELDS = ['fungi_type', 'fungi_xing']`.
       - **Scalar attribute non-identity** (`attributes.status`): same rule as scalar rel — null→take, equal→noop, differ→conflict.
       - **Notes merge:**
         - sep = STABLE_NOTES_SEPARATOR
         - existingEntries = (existing.attributes.notes?.value || '').split(sep).map(s => s.trim()).filter(s => s.length > 0)
         - incomingEntries = (incoming.attributes.notes?.value || '').split(sep).map(s => s.trim()).filter(s => s.length > 0)
         - merged set: start from existingEntries; for each incomingEntry, if not in set → append
         - merged.attributes.notes = {value: mergedArr.join(sep), format: 'plain_text'}
         - Stub marker preservation falls out for free — the marker string is just another entry.

    4. Module exports:
       ```javascript
       module.exports = { mergeAssetFields, IdentityMutationError, STABLE_NOTES_SEPARATOR };
       ```

    Module header verbatim per PATTERNS.md:
    ```javascript
    'use strict';
    // Phase 51 UPSERT-03: pure merge for asset--fungi fields. Zero client / network deps.
    // Rules: array-ref → set-union by id; identity scalars (name, type) → throw;
    // non-identity scalars → equal=noop, differ=conflict; notes → split-dedup-join.
    // Cross-ref: 51-SPEC.md UPSERT-03; 51-CONTEXT.md "Notes-field representation".
    ```

    Run tests — all 7 should pass (GREEN). Commit:
    `feat(51-02): GREEN — implement mergeAssetFields with rule table`
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/farmos/merge.test.js --runInBand</automated>
  </verify>
  <acceptance_criteria>
    - All 7 it() blocks pass under Jest
    - `grep -c "module.exports" src/agents/alerter/src/farmos/merge.js` returns ≥1
    - `grep -nE "mergeAssetFields|IdentityMutationError|STABLE_NOTES_SEPARATOR" src/agents/alerter/src/farmos/merge.js | grep -v '^#' | wc -l` returns ≥3 (all three exports present)
    - File has ≥80 lines (real implementation, not a stub)
    - No `require(` of any other src/farmos/ module (purity invariant) — verify: `grep -c "require.*farmos" src/agents/alerter/src/farmos/merge.js` returns 0
    - Commit message starts with `feat(51-02): GREEN`
  </acceptance_criteria>
  <done>merge.js implemented, tests green, commit landed. Plans 03/04/05 can now require('./merge').</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| caller → mergeAssetFields | inputs may be from network (farmOS GET response) but function is pure — no I/O |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-51-03 | Tampering | scalar overwrite hiding farmer data | mitigate | conflict-surface returns structured conflict; merged retains existing value (never silent overwrite). UPSERT-03 acceptance test #5 enforces. |
| T-51-04 | Repudiation | identity mutation slipping through | mitigate | IdentityMutationError thrown on name/type change; programmer error, not data event. Test #3 enforces. |
</threat_model>

<verification>
- Both RED and GREEN commits land
- Final state: `cd src/agents/alerter && npx jest test/farmos/merge.test.js --runInBand` exits 0
- No farmos suite regression: `cd src/agents/alerter && npx jest test/farmos/ --runInBand` (this plan adds; never modifies existing tests)
</verification>

<success_criteria>
- merge.js exports mergeAssetFields, IdentityMutationError, STABLE_NOTES_SEPARATOR
- 7 Jest cases green
- Two atomic commits (RED then GREEN)
</success_criteria>

<output>
Create `.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-02-SUMMARY.md` when done.
</output>
