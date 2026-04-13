# Phase 13: FarmOS Daily Report - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Phase Boundary

FC-1 exists as a structure asset in FarmOS and receives a daily observation log containing a camera snapshot and environment summary. The report service runs on elder-plops as a ROS2 lifecycle node — architecturally the seed for autonomous farm agents (rover, multi-chamber orchestration), but scoped in this phase to passive observe-and-report only.

</domain>

<decisions>
## Implementation Decisions

### FarmOS API Integration
- **D-01:** Authenticate with FarmOS via OAuth2 client credentials — FarmOS 2.x/3.x standard, token auto-refreshes
- **D-02:** FC-1 already exists as asset 28 in FarmOS at `http://10.68.155.50:8082/asset/28` — no provisioning needed. Hardcode asset ID 28 in config (or env var `FARMOS_ASSET_ID=28`). Lab 1 is asset 26 at `/asset/26` for reference.
- **D-03:** FarmOS credentials stored in `.env` on elder-plops alongside existing `TIMESCALE_PASSWORD` — variables: `FARMOS_URL=http://10.68.155.50:8082`, `FARMOS_USERNAME`, `FARMOS_PASSWORD` (session-cookie auth per research finding — OAuth2 consumer not configured on this instance)

### Daily Report Content & Scheduling
- **D-04:** Report runs at 06:00 local time — before grower's morning check, covers previous full day
- **D-05:** Camera snapshot is the latest frame from fc_camera's idle trickle (1 frame/hr) closest to report time — fetched from bridge's `/camera/latest.jpg` endpoint (new internal endpoint returning `latestFrame` buffer)
- **D-06:** Environment aggregation window is previous 24 hours (midnight-to-midnight local) — clean daily boundary
- **D-07:** Text summary formatted as markdown table in FarmOS observation notes — avg/min/max per metric (humidity, CO2, temperature), humidifier duty cycle %, anomaly flags

### Service Architecture
- **D-08:** Report service is a new Docker container on elder-plops in the existing compose stack — but runs a ROS2 lifecycle node (`farmos_agent`), not a plain Python script. This is the architectural seed for autonomous farm agents.
- **D-09:** Duplicate prevention via FarmOS API check — query for existing observation with today's date before posting. Idempotent by date key.
- **D-10:** Runtime is Python with rclpy — matches fc_core patterns, `requests` for FarmOS API, `psycopg2` for TimescaleDB queries
- **D-11:** ROS2 lifecycle node pattern: configure (load creds, connect DB) → activate (start daily timer) → the timer callback is `execute_report()` which does observe→synthesize→record. No actuation in this phase — passive agent only.

### Claude's Discretion
- Docker image base and build approach (slim Python + rclpy, or extend existing ros-core image)
- Timer implementation (ROS2 timer vs system cron triggering a ROS2 service call)
- Error handling and retry strategy for FarmOS API failures
- Log format and verbosity
- Whether to add a `/camera/latest.jpg` endpoint to bridge or use the existing MJPEG stream to grab a frame

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Bridge (`src/mission-control/bridge/src/index.js`) already has `latestFrame` buffer and `Pool` from `pg` for TimescaleDB queries
- `docker-compose.yml` at repo root defines the compose stack — new service goes here
- `fc_config.yaml` has all sensor topic names and configuration patterns

### Established Patterns
- Docker services use `ros-net` for ROS2 communication, `frontend-net` for web/DB access
- TimescaleDB telemetry table: `INSERT INTO telemetry (time, topic, value)` — same table the report will query with aggregation SQL
- Bridge's existing `/health` and `/history` endpoints show the HTTP API pattern

### Integration Points
- Bridge needs a new `/camera/latest.jpg` endpoint (returns `latestFrame` as JPEG)
- TimescaleDB on `timescale:5432` — report service queries `telemetry` table with `AVG/MIN/MAX` over date range
- FarmOS on port 8082 on elder-plops — external API, OAuth2 auth
- ROS2 topics: the node could optionally subscribe to sensor topics directly, but for v1 querying TimescaleDB is simpler and doesn't require the Pi to be online at report time

</code_context>

<specifics>
## Specific Ideas

- **Autonomous agent seed:** User explicitly framed this as the beginning of an autonomous farm program. The observe→synthesize→record pattern in `execute_report()` is where a future planner/executor loop slots in. The ROS2 lifecycle node gives safe state transitions. The rover (999.7) would extend this same pattern with action servers for actuation.
- **Agency management:** For Phase 13, agency is trivial (timer fires, report runs, no decisions). Future phases should consider: permission scoping per agent, action approval workflows, rollback capabilities. Capture as deferred architecture concern.

</specifics>

<deferred>
## Deferred Ideas

- **Agent decision/action loop** — Future phases (rover, multi-chamber orchestration) will need the agent to make decisions and trigger actuators. The `execute_report()` callback is where this pattern evolves. Not in Phase 13 scope.
- **Direct ROS2 topic subscription** — The agent could subscribe to sensor topics directly instead of querying TimescaleDB. Useful for real-time observations in future, but overkill for a daily summary that benefits from DB aggregation.
- **Multi-agent coordination** — When multiple agents exist (report agent, rover agent, chamber agents), they'll need coordination. ROS2 namespacing and lifecycle management handle this, but orchestration protocol is future work.
- **Agency governance** — Permission model for what each agent can observe vs act on. Trivial now (report agent is read-only) but critical for rover.

</deferred>

---

*Phase: 13-farmos-daily-report*
*Context gathered: 2026-04-13 via smart discuss*
