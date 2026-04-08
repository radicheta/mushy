# Phase 8: FarmOS Integration - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Deploy FarmOS with the farm_fungi module on elder-plops, configure assets and taxonomies for mushroom production tracking, and document the grower workflow. Manual event logging via FarmOS web UI — no custom code bridging ROS to FarmOS in this phase.

No sensor telemetry push, no control plane integration, no automated logging.

</domain>

<decisions>
## Implementation Decisions

### Scope & Data Flow Direction
- **D-01:** FarmOS is for production management — tracking batches, lifecycle events, harvest records. Sensor telemetry stays in TimescaleDB/OpenMCT (Phase 7). No duplication.
- **D-02:** One-way data flow: manual entry into FarmOS via its web UI. FarmOS does not feed back into the Pi/ROS control system. `fc_config.yaml` remains the source of truth for setpoints.

### FarmOS Deployment
- **D-03:** Self-hosted Docker on elder-plops. Add FarmOS (Drupal + PostgreSQL) containers to docker-compose alongside existing services.
- **D-04:** Separate PostgreSQL container for FarmOS — isolated from TimescaleDB. Independent backup, upgrade, and lifecycle.
- **D-05:** Accessible via elder-plops IP on LAN (e.g., port 8082). Same access pattern as OpenMCT on 8080. Reachable from any device on LAN or over WireGuard.

### Integration Method
- **D-06:** All production events entered directly in FarmOS web UI — mobile-friendly forms, taxonomy autocomplete, date pickers. No custom CLI or ROS bridge for this phase.
- **D-07:** Install `farm_fungi` module for the `fungi` asset type with species and substrate taxonomy fields.
- **D-08:** OAuth2 API credentials configured (for future automation phases) but not actively used yet.

### Asset & Log Modeling
- **D-09:** One fungi asset per bag/block — individual container tracking, not batch-level. Allows per-bag yield and contamination tracking.
- **D-10:** Four lifecycle events logged per bag/block:
  - **Inoculation** — species, substrate, date, source culture (`seeding` or `activity` log type)
  - **Colonization check** — progress observations, contamination notes (`observation` log type)
  - **Fruiting initiated** — bag enters fruiting chamber, location reference (`activity` log type)
  - **Harvest** — weight, flush number, quality notes (`harvest` log type with quantity)
- **D-11:** FC-1 modeled as a FarmOS location asset (`structure` type). Fruiting activity logs reference FC-1 as location — enables "what's in the chamber right now" queries.

### Claude's Discretion
- FarmOS Docker image version and Drupal configuration
- Specific FarmOS module set beyond farm_fungi (farm_quick, farm_api, etc.)
- Taxonomy term seeding (initial species/substrate entries)
- Docker networking between FarmOS and existing services
- Reverse proxy setup (if needed alongside OpenMCT)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### FarmOS Resources
- https://www.drupal.org/project/farm_fungi — farm_fungi module: adds `fungi` asset type with `fungi_type` and `substrate_type` taxonomy fields
- https://farmos.org/development/api/ — FarmOS JSON:API documentation, OAuth2 auth, log/asset CRUD

### Infrastructure
- `src/docker-compose.yml` — existing Docker services; FarmOS containers to be added here
- `.env` — credentials file (Phase 7 moves DB passwords here; FarmOS credentials follow same pattern)

### Prior Phase Context
- `.planning/phases/07-historical-data-storage-and-openmct-time-series-visualizatio/07-CONTEXT.md` — TimescaleDB/OpenMCT decisions; sensor telemetry stays there, not in FarmOS

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `docker-compose.yml` — established pattern for adding services with networks, volumes, depends_on
- `.env` pattern (from Phase 7) — credentials externalized, reusable for FarmOS DB password and admin credentials

### Established Patterns
- Services on `frontend-net` for web-facing apps (OpenMCT on 8080, bridge on 8081)
- Volume-backed persistent storage (`timescale-data` pattern)
- WireGuard VPN for remote access to LAN services

### Integration Points
- FarmOS web UI exposed on a new port (e.g., 8082) on `frontend-net`
- FarmOS PostgreSQL on `frontend-net` (internal only, not port-mapped)
- No code integration with ROS or bridge in this phase

</code_context>

<specifics>
## Specific Ideas

- User envisions future automation: roving robots logging observations to FarmOS, Pi camera pushing hourly images as observation logs
- The `farmOS.py` or `farmOS.js` client libraries exist for when automated logging is needed
- FarmOS API uses JSON:API with OAuth2 — API credentials should be set up now even if not used yet

</specifics>

<deferred>
## Deferred Ideas

- **Automated sensor telemetry to FarmOS** — Push hourly/daily aggregated readings as observation logs. Needs `farmOS.py` bridge. Future phase.
- **Pi camera image observations** — Hourly snapshots pushed to FarmOS as observation logs with image attachments. Needs camera setup + API bridge.
- **Roving robot observations** — Mobile robots logging visual observations to FarmOS via API. Needs robot platform + farmOS.py integration.
- **Grow recipe pull from FarmOS** — Define setpoints in FarmOS, Pi pulls them. Tight coupling, significant complexity. Only if FarmOS becomes the primary control plane.
- **Multi-chamber location hierarchy** — When FC-2 arrives, add it as another structure asset under a parent "Farm" location.
- **Harvest analytics** — Yield-per-bag reports, species comparison, substrate performance. FarmOS has some reporting; may need custom views.

</deferred>

---

*Phase: 08-farmos-integration*
*Context gathered: 2026-04-05*
