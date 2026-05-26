# Phase 51: Order-independent farmOS writes — Research

**Researched:** 2026-05-24
**Domain:** farmOS JSON:API write semantics (Drupal core JSON:API) + alerter Node.js commit primitives
**Confidence:** HIGH on existing code shape and Drupal JSON:API spec semantics; HIGH on a critical SPEC/CONTEXT contradiction (test framework); HIGH on a second critical contradiction (etag concurrency on Drupal JSON:API)

## Summary

The phase is mechanically straightforward in code shape — extend three existing alerter modules (`assets.js`, `logs.js`, `audit-logger.js`), add one new `merge.js`, extend the mock client to support PATCH, and add property tests. The existing `client.patch` method already exists (`client.js:169`); `opts.headers` is **not** currently honored by `_doFetch`, so plumbing custom request headers is a small required change.

Two findings warrant a planner-side decision before tasks land:

1. **CONTEXT.md misidentifies the test framework.** It says "Use Node `node:test` (already in use across the alerter suite)" but the alerter is **100% Jest** (`package.json` `"test": "jest"`, `devDependencies.jest ^29.7.0`, `jest.fn()` in `mock-client.js`, `describe/it/expect` in every `test/farmos/*.test.js`). Planner must override to Jest or surface to user.
2. **farmOS JSON:API does not support `If-Match`/etag optimistic concurrency.** Drupal core JSON:API operates last-write-wins. `drupal_internal__revision_id` is exposed in GET responses but the server does NOT honor `If-Match` against it on PATCH — no 412 is ever returned by core. UPSERT-04 as specified ("PATCH carries If-Match; on 412 retry once") is technically infeasible against stock farmOS. Planner must decide between: (a) read-revision-id, compare manually after GET, abort if changed pre-PATCH (a soft check, not a true concurrency primitive); (b) drop the concurrency primitive and accept last-write-wins since single-writer-per-tenant already holds (per CONTEXT.md Constraints); (c) wait until farmOS adds it (deferred).

Additionally, the JSON:API spec offers a **better merge primitive** for the set-union case: `POST /api/asset/fungi/{uuid}/relationships/parent` with the new identifiers in `data[]` appends without replacement. The locked design uses full-entity PATCH with merged `relationships` — this is correct and works, but the planner should know the alternative exists for `parent[]`, `qr_codes[]`, `farm_id_tag[]` cases.

**Primary recommendation:** Plan as locked, but insert a discuss-phase checkpoint or planner-level call on (1) test framework (Jest vs node:test — confirm Jest) and (2) etag concurrency (recommend: degrade to soft revision_id compare + audit-log the mismatch, no 412 retry loop since farmOS won't return 412).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Lookup by name (cached) | Alerter (Node) | farmOS JSON:API | `NAME_CACHE` LRU already in `assets.js`; lookup → `GET /api/asset/fungi?filter[name][value]=` |
| Merge logic (set-union, scalar conflict, notes dedup) | Alerter (pure module `merge.js`) | — | Pure function; no I/O; lives outside HTTP layer for property-test isolation |
| Write transport (POST + PATCH) | Alerter `client.js` → farmOS JSON:API | — | `client.patch` already exists; `_doFetch` needs `opts.headers` plumbing for `If-Match` if kept |
| Identity / authority | farmOS JSON:API entity | Alerter mock for hermetic tests | UUID is server-assigned on POST; name is alerter-assigned (load-bearing for lookup) |
| Concurrency control | farmOS Drupal core entity save | — (no client-side primitive available) | **Drupal JSON:API has no native If-Match support** — last-write-wins at the server |
| Audit/observability | Alerter audit-logger + signal_draft_event row | Logger pipe (console) | Phase 40 D-06 dimension extension |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| jest | ^29.7.0 | Test framework | [VERIFIED: repo grep] Already in `src/agents/alerter/package.json`. Every farmos test uses `describe/it/expect/jest.fn`. |
| pg | ^8.20.0 | Postgres client (audit table writes) | [VERIFIED: package.json] Existing dep |
| node fetch (built-in) | Node ≥18 | HTTP transport for farmOS client | [VERIFIED: client.js] Uses `globalThis.fetch` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| crypto (built-in) | n/a | Property-test seed via `crypto.randomInt` | Permutation generation for UPSERT-06 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Jest | node:test | CONTEXT.md erroneously recommends this; would require migrating all sibling farmos tests. **Do not adopt.** |
| Jest | fast-check | CONTEXT.md correctly defers this. Hand-rolled permutations are sufficient at the cardinality (20 perms × 3 events = 60 cases) the SPEC requires. |
| Full-entity PATCH with merged relationships | POST to relationship endpoint `/api/asset/fungi/{uuid}/relationships/parent` with new IDs | [CITED: drupal.org/project/jsonapi/issues/2996339] Spec-clean way to append without GET-then-merge. Tradeoff: one extra HTTP call per array field (3 fields = +3 round-trips), and asset attribute updates (notes, status) still need full PATCH. Locked design (full PATCH) is simpler and matches the merge-result-then-PATCH flow. Recommend keeping locked choice. |

**Installation:** No new dependencies. All work uses existing Jest + built-ins.

**Version verification:**
```bash
node -e "console.log(require('/mnt/slime-kingdom/opt/mushy/src/agents/alerter/package.json').devDependencies)"
# Confirmed jest ^29.7.0 already present
```

## Package Legitimacy Audit

Not applicable — Phase 51 introduces **zero new dependencies**. All required primitives exist in current `package.json` (jest, pg, ulid, zod, ws) or Node built-ins (crypto, fetch). The package-legitimacy gate is trivially clean.

## Architecture Patterns

### System Architecture Diagram

```
                       Commit handler (commit-seeding-session / commit-seeding / commit-observation)
                                       │
                                       │ caller passes opts (name, parentIds, fungiTypeName, ...)
                                       ▼
                              upsertFungiAsset(client, opts) ──── assets.js (extends current primitives)
                                       │
                                       ├─ NAME_CACHE hit?  ──yes──▶ have assetId
                                       │                              │
                                       └── filter[name] GET ──────────┘
                                                       │
                                                  found? ──no──▶ POST /api/asset/fungi  ─── outcome=created
                                                       │                                       │
                                                       yes                                     ▼
                                                       │                                  return {assetId, outcome:created}
                                                       ▼
                                              GET /api/asset/fungi/{id}  (fetch full body for merge)
                                                       │
                                                       ▼
                                       mergeAssetFields(existing, incoming)  ── merge.js (pure)
                                                       │
                                                       ├──▶ conflicts.length > 0  ──▶ return {outcome:noop, conflicts}
                                                       │                                  (NO PATCH; caller decides)
                                                       │
                                                       ├──▶ merged === existing (no diff)  ──▶ return {outcome:noop}
                                                       │
                                                       ▼
                                              PATCH /api/asset/fungi/{id}  (with optional revision check)
                                                       │
                                                       ▼
                                       audit-logger.logCommit('upsert_outcome', draft, {outcome, conflicts, etag_source})

                       Parallel: upsertLog(client, 'seeding', opts) ─── logs.js
                                       │
                                       ├─ GET /api/log/seeding?filter[asset.id][value]=<uuid>
                                       │       │
                                       │   matches.length === 0  ──▶ POST  (outcome=created)
                                       │   matches.length === 1  ──▶ merge + PATCH  (outcome=patched/noop)
                                       │   matches.length > 1    ──▶ pick oldest by created; audit LogIdentityCollision warning
                                       ▼
                                  return {logId, outcome}
```

### Recommended Project Structure
```
src/agents/alerter/src/farmos/
├── assets.js              # add upsertFungiAsset, isStubAsset, STUB_BACKFILL_MARKER (extend; do not refactor existing exports)
├── logs.js                # add upsertLog + LOG_STABLE_KEYS table; keep createLog exported for callers outside commits/
├── merge.js               # NEW; pure mergeAssetFields(existing, incoming) → {merged, conflicts}; export per-rule helpers
├── audit-logger.js        # extend payload with {outcome, conflicts, etag_source}
└── commits/
    ├── commit-seeding-session.js   # migrate findAssetByName + createFungiAsset → upsertFungiAsset; logs.createLog → logs.upsertLog
    ├── commit-seeding.js           # same
    └── commit-observation.js       # logs.createLog stays (observation is POST-only this phase)

src/agents/alerter/test/farmos/
├── mock-client.js                  # extend: patch(), revision-id surface, 412 protocol (if kept)
├── merge.test.js                   # NEW; unit tests for mergeAssetFields rule table
├── assets.test.js                  # extend: upsertFungiAsset cases (hit/miss/conflict/identity-mutation)
├── logs.test.js                    # extend: upsertLog seeding stable-key cases
├── audit-logger.test.js            # extend: outcome dimension
└── upsert-property.test.js         # NEW; 3 properties × ≥20 permutations
```

### Pattern 1: Merge-then-PATCH with full entity body
**What:** GET the existing entity, run pure `mergeAssetFields(existing, incoming)`, PATCH the merged body. Drupal JSON:API PATCH semantically replaces relationship arrays in their entirety — so the merged body must already contain the union.
**When to use:** Default path for every UPSERT-01/02 hit case.
**Example:**
```javascript
// Source: drupal.org/docs/core-modules-and-themes/core-modules/jsonapi-module/updating-existing-resources-patch
// PATCH replaces the relationship's value with whatever data array you send.
// Therefore the caller MUST construct the full merged set:
const patchBody = {
  data: {
    type: 'asset--fungi',
    id: assetId,
    attributes: { notes: { value: mergedNotes, format: 'plain_text' } },
    relationships: {
      parent: { data: mergedParentIds.map((id) => ({ type: 'asset--fungi', id })) },
      // qr_codes, farm_id_tag etc — full union, not delta
    },
  },
};
await client.patch(`/api/asset/fungi/${assetId}`, patchBody);
```

### Pattern 2: Per-relationship POST (alternative; **not chosen**)
**What:** `POST /api/asset/fungi/{uuid}/relationships/parent` with `data: [{type, id}]` appends without replacement.
**When to use:** When you want spec-clean append semantics without a GET-then-merge cycle. **Not chosen** here because the merge logic also needs to handle scalar conflicts + notes dedup, which require the full-entity GET anyway.

### Pattern 3: Pure merge function with structured conflict return
**What:** `mergeAssetFields(existing, incoming) → {merged, conflicts: [{field, existing, incoming, kind}]}`. Empty `conflicts` on happy path. Throw `IdentityMutationError` for name/type changes.
**When to use:** Always; the caller (`upsertFungiAsset`) decides whether to PATCH or no-op based on `conflicts.length`.

### Anti-Patterns to Avoid
- **PATCHing relationship arrays with the incoming set only.** Drupal JSON:API treats `relationships.parent.data` as a full replacement. Sending `data: [newParentId]` when existing has `[oldParentId]` will **drop oldParentId**. UPSERT-03's set-union rule is exactly the prevention.
- **Trusting `If-Match` to work against farmOS.** Drupal core JSON:API does not honor `If-Match` against `drupal_internal__revision_id`. Sending the header is harmless (server ignores it) but expecting a 412 response from a concurrent PATCH is wrong. See Common Pitfalls below.
- **Using `node:test` per CONTEXT.md instruction.** The alerter suite is Jest; mixing frameworks would fragment the test runner config.
- **Body-cache memoization in this phase.** CONTEXT.md correctly defers it — body cache must invalidate on every PATCH; correctness > optimization at this scale.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP concurrency primitive against farmOS | A custom `If-Match` retry loop expecting 412 from farmOS | Recognize farmOS won't return 412; degrade to "GET → compare revision_id → if changed since merge-input, abort & re-do" as a soft check, OR drop concurrency primitive entirely | [CITED: drupal.org/project/farm/issues/3216766, drupal.org/project/drupal/issues/2993557] Drupal JSON:API does not implement `If-Match` against entity revisions. The 412 path the SPEC describes cannot be exercised against stock farmOS. |
| Permutation generator for property tests | A custom Fisher-Yates + seeded PRNG from scratch | Use `crypto.randomInt(0, n)` in a Fisher-Yates loop, log the seed | [VERIFIED: Node built-in crypto] 5-line implementation; matches CONTEXT.md "no fast-check" lock |
| Set-union over UUID strings | A nested-loop dedup | `Array.from(new Set([...existing, ...incoming]))` preserves order of first appearance | [VERIFIED: ECMAScript Set semantics] Stable insertion order is spec-guaranteed |
| Multi-result log query handling | Custom oldest-by-`created` sort against the full result body | `Array.prototype.sort` on the `data[]` by `attributes.created` ascending; pick `[0]` | [VERIFIED: farmOS attribute schema] `created` is an ISO timestamp string; lexicographic sort works |
| Notes-field dedup | Hashing or content-fingerprinting | Split on `\n---\n`, exact-string compare each entry | CONTEXT.md locks this; no need for fuzzy matching |

**Key insight:** The bulk of this phase is gluing existing primitives, not inventing new ones. The only genuinely new logic is the `mergeAssetFields` rule table, which is intentionally a single pure module with property-test coverage.

## Runtime State Inventory

> This is a code+test phase touching only the alerter agent. No data migrations, no OS-level state, no live-service config changes.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None for code path.** Production farmOS already contains the 4 May-22 stubs + 11 children + 11 seeding logs from the 2026-05-24 prod write (UUIDs in `.planning/notes/2026-05-24-prod-write-receipt-uuids.json`). These become test fixtures, not migrations — the Phase 51 code is meant to enrich them in-place when the 2025-scan-backfill runs (separate phase). | No data migration in this phase. |
| Live service config | None — farmOS configuration unchanged. No new modules enabled. (`farm_group` enable is explicitly out-of-scope per SPEC Boundaries.) | None. |
| OS-registered state | None — no systemd unit, cron, scheduler, or pm2 registration changes. Alerter container will pick up the new code on next `docker compose up -d --build alerter`. | Standard alerter rebuild deploy after merge. |
| Secrets / env vars | None new. Existing `FARMOS_URL`, `FARMOS_USERNAME`, `FARMOS_PASSWORD` are used by live-fire script (already configured in dev .env). | None. |
| Build artifacts / installed packages | None — no new npm deps. `package-lock.json` will be unchanged in this phase. | None. |

**Nothing in any category requires manual ops.** This is a pure-code phase shipped via the standard alerter container rebuild.

## Common Pitfalls

### Pitfall 1: PATCH with partial relationship array silently drops existing members
**What goes wrong:** A developer thinks "I'm adding a parent, so I'll PATCH with the new parent in the array." Drupal JSON:API treats `relationships.parent.data = [newId]` as a full replacement → existing parents are removed.
**Why it happens:** The JSON:API spec is explicit ("PATCH always completely replaces the value of a relationship field") but is counter-intuitive coming from REST APIs that often append.
**How to avoid:** UPSERT-03's set-union rule + property-test 1 (order independence) catches this directly. `mergeAssetFields` MUST be called before every PATCH.
**Warning signs:** Test asserts `parent.length === 2` after a sequence of two upserts — the locked acceptance criterion catches this.

### Pitfall 2: farmOS does not honor `If-Match` — silent last-write-wins on concurrent PATCH
**What goes wrong:** The locked SPEC says "on a 412 Precondition Failed, the upsert retries the GET + merge + PATCH cycle exactly once". Stock Drupal JSON:API will never return 412 from a PATCH regardless of `If-Match`. A concurrent writer's edits are silently overwritten by whichever PATCH lands last.
**Why it happens:** Drupal JSON:API core has not implemented optimistic concurrency. The `drupal_internal__revision_id` attribute is exposed on GET responses but is not consumed by `If-Match` on PATCH. Open Drupal issues (#2993557, #3216766) confirm this is a long-standing feature gap.
**How to avoid:** Three options for the planner to pick from:
  - **(a) Soft revision-id compare (recommended).** Before PATCH, re-GET, compare `attrs.drupal_internal__revision_id` with the value captured in the original GET that fed the merge. If changed → re-merge (retry once) or audit-log and abort. Costs one extra HTTP round-trip per PATCH but matches the SPEC's semantic intent.
  - **(b) Drop the concurrency primitive.** Rely on the single-writer-per-tenant invariant (CONTEXT.md Constraints explicitly states this holds). Audit-log `etag_source: 'unavailable'`. Cheapest; most honest about what farmOS supports.
  - **(c) Defer.** Skip UPSERT-04 entirely until the farmOS upstream lands JSON:API etag support.
**Warning signs:** A property test of "two concurrent upserts to the same name with different field-sets" would expose this — but CONTEXT.md doesn't require that test. Worth adding.

### Pitfall 3: NAME_CACHE staleness after PATCH
**What goes wrong:** The cache maps `name → assetId`. PATCH does not change the assetId (UUID is stable), so the cache stays valid post-PATCH. BUT if the PATCH **changed the name attribute** (which UPSERT-03 forbids via `IdentityMutationError`), the cache would point a stale name at the asset. Since identity-mutation throws, this can't happen at runtime — but adding a body cache later (deferred per CONTEXT.md) would re-open the issue.
**Why it happens:** Caches are correctness traps in CRUD layers when the cached key is mutable.
**How to avoid:** UPSERT-03's identity-protect rule is the structural defense. Document in `assets.js` why NAME_CACHE survives PATCH without invalidation (because name is immutable on the upsert path).
**Warning signs:** A future engineer adds "rename a fungi asset" — they must invalidate the cache and remove the identity check; mark this in code comments now.

### Pitfall 4: Mock client missing `client.delete` parity
**What goes wrong:** `mock-client.js` exports `get`, `post`, `postBinary` but NOT `patch` or `delete`. Phase 48 already added `client.delete` to the real client and `commit-seeding-session._cleanup` calls it — but the mock surface was never extended. Phase 51 must add `patch`, and **should also add `delete`** while it's open (it's currently fine because no test hits the cleanup path, but it's a latent gap).
**Why it happens:** Mock clients drift behind real clients when each new feature extends the real surface but tests stub-around the gap.
**How to avoid:** Make extending the mock client a single dedicated task (CONTEXT.md migration order item #5). Add `patch` + revision-id surface; optionally add `delete` as a freebie.
**Warning signs:** Property tests want to simulate stale-revision retry but `mockClient.patch` doesn't exist → planner discovers the gap mid-task and bolts it on. Front-load the mock extension.

### Pitfall 5: `mushy:draft:<draftId>` trailer duplicates across notes-dedup
**What goes wrong:** Existing `createFungiAsset` appends `mushy:draft:<draftId>` to every notes write. If the same draft is committed twice (rare but possible — Phase 40 idempotency is at `signal_draft.id`, not at farmOS), the dedup rule should collapse the trailer to one occurrence per unique draftId.
**Why it happens:** The trailer is content, not metadata; treating it as data passes through the dedup rule naturally.
**How to avoid:** CONTEXT.md locked: "The `mushy:draft:<draftId>` trailer is treated as an entry like any other." Property test "stub enrichment" needs to assert this — if not already covered, add an explicit test for "PATCH with same draftId is idempotent in notes."
**Warning signs:** Notes field grows on every retry — visible in audit log if size unbounded.

### Pitfall 6: `created` log timestamp tie-breaks
**What goes wrong:** SPEC says "pick oldest by `created`" on multi-result seeding log query. If two logs share `created` to the second (unlikely but not impossible during a batch session commit), the tie-break is undefined.
**Why it happens:** farmOS issues `created` at write time at second-grain.
**How to avoid:** Document tie-break as "lexicographic by `id` (UUID string)" — deterministic, stable, and the property test should seed two same-second logs to verify.
**Warning signs:** Property test flakes on multi-result selection — almost never, but worth the 3 lines of code.

## Code Examples

Verified patterns sourced from the existing alerter codebase:

### Current mock-client pattern (extend, don't replace)
```javascript
// Source: src/agents/alerter/test/farmos/mock-client.js
const client = {
  _created: created,
  _calls: calls,
  get: jest.fn(async (path, opts) => { /* filter-based dispatch */ }),
  post: jest.fn(async (path, body, opts) => { /* assigns id, records body */ }),
  postBinary: jest.fn(async (path, bytes, opts) => { /* file upload */ }),
};
// TO ADD: patch: jest.fn(async (path, body, opts) => { ... revision_id handling ... })
```

### Current upsert candidate (replace this)
```javascript
// Source: src/agents/alerter/src/farmos/assets.js:113
async function resolveOrCreateAsset(client, opts) {
  const lookup = await findAssetByName(client, opts.name);
  if (lookup.found) return { ok: true, assetId: lookup.assetId, reused: true };
  return createFungiAsset(client, opts);
}
// This swallows incoming opts on a hit. New upsertFungiAsset must GET-then-merge-then-PATCH.
```

### Current commit-path call site (will be migrated)
```javascript
// Source: src/agents/alerter/src/farmos/commits/commit-seeding-session.js:121
const found = await assets.findAssetByName(client, parentName);
if (found.found) {
  sourceBlockId = found.assetId;
} else {
  const created = await assets.createFungiAsset(client, { name: parentName, fungiTypeName: species, fungiXingName: 'block', draftId });
  ...
}
// Migrates to: const r = await assets.upsertFungiAsset(client, {...}); if (!r.ok) return _cleanup(...);
```

### Pattern: full-entity merge-then-PATCH (Drupal-spec-compliant)
```javascript
// Source: drupal.org/docs/.../updating-existing-resources-patch (spec); locked design from CONTEXT.md
const get = await client.get(`/api/asset/fungi/${assetId}`);
const existing = get.body.data;
const revisionIdBefore = existing.attributes.drupal_internal__revision_id; // for soft compare (Pitfall 2)
const { merged, conflicts } = mergeAssetFields(existing, incoming);
if (conflicts.length > 0) {
  return { ok: true, assetId, outcome: 'noop', conflicts };
}
if (mergeIsNoop(existing, merged)) {
  return { ok: true, assetId, outcome: 'noop', conflicts: [] };
}
const patchBody = { data: { type: 'asset--fungi', id: assetId, attributes: merged.attributes, relationships: merged.relationships } };
const patchResp = await client.patch(`/api/asset/fungi/${assetId}`, patchBody /*, { headers: { 'If-Match': revisionIdBefore } } — see Pitfall 2 */);
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `findAssetByName + createFungiAsset` direct call sites | `upsertFungiAsset` (Phase 51) | 2026-05-24 → now | Order-independent writes; safe replay of any draft against any state |
| `logs.createLog` POST-only | `upsertLog` for seeding type | 2026-05-24 → now | Replay-safe seeding writes (B5 makes the stable key unambiguous) |
| Implicit "no merge" — resolveOrCreateAsset discards caller opts on hit | Explicit merge rule table + structured conflict | 2026-05-24 → now | Stub-enrichment becomes the same code path as real-inoc-write |

**Deprecated/outdated:**
- `resolveOrCreateAsset` becomes a thin wrapper around `upsertFungiAsset` (or is removed if not called externally). Grep first — it may have callers outside `commits/`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | [ASSUMED] farmOS exposes `attrs.drupal_internal__revision_id` on `GET /api/asset/fungi/{id}` responses for the `fungi` bundle. | Etag-guarded PATCH | Low; Drupal core JSON:API exposes this for all revisionable bundles, but farmOS `fungi` is a contrib bundle — should `curl` a known asset once to confirm. If absent → `etag_source: 'absent'` per CONTEXT.md degrade rule still works. |
| A2 | [ASSUMED] farmOS `log--seeding` supports filter `filter[asset.id][value]=<uuid>` for asset-relationship filtering. | upsertLog stable key | Low-medium; this is standard Drupal JSON:API relationship-filter syntax and is already used implicitly in similar contexts. Verify with one live `curl` against dev before plan locks. |
| A3 | [ASSUMED] farmOS does not normalize/trim the `notes.value` field on PATCH round-trip. | Notes dedup | Medium; if farmOS strips trailing whitespace or normalizes line endings, exact-string entry dedup will fail to identify duplicates. Verify by writing then reading a notes value with explicit `\n---\n` separator on dev. Mitigation if confirmed: normalize-on-read in `mergeAssetFields` (trim entries, normalize `\r\n` → `\n`). |
| A4 | [VERIFIED: WebSearch + Drupal issue #3216766] Drupal JSON:API does NOT honor `If-Match` against `drupal_internal__revision_id` on PATCH. | Etag-guarded PATCH | The locked SPEC/CONTEXT is therefore unachievable as literally written. Planner must pick a degraded approach. |
| A5 | [VERIFIED: package.json + test grep] Alerter uses Jest, not `node:test`. | Property-test framework | CONTEXT.md is wrong on this point. Planner must override to Jest. |

## Open Questions

1. **Concurrency primitive disposition** (driver: A4 above).
   - What we know: farmOS JSON:API returns 200 from PATCH regardless of `If-Match`. Last-write-wins.
   - What's unclear: Does CONTEXT.md's "single-writer-per-tenant invariant" hold strongly enough to drop the primitive (option b), or do we need the soft revision-id compare (option a)?
   - Recommendation: Option (a) soft compare — costs +1 GET per PATCH, gives best-effort detection, audit-logs mismatches. Plan a `checkpoint:human-verify` task to confirm the choice before merge.

2. **Test framework migration risk** (driver: A5 above).
   - What we know: Every existing farmos test is Jest.
   - What's unclear: Was CONTEXT.md "node:test" a typo or did discuss-phase actually intend a migration?
   - Recommendation: Treat as typo; plan uses Jest. Surface to user in plan summary.

3. **`resolveOrCreateAsset` external callers.**
   - What we know: `commits/*.js` call paths grep clean once migrated.
   - What's unclear: Is `resolveOrCreateAsset` called from any non-`commits/` site (e.g. tests, scripts/, watchdog)?
   - Recommendation: Plan includes a `grep -rn "resolveOrCreateAsset" src scripts test` task; either migrate non-commit callers or leave the export as a back-compat wrapper.

4. **Notes-field round-trip fidelity** (driver: A3 above).
   - What we know: SPEC locks `\n---\n` exact-string dedup.
   - What's unclear: Does farmOS preserve raw whitespace through PATCH?
   - Recommendation: One live-fire `curl` against dev farmOS to write and read a notes value with `entry1\n---\nentry2` and diff. Add to plan as a Wave 0 sanity check before merge logic locks.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | Alerter agent + tests | ✓ | 18+ (Jest 29 baseline) | — |
| Jest | Hermetic test suite | ✓ | ^29.7.0 (devDep) | — |
| Dev farmOS (`http://10.68.155.50:18080`) | UPSERT-07 live-fire | ✓ | farmOS 3.x — mushy-bot has fungi CRUD via `farm_manager` role | — |
| Prod farmOS (`http://10.68.155.50:8082`) | NOT required for Phase 51 | n/a | n/a | Out of scope |
| docker / docker compose | Alerter container deploy post-merge | ✓ | v2 on elder-plops | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Jest ^29.7.0 |
| Config file | `src/agents/alerter/package.json` (`"test": "jest"` script; Jest auto-discovers `**/test/**/*.test.js`) |
| Quick run command | `cd src/agents/alerter && npx jest test/farmos/<file>.test.js` |
| Full suite command | `cd src/agents/alerter && npm test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UPSERT-01 | `upsertFungiAsset` lookup-merge-or-create; commit code paths no longer call `createFungiAsset` directly | unit + grep-gate | `npx jest test/farmos/assets.test.js` + `grep -nE "createFungiAsset\\|resolveOrCreateAsset" src/agents/alerter/src/farmos/commits/` | ❌ Wave 0 (extend existing assets.test.js) |
| UPSERT-02 | `upsertLog` seeding stable-key lookup; idempotent replay | unit | `npx jest test/farmos/logs.test.js` | ❌ Wave 0 (extend existing logs.test.js) |
| UPSERT-03 | `mergeAssetFields` rule table — set-union, identity-throw, scalar-equal noop, scalar-conflict, notes dedup | unit | `npx jest test/farmos/merge.test.js` | ❌ Wave 0 (new file) |
| UPSERT-04 | Etag retry — either soft revision-id compare or degrade-noop (per planner decision on Pitfall 2 / OQ#1) | unit | `npx jest test/farmos/assets.test.js -t "revision"` | ❌ Wave 0 |
| UPSERT-05 | `isStubAsset` predicate; true on STUB marker, false otherwise | unit | `npx jest test/farmos/assets.test.js -t "isStub"` | ❌ Wave 0 |
| UPSERT-06 | Property tests — order independence (≥20 permutations), stub enrichment, conflict surfacing | property | `npx jest test/farmos/upsert-property.test.js` | ❌ Wave 0 (new file) |
| UPSERT-07 | Live-fire dev replay reports created=0, patched≥4, no duplicate UUIDs | manual+script | `FARMOS_URL=... node scripts/live-fire-51.js` | ❌ Wave 0 (new file or fork of `live-fire-48.js`) |
| Constraint: 1032+ hermetic tests still pass | Regression — no break in any existing test | regression | `cd src/agents/alerter && npm test` | ✓ existing |
| Constraint: 48-LIVE-FIRE happy path on dev still 16 assets + 11 logs | Regression — live-fire-48 still passes | live-fire | `FARMOS_URL=... node scripts/live-fire-48.js` against fresh dev state | ✓ existing |

### Sampling Rate
- **Per task commit:** `npx jest test/farmos/<changed-file>.test.js` (≤ 5s typical)
- **Per wave merge:** `cd src/agents/alerter && npm test` (full hermetic suite; ≤ 30s historically)
- **Phase gate:** Full suite green + UPSERT-07 live-fire dev attestation green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `test/farmos/merge.test.js` — NEW; covers UPSERT-03 (5 rule cases + identity throw)
- [ ] `test/farmos/upsert-property.test.js` — NEW; covers UPSERT-06 (3 properties × ≥20 permutations)
- [ ] `scripts/live-fire-51.js` — NEW (or sibling of `live-fire-48.js`); covers UPSERT-07
- [ ] `test/farmos/mock-client.js` extension — `patch()` method + revision-id surface
- [ ] No framework install — Jest already present

## Security Domain

Phase 51 is purely an internal write-layer refactor. No new attack surface; no new env vars; no new endpoints exposed. Existing farmOS auth (session cookie + CSRF + basic auth) and Postgres pool patterns are unchanged.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (unchanged from Phase 40) | Session cookie + CSRF — existing |
| V3 Session Management | no | — |
| V4 Access Control | no (mushy-bot role / `farm_manager` perms unchanged) | Drupal role config — already governed |
| V5 Input Validation | yes | Incoming `opts` to `upsertFungiAsset` must validate UUID shape for parentIds; `mergeAssetFields` must validate that incoming relationship `data[]` elements have `{type, id}` structure before set-union. Reject malformed input with structured error. |
| V6 Cryptography | no | No crypto operations introduced |

### Known Threat Patterns for Drupal JSON:API write layer

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| UUID injection via untrusted `parentIds` array (a malformed draft places non-fungi UUIDs in `parent[]`) | Tampering | Validate each parentId is a UUID-v4 string before PATCH; farmOS would 422 anyway, but fail-fast at merge time with `{ok: false, reason: 'invalid_parent_uuid'}` |
| Notes-field XSS via `\n---\n` boundary trick | Tampering / Spoofing | `notes.format = 'plain_text'` already enforced (Phase 40). Plain-text format means Drupal renders escaped. No new vector. |
| Concurrent-write race producing inconsistent merged state | Tampering (data integrity) | farmOS JSON:API can't help (no If-Match). Mitigation: single-writer-per-tenant invariant (CONTEXT.md Constraints) + soft revision-id compare in audit-log. |

## Sources

### Primary (HIGH confidence)
- `src/agents/alerter/src/farmos/assets.js` — read in full; current primitives confirmed
- `src/agents/alerter/src/farmos/logs.js` — read in full; current primitives confirmed
- `src/agents/alerter/src/farmos/audit-logger.js` — read in full; payload shape confirmed
- `src/agents/alerter/src/farmos/client.js` — confirmed `client.patch` exists at line 169; confirmed `opts.headers` is NOT currently plumbed through `_doFetch`
- `src/agents/alerter/src/farmos/commits/{commit-seeding-session,commit-seeding,commit-observation}.js` — all read; call sites of `createFungiAsset`/`createLog` enumerated
- `src/agents/alerter/test/farmos/mock-client.js` + `test/farmos/assets.test.js` — confirmed Jest (`jest.fn`, `describe/it/expect`)
- `src/agents/alerter/package.json` — confirmed `"test": "jest"`, `jest ^29.7.0` devDep
- `src/agents/alerter/scripts/live-fire-48.js` — confirmed harness shape; UPSERT-07 will fork or sibling-copy
- `.planning/phases/51-.../51-SPEC.md` + `51-CONTEXT.md` — read in full
- `.planning/notes/2026-05-24-prod-write-receipt.md` + `prod-write-receipt-uuids.json` — read; 4 stub UUIDs + 11 children + 11 logs identified as test fixtures
- `.planning/notes/2026-05-24-session-as-asset-group-design.md` — confirms `asset--group` work is separate phase, composes with this layer
- `.planning/notes/2026-05-24-v1.9-uat-findings.md` — confirms observation-of-unknown-asset principle drives UPSERT-05 contract

### Secondary (MEDIUM confidence)
- [Drupal JSON:API "Updating existing resources (PATCH)"](https://www.drupal.org/docs/core-modules-and-themes/core-modules/jsonapi-module/updating-existing-resources-patch) — PATCH semantics for relationships (full replacement) — CITED
- [Drupal issue #2996339 — Adding a new value to a multi-value relationship field without losing existing data](https://www.drupal.org/project/jsonapi/issues/2996339) — POST to `/relationships/{field}` as append primitive — CITED
- [Drupal issue #3216766 — Revisions are not supported on JSON API (farmOS context)](https://www.drupal.org/project/farm/issues/3216766) — confirms revision/etag gap — CITED
- [Drupal issue #2993557 — Allow optional creation of new revision when PATCHing revisionable entities](https://www.drupal.org/project/drupal/issues/2993557) — confirms ongoing work on revision-aware PATCH — CITED
- [farmOS API overview](https://farmos.org/development/api/) — confirms farmOS 2.x adheres to Drupal core JSON:API spec — CITED

### Tertiary (LOW confidence)
- WebSearch results on "JSON:API conflict detection" — no source claims farmOS implements 412 retry; all results show this is a Drupal feature gap. Not load-bearing.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified against `package.json` and test file grep.
- Architecture / module layout: HIGH — derived from existing module shape and CONTEXT.md locks.
- Pitfalls: HIGH — particularly Pitfall 2 (etag concurrency infeasibility) is verified by multiple Drupal issues.
- CONTEXT.md errors (test framework + etag concurrency): HIGH confidence these are mistakes that must be surfaced before planning locks.
- Notes round-trip behavior (A3): MEDIUM — needs one live `curl` to verify, mitigation path exists either way.

**Research date:** 2026-05-24
**Valid until:** 2026-06-23 (30-day window; farmOS-side schema is stable; Drupal JSON:API spec stable)

---

*Phase: 51-order-independent-farmos-writes-upsert-by-stable-identity-se*
*Research created: 2026-05-24*
*Next step: `/clear` then `/gsd-plan-phase 51` (planner must flag two CONTEXT.md corrections to user before locking plans: Jest vs node:test, and etag-concurrency degradation choice).*
