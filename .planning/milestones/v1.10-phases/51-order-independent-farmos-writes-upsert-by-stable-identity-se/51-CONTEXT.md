# Phase 51: Order-independent farmOS writes — Context

**Created:** 2026-05-24
**Mode:** auto-discuss (SPEC.md already locks WHAT/WHY; this captures HOW)

## Domain

farmOS write layer in `src/agents/alerter/src/farmos/`: turn create-only primitives (`createFungiAsset`, `createLog`) into content-addressable upserts so out-of-order events converge to the same state.

## SPEC Lock

`51-SPEC.md` locks 7 requirements (UPSERT-01..07), boundaries, and 9 acceptance criteria. Downstream agents MUST read SPEC.md before planning. This CONTEXT.md captures only implementation decisions — it does NOT restate WHAT/WHY.

## Canonical Refs

- `.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-SPEC.md` — locked requirements; MUST read before planning
- `.planning/ROADMAP.md` — Phase 51 section (UPSERT-01..07 listing with driver)
- `.planning/STATE.md` — v1.10 milestone state; 2026-05-24 closeout has the prod-write narrative
- `.planning/notes/2026-05-24-prod-write-receipt.md` — narrative of the May-22 inoc prod write + stub strategy
- `.planning/notes/2026-05-24-prod-write-receipt-uuids.json` — the 4 stub UUIDs in prod (used by live-fire fixture)
- `.planning/notes/2026-05-24-session-as-asset-group-design.md` — asset--group design that composes with this layer
- `.planning/notes/2026-05-24-v1.9-uat-findings.md` — observation-backfill principle (drives UPSERT-05's stub-merge contract)
- `src/agents/alerter/src/farmos/assets.js` — current `findAssetByName` / `createFungiAsset` / `resolveOrCreateAsset`
- `src/agents/alerter/src/farmos/logs.js` — current `createLog`; `NATIVE_LOG_TYPES` table to extend
- `src/agents/alerter/src/farmos/audit-logger.js` — payload shape to extend with `outcome` dimension
- `src/agents/alerter/test/farmos/mock-client.js` — mock surface to extend (PATCH + etag + 412)
- `scripts/live-fire-48.js` — fixture-replay harness; UPSERT-07 live-fire extends or sibling-copies this

## Code Context

**Reusable primitives:**

- `NAME_CACHE` LRU (capped at 32) in `assets.js` — keep as-is. `upsertFungiAsset` uses it on the lookup leg; PATCH does not invalidate name→id (the mapping stays valid post-PATCH). Body cache is NOT added in this phase.
- `qr.bindQrOnCreate` — POST path keeps it. PATCH path needs a sibling `qr.bindQrOnPatch` (or inline in merge); decided in plan.
- `fungiTypeCache` / `fungiXingCache` — taxonomy term UUID resolution is already memoized; merge logic uses the cached UUIDs.
- `audit-logger.js` `logCommit` — extend payload with `outcome` (string: `created|patched|noop`) and `conflicts` (array, empty when none).

**Test infrastructure:**

- `test/farmos/mock-client.js` — fake HTTP surface; extend with `mockPatch(path, response)` and an etag/412 protocol.
- 13 commit tests already exercise the create-only happy path. They get migrated to the upsert primitive; existing assertions on `assetId` shape stay valid (return contract preserved).

**B5 invariant:** one seeding log per child asset ([[project_b5_seq_is_per_session_not_per_strain]]). This is the load-bearing fact for the `upsertLog` seeding stable-key choice.

## Decisions

### Module layout

- `_mergeAssetFields` lives in a **new** `src/agents/alerter/src/farmos/merge.js`. Pure function, zero client / network deps — keeps property tests fast and isolation-friendly. Exports `mergeAssetFields(existing, incoming) → {merged, conflicts}` plus the per-rule helpers if useful for unit tests.
- `isStubAsset(asset)` lives in `assets.js` alongside the cache + lookup primitives — same module reads the `notes` field anyway. Marker string is exported as a named constant `STUB_BACKFILL_MARKER`.
- `upsertFungiAsset` is added to `assets.js` (extends the existing primitive set). `createFungiAsset` stays exported for back-compat but is no longer called from commit code paths (grep-gate per acceptance criteria).
- `upsertLog` + per-type stable-key table live in `logs.js`. Stable-key rules table is a top-level `const LOG_STABLE_KEYS = { seeding: ({assetIds}) => ({asset_id: assetIds[0]}), ... }` — other log types start with `null` (POST-only, current behavior preserved). Only `seeding` migrates in this phase.

### Notes-field representation

- **Locked:** free-text concatenation with marker-aware dedup. Reason: structured `notes_entries` would require a farmOS field-schema change (out of scope per SPEC.md). Today's `notes: {value: string, format: 'plain_text'}` shape is preserved.
- **Dedup rule:** split existing on `\n---\n`, normalize entries (trim), dedup by exact-string equality, append incoming entries that are not already present, rejoin with `\n---\n`. The `mushy:draft:<draftId>` trailer is treated as an entry like any other (so re-applying the same draft is idempotent).
- **Stub marker preservation:** `STUB - awaits 2025-paper-scan backfill` is never stripped on enrichment merge — `isStubAsset` continues to return true until the 2025-scan-backfill code explicitly clears it (separate phase).

### Etag-guarded PATCH

- Etag source: `attrs.drupal_internal__revision_id` from the GET that fed the merge. This is what farmOS's JSON:API exposes and what `If-Match` consumes against asset/log entities.
- 412 retry budget: **exactly 1**, no backoff. Second 412 → return `{ok: false, reason: 'concurrency_exhausted'}` (structured, not thrown). Caller surfaces via audit-logger.
- If the GET response is missing `drupal_internal__revision_id` (shouldn't happen in practice but mock client should cover it), PATCH proceeds **without** `If-Match` and the audit log gets `etag_source: 'absent'`. Decision: degrade-not-block — losing optimistic concurrency on one entity is preferable to losing the entire write.

### Conflict-surfacing semantics

- `mergeAssetFields` returns `{merged, conflicts: [{field, existing, incoming, kind: 'scalar_conflict'}]}`. Empty `conflicts` array on the happy path.
- `upsertFungiAsset` on non-empty conflicts: **does not PATCH**. Returns `{ok: true, assetId, outcome: 'noop', conflicts}`. The commit caller decides whether to (a) hard-fail with reason `field_conflict` (current default for v1.10), or (b) route to a farmer ack (deferred to a later phase that wires the ack UX).
- **Identity-mutation** (`name` or `type`/bundle differs): `mergeAssetFields` THROWS `IdentityMutationError`. This is a programmer error, not a data event — it means a caller is trying to upsert with the wrong primary key.

### Stable-key table for `upsertLog`

| log type    | stable key                                | this phase? |
|-------------|-------------------------------------------|-------------|
| seeding     | `(type='seeding', asset.id == assetIds[0])` | YES        |
| activity    | none — POST-only                          | no          |
| input       | none — POST-only                          | no          |
| observation | none — POST-only                          | no (different farmer-facing semantics still being shaped) |
| harvest     | none — POST-only                          | no          |

The seeding query: `GET /api/log/seeding?filter[asset.id][value]=<uuid>`. If >1 matches (B5 violation), the upsert layer treats the oldest by `created` as canonical, surfaces a `LogIdentityCollision` warning via audit-logger, and PATCHes the oldest.

### Audit-log outcome dimension

- `audit-logger.js` `logCommit` payload gains:
  - `outcome`: `'created' | 'patched' | 'noop'` (per write, aggregated when multiple writes happen in one commit — drop to `'mixed'` when set has >1)
  - `conflicts`: array, default `[]`
  - `etag_source`: `'revision_id' | 'absent'`
- Backfill of pre-Phase-51 audit rows is out of scope (per SPEC.md Constraints).

### Property-test seeding strategy

- Use Node `node:test` (already in use across the alerter suite). NO new `fast-check` dependency — keep the dep tree lean.
- Custom permutation generator: 20 permutations per property, seeded via `crypto.randomInt`. Print the seed on failure for repro.
- Property test file lives at `src/agents/alerter/test/farmos/upsert-property.test.js`.
- Fixtures: a reusable "May-22 + Jan-18 + Mar-04 inoc events" trio (small literal JSON) that exercises the multi-parent shape ([[project_inoc_shape_multi_parent_batch]]).

### Migration order (informs plan-phase task ordering)

1. `merge.js` + unit tests (pure function, no I/O dependency)
2. `upsertFungiAsset` in `assets.js` + tests; `createFungiAsset` callers in commit paths migrated
3. `upsertLog` for seeding in `logs.js` + tests; `commit-seeding-session` + `commit-seeding` migrated
4. `audit-logger` extension (outcome / conflicts / etag_source)
5. `mock-client` PATCH + 412 surface
6. Property test file
7. Live-fire script + dev attestation run

## Deferred Ideas

- **`asset--group` migration to upsert** — composes with this layer (same primitives) but blocked separately on farmOS enabling `farm_group`. Phase 52+ candidate.
- **Observation/harvest/input upsert** — defer until each has a clear stable-key rule. Observation in particular needs farmer-ack UX decisions first.
- **Structured `notes_entries` field** — would supersede the free-text dedup approach. Requires farmOS schema migration; farmos team work, not alerter.
- **Backfill of existing audit-log rows with outcome dimension** — out of scope per SPEC.md Constraints. Tracked as a v1.10+ todo if anyone wants historical analytics.
- **Farmer-ack on field conflicts** — UPSERT-03 makes conflict surfacing structured; wiring the farmer-facing flow (ask-back on `fungi_type=KOY` vs. existing `=SHI`) is a follow-on phase.
- **Body-level cache (full asset JSON memoization)** — current name-only cache stays. A body cache could reduce GETs on PATCH but adds invalidation complexity; revisit if write volumes climb.
- **Fast-check property-test framework** — dep cost not justified at current scale; revisit if hand-rolled permutations start missing edge cases.

## Discussion Log

This phase ran auto-discuss because SPEC.md (commit `62a77c6`) already locked all 7 requirements with current/target/acceptance precision (ambiguity score 0.13). The remaining gray areas were implementation choices the SPEC explicitly deferred ("decide in plan"):

| Gray area | Auto-decision | Reasoning |
|-----------|--------------|-----------|
| Notes representation | Free-text concat w/ `\n---\n` dedup | Avoids farmOS schema migration (SPEC out of scope); current `notes.value` shape preserved |
| `_mergeAssetFields` location | New `merge.js` (pure module) | Property-test isolation; zero client deps |
| `isStubAsset` location | `assets.js` (with `STUB_BACKFILL_MARKER` const) | Same module reads `notes` anyway |
| Etag retry budget | Exactly 1; degrade-not-block on missing revision_id | SPEC locked the count; degrade rule prevents single-entity etag absence from killing whole write |
| Conflict surfacing | Return `{outcome: 'noop', conflicts: [...]}`, do NOT PATCH on conflict | Caller (commit code) chooses hard-fail vs. farmer-ack |
| Identity mutation | Throw `IdentityMutationError` | Programmer error, not data event |
| upsertLog migration scope | Seeding only; others stay POST | Smallest safe surface; B5 makes seeding's stable key unambiguous |
| Audit-log additions | `outcome`, `conflicts`, `etag_source` fields | Minimal observability dimension; matches UPSERT-06 acceptance |
| Property-test framework | Node `node:test` + custom permutations | No new dep; matches existing test infra |

No scope creep introduced. No prior-phase decisions were re-litigated.

---

*Phase: 51-order-independent-farmos-writes-upsert-by-stable-identity-se*
*Context created: 2026-05-24*
*Next step: `/clear` then `/gsd-plan-phase 51`*
