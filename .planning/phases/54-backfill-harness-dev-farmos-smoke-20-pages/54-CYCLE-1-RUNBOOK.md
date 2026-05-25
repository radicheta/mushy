# Phase 54 Cycle 1 RUNBOOK (5 pages, dev farmOS, farmer-attested)

**Purpose:** Smoke the backfill harness on 5 representative 2025-notebook pages against dev farmOS (`:18080`). Operator runs this end-to-end; farmer (Santi) reviews `receipt.md` and either signs off (unblocks Cycle 2) or files findings.

**Operator runs this. Do not delegate to an autonomous agent.**

**Page selection (5 of the 8 53-04 fixtures, weighted for diversity):**

1. `IMG_3775.jpg` (2025-02-01, 24 entries, multi-strain, fully dated)
2. `IMG_3778.jpg` (2025-02-20, 8 entries, small/sparse)
3. `IMG_3785.jpg` (2025-05-27/28, 18 entries, YEAR-ABSENT two-date)
4. `IMG_3800.jpg` (2025-08-06, 21 entries, YEAR-ABSENT single-strain bulk)
5. `IMG_3830.jpg` (2025-11-17, 22 entries, YEAR-ABSENT page-truncation case)

Note: today the `--limit=5` flag just takes the first 5 from the IMG_3775..IMG_3861 range, which is `IMG_3775, IMG_3776, IMG_3777, IMG_3778, IMG_3779`. For the exact Cycle-1 selection above, set `BACKFILL_PAGE_ALLOWLIST` in env (the harness currently lacks a `--pages-file` flag; add one in a follow-on plan if Cycle 1 needs the curated 5, OR run with `--limit=5` and accept the contiguous 3775..3779 slice for the smoke). **Operator decision before run:** stick with the contiguous slice (cheaper to ship, exercises BACK-01 year-absent paths on IMG_3776..3779) OR file a `--pages-file` follow-on and pause Cycle 1.

## Pre-flight (run all before step 6)

1. **dev farmOS reachable**

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' http://10.68.155.50:18080/jsonapi
   ```
   Expect `200` or `401`. If unreachable, fix farmOS before proceeding.

2. **DATABASE_URL points at the alerter dev DB**

   ```bash
   echo "$DATABASE_URL"
   ```
   Should resolve to the alerter's dev TimescaleDB (NOT prod).

3. **`.planning/backfill/` is in `.gitignore`** (committed in Plan 02)

   ```bash
   grep -n '.planning/backfill/' .gitignore
   ```

4. **Full alerter suite green**

   ```bash
   cd src/agents/alerter && npx jest
   ```
   Expect 1232+ pass / 9 skipped / 0 fail.

5. **ANTHROPIC_API_KEY is set**

   ```bash
   [ -n "$ANTHROPIC_API_KEY" ] && echo OK || echo MISSING
   ```

## Run

6. **Dry-run smoke FIRST** (no farmOS writes, no LLM calls):

   ```bash
   cd src/agents/alerter && \
     FARMOS_URL=http://10.68.155.50:18080 \
     FARMOS_USERNAME=mushy-bot \
     FARMOS_PASSWORD=... \
     DATABASE_URL=... \
     node scripts/backfill-notebook.js \
       --bulk-backfill --farmer=santi --cycle=1 --limit=5 --dry-run
   ```

   Expect: exit 0, 5 IMG_NNNN pages listed under `[backfill] selected:`. NO farmOS writes, NO `responses.jsonl`.

7. **Real run** (real LLM spend ~$0.10-0.50, real dev-farmOS writes):

   ```bash
   cd src/agents/alerter && \
     FARMOS_URL=http://10.68.155.50:18080 \
     FARMOS_USERNAME=mushy-bot \
     FARMOS_PASSWORD=... \
     DATABASE_URL=... \
     ANTHROPIC_API_KEY=... \
     node scripts/backfill-notebook.js \
       --bulk-backfill --farmer=santi --cycle=1 --limit=5
   ```

   **NOTE on real-run bootstrap:** Plan 01-04 ship the harness but the canonical `poolFactory` + `pipelineFactory` bootstrap from `src/index.js` is NOT yet wired into `main()`. The harness currently exits 1 with `[backfill] real-run bootstrap not yet wired — pass poolFactory/pipelineFactory or use --dry-run.` on real runs. **Before step 7, file a small follow-on plan (~30 min) to lift the bootstrap from `src/index.js` into a `createBackfillContext()` helper that wires `pool + pipeline(onLlmCall)`** OR write a tiny operator-side `live-fire-54.js` driver that does the bootstrap inline (mirroring `live-fire-52.js` pattern). The hermetic test suite proves all behaviors; the missing piece is connecting the canonical alerter bootstrap.

8. **Inspect `<runDir>/receipt.md`**

   ```bash
   RUN_DIR=$(ls -t .planning/backfill/2025-notebook | head -1)
   cat .planning/backfill/2025-notebook/$RUN_DIR/receipt.md
   ```

   Verify:
   - `duplicate_asset_count: 0 (PASS)`
   - `upsert_stability: unstable: 0 (PASS)` (or near-zero with explainable cases)
   - per-page CSV diffs reasonable (>= 80% hit on pages with CSV ground truth)
   - no surprising failure reasons in any per-page section

9. **Inspect summaries.log**

   ```bash
   cat .planning/backfill/2025-notebook/$RUN_DIR/summaries.log
   ```
   One line per draft. Every draft should be `ok=true` OR have a documented reason.

10. **Inspect responses.jsonl**

    ```bash
    wc -l .planning/backfill/2025-notebook/$RUN_DIR/responses.jsonl
    jq -s 'map(.cost_estimate_usd) | add' .planning/backfill/2025-notebook/$RUN_DIR/responses.jsonl
    ```
    Aggregate cost should match the receipt's `total_cost_usd`. Expect < $0.50 for 5 pages.

11. **Send the receipt to farmer (Santi) for review.** Receipt path is the artifact, not the dev-farmOS UI (per CONTEXT D-08).

12. **Farmer responds:**
    - **SIGN-OFF** → author `.planning/phases/54-.../54-CYCLE-1-RECEIPT.md` (template in 54-05-PLAN.md Task 2) with `verdict: SIGN-OFF` and `cycle-2 unlock: YES`. Reply `Cycle 1 signed off`.
    - **FINDINGS** → file each as `.planning/todos/pending/2026-MM-DD-cycle-1-finding-<name>.md`. Address all before unlocking Cycle 2.

### DO NOT proceed to 54-06 (Cycle 2) without farmer sign-off on 54-CYCLE-1-RECEIPT.md.
