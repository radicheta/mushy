# Phase 40 Research: FarmOS Write Path

**Researched:** 2026-05-13
**Status:** Ready for planning
**Inputs:** 40-CONTEXT.md (D-01..D-08c), Phase 39 patterns (watchdog, outbound dispatcher), `farmos_client.py`, locked schema notes (2026-05-11), `signal_draft` Phase 38 table.

## 1. FarmOS Auth + Transport Shape (D-01a)

The Python `farmos_client.py` proves the shape. JS mirror:

```js
// POST {FARMOS_URL}/user/login?_format=json
//   body  { name, pass }                          (JSON, not vnd.api+json)
//   reply { csrf_token, current_user, logout_token }
//   side-effect: Set-Cookie with SSESS* session id (kept in jar)
//
// All subsequent JSON:API calls carry:
//   X-CSRF-Token: <csrf>
//   Content-Type: application/vnd.api+json
//   Accept:       application/vnd.api+json
//   Cookie:       SSESS...                        (auto from jar)
```

Implementation notes for JS:

- Use Node's native `fetch` (Node 18+; the alerter image is Node 20). No new dep.
- Maintain a cookie string manually (single-cookie jar is enough; farmOS only sets one
  session cookie). Stash `{cookie, csrf}` on the client object.
- 10s timeout per call via `AbortController + setTimeout`.
- File upload uses a different `Content-Type` (`application/octet-stream`) -- see Section 5.
- Auth retry: on 401/403, re-auth once and retry the original call. Bound the recursion.

## 2. JSON:API Request Bodies per B1..B4 (fungi assets)

All four assets share `type: 'asset--fungi'`. Differentiation is by `attributes.bundle` not the type
name (farmOS encodes bundle in the type slug: `asset--fungi` IS the bundle). `name` + relationships
encode the lifecycle role.

### B1: Sterilization batch (anonymous, no QR)

```http
POST {FARMOS_URL}/api/asset/fungi
{
  "data": {
    "type": "asset--fungi",
    "attributes": {
      "name": "BATCH-2026-05-12-001",           // BATCH- prefix per B1
      "status": "active",
      "notes": { "value": "mushy:draft:<draft_id>", "format": "plain_text" }
    }
  }
}
```
Response: `201 Created` with `data.id` = asset UUID.

### B2: Block (parent = batch, species, QR bound at inoc)

```http
POST {FARMOS_URL}/api/asset/fungi
{
  "data": {
    "type": "asset--fungi",
    "attributes": {
      "name": "260512_DT_001",                  // YYMMDD_SPECIES_SEQ per Phase 38 D-08 / B5
      "status": "active",
      "notes": { "value": "mushy:draft:<draft_id>", "format": "plain_text" }
    },
    "relationships": {
      "parent": {
        "data": [{ "type": "asset--fungi", "id": "<batch_uuid>" }]
      },
      "species": {
        "data": [{ "type": "taxonomy_term--species", "id": "<species_term_uuid>" }]
      }
    }
  }
}
```

`farm_id_tag` QR bind: see Section 4.

### B3: Harvest batch (multi-parent = source blocks)

```http
POST {FARMOS_URL}/api/asset/fungi
{
  "data": {
    "type": "asset--fungi",
    "attributes": { "name": "HBATCH-2026-05-12-DT-001", "status": "active",
                    "notes": { "value": "mushy:draft:<draft_id>", "format": "plain_text" } },
    "relationships": {
      "parent": {
        "data": [
          { "type": "asset--fungi", "id": "<block_uuid_1>" },
          { "type": "asset--fungi", "id": "<block_uuid_2>" }
        ]
      }
    }
  }
}
```

### B4: Bag (parent = harvest batch, QR bound at bagging)

Same shape as B2 but `parent` is the harvest-batch UUID and `species` is omitted (inherited).

## 3. JSON:API Request Bodies per B7 Log Types (native only, C5)

Five native types. All carry the same envelope:

```jsonc
{
  "data": {
    "type": "log--<TYPE>",
    "attributes": {
      "name": "<human-readable summary>",
      "timestamp": <unix seconds>,
      "status": "done",
      "notes": { "value": "...optional farmer text + mushy:draft:<id>...",
                 "format": "plain_text" }
    },
    "relationships": {
      "asset": { "data": [{ "type": "asset--fungi", "id": "<uuid>" }, ...] },
      "file":  { "data": [{ "type": "file--file",  "id": "<uuid>" }, ...] }   // optional
    }
  }
}
```

### B7.1 seeding (inoc)

- Endpoint: `POST /api/log/seeding`
- Required relationships: `asset[]` = [batch_uuid, block_uuid] (the block being inoculated;
  batch is the parent of the block but tagging both keeps the log queryable from either side).

### B7.2 activity

- Endpoint: `POST /api/log/activity`
- `attributes.name` MUST contain the activity subtype as the leading token
  (sterilize / sterilize_failed / water / relocate / cold_shock / archive_spent / contam)
  -- farmOS native does NOT have an activity subtype enum, so we encode it in the name and
  optionally also in a `category` taxonomy ref if the operator has set it up.
  Plan accepts the name-encoding fallback; richer categorization deferred.

### B7.3 input

- Endpoint: `POST /api/log/input`
- Used for recipe lots (substrate weights, grain spawn, etc.) -- `attributes.notes` carries
  the structured ingredient list as plain text; no quantity-typed material refs in v1.

### B7.4 observation

- Endpoint: `POST /api/log/observation`
- For state checks, pin emergence, photos. Photo handling: Section 5.

### B7.5 harvest

- Endpoint: `POST /api/log/harvest`
- Multi-asset: `asset.data` = [source_block_uuid_1, ..., harvest_batch_uuid, bag_uuid_1, ...]
- `attributes.notes` carries pick weight per bag.

## 4. QR Binding -- `farmos_asset_link` Module + Fallback (D-04, D-04a)

### Path A: module installed (preferred)

Query existing binding:
```http
GET {FARMOS_URL}/api/asset_link/farmos_asset_link?filter[qr_code]=<value>
```
Response shape (when found):
```jsonc
{ "data": [{ "type": "asset_link--farmos_asset_link",
             "attributes": { "qr_code": "<value>" },
             "relationships": { "asset": { "data": { "type": "asset--fungi", "id": "<uuid>" }}}}]}
```

Create new binding (after asset POST):
```http
POST {FARMOS_URL}/api/asset_link/farmos_asset_link
{
  "data": {
    "type": "asset_link--farmos_asset_link",
    "attributes": { "qr_code": "<value>" },
    "relationships": {
      "asset": { "data": { "type": "asset--fungi", "id": "<asset_uuid>" } }
    }
  }
}
```

### Path B: module NOT installed (D-04a fallback, dev-stack default today)

`farm_id_tag` field is the native fungi-asset field per C2. Query:
```http
GET {FARMOS_URL}/api/asset/fungi?filter[farm_id_tag.qr_code][value]=<value>
```

Bind on create: include in the asset POST payload:
```jsonc
"attributes": {
  "name": "...",
  "farm_id_tag": [{ "qr_code": "<value>" }]
}
```
(field is multi-value list of objects; one entry per QR sticker.)

### Feature detection

At client start-up, probe once:
```http
HEAD {FARMOS_URL}/api/asset_link/farmos_asset_link
```
- `200 / 4xx-not-404` → module present → Path A
- `404` → module absent → Path B globally

Cache the result on the client object. Log one INFO line at startup: `[farmos] asset_link module: <detected|absent, using farm_id_tag fallback>`.

## 5. Photo File-Entity Two-Step Upload (D-05)

### Step 1: POST raw bytes

```http
POST {FARMOS_URL}/api/file/file
Content-Type: application/octet-stream
Content-Disposition: file; filename="signal-attachment-<id>.jpg"
X-CSRF-Token: <csrf>

<binary bytes>
```

Response: `201 Created`, `data.id` = file UUID.

(Note: farmOS native also accepts the JSON:API multipart form at
`/api/log/<type>/<uuid>/relationships/file` but the octet-stream path mirrors the working
Python pattern at `farmos_client.upload_photo` and is one round-trip simpler.)

### Step 2: PATCH the parent log

After the log has been POSTed and we have `log_uuid`:
```http
PATCH {FARMOS_URL}/api/log/observation/<log_uuid>
Content-Type: application/vnd.api+json

{
  "data": {
    "type": "log--observation",
    "id": "<log_uuid>",
    "relationships": {
      "file": { "data": [{ "type": "file--file", "id": "<file_uuid>" }, ...] }
    }
  }
}
```

Alternative: include the file ref in the original POST -- the relationship is already a
JSON:API to-many, so a single-shot POST `relationships.file.data` works as long as the file
UUID is known before the log POST. Plan favors single-shot when possible to reduce round-trips
and partial-failure surface.

### Skip-on-missing (D-05a)

`signal_capture.attachment_paths[]` may have stale references (operator deleted, container
remount). On `fs.access` failure, log a WARN line per draft and continue with text-only commit.
Do NOT fail the whole commit.

### No re-encoding (D-05b)

Stream the bytes as-is. No thumbnailing, no format conversion.

## 6. Idempotency Cache Lookup (D-02 / D-02a / D-02b)

The lookup is a single PG row read, NOT a farmOS query (D-02b is explicit on this).

```sql
SELECT farmos_response, committed_at, commit_failed_reason
  FROM signal_draft
 WHERE id = $1
   AND status IN ('committed', 'commit_failed');
```

If `farmos_response IS NOT NULL` and `status = 'committed'` → no-op success, return cached
`{asset_ids[], log_ids[], file_ids[]}`. If `status = 'commit_failed'` → return cached failure
unless the operator has manually reset to `confirmed` (D-07b).

Atomic write on success: single UPDATE within the commit transaction populates
`farmos_response` and transitions `committing → committed`. No partial cache states.

## 7. Watchdog Design (mirrors Phase 39 watchdog.js exactly)

Phase 39's `confirm/watchdog.js` is the template. Phase 40 commit-watchdog differs only in:

- **Trigger query:** `SELECT * FROM signal_draft WHERE status = 'confirmed' LIMIT N` (N = batch
  cap, e.g. 10 per tick) -- vs Phase 39's nudge / expire candidates.
- **State transition lock:** atomic `UPDATE signal_draft SET status='committing',
  committed_at_attempt=now() WHERE id=$1 AND status='confirmed' RETURNING *`. The RETURNING
  with the conditional WHERE is the lock -- only one worker wins. If rowCount=0, skip
  (another tick or process beat us to it).
- **Retry on transient failures:** per D-07a, 3 attempts with 1s / 4s / 16s backoff on 5xx +
  network errors. 4xx errors are terminal (no retry).
- **Restart safety:** identical to Phase 39 -- first tick fires immediately on alerter start
  before the setInterval is registered.

```
async function tickOnce():
  rows = await commitDb.findConfirmedCandidates(pool, batchCap)  // SELECT ... LIMIT N
  for row of rows:
    lock = await commitDb.acquireCommitLock(pool, row.id)        // atomic transition
    if lock.rowCount === 0: continue                              // another worker won
    try:
      result = await commitChain(row, session, ctx)               // dispatches per log_type
      await commitDb.markCommitted(pool, row.id, result)          // populates farmos_response
      await auditLogger.logCommit('commit_success', row, result)
    catch (e):
      if isTransient(e) && row.retries < 3:
        await commitDb.requeueForRetry(pool, row.id, backoffSec)  // back to 'confirmed'
        await auditLogger.logCommit('commit_attempt_retry', row, e)
      else:
        await commitDb.markFailed(pool, row.id, e.message)
        await auditLogger.logCommit('commit_failed', row, e)
```

### Retry encoding

Two options for retry persistence:
- **Option A (simple):** new column `commit_attempt_count int default 0` on signal_draft.
  Incremented per attempt; on failure if < 3, reset status to `confirmed`, leave count.
- **Option B (event-stream):** count `commit_attempt` events in `signal_draft_event`.

Plan chooses **Option A** -- one extra integer column, no event-stream replay required for
the hot decision path. Event log still records every attempt for the audit trail.

## 8. Structured Audit Log (D-06)

One JSONL line per commit attempt to alerter stdout via the existing alerter logger
(`logger.info` with structured payload; existing alerter logger already passes objects through
to JSON-encoded stdout).

Schema:
```jsonc
{
  "ts": "2026-05-13T12:34:56.789Z",
  "event": "commit_success" | "commit_failed" | "commit_attempt_retry" | "commit_idempotent_noop",
  "draft_id": "abcdef...",
  "farmer": "+59891840205",            // sender_e164
  "log_type": "seeding",
  "asset_ids": ["uuid-1", "uuid-2"],
  "log_ids":   ["uuid-3"],
  "file_ids":  ["uuid-4"],
  "farmos_url": "http://10.68.155.50:18080",
  "http_status": 201,                  // last HTTP status from chain
  "latency_ms": 432,
  "attempt": 1,                        // for retry events
  "reason": "..."                      // failure events
}
```

Also append to `signal_draft_event` (table from Phase 39) for SQL-side audit recipes:

```sql
-- D-06a canonical recipe (document in 40-RUNBOOK.md):
SELECT id, farmos_person, log_type, farmos_response, committed_at
  FROM signal_draft
 WHERE status = 'committed'
   AND committed_at > NOW() - INTERVAL '24 hours'
 ORDER BY committed_at DESC;
```

## 9. Status Lifecycle (D-07)

```
                Phase 39 seam               Phase 40 owns
needs_review --> confirmed --> committing --> committed
                                          \-> commit_failed
```

ALTER additions to `signal_draft`:
- `farmos_response jsonb`
- `committed_at timestamptz`
- `commit_failed_reason text`
- `commit_attempt_count int default 0`
- `committed_at_attempt timestamptz` (set when entering `committing`; lets watchdog detect
  stuck `committing` rows after a crash and re-arm them)

Stale-`committing` recovery: if `status='committing' AND committed_at_attempt < now() -
COMMIT_LOCK_STALE_MIN` (default 5min), the watchdog forcibly transitions back to `confirmed`
on the next tick and logs a WARN. This handles the alerter-crashed-mid-commit case without
manual intervention.

## 10. Test Strategy (D-08 + D-08a + D-08b)

### Unit tests (mocked fetch)

Each module independently tested with `fetch` stubbed:
- `client.test.js` -- auth flow, CSRF header propagation, 401-retry-once
- `qr.test.js` -- feature-detection branch, asset_link path, farm_id_tag fallback path
- `files.test.js` -- octet-stream upload, skip-on-missing
- `commit-seeding.test.js` and one per B7 type -- payload shape assertion
- `commit-router.test.js` -- log_type dispatch + unsupported_log_type guard
- `commit-watchdog.test.js` -- mirrors Phase 39 watchdog.test.js cases

### Integration tests (live dev-farmOS at :18080)

`integration.test.js` against the real dev container. Skips with `it.skip` if
`FARMOS_INTEGRATION=0`. Each B7 log type gets one end-to-end fixture: insert a
confirmed draft, run the commit chain, assert via `GET /api/asset/fungi/<id>` and
`GET /api/log/<type>/<id>` that the entities exist with the expected shape.

### Real-prod fixture (D-08a ship gate)

One fixture sourced from `/mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/`,
PII-redacted to `+15550001234` per Phase 39 Plan 07 convention. Asserts an actual paper-log
inoc draft commits a sterilization-batch + block + seeding log to dev-farmOS. This is the
must-PASS gate -- curated-only PASS is INSUFFICIENT.

### Idempotency regression (D-08b)

Same fixture committed twice. Second call: no farmOS POST issued (asserted by intercepting
fetch). `farmos_response` unchanged. Asset count via GET unchanged.

## 11. Compose env passthrough (memory rule)

`FARMOS_URL`, `FARMOS_USERNAME`, `FARMOS_PASSWORD` are already wired into the `farmos-agent`
Python service block. The alerter service block in `docker-compose.override.yml` (line 62+)
must list them in its `environment:` block -- the agent code reads `process.env.FARMOS_URL`,
so the .env value never reaches the container without the explicit passthrough line. New
knobs introduced by Phase 40 (all OPTIONAL with defaults):

- `FARMOS_URL` (default `http://10.68.155.50:18080` for dev)
- `FARMOS_USERNAME`, `FARMOS_PASSWORD` (no defaults; required at runtime)
- `COMMIT_WATCHDOG_INTERVAL_MS` (default 30000)
- `COMMIT_WATCHDOG_BATCH_CAP` (default 10)
- `COMMIT_RETRY_MAX` (default 3)
- `COMMIT_RETRY_BACKOFF_MS` (default `1000,4000,16000` csv)
- `COMMIT_LOCK_STALE_MIN` (default 5)
- `FARMOS_INTEGRATION` (default 0 in CI; 1 to run live-farmOS integration tests)

## 12. Module Layout (final)

```
src/agents/alerter/src/farmos/
  index.js              -- barrel export
  client.js             -- auth + fetch wrapper + retry + feature-detect
  assets.js             -- create-fungi-asset helpers (B1..B4)
  logs.js               -- create-log helpers (B7.1..B7.5)
  qr.js                 -- asset_link resolution + farm_id_tag fallback
  files.js              -- two-step file upload
  commits/
    commit-router.js    -- dispatch on draft.log_type
    commit-seeding.js
    commit-activity.js
    commit-input.js
    commit-observation.js
    commit-harvest.js
  commit-db.js          -- migration + lock + state transitions (mirror confirm-db.js)
  commit-watchdog.js    -- in-process poller (mirror confirm/watchdog.js)
  audit-logger.js       -- structured JSONL emitter
```

## 13. Open questions resolved during research

- **Q:** Should `commit-*` modules sit under `commits/` subdir or flat? **A:** subdir. Five
  files plus router is enough to warrant the namespace (CONTEXT D-03 left this to discretion).
- **Q:** Single-shot vs two-step file upload? **A:** Try single-shot in the log POST
  (`relationships.file.data`); fall back to PATCH if a future farmOS version rejects. Both
  paths implemented; single-shot is the hot path.
- **Q:** Asset lookup by name -- safe? **A:** Yes for `BATCH-*` parent resolution. Use
  `filter[name][value]=BATCH-...` JSON:API filter. Cache result on the client object for the
  duration of one commit chain.
- **Q:** What if `farmos_asset_link` probe times out (network flap)? **A:** Treat as `absent`
  and use fallback for that session. Re-probe on next alerter restart.
- **Q:** Species taxonomy term UUIDs -- do we look up by name on every commit? **A:** Yes,
  with a per-process LRU cache keyed by species short-code. The locked vocabulary from Phase
  38 (`DT`, `PE`, etc.) is small enough that a tiny in-memory cache (10 entries) covers it.
- **Q:** Commit-watchdog batch ordering -- ORDER BY confirmed_at ASC? **A:** Yes. FIFO is the
  least-surprising default. Document in 40-RUNBOOK.md.

---

*Phase: 40-farmos-write-path*
*Research compiled: 2026-05-13 (in-context, no subagent fan-out)*
