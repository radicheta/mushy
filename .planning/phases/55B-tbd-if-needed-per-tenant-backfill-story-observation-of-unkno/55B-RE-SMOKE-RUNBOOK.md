# Phase 55B: GA1-Isolated 5-Page Re-Smoke Runbook

**Purpose:** Run 5 notebook pages through the Phase 55B fidelity gate + session routing +
page-image attach pipeline into an ISOLATED dev farmOS (:18080), confirm the regression
guard passes (IMG_3776 POY held, not committed as KOY), and produce an attested result for
the GA2 unblock decision.

**Operator runs this. Do not delegate to an autonomous agent.**

**Scope fence:** This runbook GATES and PREPARES -- it does NOT trigger the full-corpus run.
The parked 73-page full-corpus run remains Phase 55 / GA2-owned. Completing this re-smoke
with a PASS verdict satisfies SMOKE-01 and unblocks the GA2 decision conversation. No prod
write is authorized here (BACK-11: dev-only by default).

---

## Phase Gate Prerequisite Check

This re-smoke requires Phase 55B Plans 02 and 03 to be merged (fidelity gate + session
image-attach code). Verify before proceeding:

```bash
# Check that fidelity gate code is present
grep -r "fidelity_cross_check_unverified" src/agents/alerter/scripts/backfill-notebook.js \
  && echo "FIDELITY GATE: PRESENT" \
  || echo "FIDELITY GATE: MISSING -- run Plans 02+03 first"

# Check that page-image attach code is present
grep -r "sessionPagePaths" src/agents/alerter/src/farmos/commits/commit-seeding-session.js \
  && echo "IMAGE ATTACH: PRESENT" \
  || echo "IMAGE ATTACH: MISSING -- run Plan 03 first"
```

Both must show PRESENT before proceeding.

---

## STEP 0: Dev Credential Pre-flight (REQUIRED BEFORE ANY PAID STEP)

**This step is mandatory.** The A1 dev probe (55B-A1-SMOKE.md) found that prod bot
credentials (mushy-bot / prod password) are REJECTED by dev :18080 with HTTP 400
"unrecognized username or password." This means the re-smoke cannot proceed until working
dev :18080 credentials are available. Do NOT spend API tokens if dev auth fails.

```bash
# Confirm dev farmOS is reachable
curl -s -o /dev/null -w '%{http_code}\n' http://10.68.155.50:18080/jsonapi
# Must return 200. If not: dev farmOS is down; stop here.

# Confirm the dev credentials authenticate (HTTP 200 or 302, NOT 400)
# Replace DEV_USERNAME and DEV_PASSWORD with the actual dev :18080 credentials.
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST "http://10.68.155.50:18080/user/login?_format=json" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$DEV_USERNAME\",\"pass\":\"$DEV_PASSWORD\"}"
# Must return 200. HTTP 400 = wrong credentials; STOP. Do not proceed.
```

If the credential check returns 400, resolve the dev login before continuing:
- Option 1: Provide the dev :18080 mushy-bot password (if different from prod).
- Option 2: Provide a dev admin account (username + password) to use for the smoke.
- Do NOT try the prod password again -- it does not work on dev.

The A1 live confirmation (PATCH associates file to asset--group) is folded into this
re-smoke: "session image attached" is one of the hard pass criteria below. If the
re-smoke shows images attached, A1 is confirmed. If image attach fails, A1 is falsified
and the fallback (two-step create-then-patch or inline fileIds at creation) must be applied
before the full run.

Export the working dev credentials for use in all harness commands:

```bash
export DEV_FARMOS_USERNAME="<dev username>"
export DEV_FARMOS_PASSWORD="<dev password>"
```

---

## STEP 1: GA1 Isolation -- Option A (DEFAULT, RECOMMENDED)

This section is adapted verbatim from `55-FULL-CORPUS-RUNBOOK.md` GA1 isolation pre-flight.
Option A is the default. Use Option B only if port 5433 is occupied and no alternative is
available.

### Why isolation is required

There is ONE shared TimescaleDB on localhost:5432. The live `mushy-alerter-1` watchdog polls
it every 30s: `SELECT * FROM signal_draft WHERE status='confirmed'` and commits any matching
rows to PROD farmOS (:8082). When the backfill harness flips drafts to `status='confirmed'`,
those rows become visible to the watchdog. Confirmed backfill drafts leak to PROD within 30s
-- defeating the FARMOS_URL dev-only guard.

The throwaway postgres on :5433 ensures the watchdog is never wired to the backfill DB.

### Step A-1: Check that port 5433 is free

```bash
lsof -i :5433 2>/dev/null || echo "port 5433 free"
```

If occupied, use port 5434 (adjust the DATABASE_URL export below), or choose Option B.

### Step A-2: Start the throwaway postgres

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

### Step A-3: Export the throwaway DATABASE_URL

```bash
export DATABASE_URL="postgresql://postgres:backfill@localhost:5433/postgres"
```

### Step A-4: Assert DATABASE_URL does NOT point at the shared timescale

```bash
echo "$DATABASE_URL" | grep -v ":5432" \
  && echo "ISOLATION CHECK PASS" \
  || { echo "ABORT: DATABASE_URL may point at shared timescale on :5432"; exit 1; }
```

Exit 1 means abort -- do not proceed.

---

## STEP 2: Common Pre-flight Assertions

Run all four assertions. All must pass before any paid step.

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

---

## STEP 3: Dry Run (0 USD -- confirms page selection)

```bash
cd src/agents/alerter && \
  FARMOS_URL=http://10.68.155.50:18080 \
  FARMOS_USERNAME="$DEV_FARMOS_USERNAME" \
  FARMOS_PASSWORD="$DEV_FARMOS_PASSWORD" \
  DATABASE_URL="$DATABASE_URL" \
  node scripts/backfill-notebook.js \
    --limit=5 --resume-from=IMG_3775.jpg \
    --bulk-backfill --farmer santi --dry-run
```

Expected output: exactly 5 pages listed (IMG_3775, IMG_3776, IMG_3778, IMG_3782, IMG_3777),
0 USD spend. If fewer than 5 pages appear, abort and investigate.

---

## STEP 4: Paid Re-Smoke (5 pages, approx 0.20 USD)

Cost estimate: derived from Phase 54 Cycle-2 actual rate (20 pages / 0.78 USD). Actual cost
depends on page complexity and API caching.

```bash
RUN_ID="re-smoke-55b-$(date +%s)"
echo "Run ID: $RUN_ID"

cd src/agents/alerter && \
  FARMOS_URL=http://10.68.155.50:18080 \
  FARMOS_USERNAME="$DEV_FARMOS_USERNAME" \
  FARMOS_PASSWORD="$DEV_FARMOS_PASSWORD" \
  DATABASE_URL="$DATABASE_URL" \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  node scripts/backfill-notebook.js \
    --limit=5 --resume-from=IMG_3775.jpg \
    --bulk-backfill --farmer santi \
    --run-id="$RUN_ID"
```

The harness writes:
- `.planning/backfill/2025-notebook/$RUN_ID/receipt.md` (per-page result)
- `.planning/backfill/2025-notebook/$RUN_ID/responses.jsonl` (raw API responses, gitignored)
- `.planning/backfill/2025-notebook/$RUN_ID/summaries.log` (per-page summary lines)

---

## STEP 5: Per-Page Pass Criteria

This is the hard pass/fail gate. Check each criterion in order. The first FAIL aborts
the re-smoke verdict -- record the failure in 55B-RE-SMOKE.md and do not unblock GA2.

### IMG_3776 (02-04, mode 2: silent misattribution guard) -- HARD GATE

This is the primary regression guard. The 2026-06-07 prod audit found that POY entries on
IMG_3776 were committed as KOY with no error (silent misattribution).

PASS: Receipt shows the IMG_3776 POY entries with `ok: 'held'` and
`reason: 'fidelity_cross_check_unverified'`. No POY entry was committed as KOY (i.e.,
no KOY asset was created for IMG_3776).

FAIL: Any POY-as-KOY commit appears in the receipt or in dev farmOS for page date 2025-02-04.

```bash
# Check held entries for IMG_3776 in receipt
grep -A5 "IMG_3776" .planning/backfill/2025-notebook/"$RUN_ID"/receipt.md | \
  grep "fidelity_cross_check_unverified" \
  && echo "IMG_3776 POY HELD: PASS" \
  || echo "IMG_3776 CHECK: verify manually in receipt"
```

### IMG_3775 (02-01, mode 1: LIMA/POY misread)

PASS: ~7 entries held (LIMA x4 + POY x3) with `reason: 'fidelity_cross_check_unverified'`,
and ~17 entries committed (the CSV-verified hits). Exact counts depend on extraction output;
the key signal is that LIM and OYS variants are held while canonical LIMA and POY CSV entries
pass.

Note: counts are approximate because the CSV has ~17 curated entries for page 02-01 and the
extractor may read a slightly different count; the held/committed split should be in the
ballpark of 7 held / 17 committed.

### IMG_3778 (02-20, mode 1: CAZ->CAR misread)

PASS: CAR entries are held (not committed) because the CSV shows CAZ; CAZ-matching entries
are committed. If all entries are held, check that the CSV was loaded for this page.

### IMG_3782 (04-06, mode 3: under-capture)

PASS: Receipt shows the extracted SHI entries (expected fewer than the CSV shows); the
CSV budget holds the un-extracted ones. The session group asset is created even if some
entries are held.

### IMG_3777 (no CSV, mode 0: hold-all path)

PASS: ALL entries are held with `reason: 'fidelity_cross_check_no_csv'`. No entries from
IMG_3777 should appear as committed assets in dev farmOS.

```bash
grep -A5 "IMG_3777" .planning/backfill/2025-notebook/"$RUN_ID"/receipt.md | \
  grep "fidelity_cross_check_no_csv" \
  && echo "IMG_3777 HOLD-ALL: PASS" \
  || echo "IMG_3777 CHECK: verify manually in receipt"
```

### Session Group Assets (D-03: page image attached per page)

PASS: For each of the 5 pages, a session group asset named `inoc YYYY-MM-DD` (or with a
`#N` suffix for date collisions with existing live sessions) was created in dev farmOS
:18080, AND the notebook page image is attached to that asset.

A1 live confirmation: if the receipt shows `session_image_upload_failed: true` for any
page, A1 is falsified -- the PATCH relationship approach does not work for asset--group and
the fallback approach must be applied before the full run (see 55B-RESEARCH.md Pattern 4
fallback notes). Surface this as a FAIL in 55B-RE-SMOKE.md with the specific session
asset ID.

---

## STEP 6: Operator Held-Draft SQL Query

Run this against the throwaway DB to confirm held counts and reasons. Replace
`<page-date>` with each page date in the 5-page set.

```bash
psql "$DATABASE_URL" -c "
  SELECT id, log_type, needs_review_reason, draft_json->>'event_date' AS event_date
  FROM signal_draft
  WHERE status = 'needs_review'
    AND needs_review_reason LIKE 'fidelity_cross_check%'
  ORDER BY event_date, needs_review_reason;
"
```

Per-page date variant:

```bash
# Replace 2025-02-04 with the target page date (IMG_3776 = 2025-02-04)
psql "$DATABASE_URL" -c "
  SELECT id, log_type, needs_review_reason, draft_json
  FROM signal_draft
  WHERE status = 'needs_review'
    AND needs_review_reason LIKE 'fidelity_cross_check%'
    AND draft_json->>'event_date' = '2025-02-04';
"
```

Expected: held count > 0 for each page that has held entries; `needs_review_reason` values
should be one of:
- `fidelity_cross_check_unverified` -- strain disagrees with CSV
- `fidelity_cross_check_no_csv` -- page has no CSV rows (IMG_3777)
- `fidelity_cross_check_nonseeding` -- non-seeding shape on a CSV-covered page

---

## STEP 7: F2 Reconcile Step (SESSION-03)

For each of the 5 pages, open the session group asset in dev farmOS :18080 and verify the
F2 surface:

1. Navigate to dev farmOS :18080 -> Assets -> Groups.
2. Find the `inoc YYYY-MM-DD` group asset for each page date.
3. Confirm: the notebook page image is visible as an attachment on the group asset
   (this is the live A1 confirmation).
4. Confirm: the member list shows only the committed (CSV-verified) block assets.
   Held blocks are ABSENT from the member list -- this is the expected gap. A held
   block appearing as a member is a FAIL.
5. Open the attached page image and compare visually: the number of bags/blocks on the
   notebook page vs. the number of members in farmOS. The difference is the held count.

For IMG_3777 (all held, no CSV): the session group asset may exist with zero members and
one attached page image. This is correct behavior -- the session placeholder is there for
the farmer to use as a reconcile surface.

Record for each page:
- Session asset ID and name (e.g., `inoc 2025-02-01`)
- Whether the page image is attached (yes/no)
- Number of committed members vs. expected from CSV

---

## STEP 8: Aftercare (Option A)

After all criteria are checked and 55B-RE-SMOKE.md is written:

```bash
docker stop "$BACKFILL_PG" && docker rm "$BACKFILL_PG"
echo "Throwaway DB removed."
```

The re-smoke assets in dev farmOS :18080 may be left as-is (dev is rebuild-from-scratch
acceptable). If cleanup is desired, use farmOS admin DELETE via the UI (mushy-bot gets 403
on term DELETE).

---

## STEP 9: Record the Result in 55B-RE-SMOKE.md

Create `.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-RE-SMOKE.md`
with the following fields:

```markdown
# Phase 55B Re-Smoke Result

- run_id: <RUN_ID value>
- date: <YYYY-MM-DD>
- verdict: PASS | FAIL
- img3776_poy_held: yes | no (HARD GATE)
- img3775_held_count: <N>
- img3775_committed_count: <N>
- img3777_all_held_no_csv: yes | no
- session_images_attached: yes | no (A1 live confirmation)
- a1_confirmed: yes | no
- f2_held_absent_from_members: yes | no
- pages_completed: <N>
- harness_errors: <none | description>
- notes: <anything notable>
```

PASS criteria summary (all must be true):
- `img3776_poy_held: yes` -- the hard gate; POY not committed as KOY
- `session_images_attached: yes` -- A1 live confirmation
- `f2_held_absent_from_members: yes` -- SESSION-03 live confirmation

FAIL on any of these three: record the failing criterion and the observed behavior.
Do NOT signal "re-smoke PASS" if any of the three is no.

---

## Scope Fence

This runbook is the SMOKE-01 gate for Phase 55B. Completing it with a PASS verdict:

- Satisfies requirement SMOKE-01 (5-page re-smoke green)
- Satisfies requirement SESSION-03 live confirmation (F2 reconcile works end to end)
- Unblocks the GA2 conversation about the parked full-corpus run

It does NOT trigger the full-corpus run. The full-corpus run (73 pages) is:
- Phase 55 / GA2-owned
- Gated on Phase 55 Cycle-2 farmer SIGN-OFF (55-FULL-CORPUS-RUNBOOK.md GA2 gate)
- NOT authorized by this re-smoke result alone

Prod write remains opt-in per BACK-11 (55-PROMOTION-DECISION.md). The harness prod-guard
refuses FARMOS_URL values containing ':8082' or 'prod'. Do not attempt a prod run here.

---

## Option B Isolation (FALLBACK -- NOT default)

Use only if port 5433 is occupied and no alternative port is available.

**CRITICAL CAVEAT:** Stopping the watchdog only DEFERS the leak -- it does NOT prevent it.
After the run, you MUST run cleanup (see below) before restarting the alerter, or
backfill-confirmed drafts will drain to PROD on watchdog restart.

**Step B-1:** Confirm mushy-alerter-1 is running.

```bash
docker ps --filter "name=mushy-alerter" --format '{{.Names}} {{.Status}}'
```

**Step B-2:** Operator OK required. Note that prod RH alerting will pause for the run
window. Get an explicit operator OK before continuing.

**Step B-3:** Stop the alerter.

```bash
docker stop mushy-alerter-1
docker ps --filter "name=mushy-alerter" --format '{{.Names}} {{.Status}}'
```

Confirm no "Up" lines in output.

**Step B-4:** Verify the shared timescale is still accessible.

```bash
pg_isready -h localhost -p 5432 -U postgres
```

**Option B Aftercare -- ORDER IS MANDATORY:**

1. BEFORE starting the alerter: discard backfill drafts in the shared DB.

```bash
psql "$DATABASE_URL" -c \
  "SELECT count(*) FROM signal_draft WHERE status='confirmed' AND needs_review_reason='bulk_backfill_santi';"

psql "$DATABASE_URL" -c \
  "UPDATE signal_draft SET status='discarded' WHERE status='confirmed' AND needs_review_reason='bulk_backfill_santi';"

psql "$DATABASE_URL" -c \
  "SELECT count(*) FROM signal_draft WHERE status='confirmed' AND needs_review_reason='bulk_backfill_santi';"
```

Count must be 0 before proceeding.

2. THEN restart the alerter.

```bash
docker start mushy-alerter-1
docker ps --filter "name=mushy-alerter" --format '{{.Names}} {{.Status}}'
```

3. Confirm alerter health (check logs, no error storm).
