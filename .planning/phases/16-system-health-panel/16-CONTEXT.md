# Phase 16: System health panel — Context

**Gathered:** 2026-04-18 (autonomous, derived from seed + Phases 14/15 outcomes)
**Status:** Ready for planning
**Mode:** Auto-generated during the 2026-04-17/18 autonomous run

<domain>
## Phase Boundary

A narrow system-health panel on Mission Control that multiplies the two-light
pattern shipped in Phase 14 into a handful of lights covering the fc1
subsystems the farmer actually cares about at-a-glance. Explicitly NOT the
full "every subsystem with thresholds and click-through history" dashboard
from the seed — that's a larger scope best done when the farmer can weigh
in on layout and thresholds. This phase ships the *shape* of the panel and
the first concrete set of lights, all consuming signals that already exist
on the live stack (no new bridge endpoints, no new Pi-side publishers).

</domain>

<decisions>
## Implementation Decisions

### D-01: Lights to ship in this phase
Start with six lights. Each line below = one `makeStatusLight` instance:

1. **Sensors** — consumes `/fc1/sensor_health` (Phase 15). Green when `level=OK`;
   yellow when `level=WARN` (warming up — tooltip shows `grace_elapsed_sec`);
   red when `level=ERROR`; grey when no message received in the last 10s
   (TRANSIENT_LOCAL should make this rare, but the grey signals "no data").
2. **Camera feed** — consumes existing `/health.camera.last_frame_age_sec` +
   `/health.camera.subscribed` (Phase 14). This is literally the "Feed live"
   light already shipped in Phase 14's MC plugin; Phase 16 just relocates it
   into the new panel alongside the others instead of living inline under the
   camera image.
3. **Humidifier** — consumes `/fc1/actuators/humidifier` topic echoed via
   bridge WebSocket. Green when last message was within 30s (liveness);
   grey when stale.
4. **Bridge** — consumes `/health` itself. Green if `/health` responded
   200 in the last poll; red if it errored or timed out.
5. **Pi reachable** — consumes `/health.ros.connected` (already in bridge).
   Green when true; red when false.
6. **Phase 15 grace** — consumes `/fc1/sensor_health` for the WARN state
   specifically; shows "warming up 18/20s" with live countdown while
   `level=WARN`; disappears (or goes grey/inactive) when `level=OK`.

### D-02: Layout — a single horizontal strip
One row of lights across the top of the Mission Control main view.
Each light is label + indicator, reusing the Phase 14 `makeStatusLight`
primitive verbatim. No groupings, no sub-panels — the farmer wants a
quick scan, not a dashboard to navigate.

### D-03: Color semantics
Green / yellow / red / grey. No blink or animation.
- **Green:** subsystem is OK.
- **Yellow:** subsystem is in a transient but expected state (warming up,
  brief reconnect). Must NEVER be a real problem — problems go red.
- **Red:** subsystem is actually broken or in an unexpected stale state.
- **Grey:** we genuinely don't know (no data received yet, or poll failed
  in a way that isn't definitively a problem).

Gap-over-noise (memory `feedback_gap_over_noise.md`) in play: when in
doubt, grey, not green. Never show green when the underlying state is
unknown.

### D-04: Data source — `/health` already; no new endpoints
All signals consumed either:
- From the existing `/health` JSON response (poll every 2s, matching the
  existing MC plugin cadence), OR
- From the bridge's existing ROS-to-WebSocket forwarding for specific
  topics (`/fc1/sensor_health`, `/fc1/actuators/humidifier`).

If `/fc1/sensor_health` is not already forwarded over the bridge WebSocket,
adding that forwarding IS in-scope for this phase (one-liner in the bridge).

### D-05: Deploy target — openmct container rebuild
MC frontend plugin changes, same deploy pattern as Phase 14-04:
`docker compose up -d --build openmct` on elder-plops.

### Claude's Discretion
- Exact horizontal ordering of the six lights
- Pixel-level spacing/padding/typography
- Tooltip text wording
- Whether to bundle small additions (e.g., a numeric RH value next to the
  sensors light) — keep minimal, favor consistency over features
- Test strategy (MC frontend has no test infra; manual smoke is fine)

</decisions>

<canonical_refs>
## Canonical References

### Phase 14 primitives reused
- `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` —
  contains `makeStatusLight(parentEl, label)` factory at line 69.
  Phase 16 uses this verbatim.
- `src/mission-control/bridge/src/index.js` — `/health` endpoint already
  exposes `camera.{subscribed, last_frame_age_sec}`, `ros.connected`,
  and other signals.

### Phase 15 signal contract
- `src/chambers/fc-core/fc_core/fc_controller.py` — publishes
  `diagnostic_msgs/DiagnosticStatus` on `/fc1/sensor_health` with
  TRANSIENT_LOCAL QoS. Levels OK / WARN / ERROR. Payload includes
  `grace_elapsed_sec` and `grace_total_sec` when WARN.

### Farmer constraints carried forward
- `feedback_gap_over_noise.md` (memory) — grey over fake-green.
- `project_phase12_camera_stall.md` (memory) — context for why Phase 14
  existed and why Phase 16 matters (same trust problem at scale).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `makeStatusLight` primitive (Phase 14-04) — drop-in for all six lights
- `/health` polling loop in the fruiting-chamber plugin — extend with new
  signals, don't add a second poll loop
- Bridge `/health` JSON — has most signals already; one new field may be
  needed for humidifier liveness timestamp

### Established Patterns
- 2s poll cadence for `/health`
- DOM-first plugin code, no framework
- State transitions logged to the browser console when debugging

### Integration Points
- MC main view DOM — insert a `<div>` row above the existing camera panel
- Bridge WebSocket forwarding config (if `/fc1/sensor_health` needs adding)

</code_context>

<specifics>
## Specific Ideas

- Reuse, don't refactor. Phase 14-04 ships `makeStatusLight`; Phase 16 is
  N instances of it. If Phase 16 finds the primitive wanting, fix it in
  place rather than introducing a second primitive.
- Minimal first, thresholds later. This phase ships existence of lights;
  a follow-up can refine thresholds (e.g., "sensors yellow if any single
  sensor hasn't published in 10s", etc.).
- Humidifier light is a proxy for "control loop is alive" — if no message
  in 30s the controller is either warming up (covered by a different
  light) or wedged. This surfaces that distinction without new plumbing.

</specifics>

<deferred>
## Deferred Ideas

- Individual per-sensor lights (SHT30 / SCD41 temp / SCD41 RH / SCD41 CO2)
  — wait until the aggregator `/fc1/sensor_health` proves insufficient.
- 4G signal strength — modem-manager integration is its own plumbing.
- Disk space — low-priority; we're nowhere near full.
- Actuator-stuck detection — covers under Phase 999.3 (alerts).
- Historical state / click-through detail pages — farmer app (999.11).
- Alert routing to Signal — Phase 999.3.
- Configurable thresholds via fc_config.yaml — defer until thresholds
  prove wrong in practice.

</deferred>

---

*Phase: 16-system-health-panel*
*Context gathered: 2026-04-18 (autonomous)*
