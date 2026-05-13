# Phase 40 RUNBOOK -- farmOS Write Path

Operator runbook for driving + observing + recovering the commit pipeline.
Companion to `40-EVAL-REPORT.md` (ship-gate evidence) and `40-CONTEXT.md`
(decision record). All farmer-facing text in this doc uses the `--` separator,
never `--` em-dashes.

---

## 1. Pre-flight check

Before kicking a live-farmer UAT, confirm:

```bash
# Dev-farmOS reachable
curl -sI http://10.68.155.50:18080/user/login | head -1
# Expected: HTTP/1.x 200 OK  (or 405; 404 means the host is wrong)

# Alerter container has the credential pair set
docker compose exec alerter env | grep -E '^FARMOS_(URL|USERNAME)='
# Expected: both lines present; USERNAME non-empty

# Watchdog actually started (no credential-missing WARN)
docker compose logs alerter | tail -50 | grep -E 'commit-watchdog (started|disabled)'
# Expected: started: interval=... batchCap=... retryMax=... staleMin=...
# Bad path: 'disabled: farmOS credentials missing' --> set FARMOS_USERNAME/PASSWORD in .env

# asset_link module probe result
docker compose logs alerter | grep '\[farmos\] asset_link module' | tail -1
# Expected (dev today): 'absent, using farm_id_tag fallback'
# Expected (post-install in prod): 'present'
```

If any of the above fails, fix the gap before proceeding -- the live-farmer
UAT will not produce useful evidence if the watchdog never started.

---

## 2. Live-farmer UAT script

Mirror of Phase 39 UAT shape. Time budget: 5--10 minutes.

1. Operator opens `docker compose logs -f alerter | jq -c 'select(.event)'` in
   one pane.
2. Farmer (Don Santiago or surrogate) sends a Signal voice note describing an
   inoc session with a photo of the QR sticker.
3. Watch the event stream for this sequence (timestamps in parentheses are
   rough expected gaps):
   - `capture_inserted`           (t+0)
   - `extract_complete`           (t+15--90s; whisper + extractor)
   - `preview_sent`               (t+immediate after extract)
   - [farmer replies YES]         (t+manual)
   - `yes` (confirm event)        (t+immediate)
   - `commit_attempt`             (t+up-to-30s; watchdog tick)
   - `commit_success`             (t+immediate after attempt, if all green)
4. Verify in dev-farmOS UI (or via JSON:API):
   - New `BATCH-*` asset (or existing one re-used) under `/asset/fungi`
   - New block asset with `name = YYMMDD_<SP>_<SEQ>`, parent = batch, species set
   - New `seeding` log referencing both assets
   - If photo: file appears at `/file/file/<uuid>` and the log's `file`
     relationship points to it

If `commit_attempt` is followed by `commit_failed` rather than
`commit_success`, see section 4 (recovery procedures).

---

## 3. Audit recipe (D-06a)

Canonical single-stream audit: every committed draft in the last 24h.

```sql
SELECT id, farmos_person, log_type, farmos_response, committed_at
  FROM signal_draft
 WHERE status = 'committed'
   AND committed_at > NOW() - INTERVAL '24 hours'
 ORDER BY committed_at DESC;
```

Full event trail for a specific draft (useful when debugging a failure):

```sql
SELECT created_at, event, payload
  FROM signal_draft_event
 WHERE draft_id = '<id>'
 ORDER BY seq;
```

Count of commit outcomes in the last 24h (operational sanity check):

```sql
SELECT status, count(*)
  FROM signal_draft
 WHERE updated_at > NOW() - INTERVAL '24 hours'
   AND status IN ('confirmed','committing','committed','commit_failed')
 GROUP BY status;
```

---

## 4. Recovery procedures (D-07b)

### 4.1 commit_failed recovery (terminal error after retry budget)

After fixing the root cause (e.g. typo in batch name, farmOS auth fixed,
missing parent asset created manually), re-arm the draft:

```sql
UPDATE signal_draft
   SET status='confirmed',
       commit_attempt_count=0,
       commit_failed_reason=NULL,
       committed_at_attempt=NULL
 WHERE id='<id>';
```

The next watchdog tick (within COMMIT_WATCHDOG_INTERVAL_MS, default 30s) will
re-attempt the commit.

### 4.2 Stuck `committing` row (alerter crashed mid-commit)

Auto-released after `COMMIT_LOCK_STALE_MIN` minutes (default 5). Force-release
sooner if needed:

```sql
UPDATE signal_draft
   SET status='confirmed',
       committed_at_attempt=NULL
 WHERE id='<id>' AND status='committing';
```

### 4.3 farmOS-side asset went away (rare)

If the farmer or admin deleted the parent batch or block manually in the
farmOS UI before Phase 40 wrote its log, the commit will fail. Re-ingest from
the original Signal capture:

```sql
DELETE FROM signal_draft WHERE id='<id>';
-- Then trigger Phase 38 re-extraction from the source capture rows.
-- Easiest: have the farmer resend the message.
```

---

## 5. Dev -> prod env-flip

Pre-conditions (operator must verify):

- Farm team has installed the `farmos_asset_link` module in the prod farmOS
  instance (gated per the 2026-05-11 lock note; this is operator-deferred).
- A separate FARMOS_USERNAME exists in prod farmOS with write permission to
  `asset--fungi` and `log--seeding/activity/input/observation/harvest`.

Flip procedure:

```bash
# In repo-root .env
FARMOS_URL=http://<prod-farmos-host>:8082    # or wherever prod lives
FARMOS_USERNAME=<prod-bot-account>
FARMOS_PASSWORD=<prod-bot-password>

# Reload alerter
docker compose up -d --build alerter

# Confirm
docker compose logs alerter | grep '\[farmos\] asset_link module' | tail -1
# Expected: 'present'
```

WARNING: prod-farmOS writes are gated on the `farmos_asset_link` module install
per the 2026-05-11 lock note. Phase 40 ships dev-only by design; do not flip
prematurely or QR resolution will silently fall back to `farm_id_tag` lookup
and operator-side data hygiene will degrade.

---

## 6. Backoff + retry observability

The watchdog emits `commit_attempt_retry` events with the attempt number when
a transient failure (5xx or network) triggers `requeueForRetry`. Interpret:

- `attempt: 1` with retry -> first attempt failed transiently; waiting for
  backoffMs[0] (default 1000ms) before next try.
- `attempt: 3` with retry -> third attempt failed; this is the LAST retry
  before `commit_failed` fires on the next tick that picks the row up.

Spotting a stuck retry loop across many drafts:

```sql
SELECT id, log_type, commit_attempt_count, commit_failed_reason
  FROM signal_draft
 WHERE status = 'commit_failed'
   AND committed_at > NOW() - INTERVAL '24 hours'
 ORDER BY committed_at DESC;
```

If most failed rows share the same `commit_failed_reason`, that's the smoking
gun (likely farmOS-side schema drift, auth break, or missing species term).

---

## 7. Known limits + deferred items

- **No prod-farmOS writes.** Phase 40 is dev-only; env-flip gated on module
  install (section 5).
- **Native bundles only** (C5). Custom asset or log bundles are not supported
  by this pipeline; Phase 38 already rejects them at extraction time.
- **One draft at a time.** Bulk paper-log batch mode is routed to
  `needs_review` by Phase 38 D-12 and never reaches Phase 40.
- **No farmer-side `/retry` command.** Operator-side SQL re-trigger (section
  4.1) covers v1. Farmer-driven retry is a future UX.
- **`farmos_asset_link` probe is per-process.** Restarting the alerter
  re-probes; if the module is installed mid-run, the alerter does not pick it
  up until restart (expected; restart cadence is low).
- **Photo skip-on-missing is non-fatal** (D-05a). If the attachment file
  vanished between Phase 25 capture and Phase 40 commit, the observation log
  is created without the file reference and a WARN line is logged. Verify the
  `/data/signal-capture` volume mount if this fires frequently.

---

## 8. Memory pins consumed by this runbook

- `feedback_no_em_dashes_in_artifacts.md`
- `feedback_round_farmer_numbers.md` (no farmer-facing numbers in this doc;
  if section 6 grows operator-facing latency reports, apply `fmtNum`)
- `feedback_compose_env_passthrough_not_envfile.md` (Plan 01 ships the env
  passthrough; section 1 pre-flight verifies it)
- `feedback_real_data_before_ship_gate_pass.md` (Plan 07 fixture; this
  runbook section 2 is the live-farmer counterpart)
