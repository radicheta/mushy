# Phase 54: Backfill harness + dev-farmOS smoke (≤20 pages) - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning
**Mode:** Auto-discuss — context distilled from ROADMAP requirements (BACK-05..08), today's user direction on smoke sequencing, and Phase 53-04 corpus path correction. No new gray areas.

<domain>
## Phase Boundary

A scripted harness ingests notebook pages from the corrected corpus (`/mnt/slime-kingdom/shared/mushdatadump/jpeg/`), runs them through the normal extraction → confirm → upsert pipeline under a `--bulk-backfill --farmer=santi` mode that short-circuits the explicit-YES gate (CONF-01) for farmer=santi ONLY, and persists every paid-LLM response per-call.

**The phase ships in two cycles, gated by farmer review:**
1. **Cycle 1 (5 pages):** Smoke run on 5 representative pages. Farmer + operator review receipts. **Hard checkpoint** — farmer signs off that the receipt-review workflow is good enough to scale.
2. **Cycle 2 (≤20 pages):** Expand to 20 pages, validated against the same workflow.

Phase 55 (full corpus) only unlocks after Cycle 2 is clean.

**In-scope:**
- **BACK-05** — `scripts/backfill-notebook.js` iterates corpus pages, builds synthetic `signal_capture` rows with `corpus_context={year:2025, source:'paper_log'}` (uses BACK-01 from Phase 53), dispatches through the normal pipeline.
- **BACK-06** — `--bulk-backfill --farmer=santi` mode short-circuits CONF-01 YES requirement for farmer=santi ONLY. Every auto-confirmed draft still emits a farmer-facing summary (audit, not silent write). Mode is hard-gated to `farmer === 'santi'`; never applies to Vikki/Selina/others.
- **BACK-07** — Paid LLM responses persisted to `.planning/backfill/2025-notebook/<run-id>/responses.jsonl` (append-only, per-call unique). Honors memory `[[feedback_persist_paid_results_default]]`.
- **BACK-08** — Cycle 1 (5 pages) + Cycle 2 (20 pages) produce correct stub-enrichment on May-22 ancestors (UUIDs byte-identical pre/post per Phase 51 contract). Zero duplicate assets created.

**Out-of-scope:**
- Phase 55's full corpus run (separate phase).
- Prod farmOS write — dev only this phase (`:18080`); prod gated separately on `FARMOS_INTEGRATION`.
- Backfilling pre-existing children from earlier sessions (separate cleanup).
- Multi-farmer bulk-backfill — explicitly farmer=santi only.

</domain>

<spec_lock>
## Locked Requirements (from ROADMAP.md)

- **BACK-05** — `scripts/backfill-notebook.js` (or sibling) iterates corpus pages, builds synthetic `signal_capture` rows with `corpus_context={year:2025, source:'paper_log'}`, dispatches through the normal pipeline.
- **BACK-06** — Bulk-backfill mode flag short-circuits CONF-01 YES requirement for `farmer=santi` only; every auto-confirmed draft still emits a farmer-facing summary (audit, not just silent write).
- **BACK-07** — Paid LLM responses persisted to `.planning/backfill/2025-notebook/<run-id>/responses.jsonl` (append-only, per-call unique).
- **BACK-08** — Smoke run on 10 representative pages produces correct stub-enrichment on the 4 May-22 ancestors (UUIDs byte-identical pre/post per Phase 51 contract). No duplicate assets created. **Modified per user direction 2026-05-24: smoke runs in two cycles — 5 pages first (Cycle 1, farmer checkpoint), then ≤20 (Cycle 2). Original "10 pages" target absorbed into Cycle 2 lower bound.**

</spec_lock>

<decisions>
## Implementation Decisions

### Corpus path (CORRECTED from ROADMAP's `mushdatadump-prod/`)
- **Actual path:** `/mnt/slime-kingdom/shared/mushdatadump/jpeg/` (95 IMG_3775–IMG_3884 photos).
- ROADMAP referenced `mushdatadump-prod/` which holds Signal capture dumps, NOT notebook scans. Path-rewrite happens in the harness; ROADMAP correction is a follow-up doc commit.
- **Cycle 1 / Cycle 2 fixture range:** restrict to IMG_3775–IMG_3861 (Feb–Dec 2025, transcribed CSV ground truth in `mushroom_log.csv`). Do NOT use IMG_3862–IMG_3884 (Jan–Apr 2026 un-transcribed gap).

### Two-cycle sequencing (per user direction 2026-05-24)
- **Cycle 1 = 5 pages.** Harness runs end-to-end with farmer=santi auto-YES. **Hard checkpoint:** operator + farmer review the receipt artifact (dev-farmOS UUID list + per-page summary). Phase blocks here until farmer signs off.
- **Cycle 2 = 20 pages.** Only after Cycle 1 sign-off. Same workflow, larger N. Validates that the workflow scales without farmer-process friction.
- **Phase 55** (full corpus) cannot start until Cycle 2 is clean.
- This honors memory `[[feedback_smoke_before_expensive_batch]]` — 5-10 items first.

### Bulk-backfill mode
- **CLI:** `node scripts/backfill-notebook.js --bulk-backfill --farmer=santi --cycle=1 --limit=5` (cycle=2 / limit=20 for second pass).
- **Hard gate on `farmer=santi`:** mode aborts loudly if any other farmer name is passed. Per memory `[[feedback_hard_rules_relaxed_when_farmer_is_santi]]` — Vikki/Selina still bound by full no-silent-failure rule.
- **CONF-01 short-circuit:** the harness writes `signal_draft` rows with status pre-flipped to `confirmed_by_farmer` (or whatever the alerter's confirmed state is), bypassing the live confirm-prompt → YES round-trip. Verified by emitting a farmer-facing summary message logged to `.planning/backfill/2025-notebook/<run-id>/summaries.log` (NOT sent over Signal — text artifact for receipt review).

### Paid-LLM persistence (BACK-07)
- **Path:** `.planning/backfill/2025-notebook/<run-id>/responses.jsonl` where `<run-id>` = ISO-8601 UTC timestamp at run-start (`2026-05-24T18-30-00Z` style).
- **Append-only, per-call unique entry:** one JSONL line per LLM call, including request hash, model, response, latency, $cost-estimate.
- **Honors `[[feedback_never_overwrite_paid_live_api_results]]` / `[[feedback_persist_paid_results_default]]`** — no run ever clobbers a prior run.

### Receipt artifact (BACK-08 + farmer-review checkpoint)
- After each cycle, harness writes `.planning/backfill/2025-notebook/<run-id>/receipt.md`:
  - Per-page: source image filename, extracted date, draft count, asset UUIDs created (or reused), seeding-log UUIDs created.
  - Per-page diff vs. CSV ground truth (if fixture exists): hit/miss/extra rows.
  - Aggregate: total assets created, total reused, duplicate-asset count (must be 0).
  - Per-strain summary: N entries per strain, sanity-check against `mossrock_active_strain_codes` memory.
- Receipt is the artifact farmer reviews; not the dev-farmOS UI directly (too noisy for a 5-page review).

### Stub-enrichment check (BACK-08)
- Cycle 1 OR Cycle 2 MUST include at least one page whose entries reference the May-22 ancestor stubs (`260304_SHI_5`, `260118_SHI_23`, `260118_SHI_26`, `260118_KOY_12`, `260425_KOY_4` per STATE.md closeout note). Test: for those ancestor parent refs, the upsert returns the SAME UUID as the stub (no new asset created).
- If no Cycle-1 fixture page mentions those, weight Cycle 2 to include them.
- Phase 51 (upsert-by-stable-identity) is the contract being validated here — its tests cover the unit, this is the integration validation.

### Dev-farmOS write scope
- **Dev only** (`http://10.68.155.50:18080`). Hard prod-guard in the harness: refuse to run if `FARMOS_URL` contains `:8082` or `prod`. Same pattern as Phase 52's `live-fire-52.js`.
- Operator runs the harness; not invoked automatically by autonomous executor.

### Test strategy
- Hermetic unit tests for the harness (mock farmOS + mock LLM) — runs in regular `npx jest`.
- Live-fire = the two cycle runs themselves (operator-executed, not in CI).
- Cycle 1 IS the smoke; Cycle 2 IS the validation. No separate ship-gate beyond farmer sign-off.

### Claude's Discretion
- Exact run-id format if ISO-8601 has filesystem-illegal chars (current proposal already uses `-` instead of `:`).
- Receipt.md exact column layout — planner can iterate.
- Whether to include a `--dry-run` flag that skips farmOS writes entirely (extract + persist only). Recommend yes; cheap.
- Whether to add a `--resume-from <image-id>` flag so a partial run can continue without re-spending LLM tokens. Recommend yes for Cycle 2 (20 pages = real $); skip for Cycle 1.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- BACK-01 from Phase 53 (`signal_capture.corpus_context` JSONB column + pipeline plumbing) — the harness feeds `{year:2025, source:'paper_log'}` through this.
- BACK-02 from Phase 53 (small-N multi-draft routing) — backfill pages routinely emit >5 drafts, so they'll route to batch-review by design. The short-circuit confirms via the bulk-backfill flag, not the per-draft confirm flow.
- BACK-03 from Phase 53 (capture_kind classifier) — every backfill capture gets `capture_kind=paper_log`.
- Phase 51 upsert-by-stable-identity (assumed shipped this milestone) — the harness depends on its UUID stability contract for the May-22-ancestor stub-enrichment check.
- Phase 52 `live-fire-52.js` — pattern to mirror for the prod-guard + dev-only env vars.
- `src/agents/alerter/src/extraction/pipeline.js` — entry point for synthetic captures.
- `src/agents/alerter/src/farmos/commits/commit-router.js` — routes confirmed drafts to per-type commit handlers.

### Established Patterns
- Scripts live in `src/agents/alerter/scripts/` (per `live-fire-52.js`).
- Hermetic tests for scripts under `test/scripts/` if the pattern exists; otherwise alongside as `<script>.test.js`.
- Receipts as markdown + sibling JSONL is the standard (per Phase 51 May-22 receipt at `.planning/notes/2026-05-24-prod-write-receipt.md`).

### Integration Points
- `signal_capture` table: harness writes synthetic rows with `corpus_context` populated.
- `signal_draft` table: harness reads back created drafts, flips status to confirmed.
- Dev farmOS (`:18080`): the harness's write target.

</code_context>

<canonical_refs>
## Canonical References

- `/mnt/slime-kingdom/shared/mushdatadump/HANDOFF.md` — corpus documentation + strain list + page format.
- `/mnt/slime-kingdom/shared/mushdatadump/mushroom_log.csv` — 829-row ground truth for IMG_3775–IMG_3861.
- `/mnt/slime-kingdom/shared/mushdatadump/jpeg/` — image corpus.
- `.planning/phases/53-extraction-prerequisites-year-context-shim-phase-38-batch-mode-fixes/53-CONTEXT.md` — BACK-01..04 contracts the harness depends on.
- `.planning/phases/53-.../53-04-SUMMARY.md` — eval fixture pattern to learn from.
- `src/agents/alerter/test/eval/ingestion/fixtures/notebook-2025/` — example fixture shape.
- `.planning/phases/52-.../scripts/live-fire-52.js` location — prod-guard pattern.
- Phase 51 upsert spec — `.planning/phases/51-*/...` (depend on its UUID-stability contract).
- Memory `[[feedback_smoke_before_expensive_batch]]` — 5-10 items first.
- Memory `[[feedback_persist_paid_results_default]]` — append-only JSONL.
- Memory `[[feedback_hard_rules_relaxed_when_farmer_is_santi]]` — bulk-backfill mode is santi-only.
- Memory `[[feedback_farmer_is_reality_source_of_truth]]` — receipts are for farmer-as-judge, not bot-as-judge.

</canonical_refs>

<specifics>
## Specific Ideas

- Run-id timestamp format: `2026-05-24T18-30-00Z` (colon-free for filesystem safety).
- Cycle-1 page selection (operator/planner's choice, recommend the 8 already-fixtured pages from 53-04 plus rotation of 2 others — that means most of Cycle 1 has CSV ground truth for per-page diff in the receipt).
- May-22 ancestor strain codes to look for in Cycle 2: `260304_SHI_5`, `260118_SHI_23`, `260118_SHI_26`, `260118_KOY_12`, `260425_KOY_4` (per STATE.md closeout). Note: those are 2026 codes from this year's blocks — they wouldn't appear in 2025-notebook pages directly. The check is: do upserts from the 2025-notebook generate parent refs that COLLIDE with those May-22 prod stubs in a meaningful way? Likely they don't (different time period). If so, the BACK-08 stub-enrichment check needs to be re-scoped or marked N/A — the 2025 notebook is OLDER than the stubs and would not enrich them. **Open flag for the planner to resolve.**
- The 95-image corpus is the entire historical backfill — Cycle 2's 20 pages is ~20% of it. Phase 55 picks up the remaining ~75 pages.

</specifics>

<deferred>
## Deferred Ideas

- `--resume-from <image-id>` flag for Cycle 2 — recommend including; defer if planner finds it tricky.
- Multi-farmer bulk-backfill (Vikki, Selina) — never for backfill; their drafts always require explicit YES.
- Re-running over already-backfilled images (idempotent re-runs) — Phase 51's upsert handles this; nothing to add here.
- Prod-farmOS writes — separate decision; Phase 55 might enable per-session-class.
- ROADMAP path correction (`mushdatadump-prod/` → `mushdatadump/jpeg/`) — small doc-commit after this phase ships.

</deferred>
