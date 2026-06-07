# Phase 55: Full-Corpus Backfill RUNBOOK (73 pages, dev farmOS)

**Purpose:** Run all 73 PAGE_REGEX notebook pages through the extraction/strain-confirm/commit
harness into dev farmOS (:18080), produce a permanent receipt and UUID JSONL, and capture
per-shape stats tagged as bulk-backfill auto-YES (BACK-09 + BACK-10).

**Operator runs this. Do not delegate to an autonomous agent.**

## GA2 Gate

This runbook unlocks ONLY after Phase 54 Cycle-2 receives farmer SIGN-OFF.
Check before proceeding:

```bash
grep -E '^- verdict: SIGN-OFF$' \
  .planning/phases/54-backfill-harness-dev-farmos-smoke-20-pages/54-CYCLE-2-RECEIPT.md
grep -E '^- Phase 55 unlock: YES$' \
  .planning/phases/54-backfill-harness-dev-farmos-smoke-20-pages/54-CYCLE-2-RECEIPT.md
```

Both lines must match. If either is missing, abort.

---

## HARD PRE-FLIGHT: PROD-LEAK ISOLATION

### Why this exists

The Phase-54 Cycle-1 pre-flight said: "DATABASE_URL should resolve to the alerter's dev
TimescaleDB (NOT prod)." That assumption is FALSIFIED.

There is ONE shared TimescaleDB on localhost:5432. The live `mushy-alerter-1` watchdog polls
that same DB every 30s: `SELECT * FROM signal_draft WHERE status='confirmed'` and commits
any matching rows to PROD farmOS (:8082). When the backfill harness flips drafts to
`status='confirmed'`, those rows are immediately visible to the watchdog. Confirmed backfill
drafts leak to PROD within 30s -- defeating the harness's own FARMOS_URL dev-only guard.

You MUST choose one of the two isolation options below before any paid step. Both are
copy-pasteable verified-not-trusted checks. **Option A is the DEFAULT and RECOMMENDED.**

---

### Option A (DEFAULT -- RECOMMENDED): Throwaway Postgres on Port 5433

The backfill runs against a fresh postgres container. The prod-pointing watchdog is never
wired to this DB, so there is no leak and no cleanup race. Drop the container after the run.

**Step A-1: Check that port 5433 is free.**

```bash
lsof -i :5433 2>/dev/null || echo "port 5433 free"
```

If occupied, use port 5434, or choose Option B.

**Step A-2: Start the throwaway postgres.**

```bash
BACKFILL_PG=backfill-pg-$(date +%s)
docker run -d --name "$BACKFILL_PG" \
  -e POSTGRES_PASSWORD=backfill \
  -p 5433:5432 \
  postgres:14
echo "Container: $BACKFILL_PG"

# Wait for ready (up to 30s)
for i in $(seq 1 30); do
  pg_isready -h localhost -p 5433 -U postgres && break
  sleep 1
done
```

**Step A-3: Export the throwaway DATABASE_URL.**

```bash
export DATABASE_URL="postgresql://postgres:backfill@localhost:5433/postgres"
```

**Step A-4: Assert DATABASE_URL does NOT point at the shared timescale.**

```bash
echo "$DATABASE_URL" | grep -v ":5432" \
  && echo "ISOLATION CHECK PASS" \
  || { echo "ABORT: DATABASE_URL may point at shared timescale on :5432"; exit 1; }
```

This is a verified-not-trusted check. Exit 1 means abort -- do not proceed.

**Aftercare (Option A):** After the run and receipt verification, drop the throwaway container:

```bash
docker stop "$BACKFILL_PG" && docker rm "$BACKFILL_PG"
echo "Throwaway DB removed."
```

---

### Option B (FALLBACK -- NOT default): Stop mushy-alerter-1 for the run window

Use this only if Option A is not viable (e.g., port conflict and no alternative port available).

**CRITICAL CAVEAT:** Stopping the watchdog only DEFERS the leak -- it does NOT prevent it.
The harness commits content directly to dev farmOS (:18080) but leaves each draft at
`status='confirmed'` in the shared DB. This has been verified (2026-05-26):
`backfill-notebook.js` never advances drafts from `'confirmed'` to `'committed'`. On restart,
the watchdog will drain every still-'confirmed' backfill draft straight to PROD.

**Therefore Option B REQUIRES a mandatory pre-restart cleanup step** -- see the Aftercare
section for Option B below. Restarting the alerter before running that cleanup leaks the
entire corpus to PROD.

**Step B-1: Confirm mushy-alerter-1 is running.**

```bash
docker ps --filter "name=mushy-alerter" --format '{{.Names}} {{.Status}}'
```

**Step B-2: Operator OK required.** Note that prod RH alerting will pause for the run window.
The alerter is the farmer safety net. Get an explicit operator OK before continuing.

**Step B-3: Stop the alerter.**

```bash
docker stop mushy-alerter-1
docker ps --filter "name=mushy-alerter" --format '{{.Names}} {{.Status}}'
```

Confirm no "Up" lines in output.

**Step B-4: Verify the shared timescale is still accessible (backfill needs it for pipeline).**

```bash
pg_isready -h localhost -p 5432 -U postgres
```

**Aftercare (Option B) -- ORDER IS MANDATORY:**

1. BEFORE starting the alerter: delete or re-status all backfill drafts in the shared DB.

   ```bash
   # Verify how many backfill drafts are still 'confirmed'
   psql "$DATABASE_URL" -c \
     "SELECT count(*) FROM signal_draft WHERE status='confirmed' AND needs_review_reason='bulk_backfill_santi';"

   # Mark them discarded so the watchdog ignores them on restart
   psql "$DATABASE_URL" -c \
     "UPDATE signal_draft SET status='discarded' WHERE status='confirmed' AND needs_review_reason='bulk_backfill_santi';"

   # Verify zero rows remain at status='confirmed' for backfill origin
   psql "$DATABASE_URL" -c \
     "SELECT count(*) FROM signal_draft WHERE status='confirmed' AND needs_review_reason='bulk_backfill_santi';"
   ```

   Count must be 0 before proceeding.

2. THEN restart the alerter:

   ```bash
   docker start mushy-alerter-1
   docker ps --filter "name=mushy-alerter" --format '{{.Names}} {{.Status}}'
   ```

3. Confirm alerter health restored (check logs, no error storm).

---

### Common Pre-flight Assertions (Required Regardless of Option A or B)

```bash
# 1. Dev farmOS :18080 reachable (NOT prod :8082)
curl -s -o /dev/null -w '%{http_code}\n' http://10.68.155.50:18080/jsonapi
# Expect 200. Exit if not.

# 2. FARMOS_URL does not contain :8082 or 'prod'
echo "$FARMOS_URL" | grep -vE ":8082|prod" \
  && echo "FARMOS_URL PASS" \
  || { echo "ABORT: FARMOS_URL points at prod"; exit 1; }

# 3. ANTHROPIC_API_KEY set
[ -n "$ANTHROPIC_API_KEY" ] \
  && echo "ANTHROPIC_API_KEY SET" \
  || { echo "ABORT: ANTHROPIC_API_KEY missing"; exit 1; }

# 4. Alerter Jest suite green
cd src/agents/alerter && npx jest --passWithNoTests
```

All four must pass before any paid step.

---

## SMOKE BEFORE FULL RUN

### Step 1: Dry-run (0 USD, confirms page selection)

```bash
cd src/agents/alerter && \
  FARMOS_URL=http://10.68.155.50:18080 \
  FARMOS_USERNAME=mushy-bot \
  FARMOS_PASSWORD=<password> \
  DATABASE_URL=<throwaway_or_shared_per_option> \
  node scripts/backfill-notebook.js \
    --all-pages --bulk-backfill --farmer=santi --dry-run
```

Expected output: 73 pages listed, 0 USD spend. If fewer than 73 pages appear, abort and
investigate. The PAGE_REGEX covers IMG_3775..IMG_3847 (73 files exist in the corpus; the
regex was written for up to IMG_3861 but only 73 files match on disk).

### Step 2: Paid smoke (5 pages, about 0.20 USD)

This cost estimate is derived from the Cycle-2 actual rate (20 pages / 0.78 USD), recorded
in .planning/phases/54-backfill-harness-dev-farmos-smoke-20-pages/54-CYCLE-2-RECEIPT.md.

```bash
cd src/agents/alerter && \
  FARMOS_URL=http://10.68.155.50:18080 \
  FARMOS_USERNAME=mushy-bot \
  FARMOS_PASSWORD=<password> \
  DATABASE_URL=<throwaway_or_shared_per_option> \
  ANTHROPIC_API_KEY=<key> \
  node scripts/backfill-notebook.js \
    --limit=5 --bulk-backfill --farmer=santi --run-id=smoke-$(date +%s)
```

Review the smoke receipt (in `.planning/backfill/2025-notebook/<runId>/receipt.md`):
- `duplicate_asset_count: 0` -- PASS required
- No unexpected crash or FARMOS_URL error
- Per-page drafts show `ok=true` or documented failure reasons

Proceed to the full run only after smoke receipt is clean.

---

## FULL RUN

Full corpus: 73 pages, about 2.85 USD.

This cost estimate is derived from the Cycle-2 actual rate (20 pages / 0.78 USD), recorded
in .planning/phases/54-backfill-harness-dev-farmos-smoke-20-pages/54-CYCLE-2-RECEIPT.md.
Actual cost depends on page complexity and API caching.

Note the `--run-id` value before starting -- you will need it for crash recovery.

```bash
RUN_ID="full-corpus-$(date +%s)"
echo "Run ID: $RUN_ID"

cd src/agents/alerter && \
  FARMOS_URL=http://10.68.155.50:18080 \
  FARMOS_USERNAME=mushy-bot \
  FARMOS_PASSWORD=<password> \
  DATABASE_URL=<throwaway_or_shared_per_option> \
  ANTHROPIC_API_KEY=<key> \
  node scripts/backfill-notebook.js \
    --all-pages --bulk-backfill --farmer=santi --run-id="$RUN_ID"
```

On success, the harness writes:
- `.planning/notes/2026-XX-XX-2025-notebook-backfill-receipt.md` (permanent receipt)
- `.planning/notes/2026-XX-XX-2025-notebook-backfill-receipt.jsonl` (UUID JSONL)
- `.planning/backfill/2025-notebook/<runId>/` (gitignored audit dir with responses.jsonl)

---

## CRASH RECOVERY

If the run interrupts at page N of 73, use `--resume-from` with a FRESH `--run-id`:

```bash
# Check the last successfully-completed page in summaries.log
tail -20 .planning/backfill/2025-notebook/"$RUN_ID"/summaries.log

# Resume from the next page after the last successful one
RESUME_ID="full-corpus-resume-$(date +%s)"
cd src/agents/alerter && \
  FARMOS_URL=http://10.68.155.50:18080 \
  FARMOS_USERNAME=mushy-bot \
  FARMOS_PASSWORD=<password> \
  DATABASE_URL=<throwaway_or_shared_per_option> \
  ANTHROPIC_API_KEY=<key> \
  node scripts/backfill-notebook.js \
    --all-pages --bulk-backfill --farmer=santi \
    --resume-from=IMG_NNNN.jpg \
    --run-id="$RESUME_ID"
```

**IMPORTANT:** A fresh `--run-id` is required. The `runIdExistsGuard` (exit code 6) prevents
overwriting an existing `responses.jsonl` in the prior run dir. Using the old run-id exits 6.

The two partial run dirs are acceptable. If needed, the final BACK-09 receipt can be authored
by concatenating the two partial `receipt.md` files manually. Automating the merge is deferred
pending evidence of need.

---

## SKIP LIST

These three pages are operator-known-bad and will likely produce extraction failure reasons
in the per-page receipt. They do NOT crash the run.

| Page | Reason |
|------|--------|
| IMG_3790 | CA3 strain regex fail (pre-flagged known-bad) |
| IMG_3810 | Renumbering ambiguity |
| IMG_3820 | WEDGE substrate regex fail (pre-flagged known-bad) |

The run will encounter these pages in the --all-pages sweep. Their failure reasons will
appear in the per-page receipt section. Verify they show documented failure reasons, not
silent drops. If the run crashes at one of these pages, use `--resume-from` to skip past it.

---

## RECEIPT VERIFICATION

After the run completes, verify:

```bash
# 1. Permanent receipt exists
ls -la .planning/notes/2026-*-2025-notebook-backfill-receipt.md
ls -la .planning/notes/2026-*-2025-notebook-backfill-receipt.jsonl

# 2. Aggregate pass criteria
grep "duplicate_asset_count: 0" \
  .planning/notes/2026-*-2025-notebook-backfill-receipt.md \
  && echo "DUPLICATE CHECK PASS" \
  || echo "FAIL: duplicate assets found"

grep "unstable: 0" \
  .planning/notes/2026-*-2025-notebook-backfill-receipt.md \
  && echo "UPSERT STABILITY PASS" \
  || echo "FAIL: unstable upserts"

# 3. BACK-10 section present and tagged
grep "bulk_backfill_auto_yes" \
  .planning/notes/2026-*-2025-notebook-backfill-receipt.md \
  && echo "BACK-10 TAG PASS" \
  || echo "FAIL: BACK-10 tag missing"
```

Pass criteria:
- `duplicate_asset_count == 0`
- `upsert_stability.unstable == 0` (empty)
- BACK-10 section present and tagged `bulk_backfill_auto_yes`

---

## AFTERCARE

Run the relevant aftercare block for the isolation option you chose (Option A or Option B
above), then:

1. Commit the receipt files to git:

   ```bash
   git add .planning/notes/2026-*-2025-notebook-backfill-receipt.md
   git add .planning/notes/2026-*-2025-notebook-backfill-receipt.jsonl
   git commit -m "feat(55): add full-corpus backfill receipt (BACK-09)"
   ```

2. Author the Phase 55 run receipt doc (see 55-PROMOTION-DECISION.md for the prod-promotion
   decision process; the receipt is input to that decision).

3. If any unknown strain codes appeared in the receipt, run
   `node scripts/backfill-confirm-strains.js` to mint confirmed terms and re-run held drafts
   before treating the per-shape stats as final.
