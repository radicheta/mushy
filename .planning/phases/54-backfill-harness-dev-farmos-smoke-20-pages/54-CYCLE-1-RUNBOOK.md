# Phase 54 Cycle 1 RUNBOOK (5 pages, dev farmOS, farmer-attested)

**Purpose:** Smoke the backfill harness on 5 representative 2025-notebook pages against dev farmOS (`:18080`). Operator runs this end-to-end; farmer (Santi) reviews `receipt.md` and either signs off (unblocks Cycle 2) or files findings.

**Operator runs this. Do not delegate to an autonomous agent.**

**Page selection (5 of the 8 53-04 fixtures, weighted for diversity):**

1. `IMG_3775.jpg` (2025-02-01, 24 entries, multi-strain, fully dated)
2. `IMG_3778.jpg` (2025-02-20, 8 entries, small/sparse)
3. `IMG_3785.jpg` (2025-05-27/28, 18 entries, YEAR-ABSENT two-date)
4. `IMG_3800.jpg` (2025-08-06, 21 entries, YEAR-ABSENT single-strain bulk)
5. `IMG_3830.jpg` (2025-11-17, 22 entries, YEAR-ABSENT page-truncation case)

**DECISION LOCKED 2026-05-26 (Santi): contiguous slice.** Cycle 1 runs `--limit=5`, which takes the first 5 of the IMG_3775..IMG_3861 range: `IMG_3775, IMG_3776, IMG_3777, IMG_3778, IMG_3779`. This ships now with no new code and still exercises the BACK-01 year-absent paths on IMG_3776..3779. The curated diversity set above is NOT used for Cycle 1 (it would need a `--pages-file` flag the harness lacks); revisit curated selection only if the contiguous smoke surfaces a gap.

## Pre-flight (run all before step 6)

1. **dev farmOS reachable**

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' http://10.68.155.50:18080/jsonapi
   ```
   Expect `200` or `401`. If unreachable, fix farmOS before proceeding.

2. **PROD-LEAK ISOLATION (HARD GATE -- replaces the falsified "DATABASE_URL is the dev DB" assumption)**

   There is only ONE shared timescale on `:5432`. The live `mushy-alerter-1` watchdog polls it
   for `status='confirmed'` every 30s and commits to **PROD farmOS (:8082)**. The harness leaves
   backfill drafts at `status='confirmed'` (it commits to dev directly but never advances them to
   `'committed'`), so ANY auto-confirm run against the shared DB leaks 2025 data to prod. Cycle 1
   is NOT exempt. Use Option A (default). Option B is a fallback with a hard cleanup obligation.

   **Option A (DEFAULT) -- throwaway postgres on :5433, prod watchdog never sees it:**

   ```bash
   # 1. assert 5433 is free (verified, not trusted)
   ! lsof -iTCP:5433 -sTCP:LISTEN -P -n && echo "5433 free" || { echo "5433 in use, abort"; }
   # 2. spin a throwaway DB (dropped after the run)
   docker run -d --name mushy-backfill-pg -p 5433:5432 \
     -e POSTGRES_PASSWORD=backfill -e POSTGRES_DB=alerter \
     timescale/timescaledb:2.15.0-pg16
   # 3. point DATABASE_URL at it and assert it is NOT the shared :5432
   export DATABASE_URL='postgres://postgres:backfill@127.0.0.1:5433/alerter'
   echo "$DATABASE_URL" | grep -q ':5432' && { echo "STILL POINTS AT SHARED DB, abort"; } || echo "isolated OK"
   ```
   `createBackfillContext` self-creates the schema on first connect; the harness writes only
   synthetic drafts, so an empty DB is correct. After the run (step 12): `docker rm -f mushy-backfill-pg`.

   **Option B (FALLBACK, NOT default) -- stop the live watchdog:** `docker stop mushy-alerter-1`
   pauses prod RH alerting (the farmer safety net) for the whole window -- needs explicit OK. It
   only DEFERS the leak: on restart the watchdog drains the still-`confirmed` backfill drafts to
   prod. So BEFORE `docker start mushy-alerter-1` you MUST clean up:
   `UPDATE signal_draft SET status='discarded' WHERE needs_review_reason='bulk_backfill_santi';`
   then verify zero backfill rows remain at `status='confirmed'`, THEN restart and confirm health.

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

   **Real-run bootstrap is WIRED (verified 2026-05-26).** `main()` builds `poolFactory` + `pipelineFactory` from `createBackfillContext()` (scripts/backfill-context.js) on any non-dry-run invocation, so the real run connects pool + extraction-pipeline automatically. No follow-on driver needed; the earlier "bootstrap not yet wired" note is obsolete (landed in `e4ec929`).

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
