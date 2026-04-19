# Phase 18: Farmer Dashboard API — Context

**Gathered:** 2026-04-19 (retrofit — phase was shipped inline during a planning session, artifacts created after the fact)
**Status:** Shipped; retrofit artifacts
**Mode:** Retrofit documentation — endpoint was built and verified live before GSD phase artifacts existed

<domain>
## Phase Boundary

Mushy exposes a read-only JSON snapshot endpoint on the bridge. The farmer-facing
dashboard UI is **delegated to the farmOS / Zoy-side** (see
`.planning/ROADMAP.md` and the shared `CLAUDE-SYNC.md` in the farmOS repo).

Scope **in** for this phase (mushy-side):
- One new route on the mushy bridge: `GET /farmer/summary`
- Latest-value cache populated by existing ROS subscription callbacks
- Payload shape stable enough to wire from a farmOS module

Scope **out** (explicitly delegated or deferred):
- Dashboard UI, layout, styling, auth — all farmOS-side
- Historical rollups beyond what `/history/:topic` already serves
- Server-side event feed for alerts (no alerter→bridge back-channel in this phase)
- CORS config changes — Zoy-side decision on proxy vs browser-direct fetch

</domain>

<decisions>
## Implementation Decisions

### D-01: Scope rescoped mid-v1.3
Original Phase 18 in the v1.3 roadmap was "farmer dashboard (vanilla HTML served from
mushy bridge at `/farmer`)". Rescoped 2026-04-19 during a board-planning discussion:
farmOS already owns auth / user management / UX surface, so mushy should not
duplicate. Mushy's responsibility shrinks to a read-only JSON API.

### D-02: Single endpoint, single payload
One endpoint `GET /farmer/summary` returning a snapshot object. No pagination, no
filters, no query params. Cheap to poll from a farmOS widget. If Zoy needs
differentiated payloads per view, we add `?view=...` later — YAGNI for now.

### D-03: Shape
```json
{
  "chamber_id": "fc1",
  "timestamp": <ms epoch>,
  "sensors": {
    "humidity":    { "value": <float>, "timestamp": <ms epoch> } | null,
    "temperature": { "value": <float>, "timestamp": <ms epoch> } | null,
    "co2":         { "value": <float>, "timestamp": <ms epoch> } | null
  },
  "actuators": {
    "humidifier":  { "value": 0|1, "timestamp": <ms epoch> } | null
  },
  "sensor_health": { level, name, message, values{} } | null,
  "camera": {
    "last_frame_age_sec": <int> | null,
    "subscribed": <bool>
  }
}
```
Each sensor returns `{value, timestamp}` to let consumers detect staleness per
channel. `null` means "no message seen yet" — distinct from an explicit zero.
Mirrors the feedback-memory rule: **gap over noise**.

### D-04: Latest-value cache lives in bridge process memory
Not in Timescale. Reasons: (a) zero latency for the happy path, (b) avoids
double-write cost on every subscription, (c) bridge restarts are infrequent
and TRANSIENT_LOCAL QoS on humidifier (+ continuous sensor publishers) refill
the cache within seconds.

### D-05: No new ROS subscriptions
The endpoint piggybacks on subscriptions that already existed for the live
WebSocket broadcast (humidity, temperature, co2, humidifier, sensor_health,
camera). Each callback adds one line populating `latestTelemetry`. No new
topics, no new QoS profiles.

### D-06: No alerts feed in v1
The alerter service publishes to Signal, not back to the bridge. Adding an
alerter→bridge back-channel is deferred. If the farmOS dashboard needs
"recent alerts" we add a POST callback from alerter to bridge in a follow-up
phase. For this phase the farmer already gets alerts via Signal, so the
dashboard's job is current-state visibility, not alert history replay.

### Claude's Discretion
- Error handling: minimal — read-only endpoint, no DB dependency, errors
  surface as default express 500s if a subscription callback ever throws
  (unlikely since it's pure field access into cached objects).
- No auth — this is a read-only endpoint inside the same trust boundary as
  `/health` and `/history/:topic`. If Zoy-side exposes it publicly, Zoy adds
  the auth layer farmOS-side.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/mission-control/bridge/src/index.js` owns all ROS subscriptions and the
  existing `/health`, `/history/:topic`, `/camera/*` routes. Adding a new
  read-only endpoint is a ~30-line diff.
- `lastSensorHealthBroadcast` was already cached in-process for Phase 16.1
  replay — reused directly.
- `humidifierLastMsgTs` already tracked for health panel watchdog — reused.
- `lastFrameTime`, `cameraSubscription`, `CAMERA_ID` already exist from
  Phases 12 / 14.

### Established Patterns
- Express routes return plain JSON, no wrappers.
- CORS middleware already in place, allowlist-based, Phase 18 inherits it.
- Timestamps are ms epoch numbers, not ISO strings — matches existing
  `/health` and broadcast conventions.

### Integration Points
- Lives alongside `/health` in `index.js`. No new files, no new modules.
- farmOS-side consumer TBD by Zoy — proxy-through-farmOS assumed, which
  keeps the mushy-side CORS config as-is.

</code_context>

<specifics>
## Specific Ideas

- Payload shape proposed to Zoy via `/mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md`
  entry 2026-04-19. Any Zoy-side pushback on shape lands as a follow-up tweak,
  not a rewrite.
- Farmer sentiment: "loves it" (Phase 17 UAT 2026-04-19). Morale context for
  not over-engineering this phase — the alert pipeline already delivered the
  main visibility win; this endpoint is the plumbing for the farmOS dashboard
  to catch up.

</specifics>

<deferred>
## Deferred Ideas

- Alerter→bridge back-channel for recent-alerts feed (follow-up phase if
  farmOS dashboard requests it).
- SSE / WebSocket push variant of this endpoint (polling fine for farmer
  dashboard cadence; revisit if dashboard demands sub-second updates).
- Multi-chamber generalization — endpoint returns `chamber_id: "fc1"` only
  because that's all we have today. When FC-2/FC-3 land (999.6 / Pi Zero
  pattern), add either `chamber_id` query param or a list response.
- Payload versioning field — skipped for now. Add `schema_version` only if
  Zoy-side ever reports a breaking-change coordination issue.

</deferred>
