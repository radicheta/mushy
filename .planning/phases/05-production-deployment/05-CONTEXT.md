# Phase 5: Production Deployment - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Deploy the completed humidity control system to FC-1 at the farm. Validate stability over a 24-hour soak test. Document operations for grower handoff. Declare "better than timer."

No new control logic, no new sensors, no new OpenMCT features. Deploy, validate, document.

</domain>

<decisions>
## Implementation Decisions

### Humidity target tuning
- **D-01:** Default target humidity set to 0.80 (80%) in `fc_config.yaml`. Tolerance stays at 0.05 (5%), giving a 75-85% operational band.
- **D-02:** Configuration changes happen via `fc_config.yaml` + `deploy.sh` redeploy. No runtime config UI for MVP.
- **D-03:** Min dwell time stays at 300s (5 minutes). Proven safe in Phase 3 testing.

### Soak test criteria
- **D-04:** Soak test duration: 24 hours continuous operation on FC-1 at the farm. Full day/night cycle covers lighting transitions and temperature swings.
- **D-05:** Stability definition: systemd auto-restart (`Restart=on-failure`) counts as stable. If the service restarts and keeps working, the test passes. Log any restarts for review.
- **D-06:** Soak test is gated by physical Pi relocation from lab to farm (04-HUMAN-UAT.md pending item).

### Grower observability
- **D-07:** Day-to-day monitoring via OpenMCT dashboard over WireGuard VPN. Browser → Pi IP:8080. Already functional from Phase 4 + Phase 6.
- **D-08:** No alerts for MVP. Alert/notification system is a future phase capability.

### Operations documentation
- **D-09:** Two formats: README/OPERATIONS.md in repo (for developers) + printable 1-page checklist (for grower near the chamber).
- **D-10:** Doc covers: hardware requirements (Pi 4, SHT30, SSR-10A, GPIO pins), recovery steps (power check, SSH, service restart, redeploy), configuration guide (edit config + deploy.sh), known limitations (single chamber, no alerts, no remote config UI, GPIO library deprecation path).

### Claude's Discretion
- Exact layout and formatting of the operations documents
- Whether to include a system architecture diagram in the docs
- How to structure the printable checklist for maximum clarity
- Soak test monitoring approach (manual log checks vs automated verification script)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Deploy Infrastructure
- `scripts/pi-deploy/deploy.sh` — Production deploy pipeline: rsync + colcon build + systemd restart
- `scripts/pi-deploy/fc-core.service` — systemd unit file with ROS2 env, CycloneDDS, Restart=on-failure
- `scripts/pi-deploy/cyclonedds.xml` — CycloneDDS unicast config for WireGuard mesh

### Configuration
- `src/chambers/fc-core/config/fc_config.yaml` — All runtime parameters; target_humidity needs updating to 0.80

### Phase 4 Pending Items
- `.planning/phases/04-observability-integration/04-HUMAN-UAT.md` — Soak test and OpenMCT validation still pending

### Requirements
- `DEPL-01` — System runs stably on Pi, suitable for grower handoff, better than timer

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `deploy.sh` — Complete deploy pipeline, no changes needed for production use
- `fc-core.service` — Production-ready systemd unit with auto-restart, CycloneDDS, environment vars
- OpenMCT dashboard — Live charts for humidity, temp, CO2, humidifier state already working

### Established Patterns
- Config-driven operation via `fc_config.yaml` — all parameters tunable without code changes
- Deploy pattern: edit locally → `./scripts/pi-deploy/deploy.sh` → auto-builds on Pi → service restarts
- systemd journal for all logging (`journalctl -u fc-core`)

### Integration Points
- Pi must be physically relocated to farm and connected to power, humidifier, and network
- WireGuard VPN must be active for remote monitoring (Phase 6 already configured)
- OpenMCT docker-compose must be running on workstation for dashboard access

</code_context>

<specifics>
## Specific Ideas

- User wants target humidity configurable from mission control in the future — captured as deferred idea
- Default 80% chosen as a safe starting point; grower can tune up based on species and chamber conditions
- "Better than timer" means: humidity stays in range more consistently, system reacts to actual conditions instead of fixed schedule

</specifics>

<deferred>
## Deferred Ideas

- **OpenMCT command channel** — Bidirectional control from dashboard (set target humidity, dwell time, etc. from browser). Requires new bridge capability. Future phase.
- **Alert/notification system** — Email or push notifications when humidity drops critically. New infrastructure needed. Future phase.
- **TimescaleDB telemetry storage** — Historical data retention for trend analysis. Docker service defined but not wired. Future phase.
- **Multi-chamber support** — FC-2 integration, per-chamber config profiles. Out of MVP scope.

</deferred>

---

*Phase: 05-production-deployment*
*Context gathered: 2026-04-04*
