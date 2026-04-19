# Phase 21: Camera history continuous persistence — Research

**Researched:** 2026-04-19
**Domain:** Node.js bridge persistence, TimescaleDB hypertable + retention, filesystem atomicity, read-only JSON endpoint, health panel extension
**Confidence:** HIGH (all claims grounded in existing repo code or verified npm registry / TimescaleDB docs)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 Persister architecture:** The bridge (`src/mission-control/bridge/src/index.js`) is the persister. Keep a low-rate ROS subscription to `/fc1/camera/compressed` alive **even when `mjpegClients.size === 0`**. `ensureCameraSubscribed()` / `maybeCameraUnsubscribe()` are modified so unsubscribe only happens when there is neither a viewer *nor* a pending history capture. No new container, no new service.
- **D-02 Idle cadence:** 1 frame / 5 minutes (~9 MB/day, ~270 MB/month).
- **D-05 Viewer cadence:** Same 5-minute cadence — persistence is decoupled from viewer presence. Live MJPEG still streams at full rate to viewers; only *persistence* is capped at 1/5min.
- **D-03 Snapshots hypertable columns (LOCKED):**
  `captured_at TIMESTAMPTZ NOT NULL`,
  `camera_id TEXT NOT NULL`,
  `file_path TEXT NOT NULL`,
  `bytes INTEGER NOT NULL`,
  `source TEXT NOT NULL CHECK (source IN ('viewer','idle','manual'))`,
  `fps NUMERIC`.
  Hypertable on `captured_at`, chunk interval 1 day. Index on `(camera_id, captured_at DESC)`. Files on disk at `/data/snapshots/{camera_id}/YYYY-MM-DD/`. DB is index, not blob storage. Join to RH/CO2/temperature via existing `telemetry.time` — no denormalization.
- **D-04 Retention:** 365 days. Prune files + rows atomically. Pruning only starts once system has been writing for >30 days.
- **D-06a** `GET /camera/history?from=&to=&camera_id=` returns `[{captured_at, camera_id, file_path, bytes, source, fps}]` ordered by `captured_at ASC`, cap ~5000, `has_more` flag.
- **D-06b** `/health` gains `snapshots_last_24h` (count) and `oldest_snapshot_at` (ISO timestamp or null). Phase 16 system-health panel surfaces both.
- **Stall-safety:** No sha256 dedupe this phase. Rely on Phase 14 fix + Phase 16 `last_frame_age_sec`.

### Claude's Discretion

- Exact prune cadence (daily vs hourly) and implementation site (in-process `setInterval` vs docker service vs host cron).
- Shape of the health chip in the Phase 16 panel.
- Migration handling for pre-phase `/data/snapshots/` files (backfill vs start-from-now). **Researcher recommends below; planner locks.**
- Whether to add a `CAMERA_ID` env var / config layer now vs Phase 999.6 (env var already exists — default `fc1`).
- Pagination details for `/camera/history` (cursor vs offset, max page size).

### Deferred Ideas (OUT OF SCOPE)

- Timeline scrubber UI (Phase 22).
- ffmpeg time-lapse composition (Phase 23).
- ML vision events / ComfyUI (Phase 24).
- Pi-side edge-buffering / offline resilience (Phase 999.1).
- Multi-chamber `camera_id` wiring (Phase 999.6 — schema supports it, wiring deferred).
- Dedicated archivist subscriber on elder-plops.
- sha256 dedupe on snapshots.
- BLOB-in-DB storage (explicitly rejected — files on disk, DB as index).
</user_constraints>

## Project Constraints (from CLAUDE.md)

- Live compose is `/docker-compose.yml` + `/docker-compose.override.yml` at repo root; `src/docker-compose.yml` is deprecated for deploy.
- Bridge rebuilds MUST use `docker-compose up -d --build bridge` — compose pins build context but not image tag; `up -d` alone reuses cached image.
- Required `.env` at repo root: `TIMESCALE_PASSWORD`, `CORS_ORIGIN`.
- Environment-variable config (not YAML) for bridge-only knobs: `SNAPSHOT_DIR`, `SNAPSHOT_INTERVAL_MIN`, `CAMERA_ID`.
- Verify against **runtime** compose (not `src/docker-compose.yml`) during verification (Phase 07 regression lesson).

## Summary

Phase 21 is a focused bridge-only change. Every load-bearing primitive already exists in `src/mission-control/bridge/src/index.js`: a `pg.Pool`, a hypertable-init helper (`initDb`), a snapshot writer (`saveSnapshot`), a viewer-gated ROS subscription (`ensureCameraSubscribed`/`maybeCameraUnsubscribe`), a snapshot timer (`setInterval`, line 481), and a `/health` endpoint (line 170). The Phase 18 `/farmer/summary` endpoint is the exact stylistic template for `GET /camera/history`.

The work is four small edits and one new endpoint: (1) relax the subscribe-invariant so a singleton "history pseudo-subscriber" keeps the ROS subscription alive, (2) change `SNAPSHOT_INTERVAL_MIN` default from 15 → 5 and tag each write with a `source` value, (3) add a `snapshots` hypertable and INSERT inside `saveSnapshot`, (4) add an atomic file+row prune running in-process on a daily `setInterval`, (5) add `GET /camera/history` and extend `/health`. The frontend plugin at `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js:~497+` already polls `/health`; the two new fields slot into that existing loop.

**Primary recommendation:** Modify `maybeCameraUnsubscribe()` to also check a new `persistenceKeepalive` flag that is set permanently true at startup (once ROS/DB are ready). Keep the existing viewer-path untouched — Phase 12's invariant is preserved for viewers, the new path is purely additive. Use `setInterval` for both the 5-min snapshot tick (already exists) and the daily retention prune (new). No `node-cron` — the bridge is a single always-on process and an in-process interval is the simplest thing that composes with the `/data` volume mount. Recommend **start-from-now** for backfill: the existing `/data/snapshots/` tree has per-farmer-session gaps (see FINDINGS-2026-04-17) and indexing it gives a false-continuous timeline; documenting the migration cutover timestamp is simpler than reconstructing provenance.

## Phase Requirements

None mapped (phase_req_ids=null). Use CONTEXT.md D-01..D-06b as the requirement surface. Each maps to tests in the Validation Architecture section below.

## Standard Stack

### Core (already in the bridge — DO NOT introduce new deps)

| Library | Version | Purpose | Why Standard | Provenance |
|---------|---------|---------|--------------|------------|
| `pg` | 8.20.0 | Postgres/Timescale client (via `pg.Pool`) | Already pooled and used for `telemetry` INSERT/SELECT | [VERIFIED: package.json + `npm view pg version`] |
| `express` | 5.2.1 | HTTP routing for `/health`, `/farmer/summary`, `/history`, `/camera/*` | Already serving all bridge endpoints | [VERIFIED: package.json + npm registry] |
| `ws` | 8.16.0 | Live telemetry WS broadcast | Not involved in Phase 21 but present | [VERIFIED: package.json] |
| `rclnodejs` | 1.9.0 | ROS2 subscription runtime | Owns the `/fc1/camera/compressed` subscription we're modifying | [VERIFIED: package.json] |
| Node `fs` (built-in) | — | Snapshot writes + retention unlink | Already used in `saveSnapshot` | [VERIFIED: index.js:114] |
| Node `setInterval` (built-in) | — | Snapshot tick (line 481) and new retention tick | Composes with the always-on bridge process; no extra process supervision | [VERIFIED: index.js:481] |

### Deliberately NOT adding

| Candidate | Why skip |
|-----------|----------|
| `node-cron` 4.2.1 | Latest is current [VERIFIED: `npm view node-cron version`], but adds a dep for one daily timer. `setInterval(prune, 24 * 3600 * 1000)` inside the existing bridge process is simpler and has the same durability properties (bridge restart resets either). |
| Host `cron` / separate docker service | Violates D-01 ("no new container, no new service"). Also fragments filesystem ownership of `/data/snapshots/`. |
| `better-sqlite3` / other lightweight DB | Timescale hypertable is already the pattern for `telemetry`; reusing it is D-03. |
| sha256-hash dedupe library | Explicitly excluded by CONTEXT ("stall-safety carry-over"). |

**Installation:** None. Zero new dependencies.

**Version verification (run 2026-04-19):**
```
npm view pg version       → 8.20.0 ✓ matches
npm view express version  → 5.2.1  ✓ matches
npm view node-cron version → 4.2.1 (rejected — see table)
```

## Architecture Patterns

### Recommended file layout (additive only)

```
src/mission-control/bridge/src/
├── index.js                    # all changes land here — single-file bridge convention
└── (no new files)              # if the planner wants to split, snapshots.js is the natural seam
```

The bridge is a single-file program by convention. Don't split for this phase unless `index.js` grows past ~800 lines post-edit; the Phase 16 / Phase 18 precedent is to keep adding to `index.js`.

### Pattern 1: Hypertable init mirrors `telemetry` exactly

**What:** Add to `initDb()` (index.js:121) — same three-statement shape as the existing `telemetry` hypertable.

**Source:** `src/mission-control/bridge/src/index.js:123-139` and TimescaleDB `create_hypertable` docs.

```javascript
// Source: mirrors index.js:123-139 telemetry pattern (in-repo) + TimescaleDB create_hypertable
await pool.query(`
    CREATE TABLE IF NOT EXISTS snapshots (
        captured_at TIMESTAMPTZ NOT NULL,
        camera_id   TEXT        NOT NULL,
        file_path   TEXT        NOT NULL,
        bytes       INTEGER     NOT NULL,
        source      TEXT        NOT NULL CHECK (source IN ('viewer','idle','manual')),
        fps         NUMERIC
    )
`);
await pool.query(`
    SELECT create_hypertable('snapshots', 'captured_at',
        if_not_exists        => TRUE,
        chunk_time_interval  => INTERVAL '1 day'
    )
`);
await pool.query(`
    CREATE INDEX IF NOT EXISTS idx_snapshots_camera_captured
    ON snapshots (camera_id, captured_at DESC)
`);
```

**Rationale:** `if_not_exists => TRUE` + `CREATE INDEX IF NOT EXISTS` = idempotent startup, safe on every bridge restart. Chunk interval 1 day matches D-03 and matches the existing `telemetry` hypertable — ops parity.

**Note on `file_path` uniqueness:** D-03 does NOT mandate a UNIQUE constraint. Because `saveSnapshot` filenames include `new Date().toISOString()` down to milliseconds (index.js:112), collisions are impossible within a single bridge process. A future dedupe effort (deferred) can add a UNIQUE index later without migration pain.

### Pattern 2: Persistence pseudo-subscriber

**What:** Relax the unsubscribe guard so a singleton "history" consumer keeps the subscription alive.

**Minimal edit** (preserves Phase 12 viewer semantics):

```javascript
// Add at module scope:
let persistenceKeepalive = false;  // flipped true after initDb + ROS ready

// Unchanged: ensureCameraSubscribed() — caller set stays the same
// Changed: maybeCameraUnsubscribe()
function maybeCameraUnsubscribe() {
    if (mjpegClients.size > 0 || persistenceKeepalive || cameraSubscription === null) return;
    rosNode.destroySubscription(cameraSubscription);
    cameraSubscription = null;
    console.log('[camera] unsubscribed from /fc1/camera/compressed');
}

// In the rclnodejs.init().then() block, after initDb + node.spin() setup:
persistenceKeepalive = true;
ensureCameraSubscribed();  // prime the subscription immediately at startup
```

**Why this shape:** The existing viewer code-path (`/camera/mjpeg` route, index.js:284) calls `ensureCameraSubscribed()` on connect and `maybeCameraUnsubscribe()` on disconnect — it still works unchanged. The only behavioural change is that unsubscribe now has an extra guard. Phase 12 viewer UAT is unaffected. This is the smallest diff that satisfies D-01.

### Pattern 3: Tag snapshots at write-time

**What:** `saveSnapshot()` needs a `source` value ('viewer' | 'idle'). Determine from `mjpegClients.size`:

```javascript
async function saveSnapshot() {
    if (!latestFrame) return;
    const capturedAt = new Date();
    const bytes = latestFrame.length;
    const source = mjpegClients.size > 0 ? 'viewer' : 'idle';
    // ... existing dir + filename logic unchanged ...
    const filePath = path.join(dir, filename);

    // Write file first; only INSERT if write succeeds
    fs.writeFile(filePath, latestFrame, async (err) => {
        if (err) {
            console.error('[camera] snapshot write failed:', err.message);
            return;
        }
        if (!dbReady) return;
        try {
            await pool.query(
                `INSERT INTO snapshots (captured_at, camera_id, file_path, bytes, source, fps)
                 VALUES ($1, $2, $3, $4, $5, $6)`,
                [capturedAt, CAMERA_ID, filePath, bytes, source, null]
            );
        } catch (e) {
            console.error('[snapshots] insert failed:', e.message);
            // File exists on disk but row missing — self-heals on next retention sweep
            // (an orphan file older than retention will be deleted; planner may add a
            // reconciliation sweep in a future phase if orphans become common).
        }
    });
}
```

**fps value:** CONTEXT D-03 lists `fps NUMERIC` (nullable). There is no viewer-fps tracked in the bridge today (fc_camera owns its publish rate). Pass `null` — planner can decide to read from a future `fc_camera_fps` topic later. Document this in PLAN.

### Pattern 4: Atomic file+row prune

**What:** Daily `setInterval`, runs inside the bridge container (same `/data/snapshots` mount — required per D-01 and the "Established Patterns" note in CONTEXT).

```javascript
const RETENTION_DAYS = parseInt(process.env.RETENTION_DAYS || '365', 10);
const RETENTION_GRACE_DAYS = parseInt(process.env.RETENTION_GRACE_DAYS || '30', 10);
const PRUNE_INTERVAL_MS = 24 * 3600 * 1000;

async function pruneSnapshots() {
    if (!dbReady) return;

    // D-04 grace: do not prune until system has been writing for >30 days
    const ageCheck = await pool.query(
        `SELECT EXTRACT(EPOCH FROM (NOW() - MIN(captured_at)))/86400 AS days
         FROM snapshots`
    );
    const oldestDays = ageCheck.rows[0].days;
    if (oldestDays === null || oldestDays < RETENTION_GRACE_DAYS) {
        console.log(`[retention] skip — oldest snapshot only ${oldestDays} days old`);
        return;
    }

    // Select expired rows (don't DELETE yet — need file_path first)
    const cutoff = new Date(Date.now() - RETENTION_DAYS * 86400 * 1000);
    const expired = await pool.query(
        `SELECT file_path, captured_at FROM snapshots WHERE captured_at < $1 LIMIT 10000`,
        [cutoff]
    );

    // Atomic per-row: unlink file, then DELETE row. If unlink fails with ENOENT
    // (file already gone), treat as success and delete the row. Any other error
    // leaves BOTH file and row in place — next run retries.
    let deleted = 0;
    for (const row of expired.rows) {
        try {
            await fs.promises.unlink(row.file_path);
        } catch (e) {
            if (e.code !== 'ENOENT') {
                console.error(`[retention] unlink failed for ${row.file_path}:`, e.message);
                continue;  // skip; row stays, retry tomorrow
            }
        }
        await pool.query(`DELETE FROM snapshots WHERE file_path = $1`, [row.file_path]);
        deleted++;
    }
    console.log(`[retention] pruned ${deleted} snapshots older than ${RETENTION_DAYS} days`);
}

setInterval(pruneSnapshots, PRUNE_INTERVAL_MS);
// Also run once on startup, after a small delay to let initDb finish:
setTimeout(pruneSnapshots, 60 * 1000);
```

**Atomicity claim:** This is NOT transactional atomicity across filesystem + DB (impossible without 2PC). It is **idempotent eventual consistency**: if unlink succeeds and DELETE fails, next run's unlink returns ENOENT and DELETE retries. If unlink fails transiently, neither happens and the row is retried. The `ENOENT-treated-as-success` path guarantees forward progress.

**Why per-row loop instead of bulk DELETE + bulk unlink:** A bulk `DELETE WHERE captured_at < cutoff` followed by a directory walk leaks rows if the process crashes between steps. The row-at-a-time loop narrows the crash window to a single row.

**Empty-directory cleanup:** Optional. After unlink, the date-bucketed dir may be empty. Not load-bearing for Phase 22 (scrubber hits the index, not the filesystem). Planner's discretion — a simple `fs.rmdir` with `ENOTEMPTY`-ignore is ~3 lines.

### Pattern 5: `GET /camera/history` — mirror `/farmer/summary` style

**What:** Follow index.js:195 conventions — query-param validation, CORS already handled by the global middleware (index.js:159-166), `res.json(...)` with stable shape.

**Recommendation: offset pagination (not cursor).**

- Cursor pagination (keyset on `captured_at`) is a better choice at scale, but Phase 22's scrubber will request a bounded window `(from, to)` and almost always fit within one cap. The cap is a safety-valve, not a primary pagination axis.
- `has_more: true` in the response tells the scrubber "narrow your window"; it does not need `next_cursor` to do that.
- Offset pagination is also consistent with the existing `/history/:topic` endpoint (index.js:233) which caps at 30-day range rather than paginating.

```javascript
const HISTORY_MAX_ROWS = 5000;
const HISTORY_MAX_RANGE_MS = 30 * 24 * 3600000;  // match /history/:topic

app.get('/camera/history', async (req, res) => {
    const from = parseInt(req.query.from, 10);
    const to   = parseInt(req.query.to, 10);
    const cameraId = (req.query.camera_id || CAMERA_ID).toString();

    if (isNaN(from) || isNaN(to)) {
        return res.status(400).json({ error: 'from and to query params required (ms epoch)' });
    }
    if (to < from) {
        return res.status(400).json({ error: 'to must be >= from' });
    }
    if (to - from > HISTORY_MAX_RANGE_MS) {
        return res.status(400).json({ error: 'Max range is 30 days' });
    }
    // Allowlist camera_id against env (prevents SQL injection via param — T-07-04 style)
    // Until Phase 999.6, only CAMERA_ID is valid. Extensible to an env allowlist later.
    if (cameraId !== CAMERA_ID) {
        return res.status(400).json({ error: 'Invalid camera_id' });
    }
    if (!dbReady) {
        return res.status(503).json({ error: 'Database not available' });
    }

    try {
        // LIMIT + 1 trick: fetch cap+1, if we got cap+1 rows then has_more=true, drop the extra
        const result = await pool.query(
            `SELECT captured_at, camera_id, file_path, bytes, source, fps
             FROM snapshots
             WHERE camera_id = $1
               AND captured_at >= $2
               AND captured_at <= $3
             ORDER BY captured_at ASC
             LIMIT $4`,
            [cameraId, new Date(from), new Date(to), HISTORY_MAX_ROWS + 1]
        );
        const hasMore = result.rows.length > HISTORY_MAX_ROWS;
        const rows = hasMore ? result.rows.slice(0, HISTORY_MAX_ROWS) : result.rows;
        res.json({
            camera_id: cameraId,
            from, to,
            count: rows.length,
            has_more: hasMore,
            rows: rows.map(r => ({
                captured_at: r.captured_at.toISOString(),
                camera_id: r.camera_id,
                file_path: r.file_path,
                bytes: r.bytes,
                source: r.source,
                fps: r.fps === null ? null : parseFloat(r.fps)
            }))
        });
    } catch (err) {
        console.error('[snapshots] history query failed:', err.message);
        res.status(500).json({ error: 'Query failed' });
    }
});
```

**Why `captured_at` is ISO string, not ms epoch:** The existing `/farmer/summary` uses ms-epoch timestamps, but `/history/:topic` uses `utc` ms-epoch — there's no single convention. For `/camera/history` ISO-8601 is better: Phase 22's scrubber will render these as labels, and Postgres returns `TIMESTAMPTZ` as a JS `Date` naturally. **Planner: this is a call to make and document — both shapes are defensible.**

### Pattern 6: `/health` extension

**What:** Add two fields to the existing `/health` handler (index.js:170). Compute on-request via cheap aggregate queries. Cache if the planner measures hot-path latency; otherwise keep simple.

```javascript
// Inside app.get('/health', async (req, res) => { ... })
let snapshotsLast24h = null;
let oldestSnapshotAt = null;
if (dbReady) {
    try {
        const [countRow, oldestRow] = await Promise.all([
            pool.query(`SELECT COUNT(*)::int AS n FROM snapshots
                        WHERE captured_at > NOW() - INTERVAL '24 hours'`),
            pool.query(`SELECT MIN(captured_at) AS oldest FROM snapshots`)
        ]);
        snapshotsLast24h = countRow.rows[0].n;
        oldestSnapshotAt = oldestRow.rows[0].oldest === null
            ? null : oldestRow.rows[0].oldest.toISOString();
    } catch (e) {
        // swallow — /health must never 5xx on sub-query failure; leave fields null
        console.error('[health] snapshots stats failed:', e.message);
    }
}
// ...then add snapshots: { last_24h: snapshotsLast24h, oldest_at: oldestSnapshotAt } to the JSON
```

**Note:** The current `/health` handler is **synchronous** (`(req, res) => ...`). Adding `await` means changing the signature to `async`. Simple edit; express 5 handles async handlers natively.

**Frontend plugin diff:** `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js:~497+` already polls `/health` in a `fetch().then().catch()` loop. Add two new status lights (or a single "Snapshots" light with a count label) inside the existing `.then(data)` block. Green if `snapshots.last_24h >= expected_floor` (288 = 24h × 12/hr; use 200 as a generous floor to absorb bridge restarts). Red if 0. Grey on `/health unreachable` — same fall-through as existing lights.

### Anti-Patterns to Avoid

- **Synchronous `fs.writeFileSync` in the snapshot path.** The current `saveSnapshot` already uses async `fs.writeFile`; keep it that way. Sync writes would block the ROS subscription callback thread.
- **`DELETE` before `unlink`.** Loses the `file_path` you need to unlink. Always SELECT → unlink → DELETE.
- **Transactional fantasy.** No single transaction spans Timescale + filesystem. Design for eventual consistency with idempotent retries.
- **Reading files on retention tick to sanity-check.** `fs.existsSync` + unlink races with writers. `unlink` + ignore-ENOENT is race-free.
- **Computing `snapshots_last_24h` from filesystem `readdir`.** Use the DB — that's literally why it's indexed.
- **Adding `node-cron` for one interval.** Violates simplicity-first; `setInterval` is adequate for a daily tick on an always-on process.
- **Removing the snapshot-interval env var.** Keep `SNAPSHOT_INTERVAL_MIN` as the tunable. Change its default from 15 → 5 (in docker-compose.yml line 24) rather than hardcoding. This preserves the existing operator muscle-memory.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Time-bucketed retention | Custom "list dirs, parse filenames, delete older than X" | Query `snapshots WHERE captured_at < cutoff` | The index is authoritative; filesystem is a follower |
| Chunk management on hypertable | Manual partition DDL | `create_hypertable` | Timescale owns chunking |
| Pagination token encoding | Cursor serialization + HMAC | Offset cap with `has_more` | Scrubber uses bounded windows; cursor is over-engineering |
| JSON schema validation | `ajv` or custom validators | `parseInt` + allowlist (matches existing `/history/:topic` pattern index.js:237-251) | Query-string only; 4 scalars, trivially validated inline |
| Process supervision for retention | Separate container + docker healthcheck | In-process `setInterval` | D-01 — one process; bridge already always-on |
| HTTP client retry | `got`/`axios` with exponential backoff | N/A | No outbound HTTP in this phase |

**Key insight:** Every primitive this phase needs already exists in the bridge process. The phase is 95% "compose existing primitives" and 5% "one new table + one new endpoint." Resist new-dep temptation.

## Runtime State Inventory

> Phase 21 is additive, not a rename/refactor. This inventory is included for
> completeness of runtime-state impact, not because of string replacement.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Existing `/data/snapshots/{camera_id}/YYYY-MM-DD/*.jpg` tree on elder-plops host (pre-phase files). Count unknown at research time — live disk. | **Recommendation: start-from-now.** The pre-phase tree has per-viewer-session gaps (FINDINGS-2026-04-17 Issue 2). Indexing it creates a false-continuous timeline where "nobody watched Sat night" looks like a dense stretch. If the planner disagrees, backfill is a one-shot script: `fs.readdir` the tree + `stat` each file → INSERT rows with `source='idle'` and `bytes` from `stat.size`. File timestamps are in the filename (ISO). |
| Live service config | `docker-compose.yml` line 24: `SNAPSHOT_INTERVAL_MIN=15` — needs to change to `5`. `docker-compose.override.yml`: no snapshot-related env. No changes needed to override. | Edit `docker-compose.yml` line 24; no-op to override |
| OS-registered state | None — bridge is a docker service, not a systemd unit on the host. elder-plops does have a `fc-update.service` (git pull on boot) but it's deploy-only, not service config. | None |
| Secrets/env vars | `TIMESCALE_PASSWORD` (reused), `CAMERA_ID` (reused, default `fc1`), `SNAPSHOT_DIR` (reused, `/data/snapshots`). New optional: `RETENTION_DAYS` (default 365), `RETENTION_GRACE_DAYS` (default 30). All read via `process.env.*`. | None — just document new optional env vars in compose comment |
| Build artifacts / installed packages | Bridge image must be rebuilt: `docker-compose up -d --build bridge`. No schema migration tool — `initDb()` handles `CREATE TABLE IF NOT EXISTS` + `create_hypertable(if_not_exists)` idempotently on startup. Existing `timescale-data` named volume (docker-compose.yml:62) persists the table across bridge rebuilds. | Rebuild bridge. No DB data migration |

**Backfill recommendation rationale:** The farmer-stated v1.4 goal is "continuous timeline." Backfilling discontinuous pre-phase data **defeats** that goal visually — a scrubber would show dense-when-watched regions next to continuous-from-now regions, and the farmer has to remember which bands are which. Start-from-now with a documented cutover timestamp is cleaner. If the planner chooses backfill anyway, mark every backfilled row `source='viewer'` (accurate) so Phase 22 can style pre-phase bands differently.

## Common Pitfalls

### Pitfall 1: Pseudo-subscriber deadlock with fc_camera idle stall
**What goes wrong:** fc_camera stalls in idle (Phase 14 scenario). Bridge stays subscribed (because of `persistenceKeepalive`) but `latestFrame` never updates. `saveSnapshot` re-writes the same stale buffer every 5 minutes — a Phase-14-style regression but silent in the DB because rows keep landing.
**Why it happens:** `saveSnapshot` doesn't check frame freshness before writing.
**How to avoid:** Honor `isFrameStale()` (already exists, index.js:47) in `saveSnapshot`. If stale, log and skip — DO NOT write. Phase 16's `last_frame_age_sec` will turn the panel red and the `snapshots_last_24h` will visibly drop. That IS the intended regression signal (D-06b).
**Warning signs:** `snapshots_last_24h` drops below ~100 in a 24h window with no bridge restart.

### Pitfall 2: Retention prune on a half-populated install
**What goes wrong:** Fresh install, 5 days of history. Operator misconfigures `RETENTION_DAYS=3`. Prune nukes 40% of the history.
**Why it happens:** No safety net around small retention values.
**How to avoid:** D-04 30-day grace is the primary guard. Additionally, clamp: `if (RETENTION_DAYS < 30) { console.warn('[retention] RETENTION_DAYS too small, forcing 30'); RETENTION_DAYS = 30; }` Belt-and-suspenders but cheap.
**Warning signs:** `oldest_snapshot_at` value regresses (gets more recent) unexpectedly after a prune run.

### Pitfall 3: `/camera/history` range abuse
**What goes wrong:** A client requests `from=0&to=Date.now()` and expects all history. Query scans 365 days of rows, returns 5000, timeline scrubber gives up.
**Why it happens:** Unbounded range seems reasonable from a client UX perspective.
**How to avoid:** 30-day max range (matches `/history/:topic` precedent, index.js:248). Return 400 with a clear error message. Scrubber UI (Phase 22) is responsible for windowing.
**Warning signs:** 400 responses spiking in bridge logs.

### Pitfall 4: Timescale chunk bloat on 365-day retention
**What goes wrong:** With chunk_time_interval 1 day × 365 days = 365 chunks accumulating. Timescale handles this fine, but `pg_dump`/vacuum windows grow.
**Why it happens:** No `drop_chunks` / compression policy configured.
**How to avoid:** `DELETE`-based retention (this phase's pattern) causes chunk bloat over time. For v1.4 the volume is trivial (365 chunks × ~288 rows/day = ~105k rows total). **Defer** automatic compression and `drop_chunks` until Phase 24 when ML events may add 10×+ volume. Document this in PLAN as a known deferral.
**Warning signs:** `pg_total_relation_size('snapshots')` exceeds ~100 MB (won't happen at Phase 21 volumes).

### Pitfall 5: Missing `await` on `initDb` causing snapshots-table-before-telemetry-race
**What goes wrong:** `initDb` in the existing startup sequence is already `await`ed (index.js:378). Adding the `snapshots` hypertable *inside* `initDb` before setting `dbReady=true` is safe. Adding it *after* is not.
**How to avoid:** Extend `initDb()` in-place, not as a separate function call. The first `saveSnapshot` tick fires after `setInterval(saveSnapshot, ...)` at line 482, which is after `dbReady` is set — so the table is guaranteed to exist by first write.
**Warning signs:** `[snapshots] insert failed: relation "snapshots" does not exist` in logs at startup. If you see it, the ordering is wrong.

### Pitfall 6: `captured_at` clock source
**What goes wrong:** `new Date()` at INSERT time vs the ROS message header stamp. Bridge clock and fc1 Pi clock drift via NTP; they can differ by seconds.
**Why it matters:** Phase 22 will join `snapshots.captured_at` to `telemetry.time` to overlay env data. Both are currently `new Date()` at bridge INSERT time (telemetry: index.js:363). **Consistent-but-wrong** beats **mixed sources** — use bridge clock for both, which is what the `saveSnapshot` pattern in Pattern 3 already does.
**How to avoid:** Explicit: use `new Date()` at the moment of write decision, not at ROS message receive time. Document this in PLAN.
**Warning signs:** Phase 22 scrubber off by 1-5s from sensor graph — the fix is at Phase 22 time, not here.

## Code Examples

See Patterns 1–6 above — all code is grounded in and traceable to existing `src/mission-control/bridge/src/index.js` primitives.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 15-min viewer-gated snapshots | 5-min always-on + tag source | This phase | ~18 MB/day → consistent; ~9 MB/day net change vs. "always active" |
| `/camera/snapshot` one-shot | `/camera/history` bounded query | This phase | Scrubber becomes possible |
| 2-hour frame staleness window (FRAME_MAX_AGE_MS, index.js:45) | Unchanged | — | Still appropriate — `isFrameStale()` protects `saveSnapshot` |

**Deprecated/outdated in repo context:**
- `SNAPSHOT_INTERVAL_MIN=15` default in docker-compose.yml → will be `5` after this phase
- `src/docker-compose.yml` — already deprecated per CLAUDE.md; live compose is repo root

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Offset pagination is acceptable for Phase 22's scrubber [ASSUMED] | Pattern 5 | LOW — cursor can be added later with a backwards-compat `next_cursor` field; clients ignoring unknown fields keep working |
| A2 | `start-from-now` is preferred over backfill [ASSUMED from farmer "continuous timeline" framing] | Runtime State Inventory | MEDIUM — if farmer prefers "see every frame we ever captured," planner can flip to backfill with the script sketched above |
| A3 | `fps NUMERIC` can be `null` for idle-cadence snapshots [ASSUMED — D-03 column is nullable] | Pattern 3 | LOW — schema allows it; cosmetic only |
| A4 | Phase 16 plugin.js can extend its `/health` fetch loop with zero structural change [ASSUMED from grep-level inspection] | Pattern 6 | LOW — planner verifies during UI task |
| A5 | Row-at-a-time DELETE loop at retention-time is fast enough for the retention cadence (max ~288 rows/day × oldest day = trivially small, but a backfilled install could have N days × 288) [ASSUMED] | Pattern 4 | LOW at Phase 21 volumes; if a future ML phase pushes row counts 10×+, batch deletes are straightforward |
| A6 | No UNIQUE constraint on `file_path` is acceptable [CITED: D-03 does not mandate it, filename includes millisecond ISO timestamp] | Pattern 1 | LOW — if duplicates appear, add a UNIQUE index in a later migration |

## Open Questions (RESOLVED)

1. **Backfill: yes or no?**
   - What we know: pre-phase `/data/snapshots/` tree exists but is discontinuous by design (Phase 12 viewer-gated).
   - What's unclear: farmer's preference for "complete but patchy" vs "continuous from cutover."
   - Recommendation: start-from-now (A2). Planner: raise this with the user if uncertainty remains.
   - **RESOLVED:** No. Start-from-now. Pre-phase `/data/snapshots/` tree left unindexed to preserve continuous-timeline semantics. (Plan 02 has no backfill task.)

2. **Is `camera_id` validation via env (static `fc1`) or a config list?**
   - What we know: Phase 999.6 owns multi-chamber. Schema supports multiple IDs; wiring is discretion (CONTEXT).
   - What's unclear: whether v1.4 will have any other `camera_id` value before Phase 999.6.
   - Recommendation: static equality check against `CAMERA_ID` env var (Pattern 5). Trivial to extend to a list later.
   - **RESOLVED:** Static equality against env `CAMERA_ID`. Allowlist deferred to Phase 999.6. (Implemented in validateHistoryParams in Plan 03.)

3. **`captured_at` response shape: ISO string or ms epoch?**
   - What we know: `/farmer/summary` uses ms epoch for `timestamp`; `/history/:topic` uses ms epoch under key `utc`.
   - What's unclear: whether Phase 22's scrubber prefers one.
   - Recommendation: ISO string for `/camera/history` (new shape, correct default for TIMESTAMPTZ). Planner locks; Phase 22 consumes.
   - **RESOLVED:** ISO string (not ms epoch). Documented in Plan 03 Task 2 /camera/history response.

4. **Empty-date-dir cleanup after prune: ship now or defer?**
   - What we know: `/data/snapshots/fc1/2025-04-19/` directories stay empty after their last file is pruned.
   - What's unclear: disk-inode pressure on elder-plops (negligible at any realistic scale).
   - Recommendation: defer; add a one-liner `fs.rmdir(..., () => {})` ignore-error only if empty-dir accumulation becomes a real concern.
   - **RESOLVED:** Deferred. Not load-bearing for Phase 22. (No cleanup task in Plan 03 retention job.)

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| TimescaleDB | `snapshots` hypertable | ✓ (running as `timescale` service, pg14) | `timescale/timescaledb:latest-pg14` | — |
| `/data/snapshots` host mount | Snapshot file writes | ✓ (mounted via docker-compose.yml:27 and farmos-agent:58) | — | — |
| `pg` Node client | INSERT/SELECT | ✓ (bridge package.json) | 8.20.0 | — |
| `rclnodejs` ROS2 sub | Camera subscription invariant | ✓ | 1.9.0 | — |
| `express` | `/camera/history`, `/health` | ✓ | 5.2.1 | — |
| elder-plops disk | 365 days × 9 MB ≈ 3.3 GB | ✓ (historical: well under existing disk budget; confirm at verification) | — | Lower `RETENTION_DAYS` env |
| Docker compose v2 | Bridge rebuild | ✓ (Phase 11 shipped v2 on elder-plops) | — | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None — phase is entirely bridge-internal.

## Validation Architecture

*nyquist_validation is `true` in config.json — section required.*

### Test Framework

| Property | Value |
|----------|-------|
| Framework | **None currently in the bridge.** `src/mission-control/bridge/` has no `test/` dir, no test script in package.json. |
| Config file | None |
| Quick run command | *Wave 0 must introduce* |
| Full suite command | *Wave 0 must introduce* |

**Wave 0 recommendation:** Add `jest` (industry standard, zero-config for Node CommonJS, matches the bridge's pre-`esm` style). Alternative: `node --test` built-in (Node 20+). Given the bridge Dockerfile's Node version needs checking, `jest` is the safer recommendation. Planner verifies Node version in bridge Dockerfile and picks.

For the full test approach the bridge has historically leaned on **integration tests via live `docker-compose up`** + curl. Phase 21 should introduce the first unit tests for the new pure functions (prune decision logic, history query param validation), keeping the bridge's integration-heavy philosophy for the rest.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-01 | Bridge stays subscribed to `/fc1/camera/compressed` with zero viewers | integration | `curl :8081/health` 60s after bridge start with no MJPEG client → expect `camera.subscribed: true` | ❌ Wave 0 (smoke script) |
| D-02 | Idle cadence = 1 frame / 5 min persisted | integration | Run bridge 15 min with no viewers, assert `SELECT COUNT(*) FROM snapshots WHERE source='idle'` ≈ 3 (±1) | ❌ Wave 0 (integration harness) |
| D-03 | `snapshots` hypertable + index exist with correct columns | integration | `psql -c "\d snapshots"` + `SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name='snapshots'` | ❌ Wave 0 (smoke SQL script) |
| D-04 | Retention prune deletes file + row atomically for rows >365d old; respects 30d grace | unit | Mock clock + in-memory rows; assert unlink-then-DELETE order, ENOENT-as-success path, grace blocks under 30d | ❌ Wave 0 (new `test/retention.test.js`) |
| D-05 | Viewer-connected snapshots also tagged `source='viewer'` at 5-min cadence | integration | Open MJPEG stream, wait 10 min, assert `SELECT COUNT(*) WHERE source='viewer'` ≈ 2 | ❌ Wave 0 |
| D-06a | `GET /camera/history` returns bounded, ordered, paginated JSON | unit | Mock `pool.query` return; assert param validation (400s), cap behavior, `has_more` flag | ❌ Wave 0 (new `test/history.test.js`) |
| D-06a.2 | `/camera/history` rejects `to - from > 30 days` | unit | Request with 31-day range → expect 400 | ❌ Wave 0 |
| D-06b | `/health` exposes `snapshots_last_24h` and `oldest_snapshot_at` | integration | `curl :8081/health | jq` after seeding 10 snapshot rows | ❌ Wave 0 (smoke) |
| D-06b.UI | Phase 16 panel renders the two new fields with green/red threshold | smoke (manual) | Load Mission Control, verify new chip lights correctly with live data | N/A (manual UAT) |
| Stall-safety | `saveSnapshot` skips write when `isFrameStale()` | unit | Mock `latestFrame=null` / `lastFrameTime=old` → no INSERT, no fs.writeFile called | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd src/mission-control/bridge && npm test -- --testPathPattern='(retention|history|snapshot)'` (quick — unit tests only, <10s)
- **Per wave merge:** `cd src/mission-control/bridge && npm test` + compose-based smoke script (`scripts/verify/phase-21-smoke.sh` — Wave 0 deliverable) which runs bridge in FAKE_SENSORS mode and asserts expected row counts.
- **Phase gate:** Full suite green + live-stack `curl` verification against elder-plops runtime compose (not `src/docker-compose.yml` — CLAUDE.md).

### Wave 0 Gaps

- [ ] `src/mission-control/bridge/package.json` — add `"scripts": { "test": "jest" }` + `devDependencies: { "jest": "^29.x" }` (confirm `^29` vs `^30` against bridge Node version).
- [ ] `src/mission-control/bridge/test/retention.test.js` — covers D-04 atomicity + grace.
- [ ] `src/mission-control/bridge/test/history.test.js` — covers D-06a param validation + pagination.
- [ ] `src/mission-control/bridge/test/snapshot.test.js` — covers stall-safety (`isFrameStale` gating).
- [ ] `scripts/verify/phase-21-smoke.sh` — integration smoke against live compose (docker-compose v2 commands).
- [ ] Framework install: `cd src/mission-control/bridge && npm install --save-dev jest` — committed `package-lock.json` diff.

## Security Domain

*security_enforcement absent from config.json — treat as enabled.*

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Bridge endpoints are LAN/Tailscale-gated; no auth on `/health`, `/farmer/summary`, `/history/*`, `/camera/*` by existing convention (elder-plops is behind Tailscale) |
| V3 Session Management | no | Stateless endpoints |
| V4 Access Control | no | CORS allowlist (index.js:155-166) is the existing control surface |
| V5 Input Validation | yes | `parseInt` + explicit `camera_id` equality + range cap (Pattern 5). Matches existing `/history/:topic` allowlist pattern (index.js:220-251) — T-07-04 style. No new library. |
| V6 Cryptography | no | No new crypto surfaces |
| V10 Malicious Code | no | No file uploads; `fs.writeFile` writes ROS-provided JPEG bytes, same as today |
| V12 File Handling | partial | `file_path` in DB is bridge-generated (never from client input), so read-side path traversal is impossible. Retention `unlink` operates on DB-sourced paths only. |

### Known Threat Patterns for bridge stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via `camera_id` query param | Tampering | Parameterized `$1/$2/$3` queries (already the bridge convention — index.js:262) + allowlist equality against env `CAMERA_ID` |
| Path traversal via `file_path` response | Info Disclosure | N/A — `file_path` is DB-generated from bridge-side `path.join`. Clients receive it for display; no server-side file-serving endpoint takes client-supplied paths. If Phase 22 later adds `GET /camera/snapshots/:id` it MUST validate against DB lookup only. |
| Unbounded query DoS | DoS | 30-day range cap + 5000 row cap + `LIMIT N+1` pattern |
| Retention prune deleting wrong files | Tampering | `unlink` only runs on paths sourced from `SELECT ... WHERE captured_at < cutoff`. Never from env or client input. |
| Disk exhaustion | DoS | 365-day retention + operator-tunable `RETENTION_DAYS`. `/health` exposes `oldest_snapshot_at` for monitoring. |

## Sources

### Primary (HIGH confidence)
- `src/mission-control/bridge/src/index.js` — entire bridge implementation, lines 1-496 read.
- `src/mission-control/bridge/package.json` — dependencies and Node conventions.
- `docker-compose.yml` + `docker-compose.override.yml` at repo root — runtime bridge config.
- `src/chambers/fc-core/config/fc_config.yaml` — camera_fps and related params.
- `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js:385-625` — Phase 16 `/health` polling loop (extension site).
- `.planning/phases/21-camera-history-continuous-persistence/21-CONTEXT.md` — locked decisions D-01..D-06b.
- `.planning/phases/999.14-index-camera-snapshots-in-timescale/FINDINGS-2026-04-17.md` — scope origin and backfill rationale.
- `.planning/STATE.md` + `.planning/ROADMAP.md` — milestone position.

### Secondary (MEDIUM confidence)
- npm registry verification (2026-04-19): `pg@8.20.0`, `express@5.2.1`, `node-cron@4.2.1` — confirmed current.
- TimescaleDB `create_hypertable` API with `if_not_exists` + `chunk_time_interval` — pattern already in-repo (index.js:131-135); TimescaleDB docs confirm.

### Tertiary (LOW confidence)
- None — all claims grounded in repo code or registry-verified.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all deps already in package.json, versions verified against npm registry
- Architecture: HIGH — every primitive has a line-number citation in index.js
- Pitfalls: HIGH — mostly derived from existing code paths (Phase 14 stall, Phase 12 invariant)
- Validation architecture: MEDIUM — bridge has no test infrastructure today; Wave 0 introduces jest, but test framework choice is a planner call
- Backfill recommendation: MEDIUM — depends on farmer preference not yet confirmed

**Research date:** 2026-04-19
**Valid until:** 2026-05-19 (30 days — stable domain, no fast-moving external deps)
