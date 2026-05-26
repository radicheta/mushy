# Phase 55: full-corpus-run-receipt - Context

**Gathered:** 2026-05-25
**Status:** Ready for planning
**Mode:** Autonomous discuss (two gray areas put to Santi 2026-05-25; see Decisions). Live execution deliberately OUT of autonomous scope per [[project_v111_autonomous_run_scope]] -- this phase is planned, not run.

<domain>
## Phase Boundary

Run the FULL 2025 notebook corpus (the `mushdatadump` pages) through the Phase 54
extraction -> strain-confirm -> commit harness into **dev** farmOS, produce a receipt of
every asset/log created or patched, compute per-shape confirm-accuracy stats, and document a
prod-promotion decision (default dev-only).

This is the capstone of v1.11. It builds directly on:
- Phase 54 backfill harness (`scripts/backfill-notebook.js`, `build-backfill-receipt.js`,
  responses.jsonl observer, Cycle-1/2 RUNBOOKs).
- Phase 54.1 strain-confirm-before-mint gate (unknown strains held as `needs_review`, batched
  confirm, no blind mint).

### In scope
- Extend the harness from the Cycle ceiling (<=20 pages) to the **full corpus** run (BACK-09).
- Receipt generation: every asset/log created or patched, plus a JSONL of UUIDs, at
  `.planning/notes/2026-XX-XX-2025-notebook-backfill-receipt.md` + sibling `.jsonl` (BACK-09).
- Per-shape confirm-accuracy stats computed from the run: `n_per_shape` and YES rate,
  **tagged as bulk-backfill auto-YES** so v1.13 does NOT mistake them for human-YES signal
  (BACK-10).
- A prod-promotion decision doc: default dev-only; prod write only if the operator opts in
  per-session-class (BACK-11).
- An operator RUNBOOK whose pre-flight bakes in the prod-leak mitigation (see Decisions GA1).

### Out of scope (deferred / not this phase / not autonomous)
- **The live full-corpus run itself.** It is operator-triggered and gated on Cycle-2 farmer
  sign-off (see GA2). Autonomous mode plans this phase but MUST NOT execute the live backfill
  ([[project_v111_autonomous_run_scope]]).
- Any code change to the live alerter commit-watchdog (GA1 chose operational isolation, not an
  origin-guard). The watchdog stays as-is.
- The 4 bogus dev-farmOS terms cleanup (needs farmOS admin DELETE; carried from Phase 54.1
  deferred).
- v1.13 narrowing work (consumes BACK-10 output; separate milestone).
</domain>

<decisions>
## Implementation Decisions (with Santi 2026-05-25)

### GA1 -- Prod-leak race mitigation: OPERATIONAL ISOLATION ONLY (no code)
The hazard ([[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]]): the live
`mushy-alerter-1` commit-watchdog polls the SHARED timescale for `status='confirmed'` drafts
every 30s and commits them to **PROD** farmOS (:8082). Flipping backfill drafts to confirmed
in that DB leaks 2025 data to prod, defeating the harness's own dev-only guard.

**Decision:** Do NOT add a commit-watchdog origin-guard. Mitigate operationally, enforced as a
HARD runbook pre-flight:
- Run the backfill against an **isolated throwaway postgres** (fresh `DATABASE_URL`; harness
  `initDb` self-creates schema; the prod-pointing watchdog never sees the backfill drafts), OR
- **Stop `mushy-alerter-1`** for the run window, run backfill (harness commits to dev :18080),
  restart. Cost: minutes of no prod RH alerting -- needs an explicit OK because the alerter is
  the farmer safety net ([[feedback_no_silent_failure_after_farmer_confirm]]).
- The RUNBOOK pre-flight MUST replace the falsified Phase-54 assumption ("DATABASE_URL points at
  the alerter dev DB, NOT prod" -- there is no separate dev DB; it's shared and the alerter on
  it writes to prod). The new pre-flight verifies isolation explicitly, not by trusting the env.

Rationale for no code: keeps the live alerter untouched; the recurring-fix origin-guard was
considered and deferred -- not worth a live-path change for an operator-gated run.

### GA2 -- Scope vs Cycle-1/2: 55 = FULL RUN, GATED ON CYCLE-2 SIGN-OFF
Phase 55 plans ONLY the full-corpus run + receipt + per-shape stats + promotion decision.
The live run is explicitly gated on Phase 54 Cycle-1 and Cycle-2 dev smokes completing with
**farmer sign-off** (the operator-triggered ramp; [[project_v111_backfill_harness_shape]]).
Phase 55 does NOT re-own or re-plan the 54-05/06 cycle runbooks; it documents the gate and
picks up after Cycle-2 is signed off.

### Claude's Discretion
- Exact mechanism for the full-corpus page range (drop the IMG_3775..IMG_3861 / <=20-page cap;
  parameterize "all pages" vs an explicit max).
- Receipt + stats file layout and how per-shape buckets are defined (reuse
  `build-backfill-receipt.js` aggregation where possible).
- RUNBOOK structure (extend the Cycle-2 runbook vs a fresh full-corpus runbook).
- How the bulk-backfill auto-YES tagging is represented in the BACK-10 stats output.
</decisions>

<code_context>
## Existing Code Insights

- `scripts/backfill-notebook.js` -- the harness CLI; prod-guard (refuses ':8082'/'prod'),
  santi-only gate, page-range filter, `createBackfillContext()` bootstrap, auto-confirm
  short-circuit (`flipDraftToConfirmed`, `bulk_backfill_santi`), responses.jsonl observer.
  Phase 54.1 added the strain-confirm gate so unknown strains hold as `needs_review`.
- `scripts/build-backfill-receipt.js` -- parseCsv, computeCsvDiff (case-insensitive strain
  match), renderPageSection, computeAggregate (incl. Phase 51 intra-cycle upsert-stability
  check), buildReceipt called from main() finally{} (crash-resilient).
- `scripts/backfill-confirm-strains.js` (Phase 54.1) -- follow-up pass that mints confirmed-new
  terms + remaps corrections + commits held drafts after the batched farmer reply.
- Corpus: notebook pages under the mushdatadump corpus; ground-truth CSV is page-grain (829
  rows / 73 JPEGs) -- per-event ground truth needs OCR (out of scope; reduced eval shape).
- `.planning/backfill/` is gitignored (per-run JSONLs never committed).
</code_context>

<specifics>
## Specific Ideas

- BACK-10 stats are explicitly NOT v1.13 signal: auto-YES under `--bulk-backfill --farmer=santi`
  is not human confirmation. Tag every per-shape bucket so the v1.13 narrowing reads them as
  bulk-backfill receipts, never as human-YES rate.
- Default prod-promotion = dev-only. Prod write is opt-in per session-class, documented in
  BACK-11, never autonomous.
- The full-corpus run is paid-LLM (Anthropic) -- smoke a small N before the full batch
  ([[feedback_smoke_before_expensive_batch]]); persist every paid call append-only
  ([[feedback_persist_paid_results_default]]).
- mushdatadump pages carry no year on the page; the Phase 53 corpus_context shim supplies 2025
  ([[project_mushdatadump_is_2025_notebook]]).
</specifics>

<deferred>
## Deferred Ideas

- Commit-watchdog origin-guard (the recurring coexistence fix) -- considered, NOT chosen for
  v1.11; revisit if operational isolation proves too heavy across many runs.
- 4 bogus dev-farmOS fungi_type terms (LIM/SHIITAKE/OYS/CAR) -- need farmOS admin DELETE
  (bot gets 403); carried from Phase 54.1.
- v1.13 narrowing -- consumes BACK-10 output; separate milestone.
</deferred>

---

*Phase: 55-full-corpus-run-receipt*
*Context synthesized 2026-05-25; live execution intentionally excluded from this autonomous run.*
