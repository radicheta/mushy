---
phase: 51
plan: 04
type: execute
wave: 2
depends_on: ["51-01", "51-02"]
files_modified:
  - src/agents/alerter/src/farmos/logs.js
  - src/agents/alerter/test/farmos/logs.test.js
autonomous: true
requirements: [UPSERT-02]
must_haves:
  truths:
    - "upsertLog(client, type, opts) supports type='seeding' with stable-key lookup by asset.id"
    - "Non-seeding types fall through to current createLog POST-only behavior"
    - "Replaying a seeding event for the same child produces zero net new logs"
    - "Multiple existing matches (B5 violation): pick oldest by created, emit LogIdentityCollision warning"
  artifacts:
    - path: "src/agents/alerter/src/farmos/logs.js"
      provides: "upsertLog, LOG_STABLE_KEYS, LogIdentityCollision (in addition to existing exports)"
      contains: "function upsertLog"
    - path: "src/agents/alerter/test/farmos/logs.test.js"
      provides: "Jest coverage of upsertLog seeding hit/miss/collision + non-seeding pass-through"
  key_links:
    - from: "logs.js upsertLog"
      to: "merge.js (for log file_ids set-union + notes dedup)"
      via: "require('./merge')"
      pattern: "require\\(['\"]\\./merge['\"]\\)"
---

<objective>
Add `upsertLog(client, type, opts)` + `LOG_STABLE_KEYS` table to logs.js. Only the seeding log type migrates this phase (B5 invariant: one seeding log per child asset makes `(type='seeding', asset.id == assetIds[0])` an unambiguous stable key). All other log types map to `null` in the table → fall through to existing `createLog` POST-only behavior.

Purpose: Replaying a seeding session must be idempotent. Without this, retrying the May-22 inoc would create 11 duplicate seeding logs.
Output: 2 new exports on logs.js (plus one warning class), Jest coverage of seeding hit/miss/collision/pass-through paths.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-SPEC.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-CONTEXT.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-PATTERNS.md
@src/agents/alerter/src/farmos/logs.js

<interfaces>
From src/agents/alerter/src/farmos/logs.js (existing):
```javascript
// LOG_TYPES, NATIVE_LOG_TYPES (table at line 13)
// class UnsupportedLogTypeError (lines 16-22)
// createLog(client, logType, opts) → {ok, logId, http_status, reason?}
// module.exports = { LOG_TYPES, NATIVE_LOG_TYPES, UnsupportedLogTypeError, createLog }
```

From src/agents/alerter/src/farmos/merge.js (Plan 02):
```javascript
// STABLE_NOTES_SEPARATOR — for log notes dedup
```

farmOS log shape:
```
{
  id, type:'log--seeding',
  attributes: { name, timestamp, status, notes:{value, format}, drupal_internal__revision_id },
  relationships: {
    asset: { data: [{type:'asset--fungi', id:'<uuid>'}, ...] },
    file:  { data: [{type:'file--file', id:'<uuid>'}, ...] }
  }
}
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add upsertLog + LOG_STABLE_KEYS to logs.js</name>
  <files>src/agents/alerter/src/farmos/logs.js, src/agents/alerter/test/farmos/logs.test.js</files>
  <read_first>
    - src/agents/alerter/src/farmos/logs.js (full file — createLog body lines 24-55, exports at line 57)
    - src/agents/alerter/test/farmos/logs.test.js (existing tests + table-driven pattern)
    - src/agents/alerter/src/farmos/merge.js (STABLE_NOTES_SEPARATOR import)
    - 51-PATTERNS.md §logs.js (stable-key table + tie-break rule + return shape)
    - 51-CONTEXT.md §"Stable-key table for upsertLog"
    - 51-SPEC.md UPSERT-02
  </read_first>
  <behavior>
    Jest tests in logs.test.js (new describe block, do not modify existing):

    **LOG_STABLE_KEYS table:**
    - LOG_STABLE_KEYS.seeding is a function; called with {assetIds:['a1']} returns {path: '/api/log/seeding?filter[asset.id][value]=a1'}
    - LOG_STABLE_KEYS.seeding called with empty assetIds returns null
    - LOG_STABLE_KEYS.activity / .input / .observation / .harvest are all === null

    **upsertLog seeding miss path:**
    - No existing seeding log for assetId='a1' → falls through to createLog → returns {ok:true, logId, outcome:'created', conflicts:[], etag_source:null, http_status:201}

    **upsertLog seeding hit path:**
    - Existing seeding log L1 has asset.data=[{id:'a1'}], file.data=[] → incoming carries file=[{id:'f1'}] → PATCH merges file set-union → returns {ok:true, logId:L1.id, outcome:'patched', conflicts:[], etag_source:'soft_compare', http_status:200}
    - Verify PATCH body has merged file.data=[{type:'file--file', id:'f1'}]

    **upsertLog seeding noop path:**
    - Existing log already contains all incoming fields → no PATCH → outcome='noop'

    **upsertLog seeding collision (>1 match):**
    - GET returns 2 seeding logs for asset.id=a1 (created='2026-05-22T10:00', '2026-05-22T11:00') → upsertLog picks the OLDER (10:00) as canonical → PATCHes that one → audit-logger receives a LogIdentityCollision event/warning
    - Assert: the picked logId is the older one; mockClient call recorded contains the older id in the PATCH path
    - Assert: a warning surfaced (via injectable auditLogger or returned `warnings:['LogIdentityCollision']` field — pick one, document choice)

    **upsertLog non-seeding pass-through:**
    - upsertLog(client, 'activity', opts) → directly delegates to createLog → returns {ok, logId, outcome:'created'} on success (preserves current POST behavior)
    - upsertLog(client, 'harvest', opts) → same pass-through
    - No lookup HTTP call issued for non-seeding (verify mockClient.get was not called for /api/log/harvest)

    **upsertLog non-native type:**
    - upsertLog(client, 'bogus', opts) → throws UnsupportedLogTypeError (preserves createLog's existing contract)
  </behavior>
  <action>
    **Edits to `src/agents/alerter/src/farmos/logs.js`:**

    1. Import: `const { STABLE_NOTES_SEPARATOR } = require('./merge');`

    2. Add a `LogIdentityCollision` class near `UnsupportedLogTypeError`:
    ```javascript
    class LogIdentityCollision extends Error {
      constructor(logType, assetId, matchedIds) {
        super('log_identity_collision:' + logType + ':' + assetId);
        this.name = 'LogIdentityCollision';
        this.logType = logType;
        this.assetId = assetId;
        this.matchedIds = matchedIds;
      }
    }
    ```

    3. Add `LOG_STABLE_KEYS` table (top-level const, verbatim per PATTERNS.md):
    ```javascript
    // Phase 51 UPSERT-02: per-type stable-key resolvers. Only 'seeding' migrates
    // to upsert in this phase (B5 invariant: one seeding log per child asset).
    // Other types map to null → POST-only path preserved.
    const LOG_STABLE_KEYS = {
      seeding: ({ assetIds }) => (assetIds && assetIds[0]
        ? { path: '/api/log/seeding?filter[asset.id][value]=' + encodeURIComponent(assetIds[0]) }
        : null),
      activity: null,
      input: null,
      observation: null,
      harvest: null,
    };
    ```

    4. Add `async function upsertLog(client, type, opts)`:
       - If `!(type in NATIVE_LOG_TYPES)` and `!(type in LOG_STABLE_KEYS)` → throw UnsupportedLogTypeError(type) (mirror createLog behavior).
       - `const keyFn = LOG_STABLE_KEYS[type];`
       - If `keyFn === null` → return `createLog(client, type, opts)` wrapped with `outcome:'created'` on success:
         ```javascript
         const r = await createLog(client, type, opts);
         return r.ok ? { ...r, outcome: 'created', conflicts: [], etag_source: null } : r;
         ```
       - `const key = keyFn(opts);`
       - If `key === null` (no assetIds for seeding) → throw or return `{ok:false, reason:'missing_stable_key'}` — pick: return structured error to match existing `{ok:false, reason}` contract.
       - GET `key.path` → matches = response.data (array). If matches.length === 0 → POST via createLog (wrap outcome:'created').
       - If matches.length >= 1:
         - Sort matches by `attributes.created ASC; tie-break id ASC` per PATTERNS.md tie-break rule.
         - canonical = matches[0]; if matches.length > 1 → emit warning. Implementation: if `opts.auditLogger?.logCommit` exists, call it with event 'log_identity_collision' payload `{log_type:type, asset_id:opts.assetIds[0], matched_ids:matches.map(m=>m.id)}`; ALSO include `warnings: ['LogIdentityCollision:'+matches.length]` in the return object.
         - GET canonical full body (the filter response may not include all relationships); capture preMergeRevisionId.
         - Build `incoming` log body from opts (extract `_buildLogBody(type, opts)` helper if not already factored out of createLog).
         - **Merge log fields manually** (do NOT reuse mergeAssetFields — log identity rules differ: asset[] is identity-stable, not set-union; only file[] and notes change):
           - asset.data: assert byte-equal between existing and incoming (this is the stable key — mismatch = programmer error → throw or return ok:false reason:'log_identity_mismatch')
           - file.data: set-union by id (same algorithm as asset arrays in merge.js)
           - notes.value: dedup-and-append using STABLE_NOTES_SEPARATOR (mirror merge.js notes logic — extract a shared helper `_mergeNotes(existing, incoming, sep)` exported from merge.js if cleaner)
           - timestamp / status: equal=noop, differ=conflict (surface in return.conflicts)
         - If no fields changed → return outcome:'noop', do NOT PATCH.
         - PATCH `/api/log/<type>/<canonical.id>` with `If-Match` of preMergeRevisionId; soft-compare retry once on revision-moved (mirror upsertFungiAsset).

    5. Update `module.exports`:
    ```javascript
    module.exports = { LOG_TYPES, NATIVE_LOG_TYPES, UnsupportedLogTypeError, LogIdentityCollision, createLog, upsertLog, LOG_STABLE_KEYS };
    ```

    **Edits to `src/agents/alerter/test/farmos/logs.test.js`:**

    Add new describe blocks `'LOG_STABLE_KEYS table (Phase 51 UPSERT-02)'` and `'upsertLog (Phase 51 UPSERT-02)'` covering all behaviors above. Use makeMockClient from Plan 01 (with extended PATCH/GET-by-id/revision-id surface).

    Do NOT modify existing logs.test.js tests.

    Single commit:
    `feat(51-04): UPSERT-02 — upsertLog seeding with stable-key + collision handling`
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/farmos/logs.test.js --runInBand</automated>
  </verify>
  <acceptance_criteria>
    - All existing logs.test.js cases still pass
    - LOG_STABLE_KEYS table tests pass (5 cases: seeding fn, activity/input/observation/harvest null)
    - upsertLog seeding hit/miss/noop/collision/non-seeding-passthrough all green
    - upsertLog throws UnsupportedLogTypeError for non-native type
    - `grep -nE "^const LOG_STABLE_KEYS" src/agents/alerter/src/farmos/logs.js` returns 1 match
    - `grep -nE "function upsertLog|async function upsertLog" src/agents/alerter/src/farmos/logs.js` returns ≥1
    - `grep -c "LogIdentityCollision" src/agents/alerter/src/farmos/logs.js` returns ≥2
    - module.exports includes upsertLog, LOG_STABLE_KEYS, LogIdentityCollision
    - No regression: full farmos suite green
  </acceptance_criteria>
  <done>upsertLog ready for commit-path migration in Plan 05.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| alerter → farmOS log GET/PATCH | log writes can race; collision detection compensates for B5 violations |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-51-08 | Tampering | log identity drift (asset.data changes between existing and incoming) | mitigate | reject with `log_identity_mismatch`; never silently change which asset a seeding log belongs to |
| T-51-09 | Repudiation | duplicate seeding logs accumulate silently | mitigate | LogIdentityCollision warning surfaces in return + audit log; >1 match is observable, not silent |
</threat_model>

<verification>
- Full farmos suite green
- mock-client PATCH/GET-by-id from Plan 01 exercised
- merge.js STABLE_NOTES_SEPARATOR consumed (consistency with asset notes)
</verification>

<success_criteria>
- LOG_STABLE_KEYS table with seeding-only function; other types null
- upsertLog covers seeding hit/miss/collision; non-seeding pass-through
- Soft-compare retry budget = 1
</success_criteria>

<output>
Create `.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-04-SUMMARY.md` when done.
</output>
