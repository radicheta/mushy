# Phase 51: Order-independent farmOS writes - Pattern Map

**Mapped:** 2026-05-24
**Files analyzed:** 13 (5 new + 8 modified)
**Analogs found:** 13 / 13 (every new file has a strong in-repo analog)
**Test framework:** Jest 29 (RESEARCH.md overrides CONTEXT.md "node:test")

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/agents/alerter/src/farmos/merge.js` | utility (pure) | transform | none in `farmos/`; closest shape = `qr.js` (pure-ish payload builder) | role-only |
| `src/agents/alerter/src/farmos/assets.js` (modify: add `upsertFungiAsset`, `isStubAsset`, `STUB_BACKFILL_MARKER`) | service | request-response | self - extend existing module | exact (self-extension) |
| `src/agents/alerter/src/farmos/logs.js` (modify: add `upsertLog`, `LOG_STABLE_KEYS`) | service | request-response | self - extend existing module | exact (self-extension) |
| `src/agents/alerter/src/farmos/audit-logger.js` (modify: extend payload) | utility | event-driven | self - extend payload shape | exact (self-extension) |
| `src/agents/alerter/src/farmos/client.js` (modify: plumb `opts.headers` in `_doFetch`) | service (transport) | request-response | self - one targeted change in existing function | exact (self-extension) |
| `src/agents/alerter/src/farmos/commits/commit-seeding-session.js` (modify) | controller | request-response | self - migrate call sites to upsert | exact (self-migration) |
| `src/agents/alerter/src/farmos/commits/commit-seeding.js` (modify) | controller | request-response | self - migrate call sites to upsert | exact (self-migration) |
| `src/agents/alerter/src/farmos/commits/commit-observation.js` (modify) | controller | request-response | self - log path stays POST (observation is out of scope for log-upsert) | self (touch only if `createFungiAsset` ever called from here -- grep first) |
| `src/agents/alerter/test/farmos/merge.test.js` (NEW) | test | transform | `test/farmos/qr.test.js` (closest pure-function test in farmos suite) | role-only |
| `src/agents/alerter/test/farmos/upsert-property.test.js` (NEW) | test (property) | transform | no property-style test exists; structural analog = `test/farmos/logs.test.js` (table-driven `for (const t of ...)`) | role-only |
| `src/agents/alerter/test/farmos/fixtures/multi-parent-inoc-trio.json` (NEW) | fixture | n/a | `test/fixtures/seeding-session-may22-commit/draft.json` (referenced by live-fire-48) | exact |
| `src/agents/alerter/test/farmos/mock-client.js` (modify: add `patch`, `delete`, revision-id surface) | test infra | request-response | self - extend existing factory | exact (self-extension) |
| `src/agents/alerter/scripts/live-fire-51.js` (NEW) | script (harness) | request-response | `src/agents/alerter/scripts/live-fire-48.js` | exact |

## Pattern Assignments

### `src/agents/alerter/src/farmos/merge.js` (utility, pure transform) - NEW

**Analog:** No exact analog. Closest shape = `src/agents/alerter/src/farmos/qr.js` (small pure module that builds payload fragments and exports helpers). Test analog: `test/farmos/qr.test.js`.

**Module header pattern** (copy from `assets.js:1-15`):
```javascript
'use strict';

// Phase 51 UPSERT-03: pure merge for asset--fungi fields. Zero client / network
// deps -- isolation for property tests. Rule table:
//   - array-valued ref relationships (parent, qr_codes, farm_id_tag)  -> set-union by id
//   - scalar identity fields (name, type)                              -> throw IdentityMutationError
//   - scalar non-identity (fungi_type, fungi_xing, status)             -> equal=noop, conflict=surface
//   - notes.value (free text)                                          -> split on '\n---\n', dedup-and-append
// Cross-ref: 51-SPEC.md UPSERT-03; 51-CONTEXT.md "Notes-field representation"
```

**Export pattern** (mirror `assets.js:138` -- named exports object):
```javascript
module.exports = {
  mergeAssetFields,        // (existing, incoming) -> {merged, conflicts}
  isMergeNoop,             // (existing, merged) -> bool   (helper exported for tests)
  IdentityMutationError,   // class, thrown for name/bundle change attempts
  STABLE_NOTES_SEPARATOR,  // '\n---\n'
};
```

**Error class pattern** (copy shape from `logs.js:16-22`):
```javascript
class IdentityMutationError extends Error {
  constructor(field, existing, incoming) {
    super('identity_mutation:' + field);
    this.name = 'IdentityMutationError';
    this.field = field;
    this.existing = existing;
    this.incoming = incoming;
  }
}
```

**Set-union pattern** (from RESEARCH.md "Don't Hand-Roll" - one-liner):
```javascript
// existing[].data + incoming[].data -> dedup by id, preserve existing-first order
const existingIds = existingRefs.map((r) => r.id);
const incomingIds = incomingRefs.map((r) => r.id);
const mergedIds = Array.from(new Set([...existingIds, ...incomingIds]));
```

**Conflict-surfacing return shape** (locked by CONTEXT.md "Conflict-surfacing semantics"):
```javascript
return {
  merged: { attributes: {...}, relationships: {...} },
  conflicts: [
    // { field: 'fungi_type', existing: 'SHI', incoming: 'KOY', kind: 'scalar_conflict' }
  ],
};
```

---

### `src/agents/alerter/src/farmos/assets.js` (service, add `upsertFungiAsset`, `isStubAsset`, `STUB_BACKFILL_MARKER`)

**Analog:** Self-extend; do NOT refactor existing exports per CONTEXT.md "extends current primitives".

**Required additions:**

1. **Stub marker constant** (top-level, near `NAME_CACHE`):
```javascript
// Phase 51 UPSERT-05: marker string in notes.value identifies hand-stubbed
// ancestors awaiting 2025-paper-scan backfill. See
// .planning/notes/2026-05-24-prod-write-receipt.md (4 stubs in prod farmOS).
const STUB_BACKFILL_MARKER = 'STUB - awaits 2025-paper-scan backfill';
```

2. **`isStubAsset(asset)` predicate** (pure, exported):
```javascript
function isStubAsset(asset) {
  if (!asset || !asset.attributes || !asset.attributes.notes) return false;
  const value = asset.attributes.notes.value;
  return typeof value === 'string' && value.includes(STUB_BACKFILL_MARKER);
}
```

3. **`upsertFungiAsset(client, opts)`** - lookup-merge-or-create. Reuse:
   - `findAssetByName` for the lookup leg (lines 38-51)
   - `createFungiAsset` for the miss path (lines 53-111) - call directly, do not duplicate payload assembly
   - `mergeAssetFields` from `./merge.js` for the hit path
   - `client.patch` for the write (already exists in `client.js:169`)

   **Return shape contract** (must match `createFungiAsset` return on `created` path):
   ```javascript
   // create:  { ok: true, assetId, outcome: 'created', http_status: 201 }
   // patch:   { ok: true, assetId, outcome: 'patched', conflicts: [], http_status: 200 }
   // noop:    { ok: true, assetId, outcome: 'noop',    conflicts: [], http_status: null }
   // skip-on-conflict: { ok: true, assetId, outcome: 'noop', conflicts: [...], http_status: null }
   // failure: { ok: false, reason, http_status }
   ```

4. **Module exports update** (line 138, append):
```javascript
module.exports = {
  findAssetByName, createFungiAsset, resolveOrCreateAsset, deleteFungiAsset, _clearCache,
  upsertFungiAsset, isStubAsset, STUB_BACKFILL_MARKER,
};
```

**Cache invariant** (document in code, do NOT change behavior):
```javascript
// NAME_CACHE survives PATCH without invalidation because UPSERT-03's
// IdentityMutationError on name change makes (name -> id) stable. If a future
// feature adds rename, the cache MUST be invalidated here.
```

---

### `src/agents/alerter/src/farmos/logs.js` (service, add `upsertLog`, `LOG_STABLE_KEYS`)

**Analog:** Self-extend.

**Stable-key table** (top-level constant, mirrors `NATIVE_LOG_TYPES` shape at line 13):
```javascript
// Phase 51 UPSERT-02: per-type stable-key resolvers. Only 'seeding' migrates
// to upsert in this phase (B5 invariant: one seeding log per child asset).
// Other types map to null -> POST-only path is preserved.
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

**Tie-break rule for `>1` match** (RESEARCH.md "Common Pitfalls #6"):
```javascript
// Sort matches by attributes.created ASC; on tie, lexicographic by id ASC.
// Pick [0] as canonical; emit LogIdentityCollision audit warning for >1.
matches.sort((a, b) => {
  const ca = a.attributes.created || '';
  const cb = b.attributes.created || '';
  if (ca !== cb) return ca < cb ? -1 : 1;
  return a.id < b.id ? -1 : 1;
});
```

**`upsertLog(client, type, opts)`** - same hit/miss shape as `upsertFungiAsset`:
   - On `LOG_STABLE_KEYS[type] === null` -> fall through to `createLog` (current behavior preserved)
   - On lookup miss -> call existing `createLog` (lines 24-55)
   - On hit -> GET the matched log body, run `mergeAssetFields`-equivalent for logs (file ID set-union + notes dedup), PATCH

**Return shape** (mirror `upsertFungiAsset`):
```javascript
{ ok: true, logId, outcome: 'created' | 'patched' | 'noop', conflicts: [], http_status }
```

**Module exports update** (line 57, append):
```javascript
module.exports = { LOG_TYPES, NATIVE_LOG_TYPES, UnsupportedLogTypeError, createLog, upsertLog, LOG_STABLE_KEYS };
```

---

### `src/agents/alerter/src/farmos/audit-logger.js` (utility, extend payload)

**Analog:** Self-extend. The payload object at `audit-logger.js:11-25` is the literal extension surface.

**Three new fields** (insert in payload object literal, preserve insertion order for grepability):
```javascript
const payload = {
  ts: new Date().toISOString(),
  event,
  draft_id: draft && draft.id,
  // ... existing fields ...
  reason: result.reason != null ? result.reason : null,
  // Phase 51 UPSERT additions:
  outcome: result.outcome != null ? result.outcome : null,         // 'created'|'patched'|'noop'|'mixed'|null
  conflicts: Array.isArray(result.conflicts) ? result.conflicts : [],
  etag_source: result.etag_source != null ? result.etag_source : null,  // 'revision_id'|'absent'|null
};
```

**Test update** (`test/farmos/audit-logger.test.js:32-35` -- "13 named keys" assertion becomes "16 named keys" with the 3 new keys added to the sorted list).

---

### `src/agents/alerter/src/farmos/client.js` (service transport, plumb headers)

**Analog:** Self - one targeted change at `_doFetch` lines 74-103.

**Current pattern** (lines 77-94, headers hardcoded):
```javascript
const headers = {
  Accept: 'application/vnd.api+json',
  Cookie: _session.cookie || '',
  'X-CSRF-Token': _session.csrf || '',
};
```

**Required change** - merge `opts.headers` after defaults so caller wins:
```javascript
const headers = Object.assign({
  Accept: 'application/vnd.api+json',
  Cookie: _session.cookie || '',
  'X-CSRF-Token': _session.csrf || '',
}, (opts && opts.headers) || {});
```

This is the SINGLE surface change for any future If-Match plumbing. RESEARCH.md OQ#1 lands on "soft revision-id compare" so `If-Match` is harmless-if-ignored; the plumbing exists for honesty + future-proofing.

---

### `src/agents/alerter/src/farmos/commits/commit-seeding-session.js` (modify - migrate to upsert)

**Analog:** Self. Migration is mechanical -- replace 2 call sites + 1 log call site.

**Call site 1** (lines 121-137 -- source-block resolve-or-create):

Before:
```javascript
const found = await assets.findAssetByName(client, parentName);
if (found.found) { sourceBlockId = found.assetId; }
else {
  const created = await assets.createFungiAsset(client, { name: parentName, fungiTypeName: species, fungiXingName: 'block', draftId });
  if (!created.ok) return _cleanup(...);
  sourceBlockId = created.assetId;
  createdAssetIds.push(sourceBlockId);
}
```

After:
```javascript
const r = await assets.upsertFungiAsset(client, { name: parentName, fungiTypeName: species, fungiXingName: 'block', draftId });
if (!r.ok) return _cleanup(client, ctx, draft, createdAssetIds, r.reason || 'source_block_upsert_failed', childIndex);
sourceBlockId = r.assetId;
if (r.outcome === 'created') createdAssetIds.push(sourceBlockId);   // only created assets get rolled back
// ctx.auditLogger.logCommit('upsert_outcome', draft, { asset_ids:[sourceBlockId], outcome:r.outcome, conflicts:r.conflicts, etag_source:r.etag_source });
```

**Call site 2** (lines 147-160 -- child block create):

Before:
```javascript
const childRes = await assets.createFungiAsset(client, { name: childName, fungiTypeName: species, fungiXingName: 'block', parentIds, draftId });
```

After:
```javascript
const childRes = await assets.upsertFungiAsset(client, { name: childName, fungiTypeName: species, fungiXingName: 'block', parentIds, draftId });
// same _cleanup branch; only push to createdAssetIds when outcome === 'created'
```

**Call site 3** (lines 162-168 -- seeding log create):

Before: `await logs.createLog(client, 'seeding', {...})`
After:  `await logs.upsertLog(client, 'seeding', {...})`

**Acceptance grep gate** (SPEC.md line 107):
```bash
grep -nE "createFungiAsset|resolveOrCreateAsset" src/agents/alerter/src/farmos/commits/   # must return zero
```

---

### `src/agents/alerter/src/farmos/commits/commit-seeding.js` (modify - migrate to upsert)

**Analog:** Self. One asset call site (lines 49-58) + one log call site (lines 69-75). Same mechanical swap as `commit-seeding-session.js`. No `_cleanup` (single-asset path).

---

### `src/agents/alerter/src/farmos/commits/commit-observation.js` (modify - REVIEW only)

**Analog:** Self. Observation does NOT create assets (it resolves them via QR -- see line 18-21). The only farmOS write is `logs.createLog(client, 'observation', ...)` at line 36-38, which stays POST-only per CONTEXT.md "Stable-key table" (observation: none -- POST-only).

**Required action:** None code-wise. Add a 1-line comment confirming Phase 51 reviewed this file and observation log stays POST.

---

### `src/agents/alerter/test/farmos/merge.test.js` (NEW)

**Analog:** `test/farmos/logs.test.js` (table-driven structure) + `test/farmos/audit-logger.test.js` (per-case `it` blocks asserting structured returns).

**Header pattern** (copy from `test/farmos/logs.test.js:1-3`):
```javascript
'use strict';

const { mergeAssetFields, isMergeNoop, IdentityMutationError, STABLE_NOTES_SEPARATOR } = require('../../src/farmos/merge');
```

**Required test cases** (per SPEC UPSERT-03 acceptance):
1. set-union on `relationships.parent.data` (existing=[p1], incoming=[p2] -> merged=[p1,p2])
2. set-union dedup (existing=[p1,p2], incoming=[p2,p3] -> merged=[p1,p2,p3])
3. identity mutation throws (existing name='X', incoming name='Y' -> throws IdentityMutationError)
4. scalar equal noop (existing fungi_type=ft-shi, incoming fungi_type=ft-shi -> no conflict, no diff)
5. scalar conflict surface (existing ft-shi, incoming ft-koy -> conflicts.length=1)
6. notes dedup -- `mushy:draft:d1` trailer collapses to one occurrence
7. notes preserve `STUB_BACKFILL_MARKER` -- merge with new entry does NOT strip the marker

**Describe block pattern** (copy from `test/farmos/logs.test.js:11`):
```javascript
describe('mergeAssetFields (Phase 51 UPSERT-03)', () => {
  it('set-union on parent[] preserves existing-first order', () => { /* ... */ });
  // ...
});
```

---

### `src/agents/alerter/test/farmos/upsert-property.test.js` (NEW)

**Analog:** Closest structural shape = `test/farmos/logs.test.js` (table-driven via `for (const t of NATIVE_LOG_TYPES)`). No property-test analog in the repo -- hand-roll permutations.

**Permutation pattern** (copy semantics from RESEARCH.md "Don't Hand-Roll #2"):
```javascript
'use strict';

const crypto = require('node:crypto');
const { makeMockClient } = require('./mock-client');
const assets = require('../../src/farmos/assets');
const logs = require('../../src/farmos/logs');
const fixture = require('./fixtures/multi-parent-inoc-trio.json');

function permute(arr, seed) {
  // Fisher-Yates with crypto.randomInt; log seed on failure for repro.
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = crypto.randomInt(0, i + 1);
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

describe('upsert order independence (Phase 51 UPSERT-06)', () => {
  const N_PERMUTATIONS = 20;

  it('20 random permutations of 3 inoc events converge to byte-equivalent final state', async () => {
    const baseline = await replay(fixture.events);  // chronological
    for (let i = 0; i < N_PERMUTATIONS; i++) {
      const permuted = await replay(permute(fixture.events));
      expect(canonicalize(permuted)).toEqual(canonicalize(baseline));
    }
  });

  it('(stub-mint, real-inoc-write) === (real-inoc-write only)', async () => { /* ... */ });
  it('fungi_type conflict surfaces structured result, no silent overwrite', async () => { /* ... */ });
});
```

**Fixture-loading pattern** (mirror live-fire-48.js line 36):
```javascript
const fixture = require('./fixtures/multi-parent-inoc-trio.json');
```

---

### `src/agents/alerter/test/farmos/fixtures/multi-parent-inoc-trio.json` (NEW)

**Analog:** `src/agents/alerter/test/fixtures/seeding-session-may22-commit/draft.json` (existing seeding_session fixture used by live-fire-48).

**Expected shape** (based on commit-seeding-session.js groups parsing at lines 108-116):
```json
{
  "events": [
    {
      "label": "May-22 inoc",
      "event_date": "2026-05-22",
      "groups": [{ "species": {"value": "KOY"}, "parent": {"value": "260118_KOY_12"}, "qty": {"value": 4}, "child_block_names": {"value": ["260522_KOY_1","260522_KOY_2","260522_KOY_3","260522_KOY_4"]} }]
    },
    { "label": "Jan-18 inoc", "event_date": "2026-01-18", "groups": [{ ... }] },
    { "label": "Mar-04 inoc", "event_date": "2026-03-04", "groups": [{ ... }] }
  ],
  "expected_final": {
    "asset_count": "...",
    "parent_lineage": { "260522_KOY_1": ["260118_KOY_12"] }
  }
}
```

Anchor names from `.planning/notes/2026-05-24-prod-write-receipt-uuids.json` (the 4 stub ancestors: `260304_SHI_5`, `260118_SHI_23`, `260118_SHI_26`, `260118_KOY_12`) -- these become the property-test seeds for the "stub enrichment" property.

---

### `src/agents/alerter/test/farmos/mock-client.js` (modify - extend factory)

**Analog:** Self. Extend the `client` object literal at lines 29-85.

**Current export shape** (lines 29-85, methods: `get`, `post`, `postBinary`).

**Required additions:**

1. **PATCH support** -- mirror `post` (lines 63-77). Match on `/api/asset/fungi/<id>` and `/api/log/<type>/<id>` patterns; route to a `patched` registry keyed by id; surface revision-id and 412 protocol via test-time opts.

2. **DELETE support** (Pitfall 4 in RESEARCH.md) -- mock current `client.delete` (real client exposes at `client.js:178`). Used by `commit-seeding-session._cleanup` (`assets.deleteFungiAsset` at `assets.js:122-136`).

3. **GET-by-id support** -- current GET only handles filter queries. Upsert path GETs `/api/asset/fungi/<id>` to fetch full body for merge. Add regex `^\/api\/asset\/fungi\/([0-9a-f-]+)$` route returning the asset body from an internal registry seeded by `knownAssetsByName`.

4. **Revision-id surface** -- assets returned from GET expose `attributes.drupal_internal__revision_id`; PATCH route can be configured to return 412 once then 200 (412 protocol).

**Pattern to copy** (lines 33-61 for `get`, 63-77 for `post`):
```javascript
patch: jest.fn(async (path, body, opts) => {
  calls.push({ method: 'PATCH', path, body, headers: opts && opts.headers });
  // mirror `post` shape: return _ok(200, { data: { id, type, attributes, relationships } });
  // 412 protocol: if path is in _force412 set on first call, return _ok(412, {})
}),
delete: jest.fn(async (path, opts) => {
  calls.push({ method: 'DELETE', path });
  return _ok(204, null);
}),
```

---

### `src/agents/alerter/scripts/live-fire-51.js` (NEW)

**Analog:** `src/agents/alerter/scripts/live-fire-48.js` (read in full -- 62 lines, fork directly).

**Copy patterns verbatim from `live-fire-48.js`:**

1. **Env-var preamble** (lines 23-30):
```javascript
const farmosUrl = process.env.FARMOS_URL;
const username = process.env.FARMOS_USERNAME;
const password = process.env.FARMOS_PASSWORD;
if (!farmosUrl || !username || !password) {
  console.error('FARMOS_URL + FARMOS_USERNAME + FARMOS_PASSWORD required');
  process.exit(2);
}
```

2. **Client + audit-logger construction** (lines 37-52):
```javascript
const client = createFarmosClient({ farmosUrl, username, password, logger: console });
const auditLogger = { logCommit: async (event, d, r) => { console.log('[audit]', event, r && r.outcome, r && r.status); } };
```

3. **Result-write convention** (lines 54-58):
```javascript
const out = { elapsed_ms: Date.now() - t0, draft_id: draft.id, ...result };
fs.writeFileSync(outputPath, JSON.stringify(out, null, 2));
console.log(JSON.stringify(out, null, 2));
```

**Phase-51 specific deltas:**

- Reuse the same May-22 fixture (`test/fixtures/seeding-session-may22-commit/draft.json`) but post-merge expect zero new assets created (stubs already in dev).
- Assertion block (per SPEC UPSERT-07 acceptance): tally `result.outcome` per asset/log -> assert `created === 0`, `patched >= 4` (the 4 stubs enriched), no duplicate UUIDs in `asset_ids`.
- Lineage walk: for each child, `GET /api/asset/fungi/<id>` and assert `relationships.parent.data[].id` matches the expected stub UUIDs from `.planning/notes/2026-05-24-prod-write-receipt-uuids.json`.

**Output path convention:** default `/tmp/51-live-fire-result.json`.

---

## Shared Patterns

### Error-class declaration (used by `merge.js`)
**Source:** `src/agents/alerter/src/farmos/logs.js:16-22`
**Apply to:** `IdentityMutationError` in `merge.js`
```javascript
class UnsupportedLogTypeError extends Error {
  constructor(logType) {
    super('unsupported_log_type:' + logType);
    this.name = 'UnsupportedLogTypeError';
    this.logType = logType;
  }
}
```

### Result-object return contract (used by every upsert function)
**Source:** `src/agents/alerter/src/farmos/assets.js:102-110` (createFungiAsset) and `src/agents/alerter/src/farmos/logs.js:50-54` (createLog)
**Apply to:** `upsertFungiAsset`, `upsertLog`, all merge helpers
```javascript
// Success
return { ok: true, assetId, http_status: r.status };
// Failure (never throws -- always structured)
return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
```
Phase 51 extends with `outcome` and `conflicts` fields but preserves the `{ok, ...}` discriminator.

### Module header (`'use strict'` + Phase comment + cross-ref to `.planning/notes/`)
**Source:** `src/agents/alerter/src/farmos/assets.js:1-15`, `logs.js:1-12`, `audit-logger.js:1-7`
**Apply to:** Every new file in this phase
Pattern: `'use strict';` + blank line + multi-line block comment naming the phase number, the SPEC requirement IDs, and a cross-ref to the `.planning/notes/` or `.planning/phases/` doc.

### Mock-client factory pattern
**Source:** `src/agents/alerter/test/farmos/mock-client.js:13-87`
**Apply to:** Every new test file that needs HTTP interactions
- Factory function `makeMockClient({ knownAssetsByName, knownAssetsByQr, ... } = {})`
- Returns `{ get: jest.fn(...), post: jest.fn(...), postBinary: jest.fn(...), _created, _calls }`
- Records every call into `calls[]` for post-hoc assertion
- Filter-pattern dispatch in `get` via `/regex/.exec(path)`

### Test file skeleton
**Source:** `src/agents/alerter/test/farmos/logs.test.js:1-12`, `assets.test.js:1-26`
**Apply to:** `merge.test.js`, `upsert-property.test.js`
```javascript
'use strict';

const moduleUnderTest = require('../../src/farmos/<module>');

describe('<module> (Phase 51 <REQ-ID>)', () => {
  beforeEach(() => { /* cache clears, etc */ });
  it('<specific behavior>', async () => { /* arrange, act, expect */ });
});
```

### Audit-log event-emit pattern
**Source:** `src/agents/alerter/src/farmos/commits/commit-seeding-session.js:52-60`
**Apply to:** Every upsert call site that wants to emit outcome telemetry
```javascript
if (auditLogger && typeof auditLogger.logCommit === 'function') {
  try {
    await auditLogger.logCommit('upsert_outcome', draft, {
      asset_ids: [assetId], outcome, conflicts, etag_source,
    });
  } catch (_) { /* audit failure is non-fatal */ }
}
```

### Live-fire script env-var contract
**Source:** `src/agents/alerter/scripts/live-fire-48.js:11-15`
**Apply to:** `scripts/live-fire-51.js`
Required envs: `FARMOS_URL`, `FARMOS_USERNAME`, `FARMOS_PASSWORD`. Optional: `DRAFT_JSON_PATH`, `OUTPUT_PATH`. Standard `process.exit(2)` on missing env, `process.exit(1)` on runtime failure (line 60).

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `test/farmos/upsert-property.test.js` | property test | transform | First property-style test in the alerter repo. Hand-roll Fisher-Yates with `crypto.randomInt` (RESEARCH.md "Don't Hand-Roll #2"). Structural shape borrows from the table-driven loops in `logs.test.js:14`. |

All other new files have at least a role-level analog in the existing farmos suite.

## Metadata

**Analog search scope:**
- `src/agents/alerter/src/farmos/` (8 source files read in full)
- `src/agents/alerter/test/farmos/` (3 test files + mock-client read)
- `src/agents/alerter/scripts/` (live-fire-48.js read in full)
- `.planning/notes/` (prod-write receipts confirmed for fixture seed UUIDs)

**Files scanned:** 13 in-scope + sibling test files for pattern confirmation.

**Pattern extraction date:** 2026-05-24

---

## PATTERN MAPPING COMPLETE

**Phase:** 51 - Order-independent farmOS writes
**Files classified:** 13
**Analogs found:** 13 / 13

### Coverage
- Files with exact analog (self-extension or sibling): 12
- Files with role-only analog: 1 (`upsert-property.test.js`)
- Files with no analog: 0

### Key Patterns Identified
- Result-object `{ok, ...}` discriminator is the universal return shape; UPSERT adds `outcome` and `conflicts` without breaking callers
- Self-extension dominates: 8 of 13 files modify existing modules; copy in-file conventions verbatim
- Mock-client factory + Jest `describe/it/expect` + filter-regex dispatch is the load-bearing test shape -- extend `mock-client.js` with `patch`/`delete`/by-id GET in one task
- Live-fire harness shape: 60-line script, env-var preamble, client + audit-logger, result JSON dump -- fork directly from `live-fire-48.js`
- Notes-field is the merge logic's only non-trivial case; `'\n---\n'` separator + exact-string dedup keeps `STUB_BACKFILL_MARKER` round-trip stable

### Critical Cross-References for Planner
- **CONTEXT.md test framework claim is wrong** -- use Jest, not `node:test` (RESEARCH.md A5 verified). Every test file uses `jest.fn()` / `describe` / `it` / `expect`.
- **CONTEXT.md etag-concurrency claim is unachievable as-literally-written** -- farmOS JSON:API does not return 412 (RESEARCH.md A4 + Pitfall #2). Planner should land on RESEARCH.md option (a): soft revision-id compare via re-GET pre-PATCH. The `client.js` `opts.headers` plumbing change is still required (sending `If-Match` is harmless and audit-logs the intent).
- **Acceptance grep gate** at SPEC.md:107 -- `grep -nE "createFungiAsset|resolveOrCreateAsset" src/agents/alerter/src/farmos/commits/` must return zero after migration.

### File Created
`.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner can now reference analog patterns in PLAN.md files.
