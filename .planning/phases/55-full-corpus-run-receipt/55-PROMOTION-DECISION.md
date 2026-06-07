# BACK-11: Prod-Promotion Decision -- 2025 Notebook Backfill

**Record type:** Decision artifact (static markdown)
**Requirement:** BACK-11
**Date:** 2026-06-07
**Status:** ACTIVE -- governs all Phase 55 promotion choices

---

## Decision

**The 2025-notebook backfill is DEV-ONLY by default.**

No autonomous prod write. Any write to PROD farmOS (:8082) requires an explicit operator
opt-in, constrained to a specific session-class, and gated on a clean dev receipt for that
class. This is the BACK-11 record.

---

## Rationale

**Why dev-only by default:**

1. **Dev as the validation target.** The full-corpus run lands in dev farmOS (:18080). Dev
   is a rebuild-from-scratch-acceptable environment; receipts from dev validate extraction
   quality and upsert stability before anything touches prod.

2. **Prod already carries live data.** Prod farmOS (:8082) holds live captures from ongoing
   farming activity plus the May-22 stubs written in the 2026-05-24 prod write receipt. Any
   backfill write must enrich those stubs in-place (via the Phase 51 upsert layer), not mint
   duplicates.

3. **Prod-leak hazard.** Per the GA1 decision (55-CONTEXT.md), the live `mushy-alerter-1`
   commit-watchdog polls the shared TimescaleDB (:5432) for `status='confirmed'` drafts every
   30s and commits them to PROD. Any backfill run that points `DATABASE_URL` at that shared DB
   leaks confirmed drafts to prod without the operator explicitly authorizing it. The GA1
   isolation pre-flight in 55-FULL-CORPUS-RUNBOOK.md mitigates this for dev runs; a prod run
   carries the same hazard and requires the same pre-flight.

4. **No autonomous path.** Per the GA2 gate (55-CONTEXT.md), the full-corpus run is
   operator-triggered. Promotion to prod is a further explicit step after the operator reviews
   the dev receipt.

---

## What is a Session-Class?

For the 2025-notebook corpus a session-class is a curated subset of pages the operator
considers ready for prod promotion. The operator defines session-classes after reviewing the
dev receipt. Examples of natural groupings:

- All pages of a single log_type (e.g. all `seeding` logs from the full corpus).
- A date range the operator has cross-checked against the paper notebook.
- A strain-code subset (e.g. all SHI-strain seeding + observation entries).

A session-class is operator-defined, not a code construct. The harness does not enforce it.

---

## Per-Session-Class Opt-In Process

A session-class may be promoted to prod ONLY when ALL of the following gates are passed:

### Gate 1: Clean dev receipt for that class

From the BACK-09 full-corpus receipt at
`.planning/notes/2026-XX-XX-2025-notebook-backfill-receipt.md`:

- `duplicate_asset_count == 0` for all pages in the class.
- `upsert_stability.unstable == 0` for all pages in the class.
- No unexplained failure reasons (fungi_type_not_found is acceptable if the operator
  confirms the corpus contains known-bad pages; extraction errors for non-curated strains
  are NOT acceptable for a prod write).

### Gate 2: Operator explicit opt-in

The operator writes a short decision note naming:

- Which session-class is being promoted.
- Which pages are in-scope (by IMG_NNNN basename).
- The dev receipt date and aggregate metrics that satisfy Gate 1.
- Confirmation that the May-22 stubs (or any other existing prod records) are the
  correct upsert targets for the pages in the class.

This note MUST be a committed file (e.g.
`.planning/notes/2026-XX-XX-promotion-<class-name>.md`), not a transient terminal session.

### Gate 3: Phase 51 upsert path

The prod write MUST go through the Phase 51 upsert path. The upsert layer identifies assets
by `block_name` (content-addressable) and enriches an existing prod record in-place rather
than minting a new one. This is the only path that safely merges 2025-notebook data with the
existing May-22 stubs.

A prod write that bypasses Phase 51 upsert and mints new assets for pages that already have
prod stubs is a data-integrity violation.

---

## Prod Write Path If Promoting

When all three gates above are satisfied for a session-class, the operator runs the harness
against prod with an explicit opt-in:

```bash
# Prod run: FARMOS_URL points at :8082; harness prod-guard must be intentionally satisfied.
# The FARMOS_URL prod-guard in backfill-notebook.js exits 3 if FARMOS_URL contains ':8082'
# or 'prod'. The operator intentionally overrides this by passing a FARMOS_PROD_OVERRIDE
# flag (to be added by the operator if running against prod) -- or by temporarily disabling
# the guard for the specific production-authorized run.

# IMPORTANT: GA1 isolation still applies.
# Even for a prod-pointing FARMOS_URL run, the DATABASE_URL prod-leak hazard remains.
# The shared TimescaleDB watchdog will drain confirmed drafts to PROD. Use the isolation
# pre-flight from 55-FULL-CORPUS-RUNBOOK.md (Option A throwaway postgres is DEFAULT).

# This doc does NOT authorize a prod run. It documents the criteria for a future operator
# decision to run one.
```

Cross-reference: 55-FULL-CORPUS-RUNBOOK.md for isolation mechanics (Option A throwaway
postgres on :5433 is RECOMMENDED even for prod-authorized runs, to avoid the watchdog
draining confirmed drafts twice -- once from the backfill harness and once from the alerter).

---

## This Document Does Not Authorize a Prod Run

55-PROMOTION-DECISION.md documents the criteria for a future operator decision. No run
authorized here. Authorization happens when the operator writes the Gate 2 decision note and
manually executes the harness against prod after satisfying all three gates.

---

## Out of Scope / Deferred

These items are explicitly NOT in Phase 55 scope:

### Commit-watchdog origin-guard

The durable coexistence fix (commit-watchdog checks draft origin before committing to prod)
was considered and deferred in GA1 (55-CONTEXT.md). It would eliminate the prod-leak hazard
without requiring operational isolation per run. Revisit if the operational isolation step
proves too heavy across many promoted runs.
See: `[[project_v113_watchdog_origin_guard_candidate]]`

### 4 bogus dev-farmOS fungi_type terms

LIM, SHIITAKE, OYS, and CAR were minted in dev farmOS by early backfill cycles that used
un-curated extraction output. They need farmOS admin DELETE (the mushy-bot account gets 403
on term DELETE). Carried from Phase 54.1. These terms are in dev only and do not affect prod.

### v1.13 narrowing

Phase v1.13 will consume the BACK-10 per-shape stats (tagged `bulk_backfill_auto_yes`) for
confirm-accuracy analysis. That is a separate milestone. The tag exists in the receipt to
let v1.13 exclude bulk-backfill auto-YES counts from its human-YES training signal.
The v1.13 narrowing work does not begin until Phase 55 GA2 is complete and the receipt
is reviewed.
