# Phase 7: Historical Data Storage & OpenMCT Time-Series Visualization - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire up the existing TimescaleDB container to ingest ROS telemetry from the bridge service and serve historical data to OpenMCT. When complete, users can view past sensor/actuator readings as time-series charts in the browser — not just live data.

No new sensors, no new control logic, no new ROS nodes.

</domain>

<decisions>
## Implementation Decisions

### Data Ingestion Pipeline
- **D-01:** Bridge service (Node.js) writes telemetry to TimescaleDB — no new containers or ROS nodes. Bridge already subscribes to all ROS topics and sits on `frontend-net` with TimescaleDB.
- **D-02:** Use `pg` (node-postgres) as the DB client — lightweight, no ORM, direct INSERT statements.
- **D-03:** Immediate insert on each ROS message callback — no batching. At ~2 writes/sec across 4 topics, this is trivial for Postgres.

### OpenMCT History Provider
- **D-04:** Add REST endpoints to the bridge (Express routes, e.g. `GET /history/:topic?start=&end=`) for historical queries. OpenMCT plugin's `request()` calls these endpoints. Clean separation from WebSocket live data.
- **D-05:** Default time range is last 24 hours when opening a chart. User can zoom in/out from there.
- **D-06:** Server-side downsampling for queries using TimescaleDB `time_bucket()`. Return averaged data per 1min/5min/15min bucket depending on requested range. Keeps charts fast for longer time spans.

### Deployment & Infrastructure
- **D-07:** TimescaleDB runs on elder-plops via Docker (existing docker-compose definition). Pi runs fc-core only, stays lightweight. Bridge on elder-plops subscribes to ROS over WireGuard and writes locally to DB.
- **D-08:** Schema managed by bridge startup init — `CREATE TABLE IF NOT EXISTS` + hypertable setup. No migration tooling for a one-table schema.
- **D-09:** Move DB password from hardcoded `mysecretpassword` in docker-compose to `.env` file. Bridge reads from env vars too.

### Data Scope & Granularity
- **D-10:** Store all 4 current topics: humidity, temperature, CO2, humidifier state. Full picture of the chamber.
- **D-11:** Store every reading at full ~2s resolution. Raw data preserved for spike/event analysis.
- **D-12:** Keep all data indefinitely — no retention policy for now. At ~600MB/year for 4 topics, storage is negligible on elder-plops. Revisit downsampled retention in a few years.

### Claude's Discretion
- Table schema design (column types, indexes, hypertable chunk interval)
- Express route structure and query parameter validation
- Downsampling bucket thresholds (which bucket size at which time range)
- OpenMCT plugin `request()` implementation details
- Error handling for DB connection loss (bridge should continue live WebSocket even if DB is down)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Bridge & Frontend (modify these)
- `src/mission-control/bridge/src/index.js` — Bridge service: add pg client, DB writes on each ROS subscription callback, Express REST routes for history queries
- `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` — OpenMCT plugin: wire `request()` to call bridge REST endpoint, currently returns empty array (line 207)

### Infrastructure (modify these)
- `src/docker-compose.yml` — TimescaleDB service already defined (line 82-87), bridge already depends on it; move credentials to .env

### Configuration
- `src/chambers/fc-core/config/fc_config.yaml` — Current sensor intervals and topic names

### Prior Phase Context
- `.planning/phases/04-observability-integration/04-CONTEXT.md` — OpenMCT integration decisions, SENSORS array pattern, topic structure
- `.planning/phases/06-wireguard-vpn-routing-for-ros-traffic/06-CONTEXT.md` — WireGuard VPN setup enabling cross-machine ROS topic access

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `plugin.js` SENSORS array — declarative sensor definitions with `identifier`, `topic`, `msgType`, `extract()`. History provider just needs to match these keys.
- `plugin.js` `request()` method — already stubbed, returns `Promise.resolve([])`. Ready to wire up to REST endpoint.
- `plugin.js` `getTimestamp()` — extracts ROS header timestamps, reusable for aligning DB timestamps.
- `index.js` bridge — already has ROS subscription pattern for humidity/temperature. Same callbacks can add DB insert.

### Established Patterns
- Bridge broadcasts JSON `{value, timestamp}` — same shape should be returned by history endpoint for consistency.
- SENSORS array uses `fruiting-chamber` namespace with dot-separated keys (`fc.humidity`, `fc.temperature`, `fc.co2`, `fc.humidifier`).
- ROS topics follow `fc1/{sensor_type}` naming (namespaced for multi-chamber).

### Integration Points
- Bridge ROS callbacks → add `INSERT INTO telemetry` alongside existing `broadcast(data)`
- Bridge HTTP server (new Express app on same port or new port) → serves `/history/:topic` queries
- Plugin `request()` → fetch from bridge REST endpoint, return array of `{value, utc}` datums
- docker-compose `bridge` service → already has `depends_on: timescale`, just needs env vars for connection

</code_context>

<specifics>
## Specific Ideas

- User wants full fidelity storage — keep every 2s reading, downsample only on query
- Storage is not a concern on elder-plops — keep everything forever for now
- The system should tolerate DB downtime gracefully — live WebSocket data should keep working even if TimescaleDB is down

</specifics>

<deferred>
## Deferred Ideas

- **Downsampled retention policy** — Revisit in a few years when raw data accumulates. Use TimescaleDB continuous aggregates + retention policy to keep 15-min averages after raw data ages out.
- **Multi-chamber schema** — Current schema is fc1-only. When FC-2 comes, add chamber_id column or separate hypertables.
- **Alerting on historical trends** — e.g., "humidity hasn't recovered in 2 hours". Separate phase.
- **Data export/backup** — pg_dump scheduling for TimescaleDB. Not needed yet at this scale.

</deferred>

---

*Phase: 07-historical-data-storage-and-openmct-time-series-visualizatio*
*Context gathered: 2026-04-05*
