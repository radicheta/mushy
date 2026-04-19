# Phase 22: Timeline scrubber + farmer story view — Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Mushy-side scope for Phase 22 is **data surface only**. The farmer-facing
scrubber UI ("story view") is delegated to the farmOS / Zoy-side farmer app
— same delegation pattern as Phase 18's `/farmer/summary`.

**In scope (mushy-side):**
- New frame-bytes endpoint: `GET /camera/frame?at=<iso>&camera_id=fc1`.
- Bridge-side sidecar burn-in pipeline: every persisted snapshot is written
  twice — raw to `/data/snapshots/...`, and burnt (with a human-readable
  bottom bar) to `/data/snapshots-burnt/...`.
- `/camera/frame` serves burnt by default; `?raw=true` serves raw.
- `/camera/history` response unchanged (already shipped in Phase 21 21-03)
  — farmOS joins it with `/history/:topic` client-side to assemble the
  overlay.
- Coordination artifact: `/mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md`
  entry documenting the two endpoints + payload shape for Zoy.

**Out of scope (explicitly):**
- Scrubber UI, layout, slider, jump buttons, touch gestures — farmOS-side
  (Zoy owns auth / UX / styling, same as Phase 18 D-01).
- Pi-side (fc_camera) burn-in — considered and rejected; see D-05.
- Server-side join of frames + sensor history into one payload — rejected
  (D-04), farmOS composes.
- Time-lapse composition (Phase 23), ML vision events (Phase 24).
- Multi-chamber generalization beyond the `camera_id` param already
  present in `/camera/history` — Phase 999.6.
- Retroactive burn-in of pre-phase snapshots — new frames are burnt from
  deploy forward; old raw-only frames stay as-is.

</domain>

<decisions>
## Implementation Decisions

### Delivery surface
- **D-01:** Farmer-facing UI is **delegated to farmOS / Zoy-side**.
  Mushy's responsibility for Phase 22 is the data surface (frame bytes +
  already-shipped history index). Consistent with Phase 18 D-01
  (`.planning/phases/18-farmer-dashboard-api/18-CONTEXT.md`). The v1.4
  ROADMAP line "New route on bridge serving farmer-facing timeline" is
  reinterpreted as "new route serving farmer-facing *data*".

### Frame-bytes endpoint
- **D-02:** Add `GET /camera/frame?at=<iso>&camera_id=fc1` to the bridge
  (`src/mission-control/bridge/src/index.js`). Resolves the closest
  snapshot row at-or-before `at`, streams the JPEG file from disk with
  appropriate `Content-Type: image/jpeg` and `Cache-Control` headers.
  Single URL per frame — farmOS can use `<img src>` directly.
  - `?raw=true` serves from `/data/snapshots/` (Phase 24 ML escape hatch).
  - Default (no flag) serves from `/data/snapshots-burnt/`.
  - Returns 404 if no snapshot in a reasonable window (tolerance TBD by
    planner — Claude's discretion, likely ≤ `SNAPSHOT_INTERVAL_MS * 2`).
  - Same trust boundary as `/health`, `/farmer/summary`, `/camera/*`:
    no auth (Phase 18 D-"no auth" carried forward).

### Burn-in pipeline
- **D-03:** Burn-in happens **bridge-side in a sidecar path**: every
  `saveSnapshot` writes two files in parallel — raw JPEG to
  `/data/snapshots/{camera_id}/YYYY-MM-DD/...` (unchanged Phase 21
  layout), burnt JPEG to `/data/snapshots-burnt/{camera_id}/YYYY-MM-DD/...`
  with identical filename. DB `snapshots` row records the raw path in
  `file_path` (unchanged Phase 21 schema); the burnt path is derived by
  swapping the root directory.
  - Burn content: single bottom bar across the frame containing
    **timestamp (ISO local) · RH · T · CO2 · humidifier ON/OFF**.
  - Sensor values are pulled from the existing `latestTelemetry` cache
    already populated for `/farmer/summary` (Phase 18 D-04). No new ROS
    subscriptions.
  - Null / warming / offline sensor values render as `—` (en-dash).
    Preserves the **gap-over-noise** rule
    (`feedback_gap_over_noise.md`) — never fabricate a number.
  - Approximate disk cost: ~55 MB/year per chamber extra (on top of the
    ~9 MB/day raw from Phase 21 D-02 idle cadence). Accepted.

### Joined data
- **D-04:** Keep `/camera/history` and `/history/:topic` **separate**.
  farmOS composes the sensor overlay client-side. Consistent with
  Phase 18 D-05 "no new subscriptions, piggyback existing". Avoids
  coupling mushy to Zoy-specific overlay layout. If later profiling
  shows the round-trip cost is a problem on 4G, a convenience endpoint
  can be added; don't premature-optimize.

### Burn site rejection: Pi-side
- **D-05:** Pi-side burn-in in `fc_camera` was considered and rejected.
  Reasons:
  1. Phase 24 (ML vision via ComfyUI) depends on raw pixels — pre-burning
     on the Pi poisons training data irreversibly.
  2. fc_camera would need new subscriptions to humidity/temp/CO2/
     humidifier topics plus a sensor-warmup/offline-null rendering path
     — meaningful complexity on the Pi just for a display concern.
  3. Overlay iteration would require Pi deploys (`fc1/prod` branch +
     `fc-update.service`) instead of an elder-plops bridge redeploy.
  Bridge-side sidecar (D-03) gives us the self-describing-frame feel
  for the farmer without killing raw availability for Phase 24.

### Coordination with Zoy / farmOS
- **D-06:** Before merging this phase, append an entry to
  `/mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md` documenting:
  `/camera/frame` endpoint shape, default/raw behavior, `/camera/history`
  payload (already there from Phase 21), sidecar-burnt expectation so
  Zoy doesn't also overlay sensor text on top. Same handoff pattern as
  Phase 18.

### Claude's Discretion
- JPEG library choice (`sharp` vs `jimp` vs `@napi-rs/canvas`) — planner
  to pick based on bridge's existing node deps and binary-bundle size.
  `sharp` is the mainstream choice but has a native-binary footprint;
  `jimp` is pure-JS and simpler but slower. Either works at our ~1/5min
  cadence.
- Exact bottom-bar rendering (font, padding, background opacity, bar
  height as % of frame). Keep readable on a phone without obscuring the
  substrate. Planner/executor call.
- Tolerance window for "closest frame at-or-before `at`" in
  `/camera/frame` — suggested ≤ 2× `SNAPSHOT_INTERVAL_MS`; beyond that,
  return 404 so farmOS can render "no frame in this window".
- Whether `/camera/frame` also accepts a `file_path` form (pass-through
  from a `/camera/history` row) — nice ergonomics, but opens a path-
  traversal concern; planner decides whether to support it with a
  whitelist prefix check or skip entirely.
- Disk-layout symmetry: the simplest scheme is mirrored trees
  (`/data/snapshots/` vs `/data/snapshots-burnt/`), both retention-managed
  by the Phase 21 prune job. Planner to confirm the prune job handles
  both roots or add a second prune pass.
- `?raw=true` access control — today it's open (same trust boundary as
  raw `/camera/mjpeg`). If farm-net exposure widens, revisit.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Direct upstream (the data surface this phase extends)
- `.planning/phases/21-camera-history-continuous-persistence/21-CONTEXT.md`
  — Shipped `snapshots` table, `/camera/history` endpoint, persister
  architecture, 365-day retention, `/data/snapshots/` filesystem layout.
  Phase 22 layers on top without modifying Phase 21's schema or the
  raw-frame path.
- `src/mission-control/bridge/src/index.js` — Current `saveSnapshot()`
  at line 106, `/camera/history` at 367, `/camera/mjpeg` at 404,
  `/farmer/summary` at 278, `latestTelemetry` cache at 34, `initDb`
  pattern ~121, Postgres `pool` reuse.

### Delegation-pattern precedent
- `.planning/phases/18-farmer-dashboard-api/18-CONTEXT.md` — Same
  delegation posture: mushy exposes read-only JSON; farmOS/Zoy owns UI,
  auth, styling. D-01 (rescope), D-02 (single endpoint), D-05 (no new
  subscriptions) all carry forward.

### Coordination artifact
- `/mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md` — Shared
  handoff doc with the farmOS repo. Phase 18 established the pattern
  (2026-04-19 entry). Phase 22 adds a new entry for
  `/camera/frame` + sidecar-burnt contract.

### Feedback / memory constraints
- `feedback_gap_over_noise.md` — Null / warming sensor values render
  as `—`, never a fabricated number. Drives D-03's null-handling rule.
- `feedback_no_sparklines.md` (2026-04-18) — Farmer explicitly
  declined sparklines; burn-in is a text bar, not a mini-chart.

### Stall-safety carry-over
- `.planning/phases/14-fc-camera-idle-stall-hotfix/14-CONTEXT.md` —
  Phase 14 9s idle-stall recovery remains the line of defense against
  duplicated-frame fake continuity. Phase 22 does not add sha256
  dedupe (consistent with Phase 21 D-"no dedupe yet").
- `.planning/phases/16-system-health-panel/16-CONTEXT.md` —
  `snapshots_last_24h` + `oldest_snapshot_at` are the farmer-visible
  regression signal if either the raw or the burnt write path breaks.
  Planner should ensure the health chip still counts per *raw* row
  (one DB row per captured frame, unchanged), and optionally add a
  second counter for "burnt files present" if robustness is worth it
  (Claude's discretion).

### Phase 24 coupling
- `.planning/milestones/v1.4-ROADMAP.md` — Phase 24's ComfyUI / SAM2
  pipeline reads from the Phase 21 snapshot index. The `?raw=true`
  escape hatch on `/camera/frame` is the contract that keeps Phase 24
  un-poisoned.

### Config
- `docker-compose.yml` + `docker-compose.override.yml` (repo root) —
  Bridge env vars: `SNAPSHOT_DIR` (existing, points to `/data/snapshots`);
  new `SNAPSHOT_BURNT_DIR` (default `/data/snapshots-burnt`) to be added.
  Both must be host-mounted into the bridge container (same volume
  pattern as the raw path).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `saveSnapshot()` (`src/mission-control/bridge/src/index.js:106`) —
  single entry point for frame writes; burn-in wraps the existing write
  with a parallel second write.
- `latestTelemetry` cache (line 34, populated by Phase 18 subscriptions)
  — supplies RH / T / CO2 / humidifier values for the bottom bar with
  zero new ROS subscriptions.
- `lastSensorHealthBroadcast` + `humidifierLastMsgTs` (Phase 16 /
  Phase 18) — available if the bar ever needs a sensor-warming indicator
  (not in v1 of this phase; null → `—` is sufficient).
- `/camera/history` route at line 367 — unchanged; farmOS already
  consumes it since Phase 21 shipped.
- `pool` (`pg.Pool`) — reused for `/camera/frame`'s "closest row at-or-
  before `at`" lookup. Same query style as Phase 21 21-03's range query.

### Established Patterns
- Environment-variable config (not YAML) for bridge-only knobs
  (`SNAPSHOT_DIR`, `SNAPSHOT_INTERVAL_MIN`, `CAMERA_ID`). Add
  `SNAPSHOT_BURNT_DIR` to the same family.
- Express routes return plain responses, no wrappers. Frame endpoint
  streams binary; history stays JSON.
- Retention / prune jobs run in the bridge container so they see the
  mounted filesystem. Burnt tree must be mounted identically and
  swept by the same prune logic.
- Gap-over-noise rule is a cross-cutting discipline — drives the `—`
  placeholder for null sensor values in the burn-in.

### Integration Points
- `saveSnapshot()` — burn pipeline inserts here. Must not slow the
  write path enough to drop frames under the 5-min cadence.
- `initDb` — no schema changes (Phase 21's `snapshots` hypertable is
  reused as-is).
- `app.get('/health', ...)` — optional "burnt-pipeline healthy" bool
  if it's cheap; otherwise the existing `snapshots_last_24h` count is
  already the regression signal.
- `docker-compose.override.yml` — add the second volume mount for
  `/data/snapshots-burnt` and the `SNAPSHOT_BURNT_DIR` env var.

</code_context>

<specifics>
## Specific Ideas

- "The saved snapshot should have all info burnt in — RH, CO2, Temp,
  Hum state etc" — direct user quote 2026-04-19. Drives D-03.
- User's initial framing was Pi-side burn-in ("what if it's already
  baked in on the stream?"). Rejected after weighing against Phase 24
  ML needs (D-05). Document this rejection clearly so it doesn't come
  back as "why aren't we doing it the simple way?" in a future phase.
- Farmer app / story view is a Zoy-side deliverable. Mushy avoids
  duplicating farmOS auth + UX surface, same reasoning as Phase 18.
- Burnt-frame visual style is a security-cam / dashcam idiom the
  farmer already recognizes — no new UI literacy required.

</specifics>

<deferred>
## Deferred Ideas

- Server-side join endpoint `/camera/story?from=&to=` with snapshots
  + telemetry in one payload — adds coupling; pick it up only if
  round-trip cost on 4G turns out to matter in practice.
- Retroactive burn-in of pre-phase raw snapshots — not needed for
  v1.4 demo; the oldest un-burnt frames fall out of retention in 365
  days anyway.
- Overlay-in-live-MJPEG (burn on `/camera/mjpeg` for live viewers) —
  would extend the self-describing-frame feel to live streams, but
  adds per-frame CPU cost at 1 fps. Revisit if a farmer asks.
- Pi-side burn-in — captured as D-05 rejection, not lost.
- `/camera/frame` thumbnail / resized variants (`?w=640` etc.) —
  farmOS can do its own sizing via CSS; add only if data volume on 4G
  shows it matters.
- Alerter-side usage — burnt snapshots could be attached to Signal
  contamination alerts in Phase 24 for instant "is this a false
  positive?" human review. Note for Phase 24, don't plumb here.

</deferred>

---

*Phase: 22-timeline-scrubber-farmer-story-view*
*Context gathered: 2026-04-19*
