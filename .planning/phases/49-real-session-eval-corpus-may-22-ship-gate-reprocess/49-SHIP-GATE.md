# Phase 49 Ship-Gate -- May 22 reprocess + discard against farmOS dev

**Status:** OPERATOR-DEFERRED (gated behind `EVAL_RUN_LIVE=1` + `FARMOS_DEV_URL` + `FARMOS_API_TOKEN` + prod `PG_PROD_CONN_STRING`)
**Hermetic ship-gate:** PASS (sessions.test.js named-regression: 2 tests green) -- `npx jest --config test/eval/ingestion/jest.config.js --testPathPattern='sessions.test.js$' --no-coverage`
**Operator runbook last revised:** 2026-05-23 (paired with 49-04 SUMMARY)

This document mirrors the [48-LIVE-FIRE.md](../48-session-entity-per-bag-commit-fan-out-session-shaped-confirm/48-LIVE-FIRE.md) paper-trail format. Phase 49's hermetic ship-gate covers the extractor + commit chain against the named-regression corpus (May-22 + May-12 fixtures); the live-fire path below is the mock-vs-real proof for v1.9. The two production drafts captured during the May-22 session attempt left signal_draft in a failed-commit state; the runbook discards them, reprocesses the May-22 audio + photo through the new pipeline (Phase 47 extraction + Phase 48 commit-fan-out), and attests against farmOS dev.

## Why operator-deferred

Per CONTEXT.md Gray Area D the v1.9 ship-gate is operator-driven: the runbook is the deliverable; the actual May-22 reprocess execution is the operator's responsibility post-merge, with results appended to the "Result" section below. Per the dev-farmOS-only policy the reprocess writes ONLY to farmOS dev -- no prod farmOS writes happen on the v1.9 ship-gate, and the prod-side change is limited to the two `signal_draft` rows the discard CLI flips to `status='discarded'`.

## Prerequisites

1. **farmOS dev reachable.** Confirm `FARMOS_DEV_URL` is set in the operator environment. From project memory ([[reference_farmos_project]]) the dev project lives at `/mnt/slime-kingdom/shared/farmos/`. Verify with:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" "$FARMOS_DEV_URL/api"
   # Expect: 200 (or 401 if no token; 401 still proves reachability)
   ```

2. **farmOS dev bearer token.** Set `FARMOS_API_TOKEN` to a token with write scope on `asset/fungi` + `log/seeding` and delete scope on `asset/fungi`. Reuse the token from Phase 48 live-fire if still valid.

3. **`fungi_xing 'block'` term exists in dev.** Verify:

   ```bash
   curl -s "$FARMOS_DEV_URL/api/taxonomy_term/fungi_xing?filter[name][value]=block" \
     -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq '.data | length'
   # Expect: 1
   ```

4. **`fungi_type` terms for SHI + KOY exist in dev.** Verify:

   ```bash
   for s in SHI KOY; do
     echo -n "$s: "
     curl -s "$FARMOS_DEV_URL/api/taxonomy_term/fungi_type?filter[name][value]=$s" \
       -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq '.data | length'
   done
   # Expect: SHI: 1, KOY: 1
   ```

5. **Prod timescale connection string.** Set `PG_PROD_CONN_STRING` to a `postgres://...` URL pointing at the production timescale that owns `signal_draft`. The discard CLI uses standard libpq env vars (`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`) inside the container; running outside the container uses `psql "$PG_PROD_CONN_STRING"` for the UUID lookup step. Treat the connection string as a secret; do NOT commit it.

6. **Plans 49-01 / 49-02 / 49-03 merged.** Verify:

   ```bash
   git log --oneline | grep -E "49-(01|02|03)" | head -5
   # Expect: at least one commit per plan
   test -f src/agents/alerter/scripts/discard-drafts.js
   test -f src/agents/alerter/test/eval/ingestion/sessions.test.js
   test -d src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi
   ```

7. **Phase 47 + Phase 48 hermetic ship-gates green.** Re-run their gates if doubts:

   ```bash
   cd /mnt/slime-kingdom/opt/mushy/src/agents/alerter
   npx jest test/extraction --no-coverage
   npx jest test/farmos/integration/seeding-session-commit --no-coverage
   # Expect both: green
   ```

8. **No pre-existing `inoc 2026-05-22` asset in farmOS dev** (first-run only). If a prior live-fire left one in dev, expect the handler to mint `inoc 2026-05-22 #2`. Sweep with:

   ```bash
   curl -s "$FARMOS_DEV_URL/api/asset/fungi?filter[name][value]=inoc 2026-05-22" \
     -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq '.data[].id'
   # If non-empty: DELETE them per Step 10 cleanup, or accept the #N collision branch
   ```

9. **`signal-cli` is configured for the bot identity** (only required if Step 8 verification reads the Signal-side ack -- the dev pipeline emits acks to the configured Signal account). Verify:

   ```bash
   docker compose exec alerter signal-cli -a "$SIGNAL_BOT_NUMBER" listAccounts 2>&1 | head -3
   # Expect: bot number listed
   ```

   Skip this prerequisite if you intend to verify acks via the alerter's `signal_outbound` table instead of the live Signal feed.

## Operator steps

### Step 1 -- Hermetic sanity (sessions.test.js + Phase 47/48 gates)

```bash
cd /mnt/slime-kingdom/opt/mushy/src/agents/alerter
npx jest --config test/eval/ingestion/jest.config.js \
  --testPathPattern='sessions.test.js$' --no-coverage
```

Expect: `Test Suites: 1 passed` / `Tests: 3 passed` (2 named regressions + 1 live-fire path documentation case). The third corpus fixture (`2026-03-23_inoc_santi_photo_absent`) is loaded but excluded from the named-regression gate by design (regression_guard:false). If red, do NOT proceed -- fix the hermetic regression first.

### Step 2 -- Retrieve full UUIDs of the two failed prod drafts

The CONTEXT lists truncated prefixes `e3a564d063d4` and `6edaaba7deb0`. The operator resolves the full UUIDs against prod timescale before passing them to the discard CLI:

```bash
psql "$PG_PROD_CONN_STRING" -c "
  SELECT id, created_at, status, log_type, sender_e164
  FROM signal_draft
  WHERE id LIKE 'e3a564d063d4%' OR id LIKE '6edaaba7deb0%'
  ORDER BY created_at;
"
# Expect: exactly 2 rows; status='extraction_committed' or similar non-discarded state.
# Copy the two full id values into the operator notes for Steps 3 + 4.
```

If more than 2 rows match (unlikely; the UUID prefix space is large), STOP and surface to the planner -- the discard set must be exactly the two May-22 failed drafts.

### Step 3 -- Dry-run discard (no `--apply`)

```bash
cd /mnt/slime-kingdom/opt/mushy/src/agents/alerter
docker compose exec alerter node /app/scripts/discard-drafts.js \
  --uuid <full-uuid-e3a564d063d4...> \
  --uuid <full-uuid-6edaaba7deb0...> \
  --reason "superseded by Phase 49 reprocess (v1.9 ship-gate)"
# Expect (no --apply flag = dry-run by default):
#   classify uuid=<e3a564...> state=candidate status=extraction_committed log_type=seeding ...
#   classify uuid=<6edaaba...> state=candidate status=extraction_committed log_type=seeding ...
#   summary: candidates=2 alreadyDiscarded=0 unknown=0 updated=0 dryRun=true
```

If either uuid classifies as `unknown` or `already-discarded`, STOP and re-verify the UUIDs from Step 2 before Step 4.

### Step 4 -- Apply discard (`--apply`)

```bash
cd /mnt/slime-kingdom/opt/mushy/src/agents/alerter
docker compose exec alerter node /app/scripts/discard-drafts.js \
  --uuid <full-uuid-e3a564d063d4...> \
  --uuid <full-uuid-6edaaba7deb0...> \
  --reason "superseded by Phase 49 reprocess (v1.9 ship-gate)" \
  --apply
# Expect:
#   summary: candidates=2 alreadyDiscarded=0 unknown=0 updated=2 dryRun=false
```

Verify the write landed:

```bash
psql "$PG_PROD_CONN_STRING" -c "
  SELECT id, status, discarded_reason, discarded_at
  FROM signal_draft
  WHERE id LIKE 'e3a564d063d4%' OR id LIKE '6edaaba7deb0%';
"
# Expect: both rows status='discarded', discarded_reason set, discarded_at populated.
```

### Step 5 -- Mkdir the reprocess output directory

```bash
REPROCESS_DIR="/mnt/mossrock/shared/mushdatadump-prod/2026-05-22_inoc_santi_reprocess_v1.9"
mkdir -p "$REPROCESS_DIR"
ls -la "$REPROCESS_DIR"
# Expect: empty dir created with operator rwx perms.
```

The original capture dir `/mnt/mossrock/shared/mushdatadump-prod/2026-05-22_inoc_santi/` is read-only for this runbook. Per [[feedback_persist_paid_results_default]] every paid artifact written during the reprocess lands in `$REPROCESS_DIR` under a unique timestamped filename. Never write into the parent capture dir.

### Step 6 -- Live-fire extraction (real Whisper + real Anthropic)

The operator runs the EVAL_RUN_LIVE=1 branch of `sessions.test.js` filtered to the May-22 fixture, capturing the full extractor output (audio transcript + photo-grounded draft) to `$REPROCESS_DIR`:

```bash
cd /mnt/slime-kingdom/opt/mushy/src/agents/alerter
REPROCESS_DIR="/mnt/mossrock/shared/mushdatadump-prod/2026-05-22_inoc_santi_reprocess_v1.9"
RUN_STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$REPROCESS_DIR/$RUN_STAMP"

EVAL_RUN_LIVE=1 \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  WHISPER_URL="$WHISPER_URL" \
  EVAL_OUTPUT_DIR="$REPROCESS_DIR/$RUN_STAMP" \
  npx jest --config test/eval/ingestion/jest.config.js \
    --testPathPattern='sessions.test.js$' \
    -t '2026-05-22' --no-coverage \
  2>&1 | tee "$REPROCESS_DIR/$RUN_STAMP/jest-extract.log"

# Expect:
#   $REPROCESS_DIR/$RUN_STAMP/jest-extract.log -- full jest stdout
#   $REPROCESS_DIR/$RUN_STAMP/draft.json       -- saved seeding_session draft (from the test's EVAL_OUTPUT_DIR write)
#   $REPROCESS_DIR/$RUN_STAMP/transcript.txt   -- Whisper transcript
#   sessions.test.js asserts ground-truth equality on key fields; PASS = the live draft matches the May-22 fixture's ground-truth
```

If the test FAILS the equality assertion under EVAL_RUN_LIVE=1, the model output drifted from the named-regression ground-truth. Save the failing draft to `$REPROCESS_DIR/$RUN_STAMP/draft-MISMATCH.json` and STOP per the deviation policy -- do NOT proceed to Step 7.

### Step 7 -- Live-fire farmOS dev commit

The operator feeds the draft saved in Step 6 into the real `commitSeedingSession` handler against farmOS dev:

```bash
cd /mnt/slime-kingdom/opt/mushy/src/agents/alerter
REPROCESS_DIR="/mnt/mossrock/shared/mushdatadump-prod/2026-05-22_inoc_santi_reprocess_v1.9"
LAST_RUN_DIR=$(ls -1dt "$REPROCESS_DIR"/*/ | head -1)
echo "using draft from: $LAST_RUN_DIR"

EVAL_RUN_LIVE=1 \
  FARMOS_DEV_URL="$FARMOS_DEV_URL" \
  FARMOS_API_TOKEN="$FARMOS_API_TOKEN" \
  DRAFT_JSON_PATH="$LAST_RUN_DIR/draft.json" \
  COMMIT_RESULT_PATH="$LAST_RUN_DIR/farmos-commit-result.json" \
  node -e "
    (async () => {
      const fs = require('fs');
      const { createFarmOSClient } = require('./src/farmos/client');
      const commitSeedingSession = require('./src/farmos/commits/commit-seeding-session');
      const draftJson = JSON.parse(fs.readFileSync(process.env.DRAFT_JSON_PATH, 'utf8'));
      const client = createFarmOSClient({
        baseUrl: process.env.FARMOS_DEV_URL,
        token: process.env.FARMOS_API_TOKEN,
        logger: console,
      });
      const draft = {
        id: 'live-fire-reprocess-' + Date.now(),
        log_type: 'seeding_session',
        draft_json: draftJson,
      };
      const auditLogger = { logCommit: async (e, d, r) => console.log('[audit]', e, r && r.status) };
      const t0 = Date.now();
      const r = await commitSeedingSession(client, draft, { auditLogger });
      const out = { elapsed_ms: Date.now() - t0, ...r };
      fs.writeFileSync(process.env.COMMIT_RESULT_PATH, JSON.stringify(out, null, 2));
      console.log(JSON.stringify(out, null, 2));
    })().catch(e => { console.error(e); process.exit(1); });
  " 2>&1 | tee "$LAST_RUN_DIR/node-commit.log"
# Expect: farmos-commit-result.json saved + non-error exit + the result JSON includes
#         11 child log UUIDs + 1 session asset UUID.
```

### Step 8 -- Verify 11 logs + session asset + lineage walk (mirror 48-LIVE-FIRE Steps 3-5)

```bash
SESSION_UUID=$(curl -s "$FARMOS_DEV_URL/api/asset/fungi?filter[name][value]=inoc 2026-05-22" \
  -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq -r '.data[0].id')
echo "session=$SESSION_UUID"
# Expect: a non-null UUID.

# Lineage walk on 260522_KOY_7 reconstructs the session from logs alone:
curl -s "$FARMOS_DEV_URL/api/asset/fungi?filter[name][value]=260522_KOY_7&include=parent" \
  -H "Authorization: Bearer $FARMOS_API_TOKEN" \
  | jq '.data[0].relationships.parent.data'
# Expect: array of length 2; one entry resolves to 260118_KOY_12, one entry = $SESSION_UUID.

# Children count:
curl -s "$FARMOS_DEV_URL/api/asset/fungi?filter[parent.id]=$SESSION_UUID" \
  -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq '.data | length'
# Expect: 11.

# 11 seeding logs landed (one per child):
curl -s "$FARMOS_DEV_URL/api/log/seeding?filter[asset.id]=$SESSION_UUID" \
  -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq '.data | length'
# Expect: 11.
```

Save the lineage walk JSON verbatim into `$LAST_RUN_DIR/lineage-walk.json` for the Result section append:

```bash
curl -s "$FARMOS_DEV_URL/api/asset/fungi?filter[name][value]=260522_KOY_7&include=parent" \
  -H "Authorization: Bearer $FARMOS_API_TOKEN" \
  | jq '.data[0].relationships.parent.data' > "$LAST_RUN_DIR/lineage-walk.json"
```

### Step 9 -- Verify both Phase 45 ack paths (success ack expected)

The May-22 reprocess covers the success-path ack. The failure-path ack is exercised by the Step 4 discard (no Signal ack on discard; Phase 45 success ack fires only after the v1.9 commit lands).

```bash
# Success-ack proof: the most recent signal_outbound row referencing the reprocess
# bot session should be a success acknowledgement to the operator.
docker compose exec alerter psql "$PG_LOCAL_CONN_STRING" -c "
  SELECT id, sender_e164, body, sent_at, kind
  FROM signal_outbound
  WHERE body LIKE '%inoc 2026-05-22%' OR body LIKE '%11 bags%' OR body LIKE '%seeded%'
  ORDER BY sent_at DESC
  LIMIT 3;
"
# Expect: top row is a success-ack body referencing the 11 children + the session.
# Save to $LAST_RUN_DIR/ack-success.txt.
```

If `kind='extraction_failed'` or the body is a failure phrasing, the commit chain did not reach the success-ack emitter -- STOP per the deviation policy.

### Step 10 -- Append result to "Result" section

Append a fresh block to the "Result" section at the bottom of this file. Include:

- Date + operator (Santi / radicheta / farmer1)
- Elapsed_ms from the Node script in Step 7
- Session asset UUID
- 11 child asset UUIDs
- 11 seeding log UUIDs
- Lineage walk JSON snippet (Step 8 output verbatim from `$LAST_RUN_DIR/lineage-walk.json`)
- Children count (must be 11)
- Phase 45 success ack body (paste from Step 9 `$LAST_RUN_DIR/ack-success.txt`)
- Cleanup outcome (Step 11)
- Deviations from hermetic expectations -- IF ANY, file a Phase 50 follow-up; do NOT silently fix in Phase 49.
- Verdict (PASS / FAIL)

### Step 11 -- Cleanup farmOS dev

```bash
# Delete the test session asset's 11 children + the session asset itself.
# Source parents (260118_*, 260304_*, 260425_*) are left in place; they are real
# parent blocks that future live-fires may reuse.

for name in 260522_SHI_1 260522_SHI_2 260522_SHI_3 \
            260522_KOY_4 260522_KOY_5 260522_KOY_6 260522_KOY_7 \
            260522_KOY_8 260522_KOY_9 260522_KOY_10 260522_KOY_11; do
  uuid=$(curl -s "$FARMOS_DEV_URL/api/asset/fungi?filter[name][value]=$name" \
    -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq -r '.data[0].id // empty')
  if [ -n "$uuid" ]; then
    curl -s -X DELETE "$FARMOS_DEV_URL/api/asset/fungi/$uuid" \
      -H "Authorization: Bearer $FARMOS_API_TOKEN"
    echo "deleted child $name = $uuid"
  fi
done

if [ -n "$SESSION_UUID" ]; then
  curl -s -X DELETE "$FARMOS_DEV_URL/api/asset/fungi/$SESSION_UUID" \
    -H "Authorization: Bearer $FARMOS_API_TOKEN"
  echo "deleted session $SESSION_UUID"
fi
```

The seeding logs are referenced by the session asset and child blocks; deleting the assets cascades the log deletion in farmOS dev (Phase 48 confirmed). Verify post-cleanup:

```bash
curl -s "$FARMOS_DEV_URL/api/log/seeding?filter[asset.id]=$SESSION_UUID" \
  -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq '.data | length'
# Expect: 0 (logs removed by cascade) OR 404 if SESSION_UUID is no longer routable.
```

## Deviation policy

If the live-fire returns a result that differs from the hermetic spec, FAIL the gate and open a Phase 50 follow-up. Specifically:

- The Step 6 EVAL_RUN_LIVE=1 jest assertion FAILS the named-regression equality check: the live model drifted from the May-22 ground-truth. Save the failing draft + capture the diff; open a Phase 50 follow-up. Do NOT patch the ground-truth to match the drift.
- The Step 7 farmOS dev commit returns a non-200 / non-201 status: the commit-chain shape changed since Phase 48 hermetic. Save the response payload; open a Phase 50 follow-up.
- The Step 8 children count is not exactly 11: a partial commit landed or the name-collision branch fired silently. Investigate.
- The Step 8 lineage walk array is not exactly length 2 with the expected parent + session_uuid pair: Phase 48 lineage encoding regressed.
- The Step 9 ack body is a failure phrasing OR is missing entirely: Phase 45 ack emitter or commit-chain wiring regressed.
- The Step 11 DELETE returns 4xx: farmOS FK constraints between session asset + children regressed.

Do NOT patch silently in Phase 49. The deviation is the signal.

## Result

### 2026-05-24 — A2 partial run (Santi via Claude, autonomous in-session)

**Verdict:** PARTIAL — prod-timescale side closed; farmOS-dev live-fire deferred.

Scope chosen: discard the still-open May-22 inoc draft and reason-stamp it; skip the live-fire extraction + farmOS dev write because the hermetic gate already attests the codepath (sessions.test.js 3/3 green this run) and the live-fire spend was not authorized in-session.

**Step 1 hermetic sanity:** PASS — sessions.test.js 3/3 (2 named regressions + 1 live-fire path doc case) under `npx jest --config test/eval/ingestion/jest.config.js --testPathPattern='sessions.test.js$' --no-coverage`.

**Step 2 UUID lookup deviation:** of the two runbook UUIDs against prod timescale:
- `6edaaba7deb026ff401b788938d407bc35dd10c8e958ab6138406c3632190a77` — `status=expired`, `log_type=seeding`. THE May-22 inoc draft. → Step 3/4 target.
- `e3a564d063d4fb1819403ac56df61aeaa523a943afdb3cafbd5ccb733858368a` — `status=discarded` since 2026-05-23 18:01:39Z, `discarded_reason=NULL`, `log_type=observation`. Already swept (likely during Phase 45 ack-debt sweep) without a reason set. CLI classified `already-discarded` and was left untouched per Step 3 dry-run; reason-backfill not attempted (CLI is idempotent on `status != 'discarded'`).

**Step 3 dry-run:** `dry-run summary: 1 would-update, 1 already-discarded, 0 unknown`.

**Step 4 apply (single-uuid invocation, `6edaaba` only):**
```
updated uuid=6edaaba7deb026ff401b788938d407bc35dd10c8e958ab6138406c3632190a77 prev=candidate new=discarded reason="superseded by Phase 49 reprocess (v1.9 ship-gate)" at=2026-05-24T13:34:29.622Z
apply summary: 1 updated, 0 already-discarded, 0 unknown
```
Post-apply prod-timescale state:
```
 id_pfx       | status     | log_type    | discarded_reason                                  | discarded_at
 6edaaba7deb0 | discarded  | seeding     | superseded by Phase 49 reprocess (v1.9 ship-gate) | 2026-05-24 13:34:29.622755+00
 e3a564d063d4 | discarded  | observation | (null)                                            | 2026-05-23 18:01:39.598627+00
```

**Steps 5-11:** NOT RUN. Live-fire extraction (Step 6, paid Whisper + Anthropic), farmOS dev commit (Step 7, http://10.68.155.50:18080), lineage walk (Step 8), success-ack proof (Step 9), and cleanup (Step 11) all deferred pending operator authorization. The runbook stands as-is for a future full-send.

**Side finding — farmOS dev location:** initial in-session diagnosis misread the elder-plops topology as single-instance. Corrected: dev farmOS = `/mnt/slime-kingdom/shared/farmos/` → host port `:18080`; prod farmOS = `/mnt/slime-kingdom/opt/farmos/` → host port `:8082`. Alerter `FARMOS_URL=http://10.68.155.50:8082` (prod). Any future live-fire of this runbook must override to `:18080` with a dev-minted bearer token. Captured in memory: `[[reference_farmos_dev_vs_prod_on_elder_plops]]`.

**Deviations from hermetic:** none in the work actually executed; e3a564's existing discarded-without-reason state is a paper-trail gap from a prior sweep, not a new deviation.

### To-be-filled (future full-send)

(empty -- to be filled in by the operator who runs Steps 5-11 against farmOS dev)

```
Date:
Operator:
Elapsed_ms (Step 7):
Session UUID:
Child UUIDs (11):
Log UUIDs (11):
Lineage walk JSON (260522_KOY_7 parents):
Children count for session:
Phase 45 success ack body:
Cleanup outcome:
Discard summary (Step 4):
Deviations from hermetic:
Verdict (PASS / FAIL):
```

## INOC-07 attestation

INOC-07 (>=3 sessions in eval corpus + ship-gate runbook ready for operator execution) attests once the operator appends a PASS verdict to the Result section above. Until then INOC-07 is "ready-to-attest"; after Result is filled with PASS the attestation flips to "attested" and the v1.9 milestone closes.

Attestation checklist (to be marked off as the Result block is populated):

- [ ] Eval corpus contains 3 sessions (2 named-regression + 1 unnamed-corpus diversity): VERIFIED IN PHASE 49 PLAN 04 (this commit)
- [ ] Hermetic sessions.test.js green with 2 named-regression cases: VERIFIED IN PHASE 49 PLAN 04 (this commit)
- [ ] Two failed May-22 prod drafts marked discarded with reason: (operator -- Step 4)
- [ ] May-22 audio + photo reprocessed through new pipeline: (operator -- Step 6)
- [ ] 11 logs + 1 session asset landed cleanly in farmOS dev: (operator -- Steps 7-8)
- [ ] Lineage walk reconstructs the session from logs alone: (operator -- Step 8)
- [ ] Phase 45 success ack fired: (operator -- Step 9)
- [ ] Cleanup outcome documented: (operator -- Step 11)

## Files

- Hermetic ship-gate: `src/agents/alerter/test/eval/ingestion/sessions.test.js`
- Sessions corpus loader: `src/agents/alerter/test/eval/ingestion/sessions-loader.js`
- Eval jest config: `src/agents/alerter/test/eval/ingestion/jest.config.js`
- Discard CLI: `src/agents/alerter/scripts/discard-drafts.js` (from Plan 49-03)
- Reprocess fixtures: `src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi/`
- Third corpus fixture: `src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-03-23_inoc_santi_photo_absent/`
- Commit handler: `src/agents/alerter/src/farmos/commits/commit-seeding-session.js`
- farmOS client: `src/agents/alerter/src/farmos/client.js`
- `signal_draft.discarded_reason` + `.discarded_at` migration: Plan 49-01

## Cross-references

- [48-LIVE-FIRE.md](../48-session-entity-per-bag-commit-fan-out-session-shaped-confirm/48-LIVE-FIRE.md) -- the structural template this runbook mirrors
- [47-LIVE-FIRE.md](../47-multi-source-extraction-fusion-groups-shape-inoc-draft/47-LIVE-FIRE.md) -- the paid-paper-trail precedent
- 49-CONTEXT.md -- Gray Area D (operator-deferred ship-gate) + Gray Area F (third-session selection)
- 49-01-SUMMARY.md -- schema delta + May-22 fixture
- 49-02-SUMMARY.md -- sessions.test.js + May-12 fixture
- 49-03-SUMMARY.md -- discard-drafts CLI
- 49-04-SUMMARY.md -- third corpus fixture + this runbook
