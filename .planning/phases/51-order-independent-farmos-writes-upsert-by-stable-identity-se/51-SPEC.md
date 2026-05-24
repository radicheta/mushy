# Phase 51: Order-independent farmOS writes — upsert-by-stable-identity + set-union merge — Specification

**Created:** 2026-05-24
**Ambiguity score:** 0.13 (gate: ≤ 0.20)
**Requirements:** 7 locked

## Goal

Every farmOS write (asset + log) becomes a content-addressable upsert keyed by the entity's natural identity, with set-union merge on array fields, conflict-surfacing on scalars, and etag-guarded PATCH — so the final farmOS state is a function of *which* events happened, not *what order* the pipeline observed them.

## Background

Today's write surface in `src/agents/alerter/src/farmos/`:

- `assets.js:38` `findAssetByName(client, name)` — name-keyed lookup, in-process cache.
- `assets.js:53` `createFungiAsset(client, opts)` — unconditional POST. No merge path.
- `assets.js:114` `resolveOrCreateAsset` — find-or-create. On hit it **returns the existing asset unchanged**; new field values from the caller are discarded. No PATCH.
- `logs.js` — `createLog` writes are always POST; no "find an existing seeding log for this child and merge."
- Commit paths (`commits/commit-seeding-session.js`, `commits/commit-observation.js`, `commits/commit-seeding.js`) all bottom out in those create-only primitives.

This was bearable until 2026-05-24:

1. The May-22 inoc landed in PROD farmOS by **stubbing 4 ancestor parents by hand** (`260304_SHI_5`, `260118_SHI_23`, `260118_SHI_26`, `260118_KOY_12`) with a structured `STUB - awaits 2025-paper-scan backfill` notes marker (see `.planning/notes/2026-05-24-prod-write-receipt.md`). When the 2025 paper notebook is scanned and processed, those inoc sessions will try to **create** the same assets again → name collision OR (with current `resolveOrCreateAsset`) silent reuse that **discards** the real inoc's fungi_type / parent[] / qr_codes[].
2. The farmer-is-reality-source-of-truth principle ([[feedback_farmer_is_reality_source_of_truth]]) says observation/harvest on an unknown asset must **mint with confirm**, never reject. But mint-from-observation gives a thin asset with no parents; the real inoc, when it arrives, must **enrich in place**, not create-conflict.
3. The asset--group / session-as-asset design ([[2026-05-24-session-as-asset-group-design]]) composes naturally with the upsert layer (same path), but is blocked separately on farmOS enabling `farm_group`. Phase 51 is the architectural lift that both flows depend on.

The primary deliverable that does NOT exist yet: `upsertFungiAsset` + `upsertLog` + a codified `_mergeAssetFields` rule table, with property-test coverage proving order independence.

## Requirements

1. **UPSERT-01 — `upsertFungiAsset`**: A new entry point in `assets.js` that does lookup-merge-or-create in one call.
   - Current: `resolveOrCreateAsset` returns existing assets unchanged; new field values from the caller are silently discarded. No PATCH path exists.
   - Target: `upsertFungiAsset(client, opts)` looks up by name → if found, PATCHes a merged field-set (per UPSERT-03) and returns the merged asset → if not, POSTs and returns the created asset. Return shape matches today's `createFungiAsset`. All existing callers (`commit-seeding-session`, `commit-observation`, `commit-seeding`, plus future) route through this; direct `createFungiAsset` calls in commit code paths are removed.
   - Acceptance: `findAssetByName + createFungiAsset` is no longer called directly from any `commits/*.js` file (grep proves it). Calling `upsertFungiAsset` twice with overlapping field-sets on the same name produces a single asset whose state reflects the merge.

2. **UPSERT-02 — `logs.upsertLog`**: Same shape for logs, keyed by per-type stable identity.
   - Current: `logs.createLog` is POST-only. Replaying a seeding event for the same child creates duplicate logs.
   - Target: `upsertLog(client, type, opts)` looks up by the per-type stable key — for `type='seeding'` that key is `(asset.id)` because B5 enforces one inoc event per child ([[project_b5_seq_is_per_session_not_per_strain]]). On hit → PATCH merged. On miss → POST. Per-type key rules live in a small table in `logs.js` and are unit-tested.
   - Acceptance: Replaying the May-22 seeding session against a farmOS that already has those 11 seeding logs produces zero net new logs (idempotent). The per-type stable-key table is documented in `logs.js` and exercised by unit tests for at least the `seeding` type.

3. **UPSERT-03 — `_mergeAssetFields(existing, incoming)`**: A pure function that codifies merge rules per field type.
   - Current: No merge logic. Field-level semantics live implicitly in `createFungiAsset` (it just writes whatever the caller passed).
   - Target: A documented rule table:
     - **Array-valued ref fields** (`parent[]`, `qr_codes[]`, `farm_id_tag[]`, any other `relationships.*` that is `data: [...]`) → set-union by `id`. Order is stable (existing first, new appended in input order).
     - **Scalar identity fields** (`name`, `type`/bundle) → never mutated. If incoming differs from existing, throw a structured `IdentityMutationError`.
     - **Scalar non-identity fields** (`fungi_type`, `fungi_xing`, `status`) → if existing is null/undefined → take incoming; if both present and equal → noop; if both present and differ → return a structured `FieldConflict` (no silent overwrite). The merge function returns `{merged, conflicts: FieldConflict[]}` and the caller decides whether to surface or hard-fail.
     - **Notes**: append-with-dedup. Concrete shape (free-text concatenation with separator vs. a `notes_entries` JSON list) is **deferred to discuss-phase**; SPEC locks only the semantic: duplicate-content notes are not double-appended, and existing notes are never lost.
   - Acceptance: `_mergeAssetFields` is exported and unit-tested with at least one case per rule above (set-union, identity-mutation error, scalar equal noop, scalar conflict, notes dedup).

4. **UPSERT-04 — Etag-guarded PATCH**: Optimistic concurrency on the PATCH path.
   - Current: No PATCH path exists, so no concurrency primitive exists.
   - Target: Every PATCH carries `If-Match: <etag>` where the etag is sourced from `attrs.drupal_internal__revision_id` of the GET that fed the merge. On a 412 Precondition Failed, the upsert retries the GET + merge + PATCH cycle **exactly once** before failing with a structured `ConcurrencyExhausted` error.
   - Acceptance: A test that mocks a 412 on the first PATCH and a 200 on the retry succeeds; a test that mocks 412 on both attempts fails with `ConcurrencyExhausted`. The retry count is one, not unbounded.

5. **UPSERT-05 — Stub-detection contract**: Today's hand-stubbed ancestors are first-class upsert targets.
   - Current: The 4 May-22 ancestor stubs in prod (uuids in `.planning/notes/2026-05-24-prod-write-receipt-uuids.json`) carry the marker string `STUB - awaits 2025-paper-scan backfill` in their `notes` field. No code path knows about this marker.
   - Target: A documented predicate `isStubAsset(asset)` (location to be decided in plan, likely `assets.js`) returns true iff notes contains the structured marker. The upsert layer treats stub assets as **fully mergeable on next encounter** — no special STUB code path at the asset write level. The 2025-scan-backfill author can grep for `isStubAsset` to know where the contract lives.
   - Acceptance: `isStubAsset` exists, is exported, has unit tests for true/false cases, and is referenced from a comment block in `upsertFungiAsset` explaining the contract. No upsert call site has special-case branching on stub-vs-real — they go through the same merge path.

6. **UPSERT-06 — Hermetic ship-gate (property tests)**: The order-independence claim is proved offline.
   - Current: No order-independence tests exist. The hermetic suite tests forward-only happy paths.
   - Target: A new test file (location decided in plan, likely `test/farmos/upsert-property.test.js`) with three property tests:
     - **Order independence**: for a randomized permutation of `{May-22 inoc write, Jan-18 inoc write, Mar-04 inoc write}`, final farmOS state (asset count, parent[] sets, log count) is byte-equivalent to the chronological order. At least 20 randomized permutations exercised per run.
     - **Stub enrichment**: a sequence of `(stub-mint, real-inoc-write)` produces the same final state as `(real-inoc-write only)`. Verified at the asset field level: fungi_type, parent[], qr_codes[] all match the real-only outcome.
     - **Conflict surfacing**: incoming `fungi_type=KOY` against existing `fungi_type=SHI` returns a structured conflict result, **not** a silent overwrite, **not** a thrown unhandled exception.
   - Acceptance: `npm test` (or the per-package equivalent) runs the new test file; all three properties pass; the file is wired into the same suite that today's hermetic ship-gate runs.

7. **UPSERT-07 — Live-fire ship-gate**: One real-farmOS replay attests the layer works end-to-end.
   - Current: Today's May-22 prod write left 4 stubs + 11 children + 11 logs in prod farmOS. Dev farmOS has the parallel set from the 48-LIVE-FIRE run (commit `d3bb6a3`, 16 assets + 11 logs), with the 4 stubs added by hand if not already present.
   - Target: A live-fire script (likely an extension of `scripts/live-fire-48.js` or a sibling) replays the May-22 inoc against **dev** farmOS after Phase 51 lands. Acceptance is asserted by the script itself: `findAssetByName` of each ancestor returns the existing stub UUID (no duplicate POSTs), and each child's `parent[]` resolves exactly to the existing stub UUIDs. Outcome dimensions (created vs. patched vs. noop per asset/log) are captured in the audit log.
   - Acceptance: Live-fire script runs cleanly against dev farmOS; output reports `created=0, patched=≥4 (the stubs enriched), noop=≥11` for the asset writes (exact split depends on what dev state is at run time); zero duplicate UUIDs minted; lineage walks match the May-22 fixture.

## Boundaries

**In scope:**

- `upsertFungiAsset` entry point in `assets.js` and migration of every commit-path caller to it.
- `upsertLog` entry point in `logs.js`, per-type stable-key table, and migration of every commit-path caller.
- `_mergeAssetFields` pure function with set-union / identity-protect / conflict-surface / notes-dedup semantics.
- `isStubAsset` predicate + documented contract.
- Etag-guarded PATCH with one-shot 412 retry.
- Hermetic property tests (order independence, stub enrichment, conflict surfacing).
- Live-fire dev attestation.
- Audit log gets a new dimension capturing upsert outcome (`created` | `patched` | `noop`) — minimum-viable surface; richer telemetry is a follow-on.

**Out of scope:**

- The `asset--group` (`farm_group`) work — composes with this layer but is independently blocked on farmOS enabling the `farm_group` module on dev and prod. Phase 52+ candidate.
- The 2025-paper-scan backfill itself — Phase 51 makes it *safe*; running the actual scan + ingest is a separate phase.
- Observation-of-unknown-asset mint-with-confirm UX wiring — the upsert layer makes it *possible* (the backfill enrich path now exists); the farmer-facing ask-back flow is a separate phase.
- Concurrency beyond optimistic etag retry — no locking, no distributed coordination. The single-writer-per-tenant invariant holds for now.
- Migrating non-`fungi` asset types or non-`seeding` log types to upsert. Other types (activity, harvest, input, observation) keep their current POST-only write path until called for. (Observation log paths in particular have their own farmer-facing semantics still being shaped.)
- Backfilling existing audit-log rows with upsert-outcome dimensions. The new dimension applies to writes from Phase 51 onward.
- Notes-field schema migration (free-text vs. structured `notes_entries`) — semantics are locked here (dedup-and-preserve); the **representation** is a discuss-phase decision.

## Constraints

- Must not break any of the 1032+ hermetic tests currently green. Existing fixtures that rely on POST-only behavior get migrated, not deleted.
- Must not regress the 48-LIVE-FIRE happy path on dev farmOS (16 assets / 11 logs).
- Etag retry budget is exactly 1 — no exponential backoff, no unbounded loops. If 412 storms appear in practice that's a separate ticket.
- `findAssetByName` in-process cache must be invalidated (or refreshed) on every PATCH, to avoid serving stale post-merge state to the same request.
- Conflict-surfacing must be **structured** (a typed result with field name, existing value, incoming value) — never a generic `Error` string. The caller chooses whether to hard-fail or route to a farmer ack.
- All new code paths must be hermetic-testable without a live farmOS. The mock client surface (`test/farmos/mock-client.js`) gets extended; no test reaches the network.

## Acceptance Criteria

- [ ] `grep -nE "createFungiAsset|resolveOrCreateAsset" src/agents/alerter/src/farmos/commits/` returns zero matches in commit code paths (all routed through `upsertFungiAsset`).
- [ ] `grep -nE "logs\.createLog|createLog\(" src/agents/alerter/src/farmos/commits/` shows only `upsertLog` for seeding writes; other log types unchanged.
- [ ] `_mergeAssetFields` is exported from `assets.js` (or a sibling module decided in plan) and has unit-test coverage for: set-union on array refs, identity-mutation throw, scalar equal noop, scalar conflict surface, notes dedup.
- [ ] `isStubAsset(asset)` exists, is exported, and detects the `STUB - awaits 2025-paper-scan backfill` marker; unit-tested true/false.
- [ ] Etag-guarded PATCH: test with mocked 412→200 passes; test with mocked 412→412 throws `ConcurrencyExhausted`.
- [ ] Property test file exists; the three properties (order independence over ≥20 permutations, stub enrichment, conflict surfacing) all pass.
- [ ] Live-fire script runs against dev farmOS post-merge; reports zero duplicate ancestor UUIDs and `patched ≥ 4` for the May-22-style replay.
- [ ] Audit log captures `outcome ∈ {created, patched, noop}` for every asset and log write that goes through the upsert layer.
- [ ] All previously-green hermetic tests (1032+) still pass; the 48-LIVE-FIRE happy path on dev still produces 16 assets + 11 logs.

## Ambiguity Report

| Dimension          | Score | Min  | Status | Notes                                                                 |
|--------------------|-------|------|--------|-----------------------------------------------------------------------|
| Goal Clarity       | 0.92  | 0.75 | ✓      | One-sentence goal, 7 named requirements with current/target/acceptance |
| Boundary Clarity   | 0.85  | 0.70 | ✓      | Explicit in/out lists; asset--group + 2025-scan + observation-UX excluded with reasoning |
| Constraint Clarity | 0.80  | 0.65 | ✓      | Etag retry budget, cache invalidation, structured conflicts, hermetic-testable all locked |
| Acceptance Criteria| 0.85  | 0.70 | ✓      | 9 pass/fail checkboxes including grep assertions and outcome counts    |
| **Ambiguity**      | 0.13  | ≤0.20| ✓      | Notes-representation deferred to discuss-phase (semantics locked, shape open) |

Status: ✓ = met minimum, ⚠ = below minimum (planner treats as assumption)

## Interview Log

| Round | Perspective | Question summary | Decision locked |
|-------|-------------|------------------|-----------------|
| 0 | auto-select | ROADMAP entry already enumerated UPSERT-01..07 with current/target/acceptance; STATE.md confirmed driver and prod state | Skip interview — derive SPEC directly from roadmap + requirements + codebase grep |
| auto | Researcher | What write primitives exist today in `assets.js` / `logs.js`? | `findAssetByName`/`createFungiAsset`/`resolveOrCreateAsset` (find-or-create, no PATCH); `createLog` POST-only |
| auto | Boundary Keeper | What is explicitly OUT of scope? | `asset--group` (separate farmOS-side blocker), 2025-scan ingestion itself, observation-UX wiring, non-fungi/non-seeding migrations, notes representation choice, audit-log backfill |
| auto | Failure Analyst | What does "wrong order silently corrupts state" look like today? | `resolveOrCreateAsset` on a stub returns it unchanged and discards the caller's real fungi_type/parents → the 2025-scan backfill would silently lose the real data |
| auto | Seed Closer | What semantics on notes are locked vs. open? | Locked: dedup-and-preserve, no loss. Open: free-text concat vs. structured `notes_entries` → discuss-phase decides representation |

`[auto]` Phase requirements were already sufficiently clear from ROADMAP.md + STATE.md + codebase grep — generated SPEC.md from existing context without an interactive interview, per spec-phase Step 3 short-circuit.

---

*Phase: 51-order-independent-farmos-writes-upsert-by-stable-identity-se*
*Spec created: 2026-05-24*
*Next step: /gsd-discuss-phase 51 — implementation decisions (notes-field representation, exact module layout for `_mergeAssetFields` and `isStubAsset`, audit-log outcome wiring, property-test seeding strategy)*
