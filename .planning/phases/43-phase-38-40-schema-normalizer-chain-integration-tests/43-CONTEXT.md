# Phase 43: Phase 38<->40 Schema Normalizer + Chain Integration Tests - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Eliminate the extractor<->commit shape mismatch responsible for the 2026-05-15 lion's-mane `commit_failed` regression by:

1. Inserting a router-side normalizer (`src/agents/alerter/src/farmos/commits/normalize.js`) that translates extractor-shape -> commit-shape per `log_type`, called from `commit-router.commit(...)` before the DISPATCH lookup. Idempotent: commit-shape input passes through unchanged. (Audit Option A.)
2. Adding 5 chain integration tests under `src/agents/alerter/test/farmos/integration/extractor-to-commit.test.js` covering all 5 log_types (seeding, activity, observation, input, harvest). Test 2 (activity-relocate via the real 2026-05-15 lion's-mane transcript) is the named regression guard. Tests run by default under `npm test` -- no `FARMOS_INTEGRATION=1` gate. (Audit Option C.)

**Out of scope** (per audit + discussion):
- Reshaping Phase 38 extractor schemas (Option B rejected: collides with farmer-facing askback preview, blows up Phase 38 eval corpus, conflates farmer-input shape with farmOS-write shape).
- Multi-bag harvest model (extractor's `qty_g` single-number vs commit's `bags[]` -- filed as v1.8 candidate).
- Structured farmOS-side `recipe_lot` field (defer to coordination with farmOS schema team).
- Seeding lineage bridge (`batch_name` <-> `parent_batch_name` stays distinct until farmOS pasteurization log lands).

</domain>

<decisions>
## Implementation Decisions

### Normalizer shape contract (Option A)

- **D-01:** `normalize.js` is a pure function `(draft) -> draft'` that returns a NEW draft with `draft_json` reshaped to commit-shape. Idempotent: if `draft_json` already has commit-shape markers (`qr_codes`, `timestamp`, `activity_subtype`, etc.), pass through unchanged. This satisfies SCHEMA-03.
- **D-02:** Wired in `commit-router.js` as `fn(client, require('./normalize').normalize(draft), ctx)` -- a one-line edit at the dispatch site. Original `signal_draft.draft_json` in the DB is NOT mutated; the audit-trail extractor-shape farmers see in askback previews is preserved. The normalized shape lives only inside the commit dispatch frame.
- **D-03:** Common transforms (apply across all `log_type`s before the switch): `event_timestamp` (ISO string) -> `timestamp` (unix seconds, floor); `asset_ref` (string, filter `<UNKNOWN>` sentinel) -> `qr_codes` (string[]).
- **D-04:** Per-log_type transforms follow the audit's `normalize()` sketch verbatim except as amended by D-05 and D-09 below.

### Q1: harvest `source_block_refs` resolution

- **D-05:** Normalizer renames `source_block_refs` (string[]) -> `source_qr_codes` (string[]) verbatim. No regex gate, no filtering. The B5 strain-id regex (`/^[0-9]{6}_[A-Z]{2,4}_[0-9]+$/`) is NOT used at the normalizer layer.
- **D-06:** Extend `src/agents/alerter/src/farmos/qr.js` `resolveQr(client, qrCode)` with an id_tag-first, name-on-miss fallback. New flow: try `filter[id_tag.id][value]=<qrCode>` (existing path) -> if `data: []`, retry against `filter[name][value]=<qrCode>` -> return `{found, assetId, path: 'id_tag'|'name'}`. The returned `path` indicates which lookup matched (useful for debug logs and a future telemetry counter).
- **D-07:** `<UNKNOWN>` sentinel is filtered upstream by D-03 (normalizer common transform), so by-name fallback never receives it.
- **D-08:** Name collisions are a farmer-side discipline risk, not a structural concern for v1.7. If two fungi assets share a `name`, the first JSON:API result wins; this matches today's id_tag behavior. Document the risk inline in qr.js; no programmatic dedup in Phase 43.

### Q3: input `recipe_lot` landing

- **D-09:** Normalizer prepends `recipe_lot: <value>\n` to `draft_json.notes` BEFORE commit-input runs its existing ingredients-into-notes serializer (`commit-input.js:24-25`). Final notes order: `recipe_lot: RB-2026-05\n\nIngredients:\n- oat 1kg\n- gypsum 50g`. No farmOS schema change required.
- **D-10:** Phase 38 keeps `recipe_lot` as a required field on the input log Zod schema (`schemas/input.js:11`). No extractor-side change.

### Q2 (auto-default, audit recommendation)

- **D-11:** `seeding.batch_name` (sterilization batch, pre-inoc, not yet a farmOS asset) and `seeding.parent_batch_name` (lineage parent, farmOS fungi asset) stay distinct. Normalizer does NOT fold them. Defer the bridge until the farmOS pasteurization log lands (post-v1.7).

### Q4 (auto-default, audit recommendation)

- **D-12:** Harvest `qty_g` (single number) -> `bags: [{weight_grams: qty_g}]` (single synthesized unnamed bag) when `qty_g` is present and `bags` is absent. If `qty_g` is absent, leave `bags` undefined. The real multi-bag model (extractor-side schema extension OR farmer UX change to bag-shaped reports) is filed as a v1.8 candidate. Test 5 documents this gap inline.

### Chain integration tests (Option C)

- **D-13:** Test file location: `src/agents/alerter/test/farmos/integration/extractor-to-commit.test.js`. Suite runs under `npm test` by default; no environment gate. Each test follows the audit's three-phase pattern: extract -> normalize -> commit, asserting shape at each boundary AND `commit_success` at the end.
- **D-14:** LLM side: mocked Anthropic responder using existing helpers in `test/extraction/helpers/`. No paid API calls; no Phase 38 eval-corpus dependency.
- **D-15:** farmOS side: existing `test/farmos/mock-client.js`. No prod-farmOS dependency.
- **D-16:** **Test 2 (activity-relocate, the 2026-05-15 regression guard) MUST use the real 2026-05-15 lion's-mane transcript** -- the actual messages captured during the Vikki/Rambo unscripted run, not a paraphrase. Curated fixtures alone do NOT satisfy SCHEMA-02 ([[feedback_real_data_before_ship_gate_pass]] applies). Locate the transcript in the prod corpus before planning.
- **D-17:** Test assertion structure per test: (a) post-extract shape (extractor-shape markers present), (b) post-normalize shape (commit-shape markers present), (c) `commit_success: true` and verify the specific commit-side side-effect (correct asset relationship, correct id_tag binding, correct notes content, etc.). Failure messages must name which boundary failed.
- **D-18:** Idempotency test for SCHEMA-03 lives in `test/farmos/normalize.test.js` (unit, NOT the integration suite). It feeds a hand-constructed commit-shape `draft_json` directly to `normalize()` and asserts byte-identical output. Keep the integration tests focused on the real chain; don't conflate with unit-shape assertions.

### Claude's Discretion

- `normalize.js` internal organization (one switch statement vs per-log_type helper functions). Audit's switch sketch is fine; planner picks final style.
- Telemetry/logging on resolve-by-name path hits (D-06). Not in v1.7 scope unless trivially cheap.
- Unit-test file location for `normalize.js` itself: `test/farmos/normalize.test.js` (parallel to existing commit-*.test.js files) unless planner finds a better local pattern.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 43 audit + decision (read FIRST)
- `.planning/notes/2026-05-16-schema-audit.md` -- the full audit; §1 per-log_type matrix, §3 Option A normalizer sketch + 4 open questions (Q1+Q3 settled in this CONTEXT.md; Q2+Q4 audit-default deferred), §A1-A10 code-reference appendix.
- `.planning/ROADMAP.md` §"Phase 43" -- requirements SCHEMA-01..04 + the 4 open questions verbatim.
- `.planning/milestones/v1.7-findings/2026-05-15-vikki-rambo-unscripted-run.md` if present, else `[[project_2026_05_15_vikki_rambo_unscripted_run]]` memory -- origin of the lion's-mane `commit_failed` regression that Test 2 guards against.
- `.planning/notes/2026-05-14-reply-from-farmos-fungi-schema.md` -- farmOS-side schema lock; relevant for D-11 (seeding lineage deferred until pasteurization log).

### Files this phase will modify
- `src/agents/alerter/src/farmos/commits/commit-router.js:36` -- one-line wire-in for normalize().
- `src/agents/alerter/src/farmos/qr.js` -- add name-on-miss fallback to `resolveQr` (D-06).

### Files this phase will create
- `src/agents/alerter/src/farmos/commits/normalize.js` -- the normalizer.
- `src/agents/alerter/test/farmos/normalize.test.js` -- unit tests, incl. SCHEMA-03 idempotency.
- `src/agents/alerter/test/farmos/integration/extractor-to-commit.test.js` -- 5-test chain suite.

### Existing patterns to preserve
- `src/agents/alerter/src/farmos/commits/commit-input.js:14-28` -- ingredients-into-notes serializer; normalizer's `recipe_lot:` prepend (D-09) chains in front of this.
- `src/agents/alerter/test/farmos/mock-client.js` -- mock farmOS client used by every commit-* test today.
- `src/agents/alerter/test/extraction/helpers/` -- mocked Anthropic responder helpers for extractor-side test inputs.

### Phase 38 / Phase 40 shipped artifacts (referenced, not modified)
- `src/agents/alerter/src/extraction/schemas/{activity,observation,input,harvest,seeding}.js` -- extractor Zod schemas (frozen).
- `src/agents/alerter/src/extraction/state-machine.js:26` -- required-field map.
- `src/agents/alerter/src/extraction/preview-builder.js` -- farmer-facing askback preview (uses extractor-shape; do NOT change).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `commit-input.js:24-25` notes-serializer pattern: `(dj.notes ? dj.notes + '\n' : '') + (lines ? 'Ingredients:\n' + lines : '')`. D-09 (recipe_lot prepend) chains before this. Same idiom -- no new abstraction needed.
- `qr.js:22-35` resolveQr return shape `{found, assetId, path, error?}`. D-06 extends `path` enum from just `'id_tag'` to `'id_tag' | 'name'`.
- `test/farmos/mock-client.js` -- existing mock with seeded assets; chain tests reuse without modification.

### Established Patterns
- `commit-router.js` does pre-dispatch validation already; normalizer is a sibling pre-dispatch step (D-02). No new routing abstraction.
- All `commit-*.js` modules read `draft.draft_json.<field>` directly. Normalizer producing a new draft with mutated `draft_json` is the smallest possible blast radius (audit §3.A).
- Existing commit-*.test.js suites under `test/farmos/` all run by default; the existing integration suite (`test/farmos/integration/` if present, else create) follows the same default-run discipline. SCHEMA-04 codifies this.

### Integration Points
- `commit-router.commit(...)` is the single dispatch entry. Adding normalize() there means every existing test path (curated commit-shape fixtures included) goes through the idempotent pass-through, so SCHEMA-03 regression-tests itself via the existing suite.
- `signal_draft.draft_json` in the SQLite buffer is NOT touched (extractor-shape preserved for audit). The normalized draft is local-only inside the commit frame -- preview-builder.js sees unchanged data.

</code_context>

<specifics>
## Specific Ideas

- **Test 2 transcript provenance** (D-16): the real 2026-05-15 lion's-mane messages must be located in `mushdatadump-prod/` (or wherever the Vikki/Rambo unscripted run was persisted). Planner: include a "locate transcript" task BEFORE the test-write task; if not found, escalate to Don Santiago before scaffolding fake data.
- Audit's exact `normalize()` switch (lines 384-451 of `.planning/notes/2026-05-16-schema-audit.md`) is the starting point. Plan from it; deviate only on identified issues.
- Sizing baseline from audit: ~150-200 LOC normalize.js + 1-line router edit + 10 unit tests + 5 chain tests (~60 LOC each) + small helpers. Half-day Option A + half-day Option C, bundled = ~1d total per audit §3.

</specifics>

<deferred>
## Deferred Ideas

- **Multi-bag harvest model (Q4)** -- v1.8 candidate. Extractor schema extension OR farmer UX change to bag-shaped reports. Phase 43 Test 5 documents the gap inline.
- **Structured farmOS-side `recipe_lot` field (Q3 alt)** -- requires coordination with farmOS schema team. Revisit after the next farmOS schema cadence.
- **Seeding lineage bridge (Q2)** -- bridge `batch_name` -> `parent_batch_name` only after farmOS pasteurization log lands. Currently distinct; do not fold.
- **Telemetry counter on resolve-by-name fallback hits (D-06)** -- nice-to-have observability; not in v1.7 scope.
- **Audit follow-on D** (declared `extractorShape -> commitShape` JSON Schema artifact) -- useful for Phase 41+42 ingestion harness work; not Phase 43.
- **Resolve-by-name dedup** when multiple fungi assets share a `name` (D-08) -- farmer-side discipline today; revisit if collisions actually occur.

</deferred>

---

*Phase: 43-phase-38-40-schema-normalizer-chain-integration-tests*
*Context gathered: 2026-05-16*
