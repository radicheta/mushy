# Phase 54 Cycle 2 RUNBOOK (20 pages, dev farmOS, Phase 55 unlock gate)

**Purpose:** 20-page validation run on dev farmOS. Only unlocks after Cycle 1 sign-off. Same workflow at larger N validates that the receipt-review process scales without farmer-process friction. After Cycle 2 sign-off, Phase 55 (full-corpus backfill) unlocks.

**Operator runs this. Do not delegate to an autonomous agent.**

## Prerequisite

54-CYCLE-1-RECEIPT.md MUST exist with `verdict: SIGN-OFF`. If not, abort.

```bash
grep -E '^- verdict: SIGN-OFF$' \
  .planning/phases/54-backfill-harness-dev-farmos-smoke-20-pages/54-CYCLE-1-RECEIPT.md
```

Exit 0 required before proceeding.

## Pre-flight: PROD-LEAK ISOLATION (HARD GATE)

Same hazard as Cycle 1, at 4x the page count: the harness flips drafts to `status='confirmed'`
in the SHARED timescale (:5432), and the live `mushy-alerter-1` watchdog drains those to PROD
farmOS (:8082). Cycle 2 is NOT exempt. Run the SAME Option A isolation as Cycle 1 before any
paid step: spin a throwaway postgres on :5433, `export DATABASE_URL` pointing at it, and assert
it does NOT contain `:5432` (see 54-CYCLE-1-RUNBOOK.md pre-flight step 2 for the exact commands).
Option B (stop `mushy-alerter-1`) carries the same mandatory pre-restart draft cleanup. Drop the
throwaway DB after the run.

## Page Selection (20 pages)

**Tier A — re-run the 8 Cycle 1 + 53-04 fixtures (validates Phase 51 cross-cycle upsert stability):**

- `IMG_3775, IMG_3776, IMG_3778, IMG_3782, IMG_3785, IMG_3800, IMG_3825, IMG_3830`

**Tier B — 12 new pages from IMG_3775..IMG_3861 chosen by operator to:**

- cover dates not in Tier A (Mar, Jun, Jul, Sep, Oct, Dec 2025)
- include >= 3 pages whose `source` field references parent-block codes that Tier A already created (verifiable by `awk -F, '$1=="<page-date>"' /mnt/slime-kingdom/shared/mushdatadump/mushroom_log.csv`)
- skip operator-known-bad pages: `IMG_3790` (CA3 strain regex fail), `IMG_3810` (continuation/renumbering ambiguity), `IMG_3820` (WEDGE substrate regex fail) — same skip list from 53-04 SUMMARY.

**Operator records the 12 chosen IMG_NNNN here before execution:**

- (TBD: fill in before run)

## Steps

1. **Confirm Cycle 1 SIGN-OFF**

   ```bash
   grep -E '^- verdict: SIGN-OFF$' \
     .planning/phases/54-backfill-harness-dev-farmos-smoke-20-pages/54-CYCLE-1-RECEIPT.md
   ```

2. **Confirm dev farmOS state from Cycle 1: assets from those 5 pages exist.** Spot-check:

   ```bash
   curl -s -u "$FARMOS_USERNAME:$FARMOS_PASSWORD" \
     "http://10.68.155.50:18080/api/asset/fungi?filter%5Bname%5D=<block_name>"
   ```
   Should return the Cycle 1 UUID.

3. **Backup note:** corpus is read-only (backup at `/mnt/slime-kingdom/shared/mushdatadump.backup-2026-05-24/`); dev farmOS state is rebuild-from-scratch-acceptable per CONTEXT D-09. No DB backup required.

4. **Dry-run smoke FIRST:**

   ```bash
   cd src/agents/alerter && \
     FARMOS_URL=http://10.68.155.50:18080 \
     FARMOS_USERNAME=mushy-bot FARMOS_PASSWORD=... DATABASE_URL=... \
     node scripts/backfill-notebook.js \
       --bulk-backfill --farmer=santi --cycle=2 --limit=20 --dry-run
   ```
   Expect 20 pages listed.

5. **Real run** (~$2 estimated for 20 pages):

   Drop `--dry-run` and add `ANTHROPIC_API_KEY`. Note the new `<runId>`.

6. **If the run interrupts** (network blip, OOM, etc.), use `--resume-from=IMG_NNNN.jpg` to continue without re-spending tokens on completed pages. Per the receipt-builder design, prior responses.jsonl is preserved (T-54-10 guard refuses to overwrite); operator picks a fresh `--run-id` and `--resume-from` from the last successfully-completed page.

7. **Inspect `<runDir>/receipt.md`:**

   - **Aggregate:** `duplicate_asset_count: 0 (PASS)`.
   - **Tier A re-run validation:** for the 8 fixture pages, `assets_reused` count should be HIGH (most assets pre-exist from Cycle 1). `assets_created` on Tier A pages should be NEAR-ZERO. **If non-zero, that's a Phase 51 contract regression — file as finding and BLOCK Phase 55.**
   - **Upsert stability:** all stable (`unstable: 0 (PASS)`).
   - **CSV diff:** >= 80% hit on pages with CSV coverage.
   - **Unknown strain codes:** review with farmer (could indicate new strain to add to `mossrock_active_strain_codes` memory).

8. **Inspect summaries.log:** 20 pages worth, every draft has `ok=true` OR a documented reason.

9. **Inspect responses.jsonl:** `total_cost_usd` reported in receipt aggregate matches sum of `cost_estimate_usd` per line.

10. **Send receipt.md to farmer for review.**

11. **Author 54-CYCLE-2-RECEIPT.md** (template in 54-06-PLAN.md Task 2).

## Phase 55 unlock gate

Cycle 2 sign-off + receipt's `Phase 55 unlock: YES` line is what unblocks the full-corpus backfill (Phase 55). Phase 55 unlocks ONLY when `verdict == SIGN-OFF AND Phase 55 unlock == YES`.
