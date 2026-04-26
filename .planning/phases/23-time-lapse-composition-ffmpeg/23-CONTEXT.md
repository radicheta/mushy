# Phase 23: Time-lapse composition (ffmpeg) — Context

**Gathered:** 2026-04-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Automated daily mp4 generation from Phase 21 snapshots, plus an on-demand endpoint for
arbitrary date ranges. Raw frame retention policy tightened as part of this phase.
No ML, no farmOS integration, no farmer-facing UI — just the pipeline and the file.

</domain>

<decisions>
## Implementation Decisions

### All areas — Claude's discretion
User delegated all implementation choices: "make something sensible, we'll fine tune later."
Decisions below are Claude's defaults — all are tunable without replanning.

### Composer deployment
- **D-01:** New `timelapse` container in docker-compose, sibling to bridge/alerter. Node.js + ffmpeg binary. Keeps bridge focused; timelapse can be rebuilt independently.
- **D-02:** Nightly trigger via `node-cron` inside the container at 00:30 local time. Composes the previous calendar day's frames.
- **D-03:** On-demand endpoint `GET /timelapse?from=<iso>&to=<iso>&camera_id=fc1` lives in the same timelapse container (not the bridge). Returns the pre-composed mp4 if it exists; returns 202+job-id if it needs to be composed on the fly (async, poll `/timelapse/status/:id`).

### ffmpeg recipe
- **D-04:** Input: sorted frame list from `/data/snapshots/{camera_id}/{date}/` via `-f concat -safe 0 -i filelist.txt`. Output: `-c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p -r 12`.
- **D-05:** Framerate: 12fps. At 96 frames/day → ~8s clip. At current sparse rate (~11 frames/day) → ~1s — acceptable for now; framerate tunable via env var `TIMELAPSE_FPS` (default: 12).
- **D-06:** Overlay: `drawtext` filter — timestamp (derived from filename, formatted as `YYYY-MM-DD HH:MM`) in top-left, RH (nearest-neighbor lookup from Timescale `telemetry` table by `captured_at`) in top-right. White text, small font, semi-transparent background box. CO2 and other fields deferred.
- **D-07:** If fewer than 3 frames exist for a day, skip mp4 generation and log a warning. No empty/broken clips.

### Storage
- **D-08:** Output path: `/data/timelapse/{camera_id}/YYYY-MM-DD.mp4`. Bind-mount `/data/timelapse` into the container.
- **D-09:** Per-day mp4s kept forever (no retention pruning). Raw frames already on 365-day retention via Phase 21 bridge retention job — no change needed.
- **D-10:** Timescale `timelapses` table: `(camera_id, date, file_path, frames_used, composed_at, duration_sec)`. Lets the on-demand endpoint skip recomposition if the mp4 already exists.

### RH sourcing for overlay
- **D-11:** At composition time, run one Timescale query: `SELECT captured_at, value FROM telemetry WHERE topic='fc1/humidity' AND captured_at BETWEEN day_start AND day_end ORDER BY captured_at`. For each frame, find nearest RH reading by timestamp delta. If no RH within 30min of frame → omit RH from that frame's overlay rather than fail.

### Claude's Discretion
- Exact font size and overlay positioning
- Whether to add a progress/health chip to Mission Control or bridge `/health` for timelapse job state
- Error handling details (retry count, alerter integration if nightly job fails)

</decisions>

<canonical_refs>
## Canonical References

### Snapshot storage (Phase 21)
- `src/mission-control/bridge/src/retention.js` — retention logic; raw frame pruning already in place
- `src/mission-control/bridge/src/index.js` — `SNAPSHOT_DIR`, `SNAPSHOT_BURNT_DIR`, `saveSnapshot()`, `/camera/history` endpoint

### Timescale schema
- `src/mission-control/bridge/src/index.js` — `snapshots` hypertable schema (D-03 from Phase 21 context): `camera_id, captured_at, file_path, bytes, source, fps`
- `telemetry` table for RH lookup (pre-existing, `topic + captured_at + value`)

### Compose stack
- `docker-compose.yml` + `docker-compose.override.yml` at repo root — add new `timelapse` service here

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `/data/snapshots/fc1/YYYY-MM-DD/` — 15 days of frames already on disk, filenames are ISO timestamps (`2026-04-16T00-07-25-693Z.jpg`)
- `SNAPSHOT_DIR` env var in bridge — timelapse container should share the same bind-mount path
- Timescale `telemetry` table — RH available for overlay lookup

### Established Patterns
- All services are Node.js in docker-compose
- Timescale pool pattern: `new Pool({ connectionString: process.env.TIMESCALE_URL })`
- `node-cron` already available in the alerter — reuse the same pattern
- Bridge bind-mounts `/data` — timelapse container should do the same

### Integration Points
- New container in `docker-compose.yml` + `docker-compose.override.yml`
- Read from `/data/snapshots/` (read-only), write to `/data/timelapse/` (new dir)
- Read from Timescale for RH overlay and `timelapses` table writes
- No bridge changes required for the nightly job; on-demand endpoint is standalone

</code_context>

<specifics>
## Specific Ideas

- Farmer has already seen a hand-composed prototype (2026-04-19). First demoable artifact is a "tweet-able" daily clip — keep it clean and shareable.
- First real test: compose 2026-04-26 frames manually after container is live to validate recipe before cron fires.

</specifics>

<deferred>
## Deferred Ideas

- CO2 overlay — deferred until we know it adds value over RH alone
- Farmer-facing UI to browse/download time-lapses — 999.11 (farmer app)
- Multi-camera support — 999.6 (multi-chamber)
- Annotated time-lapses with ML bounding boxes — Phase 24 (ComfyUI)
- Signal notification when daily timelapse is ready — future phase or Phase 25 extension

</deferred>

---

*Phase: 23-time-lapse-composition-ffmpeg*
*Context gathered: 2026-04-26*
