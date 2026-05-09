# Phase 21: Camera history continuous persistence - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Close the "blank hours" gap in the fc1 camera history so Phase 22 has a
continuous timeline to scrub. Today the bridge only captures frames while
a Mission Control viewer is connected (Phase 12 subscriber-awareness) —
overnight and weekends have zero persisted frames even though fc_camera
publishes an idle pulse to the ROS topic.

**In scope:** persister architecture, idle cadence, snapshots index in
Timescale, filesystem layout + retention, a read-only history endpoint
and health-panel chip so the farmer can trust the pipeline.

**Out of scope (other phases):**
- Timeline scrubber UI in Mission Control — Phase 22
- Time-lapse composition (ffmpeg) — Phase 23
- ML vision events via ComfyUI — Phase 24
- Pi-side edge-buffering / offline resilience — Phase 999.1
- Multi-chamber `camera_id` parameterization — Phase 999.6 (honored in
  schema shape, not implemented here)
</domain>

<decisions>
## Implementation Decisions

### Persister architecture
- **D-01:** The bridge (`src/mission-control/bridge/src/index.js`) is the
  persister. It keeps a low-rate ROS subscription to
  `/fc1/camera/compressed` alive **even when `mjpegClients.size === 0`**.
  `ensureCameraSubscribed()` / `maybeCameraUnsubscribe()` are modified so
  unsubscribe only happens if there is neither a viewer *nor* a pending
  history capture. No new container, no new service. One process keeps
  owning both the stream and the archive.

### Persistence cadence
- **D-02:** Idle cadence (no viewer) = **1 frame / 5 minutes**
  (~9 MB/day, ~270 MB/month). Dense enough for Phase 22's scrubber and
  future contamination/pinning workflows.
- **D-05:** Viewer-connected cadence = **same 5-minute cadence**.
  Persistence is *decoupled* from viewer presence — the scrubber gets a
  uniform timeline, no "fat" viewer-regions. The live MJPEG stream still
  runs at full rate for viewers; we just don't persist every live frame.

### Snapshots index (Timescale)
- **D-03:** New hypertable `snapshots` with columns:
  `captured_at TIMESTAMPTZ NOT NULL`,
  `camera_id TEXT NOT NULL`,
  `file_path TEXT NOT NULL`,
  `bytes INTEGER NOT NULL`,
  `source TEXT NOT NULL CHECK (source IN ('viewer','idle','manual'))`,
  `fps NUMERIC`.
  Hypertable on `captured_at`, chunk interval 1 day (matches existing
  `telemetry` hypertable conventions). Index on `(camera_id,
  captured_at DESC)`. Files stay on disk at
  `/data/snapshots/{camera_id}/YYYY-MM-DD/` — the DB is a lookup index,
  not blob storage.
- Joining to RH/CO2/temperature at frame time uses the existing
  `telemetry` hypertable via `telemetry.time` — no denormalization into
  `snapshots`.

### Retention
- **D-04:** **365 days**, then prune (files + DB rows). One full growing
  year covers seasonal review + ML training corpus for Phase 24.
  Prune job runs on a schedule (cron or periodic in bridge) and deletes
  both the file and the row atomically. Pruning starts only once the
  system has been writing for >30 days (avoid nuking a half-populated
  history on a fresh install).

### Demo-able v1.4 artifacts
- **D-06a:** New read-only endpoint `GET /camera/history?from=&to=&camera_id=`
  on the bridge. Returns JSON list of
  `{captured_at, camera_id, file_path, bytes, source, fps}` ordered by
  `captured_at ASC`, capped (e.g. 5000 rows) with a `has_more` flag.
  This is the shape Phase 22's scrubber will consume.
- **D-06b:** Health exposure — extend the Phase 16 system-health panel
  (and `/health`) with two fields: `snapshots_last_24h` (count) and
  `oldest_snapshot_at` (ISO timestamp or null). Farmer-visible regression
  signal; drops to 0 = pipeline broken.

### Stall-safety carry-over
- The Phase 14 fc_camera idle-stall recovery (9s) stays the line of
  defense against duplicated-frame "fake continuity". This phase does
  **not** add sha256 dedupe; rely on the Phase 14 fix + Phase 16
  `last_frame_age_sec` already exposed in `/health`. Revisit if a future
  stall class slips past those.

### Claude's Discretion
- Exact prune cadence (daily vs hourly cron) and implementation site
  (bridge in-process interval vs docker service vs system cron).
- Exact shape of the health chip in the Mission Control UI (Phase 16
  panel integration style).
- Migration handling for existing `/data/snapshots/` files written before
  this phase (backfill into DB vs start-from-now). Researcher to
  recommend; planner to lock.
- Whether to add a `camera_id` env var / config layer now vs when
  Phase 999.6 lands (schema already supports it; wiring is discretionary).
- Response pagination details for `/camera/history` (cursor vs offset,
  max page size).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 21 seed
- `.planning/phases/999.14-index-camera-snapshots-in-timescale/FINDINGS-2026-04-17.md` —
  Original scope discussion; Issue 2 (idle pulse never persisted) is the
  core problem this phase solves.

### Prior camera/bridge phases (touched or respected)
- `src/mission-control/bridge/src/index.js` — Current `saveSnapshot()`
  at line 106; `ensureCameraSubscribed()` / `maybeCameraUnsubscribe()`
  at 86/99; snapshot timer at 481; `/health` at 170.
- `.planning/phases/12-subscriber-aware-camera/12-CONTEXT.md` —
  Subscriber-aware design; this phase modifies its invariant.
- `.planning/phases/14-fc-camera-idle-stall-hotfix/14-CONTEXT.md` —
  9s idle-stall recovery we depend on for stall safety.
- `.planning/phases/16-system-health-panel/16-CONTEXT.md` — Health panel
  to extend with `snapshots_last_24h` / `oldest_snapshot_at`.

### Phase 18 reference (endpoint style)
- `.planning/phases/18-farmer-dashboard-api/18-CONTEXT.md` — Read-only
  bridge endpoint conventions (`GET /farmer/summary`). Follow same
  pattern for `GET /camera/history`.

### Config
- `src/chambers/fc-core/config/fc_config.yaml` — Camera FPS /
  rate params (may need a new `persistence_rate_sec` or similar).
- `docker-compose.yml` + `docker-compose.override.yml` (repo root) —
  Bridge env vars: `SNAPSHOT_DIR`, `SNAPSHOT_INTERVAL_MIN`, `CAMERA_ID`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pushFrame()` / `latestFrame` in bridge — already updates a single
  in-memory JPEG whenever the subscription fires. Lives in
  `src/mission-control/bridge/src/index.js:60`.
- `saveSnapshot()` (line 106) — already writes `latestFrame` to a
  date-bucketed dir. The persistence *write path* exists; it's the
  *subscription invariant* that needs changing.
- `initDb()` (line 121) — hypertable creation pattern (`telemetry`).
  Copy this pattern for `snapshots` hypertable + index.
- `/health` JSON + `last_frame_age_sec` (Phase 14 HFIX-03) — append new
  fields here.
- `pool` (`pg.Pool`) — bridge already has a Postgres client pool for
  telemetry. Reuse for `snapshots` inserts and queries.
- Phase 18 `/farmer/summary` — established shape for read-only JSON
  endpoints on the bridge.

### Established Patterns
- All telemetry goes through Timescale hypertables chunked 1 day.
- File paths on `/data/...` are mounted from the elder-plops host into
  the bridge container; retention jobs must run in the same container
  (so they see the same filesystem).
- Environment-variable config (not YAML) for bridge-only knobs:
  `SNAPSHOT_DIR`, `SNAPSHOT_INTERVAL_MIN`, `CAMERA_ID`.
- Subscriber-awareness on ROS subscriptions is the baseline invariant
  in the bridge — this phase relaxes it *only* for the history path.

### Integration Points
- `ensureCameraSubscribed()` / `maybeCameraUnsubscribe()` — invariant
  change point.
- `setInterval(saveSnapshot, SNAPSHOT_INTERVAL_MS)` at line 481 — rate
  source of truth for persistence cadence.
- `initDb()` — add `snapshots` hypertable creation.
- `app.get('/health', ...)` at line 170 — extend with new fields.
- Phase 16 system-health panel — UI consumer of those new fields.

</code_context>

<specifics>
## Specific Ideas

- Decoupling persistence cadence from viewer cadence is deliberate:
  farmer told us (see `feedback_no_sparklines.md` + FINDINGS-2026-04-17)
  that an *annotated, uniform* timeline is the goal, not a dense-where-
  I-watched / blank-elsewhere mosaic.
- The 1/5-min idle rate was chosen because it's 3× cheaper than the
  pre-Phase-12 workaround (35 MB/day → ~9 MB/day) while giving the
  scrubber enough density to catch a 30-min contamination event.
- 365-day retention is operator-chosen: one mushroom season + review.
  Prefer pruning over fatalistic disk-fill on elder-plops (which also
  runs Mission Control).
- Do not introduce sha256 dedupe yet — trust the Phase 14 fc_camera
  stall fix + Phase 16 `last_frame_age_sec`. Revisit only if a new
  stall class is observed.

</specifics>

<deferred>
## Deferred Ideas

- **Pi-side ring buffer with sync** — composes with Phase 999.1
  (edge-buffering). Adds offline resilience if elder-plops / WireGuard
  go down. Not needed to unblock Phase 22.
- **Dedicated archivist subscriber on elder-plops** — cleaner
  decoupling; deferred because bridge trickle-subscribe is simpler and
  the 4G cost is acceptable at 1/5min.
- **sha256 dedupe on snapshots** — structural guarantee against
  future stall classes; revisit if Phase 14's fix proves insufficient.
- **Backfill of pre-phase `/data/snapshots/` files into the index** —
  discretionary during planning; may be ship-from-now instead of
  backfill.
- **Camera_id plumbing for multi-chamber** — schema supports it; full
  wiring lives in Phase 999.6.
- **BLOB-in-DB storage of frames** — explicitly rejected; files on disk,
  DB as index.

</deferred>

---

*Phase: 21-camera-history-continuous-persistence*
*Context gathered: 2026-04-19*
