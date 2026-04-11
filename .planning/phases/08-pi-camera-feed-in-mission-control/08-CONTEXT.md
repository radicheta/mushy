# Phase 8: Pi Camera Feed in Mission Control - Context

**Gathered:** 2026-04-08
**Status:** Ready for planning

<domain>
## Phase Boundary

USB webcam on fc1 Pi publishes image frames via ROS2, viewable as a live camera feed in Mission Control (OpenMCT). Periodic snapshots stored on elder-plops. Foundation for future vision features (time-lapse, contamination detection, rover bot cameras).

No image analysis, no ML inference, no multi-camera support in this phase.

</domain>

<decisions>
## Implementation Decisions

### Streaming Architecture
- **D-01:** Camera publishes as a ROS2 node using `sensor_msgs/Image` or `sensor_msgs/CompressedImage` topics. This is the rover-ready path — any future camera (Pi, rover, USB) just publishes to the same topic pattern.
- **D-02:** Use compressed JPEG over ROS topics (`fc/camera/compressed`) to minimize bandwidth. Cellular link between Pi and elder-plops means every byte counts.
- **D-03:** MJPEG stream served from the bridge on elder-plops for Mission Control consumption. Bridge subscribes to the ROS compressed image topic and re-serves as an HTTP MJPEG endpoint. Browser-native, no transcoding, no WebRTC complexity.

### Bandwidth Management
- **D-04:** Low framerate by default — 1-2 FPS for live monitoring. Mushroom growth is slow; high FPS wastes cellular bandwidth for zero benefit.
- **D-05:** Resolution capped at 640x480 or 720p max. Configurable in `fc_config.yaml`. Good enough for visual monitoring, keeps frame sizes small.
- **D-06:** JPEG compression quality configurable (default ~60-70%). Balance between visual clarity and bandwidth.

### Camera on the Pi
- **D-07:** USB webcam accessed via v4l2 (Video4Linux2). Standard Linux camera interface, works with any USB webcam.
- **D-08:** Camera node is a ROS2 Python node in `fc_core` package, launched alongside sensor/controller nodes. Auto-starts with the systemd service.
- **D-09:** Topic naming follows existing pattern: `fc1/camera/compressed` for frames, `fc1/camera/info` for camera metadata.

### Snapshot Storage
- **D-10:** Bridge captures periodic snapshots (configurable interval, default every 15 minutes) and saves to elder-plops filesystem.
- **D-11:** Snapshots stored in a date-organized directory structure on elder-plops (e.g., `/data/snapshots/fc1/2026-04-08/`). Plenty of storage available.
- **D-12:** Snapshot metadata (timestamp, camera ID) logged — ready for future time-lapse assembly or FarmOS observation attachments.

### Mission Control Integration
- **D-13:** Camera feed appears as a dedicated view/panel in Mission Control. Simple `<img>` tag pointing at the MJPEG endpoint from the bridge.
- **D-14:** OpenMCT plugin registers the camera as a telemetry source with a custom view type (image stream, not chart).

### Claude's Discretion
- Exact v4l2 configuration and device detection
- ROS2 node implementation details (cv_bridge vs raw v4l2 + manual JPEG)
- MJPEG endpoint implementation in the Node.js bridge
- OpenMCT plugin structure for camera view
- Snapshot directory cleanup/rotation policy
- Error handling when camera is disconnected

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### ROS2 Camera
- `src/chambers/fc-core/fc_core/fc_sensors.py` — existing sensor node pattern to follow for camera node
- `src/chambers/fc-core/config/fc_config.yaml` — config file where camera parameters will live
- `src/chambers/fc-core/launch/fc.launch.py` — launch file to add camera node

### Mission Control
- `src/mission-control/bridge/index.js` — bridge service; camera MJPEG endpoint adds here
- `src/mission-control/frontend/plugins/fruiting-chamber/` — OpenMCT plugin directory for camera view
- `src/docker-compose.yml` — bridge runs `network_mode: host`, camera endpoint exposed through it

### Infrastructure
- `.planning/phases/06-wireguard-vpn-routing-for-ros-traffic/06-CONTEXT.md` — VPN topology; camera frames traverse cellular WireGuard tunnel
- `.planning/phases/07-historical-data-storage-and-openmct-time-series-visualizatio/07-CONTEXT.md` — bridge architecture; camera endpoint follows same pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `fc_sensors.py` — ROS2 node pattern with timer-based publishing, error handling, config loading. Camera node follows same structure.
- `bridge/index.js` — Node.js service with WebSocket + HTTP endpoints. MJPEG endpoint adds alongside existing REST history endpoint.
- `frontend/plugins/fruiting-chamber/` — OpenMCT plugin pattern for registering new telemetry types and views.

### Established Patterns
- ROS2 topics under `fc/` namespace (`fc/humidity`, `fc/temperature`, `fc/co2`, `fc/actuators/humidifier`)
- Configuration in `fc_config.yaml` with grower-readable parameter names
- Bridge subscribes to ROS topics via rclnodejs, serves data to frontend
- Docker services on `frontend-net` for web-facing, `ros-net` for ROS comms

### Integration Points
- Camera node publishes to `fc/camera/compressed` on `ros-net`
- Bridge subscribes to camera topic, serves MJPEG on HTTP (same host:port as history API)
- OpenMCT frontend loads camera view plugin alongside existing sensor charts
- Snapshots written to elder-plops local filesystem (not containerized storage)

</code_context>

<specifics>
## Specific Ideas

- This is the first step toward a rover bot with cameras — ROS2 image topic pattern must be generic enough for any camera source
- Cellular bandwidth is the primary constraint — optimize for low bandwidth over high quality
- Elder-plops has plenty of storage for snapshots
- Future vision features: time-lapse assembly, contamination detection (ML), growth stage classification, FarmOS observation image attachments

</specifics>

<deferred>
## Deferred Ideas

- **Time-lapse assembly** — Stitch snapshots into time-lapse videos. Needs ffmpeg or similar. Future phase.
- **Contamination detection** — ML-based visual anomaly detection from camera frames. Needs training data + inference pipeline.
- **Growth stage classification** — Classify pin set / primordia / mature from images. ML task, future phase.
- **Multi-camera support** — Multiple cameras (Pi cam, rover cam) with camera ID namespacing. When rover arrives.
- **FarmOS image observations** — Push snapshots as observation log attachments to FarmOS. Blocked on FarmOS integration (backlog 999.2).
- **Pan/tilt/zoom control** — If rover or PTZ camera, actuator controls via ROS. Future hardware.

</deferred>

---

*Phase: 08-pi-camera-feed-in-mission-control*
*Context gathered: 2026-04-08*
