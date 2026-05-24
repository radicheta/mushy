# Phase 53: Extraction prerequisites — year-context shim + Phase 38 batch-mode fixes - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning
**Mode:** Auto-discuss — context distilled from ROADMAP requirements (BACK-01..04) + two pending todos that this phase explicitly closes. No new gray areas.

<domain>
## Phase Boundary

Close the three known extraction bugs that would corrupt a 2025-notebook backfill BEFORE any batch run touches farmOS. This is a hard prereq for Phase 54 (smoke harness) and Phase 55 (full corpus).

**In-scope:**
- **BACK-01 — year-context shim.** Wire `corpus_context.default_year` end-to-end so a fixture/job can pin `year=2025` and stop the extractor from hallucinating years on undated 2025 notebook pages. Schema-side: `signal_capture.corpus_context` column (JSONB or text), or job-arg passthrough — whichever requires less moving parts.
- **BACK-02 — small multi-draft routing fix.** At the routing seam between Phase 38 extraction emit and Phase 39 confirm dispatch: `drafts.length > 5 OR min(per-draft confidence) < 0.7` → batch-review queue (current behavior). Otherwise → normal per-draft confirm flow. Closes `2026-05-24-phase38-batch-mode-misroutes-small-multi-draft-captures.md` (DT tubs case, capture `01KSCW771VB2FDWBPWNS4MEHAZ`).
- **BACK-03 — photo-vs-paper-log classifier.** Add `capture_kind: 'paper_log' | 'physical_object_photo' | 'voice_note' | 'text'` to the extraction envelope so downstream routing can distinguish. Closes `2026-05-24-phase38-photo-vs-paper-log-classifier-too-eager.md`. Implementation = **extractor prompt enhancement** (Option 1 from todo), not vision-pre-classifier (Option 2). Cheaper, lower latency, accepted cognitive-load tradeoff.
- **BACK-04 — hermetic eval gate.** 5-10 hand-labeled 2025 notebook pages in `test/eval/ingestion/fixtures/sessions/` (or sibling `pages/` subdir). Eval suite PASSES against the fixed extractor. Phase 54 cannot kick off until this is green.

**Out-of-scope:**
- Vision-only pre-classifier (Option 2 in BACK-03 todo) — deferred unless prompt-only approach proves insufficient.
- Recovering the 2 stuck DT-tub drafts (`bb34475403…`, `ccd52457c2…`) — recoverable post-fix via re-route, but separate one-off operator action.
- Any actual backfill run — Phase 54.
- Trinity-skip operator-channel fix — already hotfixed (separate todo).

</domain>

<decisions>
## Implementation Decisions

### BACK-01 — year-context wiring
- **Schema change:** add `corpus_context` column (JSONB) to `signal_capture`. Nullable. Default null. Migration file in alerter's standard migration dir.
- **Wiring path:** `signal_capture.corpus_context` → `pipeline.js` extracts and passes to `extractor.js` (which already accepts `corpusContext` per the existing system-prompt scaffolding, see `prompts/system.js:117,134,174,239,335`). So this is plumbing, not new behavior in the extractor itself.
- **For Phase 54's harness:** the bulk-backfill script will set `corpus_context = {default_year: 2025, source: 'paper_log'}` on every synthetic capture row.
- **No farmer-facing surface for now** — backfill-only context. Live captures never set it.

### BACK-02 — routing heuristic
- **Location:** routing seam at `src/agents/alerter/src/extraction/pipeline.js:143` (Plan 08 batch-mode entry). NOT in the extractor — extraction stays pure; routing is policy.
- **Heuristic:** `drafts.length > 5 OR min(per-draft confidence) < 0.7` → batch-review queue. Otherwise → normal per-draft confirm flow.
- **Confidence field:** use the existing per-draft `confidence.state` (or whichever per-draft scalar already exists; if multiple, take the min). If no per-draft scalar exists, take a min over all confidence sub-fields.
- **Regression fixture:** `01KSCW771VB2FDWBPWNS4MEHAZ` (DT tubs) goes into eval fixtures; expected outcome = 2 separate `confirm_prompt`s, no operator-channel ping.
- **Counter-fixture:** keep one existing true-paper-log capture in eval to assert it STILL routes to batch-review.

### BACK-03 — capture_kind classifier
- **Approach:** Option 1 (extractor prompt enhancement) — add few-shot pairs distinguishing paper-log photo from physical-object photo; output a `capture_kind` field on the extraction envelope.
- **Allowed values:** `'paper_log' | 'physical_object_photo' | 'voice_note' | 'text'` (extensible later).
- **Default behavior:** if extractor omits the field, treat as `null` and DO NOT use as a routing input (back-compat). Routing fix (BACK-02) is the load-bearing piece; classifier is supportive metadata for analytics + future routing refinements.
- **No schema change required immediately** — capture_kind rides in the extraction envelope JSON. Persist in `signal_draft.extraction_envelope` if it's already JSONB; no new column.

### BACK-04 — hermetic eval gate
- **Corpus:** 5-10 hand-labeled pages drawn from `/mnt/mossrock/shared/mushdatadump-prod/` (see memory `[[project_phase38_production_logs_available]]`).
- **Labels:** per-page expected extraction JSON (drafts[], confidence, capture_kind). Hand-curated by Santi or radicheta-claude.
- **Fixture location:** `test/eval/ingestion/fixtures/notebook-2025/` (new subdir).
- **Test runner:** extend existing eval suite under `test/eval/ingestion/` (mirrors current pattern; do NOT spin up a new harness).
- **Pass criteria:** all per-page extraction JSONs match expected labels (exact match on `asset_ref`, `event_kind`, `qty` where applicable; tolerance on free-text fields).
- **CI gate:** this suite must PASS in `npx jest` before Phase 54 starts. If too expensive to run in CI (paid LLM), mark as `it.skip` by default but include a `test:eval` npm script that runs it on demand.

### Test strategy
- Unit tests for routing-heuristic in `pipeline.test.js`.
- Unit test for `corpus_context` plumbing (signal_capture → extractor input).
- Hermetic eval gate (BACK-04) as the ship-gate.
- **No live-fire on dev farmOS** in this phase — extraction-only changes; no farmOS write path touched.

### Claude's Discretion
- Migration framework specifics (whether alerter uses node-pg-migrate, knex, raw SQL — confirm in plan-phase).
- Exact few-shot pairs in the classifier prompt — let the planner draft, then refine if the eval gate misses.
- Whether to add a small operator-facing summary noting "N captures classified as physical_object_photo today" — defer unless trivially cheap.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/agents/alerter/src/extraction/prompts/system.js` — already has `corpus_context.default_year` scaffolding (lines 117, 134, 174, 239, 335). BACK-01 is plumbing the value through, not adding new prompt behavior. BACK-03 extends the same prompt with `capture_kind` few-shots.
- `src/agents/alerter/src/extraction/extractor.js:67` — already JSON-serializes `corpusContext` into the model input. Wiring just needs to pass non-null values.
- `src/agents/alerter/src/extraction/pipeline.js:143` — Plan 08 batch-mode entry point; BACK-02 routing heuristic lives here.
- `src/agents/alerter/src/extraction/outbound.js:92-114` — confirm_prompt dispatch; needs to handle the "now N per-draft prompts instead of suppressed" case post-BACK-02.
- `test/eval/ingestion/` — existing eval suite; BACK-04 extends it, doesn't replace.

### Established Patterns
- Migrations live alongside other alerter migrations (find the dir during planning — likely `src/agents/alerter/migrations/` or similar).
- Eval fixtures: per-fixture JSON under `test/eval/ingestion/fixtures/`.
- Extraction envelope is a single JSON object stored in `signal_draft.extraction_envelope`.

### Integration Points
- `signal_capture` table: BACK-01 adds `corpus_context` column.
- Phase 39 confirm-flow consumes per-draft `confirm_prompt`s — BACK-02 changes how many are dispatched per capture but not the shape.
- `signal_draft` table: BACK-03 capture_kind lives inside the existing envelope JSON; no schema change.

</code_context>

<canonical_refs>
## Canonical References

- `.planning/todos/pending/2026-05-24-phase38-batch-mode-misroutes-small-multi-draft-captures.md` — **BACK-02 source-of-truth.**
- `.planning/todos/pending/2026-05-24-phase38-photo-vs-paper-log-classifier-too-eager.md` — **BACK-03 source-of-truth.**
- `.planning/todos/pending/2026-05-24-observation-of-unknown-asset-should-backfill-not-fail.md` — related (Phase 55b TBD); not in scope here.
- `src/agents/alerter/src/extraction/pipeline.js:143` — BACK-02 routing seam.
- `src/agents/alerter/src/extraction/prompts/system.js` — BACK-01 corpus_context scaffolding + BACK-03 classifier few-shots.
- `src/agents/alerter/src/extraction/extractor.js:67` — corpus_context serialization point.
- Memory `[[project_phase38_production_logs_available]]` — `/mnt/mossrock/shared/mushdatadump-prod/` corpus location.
- Memory `[[project_mushdatadump_is_2025_notebook]]` — extractor hallucinates years; this phase fixes the structural cause.
- Memory `[[reference_mushdatadump_benchmark]]` — v1.6 multimodal eval set; pattern to follow for BACK-04.
- Memory `[[feedback_smoke_before_expensive_batch]]` — 5-10 items first; informs BACK-04 corpus size.
- Memory `[[feedback_persist_paid_results_default]]` — eval fixture extraction outputs go in append-only JSONL if a paid LLM is used.

</canonical_refs>

<specifics>
## Specific Ideas

- DT tubs capture `01KSCW771VB2FDWBPWNS4MEHAZ` is the named regression guard for BACK-02. Expected outcome post-fix: 2 separate `confirm_prompt`s to farmer, no operator-channel ping.
- True paper-log fixture (e.g. May-22 paper-log photo at `mushdatadump-prod/2026-05-12_inoc_santi/XAbzzUidkLR3irhVmjea.jpg`) must continue routing to batch-review.
- The 2 stuck drafts (`bb34475403…`, `ccd52457c2…`) can be re-routed post-fix as a one-off cleanup; not part of this phase.
- Stretch goal (deferred unless trivial): emit `capture_kind` in confirm_prompt audit lines so farmer-facing messages can later differentiate without changing schema.

</specifics>

<deferred>
## Deferred Ideas

- Vision-only pre-classifier (Option 2 in BACK-03 todo) — only revisit if the prompt-only classifier underperforms in the BACK-04 eval gate.
- Per-capture-kind farmer-facing message differentiation — wait for explicit farmer ask.
- Recovery of pre-existing stuck `needs_review` drafts at scale — one-off operator script, separate from this phase.
- Observation-of-unknown-asset backfill path (`2026-05-24-observation-of-unknown-asset-should-backfill-not-fail.md`) — Phase 55b candidate.

</deferred>
