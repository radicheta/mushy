# Phase 12: Subscriber-Aware Camera - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Phase Boundary

fc_camera conserves 4G bandwidth by idling at a trickle rate when no Mission Control viewers are connected; ramps to full-rate the moment a subscriber appears on `/fc1/camera/compressed`. Self-contained change to fc_camera.py on the Pi.

</domain>

<decisions>
## Implementation Decisions

### Rate configuration
- **D-01:** Active FPS is 1.0 when subscribers are present — live enough to check the chamber, low enough for 4G (~20-40KB/frame at 640x480 q65)
- **D-02:** Idle FPS is ~1 frame/hour (0.000278) when no subscribers — down from current 1 frame/min to further conserve 4G. Phase 13 daily snapshot still has 24 frames/day to pick from.
- **D-03:** Existing `camera_fps` parameter in fc_config.yaml becomes the idle rate. Two new parameters added: `camera_active_fps` (default 1.0) and `camera_subscriber_grace_sec` (default 5.0).

### Subscriber detection
- **D-04:** Use ROS2 `publisher.get_subscription_count()` on the `/fc1/camera/compressed` publisher — checked on every timer tick (cheap integer read, no separate polling timer)
- **D-05:** When subscriber count goes from 0 to >0, destroy the idle timer and create a new timer at active FPS rate
- **D-06:** When subscriber count drops to 0, start a grace countdown (D-07); if still 0 after grace period, destroy active timer and create idle timer

### Disconnect grace period
- **D-07:** 5-second grace period before dropping from active to idle — survives a page refresh without camera cycling. Configurable via `camera_subscriber_grace_sec` in fc_config.yaml.

### Claude's Discretion
- Timer swap implementation details (destroy/recreate vs. other ROS2 patterns)
- Logging verbosity for rate transitions
- Whether to capture+publish immediately on ramp-up or wait for next timer tick
- Test structure for new subscriber-aware behavior

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Camera node
- `src/chambers/fc-core/fc_core/fc_camera.py` — Current fixed-rate implementation; all changes happen here
- `src/chambers/fc-core/config/fc_config.yaml` — Camera parameters (camera_fps, camera_device, etc.); new params added here
- `src/chambers/fc-core/fc_core/test/test_camera.py` — Existing camera tests; new subscriber-aware tests follow this pattern

### Bridge (read-only context)
- `src/mission-control/bridge/src/index.js` — Bridge subscribes to `/fc1/camera/compressed` and serves MJPEG; tracks `mjpegClients`. No changes needed here, but its subscription is what fc_camera detects.

### Launch
- `src/chambers/fc-core/launch/fc.launch.py` — Launches fc_camera with config; may need new param declarations
- `src/chambers/fc-core/setup.py` — Entry point registration for fc_camera

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `fc_camera.py` FcCamera class — timer-based capture pattern, CompressedImage publisher, config-driven parameters. The subscriber-aware version extends this directly.
- `test_camera.py` — FakeNode/FakePublisher test harness. Can be extended to mock `get_subscription_count()` return values.

### Established Patterns
- Timer-based callbacks (`self.create_timer(period, callback)`) — same pattern used by fc_sensors, fc_controller
- Parameter declaration via `declare_parameters()` with defaults in fc_config.yaml
- Non-blocking error handling: log and skip, never crash the node

### Integration Points
- Bridge subscribes to `/fc1/camera/compressed` via rclcnodejs — this subscription is what triggers fc_camera's active mode
- When bridge has 0 MJPEG clients, it still holds the ROS subscription (subscription count stays 1). Rate change is driven by ROS subscriber count, not MJPEG client count.
- fc_config.yaml parameter loading via ROS2 parameter server — new params follow existing pattern

</code_context>

<specifics>
## Specific Ideas

- User explicitly wants idle rate lower than current 1/min — 1 frame/hour is the target idle rate
- Phase 13 daily snapshot depends on the idle trickle, so idle must still capture (not go fully silent)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 12-subscriber-aware-camera*
*Context gathered: 2026-04-13*
