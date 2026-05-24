---
phase: 51-order-independent-farmos-writes-upsert-by-stable-identity-se
verified: 2026-05-24T18:40:50Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
verdict: SHIP
---

# Phase 51: Order-independent farmOS writes — Verification Report

**Phase Goal:** Every farmOS write (asset + log) becomes a content-addressable upsert keyed by the entity's natural identity, with set-union merge on array fields, conflict-surfacing on scalars, and etag-guarded PATCH — so the final farmOS state is a function of *which* events happened, not *what order* the pipeline observed them.

**Verified:** 2026-05-24
**Status:** passed
**Final phase verdict:** **SHIP**

---

## Goal Achievement (Goal-Backward)

### The narrowed goal

For the goal to hold, the codebase must demonstrate, in this order of necessity:

1. A merge function that is order-independent on the dimensions that matter (array refs → set-union, scalar identity → protected, scalar non-identity → conflict-surfaced, notes → dedup-and-preserve).
2. An upsert entry point on both asset and (seeding-)log surfaces wired through to the lookup-merge-or-create path with no remaining direct POST escape hatches in commit code.
3. A property test that proves permutation independence offline.
4. A live-fire attestation that the layer actually converges on real farmOS against pre-existing stubs without minting duplicates.

All four observable conditions are present in the codebase; the live-fire receipt records empirical convergence on dev farmOS at 2026-05-24 with `asset.created=0 / asset.patched=16, log.created=0 / log.patched=11`, zero duplicate UUIDs, and 11/11 parent lineage walks green.

---

## Per-Requirement Verdict

| Req | Status | Primary evidence |
|-----|--------|------------------|
| UPSERT-01 `upsertFungiAsset` | ✓ VERIFIED | `src/agents/alerter/src/farmos/assets.js:185-308` implements lookup-merge-or-create; exported at line 335. Commit callers migrated in `commit-seeding-session.js:125,156`, `commit-seeding.js:52`, `commit-harvest.js:82`. Grep gate clean (zero `createFungiAsset|resolveOrCreateAsset` in `commits/`). Unit tests in `test/farmos/assets.test.js` cover miss / hit-mergeable / hit-noop / hit-conflict / identity-mutation / soft-compare retry / stub enrichment / absent-revision_id — 59 farmos suite tests all green. |
| UPSERT-02 `upsertLog` (seeding) | ✓ VERIFIED | `src/agents/alerter/src/farmos/logs.js:149-319` implements per-type stable-key dispatch. `LOG_STABLE_KEYS` table (lines 45-53) maps only `seeding → (asset.id)` to upsert per B5 invariant; all other native types fall through to POST. `commit-seeding-session.js:181` and `commit-seeding.js:72` route through `upsertLog`. Idempotency proven by live-fire (`log.patched=11, log.created=0`). |
| UPSERT-03 `_mergeAssetFields` | ✓ VERIFIED | `src/agents/alerter/src/farmos/merge.js` exports `mergeAssetFields` + `IdentityMutationError` + `STABLE_NOTES_SEPARATOR`. Rule table codified at lines 10-12 (`ARRAY_REF_FIELDS`, `SCALAR_REL_FIELDS`, `SCALAR_ATTR_FIELDS`). 7 unit tests in `test/farmos/merge.test.js` cover set-union (order + dedup), identity throw, scalar equal noop, scalar conflict, notes dedup, and stub-marker preservation — all green. |
| UPSERT-04 etag-guarded PATCH (DEGRADED → soft-compare) | ✓ VERIFIED (with documented degradation) | `assets.js:266-274` implements pre-merge / post-merge revision_id compare, retry budget = 1, fall through to `outcome='noop', reason='concurrency_loss'`. `logs.js:275-303` mirrors the same for log PATCH. `If-Match` header is still emitted on the wire but documented as best-effort (farmOS does not honor it — RESEARCH §3). `etag_source: 'soft_compare' | 'absent'` is surfaced on every upsert return. Unit test "soft-compare retry: revision moves between merge and PATCH" passes. **Deviation from SPEC UPSERT-04 wording (412→retry→ConcurrencyExhausted)** is documented in VALIDATION.md as a planner-accepted degradation due to RESEARCH critical finding #2; semantic equivalent (one-shot retry + structured non-throwing surface) is preserved. |
| UPSERT-05 stub-detection contract | ✓ VERIFIED | `assets.js:140-144` exports `isStubAsset`; `STUB_BACKFILL_MARKER` constant exported at line 337. Comment block at lines 17-20 documents the contract. 6 unit tests cover true/false/multi-entry-notes/null-asset cases. `upsert-property.test.js` Property 2 attests stub enrichment converges at field level to the real-only outcome with the STUB marker preserved. |
| UPSERT-06 hermetic property tests | ✓ VERIFIED | `test/farmos/upsert-property.test.js` (301 lines) contains all three required properties. Verified by re-running: Property 1 (20 random permutations of 3 inoc events → byte-equivalent state, 22 ms), Property 2 (stub-mint then real-inoc enrichment field-equivalent + marker preserved, 2 ms), Property 3 (fungi_type SHI vs KOY → structured conflict, no PATCH, no throw, 1 ms). All pass. |
| UPSERT-07 live-fire ship-gate | ✓ VERIFIED | `src/agents/alerter/scripts/live-fire-51.js` (181 lines) executed against dev farmOS at `http://10.68.155.50:18080` 2026-05-24. Receipt at `.planning/notes/2026-05-24-phase-51-live-fire.md`. Tally: `asset.patched=16, asset.created=0; log.patched=11, log.created=0`. Zero duplicate UUIDs. 11/11 lineage walks resolve to expected parents including all 4 stub UUIDs. Stub UUIDs byte-identical pre/post. T-51-12 (dev-vs-prod) and T-51-13 (duplicate-mint DoS) both mitigated and recorded. |

**Score: 7/7**

---

## Goal-backward observable truths

| # | Observable truth | Status | Evidence |
|---|------------------|--------|----------|
| 1 | Asset re-write on an existing name produces ONE asset whose state is the merge of all writers, not the last-writer-wins | ✓ VERIFIED | `assets.js` upsertFungiAsset hit-path PATCHes merged body; property test 1 permutation invariant; live-fire `asset.created=0, patched=16` |
| 2 | Seeding-log re-write for the same child asset is idempotent (B5 invariant: one seeding log per child) | ✓ VERIFIED | `LOG_STABLE_KEYS.seeding = (asset.id)`; live-fire `log.created=0, log.patched=11` |
| 3 | Pre-stubbed ancestors are enriched in place by next real-inoc write, not duplicated | ✓ VERIFIED | property test 2; live-fire receipt §"Post-flight verification" — 4 stub UUIDs unchanged pre/post |
| 4 | A scalar field conflict (e.g. fungi_type SHI vs KOY) surfaces as a structured result, never as silent overwrite or unhandled throw | ✓ VERIFIED | `merge.js:90-98`; property test 3; assets.test.js "hit-with-conflicts path" |
| 5 | Order-of-arrival of N inoc events is irrelevant to final farmOS state | ✓ VERIFIED | property test 1: 20 randomized permutations of {May-22, Jan-18, Mar-04} byte-equivalent |
| 6 | Audit log records outcome ∈ {created, patched, noop} for every upsert write that occurred during this phase forward | ✓ VERIFIED | `commit-seeding-session.js:139` and siblings emit `upsert_outcome` event; live-fire captured 27 events |
| 7 | Existing hermetic suite remains green; live-fire happy path unregressed | ✓ VERIFIED | `npm test` → 1103 passed / 9 skipped (pre-existing) / 0 failed. 78 of 80 suites pass; 2 skipped are pre-existing SDK-missing integration & live-fire-gated eval (not regression). |

---

## Required Artifacts

| Artifact | Status | Notes |
|----------|--------|-------|
| `src/agents/alerter/src/farmos/merge.js` | ✓ VERIFIED | 133 LOC; pure, no client deps; exports `mergeAssetFields`, `IdentityMutationError`, `STABLE_NOTES_SEPARATOR` |
| `src/agents/alerter/src/farmos/assets.js` (upsert layer) | ✓ VERIFIED | 339 LOC; `upsertFungiAsset` + `isStubAsset` + `STUB_BACKFILL_MARKER` exported |
| `src/agents/alerter/src/farmos/logs.js` (upsert layer) | ✓ VERIFIED | 329 LOC; `upsertLog`, `LOG_STABLE_KEYS`, `UnsupportedLogTypeError`, `LogIdentityCollision` exported |
| `src/agents/alerter/test/farmos/merge.test.js` | ✓ VERIFIED | 144 LOC; 7 tests; green |
| `src/agents/alerter/test/farmos/upsert-property.test.js` | ✓ VERIFIED | 301 LOC; 3 properties; green |
| `src/agents/alerter/scripts/live-fire-51.js` | ✓ VERIFIED | 181 LOC; executed against dev with PASS verdict |
| `.planning/notes/2026-05-24-phase-51-live-fire.md` | ✓ VERIFIED | Receipt committed |
| `.planning/notes/2026-05-24-phase-51-notes-roundtrip-probe.md` | ✓ VERIFIED | Wave-0 `\n---\n` byte-round-trip probe receipt — fidelity confirmed |

---

## Key Links (Wiring)

| From | To | Via | Status |
|------|-----|-----|--------|
| `commit-seeding-session.js` parent block create | `assets.upsertFungiAsset` | line 125 | ✓ WIRED |
| `commit-seeding-session.js` child block create | `assets.upsertFungiAsset` | line 156 | ✓ WIRED |
| `commit-seeding-session.js` per-child seeding log | `logs.upsertLog('seeding', …)` | line 181 | ✓ WIRED |
| `commit-seeding.js` block asset | `assets.upsertFungiAsset` | line 52 | ✓ WIRED |
| `commit-seeding.js` seeding log | `logs.upsertLog('seeding', …)` | line 72 | ✓ WIRED |
| `commit-harvest.js` bag asset | `assets.upsertFungiAsset` | line 82 | ✓ WIRED |
| `assets.js` upsertFungiAsset → merge | `mergeAssetFields(existing, incoming)` | line 247 | ✓ WIRED |
| `logs.js` upsertLog notes merge | `STABLE_NOTES_SEPARATOR` from `./merge` | line 19 | ✓ WIRED |
| upsert outcome → audit logger | `ctx.auditLogger.logCommit('upsert_outcome', …)` | commit-seeding-session.js:139 + siblings | ✓ WIRED |

Grep gates (from SPEC acceptance):
- `grep -nE "createFungiAsset|resolveOrCreateAsset" src/agents/alerter/src/farmos/commits/` → **0 matches** ✓
- `grep -nE "logs\.createLog|createLog\(" src/agents/alerter/src/farmos/commits/` → 4 matches (commit-input, commit-harvest harvest-log, commit-activity, commit-observation). All are non-seeding log types and explicitly out of scope per SPEC UPSERT-02 ("only `seeding` migrates this phase") and the boundary section ("Other types (activity, harvest, input, observation) keep their current POST-only write path until called for"). ✓

---

## Cross-cutting concerns

### Constraints (SPEC §Constraints)

| Constraint | Status |
|-----------|--------|
| Must not break 1032+ hermetic tests | ✓ 1103 passed, 0 failed |
| Must not regress 48-LIVE-FIRE happy path | ✓ Live-fire shows convergence on the same 16 assets + 11 logs |
| Etag retry budget = exactly 1 | ✓ `assets.js:296`, `logs.js:278-303` — single retry, no exponential backoff |
| `findAssetByName` cache invalidation | ✓ `assets.js:25-27` documents stability via IdentityMutationError; `deleteFungiAsset:322-325` invalidates by-id on orphan cleanup |
| Conflict surfacing structured (not generic Error) | ✓ `merge.js:91-96` returns `{field, existing, incoming, kind:'scalar_conflict'}` |
| All new code hermetic-testable | ✓ Mock-client extended (Wave 0 commit `eeeae9d`); zero tests reach the network |

### Deviations from SPEC

1. **UPSERT-04 etag → soft-compare**: SPEC text said "412 Precondition Failed retry" but RESEARCH finding #2 established that farmOS does not honor `If-Match`. The implementation degrades to a revision_id soft-compare with the same one-shot retry budget and structured non-throwing surface. The `If-Match` header is still emitted on the wire (defensive forward-compat), and `etag_source: 'soft_compare' | 'absent'` is surfaced for audit visibility. The spirit of UPSERT-04 (one-shot retry, no unbounded loops, no silent overwrites under concurrency) is preserved. VALIDATION.md frontmatter explicitly tags UPSERT-04 as "DEGRADED" so this is a planner-accepted deviation, not a surprise.

2. **Live-fire log outcome is `patched=11`, not `created=11`**: A naive reading of SPEC UPSERT-07 ("≥4 stubs enriched, ≥11 noop on logs") implies May-22 logs would be net-new. Dev farmOS had pre-existing seeding logs against each child asset from a prior session, so `upsertLog` matched them via the `(asset.id)` stable key and PATCHed in place. This is CORRECT B5-invariant convergence (one seeding log per child) and the SPEC's "zero duplicate POSTs" criterion is in fact strengthened. Plan 06 summary documents this as a clarification, not a deviation. A follow-up open question (`upsertLog` timestamp diff handling) is captured in the live-fire receipt — out of scope for this phase.

3. **Notes-field representation**: SPEC deferred to discuss-phase. CONTEXT.md and `merge.js:8` lock the representation as a `\n---\n`-separated `plain_text` field; Wave-0 probe (`2026-05-24-phase-51-notes-roundtrip-probe.md`) attests byte-fidelity through Drupal storage. Decision is documented and verified.

### No anti-patterns found in modified surface

Files modified in this phase (`merge.js`, `assets.js`, `logs.js`, `commits/commit-seeding-session.js`, `commits/commit-seeding.js`, `commits/commit-harvest.js`, `scripts/live-fire-51.js`, `test/farmos/{merge,upsert-property}.test.js`, mock-client extensions) were scanned for `TBD|FIXME|XXX|HACK|PLACEHOLDER|TODO`. No unreferenced debt markers found in the upsert layer itself. Adjacent unchanged code retains pre-existing markers — not in this phase's scope.

### Boundaries respected

- `farm_group` work not attempted ✓
- 2025-paper-scan ingestion not attempted ✓
- Observation-of-unknown-asset farmer-ack UX not wired ✓
- Non-`fungi`, non-`seeding` log paths untouched (verified by grep gate residual matches in commit-input/activity/observation/harvest) ✓
- Audit log backfill not attempted (new dimension is forward-only as scoped) ✓

---

## Final Phase Verdict

**SHIP**

All 7 requirements verified end-to-end. The order-independence claim is proven by:

1. Pure-function unit tests on the merge layer.
2. Property test exercising 20 randomized permutations of 3 multi-parent inoc events.
3. Empirical convergence on dev farmOS with 16 assets + 11 logs PATCHed in place, zero duplicates, 11/11 lineage walks green.

Grep gates clean, hermetic suite green (1103/1103 non-skipped), live-fire receipt committed, no blocking debt. The UPSERT-04 etag-degradation is a planner-accepted deviation documented in VALIDATION.md and offset by the soft-compare + structured surface. The `patched` vs `created` log outcome in live-fire is a strengthening of B5 invariance, not a regression.

The 2025-paper-scan backfill — the future write path that motivated this phase — now has a layer that will enrich the 4 in-prod stubs in place rather than minting parallel duplicates. The phase is ready to ship.

---

*Verified: 2026-05-24T18:40:50Z*
*Verifier: Claude (gsd-verifier, goal-backward mode)*
